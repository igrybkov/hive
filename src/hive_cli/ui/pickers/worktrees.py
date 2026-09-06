"""Interactive worktree/branch picker for agent workflows (`hive wt cd`/`ensure`).

`pick_worktree` paints the picker from `worktree_items.first_paint` (one
spawn) and hands `fuzzy_select` two refiners that run off the event loop:
`refine_git` (throttled `git fetch`, per-worktree summaries, the branch
list) and `refine_issues` (cached GitHub issues). Each returns the full item
list for the picker to merge in place, or None for "no change", and stops as
soon as its `cancel` event is set.

Moved from commands/wt.py (A0 wt.py pass): `pick_worktree` is the old
`_interactive_ensure`, split by pure extraction into the helpers below.
"""

from __future__ import annotations

import functools
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
    get_all_branches,
    get_current_worktree_branch,
    get_default_branch,
    get_main_repo,
    get_worktree_path,
    is_worktree_dirty,
)
from ...services import editors, facts
from ..console import error, info, warn
from ..flows import worktrees as flows
from .agents import select_agent
from .editors import select_editor
from .fuzzy import FuzzyItem, fuzzy_select
from .profiles import select_profile
from .workdir import WORKDIR_CLEAR, select_workdir
from .worktree_items import (
    ACTION_CHANGE_AGENT,
    ACTION_CHANGE_PROFILE,
    ACTION_CHANGE_WORKDIR,
    ACTION_DELETE_PREFIX,
    ACTION_ISSUE_PREFIX,
    ACTION_NEW_BRANCH,
    ACTION_OPEN_IN_EDITOR_PREFIX,
    ACTION_TOGGLE_SKIP_PERMISSIONS,
    PickerItems,
    first_paint,
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
    "refine_git",
    "refine_issues",
]


def refine_git(
    main_repo: Path, sections: PickerItems, cancel: threading.Event
) -> list[FuzzyItem] | None:
    """Fetch (throttled), summarise every worktree, list branches; recompose."""
    facts.fetch_if_stale(main_repo, get_settings().worktrees.fetch_interval)
    if cancel.is_set():
        return None
    sections.summaries = facts.summaries(sections.worktrees, cancel=cancel)
    if cancel.is_set():
        return None
    sections.branches = get_all_branches(main_repo)
    return sections.compose()[0]


def refine_issues(
    main_repo: Path, sections: PickerItems, cancel: threading.Event
) -> list[FuzzyItem] | None:
    """Add GitHub issues (cached, refreshed when stale); None keeps the list."""
    found = facts.issues(main_repo)
    if found is None or cancel.is_set():
        return None
    sections.issues = found
    return sections.compose()[0]


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

    editors.open_in_editor(worktree_path, editor, progress=info)
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
        # One spawn, then the refiners fill in summaries, branches and issues.
        sections, items, initial_selection = first_paint(
            main_repo, current_worktree_branch, state.preselect_branch
        )
        refiners = (
            functools.partial(refine_git, main_repo, sections),
            functools.partial(refine_issues, main_repo, sections),
        )

        skip_perms_indicator = "ON" if state.skip_permissions else "OFF"
        selected = fuzzy_select(
            items=items,
            prompt_text=">",
            header=_build_header(agent_num, state, rt),
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
            refiners=refiners,
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
