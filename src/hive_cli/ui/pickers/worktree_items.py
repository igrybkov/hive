"""Items for the worktree/branch picker: one cheap first paint, refined later.

`first_paint` costs exactly one spawn (`git worktree list --porcelain`): the
main repo, its worktrees, and nothing else. `PickerItems` keeps the sections
the picker shows; the refiners in ./worktrees.py fill in git summaries
(dirty/ahead/behind), the branch list and GitHub issues, and call
`compose()` to hand the picker a full list each time. Issues are filtered
against every branch known at compose time, so whichever refiner finishes
last still produces a consistent list.

The `ACTION_*` sentinels live here (not in worktrees.py) so this module has
no dependency on worktrees.py, keeping the dependency one-directional.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ...git import GitHubIssue, GitSummary, WorktreeInfo, list_worktrees
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
    """FuzzyItem for a GitHub issue, or None when a branch for it already exists."""
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


def _is_initial_selection(wt: WorktreeInfo, select_branch: str | None) -> bool:
    """Whether `wt` is the one to pre-select in the picker."""
    if wt.is_main:
        return select_branch in ("main", "1")
    return wt.branch == select_branch


def _main_item(wt: WorktreeInfo, current_main_branch: str | None) -> FuzzyItem:
    if current_main_branch and current_main_branch not in ("main", "master"):
        meta = f"[repo @ {current_main_branch}]"
    else:
        meta = "[repo]"
    return FuzzyItem(text="main", value=wt.branch, meta=meta, style="bold green")


def _worktree_item(
    wt: WorktreeInfo, current_worktree_branch: str | None, summary: GitSummary | None
) -> FuzzyItem:
    """One non-main worktree; dirty/ahead/behind appear once a summary exists."""
    meta_parts: list[str] = []
    if wt.branch == current_worktree_branch:
        meta_parts.append("← current")
    is_dirty = summary.dirty if summary else False
    if is_dirty:
        meta_parts.append("(dirty)")
    if summary and summary.ahead:
        meta_parts.append(f"+{summary.ahead}")
    if summary and summary.behind:
        meta_parts.append(f"-{summary.behind}")
    style = "yellow" if is_dirty else "green"
    return FuzzyItem(
        text=wt.branch, value=wt.branch, meta=" ".join(meta_parts), style=style
    )


@dataclass
class PickerItems:
    """The picker's item sections. Refiners replace a section and `compose()`."""

    worktrees: list[WorktreeInfo]
    current_worktree_branch: str | None
    select_branch: str | None
    summaries: dict[Path, GitSummary] = field(default_factory=dict)
    branches: list[str] = field(default_factory=list)
    issues: list[GitHubIssue] = field(default_factory=list)

    @property
    def current_main_branch(self) -> str | None:
        main = next((wt for wt in self.worktrees if wt.is_main), None)
        return (main.head or None) if main else None

    def _worktree_section(self) -> tuple[list[FuzzyItem], set[str], int]:
        items: list[FuzzyItem] = []
        excluded: set[str] = set()
        initial = 0
        for wt in self.worktrees:
            excluded.add(wt.branch)
            if wt.is_main:
                item = _main_item(wt, self.current_main_branch)
                # The main repo's checked-out branch can't get a worktree either.
                if self.current_main_branch not in (None, "main", "master"):
                    excluded.add(str(self.current_main_branch))
            else:
                item = _worktree_item(
                    wt, self.current_worktree_branch, self.summaries.get(wt.path)
                )
            if _is_initial_selection(wt, self.select_branch):
                initial = len(items)
            items.append(item)
        return items, excluded, initial

    def compose(self) -> tuple[list[FuzzyItem], int]:
        """Full item list (worktrees, plain branches, issues) and initial index."""
        items, excluded, initial = self._worktree_section()
        for branch in self.branches:
            if branch in excluded:
                continue
            if branch == self.select_branch:
                initial = len(items)
            items.append(FuzzyItem(text=branch, value=branch, meta="", style="dim"))
        existing = excluded | set(self.branches)
        for issue in self.issues:
            item = _issue_fuzzy_item(issue, existing)
            if item:
                items.append(item)
        return items, initial


def first_paint(
    main_repo: Path,
    current_worktree_branch: str | None = None,
    preselect_branch: str | None = None,
) -> tuple[PickerItems, list[FuzzyItem], int]:
    """Items the picker can show at once: one `git worktree list` spawn.

    Returns the sections (for the refiners to fill in), the items and the
    initial selection index.
    """
    sections = PickerItems(
        worktrees=list_worktrees(main_repo),
        current_worktree_branch=current_worktree_branch,
        select_branch=preselect_branch or current_worktree_branch,
    )
    items, initial = sections.compose()
    return sections, items, initial
