"""Integration tests for git/status.py using real git repos."""

from __future__ import annotations

from pathlib import Path

from conftest import commit_file, git

from hive_cli.git.status import (
    GitStatusDetail,
    get_git_status_detail,
    get_recent_commits,
    last_commit_summary,
    upstream_ahead_behind,
)


class TestUpstreamAheadBehind:
    def test_no_upstream_and_ahead(self, temp_git_repo: Path, repo_with_origin: Path):
        assert upstream_ahead_behind(temp_git_repo) == (0, 0)
        commit_file(repo_with_origin, "a.txt", "1")
        assert upstream_ahead_behind(repo_with_origin) == (1, 0)


class TestLastCommitSummary:
    def test_hash_message_and_truncation(self, temp_git_repo: Path):
        commit_file(temp_git_repo, "f.txt", "x", message="a specific message")
        commit_hash, msg = last_commit_summary(temp_git_repo)
        assert commit_hash
        assert msg == "a specific message"

        commit_file(temp_git_repo, "f2.txt", "x", message="y" * 80)
        assert len(last_commit_summary(temp_git_repo)[1]) == 50


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
