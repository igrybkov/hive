"""ui/views/tasks.py: pure renderables for `hive task`."""

from __future__ import annotations

import io

from rich.console import Console

from hive_cli.services.tasks import TaskEntry
from hive_cli.ui.views import tasks as views


def render(renderable) -> str:
    buf = io.StringIO()
    Console(file=buf, width=100).print(renderable)
    return buf.getvalue()


def test_labels_by_kind():
    assert "Agent 1 (main)" in render(views.build_task(TaskEntry("1", None)))
    assert "Agent feat" in render(views.build_task(TaskEntry("feat", None)))
    stray = render(views.build_task(TaskEntry("weird", "x", no_worktree=True)))
    assert "weird" in stray and "(no worktree)" in stray


def test_content_or_no_task():
    assert "No task assigned" in render(views.build_task(TaskEntry("2", None)))
    text = render(views.build_task(TaskEntry("2", "[Describe the task here]\n")))
    assert "[Describe the task here]" in text and "No task assigned" not in text


def test_all_tasks_has_header_and_every_entry():
    text = render(
        views.build_all_tasks([TaskEntry("1", None), TaskEntry("feat", "do")])
    )
    assert "Agent Tasks" in text and "Agent 1 (main)" in text and "Agent feat" in text
