"""Tests for hive_cli.ui.pickers.editors.select_editor.

get_available_editors/open_in_editor themselves are tested in
test_services_editors.py, moved with their code.
"""

from __future__ import annotations

from unittest.mock import patch

from hive_cli.ui.pickers.editors import select_editor


class TestSelectEditorNoneAvailable:
    def test_returns_none_and_reports_error(self):
        with patch("hive_cli.services.editors.shutil.which", return_value=None):
            assert select_editor() is None


class TestSelectEditorSingleAvailable:
    def test_returns_the_only_editor_without_prompting(self):
        def fake_which(cmd):
            return "/usr/bin/code" if cmd == "code" else None

        with (
            patch("hive_cli.services.editors.shutil.which", side_effect=fake_which),
            patch("hive_cli.ui.pickers.editors.fuzzy_select") as mock_select,
        ):
            result = select_editor()

        assert result.command == "code"
        mock_select.assert_not_called()


class TestSelectEditorMultipleAvailable:
    def test_prompts_and_returns_chosen_editor(self):
        with (
            patch("hive_cli.services.editors.shutil.which", return_value="/usr/bin/x"),
            patch("hive_cli.ui.pickers.editors.fuzzy_select", return_value="cursor"),
        ):
            result = select_editor()

        assert result.command == "cursor"

    def test_cancelled_returns_none(self):
        with (
            patch("hive_cli.services.editors.shutil.which", return_value="/usr/bin/x"),
            patch("hive_cli.ui.pickers.editors.fuzzy_select", return_value=None),
        ):
            assert select_editor() is None
