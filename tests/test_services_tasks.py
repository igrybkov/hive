"""Tests for services/tasks.py.

Moved from commands/task.py (A0 step 6): get_tasks_dir/get_task_file/
ensure_tasks_dir are direct moves (dropping their leading underscore now
that they're cross-module service functions); write_task/
ensure_task_template/delete_task are new names for the non-printing
halves of set_task/edit_task/clear_task. The CLI-level behavior these
back is already covered end-to-end in test_cli_task.py.
"""

from __future__ import annotations

from hive_cli.services.tasks import (
    delete_task,
    ensure_task_template,
    ensure_tasks_dir,
    get_task_file,
    get_tasks_dir,
    write_task,
)


class TestPaths:
    def test_get_tasks_dir(self, tmp_path):
        assert (
            get_tasks_dir(tmp_path) == tmp_path / ".claude" / "local-agents" / "tasks"
        )

    def test_get_task_file(self, tmp_path):
        assert get_task_file(tmp_path, "2") == get_tasks_dir(tmp_path) / "agent-2.md"

    def test_ensure_tasks_dir_creates_and_returns_dir(self, tmp_path):
        result = ensure_tasks_dir(tmp_path)
        assert result == get_tasks_dir(tmp_path)
        assert result.is_dir()


class TestWriteTask:
    def test_write_task_creates_dir_and_file(self, tmp_path):
        task_file = write_task(tmp_path, "2", "Implement auth")
        assert task_file == get_task_file(tmp_path, "2")
        content = task_file.read_text()
        assert "# Agent 2 Task" in content
        assert "Implement auth" in content
        assert "*Assigned:" in content

    def test_write_task_overwrites_existing(self, tmp_path):
        write_task(tmp_path, "3", "First")
        task_file = write_task(tmp_path, "3", "Second")
        content = task_file.read_text()
        assert "Second" in content
        assert "First" not in content


class TestEnsureTaskTemplate:
    def test_seeds_template_when_missing(self, tmp_path):
        task_file = ensure_task_template(tmp_path, "2")
        content = task_file.read_text()
        assert "# Agent 2 Task" in content
        assert "[Describe the task here]" in content
        assert "Acceptance Criteria" in content

    def test_leaves_existing_content_untouched(self, tmp_path):
        write_task(tmp_path, "4", "Existing content")
        task_file = ensure_task_template(tmp_path, "4")
        content = task_file.read_text()
        assert "Existing content" in content
        assert "[Describe the task here]" not in content


class TestDeleteTask:
    def test_deletes_existing_and_reports_missing(self, tmp_path):
        write_task(tmp_path, "5", "Something")
        assert delete_task(tmp_path, "5") is True
        assert not get_task_file(tmp_path, "5").exists()
        assert delete_task(tmp_path, "5") is False


class TestCollectAll:
    def test_agent_one_only_when_nothing_is_set(self, temp_git_repo):
        from hive_cli.services.tasks import TaskEntry, collect_all

        assert collect_all(temp_git_repo) == [TaskEntry("1", None)]

    def test_worktrees_then_stray_files(
        self, temp_git_repo, isolated_worktrees, make_worktree
    ):
        from hive_cli.services.tasks import collect_all, read_task, write_task

        make_worktree("feat")
        write_task(temp_git_repo, "1", "main task")
        write_task(temp_git_repo, "orphan", "orphan task")
        tasks_dir = temp_git_repo / ".claude" / "local-agents" / "tasks"
        (tasks_dir / "weird.md").write_text("# stray\nweird task\n")

        entries = collect_all(temp_git_repo)

        assert [(e.agent_id, e.no_worktree) for e in entries] == [
            ("1", False),
            ("feat", False),
            ("orphan", True),
            ("weird", True),
        ]
        assert "main task" in (entries[0].content or "")
        assert entries[1].content is None
        assert entries[3].content == "# stray\nweird task\n"
        assert read_task(temp_git_repo, "feat").content is None
