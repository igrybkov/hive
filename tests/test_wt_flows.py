"""Tests for wt.py picker item-building, worktree flows, and CLI subcommands."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from conftest import git

from hive_cli.commands.wt import (
    ACTION_ISSUE_PREFIX,
    GitHubIssue,
    GitHubIssueDetails,
    _build_fuzzy_items,
    _build_fuzzy_items_fast,
    _complete_branch,
    _create_worktree_flow,
    _delete_worktree_flow,
    _get_issues_cache_path,
    _issue_branch_flow,
    _new_branch_flow,
    _save_cached_issues,
    _setup_agent_context,
)
from hive_cli.config import reload_config
from hive_cli.git import get_current_branch, worktree_exists

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

        cache_path = _get_issues_cache_path(temp_git_repo)
        _save_cached_issues([GitHubIssue(number=9, title="Do the thing")], cache_path)

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

        cache_path = _get_issues_cache_path(temp_git_repo)
        _save_cached_issues([GitHubIssue(number=9, title="Do the thing")], cache_path)
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
        cache_path = _get_issues_cache_path(temp_git_repo)
        _save_cached_issues([GitHubIssue(number=1, title=long_title)], cache_path)

        items, _selection = _build_fuzzy_items_fast(temp_git_repo)
        issue_items = [i for i in items if i.value.startswith(ACTION_ISSUE_PREFIX)]

        assert issue_items[0].text.endswith("...")
        assert long_title not in issue_items[0].text

        rt_mod._runtime_settings = None


class TestBuildFuzzyItemsSlowGithubIssues:
    """_build_fuzzy_items' live GitHub fetch, with only the `gh` call faked.

    Real git commands (e.g. `git remote get-url origin`) still run for real —
    the hard rule is "never mock git", so the subprocess.run patch below
    only intercepts calls whose argv starts with "gh".
    """

    def test_fetched_issue_shown(
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

        payload = json.dumps([{"number": 11, "title": "Slow path issue"}])
        mock_result = MagicMock(returncode=0, stdout=payload)
        real_run = subprocess.run

        def fake_run(cmd, *args, **kwargs):
            if cmd[0] == "gh":
                return mock_result
            return real_run(cmd, *args, **kwargs)

        with patch("hive_cli.commands.wt.subprocess.run", side_effect=fake_run):
            items, _selection = _build_fuzzy_items(temp_git_repo)

        issue_items = [i for i in items if i.value.startswith(ACTION_ISSUE_PREFIX)]
        assert len(issue_items) == 1
        assert "11" in issue_items[0].text

        rt_mod._runtime_settings = None


class TestBuildFuzzyItemsSlow:
    """_build_fuzzy_items performs real dirty checks and fetches GitHub issues.

    github.fetch_issues is disabled via .hive.yml for these tests so no real
    `gh` subprocess is invoked (see test_wt_github.py for that surface).
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


# ---------------------------------------------------------------------------
# _create_worktree_flow / _setup_agent_context
# ---------------------------------------------------------------------------


class TestCreateWorktreeFlow:
    def test_creates_worktree_and_returns_path(self, temp_git_repo, isolated_worktrees):
        result = _create_worktree_flow("feat-a", temp_git_repo, agent_num=0)

        assert result is not None
        assert Path(result).exists()
        assert get_current_branch(Path(result)) == "feat-a"

    def test_agent_context_written_when_agent_num_positive(
        self, temp_git_repo, isolated_worktrees
    ):
        result = _create_worktree_flow("feat-a", temp_git_repo, agent_num=2)

        context_file = Path(result) / ".claude" / "worktree-context.md"
        assert context_file.exists()
        content = context_file.read_text()
        assert "Agent 2" in content
        assert "feat-a" in content

    def test_no_agent_context_when_agent_num_zero(
        self, temp_git_repo, isolated_worktrees
    ):
        result = _create_worktree_flow("feat-a", temp_git_repo, agent_num=0)

        context_file = Path(result) / ".claude" / "worktree-context.md"
        assert not context_file.exists()

    def test_returns_none_on_failure(self, temp_git_repo, isolated_worktrees):
        # main is not a valid branch to create a worktree for.
        result = _create_worktree_flow("main", temp_git_repo, agent_num=0)
        assert result is None


class TestPromptNewBranch:
    """_prompt_new_branch wraps prompt_toolkit.prompt; only its return-value
    handling (trim/cancel/interrupt) is unit-testable without a full TUI
    event-loop harness, so prompt_toolkit.prompt itself is mocked here.
    """

    def test_returns_stripped_input(self):
        from hive_cli.commands.wt import _prompt_new_branch

        with patch("prompt_toolkit.prompt", return_value="  my-branch  "):
            assert _prompt_new_branch() == "my-branch"

    def test_empty_result_returns_none(self):
        from hive_cli.commands.wt import _prompt_new_branch

        with patch("prompt_toolkit.prompt", return_value=""):
            assert _prompt_new_branch() is None

    def test_keyboard_interrupt_propagates(self):
        from hive_cli.commands.wt import _prompt_new_branch

        with (
            patch("prompt_toolkit.prompt", side_effect=KeyboardInterrupt),
            pytest.raises(KeyboardInterrupt),
        ):
            _prompt_new_branch()

    def test_eof_error_raises_keyboard_interrupt(self):
        from hive_cli.commands.wt import _prompt_new_branch

        with (
            patch("prompt_toolkit.prompt", side_effect=EOFError),
            pytest.raises(KeyboardInterrupt),
        ):
            _prompt_new_branch()


class TestPromptIssueBranch:
    def test_returns_typed_branch_name(self):
        from hive_cli.commands.wt import _prompt_issue_branch

        with patch("prompt_toolkit.prompt", return_value="gh-5-fix-bug"):
            assert _prompt_issue_branch(5, "Fix bug") == "gh-5-fix-bug"

    def test_unmodified_prefix_returns_none(self):
        from hive_cli.commands.wt import _prompt_issue_branch

        with patch("prompt_toolkit.prompt", return_value="gh-5-"):
            assert _prompt_issue_branch(5, "Fix bug") is None

    def test_empty_result_returns_none(self):
        from hive_cli.commands.wt import _prompt_issue_branch

        with patch("prompt_toolkit.prompt", return_value=""):
            assert _prompt_issue_branch(5, "Fix bug") is None

    def test_keyboard_interrupt_propagates(self):
        from hive_cli.commands.wt import _prompt_issue_branch

        with (
            patch("prompt_toolkit.prompt", side_effect=KeyboardInterrupt),
            pytest.raises(KeyboardInterrupt),
        ):
            _prompt_issue_branch(5, "Fix bug")


class TestNewBranchFlow:
    def test_cancelled_prompt_returns_none(self, temp_git_repo):
        with patch("hive_cli.commands.wt._prompt_new_branch", return_value=None):
            assert _new_branch_flow(temp_git_repo, agent_num=0) is None

    def test_default_branch_name_rejected(self, temp_git_repo):
        with patch("hive_cli.commands.wt._prompt_new_branch", return_value="main"):
            assert _new_branch_flow(temp_git_repo, agent_num=0) is None

    def test_existing_worktree_branch_rejected(
        self, temp_git_repo, make_worktree, isolated_worktrees
    ):
        make_worktree("feat-a")
        with patch("hive_cli.commands.wt._prompt_new_branch", return_value="feat-a"):
            assert _new_branch_flow(temp_git_repo, agent_num=0) is None

    def test_creates_worktree_for_new_branch(self, temp_git_repo, isolated_worktrees):
        with patch("hive_cli.commands.wt._prompt_new_branch", return_value="feat-new"):
            result = _new_branch_flow(temp_git_repo, agent_num=0)

        assert result is not None
        assert Path(result).exists()
        assert get_current_branch(Path(result)) == "feat-new"


class TestIssueBranchFlow:
    def test_cancelled_prompt_returns_none(self, temp_git_repo):
        with patch("hive_cli.commands.wt._prompt_issue_branch", return_value=None):
            assert _issue_branch_flow(5, "Fix bug", temp_git_repo, agent_num=0) is None

    def test_default_branch_name_rejected(self, temp_git_repo):
        with patch("hive_cli.commands.wt._prompt_issue_branch", return_value="master"):
            assert _issue_branch_flow(5, "Fix bug", temp_git_repo, agent_num=0) is None

    def test_existing_worktree_branch_rejected(
        self, temp_git_repo, make_worktree, isolated_worktrees
    ):
        make_worktree("gh-5-fix")
        with patch(
            "hive_cli.commands.wt._prompt_issue_branch", return_value="gh-5-fix"
        ):
            assert _issue_branch_flow(5, "Fix bug", temp_git_repo, agent_num=0) is None

    def test_creates_worktree_and_writes_task_file(
        self, temp_git_repo, isolated_worktrees
    ):
        details = GitHubIssueDetails(
            number=5, title="Fix bug", url="https://x/5", body="Do it"
        )
        with (
            patch("hive_cli.commands.wt._prompt_issue_branch", return_value="gh-5-fix"),
            patch("hive_cli.commands.wt._fetch_issue_details", return_value=details),
        ):
            result = _issue_branch_flow(5, "Fix bug", temp_git_repo, agent_num=0)

        assert result is not None
        task_file = Path(result) / ".claude" / "task.local.md"
        assert task_file.exists()
        assert "Fix bug" in task_file.read_text()

    def test_creates_worktree_even_if_details_fetch_fails(
        self, temp_git_repo, isolated_worktrees
    ):
        with (
            patch("hive_cli.commands.wt._prompt_issue_branch", return_value="gh-5-fix"),
            patch("hive_cli.commands.wt._fetch_issue_details", return_value=None),
        ):
            result = _issue_branch_flow(5, "Fix bug", temp_git_repo, agent_num=0)

        assert result is not None
        assert not (Path(result) / ".claude" / "task.local.md").exists()


class TestSetupAgentContext:
    def test_writes_context_file(self, tmp_path):
        _setup_agent_context(tmp_path, agent_num=3, branch_name="feat-x")

        content = (tmp_path / ".claude" / "worktree-context.md").read_text()
        assert "Agent 3" in content
        assert "feat-x" in content
        assert str(tmp_path) in content


# ---------------------------------------------------------------------------
# _delete_worktree_flow
# ---------------------------------------------------------------------------


class TestDeleteWorktreeFlow:
    def test_declines_deleting_main(self, temp_git_repo):
        result = _delete_worktree_flow("main", temp_git_repo)
        assert result is False

    def test_warns_for_nonexistent_worktree(self, temp_git_repo):
        result = _delete_worktree_flow("never-created", temp_git_repo)
        assert result is False

    def test_confirmed_deletion_removes_worktree(
        self, temp_git_repo, make_worktree, isolated_worktrees
    ):
        wt_path = make_worktree("feat-a")

        with patch("hive_cli.commands.wt.confirm", return_value=True):
            result = _delete_worktree_flow("feat-a", temp_git_repo)

        assert result is True
        assert not wt_path.exists()
        assert worktree_exists("feat-a", temp_git_repo) is False

    def test_declined_confirmation_keeps_worktree(
        self, temp_git_repo, make_worktree, isolated_worktrees
    ):
        wt_path = make_worktree("feat-a")

        with patch("hive_cli.commands.wt.confirm", return_value=False):
            result = _delete_worktree_flow("feat-a", temp_git_repo)

        assert result is False
        assert wt_path.exists()

    def test_dirty_worktree_still_deletable_when_confirmed(
        self, temp_git_repo, make_worktree, isolated_worktrees
    ):
        wt_path = make_worktree("feat-a")
        (wt_path / "uncommitted.txt").write_text("oops")

        with patch("hive_cli.commands.wt.confirm", return_value=True):
            result = _delete_worktree_flow("feat-a", temp_git_repo)

        assert result is True
        assert not wt_path.exists()

    def test_delete_exception_is_reported_and_returns_false(
        self, temp_git_repo, make_worktree, isolated_worktrees
    ):
        wt_path = make_worktree("feat-a")

        with (
            patch("hive_cli.commands.wt.confirm", return_value=True),
            patch(
                "hive_cli.commands.wt.delete_worktree",
                side_effect=RuntimeError("boom"),
            ),
        ):
            result = _delete_worktree_flow("feat-a", temp_git_repo)

        assert result is False
        # delete_worktree was mocked, so the real worktree is untouched.
        assert wt_path.exists()


class TestCompleteBranch:
    def test_returns_matching_branches(
        self, temp_git_repo, make_worktree, isolated_worktrees
    ):
        make_worktree("feature-one")
        make_worktree("feature-two")
        git("branch", "other", cwd=temp_git_repo)

        result = _complete_branch(None, None, "feature")

        assert set(result) == {"feature-one", "feature-two"}

    def test_no_match_returns_empty_list(self, temp_git_repo):
        assert _complete_branch(None, None, "nonexistent-prefix") == []

    def test_exception_returns_empty_list(self):
        with patch(
            "hive_cli.commands.wt.get_main_repo", side_effect=RuntimeError("boom")
        ):
            assert _complete_branch(None, None, "") == []
