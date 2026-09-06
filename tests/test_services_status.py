"""Tests for services/status.py: status collection, no printing."""

from __future__ import annotations

from pathlib import Path

from hive_cli.services.status import _get_task, collect_status, get_shared_notes_summary


class TestGetTask:
    def test_first_non_header_line_truncated_to_sixty(self, temp_git_repo: Path):
        assert _get_task(temp_git_repo, "feat") is None  # no task file yet
        tasks_dir = temp_git_repo / ".claude" / "local-agents" / "tasks"
        tasks_dir.mkdir(parents=True)
        (tasks_dir / "agent-feat.md").write_text("# Header\n\n" + "z" * 100 + "\n")
        assert _get_task(temp_git_repo, "feat") == ("z" * 100)[:60]

    def test_main_agent_uses_agent_1_filename(self, temp_git_repo: Path):
        # main worktree's agent_id is "1", so its file is agent-1.md.
        tasks_dir = temp_git_repo / ".claude" / "local-agents" / "tasks"
        tasks_dir.mkdir(parents=True)
        (tasks_dir / "agent-1.md").write_text("main repo task\n")
        assert _get_task(temp_git_repo, "1") == "main repo task"
        assert _get_task(temp_git_repo, "main") is None


class TestGetSharedNotesSummary:
    def test_missing_shared_notes_file(self, temp_git_repo: Path):
        assert get_shared_notes_summary(temp_git_repo) == (0, None)

    def test_lines_and_header(self, temp_git_repo: Path):
        notes_dir = temp_git_repo / ".claude" / "local-agents"
        notes_dir.mkdir(parents=True)
        (notes_dir / "shared-notes.md").write_text(
            "## First\nbody\n\n## Second\nmore\n"
        )
        assert get_shared_notes_summary(temp_git_repo) == (5, "Second")

    def test_no_headers(self, temp_git_repo: Path):
        notes_dir = temp_git_repo / ".claude" / "local-agents"
        notes_dir.mkdir(parents=True)
        (notes_dir / "shared-notes.md").write_text("just text\nno headers\n")
        assert get_shared_notes_summary(temp_git_repo) == (2, None)


class TestCollectStatus:
    def test_main_only_repo_has_single_entry(self, temp_git_repo: Path):
        # Regression guard: a path-resolution mismatch in list_worktrees'
        # main-vs-porcelain dedupe would make main appear twice.
        statuses = collect_status(temp_git_repo)
        assert len(statuses) == 1
        assert statuses[0].is_main is True
        assert statuses[0].agent_id == "1"

    def test_worktree_dirty_and_task_are_reflected(
        self, temp_git_repo: Path, isolated_worktrees, make_worktree
    ):
        wt_path = make_worktree("feat")
        (wt_path / "scratch.txt").write_text("dirty")
        tasks_dir = temp_git_repo / ".claude" / "local-agents" / "tasks"
        tasks_dir.mkdir(parents=True)
        (tasks_dir / "agent-feat.md").write_text("the assigned task\n")

        by_branch = {s.branch: s for s in collect_status(temp_git_repo)}
        assert set(by_branch) == {"main", "feat"}
        assert by_branch["feat"].is_dirty is True
        assert by_branch["feat"].is_main is False
        assert by_branch["feat"].task == "the assigned task"


WORKTREE_LIST = """\
worktree {main}
HEAD 1111111111111111111111111111111111111111
branch refs/heads/main

worktree {main}-feat-a
HEAD 2222222222222222222222222222222222222222
branch refs/heads/feat-a

worktree {main}-feat-b
HEAD 3333333333333333333333333333333333333333
branch refs/heads/feat-b

"""


class TestCollectStatusSpawnBudget:
    def test_one_list_plus_two_per_worktree(self, fake_proc, tmp_path):
        main = tmp_path / "repo"
        main.mkdir()
        fake_proc.script(
            ("git", "worktree", "list"), stdout=WORKTREE_LIST.format(main=main)
        )
        fake_proc.script(
            ("git", "status"), stdout="# branch.head feat\n# branch.ab +1 -0\n? x\n"
        )
        fake_proc.script(("git", "log"), stdout="abc\x00msg\x00now\n")

        statuses = collect_status(main)

        assert [s.branch for s in statuses] == ["feat", "feat-a", "feat-b"]
        assert len(fake_proc.calls) <= 1 + 2 * 3
        assert all(s.is_dirty and s.ahead == 1 for s in statuses)
        assert statuses[0].is_main and statuses[0].agent_id == "1"

    def test_main_branch_falls_back_when_detached(self, fake_proc, tmp_path):
        fake_proc.script(("git", "status"), stdout="# branch.head (detached)\n")
        statuses = collect_status(tmp_path)
        assert statuses[0].branch == "main"
