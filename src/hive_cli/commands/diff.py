"""Diff command - show unified diff of all agent worktrees against main branch."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Annotated

from cyclopts import App, Parameter
from rich.console import Console

from ..git import (
    get_current_branch,
    get_default_branch,
    get_main_repo,
    list_worktrees,
)

# Console for output
console = Console()


def _has_delta() -> bool:
    """Check if delta pager is available."""
    return shutil.which("delta") is not None


def _get_diff(
    path: Path,
    default_branch: str,
    stat: bool = False,
    files_only: bool = False,
) -> str:
    """Get diff for a worktree.

    Args:
        path: Path to worktree.
        default_branch: Default branch to diff against.
        stat: If True, show diffstat.
        files_only: If True, show only changed file names.

    Returns:
        Diff output string.
    """
    cmd = ["git", "-C", str(path), "diff"]

    if files_only:
        cmd.append("--name-only")
    elif stat:
        cmd.append("--stat")

    cmd.append(default_branch)

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return result.stdout
    except subprocess.CalledProcessError:
        return ""


def _show_diff_with_delta(path: Path, default_branch: str) -> bool:
    """Show diff using delta pager.

    Args:
        path: Path to worktree.
        default_branch: Default branch to diff against.

    Returns:
        True if diff was shown.
    """
    try:
        git_proc = subprocess.Popen(
            ["git", "-C", str(path), "diff", default_branch],
            stdout=subprocess.PIPE,
        )
        delta_proc = subprocess.Popen(
            ["delta"],
            stdin=git_proc.stdout,
        )
        git_proc.stdout.close()
        delta_proc.communicate()
        return True
    except subprocess.CalledProcessError:
        return False


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

    console.print()
    console.print("[cyan]" + "═" * 55 + "[/]")

    if is_main:
        console.print(f"[bold magenta]Agent 1 (main)[/] - [green]{branch}[/]")
    else:
        console.print(f"[bold magenta]Agent {agent_id}[/] - [green]{branch}[/]")

    console.print("[cyan]" + "═" * 55 + "[/]")

    if files_only or stat:
        diff_output = _get_diff(path, default_branch, stat=stat, files_only=files_only)
        if diff_output:
            console.print(diff_output)
        else:
            console.print("  [dim](no changes)[/]")
    else:
        # Use delta if available
        if _has_delta():
            if not _show_diff_with_delta(path, default_branch):
                console.print("  [dim](no changes)[/]")
        else:
            diff_output = _get_diff(path, default_branch)
            if diff_output:
                console.print(diff_output)
            else:
                console.print("  [dim](no changes)[/]")


def show_diff(stat: bool = False, files_only: bool = False) -> None:
    """Show unified diff of all agent worktrees.

    Args:
        stat: If True, show diffstat instead of full diff.
        files_only: If True, show only changed file names.
    """
    main_repo = get_main_repo()
    default_branch = get_default_branch(main_repo)

    console.print(f"[bold cyan]Agent Diff View - comparing against {default_branch}[/]")

    worktrees = list_worktrees(main_repo)

    for wt in worktrees:
        # For main repo, check if there are changes
        if wt.is_main:
            changes = _get_diff(wt.path, default_branch, files_only=True)
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

    console.print()


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
