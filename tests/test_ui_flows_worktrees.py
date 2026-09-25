"""Tests for ui/flows/worktrees.py: new-branch/issue-branch prompts, create, delete."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from hive_cli.git import get_current_branch, worktree_exists
from hive_cli.git.github import GitHubIssueDetails
from hive_cli.ui.flows.worktrees import (
    create_worktree_flow,
    delete_worktree_flow,
    issue_branch_flow,
    new_branch_flow,
)

# ---------------------------------------------------------------------------
# create_worktree_flow
# ---------------------------------------------------------------------------


class TestCreateWorktreeFlow:
    """create_worktree_flow is now a thin try/except around
    services.worktrees.provision(); provision()'s own behavior (dependency
    install, agent-context writing) is covered by test_services_worktrees.py.
    """

    def test_creates_worktree_and_returns_path(self, temp_git_repo, isolated_worktrees):
        result = create_worktree_flow("feat-a", temp_git_repo, agent_num=0)

        assert result is not None
        assert Path(result).exists()
        assert get_current_branch(Path(result)) == "feat-a"

    def test_agent_context_written_when_agent_num_positive(
        self, temp_git_repo, isolated_worktrees
    ):
        result = create_worktree_flow("feat-a", temp_git_repo, agent_num=2)

        context_file = Path(result) / ".claude" / "worktree-context.md"
        assert context_file.exists()

    def test_returns_none_on_failure(self, temp_git_repo, isolated_worktrees):
        # main is not a valid branch to create a worktree for.
        result = create_worktree_flow("main", temp_git_repo, agent_num=0)
        assert result is None


class TestPromptNewBranch:
    """_prompt_new_branch wraps prompt_toolkit.prompt; only its return-value
    handling (trim/cancel/interrupt) is unit-testable without a full TUI
    event-loop harness, so prompt_toolkit.prompt itself is mocked here.
    """

    def test_returns_stripped_input(self):
        from hive_cli.ui.flows.worktrees import _prompt_new_branch

        with patch("prompt_toolkit.prompt", return_value="  my-branch  "):
            assert _prompt_new_branch() == "my-branch"

    def test_empty_result_returns_none(self):
        from hive_cli.ui.flows.worktrees import _prompt_new_branch

        with patch("prompt_toolkit.prompt", return_value=""):
            assert _prompt_new_branch() is None

    def test_keyboard_interrupt_propagates(self):
        from hive_cli.ui.flows.worktrees import _prompt_new_branch

        with (
            patch("prompt_toolkit.prompt", side_effect=KeyboardInterrupt),
            pytest.raises(KeyboardInterrupt),
        ):
            _prompt_new_branch()

    def test_eof_error_raises_keyboard_interrupt(self):
        from hive_cli.ui.flows.worktrees import _prompt_new_branch

        with (
            patch("prompt_toolkit.prompt", side_effect=EOFError),
            pytest.raises(KeyboardInterrupt),
        ):
            _prompt_new_branch()


class TestPromptIssueBranch:
    def test_returns_typed_branch_name(self):
        from hive_cli.ui.flows.worktrees import _prompt_issue_branch

        with patch("prompt_toolkit.prompt", return_value="gh-5-fix-bug"):
            assert _prompt_issue_branch(5, "Fix bug") == "gh-5-fix-bug"

    def test_unmodified_prefix_returns_none(self):
        from hive_cli.ui.flows.worktrees import _prompt_issue_branch

        with patch("prompt_toolkit.prompt", return_value="gh-5-"):
            assert _prompt_issue_branch(5, "Fix bug") is None

    def test_empty_result_returns_none(self):
        from hive_cli.ui.flows.worktrees import _prompt_issue_branch

        with patch("prompt_toolkit.prompt", return_value=""):
            assert _prompt_issue_branch(5, "Fix bug") is None

    def test_keyboard_interrupt_propagates(self):
        from hive_cli.ui.flows.worktrees import _prompt_issue_branch

        with (
            patch("prompt_toolkit.prompt", side_effect=KeyboardInterrupt),
            pytest.raises(KeyboardInterrupt),
        ):
            _prompt_issue_branch(5, "Fix bug")


class TestNewBranchFlow:
    def test_cancelled_prompt_returns_none(self, temp_git_repo):
        with patch("hive_cli.ui.flows.worktrees._prompt_new_branch", return_value=None):
            assert new_branch_flow(temp_git_repo, agent_num=0) is None

    def test_default_branch_name_rejected(self, temp_git_repo):
        with patch(
            "hive_cli.ui.flows.worktrees._prompt_new_branch", return_value="main"
        ):
            assert new_branch_flow(temp_git_repo, agent_num=0) is None

    def test_existing_worktree_branch_rejected(
        self, temp_git_repo, make_worktree, isolated_worktrees
    ):
        make_worktree("feat-a")
        with patch(
            "hive_cli.ui.flows.worktrees._prompt_new_branch", return_value="feat-a"
        ):
            assert new_branch_flow(temp_git_repo, agent_num=0) is None

    def test_creates_worktree_for_new_branch(self, temp_git_repo, isolated_worktrees):
        with patch(
            "hive_cli.ui.flows.worktrees._prompt_new_branch", return_value="feat-new"
        ):
            result = new_branch_flow(temp_git_repo, agent_num=0)

        assert result is not None
        assert Path(result).exists()
        assert get_current_branch(Path(result)) == "feat-new"


class TestIssueBranchFlow:
    def test_cancelled_prompt_returns_none(self, temp_git_repo):
        with patch(
            "hive_cli.ui.flows.worktrees._prompt_issue_branch", return_value=None
        ):
            assert issue_branch_flow(5, "Fix bug", temp_git_repo, agent_num=0) is None

    def test_default_branch_name_rejected(self, temp_git_repo):
        with patch(
            "hive_cli.ui.flows.worktrees._prompt_issue_branch", return_value="master"
        ):
            assert issue_branch_flow(5, "Fix bug", temp_git_repo, agent_num=0) is None

    def test_existing_worktree_branch_rejected(
        self, temp_git_repo, make_worktree, isolated_worktrees
    ):
        make_worktree("gh-5-fix")
        with patch(
            "hive_cli.ui.flows.worktrees._prompt_issue_branch", return_value="gh-5-fix"
        ):
            assert issue_branch_flow(5, "Fix bug", temp_git_repo, agent_num=0) is None

    def test_creates_worktree_and_writes_task_file(
        self, temp_git_repo, isolated_worktrees
    ):
        details = GitHubIssueDetails(
            number=5, title="Fix bug", url="https://x/5", body="Do it"
        )
        with (
            patch(
                "hive_cli.ui.flows.worktrees._prompt_issue_branch",
                return_value="gh-5-fix",
            ),
            patch(
                "hive_cli.ui.flows.worktrees.fetch_issue_details", return_value=details
            ),
        ):
            result = issue_branch_flow(5, "Fix bug", temp_git_repo, agent_num=0)

        assert result is not None
        task_file = Path(result) / ".claude" / "task.local.md"
        assert task_file.exists()
        assert "Fix bug" in task_file.read_text()

    def test_creates_worktree_even_if_details_fetch_fails(
        self, temp_git_repo, isolated_worktrees
    ):
        with (
            patch(
                "hive_cli.ui.flows.worktrees._prompt_issue_branch",
                return_value="gh-5-fix",
            ),
            patch("hive_cli.ui.flows.worktrees.fetch_issue_details", return_value=None),
        ):
            result = issue_branch_flow(5, "Fix bug", temp_git_repo, agent_num=0)

        assert result is not None
        assert not (Path(result) / ".claude" / "task.local.md").exists()


# ---------------------------------------------------------------------------
# delete_worktree_flow
# ---------------------------------------------------------------------------


class TestDeleteWorktreeFlow:
    def test_declines_deleting_main(self, temp_git_repo):
        with patch("hive_cli.ui.flows.worktrees.confirm") as mock_confirm:
            result = delete_worktree_flow("main", temp_git_repo)
        assert result is False
        mock_confirm.assert_not_called()

    def test_warns_for_nonexistent_worktree(self, temp_git_repo):
        with patch("hive_cli.ui.flows.worktrees.confirm") as mock_confirm:
            result = delete_worktree_flow("never-created", temp_git_repo)
        assert result is False
        mock_confirm.assert_not_called()

    def test_confirmed_deletion_removes_worktree(
        self, temp_git_repo, make_worktree, isolated_worktrees
    ):
        wt_path = make_worktree("feat-a")

        with patch("hive_cli.ui.flows.worktrees.confirm", return_value=True):
            result = delete_worktree_flow("feat-a", temp_git_repo)

        assert result is True
        assert not wt_path.exists()
        assert worktree_exists("feat-a", temp_git_repo) is False

    def test_declined_confirmation_keeps_worktree(
        self, temp_git_repo, make_worktree, isolated_worktrees
    ):
        wt_path = make_worktree("feat-a")

        with patch("hive_cli.ui.flows.worktrees.confirm", return_value=False):
            result = delete_worktree_flow("feat-a", temp_git_repo)

        assert result is False
        assert wt_path.exists()

    def test_dirty_worktree_still_deletable_when_confirmed(
        self, temp_git_repo, make_worktree, isolated_worktrees
    ):
        wt_path = make_worktree("feat-a")
        (wt_path / "uncommitted.txt").write_text("oops")

        with patch("hive_cli.ui.flows.worktrees.confirm", return_value=True):
            result = delete_worktree_flow("feat-a", temp_git_repo)

        assert result is True
        assert not wt_path.exists()

    def test_delete_exception_is_reported_and_returns_false(
        self, temp_git_repo, make_worktree, isolated_worktrees
    ):
        wt_path = make_worktree("feat-a")

        with (
            patch("hive_cli.ui.flows.worktrees.confirm", return_value=True),
            patch(
                "hive_cli.services.worktrees.delete_worktree",
                side_effect=RuntimeError("boom"),
            ),
        ):
            result = delete_worktree_flow("feat-a", temp_git_repo)

        assert result is False
        # delete_worktree was mocked, so the real worktree is untouched.
        assert wt_path.exists()
