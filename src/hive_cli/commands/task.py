"""Task command - manage agent tasks."""

from __future__ import annotations

from typing import Annotated

from cyclopts import App, Parameter

from ..config import get_runtime_settings
from ..git import get_main_repo
from ..services import editors, tasks
from ..ui import board
from ..ui.console import out, success, warn
from ..ui.views import tasks as task_views


def show_all_tasks() -> None:
    """Display all agent tasks."""
    out.print(task_views.build_all_tasks(tasks.collect_all(get_main_repo())))


def watch_all_tasks(interval: float = 5.0) -> None:
    """Live board of all tasks, repainted only when a task file changes."""
    main_repo = get_main_repo()
    board.watch(
        lambda: tasks.collect_all(main_repo),
        task_views.build_all_tasks,
        interval=interval,
    )


def show_task(agent_id: str) -> None:
    """Display task for a specific agent.

    Args:
        agent_id: Agent identifier.
    """
    out.print(task_views.build_task(tasks.read_task(get_main_repo(), agent_id)))


def set_task(agent_id: str, task_content: str) -> None:
    """Set task for an agent.

    Args:
        agent_id: Agent identifier.
        task_content: Task description.
    """
    tasks.write_task(get_main_repo(), agent_id, task_content)
    success(f"Task set for Agent {agent_id}")


def edit_task(agent_id: str) -> None:
    """Edit task in $EDITOR.

    Args:
        agent_id: Agent identifier.
    """
    task_file = tasks.ensure_task_template(get_main_repo(), agent_id)
    editor = get_runtime_settings().editor
    editors.edit_in_terminal_editor(editor, task_file)


def clear_task(agent_id: str) -> None:
    """Clear task for an agent.

    Args:
        agent_id: Agent identifier.
    """
    if tasks.delete_task(get_main_repo(), agent_id):
        success(f"Task cleared for Agent {agent_id}")
    else:
        warn(f"No task to clear for Agent {agent_id}")


# Cyclopts App

task_app = App(
    name="task",
    help="Manage agent tasks.",
)


@task_app.default
def task_default(
    watch: Annotated[
        bool,
        Parameter(
            name=["--watch", "-w"],
            help="Live board, repainted only when a task changes. q quits.",
        ),
    ] = False,
    interval: Annotated[
        float,
        Parameter(name="--interval", help="Seconds between refreshes in watch mode."),
    ] = 5.0,
):
    """Show all tasks.

    Examples:
        hive task                 # Show all tasks
        hive task --watch         # Live board (q quits)
        hive task 2               # Show task for agent 2
        hive task 2 "Fix the bug" # Set task for agent 2
        hive task edit 2          # Edit task in $EDITOR
        hive task clear 2         # Clear task
    """
    if watch:
        watch_all_tasks(interval=interval)
    else:
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
