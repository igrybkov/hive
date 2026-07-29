"""Rebase-check command - check if agent worktrees need rebasing."""

from __future__ import annotations

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
from ..utils import info

# Console for output
console = Console()


def _fetch_origin(main_repo: Path, default_branch: str) -> bool:
    """Fetch from origin.

    Args:
        main_repo: Path to main repository.
        default_branch: Default branch name.

    Returns:
        True if fetch succeeded.
    """
    try:
        subprocess.run(
            ["git", "-C", str(main_repo), "fetch", "origin", default_branch, "--quiet"],
            capture_output=True,
            check=True,
        )
        return True
    except subprocess.CalledProcessError:
        return False


def _get_commits_ahead_behind(path: Path, default_branch: str) -> tuple[int, int]:
    """Get commits ahead/behind origin/default_branch.

    Args:
        path: Path to worktree.
        default_branch: Default branch name.

    Returns:
        Tuple of (ahead, behind) counts.
    """
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(path),
                "rev-list",
                "--count",
                f"HEAD..origin/{default_branch}",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        behind = int(result.stdout.strip())
    except (subprocess.CalledProcessError, ValueError):
        behind = 0

    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(path),
                "rev-list",
                "--count",
                f"origin/{default_branch}..HEAD",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        ahead = int(result.stdout.strip())
    except (subprocess.CalledProcessError, ValueError):
        ahead = 0

    return ahead, behind


def _get_changed_files(path: Path, default_branch: str, limit: int = 5) -> list[str]:
    """Get changed files that may conflict.

    Args:
        path: Path to worktree.
        default_branch: Default branch name.
        limit: Maximum number of files to return.

    Returns:
        List of changed file names.
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(path), "diff", "--name-only", f"origin/{default_branch}"],
            capture_output=True,
            text=True,
            check=True,
        )
        files = result.stdout.strip().splitlines()
        return files[:limit]
    except subprocess.CalledProcessError:
        return []


def _check_worktree(
    agent_id: str,
    path: Path,
    default_branch: str,
    is_main: bool,
) -> None:
    """Check rebase status for a single worktree.

    Args:
        agent_id: Agent identifier.
        path: Path to worktree.
        default_branch: Default branch name.
        is_main: Whether this is the main repo.
    """
    branch = get_current_branch(path) or "detached"

    # Don't check default branch against itself
    if branch == default_branch:
        return

    ahead, behind = _get_commits_ahead_behind(path, default_branch)

    # Determine status
    if behind == 0:
        status_icon = "[green]✓[/]"
        status_msg = "[green]up to date[/]"
    elif behind < 5:
        status_icon = "[yellow]![/]"
        status_msg = f"[yellow]{behind} commits behind[/]"
    else:
        status_icon = "[red]✗[/]"
        status_msg = f"[red]{behind} commits behind - rebase recommended[/]"

    ahead_msg = f" [dim]({ahead} ahead)[/]" if ahead > 0 else ""

    # Agent label
    if is_main:
        label = "[bold cyan]Agent 1 (main)[/]"
    else:
        label = f"[bold magenta]Agent {agent_id}[/]"

    console.print(f"{status_icon} {label} [dim]({branch})[/]")
    console.print(f"    {status_msg}{ahead_msg}")

    # Show potential conflicts if behind
    if behind > 0:
        files = _get_changed_files(path, default_branch)
        if files:
            console.print("    [dim]Changed files that may conflict:[/]")
            for f in files:
                console.print(f"    [dim]  - {f}[/]")

    console.print()


def check_rebase(fetch: bool = False) -> None:
    """Check if agent worktrees need rebasing.

    Args:
        fetch: If True, fetch from origin first.
    """
    main_repo = get_main_repo()
    default_branch = get_default_branch(main_repo)

    if fetch:
        info("Fetching from origin...")
        _fetch_origin(main_repo, default_branch)
        console.print()

    console.print("[bold cyan]" + "═" * 55 + "[/]")
    console.print(f"[bold cyan]  Rebase Check - against origin/{default_branch}[/]")
    console.print("[bold cyan]" + "═" * 55 + "[/]")
    console.print()

    worktrees = list_worktrees(main_repo)

    for wt in worktrees:
        _check_worktree(
            agent_id=wt.branch if not wt.is_main else "main",
            path=wt.path,
            default_branch=default_branch,
            is_main=wt.is_main,
        )

    console.print("[dim]Tip: Run with --fetch to update remote tracking first[/]")


# Cyclopts App

rebase_check_app = App(
    name="rebase-check",
    help="Check if agent worktrees need rebasing against default branch.",
)


@rebase_check_app.default
def rebase_check_cmd(
    fetch: Annotated[
        bool,
        Parameter(
            name=["--fetch", "-f"],
            help="Fetch from origin before checking.",
        ),
    ] = False,
):
    """Check if agent worktrees need rebasing against default branch.

    Shows how many commits each worktree is behind the default branch
    and highlights potential conflict files.

    Examples:
        hive rebase-check           # Check rebase status
        hive rebase-check --fetch   # Fetch first, then check
    """
    check_rebase(fetch=fetch)
