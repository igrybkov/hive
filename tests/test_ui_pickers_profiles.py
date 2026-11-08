"""Tests for hive_cli.ui.pickers.profiles.select_profile."""

from __future__ import annotations

from unittest.mock import patch

from hive_cli.config import reset_settings
from hive_cli.ui.pickers.profiles import (
    DEFAULT_PROFILE_VALUE,
    NEW_PROFILE_ITEM_VALUE,
    select_profile,
)


class TestSelectProfile:
    """Tests for select_profile() picker function."""

    def setup_method(self):
        reset_settings()

    def teardown_method(self):
        reset_settings()

    def test_unsupported_agent_returns_none_and_warns(
        self, monkeypatch, tmp_path, capsys
    ):
        """Unknown agent prints warning and returns None."""
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        with patch("hive_cli.config.loader.find_config_files", return_value=[]):
            result = select_profile("unknown-agent")
        assert result is None

    def test_returns_none_on_cancel(self, monkeypatch, tmp_path):
        """Cancelled picker (fuzzy_select returns None) → None."""
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        with (
            patch("hive_cli.config.loader.find_config_files", return_value=[]),
            patch("hive_cli.ui.pickers.profiles.fuzzy_select", return_value=None),
        ):
            result = select_profile("claude")
        assert result is None

    def test_returns_empty_string_for_default(self, monkeypatch, tmp_path):
        """Selecting <default> returns empty string (passthrough)."""
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        with (
            patch("hive_cli.config.loader.find_config_files", return_value=[]),
            patch(
                "hive_cli.ui.pickers.profiles.fuzzy_select",
                return_value=DEFAULT_PROFILE_VALUE,
            ),
        ):
            result = select_profile("claude")
        assert result == ""

    def test_returns_profile_name_when_selected(self, monkeypatch, tmp_path):
        """Selecting an existing profile returns its name."""
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        (tmp_path / "hive" / "profiles" / "claude" / "work").mkdir(parents=True)
        with (
            patch("hive_cli.config.loader.find_config_files", return_value=[]),
            patch("hive_cli.ui.pickers.profiles.fuzzy_select", return_value="work"),
        ):
            result = select_profile("claude", current_profile="work")
        assert result == "work"

    def test_new_profile_flow(self, monkeypatch, tmp_path):
        """Selecting ＋ new profile… triggers creation and returns the new name."""
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        with (
            patch("hive_cli.config.loader.find_config_files", return_value=[]),
            patch(
                "hive_cli.ui.pickers.profiles.fuzzy_select",
                return_value=NEW_PROFILE_ITEM_VALUE,
            ),
            patch("builtins.input", return_value="personal"),
        ):
            result = select_profile("claude")
        assert result == "personal"
        assert (tmp_path / "hive" / "profiles" / "claude" / "personal").is_dir()

    def test_new_profile_invalid_name_returns_none(self, monkeypatch, tmp_path):
        """Invalid profile name (special chars) returns None."""
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        with (
            patch("hive_cli.config.loader.find_config_files", return_value=[]),
            patch(
                "hive_cli.ui.pickers.profiles.fuzzy_select",
                return_value=NEW_PROFILE_ITEM_VALUE,
            ),
            patch("builtins.input", return_value="my profile!"),
        ):
            result = select_profile("claude")
        assert result is None

    def test_new_profile_empty_name_returns_none(self, monkeypatch, tmp_path):
        """Empty profile name (cancel) returns None."""
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        with (
            patch("hive_cli.config.loader.find_config_files", return_value=[]),
            patch(
                "hive_cli.ui.pickers.profiles.fuzzy_select",
                return_value=NEW_PROFILE_ITEM_VALUE,
            ),
            patch("builtins.input", return_value=""),
        ):
            result = select_profile("claude")
        assert result is None
