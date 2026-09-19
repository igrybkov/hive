"""Tests for hive_cli.agents.launch: extra-dirs args and hook injection.

get_extra_dirs_args is pure: resolving extra_dirs (override vs
settings.extra_dirs, expand_path against main_repo) is the caller's job
(commands/run.py:_resolved_extra_dirs, tested in test_run.py) since it needs
the git layer, which agents/launch.py no longer depends on (A0 step 9:
agents -> git layering fix).
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from hive_cli.agents.launch import get_extra_dirs_args, hive_hook_path, hook_args
from hive_cli.config import (
    AgentConfig,
    AgentHooksConfig,
    AgentsConfig,
    HiveSettings,
    HooksConfig,
    load_config,
)
from hive_cli.core.errors import HiveError
from hive_cli.hooks.templates import claude_settings


class TestGetExtraDirsArgs:
    """Tests for get_extra_dirs_args helper."""

    def test_empty_when_no_dirs(self, tmp_path, monkeypatch):
        """Returns empty list when no resolved dirs are given."""
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)

        load_config.cache_clear()
        with patch("hive_cli.config.loader.find_config_files", return_value=[]):
            result = get_extra_dirs_args("claude", [])

        assert result == []

    def test_empty_when_agent_has_no_flag(self, tmp_path, monkeypatch):
        """Returns empty list when agent has no extra_dirs_flag, even with dirs."""
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)

        load_config.cache_clear()
        with patch("hive_cli.config.loader.find_config_files", return_value=[]):
            result = get_extra_dirs_args("unknown-agent", ["/some/dir"])

        assert result == []

    def test_builds_flag_path_pairs(self, tmp_path, monkeypatch):
        """Builds [flag, path, flag, path] pairs for resolved dirs."""
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)

        load_config.cache_clear()
        with patch("hive_cli.config.loader.find_config_files", return_value=[]):
            result = get_extra_dirs_args("claude", ["/abs/dir1", "/abs/dir2"])

        assert result == ["--add-dir", "/abs/dir1", "--add-dir", "/abs/dir2"]


def _settings(*, enabled: bool, configs: dict[str, AgentConfig] | None = None):
    return HiveSettings(
        hooks=HooksConfig(enabled=enabled),
        agents=AgentsConfig(configs=configs or {}),
    )


class TestHookArgs:
    """Tests for hive_cli.agents.launch.hook_args."""

    def test_disabled_returns_empty(self):
        settings = _settings(
            enabled=False,
            configs={"claude": AgentConfig(hooks=AgentHooksConfig(mode="cli"))},
        )
        assert hook_args("claude", hive_hook="/x/hive-hook", settings=settings) == []

    def test_claude_returns_settings_flag(self):
        settings = _settings(
            enabled=True,
            configs={"claude": AgentConfig(hooks=AgentHooksConfig(mode="cli"))},
        )
        result = hook_args("claude", hive_hook="/x/hive-hook", settings=settings)
        assert result[0] == "--settings"
        assert json.loads(result[1]) == claude_settings("/x/hive-hook")

    def test_codex_returns_notify_flag(self):
        settings = _settings(
            enabled=True,
            configs={"codex": AgentConfig(hooks=AgentHooksConfig(mode="cli"))},
        )
        result = hook_args("codex", hive_hook="/x/hive-hook", settings=settings)
        assert result == ["-c", 'notify=["/x/hive-hook","codex"]']

    def test_profile_mode_returns_empty(self):
        """Gemini's 'profile' mode is wired via agents/profiles.py, not CLI args."""
        settings = _settings(
            enabled=True,
            configs={"gemini": AgentConfig(hooks=AgentHooksConfig(mode="profile"))},
        )
        assert hook_args("gemini", hive_hook="/x/hive-hook", settings=settings) == []

    def test_unsupported_mode_returns_empty(self):
        settings = _settings(
            enabled=True,
            configs={
                "copilot": AgentConfig(hooks=AgentHooksConfig(mode="unsupported"))
            },
        )
        assert hook_args("copilot", hive_hook="/x/hive-hook", settings=settings) == []

    def test_agent_missing_from_configs_returns_empty(self):
        settings = _settings(enabled=True, configs={})
        assert hook_args("claude", hive_hook="/x/hive-hook", settings=settings) == []


class TestHiveHookPath:
    """Tests for hive_cli.agents.launch.hive_hook_path."""

    def test_found_on_path(self):
        with patch("shutil.which", return_value="/usr/local/bin/hive-hook"):
            assert hive_hook_path() == "/usr/local/bin/hive-hook"

    def test_falls_back_to_hive_sibling(self, tmp_path):
        (tmp_path / "hive-hook").touch()
        with (
            patch("shutil.which", return_value=None),
            patch(
                "hive_cli.agents.launch.paths.hive_executable",
                return_value=str(tmp_path / "hive"),
            ),
        ):
            assert hive_hook_path() == str(tmp_path / "hive-hook")

    def test_raises_when_neither_exists(self, tmp_path):
        with (
            patch("shutil.which", return_value=None),
            patch(
                "hive_cli.agents.launch.paths.hive_executable",
                return_value=str(tmp_path / "hive"),
            ),
        ):
            with pytest.raises(HiveError):
                hive_hook_path()
