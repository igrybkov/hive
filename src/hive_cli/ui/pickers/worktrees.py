"""Interactive worktree/branch picker for agent workflows (`hive wt cd`/`ensure`).

Moved from commands/wt.py (A0 wt.py pass): `pick_worktree` is the old
`_interactive_ensure`, a pre-existing complexipy violation (cognitive
complexity > 15) split by pure extraction (helpers with the same locals as
parameters, no logic change) in this same move. The FuzzyItem builders it
uses live in ./worktree_items.py (split out to keep this module under the
600-line cap, per A0-architecture.md's own suggested split for this file).

`_refresh_dirty_status`'s worktree-item loop near-duplicates
worktree_items.py's `_build_fuzzy_items` (both compute dirty status per
worktree), but it serves a different call site (a background re-render vs.
the initial full build) and doesn't track `initial_selection` -- kept
separate rather than unified, matching the same "don't unify near-duplicates
with different call-sites" rule applied to the two `_delete_worktree_flow`
copies.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path

from ...agents import detect_agent
from ...config import (
    RuntimeSettings,
    get_agent_order,
    get_runtime_settings,
    get_settings,
)
from ...git import (
    fetch_issues,
    fetch_origin,
    get_all_branches,
    get_current_branch,
    get_current_worktree_branch,
    get_default_branch,
    get_main_repo,
    get_worktree_path,
    is_worktree_dirty,
    list_worktrees,
)
from ...utils import (
    WORKDIR_CLEAR,
    open_in_editor,
    select_agent,
    select_editor,
    select_workdir,
)
from ...utils.profiles import select_profile
from ..console import error, warn
from ..flows import worktrees as flows
from .fuzzy import FuzzyItem, fuzzy_select
from .worktree_items import (
    ACTION_CHANGE_AGENT,
    ACTION_CHANGE_PROFILE,
    ACTION_CHANGE_WORKDIR,
    ACTION_DELETE_PREFIX,
    ACTION_ISSUE_PREFIX,
    ACTION_NEW_BRANCH,
    ACTION_OPEN_IN_EDITOR_PREFIX,
    ACTION_TOGGLE_SKIP_PERMISSIONS,
    _build_fuzzy_items,
    _build_fuzzy_items_fast,
    _slow_worktree_item,
)

__all__ = [
    "ACTION_CHANGE_AGENT",
    "ACTION_CHANGE_PROFILE",
    "ACTION_CHANGE_WORKDIR",
    "ACTION_DELETE_PREFIX",
    "ACTION_ISSUE_PREFIX",
    "ACTION_NEW_BRANCH",
    "ACTION_OPEN_IN_EDITOR_PREFIX",
    "ACTION_TOGGLE_SKIP_PERMISSIONS",
    "pick_worktree",
]


def _refresh_dirty_status(
    main_repo: Path,
    current_worktree_branch: str | None,
    base_header: str,
    update_callbacks: list,
    update_callbacks_ready: threading.Event,
) -> None:
    """Background: fetch origin, then refresh items with real dirty checks."""
    # Wait for update functions to be populated (should be very quick, < 100ms)
    if not update_callbacks_ready.wait(timeout=1.0):
        return  # Update functions not available within 1 second, skip update

    if not update_callbacks:
        return  # Update functions not available, skip update

    update_items, update_header = update_callbacks[0]

    # Start git fetch (this is the slow part, ~3 seconds)
    fetch_origin(main_repo)

    # Remove fetching indicator immediately after fetch completes
    update_header(base_header)

    # Update items with dirty checks
    # Branches already shown, just updating metadata
    # Skip GitHub issues (they're fetched separately)
    items_with_dirty = []
    worktree_branches: set[str] = set()

    # Get worktrees and update dirty status
    worktrees = list_worktrees(main_repo)
    current_main_branch = get_current_branch(main_repo)

    for wt in worktrees:
        worktree_branches.add(wt.branch)
        item, extra_excluded = _slow_worktree_item(
            wt, current_main_branch, current_worktree_branch
        )
        if extra_excluded:
            worktree_branches.add(extra_excluded)
        items_with_dirty.append(item)

    # Add all branches (already shown, but rebuild to match structure)
    all_branches = get_all_branches(main_repo)
    for branch in all_branches:
        if branch not in worktree_branches:
            items_with_dirty.append(
                FuzzyItem(text=branch, value=branch, meta="", style="dim")
            )

    # Update with dirty status (branches stay in place, only metadata changes)
    update_items(items_with_dirty)


def _refresh_github_issues(
    main_repo: Path,
    current_worktree_branch: str | None,
    preselect_branch: str | None,
    base_header: str,
    update_callbacks: list,
    update_callbacks_ready: threading.Event,
) -> None:
    """Fetch GitHub issues independently and update when ready."""
    # Wait for update functions to be populated
    if not update_callbacks_ready.wait(timeout=1.0):
        return

    if not update_callbacks:
        return

    update_items, update_header = update_callbacks[0]

    # Fetch GitHub issues (independent of git fetch - happens in parallel)
    github_issues = fetch_issues(main_repo)
    if github_issues is None:
        # Fetch failed - show error in header (but keep cached issues)
        update_header(f"{base_header} <red>(GitHub issues failed)</red>")
        return

    # Fetch succeeded (may be empty if all issues closed)
    # We need to update the list to remove any stale cached issues
    # Always update to remove stale cached issues (even if there are none)
    # Rebuild to get current state (with dirty checks from fetch thread)
    items_with_issues, _ = _build_fuzzy_items(
        main_repo, current_worktree_branch, preselect_branch
    )
    # Update with issues (update_items merge logic will remove stale items)
    update_items(items_with_issues)


@dataclass
class _PickerState:
    """Mutable picker context threaded through _handle_picker_selection."""

    selected_agent: str
    skip_permissions: bool
    preselect_branch: str | None


def _handle_workdir_change(rt: RuntimeSettings, current_agent: str) -> None:
    """Handle the Ctrl+W "change workdir" action."""
    if not get_settings().extra_dirs:
        warn(
            "No extra_dirs configured — add some to hive.yml or "
            ".hive.local.yml to enable workdir override."
        )
        return

    new_workdir = select_workdir(
        current_agent=current_agent, current_override=rt.workdir
    )
    if new_workdir is WORKDIR_CLEAR:
        rt.workdir = None
        rt.workdir_extras_override = None
    elif new_workdir is not None:
        rt.workdir = new_workdir
        # Clear any stale extras override; computed at launch time.
        rt.workdir_extras_override = None


def _handle_open_in_editor(
    selected: str, main_repo: Path, agent_num: int, state: _PickerState
) -> None:
    """Handle the Shift+Enter "open in editor" action."""
    branch_to_open = selected[len(ACTION_OPEN_IN_EDITOR_PREFIX) :]
    if branch_to_open in ("main", "1"):
        worktree_path = main_repo
    else:
        worktree_path = get_worktree_path(branch_to_open, main_repo)
        if not worktree_path.exists():
            result = flows.create_worktree_flow(branch_to_open, main_repo, agent_num)
            if not result:
                return
            worktree_path = Path(result)

    editor = select_editor()
    if editor is None:
        return

    open_in_editor(worktree_path, editor)
    state.preselect_branch = branch_to_open


def _handle_issue_selection(
    selected: str, main_repo: Path, agent_num: int
) -> tuple[bool, tuple[str, str] | None]:
    """Handle a GitHub-issue item selection."""
    issue_data = selected[len(ACTION_ISSUE_PREFIX) :]
    issue_number_str, issue_title = issue_data.split(":", 1)
    issue_number = int(issue_number_str)
    result = flows.issue_branch_flow(issue_number, issue_title, main_repo, agent_num)
    if result:
        return True, (result, Path(result).name)
    return False, None


def _handle_branch_selection(
    branch: str, main_repo: Path, agent_num: int
) -> tuple[bool, tuple[str, str] | None]:
    """Handle selection of a plain branch/worktree/main entry."""
    if branch in ("main", "1"):
        return True, (str(main_repo), "main")

    path = get_worktree_path(branch, main_repo)
    if path.exists():
        if is_worktree_dirty(path):
            warn(f"⚠ Uncommitted changes in '{branch}'")
        return True, (str(path), branch)

    result = flows.create_worktree_flow(branch, main_repo, agent_num)
    if result:
        return True, (result, branch)
    return False, None


def _handle_context_action(
    selected: str, rt: RuntimeSettings, state: _PickerState
) -> bool:
    """Handle the picker's non-navigational context toggles (agent, skip-
    permissions, profile, workdir). Mutates `rt`/`state` in place.

    Returns:
        True if `selected` was one of these actions (caller should loop
        again), False otherwise.
    """
    if selected == ACTION_CHANGE_AGENT:
        new_agent = select_agent(current_agent=state.selected_agent)
        if new_agent and new_agent != state.selected_agent:
            state.selected_agent = new_agent
            rt.agent = new_agent
            # Profile is agent-scoped; reset it when the agent changes
            rt.agent_profile = None
        return True

    if selected == ACTION_TOGGLE_SKIP_PERMISSIONS:
        state.skip_permissions = not state.skip_permissions
        rt.skip_permissions = state.skip_permissions
        return True

    if selected == ACTION_CHANGE_PROFILE:
        new_profile = select_profile(
            agent_name=state.selected_agent, current_profile=rt.agent_profile
        )
        if new_profile is not None:
            # "" means <default> (passthrough); any other string is a named profile
            rt.agent_profile = new_profile if new_profile else None
        return True

    if selected == ACTION_CHANGE_WORKDIR:
        _handle_workdir_change(rt, state.selected_agent)
        return True

    return False


def _handle_picker_selection(
    selected: str,
    *,
    main_repo: Path,
    agent_num: int,
    rt: RuntimeSettings,
    state: _PickerState,
) -> tuple[bool, tuple[str, str] | None]:
    """Handle one fuzzy_select result from the worktree/branch picker.

    Mutates `state` in place for actions that change picker context (agent,
    skip-permissions, preselect branch); `rt` (runtime settings) is mutated
    directly for agent/profile/skip-permissions/workdir, matching the
    original inline behavior.

    Returns:
        (done, result): when done is True, the picker loop returns `result`
        (a (path, branch) tuple); when False, the picker loops again.
    """
    if selected == ACTION_NEW_BRANCH:
        result = flows.new_branch_flow(main_repo, agent_num)
        if result:
            return True, (result, Path(result).name)
        return False, None

    if _handle_context_action(selected, rt, state):
        return False, None

    if selected.startswith(ACTION_DELETE_PREFIX):
        branch_to_delete = selected[len(ACTION_DELETE_PREFIX) :]
        flows.delete_worktree_flow(branch_to_delete, main_repo)
        return False, None

    if selected.startswith(ACTION_OPEN_IN_EDITOR_PREFIX):
        _handle_open_in_editor(selected, main_repo, agent_num, state)
        return False, None

    if selected.startswith(ACTION_ISSUE_PREFIX):
        return _handle_issue_selection(selected, main_repo, agent_num)

    return _handle_branch_selection(selected, main_repo, agent_num)


def _resolve_auto_select(auto_select_branch: str | None, main_repo: Path) -> str | None:
    """Resolve "-" to the repo's default branch; pass any other value through."""
    if auto_select_branch is None:
        return None
    if auto_select_branch == "-":
        return get_default_branch(main_repo)
    return auto_select_branch


def _build_header(agent_num: int, state: _PickerState, rt: RuntimeSettings) -> str:
    """Build the picker's header text from current agent/skip-perms/workdir/profile."""
    skip_perms_tag = " [skip-perms]" if state.skip_permissions else ""
    workdir_tag = f" [workdir: {rt.workdir}]" if rt.workdir else ""
    profile_tag = f" [profile: {rt.agent_profile}]" if rt.agent_profile else ""
    return (
        f"Agent {agent_num} [{state.selected_agent}]{skip_perms_tag}"
        f"{workdir_tag}{profile_tag}"
        f" - Select worktree or branch"
    )


def _start_background_refreshes(
    main_repo: Path,
    current_worktree_branch: str | None,
    preselect_branch: str | None,
    base_header: str,
) -> tuple[list, threading.Event]:
    """Start the dirty-status and GitHub-issues background refresh threads."""
    update_callbacks: list = []
    update_callbacks_ready = threading.Event()

    fetch_thread = threading.Thread(
        target=_refresh_dirty_status,
        args=(
            main_repo,
            current_worktree_branch,
            base_header,
            update_callbacks,
            update_callbacks_ready,
        ),
        daemon=True,
    )
    fetch_thread.start()

    issues_thread = threading.Thread(
        target=_refresh_github_issues,
        args=(
            main_repo,
            current_worktree_branch,
            preselect_branch,
            base_header,
            update_callbacks,
            update_callbacks_ready,
        ),
        daemon=True,
    )
    issues_thread.start()

    return update_callbacks, update_callbacks_ready


def pick_worktree(
    agent_num: int,
    preselect_branch: str | None = None,
    auto_select_branch: str | None = None,
    auto_select_timeout: float = 3.0,
) -> tuple[str, str] | None:
    """Run the interactive worktree selection with fuzzy finder.

    Args:
        agent_num: Agent number.
        preselect_branch: Branch to pre-select in the picker.
        auto_select_branch: Branch to auto-select after timeout. Use "-"
            for repo's default branch (main/master).
        auto_select_timeout: Seconds before auto-selection (default 3.0).

    Returns:
        Tuple of (path to selected/created worktree, selected branch name),
        or None if cancelled.
    """
    main_repo = get_main_repo()
    resolved_auto_select = _resolve_auto_select(auto_select_branch, main_repo)

    # Get current worktree branch for marking
    current_worktree_branch = get_current_worktree_branch()

    # Detect current agent, respecting HIVE_AGENT env var if set
    rt = get_runtime_settings()
    detected = detect_agent(preferred=rt.agent)
    if not detected:
        agent_list = ", ".join(get_agent_order())
        error(f"Can't find installed agent that matches configuration: {agent_list}")
        return None
    rt.agent = detected.name

    state = _PickerState(
        selected_agent=detected.name,
        skip_permissions=rt.skip_permissions,
        preselect_branch=preselect_branch,
    )

    while True:
        # Build initial items immediately (fast version - skips slow git operations)
        items, initial_selection = _build_fuzzy_items_fast(
            main_repo, current_worktree_branch, state.preselect_branch
        )

        base_header = _build_header(agent_num, state, rt)
        # Start with "Fetching..." indicator
        header_with_indicator = f"{base_header} <dim>(Fetching...)</dim>"

        update_callbacks, update_callbacks_ready = _start_background_refreshes(
            main_repo, current_worktree_branch, state.preselect_branch, base_header
        )

        # Show fuzzy finder immediately with fetching indicator
        # Update functions will be populated in update_callbacks before app.run()
        skip_perms_indicator = "ON" if state.skip_permissions else "OFF"
        selected = fuzzy_select(
            items=items,
            prompt_text=">",
            header=header_with_indicator,
            hint=(
                "</dim><b>↑↓</b><dim> nav  </dim><b>Enter</b><dim> open  "
                "</dim><b>^O</b><dim> editor  </dim><b>^D</b><dim> del  "
                "</dim><b>^A</b><dim> agent  "
                f"</dim><b>^S</b><dim> skip-perms:{skip_perms_indicator}  "
                "</dim><b>^W</b><dim> workdir  "
                "</dim><b>^P</b><dim> profile  "
                "</dim><b>Esc</b><dim> new  "
                "</dim><b>^C</b><dim> quit"
            ),
            initial_selection=initial_selection,
            on_escape=lambda: ACTION_NEW_BRANCH,
            on_tab=lambda branch: f"{ACTION_DELETE_PREFIX}{branch}",
            on_shift_enter=lambda branch: f"{ACTION_OPEN_IN_EDITOR_PREFIX}{branch}",
            on_ctrl_a=lambda: ACTION_CHANGE_AGENT,
            on_ctrl_s=lambda: ACTION_TOGGLE_SKIP_PERMISSIONS,
            on_ctrl_w=lambda: ACTION_CHANGE_WORKDIR,
            on_ctrl_p=lambda: ACTION_CHANGE_PROFILE,
            update_callbacks=update_callbacks,
            update_callbacks_ready=update_callbacks_ready,
            auto_select_value=resolved_auto_select,
            auto_select_timeout=auto_select_timeout,
        )
        # Clear auto-select after first iteration (only auto-select on initial show)
        resolved_auto_select = None

        if selected is None:
            return None

        done, result = _handle_picker_selection(
            selected, main_repo=main_repo, agent_num=agent_num, rt=rt, state=state
        )
        if done:
            return result
