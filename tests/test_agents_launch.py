"""Tests for hive_cli.agents.launch.get_extra_dirs_args.

Pure now: resolving extra_dirs (override vs settings.extra_dirs, expand_path
against main_repo) is the caller's job (commands/run.py:_resolved_extra_dirs,
tested in test_run.py) since it needs the git layer, which agents/launch.py
no longer depends on (A0 step 9: agents -> git layering fix).
"""

from __future__ import annotations

from unittest.mock import patch

from hive_cli.agents.launch import get_extra_dirs_args
from hive_cli.config import load_config


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
