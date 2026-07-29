"""Tests for the configuration module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from hive_cli.config import (
    KNOWN_AGENTS,
    AgentConfig,
    deep_merge,
    find_config_files,
    find_global_config,
    get_extra_dirs_args,
    get_xdg_config_home,
    load_config,
    reload_config,
)


class TestDeepMerge:
    """Tests for the deep_merge utility function."""

    def test_merge_flat_dicts(self):
        """Merge two flat dictionaries."""
        base = {"a": 1, "b": 2}
        override = {"b": 3, "c": 4}
        result = deep_merge(base, override)
        assert result == {"a": 1, "b": 3, "c": 4}

    def test_merge_nested_dicts(self):
        """Nested dicts are merged recursively."""
        base = {"a": {"b": 1, "c": 2}}
        override = {"a": {"c": 3, "d": 4}}
        result = deep_merge(base, override)
        assert result == {"a": {"b": 1, "c": 3, "d": 4}}

    def test_lists_are_replaced(self):
        """Lists are replaced, not merged."""
        base = {"a": [1, 2, 3]}
        override = {"a": [4, 5]}
        result = deep_merge(base, override)
        assert result == {"a": [4, 5]}

    def test_base_not_modified(self):
        """Original dictionaries are not modified."""
        base = {"a": 1}
        override = {"b": 2}
        _ = deep_merge(base, override)
        assert base == {"a": 1}
        assert override == {"b": 2}

    def test_deeply_nested(self):
        """Test deeply nested structure."""
        base = {"a": {"b": {"c": 1}}}
        override = {"a": {"b": {"d": 2}}}
        result = deep_merge(base, override)
        assert result == {"a": {"b": {"c": 1, "d": 2}}}


class TestXDGConfigHome:
    """Tests for XDG config home resolution."""

    def test_default_config_home(self, monkeypatch):
        """Default to ~/.config when XDG_CONFIG_HOME not set."""
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        result = get_xdg_config_home()
        assert result == Path.home() / ".config"

    def test_custom_config_home(self, monkeypatch):
        """Use XDG_CONFIG_HOME when set."""
        monkeypatch.setenv("XDG_CONFIG_HOME", "/custom/config")
        result = get_xdg_config_home()
        assert result == Path("/custom/config")


class TestFindGlobalConfig:
    """Tests for global config file discovery."""

    def test_no_global_config(self, tmp_path, monkeypatch):
        """Returns None when no global config exists."""
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        result = find_global_config()
        assert result is None

    def test_find_hive_yml(self, tmp_path, monkeypatch):
        """Finds hive.yml in config directory."""
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        hive_dir = tmp_path / "hive"
        hive_dir.mkdir()
        config_file = hive_dir / "hive.yml"
        config_file.write_text("agents:\n  order: [claude]\n")
        result = find_global_config()
        assert result == config_file

    def test_find_hive_yaml(self, tmp_path, monkeypatch):
        """Finds hive.yaml in config directory."""
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        hive_dir = tmp_path / "hive"
        hive_dir.mkdir()
        config_file = hive_dir / "hive.yaml"
        config_file.write_text("agents:\n  order: [gemini]\n")
        result = find_global_config()
        assert result == config_file

    def test_yml_takes_precedence(self, tmp_path, monkeypatch):
        """hive.yml takes precedence over hive.yaml."""
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        hive_dir = tmp_path / "hive"
        hive_dir.mkdir()
        yml_file = hive_dir / "hive.yml"
        yaml_file = hive_dir / "hive.yaml"
        yml_file.write_text("agents:\n  order: [claude]\n")
        yaml_file.write_text("agents:\n  order: [gemini]\n")
        result = find_global_config()
        assert result == yml_file


class TestFindConfigFiles:
    """Tests for config file discovery."""

    def test_no_git_root(self, tmp_path, monkeypatch):
        """Returns empty list when not in git repo."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        # No .git directory, so find_git_root returns None
        result = find_config_files(git_root=None)
        # May return global config if it exists, but no project config
        assert all(
            not str(p).startswith(str(tmp_path))
            for p in result
            if ".config" not in str(p)
        )

    def test_finds_hive_yml(self, tmp_path, monkeypatch):
        """Finds .hive.yml in git root."""
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        config_file = tmp_path / ".hive.yml"
        config_file.write_text("agents:\n  order: [claude]\n")
        result = find_config_files(git_root=tmp_path)
        assert config_file in result

    def test_finds_hive_local_yml(self, tmp_path, monkeypatch):
        """Finds .hive.local.yml in git root."""
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        config_file = tmp_path / ".hive.local.yml"
        config_file.write_text("resume:\n  enabled: true\n")
        result = find_config_files(git_root=tmp_path)
        assert config_file in result

    def test_precedence_order(self, tmp_path, monkeypatch):
        """Files returned in correct precedence order."""
        # Set up XDG config
        xdg_dir = tmp_path / "xdg"
        xdg_dir.mkdir()
        monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg_dir))
        hive_dir = xdg_dir / "hive"
        hive_dir.mkdir()
        global_config = hive_dir / "hive.yml"
        global_config.write_text("agents:\n  order: [gemini]\n")

        # Set up project config
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        project_config = project_dir / ".hive.yml"
        project_config.write_text("agents:\n  order: [claude]\n")
        local_config = project_dir / ".hive.local.yml"
        local_config.write_text("resume:\n  enabled: true\n")

        result = find_config_files(git_root=project_dir)

        # Order should be: global, project, local
        assert result == [global_config, project_config, local_config]


class TestLoadConfig:
    """Tests for configuration loading."""

    def test_default_config(self, tmp_path, monkeypatch):
        """Returns default config when no files exist."""
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        monkeypatch.delenv("HIVE_AGENTS_ORDER", raising=False)

        # Clear cache and mock find_config_files to return empty
        reload_config.cache_clear() if hasattr(reload_config, "cache_clear") else None
        load_config.cache_clear()

        with patch("hive_cli.config.loader.find_config_files", return_value=[]):
            config = load_config()

        assert config.agents.order == KNOWN_AGENTS
        assert config.resume.enabled is False
        assert config.worktrees.enabled is True
        assert config.worktrees.parent_dir == "~/.worktrees/{repo}/{branch}"
        assert config.zellij.layout == "agent"  # Default layout from default.yml

    def test_config_from_file(self, tmp_path, monkeypatch):
        """Loads config from file."""
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        monkeypatch.delenv("HIVE_AGENTS_ORDER", raising=False)

        config_file = tmp_path / ".hive.yml"
        config_file.write_text("""
agents:
  order: [gemini, claude]
resume:
  enabled: true
worktrees:
  parent_dir: ".wt"
zellij:
  layout: "custom-layout"
""")

        load_config.cache_clear()
        with patch(
            "hive_cli.config.loader.find_config_files", return_value=[config_file]
        ):
            config = load_config()

        assert config.agents.order == ["gemini", "claude"]
        assert config.resume.enabled is True
        assert config.worktrees.parent_dir == ".wt"
        assert config.zellij.layout == "custom-layout"

    def test_local_overrides_project(self, tmp_path, monkeypatch):
        """Local config overrides project config."""
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        monkeypatch.delenv("HIVE_AGENTS_ORDER", raising=False)

        project_config = tmp_path / ".hive.yml"
        project_config.write_text("""
agents:
  order: [gemini, claude]
resume:
  enabled: false
""")

        local_config = tmp_path / ".hive.local.yml"
        local_config.write_text("""
resume:
  enabled: true
""")

        load_config.cache_clear()
        with patch(
            "hive_cli.config.loader.find_config_files",
            return_value=[project_config, local_config],
        ):
            config = load_config()

        # agents.order from project config (not overridden)
        assert config.agents.order == ["gemini", "claude"]
        # resume.enabled overridden by local
        assert config.resume.enabled is True

    def test_env_var_fallback(self, tmp_path, monkeypatch):
        """Environment variables used as fallback."""
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        monkeypatch.setenv("HIVE_AGENTS_ORDER", "codex,claude")

        load_config.cache_clear()
        with patch("hive_cli.config.loader.find_config_files", return_value=[]):
            config = load_config()

        assert config.agents.order == ["codex", "claude"]

    def test_env_overrides_config(self, tmp_path, monkeypatch):
        """Environment variables take precedence over config files."""
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        monkeypatch.setenv("HIVE_AGENTS_ORDER", "codex,claude")

        config_file = tmp_path / ".hive.yml"
        config_file.write_text("""
agents:
  order: [gemini]
""")

        load_config.cache_clear()
        with patch(
            "hive_cli.config.loader.find_config_files", return_value=[config_file]
        ):
            config = load_config()

        # Environment variable takes precedence over config file
        assert config.agents.order == ["codex", "claude"]

    def test_hive_worktrees_enabled_env(self, tmp_path, monkeypatch):
        """HIVE_WORKTREES_ENABLED env var works."""
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        monkeypatch.setenv("HIVE_WORKTREES_ENABLED", "false")

        load_config.cache_clear()
        with patch("hive_cli.config.loader.find_config_files", return_value=[]):
            config = load_config()

        assert config.worktrees.enabled is False

    def test_hive_worktrees_parent_dir_env(self, tmp_path, monkeypatch):
        """HIVE_WORKTREES_PARENT_DIR env var works."""
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        monkeypatch.setenv("HIVE_WORKTREES_PARENT_DIR", "/custom/worktrees")

        load_config.cache_clear()
        with patch("hive_cli.config.loader.find_config_files", return_value=[]):
            config = load_config()

        assert config.worktrees.parent_dir == "/custom/worktrees"

    def test_hive_resume_enabled_env(self, tmp_path, monkeypatch):
        """HIVE_RESUME_ENABLED env var works."""
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        monkeypatch.setenv("HIVE_RESUME_ENABLED", "true")

        load_config.cache_clear()
        with patch("hive_cli.config.loader.find_config_files", return_value=[]):
            config = load_config()

        assert config.resume.enabled is True

    def test_hive_zellij_layout_env(self, tmp_path, monkeypatch):
        """HIVE_ZELLIJ_LAYOUT env var works."""
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        monkeypatch.setenv("HIVE_ZELLIJ_LAYOUT", "custom-layout")

        load_config.cache_clear()
        with patch("hive_cli.config.loader.find_config_files", return_value=[]):
            config = load_config()

        assert config.zellij.layout == "custom-layout"

    def test_hive_github_issue_limit_env(self, tmp_path, monkeypatch):
        """HIVE_GITHUB_ISSUE_LIMIT env var works."""
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        monkeypatch.setenv("HIVE_GITHUB_ISSUE_LIMIT", "50")

        load_config.cache_clear()
        with patch("hive_cli.config.loader.find_config_files", return_value=[]):
            config = load_config()

        assert config.github.issue_limit == 50


class TestAgentConfig:
    """Tests for agent-specific configuration."""

    def test_empty_resume_args_by_default(self):
        """AgentConfig dataclass has empty resume_args by default."""
        config = AgentConfig()
        assert config.resume_args == []

    def test_custom_resume_args(self):
        """Custom resume args work."""
        config = AgentConfig(resume_args=["resume", "--last"])
        assert config.resume_args == ["resume", "--last"]

    def test_claude_resume_args_from_default_config(self, tmp_path, monkeypatch):
        """Claude gets --continue from default.yml config."""
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        monkeypatch.delenv("HIVE_AGENTS_ORDER", raising=False)

        load_config.cache_clear()
        with patch("hive_cli.config.loader.find_config_files", return_value=[]):
            config = load_config()

        # Claude should have --continue from default.yml
        assert config.agents.configs.get("claude") is not None
        assert config.agents.configs["claude"].resume_args == ["--continue"]


class TestPostCreateCommands:
    """Tests for post_create command configuration."""

    def test_parse_simple_command(self, tmp_path, monkeypatch):
        """Parse simple command string."""
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)

        config_file = tmp_path / ".hive.yml"
        config_file.write_text("""
worktrees:
  post_create:
    - "npm install"
""")

        load_config.cache_clear()
        with patch(
            "hive_cli.config.loader.find_config_files", return_value=[config_file]
        ):
            config = load_config()

        assert len(config.worktrees.post_create) == 1
        assert config.worktrees.post_create[0].command == "npm install"
        assert config.worktrees.post_create[0].if_exists is None

    def test_parse_conditional_command(self, tmp_path, monkeypatch):
        """Parse command with if_exists condition."""
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)

        config_file = tmp_path / ".hive.yml"
        config_file.write_text("""
worktrees:
  post_create:
    - command: "pnpm install"
      if_exists: "pnpm-lock.yaml"
""")

        load_config.cache_clear()
        with patch(
            "hive_cli.config.loader.find_config_files", return_value=[config_file]
        ):
            config = load_config()

        assert len(config.worktrees.post_create) == 1
        assert config.worktrees.post_create[0].command == "pnpm install"
        assert config.worktrees.post_create[0].if_exists == "pnpm-lock.yaml"


class TestCaching:
    """Tests for configuration caching."""

    def test_reload_clears_cache(self, tmp_path, monkeypatch):
        """reload_config clears cache and reloads."""
        # Set XDG to empty dir to avoid picking up real global config
        empty_xdg = tmp_path / "empty_xdg"
        empty_xdg.mkdir()
        monkeypatch.setenv("XDG_CONFIG_HOME", str(empty_xdg))
        monkeypatch.delenv("HIVE_AGENTS_ORDER", raising=False)

        config_file = tmp_path / ".hive.yml"
        config_file.write_text("agents:\n  order: [claude]\n")

        load_config.cache_clear()
        with patch(
            "hive_cli.config.loader.find_config_files", return_value=[config_file]
        ):
            config1 = load_config()
            assert config1.agents.order == ["claude"]

            # Update file
            config_file.write_text("agents:\n  order: [gemini]\n")

            # Without reload, still returns cached
            config2 = load_config()
            assert config2.agents.order == ["claude"]

            # After reload, returns new value
            config3 = reload_config()
            assert config3.agents.order == ["gemini"]


class TestExtraDirsConfig:
    """Tests for extra_dirs configuration."""

    def test_default_extra_dirs_empty(self, tmp_path, monkeypatch):
        """Default config has empty extra_dirs."""
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)

        load_config.cache_clear()
        with patch("hive_cli.config.loader.find_config_files", return_value=[]):
            config = load_config()

        assert config.extra_dirs == []

    def test_extra_dirs_from_file(self, tmp_path, monkeypatch):
        """Loads extra_dirs from config file."""
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)

        config_file = tmp_path / ".hive.yml"
        config_file.write_text("""
extra_dirs:
  - ../sibling-repo
  - ~/Projects/shared-lib
  - /absolute/path
""")

        load_config.cache_clear()
        with patch(
            "hive_cli.config.loader.find_config_files", return_value=[config_file]
        ):
            config = load_config()

        assert config.extra_dirs == [
            "../sibling-repo",
            "~/Projects/shared-lib",
            "/absolute/path",
        ]

    def test_extra_dirs_flag_in_agent_config(self, tmp_path, monkeypatch):
        """Agent configs can specify extra_dirs_flag."""
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)

        config_file = tmp_path / ".hive.yml"
        config_file.write_text("""
agents:
  configs:
    claude:
      extra_dirs_flag: "--add-dir"
    agent:
      extra_dirs_flag: "--directory"
""")

        load_config.cache_clear()
        with patch(
            "hive_cli.config.loader.find_config_files", return_value=[config_file]
        ):
            config = load_config()

        assert config.agents.configs["claude"].extra_dirs_flag == "--add-dir"
        assert config.agents.configs["agent"].extra_dirs_flag == "--directory"

    def test_extra_dirs_flag_default_none(self):
        """AgentConfig extra_dirs_flag defaults to None."""
        config = AgentConfig()
        assert config.extra_dirs_flag is None

    def test_claude_extra_dirs_flag_from_defaults(self, tmp_path, monkeypatch):
        """Claude gets --add-dir from default.yml config."""
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        monkeypatch.delenv("HIVE_AGENTS_ORDER", raising=False)

        load_config.cache_clear()
        with patch("hive_cli.config.loader.find_config_files", return_value=[]):
            config = load_config()

        assert config.agents.configs["claude"].extra_dirs_flag == "--add-dir"


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


class TestRuntimeWorkdirOverride:
    """Tests for the session-scoped Ctrl+W workdir override."""

    def test_workdir_fields_default_to_none(self):
        """New RuntimeSettings has no workdir override set."""
        from hive_cli.config.runtime import RuntimeSettings

        rt = RuntimeSettings()
        assert rt.workdir is None
        assert rt.workdir_extras_override is None

    def test_workdir_not_read_from_env(self, monkeypatch):
        """$WORKDIR must not leak into the override (aliased to a synthetic name)."""
        from hive_cli.config.runtime import RuntimeSettings

        monkeypatch.setenv("WORKDIR", "/should/not/leak")
        rt = RuntimeSettings()
        assert rt.workdir is None

    def test_workdir_not_exported_to_child_env(self):
        """build_child_env must not expose the workdir override to subprocesses."""
        from pathlib import Path

        from hive_cli.config.runtime import RuntimeSettings

        rt = RuntimeSettings()
        rt.workdir = Path("/tmp/custom")
        rt.workdir_extras_override = ["/tmp/other"]
        env = rt.build_child_env()
        assert "WORKDIR" not in env
        assert "_HIVE_WORKDIR_SESSION" not in env
        assert "_HIVE_WORKDIR_EXTRAS_SESSION" not in env


class TestApplyWorkdirOverride:
    """Tests for exec_runner._apply_workdir_override."""

    def test_noop_when_no_override(self, tmp_path, monkeypatch):
        """Without rt.workdir, cwd is not changed and override list stays None."""
        import os

        from hive_cli.commands.exec_runner import _apply_workdir_override
        from hive_cli.config import get_runtime_settings

        rt = get_runtime_settings()
        rt.workdir = None
        rt.workdir_extras_override = None

        primary = tmp_path / "primary"
        primary.mkdir()
        monkeypatch.chdir(primary)

        _apply_workdir_override(primary)

        assert Path(os.getcwd()).resolve() == primary.resolve()
        assert rt.workdir_extras_override is None

    def test_swap_sets_cwd_and_extras(self, tmp_path, monkeypatch):
        """Override: cwd→chosen, primary prepended to extras, chosen dropped."""
        import os

        from hive_cli.commands.exec_runner import _apply_workdir_override
        from hive_cli.config import get_runtime_settings, load_config

        primary = tmp_path / "primary"
        primary.mkdir()
        chosen = tmp_path / "chosen"
        chosen.mkdir()
        other = tmp_path / "other"
        other.mkdir()

        config_file = tmp_path / ".hive.yml"
        config_file.write_text(
            f"""
extra_dirs:
  - {chosen}
  - {other}
"""
        )
        load_config.cache_clear()

        rt = get_runtime_settings()
        rt.workdir = chosen
        rt.workdir_extras_override = None

        monkeypatch.chdir(primary)
        try:
            with (
                patch(
                    "hive_cli.config.loader.find_config_files",
                    return_value=[config_file],
                ),
                patch("hive_cli.git.get_main_repo", return_value=tmp_path),
            ):
                _apply_workdir_override(primary)

            assert Path(os.getcwd()).resolve() == chosen.resolve()
            assert rt.workdir_extras_override == [str(primary), str(other)]
        finally:
            rt.workdir = None
            rt.workdir_extras_override = None
