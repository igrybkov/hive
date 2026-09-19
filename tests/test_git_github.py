"""Tests for git/github.py: repo detection, issue cache, and `gh` fetch.

Covers remote-URL parsing (real git, no mocking), the on-disk issue cache,
and the `gh`/`git` subprocess wrappers (via fake_proc, since git/github.py
goes through core.proc.run).
"""

from __future__ import annotations

import json

from conftest import git

from hive_cli.config import reload_config
from hive_cli.git.github import (
    GitHubIssue,
    GitHubIssueDetails,
    fetch_issue_details,
    fetch_issues,
    get_github_repo_info,
    get_issues_cache_path,
    load_cached_issues,
    save_cached_issues,
)

# ---------------------------------------------------------------------------
# get_github_repo_info — real git, no mocking
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
        assert get_github_repo_info(temp_git_repo) == ("acme", "widgets")

    def test_https_url_without_git_suffix(self, temp_git_repo):
        git(
            "remote",
            "add",
            "origin",
            "https://github.com/acme/widgets",
            cwd=temp_git_repo,
        )
        assert get_github_repo_info(temp_git_repo) == ("acme", "widgets")

    def test_ssh_url(self, temp_git_repo):
        git(
            "remote",
            "add",
            "origin",
            "git@github.com:acme/widgets.git",
            cwd=temp_git_repo,
        )
        assert get_github_repo_info(temp_git_repo) == ("acme", "widgets")

    def test_non_github_remote_returns_none(self, temp_git_repo):
        git(
            "remote",
            "add",
            "origin",
            "https://gitlab.com/acme/widgets.git",
            cwd=temp_git_repo,
        )
        assert get_github_repo_info(temp_git_repo) is None

    def test_unrecognized_scheme_returns_none(self, temp_git_repo):
        # Contains "github.com" but neither the git@ nor http(s):// prefix.
        git(
            "remote",
            "add",
            "origin",
            "ftp://github.com/acme/widgets.git",
            cwd=temp_git_repo,
        )
        assert get_github_repo_info(temp_git_repo) is None

    def test_no_remote_returns_none(self, temp_git_repo):
        assert get_github_repo_info(temp_git_repo) is None


# ---------------------------------------------------------------------------
# get_issues_cache_path
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

        path = get_issues_cache_path(temp_git_repo)

        assert path == tmp_path / "cache" / "hive" / "gh-acme--widgets-issues.json"
        assert path.parent.is_dir()

        rt_mod._runtime_settings = None

    def test_non_github_repo_returns_none(self, temp_git_repo):
        assert get_issues_cache_path(temp_git_repo) is None


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

        save_cached_issues(issues, cache_path)
        loaded = load_cached_issues(cache_path)

        assert loaded == issues

    def test_load_missing_file_returns_empty_list(self, tmp_path):
        assert load_cached_issues(tmp_path / "missing.json") == []

    def test_load_none_path_returns_empty_list(self):
        assert load_cached_issues(None) == []

    def test_load_corrupt_json_returns_empty_list(self, tmp_path):
        cache_path = tmp_path / "bad.json"
        cache_path.write_text("{not valid json!!")
        assert load_cached_issues(cache_path) == []

    def test_load_json_missing_expected_keys_returns_empty_list(self, tmp_path):
        cache_path = tmp_path / "bad-shape.json"
        cache_path.write_text(json.dumps([{"title": "no number field"}]))
        assert load_cached_issues(cache_path) == []

    def test_save_none_path_is_noop(self):
        # Should not raise.
        save_cached_issues([GitHubIssue(number=1, title="x")], None)

    def test_save_creates_parent_directories(self, tmp_path):
        cache_path = tmp_path / "nested" / "dir" / "issues.json"
        save_cached_issues([GitHubIssue(number=1, title="x")], cache_path)
        assert cache_path.exists()
        data = json.loads(cache_path.read_text())
        assert data == [{"number": 1, "title": "x"}]

    def test_save_empty_list_clears_cache(self, tmp_path):
        cache_path = tmp_path / "issues.json"
        save_cached_issues([GitHubIssue(number=1, title="stale")], cache_path)
        save_cached_issues([], cache_path)
        assert load_cached_issues(cache_path) == []


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
# fetch_issues — via fake_proc (core.proc.run)
# ---------------------------------------------------------------------------


class TestFetchIssues:
    def test_disabled_in_config_returns_none_without_subprocess(
        self, temp_git_repo, fake_proc
    ):
        config_file = temp_git_repo / ".hive.yml"
        config_file.write_text("github:\n  fetch_issues: false\n")
        reload_config()

        result = fetch_issues(temp_git_repo)

        assert result is None
        assert fake_proc.calls == []

    def test_gh_not_installed_returns_none(self, temp_git_repo, fake_proc):
        fake_proc.script(("gh",), returncode=127, stderr="gh: command not found")
        assert fetch_issues(temp_git_repo) is None

    def test_gh_timeout_returns_none(self, temp_git_repo, fake_proc):
        fake_proc.script(("gh",), returncode=124, stderr="timed out after 2.0s")
        assert fetch_issues(temp_git_repo) is None

    def test_gh_error_returncode_returns_none(self, temp_git_repo, fake_proc):
        fake_proc.script(("gh",), returncode=1, stderr="not logged in")
        assert fetch_issues(temp_git_repo) is None

    def test_gh_invalid_json_returns_none(self, temp_git_repo, fake_proc):
        fake_proc.script(("gh",), returncode=0, stdout="not json")
        assert fetch_issues(temp_git_repo) is None

    def test_success_returns_issues_and_writes_cache(
        self, temp_git_repo, tmp_path, monkeypatch, fake_gh
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
        fake_gh.script(("gh", "issue", "list"), returncode=0, stdout=payload)

        issues = fetch_issues(temp_git_repo)

        assert issues == [GitHubIssue(number=7, title="Do the thing")]
        assert fake_gh.count("gh", "issue", "list") == 1

        cache_path = get_issues_cache_path(temp_git_repo)
        assert load_cached_issues(cache_path) == issues

        rt_mod._runtime_settings = None

    def test_success_with_empty_list_clears_stale_cache(
        self, temp_git_repo, tmp_path, monkeypatch, fake_gh
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

        cache_path = get_issues_cache_path(temp_git_repo)
        save_cached_issues([GitHubIssue(number=1, title="stale")], cache_path)

        fake_gh.script(("gh", "issue", "list"), returncode=0, stdout="[]")

        issues = fetch_issues(temp_git_repo)

        assert issues == []
        assert load_cached_issues(cache_path) == []

        rt_mod._runtime_settings = None


# ---------------------------------------------------------------------------
# fetch_issue_details
# ---------------------------------------------------------------------------


class TestFetchIssueDetails:
    def test_success_returns_details(self, temp_git_repo, fake_proc):
        payload = json.dumps(
            {
                "number": 5,
                "title": "Title",
                "url": "https://github.com/acme/widgets/issues/5",
                "body": "Body text",
            }
        )
        fake_proc.script(("gh", "issue", "view"), returncode=0, stdout=payload)

        details = fetch_issue_details(5, temp_git_repo)

        assert details == GitHubIssueDetails(
            number=5,
            title="Title",
            url="https://github.com/acme/widgets/issues/5",
            body="Body text",
        )

    def test_missing_body_defaults_to_empty_string(self, temp_git_repo, fake_proc):
        payload = json.dumps({"number": 5, "title": "Title", "url": "https://x/5"})
        fake_proc.script(("gh", "issue", "view"), returncode=0, stdout=payload)
        details = fetch_issue_details(5, temp_git_repo)
        assert details.body == ""

    def test_null_body_defaults_to_empty_string(self, temp_git_repo, fake_proc):
        payload = json.dumps(
            {"number": 5, "title": "Title", "url": "https://x/5", "body": None}
        )
        fake_proc.script(("gh", "issue", "view"), returncode=0, stdout=payload)
        details = fetch_issue_details(5, temp_git_repo)
        assert details.body == ""

    def test_error_returncode_returns_none(self, temp_git_repo, fake_proc):
        fake_proc.script(("gh", "issue", "view"), returncode=1, stdout="")
        assert fetch_issue_details(5, temp_git_repo) is None

    def test_exception_returns_none(self, temp_git_repo, fake_proc):
        fake_proc.script(("gh", "issue", "view"), returncode=127)
        assert fetch_issue_details(5, temp_git_repo) is None
