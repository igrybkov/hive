"""services/facts.py: fetch throttle, per-worktree summaries, cached gh issues.

Spawn counts are the assertions (fake_proc); nothing here needs a network.
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

import pytest

from hive_cli.git.github import GitHubIssue, save_cached_issues
from hive_cli.git.worktree import WorktreeInfo
from hive_cli.services import facts


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    main = tmp_path / "repo"
    (main / ".git").mkdir(parents=True)
    return main


class TestFetchIfStale:
    def test_skips_when_fetch_head_is_recent(self, repo: Path, fake_proc):
        (repo / ".git" / "FETCH_HEAD").write_text("")
        assert facts.fetch_if_stale(repo, 300) is False
        assert fake_proc.count("git", "fetch") == 0

    def test_fetches_when_fetch_head_is_old(self, repo: Path, fake_proc):
        fetch_head = repo / ".git" / "FETCH_HEAD"
        fetch_head.write_text("")
        old = time.time() - 301
        os.utime(fetch_head, (old, old))
        assert facts.fetch_if_stale(repo, 300) is True
        assert fake_proc.calls == [["git", "fetch", "origin"]]

    def test_fetches_when_fetch_head_is_missing(self, repo: Path, fake_proc):
        assert facts.fetch_if_stale(repo, 300) is True
        assert fake_proc.count("git", "fetch") == 1

    def test_now_parameter_controls_staleness(self, repo: Path, fake_proc):
        fetch_head = repo / ".git" / "FETCH_HEAD"
        fetch_head.write_text("")
        mtime = fetch_head.stat().st_mtime
        assert facts.fetch_if_stale(repo, 300, now=mtime + 299) is False
        assert facts.fetch_if_stale(repo, 300, now=mtime + 301) is True

    def test_failed_fetch_returns_false(self, repo: Path, fake_proc):
        fake_proc.script(("git", "fetch"), returncode=128)
        assert facts.fetch_if_stale(repo, 300) is False


class TestSummaries:
    def test_two_spawns_per_worktree(self, fake_proc, tmp_path):
        fake_proc.script(("git", "status"), stdout="# branch.head feat\n")
        worktrees = [
            WorktreeInfo("main", tmp_path / "a", is_main=True),
            WorktreeInfo("feat", tmp_path / "b"),
        ]
        result = facts.summaries(worktrees)
        assert set(result) == {tmp_path / "a", tmp_path / "b"}
        assert result[tmp_path / "b"].branch == "feat"
        assert len(fake_proc.calls) == 4

    def test_respects_cancel(self, fake_proc, tmp_path):
        cancel = threading.Event()
        cancel.set()
        assert (
            facts.summaries([WorktreeInfo("main", tmp_path, True)], cancel=cancel) == {}
        )
        assert fake_proc.calls == []


class TestIssues:
    @pytest.fixture(autouse=True)
    def _github_repo(self, fake_proc, mocker):
        fake_proc.script(
            ("git", "-C"), stdout="https://github.com/acme/widgets.git\n"
        )  # `git -C <repo> remote get-url origin`
        mocker.patch("hive_cli.services.facts.shutil.which", return_value="/bin/gh")

    def test_none_when_gh_missing(self, repo: Path, fake_proc, mocker):
        mocker.patch("hive_cli.services.facts.shutil.which", return_value=None)
        assert facts.issues(repo) is None
        assert fake_proc.calls == []

    def test_none_when_disabled(self, repo: Path, fake_proc, monkeypatch):
        monkeypatch.setenv("HIVE_GITHUB_FETCH_ISSUES", "false")
        from hive_cli.config import reset_settings

        reset_settings()
        assert facts.issues(repo) is None
        assert fake_proc.calls == []

    def test_uses_cache_within_max_age(self, repo: Path, fake_proc):
        from hive_cli.git.github import get_issues_cache_path

        cache_path = get_issues_cache_path(repo)
        assert cache_path is not None
        save_cached_issues([GitHubIssue(7, "cached")], cache_path)

        result = facts.issues(repo, max_age_s=60)

        assert result == [GitHubIssue(7, "cached")]
        assert fake_proc.count("gh") == 0

    def test_refreshes_when_cache_is_stale(self, repo: Path, fake_proc):
        from hive_cli.git.github import get_issues_cache_path, load_cached_issues

        cache_path = get_issues_cache_path(repo)
        save_cached_issues([GitHubIssue(7, "old")], cache_path)
        fake_proc.script(
            ("gh", "issue", "list"), stdout='[{"number": 8, "title": "new"}]'
        )

        result = facts.issues(repo, max_age_s=0)

        assert result == [GitHubIssue(8, "new")]
        assert fake_proc.count("gh") == 1
        assert load_cached_issues(cache_path) == [GitHubIssue(8, "new")]

    def test_falls_back_to_stale_cache_when_gh_fails(self, repo: Path, fake_proc):
        from hive_cli.git.github import get_issues_cache_path

        save_cached_issues([GitHubIssue(7, "old")], get_issues_cache_path(repo))
        fake_proc.script(("gh",), returncode=1, stderr="not logged in")
        assert facts.issues(repo, max_age_s=0) == [GitHubIssue(7, "old")]

    def test_none_when_gh_fails_and_nothing_cached(self, repo: Path, fake_proc):
        fake_proc.script(("gh",), returncode=1)
        assert facts.issues(repo, max_age_s=0) is None
