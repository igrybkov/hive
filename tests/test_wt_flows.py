"""Tests for commands/wt.py's remaining private helper: shell completion.

The picker item-builders and interactive flows that used to live here moved
to test_ui_pickers_worktrees.py and test_ui_flows_worktrees.py respectively
(A0 wt.py pass).
"""

from __future__ import annotations

from unittest.mock import patch

from conftest import git

from hive_cli.commands.wt import _complete_branch


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
