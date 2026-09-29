"""Rich renderables for `hive task`: pure data -> Group, no printing."""

from __future__ import annotations

from rich.console import Group
from rich.text import Text

from ...services.tasks import TaskEntry

_RULE = Text.from_markup("[dim]" + "─" * 41 + "[/]")


def build_task(entry: TaskEntry) -> Group:
    """One agent's block: label, then the task text (or "No task assigned")."""
    if entry.agent_id == "1":
        label = "[bold cyan]Agent 1 (main)[/]"
    elif entry.no_worktree:
        label = f"[bold yellow]{entry.agent_id}[/] [dim](no worktree)[/]"
    else:
        label = f"[bold magenta]Agent {entry.agent_id}[/]"
    parts: list = [Text.from_markup(label)]
    if entry.content is not None:
        parts.extend([_RULE, Text(entry.content), _RULE])
    else:
        parts.append(Text.from_markup("  [dim]No task assigned[/]"))
    parts.append(Text(""))
    return Group(*parts)


def build_all_tasks(entries: list[TaskEntry]) -> Group:
    """The full `hive task` listing with its header."""
    rule = Text.from_markup("[bold cyan]" + "═" * 55 + "[/]")
    header = [rule, Text.from_markup("[bold cyan]  Agent Tasks[/]"), rule, Text("")]
    return Group(*header, *(build_task(entry) for entry in entries))
