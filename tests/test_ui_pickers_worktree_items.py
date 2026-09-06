"""Tests for ui/pickers/worktree_items.py: FuzzyItem builders for the picker."""

from __future__ import annotations

import json
from pathlib import Path

from conftest import git

from hive_cli.config import reload_config
from hive_cli.git.github import (
    GitHubIssue,
    get_issues_cache_path,
    save_cached_issues,
)
from hive_cli.ui.pickers.worktree_items import (
    ACTION_ISSUE_PREFIX,
    _build_fuzzy_items,
    _build_fuzzy_items_fast,
)

# ---------------------------------------------------------------------------
# _build_fuzzy_items_fast / _build_fuzzy_items
# ---------------------------------------------------------------------------


class TestBuildFuzzyItemsFast:
    def test_main_and_worktrees_listed(
        self, temp_git_repo, make_worktree, isolated_worktrees
    ):
        make_worktree("feat-a")
        make_worktree("feat-b")

        items, _selection = _build_fuzzy_items_fast(temp_git_repo)

        by_value = {item.value: item for item in items}
        assert by_value["main"].text == "main"
        assert by_value["main"].meta == "[repo]"
        assert by_value["main"].style == "bold green"
        assert by_value["feat-a"].style == "green"
        assert by_value["feat-b"].style == "green"

    def test_dirty_worktree_still_shown_clean_in_fast_mode(
        self, temp_git_repo, make_worktree, isolated_worktrees
    ):
        wt_path = make_worktree("feat-b")
        (wt_path / "dirty.txt").write_text("uncommitted")

        items, _selection = _build_fuzzy_items_fast(temp_git_repo)
        by_value = {item.value: item for item in items}

        assert by_value["feat-b"].style == "green"
        assert by_value["feat-b"].meta == ""

    def test_current_worktree_branch_marked(
        self, temp_git_repo, make_worktree, isolated_worktrees
    ):
        make_worktree("feat-a")

        items, _selection = _build_fuzzy_items_fast(
            temp_git_repo, current_worktree_branch="feat-a"
        )
        by_value = {item.value: item for item in items}
        assert by_value["feat-a"].meta == "← current"

    def test_branch_without_worktree_shown_dim(self, temp_git_repo, isolated_worktrees):
        git("branch", "feat-c", cwd=temp_git_repo)

        items, _selection = _build_fuzzy_items_fast(temp_git_repo)
        by_value = {item.value: item for item in items}

        assert by_value["feat-c"].style == "dim"
        assert by_value["feat-c"].meta == ""

    def test_preselect_branch_sets_initial_selection(
        self, temp_git_repo, make_worktree, isolated_worktrees
    ):
        make_worktree("feat-a")
        make_worktree("feat-b")

        items, selection = _build_fuzzy_items_fast(
            temp_git_repo, preselect_branch="feat-b"
        )
        assert items[selection].value == "feat-b"

    def test_preselect_main(self, temp_git_repo, make_worktree, isolated_worktrees):
        make_worktree("feat-a")

        items, selection = _build_fuzzy_items_fast(
            temp_git_repo, preselect_branch="main"
        )
        assert items[selection].value == "main"

    def test_no_worktrees_lists_main_only(self, temp_git_repo, isolated_worktrees):
        items, selection = _build_fuzzy_items_fast(temp_git_repo)
        assert len(items) == 1
        assert items[0].value == "main"
        assert selection == 0


class TestBuildFuzzyItemsFastCachedIssues:
    def test_cached_issue_shown(
        self, temp_git_repo, isolated_worktrees, tmp_path, monkeypatch
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
        save_cached_issues([GitHubIssue(number=9, title="Do the thing")], cache_path)

        items, _selection = _build_fuzzy_items_fast(temp_git_repo)
        issue_items = [i for i in items if i.value.startswith(ACTION_ISSUE_PREFIX)]

        assert len(issue_items) == 1
        assert "9" in issue_items[0].text
        assert "Do the thing" in issue_items[0].text
        assert issue_items[0].style == "cyan"

        rt_mod._runtime_settings = None

    def test_cached_issue_hidden_if_branch_already_exists(
        self, temp_git_repo, isolated_worktrees, tmp_path, monkeypatch
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
        save_cached_issues([GitHubIssue(number=9, title="Do the thing")], cache_path)
        git("branch", "gh-9-do-the-thing", cwd=temp_git_repo)

        items, _selection = _build_fuzzy_items_fast(temp_git_repo)
        issue_items = [i for i in items if i.value.startswith(ACTION_ISSUE_PREFIX)]

        assert issue_items == []

        rt_mod._runtime_settings = None

    def test_long_issue_title_truncated(
        self, temp_git_repo, isolated_worktrees, tmp_path, monkeypatch
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

        long_title = "x" * 80
        cache_path = get_issues_cache_path(temp_git_repo)
        save_cached_issues([GitHubIssue(number=1, title=long_title)], cache_path)

        items, _selection = _build_fuzzy_items_fast(temp_git_repo)
        issue_items = [i for i in items if i.value.startswith(ACTION_ISSUE_PREFIX)]

        assert issue_items[0].text.endswith("...")
        assert long_title not in issue_items[0].text

        rt_mod._runtime_settings = None


class TestBuildFuzzyItemsSlowGithubIssues:
    """_build_fuzzy_items' live GitHub fetch, with only the `gh` call faked.

    Real git commands (e.g. `git remote get-url origin`) still run for real —
    the hard rule is "never mock git" — so fake_gh below only intercepts
    calls whose argv starts with "gh".
    """

    def test_fetched_issue_shown(
        self, temp_git_repo, isolated_worktrees, tmp_path, monkeypatch, fake_gh
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

        payload = json.dumps([{"number": 11, "title": "Slow path issue"}])
        fake_gh.script(("gh", "issue", "list"), returncode=0, stdout=payload)

        items, _selection = _build_fuzzy_items(temp_git_repo)

        issue_items = [i for i in items if i.value.startswith(ACTION_ISSUE_PREFIX)]
        assert len(issue_items) == 1
        assert "11" in issue_items[0].text

        rt_mod._runtime_settings = None


class TestBuildFuzzyItemsSlow:
    """_build_fuzzy_items performs real dirty checks and fetches GitHub issues.

    github.fetch_issues is disabled via .hive.yml for these tests so no real
    `gh` subprocess is invoked (see test_git_github.py for that surface).
    """

    def _disable_github_issues(self, repo: Path) -> None:
        (repo / ".hive.yml").write_text("github:\n  fetch_issues: false\n")
        reload_config()

    def test_dirty_worktree_marked(
        self, temp_git_repo, make_worktree, isolated_worktrees
    ):
        self._disable_github_issues(temp_git_repo)
        wt_path = make_worktree("feat-b")
        (wt_path / "dirty.txt").write_text("uncommitted")

        items, _selection = _build_fuzzy_items(temp_git_repo)
        by_value = {item.value: item for item in items}

        assert by_value["feat-b"].style == "yellow"
        assert by_value["feat-b"].meta == "(dirty)"

    def test_clean_worktree_not_marked_dirty(
        self, temp_git_repo, make_worktree, isolated_worktrees
    ):
        self._disable_github_issues(temp_git_repo)
        make_worktree("feat-a")

        items, _selection = _build_fuzzy_items(temp_git_repo)
        by_value = {item.value: item for item in items}

        assert by_value["feat-a"].style == "green"
        assert by_value["feat-a"].meta == ""

    def test_current_dirty_worktree_meta(
        self, temp_git_repo, make_worktree, isolated_worktrees
    ):
        self._disable_github_issues(temp_git_repo)
        wt_path = make_worktree("feat-a")
        (wt_path / "dirty.txt").write_text("uncommitted")

        items, _selection = _build_fuzzy_items(
            temp_git_repo, current_worktree_branch="feat-a"
        )
        by_value = {item.value: item for item in items}
        assert by_value["feat-a"].meta == "← current (dirty)"
