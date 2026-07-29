"""Merge-preview command - preview potential merge conflicts between agent branches."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Annotated

from cyclopts import App, Parameter
from rich.console import Console

from ..git import (
    get_current_branch,
    get_default_branch,
    get_main_repo,
    get_worktree_path,
    list_worktrees,
)
from ..utils import error

# Console for output
console = Console()


def _get_changed_files(path: Path, default_branch: str) -> list[str]:
    """Get files changed compared to default branch.

    Args:
        path: Path to worktree.
        default_branch: Default branch name.

    Returns:
        List of changed file names.
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(path), "diff", "--name-only", default_branch],
            capture_output=True,
            text=True,
            check=True,
        )
        return [f for f in result.stdout.strip().splitlines() if f]
    except subprocess.CalledProcessError:
        return []


def _show_file_overlap(main_repo: Path) -> None:
    """Show files modified by multiple agents.

    Args:
        main_repo: Path to main repository.
    """
    default_branch = get_default_branch(main_repo)

    console.print("[bold cyan]" + "═" * 55 + "[/]")
    console.print("[bold cyan]  File Overlap Analysis[/]")
    console.print("[bold cyan]" + "═" * 55 + "[/]")
    console.print()

    # Collect changed files per agent
    file_agents: dict[str, list[str]] = defaultdict(list)

    worktrees = list_worktrees(main_repo)
    for wt in worktrees:
        agent_id = "1" if wt.is_main else wt.branch
        files = _get_changed_files(wt.path, default_branch)
        for f in files:
            file_agents[f].append(agent_id)

    # Find overlaps
    has_overlap = False
    console.print("[yellow]Files modified by multiple agents:[/]")
    console.print()

    for file_path, agents in sorted(file_agents.items()):
        if len(agents) > 1:
            has_overlap = True
            console.print(f"  [red]{file_path}[/]")
            console.print(f"    [dim]Modified by agents: {' '.join(agents)}[/]")

    if not has_overlap:
        console.print(
            "  [green]No overlapping files - agents are working on separate areas[/]"
        )

    console.print()
    console.print(
        "[dim]Tip: Run 'hive merge-preview <agent-id>' to simulate a specific merge[/]"
    )


def _preview_agent_merge(agent_id: str, main_repo: Path) -> bool:
    """Preview merge for a specific agent.

    Args:
        agent_id: Agent identifier.
        main_repo: Path to main repository.

    Returns:
        True if merge would succeed.
    """
    if agent_id == "1":
        path = main_repo
    else:
        path = get_worktree_path(f"agent-{agent_id}", main_repo)

    if not path.exists():
        error(f"Agent {agent_id} worktree not found")
        return False

    branch = get_current_branch(path) or "detached"
    default_branch = get_default_branch(main_repo)

    console.print("[bold cyan]" + "═" * 55 + "[/]")
    console.print(f"[bold cyan]  Merge Preview: {branch} → {default_branch}[/]")
    console.print("[bold cyan]" + "═" * 55 + "[/]")
    console.print()

    # Get branch commit
    try:
        result = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        branch_commit = result.stdout.strip()
    except subprocess.CalledProcessError:
        error("Failed to get branch commit")
        return False

    # Create temp directory for safe merge test
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)

        # Clone to temp dir
        console.print("[cyan]Attempting merge simulation...[/]")
        console.print()

        try:
            subprocess.run(
                ["git", "clone", "--quiet", "--shared", str(main_repo), str(temp_path)],
                check=True,
                capture_output=True,
            )
        except subprocess.CalledProcessError:
            error("Failed to create test environment")
            return False

        # Checkout default branch
        try:
            subprocess.run(
                ["git", "-C", str(temp_path), "checkout", "--quiet", default_branch],
                check=True,
                capture_output=True,
            )
        except subprocess.CalledProcessError:
            error(f"Failed to checkout {default_branch}")
            return False

        # Try to merge
        merge_result = subprocess.run(
            [
                "git",
                "-C",
                str(temp_path),
                "merge",
                "--no-commit",
                "--no-ff",
                branch_commit,
            ],
            capture_output=True,
        )

        if merge_result.returncode == 0:
            console.print("[green]✓ Merge would succeed without conflicts[/]")
            console.print()
            console.print("[dim]Files that would be changed:[/]")

            # Show changed files
            result = subprocess.run(
                ["git", "-C", str(temp_path), "diff", "--cached", "--name-status"],
                capture_output=True,
                text=True,
            )

            for line in result.stdout.strip().splitlines():
                if not line:
                    continue
                parts = line.split("\t", 1)
                if len(parts) == 2:
                    status, file_path = parts
                    if status == "A":
                        console.print(f"  [green]+ {file_path}[/]")
                    elif status == "M":
                        console.print(f"  [yellow]~ {file_path}[/]")
                    elif status == "D":
                        console.print(f"  [red]- {file_path}[/]")
                    else:
                        console.print(f"  {status} {file_path}")

            # Abort merge
            subprocess.run(
                ["git", "-C", str(temp_path), "merge", "--abort"],
                capture_output=True,
            )
            return True
        else:
            console.print("[red]✗ Merge would have conflicts[/]")
            console.print()
            console.print("[bold]Conflicting files:[/]")

            # Show conflicting files
            result = subprocess.run(
                ["git", "-C", str(temp_path), "diff", "--name-only", "--diff-filter=U"],
                capture_output=True,
                text=True,
            )

            for line in result.stdout.strip().splitlines():
                if line:
                    console.print(f"  [red]! {line}[/]")

            # Abort merge
            subprocess.run(
                ["git", "-C", str(temp_path), "merge", "--abort"],
                capture_output=True,
            )
            return False


# Cyclopts App

merge_preview_app = App(
    name="merge-preview",
    help="Preview potential merge conflicts between agent branches.",
)


@merge_preview_app.default
def merge_preview(
    agent_id: Annotated[
        str | None,
        Parameter(help="Agent identifier to preview merge for."),
    ] = None,
):
    """Preview potential merge conflicts between agent branches.

    Without arguments, shows file overlap between all agents.
    With an agent ID, simulates merging that agent's branch into default branch.

    Examples:
        hive merge-preview      # Show file overlap
        hive merge-preview 2    # Simulate merge for agent 2
    """
    main_repo = get_main_repo()

    if agent_id:
        success = _preview_agent_merge(agent_id, main_repo)
        if not success:
            sys.exit(1)
    else:
        _show_file_overlap(main_repo)
