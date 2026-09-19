"""Tests for services/editors.py -- installed-editor discovery and launching.

Moved from test_utils_misc.py (A0 step 6): the picker (select_editor) stays
in utils/editors.py for now (moves to ui/pickers/editors.py in step 7), but
the underlying shutil.which/subprocess.Popen calls now live here.
"""

from __future__ import annotations

from unittest.mock import patch

from hive_cli.services.editors import (
    EditorConfig,
    get_available_editors,
    open_in_editor,
)


class TestGetAvailableEditors:
    def test_filters_to_installed_editors(self):
        def fake_which(cmd):
            return "/usr/bin/code" if cmd == "code" else None

        with patch("hive_cli.services.editors.shutil.which", side_effect=fake_which):
            available = get_available_editors()

        assert [e.command for e in available] == ["code"]

    def test_no_editors_installed_returns_empty(self):
        with patch("hive_cli.services.editors.shutil.which", return_value=None):
            assert get_available_editors() == []

    def test_all_editors_installed(self):
        with patch("hive_cli.services.editors.shutil.which", return_value="/usr/bin/x"):
            available = get_available_editors()
        assert {e.command for e in available} == {"code", "pycharm", "cursor"}


class TestOpenInEditor:
    def test_opens_with_chat_flag_when_present(self, tmp_path):
        editor = EditorConfig("Cursor", "cursor", "--new-window")
        with patch("hive_cli.services.editors.subprocess.Popen") as mock_popen:
            open_in_editor(tmp_path, editor)

        args, kwargs = mock_popen.call_args
        assert args[0] == ["cursor", "--new-window", str(tmp_path)]
        assert kwargs["start_new_session"] is True

    def test_opens_without_chat_flag(self, tmp_path):
        editor = EditorConfig("VS Code", "code", None)
        with patch("hive_cli.services.editors.subprocess.Popen") as mock_popen:
            open_in_editor(tmp_path, editor)

        args, _kwargs = mock_popen.call_args
        assert args[0] == ["code", str(tmp_path)]
