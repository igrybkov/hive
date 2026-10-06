"""Diff command - show unified diff of all agent worktrees against main branch."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from cyclopts import App, Parameter

from ..git import (
    get_current_branch,
    get_default_branch,
    get_diff,
    get_main_repo,
    has_delta,
    list_worktrees,
    show_diff_with_delta,
)
from ..ui.console import out


def _print_worktree_header(agent_id: str, branch: str, is_main: bool) -> None:
    """Print the "Agent N - branch" banner for a worktree's diff section.

    Args:
        agent_id: Agent identifier.
        branch: Current branch name.
        is_main: Whether this is the main repo.
    """
    out.print()
    out.print("[cyan]" + "═" * 55 + "[/]")

    if is_main:
        out.print(f"[bold magenta]Agent 1 (main)[/] - [green]{branch}[/]")
    else:
        out.print(f"[bold magenta]Agent {agent_id}[/] - [green]{branch}[/]")

    out.print("[cyan]" + "═" * 55 + "[/]")


def _print_diff_or_no_changes(diff_output: str) -> None:
    """Print raw diff output, or a "(no changes)" marker if empty.

    Args:
        diff_output: Raw git diff output (never parsed as Rich markup, or
            `list[str]` and `[text](url)` in the diff are silently swallowed).
    """
    if diff_output:
        out.print(diff_output, markup=False)
    else:
        out.print("  [dim](no changes)[/]")


def _print_diff_body(
    path: Path, default_branch: str, stat: bool, files_only: bool
) -> None:
    """Print the diff for a worktree, choosing delta/plain/stat rendering.

    Args:
        path: Path to worktree.
        default_branch: Default branch to diff against.
        stat: If True, show diffstat.
        files_only: If True, show only file names.
    """
    if files_only or stat:
        _print_diff_or_no_changes(
            get_diff(path, default_branch, stat=stat, files_only=files_only)
        )
    elif has_delta():
        if not show_diff_with_delta(path, default_branch):
            out.print("  [dim](no changes)[/]")
    else:
        _print_diff_or_no_changes(get_diff(path, default_branch))


def _show_worktree_diff(
    agent_id: str,
    path: Path,
    default_branch: str,
    is_main: bool,
    stat: bool,
    files_only: bool,
) -> None:
    """Show diff for a single worktree.

    Args:
        agent_id: Agent identifier.
        path: Path to worktree.
        default_branch: Default branch to diff against.
        is_main: Whether this is the main repo.
        stat: If True, show diffstat.
        files_only: If True, show only file names.
    """
    branch = get_current_branch(path) or "detached"
    _print_worktree_header(agent_id, branch, is_main)
    _print_diff_body(path, default_branch, stat, files_only)


def show_diff(stat: bool = False, files_only: bool = False) -> None:
    """Show unified diff of all agent worktrees.

    Args:
        stat: If True, show diffstat instead of full diff.
        files_only: If True, show only changed file names.
    """
    main_repo = get_main_repo()
    default_branch = get_default_branch(main_repo)

    out.print(f"[bold cyan]Agent Diff View - comparing against {default_branch}[/]")

    worktrees = list_worktrees(main_repo)

    for wt in worktrees:
        # For main repo, check if there are changes
        if wt.is_main:
            changes = get_diff(wt.path, default_branch, files_only=True)
            if not changes.strip():
                continue  # Skip main if no changes

        _show_worktree_diff(
            agent_id=wt.branch if not wt.is_main else "1",
            path=wt.path,
            default_branch=default_branch,
            is_main=wt.is_main,
            stat=stat,
            files_only=files_only,
        )

    out.print()


# Cyclopts App

diff_app = App(
    name="diff",
    help="Show unified diff of all agent worktrees against main branch.",
)


@diff_app.default
def diff(
    stat: Annotated[
        bool,
        Parameter(
            name=["--stat", "-s"],
            help="Show diffstat instead of full diff.",
        ),
    ] = False,
    files: Annotated[
        bool,
        Parameter(
            name=["--files", "-f"],
            help="Show only changed file names.",
        ),
    ] = False,
):
    """Show unified diff of all agent worktrees against main branch.

    Uses delta pager if available for syntax-highlighted diffs.

    Examples:
        hive diff           # Full diff view
        hive diff --stat    # Show diffstat only
        hive diff --files   # Show only file names
    """
    show_diff(stat=stat, files_only=files)
