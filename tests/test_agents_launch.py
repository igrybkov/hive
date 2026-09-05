"""Tests for hive_cli.agents.launch (argv/env assembly for launching an agent).

Moved from tests/test_config.py:TestGetExtraDirsArgs when get_extra_dirs_args
moved to agents/launch.py (A0 step 3, config purity). Patch targets are
unchanged: the function still reads settings via hive_cli.config.loader and
resolves main_repo via hive_cli.git.get_main_repo (a deliberate, documented
architecture-guard violation until the F5-adjacent step that gives this
function a main_repo parameter instead — see the A0 commit for get_extra_dirs_args).
"""

from __future__ import annotations

from unittest.mock import patch

from hive_cli.agents.launch import get_extra_dirs_args
from hive_cli.config import load_config


class TestGetExtraDirsArgs:
    """Tests for get_extra_dirs_args helper."""

    def test_empty_when_no_dirs(self, tmp_path, monkeypatch):
        """Returns empty list when no extra_dirs configured."""
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)

        load_config.cache_clear()
        with patch("hive_cli.config.loader.find_config_files", return_value=[]):
            result = get_extra_dirs_args("claude")

        assert result == []

    def test_empty_when_agent_has_no_flag(self, tmp_path, monkeypatch):
        """Returns empty list when agent has no extra_dirs_flag."""
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)

        config_file = tmp_path / ".hive.yml"
        config_file.write_text("""
extra_dirs:
  - /some/dir
""")

        load_config.cache_clear()
        with patch(
            "hive_cli.config.loader.find_config_files", return_value=[config_file]
        ):
            result = get_extra_dirs_args("unknown-agent")

        assert result == []

    def test_builds_flag_path_pairs(self, tmp_path, monkeypatch):
        """Builds [flag, path, flag, path] pairs for absolute dirs."""
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)

        config_file = tmp_path / ".hive.yml"
        config_file.write_text("""
extra_dirs:
  - /abs/dir1
  - /abs/dir2
""")

        load_config.cache_clear()
        with (
            patch(
                "hive_cli.config.loader.find_config_files", return_value=[config_file]
            ),
            patch("hive_cli.git.get_main_repo", return_value=tmp_path),
        ):
            result = get_extra_dirs_args("claude")

        assert result == ["--add-dir", "/abs/dir1", "--add-dir", "/abs/dir2"]

    def test_relative_paths_resolve_against_main_repo(self, tmp_path, monkeypatch):
        """Relative paths are resolved against main repo root."""
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)

        main_repo = tmp_path / "main-repo"
        main_repo.mkdir()

        config_file = tmp_path / ".hive.yml"
        config_file.write_text("""
extra_dirs:
  - ../sibling
""")

        load_config.cache_clear()
        with (
            patch(
                "hive_cli.config.loader.find_config_files", return_value=[config_file]
            ),
            patch("hive_cli.git.get_main_repo", return_value=main_repo),
        ):
            result = get_extra_dirs_args("claude")

        assert result == ["--add-dir", str(tmp_path / "sibling")]

    def test_runtime_override_replaces_configured_dirs(self, tmp_path, monkeypatch):
        """When rt.workdir_extras_override is set, it replaces settings.extra_dirs."""
        from hive_cli.config import get_runtime_settings

        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)

        config_file = tmp_path / ".hive.yml"
        config_file.write_text("""
extra_dirs:
  - /configured/dir
""")

        load_config.cache_clear()
        rt = get_runtime_settings()
        rt.workdir_extras_override = ["/runtime/one", "/runtime/two"]
        try:
            with (
                patch(
                    "hive_cli.config.loader.find_config_files",
                    return_value=[config_file],
                ),
                patch("hive_cli.git.get_main_repo", return_value=tmp_path),
            ):
                result = get_extra_dirs_args("claude")
        finally:
            rt.workdir_extras_override = None

        assert result == [
            "--add-dir",
            "/runtime/one",
            "--add-dir",
            "/runtime/two",
        ]

    def test_runtime_override_empty_list_produces_no_args(self, tmp_path, monkeypatch):
        """Empty override list drops all extras even if config has dirs."""
        from hive_cli.config import get_runtime_settings

        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)

        config_file = tmp_path / ".hive.yml"
        config_file.write_text("""
extra_dirs:
  - /configured/dir
""")

        load_config.cache_clear()
        rt = get_runtime_settings()
        rt.workdir_extras_override = []
        try:
            with (
                patch(
                    "hive_cli.config.loader.find_config_files",
                    return_value=[config_file],
                ),
                patch("hive_cli.git.get_main_repo", return_value=tmp_path),
            ):
                result = get_extra_dirs_args("claude")
        finally:
            rt.workdir_extras_override = None

        assert result == []
