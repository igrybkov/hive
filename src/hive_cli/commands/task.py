"""Task command - manage agent tasks."""

from __future__ import annotations

import subprocess
from datetime import datetime
from pathlib import Path
from typing import Annotated

from cyclopts import App, Parameter
from rich.console import Console

from ..config import get_runtime_settings
from ..git import get_main_repo, list_worktrees
from ..utils import success, warn

# Console for output
console = Console()


def _get_tasks_dir(main_repo: Path) -> Path:
    """Get the tasks directory path.

    Args:
        main_repo: Path to main repository.

    Returns:
        Path to tasks directory.
    """
    return main_repo / ".claude" / "local-agents" / "tasks"


def _get_task_file(main_repo: Path, agent_id: str) -> Path:
    """Get task file path for an agent.

    Args:
        main_repo: Path to main repository.
        agent_id: Agent identifier.

    Returns:
        Path to task file.
    """
    return _get_tasks_dir(main_repo) / f"agent-{agent_id}.md"


def _ensure_tasks_dir(main_repo: Path) -> None:
    """Ensure tasks directory exists.

    Args:
        main_repo: Path to main repository.
    """
    _get_tasks_dir(main_repo).mkdir(parents=True, exist_ok=True)


def _show_task(agent_id: str, task_file: Path, no_worktree: bool = False) -> None:
    """Display task for an agent.

    Args:
        agent_id: Agent identifier.
        task_file: Path to task file.
        no_worktree: Whether agent has no worktree.
    """
    if agent_id == "1":
        console.print("[bold cyan]Agent 1 (main)[/]")
    elif no_worktree:
        console.print(f"[bold yellow]{agent_id}[/] [dim](no worktree)[/]")
    else:
        console.print(f"[bold magenta]Agent {agent_id}[/]")

    if task_file.exists():
        console.print("[dim]" + "─" * 41 + "[/]")
        console.print(task_file.read_text())
        console.print("[dim]" + "─" * 41 + "[/]")
    else:
        console.print("  [dim]No task assigned[/]")

    console.print()


def show_all_tasks() -> None:
    """Display all agent tasks."""
    main_repo = get_main_repo()
    tasks_dir = _get_tasks_dir(main_repo)

    console.print("[bold cyan]" + "═" * 55 + "[/]")
    console.print("[bold cyan]  Agent Tasks[/]")
    console.print("[bold cyan]" + "═" * 55 + "[/]")
    console.print()

    # Track which agents we've shown
    shown_agents: set[str] = set()

    # Show task for Agent 1 (main)
    task_file = _get_task_file(main_repo, "1")
    _show_task("1", task_file)
    shown_agents.add("1")
    shown_agents.add("main")  # Also exclude main

    # Show tasks for worktrees
    worktrees = list_worktrees(main_repo)
    for wt in worktrees:
        if wt.is_main:
            continue
        task_file = _get_task_file(main_repo, wt.branch)
        _show_task(wt.branch, task_file)
        shown_agents.add(wt.branch)

    # Also show tasks for agents without worktrees
    if tasks_dir.exists():
        for task_file in sorted(tasks_dir.glob("*.md")):
            task_name = task_file.stem  # agent-X -> agent-X
            if task_name.startswith("agent-"):
                agent_id = task_name[6:]  # Remove "agent-" prefix
            else:
                agent_id = task_name

            if agent_id not in shown_agents:
                _show_task(agent_id, task_file, no_worktree=True)


def show_task(agent_id: str) -> None:
    """Display task for a specific agent.

    Args:
        agent_id: Agent identifier.
    """
    main_repo = get_main_repo()
    task_file = _get_task_file(main_repo, agent_id)
    _show_task(agent_id, task_file)


def set_task(agent_id: str, task_content: str) -> None:
    """Set task for an agent.

    Args:
        agent_id: Agent identifier.
        task_content: Task description.
    """
    main_repo = get_main_repo()
    _ensure_tasks_dir(main_repo)

    task_file = _get_task_file(main_repo, agent_id)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    content = f"""# Agent {agent_id} Task

{task_content}

---
*Assigned: {timestamp}*
"""
    task_file.write_text(content)
    success(f"Task set for Agent {agent_id}")


def edit_task(agent_id: str) -> None:
    """Edit task in $EDITOR.

    Args:
        agent_id: Agent identifier.
    """
    main_repo = get_main_repo()
    _ensure_tasks_dir(main_repo)

    task_file = _get_task_file(main_repo, agent_id)

    # Create template if doesn't exist
    if not task_file.exists():
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        template = f"""# Agent {agent_id} Task

[Describe the task here]

## Acceptance Criteria

- [ ] Criterion 1
- [ ] Criterion 2

## Notes

---
*Assigned: {timestamp}*
"""
        task_file.write_text(template)

    editor = get_runtime_settings().editor
    subprocess.run([editor, str(task_file)])


def clear_task(agent_id: str) -> None:
    """Clear task for an agent.

    Args:
        agent_id: Agent identifier.
    """
    main_repo = get_main_repo()
    task_file = _get_task_file(main_repo, agent_id)

    if task_file.exists():
        task_file.unlink()
        success(f"Task cleared for Agent {agent_id}")
    else:
        warn(f"No task to clear for Agent {agent_id}")


# Cyclopts App

task_app = App(
    name="task",
    help="Manage agent tasks.",
)


@task_app.default
def task_default():
    """Show all tasks.

    Examples:
        hive task                 # Show all tasks
        hive task 2               # Show task for agent 2
        hive task 2 "Fix the bug" # Set task for agent 2
        hive task edit 2          # Edit task in $EDITOR
        hive task clear 2         # Clear task
    """
    show_all_tasks()


@task_app.command
def show(
    agent_id: Annotated[
        str | None,
        Parameter(help="Agent identifier."),
    ] = None,
):
    """Show task(s).

    If AGENT_ID is specified, shows task for that agent.
    Otherwise, shows all tasks.

    Examples:
        hive task show      # Show all tasks
        hive task show 2    # Show task for agent 2
    """
    if agent_id:
        show_task(agent_id)
    else:
        show_all_tasks()


@task_app.command(name="set")
def set_cmd(
    agent_id: Annotated[str, Parameter(help="Agent identifier.")],
    task_content: Annotated[
        tuple[str, ...],
        Parameter(help="Task description."),
    ],
):
    """Set task for an agent.

    Examples:
        hive task set 2 "Implement user authentication"
        hive task set 3 Fix the login bug and add tests
    """
    set_task(agent_id, " ".join(task_content))


@task_app.command
def edit(
    agent_id: Annotated[str, Parameter(help="Agent identifier.")],
):
    """Edit task in $EDITOR.

    Creates a template if no task exists.

    Examples:
        hive task edit 2
    """
    edit_task(agent_id)


@task_app.command
def clear(
    agent_id: Annotated[str, Parameter(help="Agent identifier.")],
):
    """Clear task for an agent.

    Examples:
        hive task clear 2
    """
    clear_task(agent_id)
