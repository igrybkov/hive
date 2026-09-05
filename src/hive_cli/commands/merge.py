"""Merge-preview command - preview potential merge conflicts between agent branches."""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path
from typing import Annotated

from cyclopts import App, Parameter

from ..git import (
    MergeSimulation,
    get_current_branch,
    get_default_branch,
    get_main_repo,
    get_worktree_path,
    list_worktrees,
    merge_changed_files,
    simulate_merge,
)
from ..ui.console import error, out


def _show_file_overlap(main_repo: Path) -> None:
    """Show files modified by multiple agents.

    Args:
        main_repo: Path to main repository.
    """
    default_branch = get_default_branch(main_repo)

    out.print("[bold cyan]" + "═" * 55 + "[/]")
    out.print("[bold cyan]  File Overlap Analysis[/]")
    out.print("[bold cyan]" + "═" * 55 + "[/]")
    out.print()

    # Collect changed files per agent
    file_agents: dict[str, list[str]] = defaultdict(list)

    worktrees = list_worktrees(main_repo)
    for wt in worktrees:
        agent_id = "1" if wt.is_main else wt.branch
        files = merge_changed_files(wt.path, default_branch)
        for f in files:
            file_agents[f].append(agent_id)

    # Find overlaps
    has_overlap = False
    out.print("[yellow]Files modified by multiple agents:[/]")
    out.print()

    for file_path, agents in sorted(file_agents.items()):
        if len(agents) > 1:
            has_overlap = True
            out.print(f"  [red]{file_path}[/]")
            out.print(f"    [dim]Modified by agents: {' '.join(agents)}[/]")

    if not has_overlap:
        out.print(
            "  [green]No overlapping files - agents are working on separate areas[/]"
        )

    out.print()
    out.print(
        "[dim]Tip: Run 'hive merge-preview <agent-id>' to simulate a specific merge[/]"
    )


def _print_merge_result(sim: MergeSimulation) -> bool:
    """Print the outcome of a merge simulation.

    Args:
        sim: The MergeSimulation to report.

    Returns:
        True if the merge would succeed without conflicts.
    """
    if sim.conflicts:
        out.print("[red]✗ Merge would have conflicts[/]")
        out.print()
        out.print("[bold]Conflicting files:[/]")
        for f in sim.conflicting_files:
            out.print(f"  [red]! {f}[/]")
        return False

    out.print("[green]✓ Merge would succeed without conflicts[/]")
    out.print()
    out.print("[dim]Files that would be changed:[/]")
    for status, file_path in sim.changed:
        if status == "A":
            out.print(f"  [green]+ {file_path}[/]")
        elif status == "M":
            out.print(f"  [yellow]~ {file_path}[/]")
        elif status == "D":
            out.print(f"  [red]- {file_path}[/]")
        else:
            out.print(f"  {status} {file_path}")
    return True


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

    out.print("[bold cyan]" + "═" * 55 + "[/]")
    out.print(f"[bold cyan]  Merge Preview: {branch} → {default_branch}[/]")
    out.print("[bold cyan]" + "═" * 55 + "[/]")
    out.print()

    sim = simulate_merge(path, main_repo, default_branch, progress=out.print)
    if not sim.ok:
        assert sim.error is not None  # every ok=False construction sets it
        error(sim.error)
        return False

    return _print_merge_result(sim)


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
