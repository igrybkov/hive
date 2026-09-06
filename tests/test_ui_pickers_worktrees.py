"""Tests for the state-threading seam in ui/pickers/worktrees.py:pick_worktree.

pick_worktree itself has no direct tests (only test_wt_cli.py mocking it out
entirely), so these pin the exact behavior the A0 wt.py pass's extraction of
_PickerState / _handle_context_action / _handle_open_in_editor introduced:
that toggling skip-permissions flips both the loop-local state and the
runtime settings mirror, and that opening a branch in an editor threads the
branch back into state.preselect_branch for the next loop iteration.
"""

from __future__ import annotations

from unittest.mock import patch

from hive_cli.config.runtime import RuntimeSettings
from hive_cli.ui.console import info
from hive_cli.ui.pickers.worktrees import (
    ACTION_TOGGLE_SKIP_PERMISSIONS,
    _handle_context_action,
    _handle_open_in_editor,
    _PickerState,
)


class TestHandleContextActionSkipPermissions:
    def test_toggle_flips_state_and_runtime(self):
        rt = RuntimeSettings()
        rt.skip_permissions = False
        state = _PickerState(
            selected_agent="claude", skip_permissions=False, preselect_branch=None
        )

        handled = _handle_context_action(ACTION_TOGGLE_SKIP_PERMISSIONS, rt, state)

        assert handled is True
        assert state.skip_permissions is True
        assert rt.skip_permissions is True

    def test_toggle_twice_returns_to_original(self):
        rt = RuntimeSettings()
        rt.skip_permissions = False
        state = _PickerState(
            selected_agent="claude", skip_permissions=False, preselect_branch=None
        )

        _handle_context_action(ACTION_TOGGLE_SKIP_PERMISSIONS, rt, state)
        _handle_context_action(ACTION_TOGGLE_SKIP_PERMISSIONS, rt, state)

        assert state.skip_permissions is False
        assert rt.skip_permissions is False


class TestHandleOpenInEditor:
    def test_sets_preselect_branch_for_existing_worktree(self, tmp_path):
        main_repo = tmp_path / "main"
        main_repo.mkdir()
        worktree_path = tmp_path / "wt"
        worktree_path.mkdir()
        state = _PickerState(
            selected_agent="claude", skip_permissions=False, preselect_branch=None
        )

        with (
            patch(
                "hive_cli.ui.pickers.worktrees.get_worktree_path",
                return_value=worktree_path,
            ),
            patch("hive_cli.ui.pickers.worktrees.select_editor", return_value="code"),
            patch("hive_cli.services.editors.open_in_editor") as mock_open,
        ):
            _handle_open_in_editor("__open_in_editor__:feature-x", main_repo, 1, state)

        mock_open.assert_called_once_with(worktree_path, "code", progress=info)
        assert state.preselect_branch == "feature-x"

    def test_no_editor_selected_leaves_preselect_branch_unset(self, tmp_path):
        main_repo = tmp_path / "main"
        main_repo.mkdir()
        worktree_path = tmp_path / "wt"
        worktree_path.mkdir()
        state = _PickerState(
            selected_agent="claude", skip_permissions=False, preselect_branch=None
        )

        with (
            patch(
                "hive_cli.ui.pickers.worktrees.get_worktree_path",
                return_value=worktree_path,
            ),
            patch("hive_cli.ui.pickers.worktrees.select_editor", return_value=None),
            patch("hive_cli.services.editors.open_in_editor") as mock_open,
        ):
            _handle_open_in_editor("__open_in_editor__:feature-x", main_repo, 1, state)

        mock_open.assert_not_called()
        assert state.preselect_branch is None
