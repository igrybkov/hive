"""Tests for hive_cli.ui.tty."""

from __future__ import annotations

import io
from unittest.mock import patch

from hive_cli.ui.tty import confirm, read_single_key


class TestConfirm:
    def test_yes_returns_true(self):
        with patch("hive_cli.ui.tty.read_single_key", return_value="y"):
            assert confirm("Proceed?") is True

    def test_uppercase_yes_returns_true(self):
        with patch("hive_cli.ui.tty.read_single_key", return_value="Y"):
            assert confirm("Proceed?") is True

    def test_no_returns_false(self):
        with patch("hive_cli.ui.tty.read_single_key", return_value="n"):
            assert confirm("Proceed?", default=True) is False

    def test_enter_uses_default_true(self):
        with patch("hive_cli.ui.tty.read_single_key", return_value="\r"):
            assert confirm("Proceed?", default=True) is True

    def test_enter_uses_default_false(self):
        with patch("hive_cli.ui.tty.read_single_key", return_value="\n"):
            assert confirm("Proceed?", default=False) is False

    def test_unrecognized_key_returns_false(self):
        with patch("hive_cli.ui.tty.read_single_key", return_value="x"):
            assert confirm("Proceed?", default=True) is False

    def test_no_key_available_returns_false(self):
        with patch("hive_cli.ui.tty.read_single_key", return_value=None):
            assert confirm("Proceed?", default=True) is False


class TestReadSingleKey:
    def test_dev_tty_unavailable_returns_none(self):
        # In sandboxed/CI environments /dev/tty typically has no controlling
        # terminal, so open() raises OSError and read_single_key degrades
        # gracefully to None rather than raising.
        assert read_single_key() is None

    def test_returns_typed_character_when_tty_available(self, monkeypatch):
        """Simulate a real /dev/tty by faking open() + termios for this module."""

        class FakeTtyFile(io.StringIO):
            def fileno(self):
                return 99

        fake_file = FakeTtyFile("q")

        def fake_open(path, *args, **kwargs):
            if path == "/dev/tty":
                return fake_file
            raise AssertionError(f"unexpected open() call: {path}")

        monkeypatch.setattr("hive_cli.ui.tty.open", fake_open, raising=False)
        with (
            patch("termios.tcgetattr", return_value="fake-settings"),
            patch("termios.tcsetattr"),
            patch("tty.setraw"),
        ):
            assert read_single_key() == "q"

    def test_termios_failure_returns_none(self, monkeypatch):
        class FakeTtyFile(io.StringIO):
            def fileno(self):
                return 99

        fake_file = FakeTtyFile("q")

        def fake_open(path, *args, **kwargs):
            return fake_file

        monkeypatch.setattr("hive_cli.ui.tty.open", fake_open, raising=False)
        with patch("termios.tcgetattr", side_effect=OSError("no tty attrs")):
            assert read_single_key() is None
