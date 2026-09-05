"""Tests for GitHub issue integration in commands/wt.py.

Covers remote-URL parsing (real git, no mocking), the on-disk issue cache,
and the `gh` subprocess wrappers (subprocess.run patched at the module).
"""

from __future__ import annotations

import json
import subprocess
from unittest.mock import MagicMock, patch

from conftest import git

from hive_cli.commands.wt import (
    GitHubIssue,
    GitHubIssueDetails,
    _fetch_github_issues,
    _fetch_issue_details,
    _get_github_repo_info,
    _get_issues_cache_path,
    _load_cached_issues,
    _save_cached_issues,
    _write_task_file,
)
from hive_cli.config import reload_config

# ---------------------------------------------------------------------------
# _get_github_repo_info — real git, no mocking
# ---------------------------------------------------------------------------


class TestGetGithubRepoInfo:
    def test_https_url(self, temp_git_repo):
        git(
            "remote",
            "add",
            "origin",
            "https://github.com/acme/widgets.git",
            cwd=temp_git_repo,
        )
        assert _get_github_repo_info(temp_git_repo) == ("acme", "widgets")

    def test_https_url_without_git_suffix(self, temp_git_repo):
        git(
            "remote",
            "add",
            "origin",
            "https://github.com/acme/widgets",
            cwd=temp_git_repo,
        )
        assert _get_github_repo_info(temp_git_repo) == ("acme", "widgets")

    def test_ssh_url(self, temp_git_repo):
        git(
            "remote",
            "add",
            "origin",
            "git@github.com:acme/widgets.git",
            cwd=temp_git_repo,
        )
        assert _get_github_repo_info(temp_git_repo) == ("acme", "widgets")

    def test_non_github_remote_returns_none(self, temp_git_repo):
        git(
            "remote",
            "add",
            "origin",
            "https://gitlab.com/acme/widgets.git",
            cwd=temp_git_repo,
        )
        assert _get_github_repo_info(temp_git_repo) is None

    def test_unrecognized_scheme_returns_none(self, temp_git_repo):
        # Contains "github.com" but neither the git@ nor http(s):// prefix.
        git(
            "remote",
            "add",
            "origin",
            "ftp://github.com/acme/widgets.git",
            cwd=temp_git_repo,
        )
        assert _get_github_repo_info(temp_git_repo) is None

    def test_no_remote_returns_none(self, temp_git_repo):
        assert _get_github_repo_info(temp_git_repo) is None


# ---------------------------------------------------------------------------
# _get_issues_cache_path
# ---------------------------------------------------------------------------


class TestGetIssuesCachePath:
    def test_github_repo_returns_and_creates_cache_dir(
        self, temp_git_repo, tmp_path, monkeypatch
    ):
        git(
            "remote",
            "add",
            "origin",
            "https://github.com/acme/widgets.git",
            cwd=temp_git_repo,
        )
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
        import hive_cli.config.runtime as rt_mod

        rt_mod._runtime_settings = None

        path = _get_issues_cache_path(temp_git_repo)

        assert path == tmp_path / "cache" / "hive" / "gh-acme--widgets-issues.json"
        assert path.parent.is_dir()

        rt_mod._runtime_settings = None

    def test_non_github_repo_returns_none(self, temp_git_repo):
        assert _get_issues_cache_path(temp_git_repo) is None


# ---------------------------------------------------------------------------
# Cache load/save round trip
# ---------------------------------------------------------------------------


class TestCacheRoundTrip:
    def test_save_then_load_round_trips(self, tmp_path):
        cache_path = tmp_path / "issues.json"
        issues = [
            GitHubIssue(number=1, title="Fix bug"),
            GitHubIssue(number=2, title="Add feature"),
        ]

        _save_cached_issues(issues, cache_path)
        loaded = _load_cached_issues(cache_path)

        assert loaded == issues

    def test_load_missing_file_returns_empty_list(self, tmp_path):
        assert _load_cached_issues(tmp_path / "missing.json") == []

    def test_load_none_path_returns_empty_list(self):
        assert _load_cached_issues(None) == []

    def test_load_corrupt_json_returns_empty_list(self, tmp_path):
        cache_path = tmp_path / "bad.json"
        cache_path.write_text("{not valid json!!")
        assert _load_cached_issues(cache_path) == []

    def test_load_json_missing_expected_keys_returns_empty_list(self, tmp_path):
        cache_path = tmp_path / "bad-shape.json"
        cache_path.write_text(json.dumps([{"title": "no number field"}]))
        assert _load_cached_issues(cache_path) == []

    def test_save_none_path_is_noop(self):
        # Should not raise.
        _save_cached_issues([GitHubIssue(number=1, title="x")], None)

    def test_save_creates_parent_directories(self, tmp_path):
        cache_path = tmp_path / "nested" / "dir" / "issues.json"
        _save_cached_issues([GitHubIssue(number=1, title="x")], cache_path)
        assert cache_path.exists()
        data = json.loads(cache_path.read_text())
        assert data == [{"number": 1, "title": "x"}]

    def test_save_empty_list_clears_cache(self, tmp_path):
        cache_path = tmp_path / "issues.json"
        _save_cached_issues([GitHubIssue(number=1, title="stale")], cache_path)
        _save_cached_issues([], cache_path)
        assert _load_cached_issues(cache_path) == []


# ---------------------------------------------------------------------------
# GitHubIssue (de)serialization
# ---------------------------------------------------------------------------


class TestGitHubIssueDictRoundTrip:
    def test_to_dict_and_from_dict(self):
        issue = GitHubIssue(number=42, title="The answer")
        data = issue.to_dict()
        assert data == {"number": 42, "title": "The answer"}
        assert GitHubIssue.from_dict(data) == issue


# ---------------------------------------------------------------------------
# _fetch_github_issues — subprocess.run patched at hive_cli.commands.wt
# ---------------------------------------------------------------------------


class TestFetchGithubIssues:
    def test_disabled_in_config_returns_none_without_subprocess(
        self, temp_git_repo, monkeypatch
    ):
        config_file = temp_git_repo / ".hive.yml"
        config_file.write_text("github:\n  fetch_issues: false\n")
        reload_config()

        with patch("hive_cli.commands.wt.subprocess.run") as mock_run:
            result = _fetch_github_issues(temp_git_repo)

        assert result is None
        mock_run.assert_not_called()

    def test_gh_not_installed_returns_none(self, temp_git_repo):
        with patch(
            "hive_cli.commands.wt.subprocess.run", side_effect=FileNotFoundError
        ):
            assert _fetch_github_issues(temp_git_repo) is None

    def test_gh_timeout_returns_none(self, temp_git_repo):
        with patch(
            "hive_cli.commands.wt.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="gh", timeout=2),
        ):
            assert _fetch_github_issues(temp_git_repo) is None

    def test_gh_error_returncode_returns_none(self, temp_git_repo):
        mock_result = MagicMock(returncode=1, stdout="", stderr="not logged in")
        with patch("hive_cli.commands.wt.subprocess.run", return_value=mock_result):
            assert _fetch_github_issues(temp_git_repo) is None

    def test_gh_invalid_json_returns_none(self, temp_git_repo):
        mock_result = MagicMock(returncode=0, stdout="not json")
        with patch("hive_cli.commands.wt.subprocess.run", return_value=mock_result):
            assert _fetch_github_issues(temp_git_repo) is None

    def test_success_returns_issues_and_writes_cache(
        self, temp_git_repo, tmp_path, monkeypatch
    ):
        git(
            "remote",
            "add",
            "origin",
            "https://github.com/acme/widgets.git",
            cwd=temp_git_repo,
        )
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
        import hive_cli.config.runtime as rt_mod

        rt_mod._runtime_settings = None

        payload = json.dumps([{"number": 7, "title": "Do the thing"}])
        mock_result = MagicMock(returncode=0, stdout=payload)
        real_run = subprocess.run

        def fake_run(cmd, *args, **kwargs):
            # Only fake the `gh` call; let real git commands (e.g. the
            # `git remote get-url origin` used to derive the cache path)
            # execute for real — never mock git.
            if cmd[0] == "gh":
                return mock_result
            return real_run(cmd, *args, **kwargs)

        with patch(
            "hive_cli.commands.wt.subprocess.run", side_effect=fake_run
        ) as mock_run:
            issues = _fetch_github_issues(temp_git_repo)

        assert issues == [GitHubIssue(number=7, title="Do the thing")]
        # Called the gh CLI with the expected shape.
        gh_calls = [c for c in mock_run.call_args_list if c.args[0][0] == "gh"]
        assert len(gh_calls) == 1
        assert gh_calls[0].args[0][:3] == ["gh", "issue", "list"]

        cache_path = _get_issues_cache_path(temp_git_repo)
        assert _load_cached_issues(cache_path) == issues

        rt_mod._runtime_settings = None

    def test_success_with_empty_list_clears_stale_cache(
        self, temp_git_repo, tmp_path, monkeypatch
    ):
        git(
            "remote",
            "add",
            "origin",
            "https://github.com/acme/widgets.git",
            cwd=temp_git_repo,
        )
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
        import hive_cli.config.runtime as rt_mod

        rt_mod._runtime_settings = None

        cache_path = _get_issues_cache_path(temp_git_repo)
        _save_cached_issues([GitHubIssue(number=1, title="stale")], cache_path)

        mock_result = MagicMock(returncode=0, stdout="[]")
        real_run = subprocess.run

        def fake_run(cmd, *args, **kwargs):
            if cmd[0] == "gh":
                return mock_result
            return real_run(cmd, *args, **kwargs)

        with patch("hive_cli.commands.wt.subprocess.run", side_effect=fake_run):
            issues = _fetch_github_issues(temp_git_repo)

        assert issues == []
        assert _load_cached_issues(cache_path) == []

        rt_mod._runtime_settings = None


# ---------------------------------------------------------------------------
# _fetch_issue_details
# ---------------------------------------------------------------------------


class TestFetchIssueDetails:
    def test_success_returns_details(self, temp_git_repo):
        payload = json.dumps(
            {
                "number": 5,
                "title": "Title",
                "url": "https://github.com/acme/widgets/issues/5",
                "body": "Body text",
            }
        )
        mock_result = MagicMock(returncode=0, stdout=payload)
        with patch("hive_cli.commands.wt.subprocess.run", return_value=mock_result):
            details = _fetch_issue_details(5, temp_git_repo)

        assert details == GitHubIssueDetails(
            number=5,
            title="Title",
            url="https://github.com/acme/widgets/issues/5",
            body="Body text",
        )

    def test_missing_body_defaults_to_empty_string(self, temp_git_repo):
        payload = json.dumps({"number": 5, "title": "Title", "url": "https://x/5"})
        mock_result = MagicMock(returncode=0, stdout=payload)
        with patch("hive_cli.commands.wt.subprocess.run", return_value=mock_result):
            details = _fetch_issue_details(5, temp_git_repo)
        assert details.body == ""

    def test_null_body_defaults_to_empty_string(self, temp_git_repo):
        payload = json.dumps(
            {"number": 5, "title": "Title", "url": "https://x/5", "body": None}
        )
        mock_result = MagicMock(returncode=0, stdout=payload)
        with patch("hive_cli.commands.wt.subprocess.run", return_value=mock_result):
            details = _fetch_issue_details(5, temp_git_repo)
        assert details.body == ""

    def test_error_returncode_returns_none(self, temp_git_repo):
        mock_result = MagicMock(returncode=1, stdout="")
        with patch("hive_cli.commands.wt.subprocess.run", return_value=mock_result):
            assert _fetch_issue_details(5, temp_git_repo) is None

    def test_exception_returns_none(self, temp_git_repo):
        with patch(
            "hive_cli.commands.wt.subprocess.run", side_effect=FileNotFoundError
        ):
            assert _fetch_issue_details(5, temp_git_repo) is None


# ---------------------------------------------------------------------------
# _write_task_file
# ---------------------------------------------------------------------------


class TestWriteTaskFile:
    def test_writes_task_file_with_body(self, tmp_path):
        issue = GitHubIssueDetails(
            number=12, title="Fix the thing", url="https://x/12", body="Do X then Y."
        )
        _write_task_file(tmp_path, issue)

        content = (tmp_path / ".claude" / "task.local.md").read_text()
        assert "# Task: Fix the thing" in content
        assert "[#12](https://x/12)" in content
        assert "Do X then Y." in content

    def test_writes_task_file_without_body(self, tmp_path):
        issue = GitHubIssueDetails(
            number=13, title="No body issue", url="https://x/13", body=""
        )
        _write_task_file(tmp_path, issue)

        content = (tmp_path / ".claude" / "task.local.md").read_text()
        assert "_No description provided._" in content

    def test_creates_claude_directory(self, tmp_path):
        issue = GitHubIssueDetails(number=1, title="T", url="https://x/1", body="B")
        assert not (tmp_path / ".claude").exists()
        _write_task_file(tmp_path, issue)
        assert (tmp_path / ".claude").is_dir()
