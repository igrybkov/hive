"""FuzzyItem builders for the worktree/branch picker.

Split out of ui/pickers/worktrees.py (A0 wt.py pass) to keep that module
under the 600-line cap, per A0-architecture.md's own suggested split for
this file. `_build_fuzzy_items_fast`/`_build_fuzzy_items` were pre-existing
complexipy violations (cognitive complexity > 15); split by pure extraction
(helpers with the same locals as parameters, no logic change) in the same
move that relocated them here.

The `ACTION_*` sentinels live here (not in worktrees.py) so this module has
no dependency on worktrees.py -- worktrees.py imports them (and the two
builders, and `_slow_worktree_item` for its own background refresh) from
here instead, keeping the dependency one-directional.
"""

from __future__ import annotations

from pathlib import Path

from ...git import (
    GitHubIssue,
    fetch_issues,
    get_all_branches,
    get_current_branch,
    get_issues_cache_path,
    is_worktree_dirty,
    list_worktrees,
    load_cached_issues,
)
from ..flows import worktrees as flows
from .fuzzy import FuzzyItem

# Special sentinels for actions that need to run outside the fuzzy finder
ACTION_NEW_BRANCH = "__new_branch__"
ACTION_DELETE_PREFIX = "__delete__:"
ACTION_OPEN_IN_EDITOR_PREFIX = "__open_in_editor__:"
ACTION_ISSUE_PREFIX = "__issue__:"
ACTION_CHANGE_AGENT = "__change_agent__"
ACTION_TOGGLE_SKIP_PERMISSIONS = "__toggle_skip_permissions__"
ACTION_CHANGE_WORKDIR = "__change_workdir__"
ACTION_CHANGE_PROFILE = "__change_profile__"


def _issue_fuzzy_item(
    issue: GitHubIssue, existing_branches: set[str]
) -> FuzzyItem | None:
    """Build a FuzzyItem for a GitHub issue, or None if a branch for it already exists.

    Shared by the fast (cached) and slow (live-fetched) item builders below,
    and by pick_worktree's background issue refresh -- the three copies of
    this logic were byte-for-byte identical duplicates, not divergent flows.
    """
    issue_prefix = f"gh-{issue.number}-"
    has_existing_branch = any(
        b.startswith(issue_prefix) or b == f"gh-issue-{issue.number}"
        for b in existing_branches
    )
    if has_existing_branch:
        return None
    title = issue.title[:50] + "..." if len(issue.title) > 50 else issue.title
    value = f"{ACTION_ISSUE_PREFIX}{issue.number}:{issue.title}"
    return FuzzyItem(
        text=f"{flows.ISSUE_EMOJI} #{issue.number}: {title}",
        value=value,
        meta="",
        style="cyan",
    )


def _is_initial_selection(wt, select_branch: str | None) -> bool:
    """Whether `wt` is the one to pre-select in the picker."""
    if wt.is_main:
        return select_branch in ("main", "1")
    return wt.branch == select_branch


def _fast_worktree_item(
    wt, current_main_branch: str | None, current_worktree_branch: str | None
) -> tuple[FuzzyItem, str | None]:
    """Build a FuzzyItem for one worktree in the fast (no dirty-check) list.

    Returns (item, extra_excluded_branch): extra_excluded_branch is the
    current_main_branch when it should also be excluded from the plain
    branch list (main repo checked out to a non-main/master branch).
    """
    if wt.is_main:
        if current_main_branch and current_main_branch not in ("main", "master"):
            return (
                FuzzyItem(
                    text="main",
                    value=wt.branch,
                    meta=f"[repo @ {current_main_branch}]",
                    style="bold green",
                ),
                current_main_branch,
            )
        return (
            FuzzyItem(text="main", value=wt.branch, meta="[repo]", style="bold green"),
            None,
        )

    is_current = wt.branch == current_worktree_branch
    meta = "← current" if is_current else ""
    return FuzzyItem(text=wt.branch, value=wt.branch, meta=meta, style="green"), None


def _append_fast_worktree_items(
    items: list[FuzzyItem],
    worktree_branches: set[str],
    worktrees,
    current_main_branch: str | None,
    current_worktree_branch: str | None,
    select_branch: str | None,
) -> int:
    """Append fast (no dirty-check) worktree items to `items` in place.

    Returns the initial_selection index if a worktree matched select_branch,
    else -1 (caller keeps its previous value).
    """
    initial_selection = -1
    for wt in worktrees:
        worktree_branches.add(wt.branch)
        item, extra_excluded = _fast_worktree_item(
            wt, current_main_branch, current_worktree_branch
        )
        if extra_excluded:
            worktree_branches.add(extra_excluded)
        if _is_initial_selection(wt, select_branch):
            initial_selection = len(items)
        items.append(item)
    return initial_selection


def _build_fuzzy_items_fast(
    main_repo: Path,
    current_worktree_branch: str | None = None,
    preselect_branch: str | None = None,
) -> tuple[list[FuzzyItem], int]:
    """Build list of items quickly.

    Skips slow operations like dirty checks and remote branches.

    Args:
        main_repo: Path to the main repository.
        current_worktree_branch: Branch of current worktree (if in one).
        preselect_branch: Branch to pre-select (overrides current_worktree_branch).

    Returns:
        Tuple of (list of FuzzyItem, initial selection index).
    """
    items: list[FuzzyItem] = []
    worktree_branches: set[str] = set()
    initial_selection = 0

    # Use preselect_branch if provided, otherwise fall back to current_worktree_branch
    select_branch = preselect_branch or current_worktree_branch

    # Get current branch of main repo - can't create worktree for it
    current_main_branch = get_current_branch(main_repo)

    # Get worktrees first (they show at top) - fast operation
    worktrees = list_worktrees(main_repo)
    selected_idx = _append_fast_worktree_items(
        items,
        worktree_branches,
        worktrees,
        current_main_branch,
        current_worktree_branch,
        select_branch,
    )
    if selected_idx >= 0:
        initial_selection = selected_idx

    # Get all branches (local + remote from existing refs)
    # This is fast, no fetch needed! Remote branches are already stored locally
    all_branches = get_all_branches(main_repo)
    for branch in all_branches:
        if branch not in worktree_branches:
            if branch == select_branch:
                initial_selection = len(items)
            items.append(FuzzyItem(text=branch, value=branch, meta="", style="dim"))

    # Load cached GitHub issues immediately (fast, no API call needed)
    cache_path = get_issues_cache_path(main_repo)
    cached_issues = load_cached_issues(cache_path)
    existing_branches = worktree_branches | set(all_branches)
    for issue in cached_issues:
        item = _issue_fuzzy_item(issue, existing_branches)
        if item:
            items.append(item)

    return items, initial_selection


def _slow_worktree_item(
    wt, current_main_branch: str | None, current_worktree_branch: str | None
) -> tuple[FuzzyItem, str | None]:
    """Build a FuzzyItem for one worktree, with a real dirty check.

    Returns (item, extra_excluded_branch), same shape as _fast_worktree_item.
    """
    is_dirty = False if wt.is_main else is_worktree_dirty(wt.path)

    if wt.is_main:
        if current_main_branch and current_main_branch not in ("main", "master"):
            return (
                FuzzyItem(
                    text="main",
                    value=wt.branch,
                    meta=f"[repo @ {current_main_branch}]",
                    style="bold green",
                ),
                current_main_branch,
            )
        return (
            FuzzyItem(text="main", value=wt.branch, meta="[repo]", style="bold green"),
            None,
        )

    is_current = wt.branch == current_worktree_branch
    if is_current:
        meta = "← current" + (" (dirty)" if is_dirty else "")
    else:
        meta = "(dirty)" if is_dirty else ""
    style = "yellow" if is_dirty else "green"
    return FuzzyItem(text=wt.branch, value=wt.branch, meta=meta, style=style), None


def _append_slow_worktree_items(
    items: list[FuzzyItem],
    worktree_branches: set[str],
    worktrees,
    current_main_branch: str | None,
    current_worktree_branch: str | None,
    select_branch: str | None,
) -> int:
    """Append dirty-checked worktree items to `items` in place.

    Returns the initial_selection index if a worktree matched select_branch,
    else -1 (caller keeps its previous value).
    """
    initial_selection = -1
    for wt in worktrees:
        worktree_branches.add(wt.branch)
        item, extra_excluded = _slow_worktree_item(
            wt, current_main_branch, current_worktree_branch
        )
        if extra_excluded:
            worktree_branches.add(extra_excluded)
        if _is_initial_selection(wt, select_branch):
            initial_selection = len(items)
        items.append(item)
    return initial_selection


def _build_fuzzy_items(
    main_repo: Path,
    current_worktree_branch: str | None = None,
    preselect_branch: str | None = None,
) -> tuple[list[FuzzyItem], int]:
    """Build list of items for fuzzy selection.

    Args:
        main_repo: Path to the main repository.
        current_worktree_branch: Branch of current worktree (if in one).
        preselect_branch: Branch to pre-select (overrides current_worktree_branch).

    Returns:
        Tuple of (list of FuzzyItem, initial selection index).
    """
    items: list[FuzzyItem] = []
    worktree_branches: set[str] = set()
    initial_selection = 0

    # Use preselect_branch if provided, otherwise fall back to current_worktree_branch
    select_branch = preselect_branch or current_worktree_branch

    # Get current branch of main repo - can't create worktree for it
    current_main_branch = get_current_branch(main_repo)

    # Get worktrees first (they show at top)
    worktrees = list_worktrees(main_repo)
    selected_idx = _append_slow_worktree_items(
        items,
        worktree_branches,
        worktrees,
        current_main_branch,
        current_worktree_branch,
        select_branch,
    )
    if selected_idx >= 0:
        initial_selection = selected_idx

    # Get all branches and add those without worktrees
    all_branches = get_all_branches(main_repo)
    for branch in all_branches:
        if branch not in worktree_branches:
            if branch == select_branch:
                initial_selection = len(items)
            items.append(FuzzyItem(text=branch, value=branch, meta="", style="dim"))

    # Fetch GitHub issues assigned to user and add them
    # Issues are shown after branches with emoji prefix
    github_issues = fetch_issues(main_repo)
    if github_issues is not None:
        existing_branches = worktree_branches | set(all_branches)
        for issue in github_issues:
            item = _issue_fuzzy_item(issue, existing_branches)
            if item:
                items.append(item)

    return items, initial_selection
