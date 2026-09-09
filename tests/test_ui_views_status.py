"""Tests for ui/views/status.py: pure Rich renderables, no printing."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from rich.console import Console, Group

from hive_cli.git.status import CommitInfo, GitStatusDetail
from hive_cli.services.status import AgentStatus
from hive_cli.ui.views.status import (
    build_compact_output,
    build_detail_content,
    build_full_output,
)


def make_status(
    *,
    agent_id: str = "feat",
    path: Path | None = None,
    branch: str = "feat",
    is_main: bool = False,
    is_dirty: bool = False,
    ahead: int = 0,
    behind: int = 0,
    last_commit_hash: str = "abc1234",
    last_commit_msg: str = "do a thing",
    task: str | None = None,
) -> AgentStatus:
    """Build an AgentStatus with sane defaults for renderer tests."""
    return AgentStatus(
        agent_id=agent_id,
        path=path or Path("/tmp/fake-worktree"),
        branch=branch,
        is_main=is_main,
        is_dirty=is_dirty,
        ahead=ahead,
        behind=behind,
        last_commit_hash=last_commit_hash,
        last_commit_msg=last_commit_msg,
        task=task,
    )


def render(renderable: Group) -> str:
    """Render a rich Group to plain text (styles stripped, no tty)."""
    buf = io.StringIO()
    Console(file=buf, width=100).print(renderable)
    return buf.getvalue()


class TestBuildFullOutput:
    @pytest.mark.parametrize(
        ("kwargs", "expected"),
        [
            ({"is_main": True, "branch": "main"}, "Agent 1 (main)"),
            ({"agent_id": "feat"}, "Agent feat"),
        ],
    )
    def test_agent_label(self, tmp_path: Path, kwargs, expected):
        assert expected in render(build_full_output([make_status(**kwargs)], tmp_path))

    def test_dirty_marker_shown_only_when_dirty(self, tmp_path: Path):
        clean = render(build_full_output([make_status(is_dirty=False)], tmp_path))
        dirty = render(build_full_output([make_status(is_dirty=True)], tmp_path))
        assert "*" not in clean and "*" in dirty

    @pytest.mark.parametrize(
        ("ahead", "behind", "plus", "minus"),
        [
            (2, 0, True, False),
            (0, 3, False, True),
            (2, 3, True, True),
            (0, 0, False, False),
        ],
    )
    def test_ahead_behind_markers(self, tmp_path: Path, ahead, behind, plus, minus):
        text = render(
            build_full_output([make_status(ahead=ahead, behind=behind)], tmp_path)
        )
        assert (f"+{ahead}" in text) is plus
        assert (f"-{behind}" in text) is minus

    def test_task_line_shown_only_when_present(self, tmp_path: Path):
        with_task = render(build_full_output([make_status(task="fix it")], tmp_path))
        without_task = render(build_full_output([make_status(task=None)], tmp_path))
        assert "Task:" in with_task and "fix it" in with_task
        assert "Task:" not in without_task

    def test_repo_name_in_header(self, tmp_path: Path):
        text = render(build_full_output([], tmp_path))
        assert tmp_path.name in text
        assert "Agent Status Board" in text

    def test_shared_notes_summary_included_only_when_file_exists(self, tmp_path: Path):
        assert "Shared Notes" not in render(build_full_output([], tmp_path))

        notes = tmp_path / ".claude" / "local-agents"
        notes.mkdir(parents=True)
        content = "intro\n\n## First\nbody\n\n## Latest\nbody\n"
        (notes / "shared-notes.md").write_text(content)
        text = render(build_full_output([], tmp_path))
        assert "Shared Notes" in text
        assert "7 lines" in text
        assert "Latest" in text


class TestBuildCompactOutput:
    def test_single_line_per_agent_with_dirty_and_ahead_behind(self, tmp_path: Path):
        statuses = [
            make_status(is_main=True, branch="main"),
            make_status(
                agent_id="feat", branch="feat", is_dirty=True, ahead=1, behind=2
            ),
        ]
        text = render(build_compact_output(statuses, tmp_path))
        assert "Agents" in text
        assert "main" in text and "feat" in text
        assert "*" in text
        assert "+1" in text and "-2" in text


class TestBuildDetailContent:
    @staticmethod
    def _text(parts: list[tuple[str, str]]) -> str:
        return "".join(t for _, t in parts)

    def _build(self, status=None, git_status=None, commits=None):
        return self._text(
            build_detail_content(
                status or make_status(),
                git_status or GitStatusDetail(staged=[], unstaged=[], untracked=[]),
                commits or [],
            )
        )

    def test_main_header_and_up_to_date(self):
        text = self._build(make_status(is_main=True, branch="main", ahead=0, behind=0))
        assert "main" in text and "(main)" in text
        assert "up to date" in text

    def test_ahead_and_behind_shown(self):
        text = self._build(make_status(ahead=2, behind=1))
        assert "2 ahead" in text and "1 behind" in text

    def test_clean_working_tree_message(self):
        assert "Working tree clean" in self._build()

    def test_staged_unstaged_untracked_sections(self):
        git_status = GitStatusDetail(
            staged=["A new.py"], unstaged=["M mod.py"], untracked=["scratch.txt"]
        )
        text = self._build(git_status=git_status)
        assert "Staged:" in text and "A new.py" in text
        assert "Modified:" in text and "M mod.py" in text
        assert "Untracked:" in text and "scratch.txt" in text

    def test_no_commits_message(self):
        assert "No commits found" in self._build()

    def test_recent_commits_listed(self):
        commits = [
            CommitInfo(hash="abc123", message="did stuff", author="A", date="1h ago")
        ]
        text = self._build(commits=commits)
        assert "abc123" in text and "did stuff" in text and "A, 1h ago" in text

    def test_task_section_only_when_present(self):
        assert "Current Task" in self._build(make_status(task="write tests"))
        assert "Current Task" not in self._build(make_status(task=None))
