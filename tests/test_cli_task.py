"""Integration tests for the ``hive task`` command group."""

from __future__ import annotations

import io
import stat
from pathlib import Path

import pytest
from conftest import CycloptsTestRunner
from rich.console import Console

from hive_cli.app import app

# ---------------------------------------------------------------------------
# Local helpers / fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def editor_script(tmp_path: Path) -> Path:
    """A fake $EDITOR that appends a marker line to the file it's given."""
    script = tmp_path / "fake-editor.sh"
    script.write_text('#!/bin/sh\necho "EDITED-BY-TEST" >> "$1"\n')
    script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return script


def use_editor(monkeypatch: pytest.MonkeyPatch, script: Path) -> None:
    """Point $EDITOR at ``script`` and force RuntimeSettings to re-read it."""
    monkeypatch.setenv("EDITOR", str(script))
    import hive_cli.config.runtime as runtime_mod

    runtime_mod._runtime_settings = None


class TestTaskHelp:
    def test_help_lists_subcommands(self, cli_runner: CycloptsTestRunner):
        result = cli_runner.invoke(app, ["task", "--help"])
        assert result.exit_code == 0
        assert "Manage agent tasks" in result.output
        for cmd in ["show", "set", "edit", "clear"]:
            assert cmd in result.output


class TestTaskDefault:
    def test_default_shows_agent_one_with_no_task(
        self, cli_runner: CycloptsTestRunner, temp_git_repo
    ):
        result = cli_runner.invoke(app, ["task"])
        assert result.exit_code == 0
        assert "Agent Tasks" in result.output
        assert "Agent 1 (main)" in result.output
        assert "No task assigned" in result.output

    def test_default_shows_worktree_agents(
        self,
        cli_runner: CycloptsTestRunner,
        temp_git_repo,
        isolated_worktrees,
        make_worktree,
    ):
        make_worktree("feat")
        result = cli_runner.invoke(app, ["task"])
        assert result.exit_code == 0
        assert "Agent 1 (main)" in result.output
        assert "Agent feat" in result.output

    def test_default_shows_task_content_for_agent_one(
        self, cli_runner: CycloptsTestRunner, temp_git_repo
    ):
        result = cli_runner.invoke(app, ["task", "set", "1", "Fix", "the", "bug"])
        assert result.exit_code == 0

        result = cli_runner.invoke(app, ["task"])
        assert result.exit_code == 0
        assert "Agent 1 (main)" in result.output
        assert "Fix the bug" in result.output

    def test_default_shows_agent_without_worktree(
        self, cli_runner: CycloptsTestRunner, temp_git_repo
    ):
        result = cli_runner.invoke(app, ["task", "set", "orphan", "Do", "something"])
        assert result.exit_code == 0

        result = cli_runner.invoke(app, ["task"])
        assert result.exit_code == 0
        assert "orphan" in result.output
        assert "(no worktree)" in result.output
        assert "Do something" in result.output

    def test_default_shows_stray_task_file_without_agent_prefix(
        self, cli_runner: CycloptsTestRunner, temp_git_repo
    ):
        # _get_task_file() always names files "agent-{id}.md", but
        # show_all_tasks() also globs for any *.md file, so a manually
        # dropped file without that prefix is shown using its bare stem.
        tasks_dir = temp_git_repo / ".claude" / "local-agents" / "tasks"
        tasks_dir.mkdir(parents=True)
        (tasks_dir / "weird.md").write_text("# stray task\nDo the weird thing\n")

        result = cli_runner.invoke(app, ["task"])
        assert result.exit_code == 0
        assert "weird" in result.output
        assert "(no worktree)" in result.output
        assert "Do the weird thing" in result.output


class TestTaskShow:
    def test_show_no_agent_shows_all(
        self, cli_runner: CycloptsTestRunner, temp_git_repo
    ):
        result = cli_runner.invoke(app, ["task", "show"])
        assert result.exit_code == 0
        assert "Agent Tasks" in result.output
        assert "Agent 1 (main)" in result.output

    def test_show_agent_one(self, cli_runner: CycloptsTestRunner, temp_git_repo):
        result = cli_runner.invoke(app, ["task", "show", "1"])
        assert result.exit_code == 0
        assert "Agent 1 (main)" in result.output
        assert "No task assigned" in result.output
        # Only shows agent 1's section, not the full "Agent Tasks" listing.
        assert "Agent Tasks" not in result.output

    def test_show_specific_agent_with_no_worktree_label_absent(
        self, cli_runner: CycloptsTestRunner, temp_git_repo
    ):
        # show_task() never passes no_worktree=True, unlike show_all_tasks().
        result = cli_runner.invoke(app, ["task", "show", "nonexistent"])
        assert result.exit_code == 0
        assert "Agent nonexistent" in result.output
        assert "(no worktree)" not in result.output
        assert "No task assigned" in result.output

    def test_show_agent_with_content(
        self, cli_runner: CycloptsTestRunner, temp_git_repo
    ):
        result = cli_runner.invoke(app, ["task", "set", "2", "Implement", "auth"])
        assert result.exit_code == 0

        result = cli_runner.invoke(app, ["task", "show", "2"])
        assert result.exit_code == 0
        assert "Agent 2" in result.output
        assert "Implement auth" in result.output


class TestTaskSet:
    def test_set_writes_task_file(self, cli_runner: CycloptsTestRunner, temp_git_repo):
        result = cli_runner.invoke(
            app, ["task", "set", "2", "Implement", "user", "authentication"]
        )
        assert result.exit_code == 0
        assert "Task set for Agent 2" in result.output

        task_file = temp_git_repo / ".claude" / "local-agents" / "tasks" / "agent-2.md"
        content = task_file.read_text()
        assert "# Agent 2 Task" in content
        assert "Implement user authentication" in content
        assert "*Assigned:" in content

    def test_set_overwrites_previous_task(
        self, cli_runner: CycloptsTestRunner, temp_git_repo
    ):
        result = cli_runner.invoke(app, ["task", "set", "3", "First", "task"])
        assert result.exit_code == 0
        result = cli_runner.invoke(app, ["task", "set", "3", "Second", "task"])
        assert result.exit_code == 0

        task_file = temp_git_repo / ".claude" / "local-agents" / "tasks" / "agent-3.md"
        content = task_file.read_text()
        assert "Second task" in content
        assert "First task" not in content

    def test_set_for_agent_one(self, cli_runner: CycloptsTestRunner, temp_git_repo):
        result = cli_runner.invoke(app, ["task", "set", "1", "Review", "PRs"])
        assert result.exit_code == 0
        assert "Task set for Agent 1" in result.output


class TestTaskEdit:
    def test_edit_creates_template_when_missing(
        self, cli_runner: CycloptsTestRunner, temp_git_repo, editor_script, monkeypatch
    ):
        use_editor(monkeypatch, editor_script)
        result = cli_runner.invoke(app, ["task", "edit", "2"])
        assert result.exit_code == 0

        task_file = temp_git_repo / ".claude" / "local-agents" / "tasks" / "agent-2.md"
        content = task_file.read_text()
        assert "# Agent 2 Task" in content
        assert "[Describe the task here]" in content
        assert "Acceptance Criteria" in content
        assert "- [ ] Criterion 1" in content
        assert "EDITED-BY-TEST" in content

    def test_edit_does_not_recreate_template_when_task_exists(
        self, cli_runner: CycloptsTestRunner, temp_git_repo, editor_script, monkeypatch
    ):
        result = cli_runner.invoke(
            app, ["task", "set", "4", "Existing", "task", "content"]
        )
        assert result.exit_code == 0

        use_editor(monkeypatch, editor_script)
        result = cli_runner.invoke(app, ["task", "edit", "4"])
        assert result.exit_code == 0

        task_file = temp_git_repo / ".claude" / "local-agents" / "tasks" / "agent-4.md"
        content = task_file.read_text()
        assert "Existing task content" in content
        assert "[Describe the task here]" not in content
        assert "EDITED-BY-TEST" in content


class TestTaskClear:
    def test_clear_existing_task(self, cli_runner: CycloptsTestRunner, temp_git_repo):
        result = cli_runner.invoke(app, ["task", "set", "5", "Something", "to", "do"])
        assert result.exit_code == 0

        result = cli_runner.invoke(app, ["task", "clear", "5"])
        assert result.exit_code == 0
        assert "Task cleared for Agent 5" in result.output

        task_file = temp_git_repo / ".claude" / "local-agents" / "tasks" / "agent-5.md"
        assert not task_file.exists()

    def test_clear_no_task_warns(self, cli_runner: CycloptsTestRunner, temp_git_repo):
        result = cli_runner.invoke(app, ["task", "clear", "6"])
        assert result.exit_code == 0
        assert "No task to clear for Agent 6" in result.output


class TestTaskWatch:
    def test_watch_hands_the_listing_to_the_live_board(
        self, cli_runner: CycloptsTestRunner, temp_git_repo, mocker
    ):
        cli_runner.invoke(app, ["task", "set", "1", "Watch", "me"])
        frames: list[str] = []

        def fake_watch(collect, render, **kwargs):
            buf = io.StringIO()
            Console(file=buf, width=100).print(render(collect()))
            frames.append(buf.getvalue())
            assert kwargs["interval"] == 7
            return "q", None

        mocker.patch("hive_cli.ui.board.watch", side_effect=fake_watch)

        result = cli_runner.invoke(app, ["task", "--watch", "--interval", "7"])

        assert result.exit_code == 0
        assert "Agent Tasks" in frames[0] and "Watch me" in frames[0]
