"""Tests for git/status.py: the porcelain-v2 parser (pure) and real-repo facts."""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import commit_file, git

from hive_cli.git.status import (
    GitStatusDetail,
    GitSummary,
    get_git_status_detail,
    get_recent_commits,
    git_summary,
    parse_porcelain_v2,
)

HEADER = "# branch.oid 1a2b3c\n# branch.head main\n"


class TestParsePorcelainV2:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            # (branch, upstream, ahead, behind, staged, modified, untracked, conflicted)
            (HEADER, ("main", "", 0, 0, 0, 0, 0, 0)),
            (
                HEADER + "# branch.upstream origin/main\n# branch.ab +2 -1\n",
                ("main", "origin/main", 2, 1, 0, 0, 0, 0),
            ),
            ("# branch.head (detached)\n", ("", "", 0, 0, 0, 0, 0, 0)),
            (
                HEADER + "1 .M N... 100644 100644 100644 abc def src/x.py\n",
                ("main", "", 0, 0, 0, 1, 0, 0),
            ),
            (
                HEADER + "1 M. N... 100644 100644 100644 abc def src/y.py\n",
                ("main", "", 0, 0, 1, 0, 0, 0),
            ),
            (
                HEADER + "1 MM N... 100644 100644 100644 abc def src/z.py\n",
                ("main", "", 0, 0, 1, 1, 0, 0),
            ),
            (
                HEADER + "2 R. N... 100644 100644 100644 abc def R100 new\told\n",
                ("main", "", 0, 0, 1, 0, 0, 0),
            ),
            (
                HEADER + "u UU N... 100644 100644 100644 100644 abc def ghi f\n",
                ("main", "", 0, 0, 0, 0, 0, 1),
            ),
            (HEADER + "? notes.txt\n", ("main", "", 0, 0, 0, 0, 1, 0)),
            (HEADER + "! ignored.txt\n", ("main", "", 0, 0, 0, 0, 0, 0)),
            ("", ("", "", 0, 0, 0, 0, 0, 0)),
        ],
    )
    def test_table(self, text, expected):
        assert parse_porcelain_v2(text) == expected


class TestGitSummary:
    def test_real_repo_counts(self, temp_git_repo: Path):
        clean = git_summary(temp_git_repo)
        assert clean.branch == "main" and clean.upstream == ""
        assert (clean.ahead, clean.behind) == (0, 0)
        assert (clean.staged, clean.modified, clean.untracked, clean.conflicted) == (
            0,
            0,
            0,
            0,
        )
        assert clean.dirty is False
        assert clean.last_hash and clean.last_subject == "Initial commit"
        assert "ago" in clean.last_age

        (temp_git_repo / "new.txt").write_text("new")
        assert git_summary(temp_git_repo).untracked == 1
        git("add", "new.txt", cwd=temp_git_repo)
        assert git_summary(temp_git_repo).staged == 1
        (temp_git_repo / "README.md").write_text("changed\n")
        summary = git_summary(temp_git_repo)
        assert summary.modified == 1 and summary.dirty is True

    def test_ahead_behind_against_upstream(self, repo_with_origin: Path, tmp_path):
        commit_file(repo_with_origin, "local.txt", "1", message="local work")
        clone = tmp_path / "clone"
        git("clone", "-q", str(tmp_path / "origin.git"), str(clone), cwd=tmp_path)
        commit_file(clone, "remote.txt", "2", message="remote work")
        git("push", "-q", "origin", "main", cwd=clone)
        git("fetch", "-q", "origin", cwd=repo_with_origin)

        summary = git_summary(repo_with_origin)
        assert summary.upstream == "origin/main"
        assert (summary.ahead, summary.behind) == (1, 1)
        assert summary.last_subject == "local work"

    def test_is_exactly_two_spawns(self, fake_proc, tmp_path):
        fake_proc.script(("git", "status"), stdout=HEADER + "? a\n")
        fake_proc.script(("git", "log"), stdout="abc1234\x00subject\x003 hours ago\n")
        summary = git_summary(tmp_path)
        assert len(fake_proc.calls) == 2
        assert summary == GitSummary(
            branch="main",
            upstream="",
            ahead=0,
            behind=0,
            staged=0,
            modified=0,
            untracked=1,
            conflicted=0,
            last_hash="abc1234",
            last_subject="subject",
            last_age="3 hours ago",
        )

    def test_failed_git_gives_empty_summary(self, fake_proc, tmp_path):
        fake_proc.script(("git",), returncode=128, stderr="fatal: not a git repo")
        summary = git_summary(tmp_path)
        assert summary == GitSummary("", "", 0, 0, 0, 0, 0, 0, "", "", "")
        assert summary.dirty is False


class TestGetGitStatusDetail:
    def test_clean_then_dirty(self, temp_git_repo: Path):
        assert get_git_status_detail(temp_git_repo) == GitStatusDetail([], [], [])

        (temp_git_repo / "untracked.txt").write_text("new")
        (temp_git_repo / "README.md").write_text("modified content\n")
        (temp_git_repo / "staged.txt").write_text("staged")
        git("add", "staged.txt", cwd=temp_git_repo)

        detail = get_git_status_detail(temp_git_repo)
        assert any("staged.txt" in f for f in detail.staged)
        assert any("README.md" in f for f in detail.unstaged)
        assert "untracked.txt" in detail.untracked


class TestGetRecentCommits:
    def test_most_recent_first_with_count(self, temp_git_repo: Path):
        commit_file(temp_git_repo, "one.txt", "1", message="first change")
        commit_file(temp_git_repo, "two.txt", "2", message="second change")
        commits = get_recent_commits(temp_git_repo, count=1)
        assert len(commits) == 1
        assert commits[0].message == "second change"
        assert commits[0].author == "Test User"
