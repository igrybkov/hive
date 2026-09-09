"""Tests for the configuration module."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from conftest import git

from hive_cli.config import (
    KNOWN_AGENTS,
    AgentConfig,
    AgentHooksConfig,
    AgentProfileConfig,
    HooksConfig,
    deep_merge,
    find_config_files,
    find_global_config,
    find_project_root,
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


class TestFindProjectRoot:
    """Tests for find_project_root(): walk-up to .git, no subprocess spawn."""

    def test_find_project_root_from_nested_dir(self, temp_git_repo, monkeypatch):
        """Chdir into a nested subdirectory still resolves the repo root."""
        nested = temp_git_repo / "sub" / "dir"
        nested.mkdir(parents=True)
        monkeypatch.chdir(nested)
        assert find_project_root() == temp_git_repo

    def test_find_project_root_in_worktree(self, temp_git_repo, tmp_path, monkeypatch):
        """A worktree's .git is a *file*; the worktree root itself is returned."""
        worktree_path = tmp_path / "wt"
        git("worktree", "add", "-b", "feat", str(worktree_path), cwd=temp_git_repo)
        assert (worktree_path / ".git").is_file()
        monkeypatch.chdir(worktree_path)
        assert find_project_root() == worktree_path

    def test_find_project_root_outside_repo_is_none(self, tmp_path, monkeypatch):
        """No .git anywhere above cwd → None."""
        monkeypatch.chdir(tmp_path)
        assert find_project_root() is None

    def test_no_subprocess_during_config_load(self, fake_proc, monkeypatch):
        """Config discovery/loading never spawns a process (git or otherwise)."""
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        reload_config()
        assert fake_proc.calls == []


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


class TestPaneLabels:
    def test_default_pane_labels_match_bundled_layout(self):
        """zellij.pane_labels must be the c1..c16 names from the agent-16 layout."""
        import re
        from pathlib import Path

        from hive_cli.config import get_settings
        from hive_cli.layout.resolve import resolve_layout

        settings = get_settings()
        resolved = resolve_layout(
            "agent-16",
            session="s",
            hive="/opt/hive",
            settings=settings,
            render=lambda spec, hive: "",
        )
        kdl = Path(resolved).read_text()
        found = re.findall(r'pane name="c(\d+): ([^"]+)"', kdl)
        by_number = {int(n): label for n, label in found}
        expected = [by_number[n] for n in sorted(by_number)]
        assert settings.zellij.pane_labels == expected
        assert len(expected) == 16

    def test_pane_labels_env_csv(self, monkeypatch):
        from hive_cli.config import get_settings, reset_settings

        monkeypatch.setenv("HIVE_ZELLIJ_PANE_LABELS", "Ann,Bob")
        reset_settings()
        assert get_settings().zellij.pane_labels == ["Ann", "Bob"]


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


class TestAgentProfileConfig:
    """Tests for the AgentProfileConfig schema model."""

    def test_defaults_are_empty(self):
        """AgentProfileConfig defaults: no config_dir_env, empty dicts."""
        cfg = AgentProfileConfig()
        assert cfg.config_dir_env is None
        assert cfg.extra_env == {}
        assert cfg.seed_files == {}

    def test_config_dir_env_set(self):
        cfg = AgentProfileConfig(config_dir_env="CLAUDE_CONFIG_DIR")
        assert cfg.config_dir_env == "CLAUDE_CONFIG_DIR"

    def test_extra_env_set(self):
        cfg = AgentProfileConfig(extra_env={"GEMINI_FORCE_FILE_STORAGE": "true"})
        assert cfg.extra_env == {"GEMINI_FORCE_FILE_STORAGE": "true"}

    def test_seed_files_set(self):
        cfg = AgentProfileConfig(seed_files={"config.toml": 'key = "value"\n'})
        assert cfg.seed_files == {"config.toml": 'key = "value"\n'}


class TestAgentConfigProfileField:
    """Tests for profile field on AgentConfig."""

    def test_profile_defaults_to_none(self):
        cfg = AgentConfig()
        assert cfg.profile is None

    def test_profile_can_be_set(self):
        profile_cfg = AgentProfileConfig(config_dir_env="CLAUDE_CONFIG_DIR")
        cfg = AgentConfig(
            resume_args=[], skip_permissions_args=[], extra_args=[], profile=profile_cfg
        )
        assert cfg.profile is not None
        assert cfg.profile.config_dir_env == "CLAUDE_CONFIG_DIR"


class TestAgentHooksConfig:
    """Tests for the AgentHooksConfig schema model."""

    def test_defaults_to_unsupported(self):
        cfg = AgentHooksConfig()
        assert cfg.mode == "unsupported"
        assert cfg.note is None

    def test_mode_and_note_can_be_set(self):
        cfg = AgentHooksConfig(mode="cli", note="replaces a user-configured notify")
        assert cfg.mode == "cli"
        assert cfg.note == "replaces a user-configured notify"

    def test_agent_config_hooks_defaults_to_unsupported(self):
        assert AgentConfig().hooks.mode == "unsupported"

    def test_default_config_agent_hook_modes(self, tmp_path, monkeypatch):
        """Each bundled agent's hooks.mode matches the F5 spec table."""
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        monkeypatch.delenv("HIVE_AGENTS_ORDER", raising=False)

        load_config.cache_clear()
        with patch("hive_cli.config.loader.find_config_files", return_value=[]):
            config = load_config()

        configs = config.agents.configs
        assert configs["claude"].hooks.mode == "cli"
        assert configs["codex"].hooks.mode == "cli"
        assert configs["gemini"].hooks.mode == "profile"
        assert configs["copilot"].hooks.mode == "unsupported"
        assert configs["agent"].hooks.mode == "unsupported"
        assert configs["cursor-agent"].hooks.mode == "unsupported"


class TestHooksConfig:
    """Tests for the top-level hooks.enabled setting."""

    def test_disabled_by_default(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        load_config.cache_clear()
        with patch("hive_cli.config.loader.find_config_files", return_value=[]):
            config = load_config()
        assert config.hooks.enabled is False

    def test_enabled_from_config_file(self, tmp_path, monkeypatch):
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        config_file = tmp_path / ".hive.yml"
        config_file.write_text("hooks:\n  enabled: true\n")

        load_config.cache_clear()
        with patch(
            "hive_cli.config.loader.find_config_files", return_value=[config_file]
        ):
            config = load_config()
        assert config.hooks.enabled is True

    def test_hive_hooks_enabled_env(self, tmp_path, monkeypatch):
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        monkeypatch.setenv("HIVE_HOOKS_ENABLED", "true")

        load_config.cache_clear()
        with patch("hive_cli.config.loader.find_config_files", return_value=[]):
            config = load_config()
        assert config.hooks.enabled is True

    def test_defaults_standalone(self):
        assert HooksConfig().enabled is False


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


class TestWorktreesFetchInterval:
    def test_default_is_five_minutes(self):
        from hive_cli.config import get_settings

        assert get_settings().worktrees.fetch_interval == 300

    def test_env_override(self, monkeypatch):
        from hive_cli.config import get_settings, reset_settings

        monkeypatch.setenv("HIVE_WORKTREES_FETCH_INTERVAL", "30")
        reset_settings()
        assert get_settings().worktrees.fetch_interval == 30


class TestZellijLayoutConfig:
    def test_defaults(self):
        from hive_cli.config import get_settings

        settings = get_settings()
        assert settings.zellij.agents_per_tab == 2
        assert settings.zellij.control_plane == "right"

    def test_agents_per_tab_rejects_invalid_value(self, tmp_path, monkeypatch):
        from pydantic import ValidationError

        from hive_cli.config import load_config

        config_file = tmp_path / ".hive.yml"
        config_file.write_text("zellij:\n  agents_per_tab: 3\n")
        load_config.cache_clear()
        with patch(
            "hive_cli.config.loader.find_config_files", return_value=[config_file]
        ):
            with pytest.raises(ValidationError):
                load_config()

    def test_control_plane_rejects_invalid_value(self, tmp_path, monkeypatch):
        from pydantic import ValidationError

        from hive_cli.config import load_config

        config_file = tmp_path / ".hive.yml"
        config_file.write_text("zellij:\n  control_plane: sideways\n")
        load_config.cache_clear()
        with patch(
            "hive_cli.config.loader.find_config_files", return_value=[config_file]
        ):
            with pytest.raises(ValidationError):
                load_config()


class TestTabsConfig:
    def test_default_empty(self):
        from hive_cli.config import get_settings

        assert get_settings().tabs == {}

    def test_parsed_into_tab_config(self, tmp_path, monkeypatch):
        from hive_cli.config import TabConfig, load_config

        config_file = tmp_path / ".hive.yml"
        config_file.write_text("""
tabs:
  git:
    panes:
      - name: lazygit
        command: "lazygit"
        size: "70%"
      - name: git-shell
        command: ["fish"]
        suspended: true
""")
        load_config.cache_clear()
        with patch(
            "hive_cli.config.loader.find_config_files", return_value=[config_file]
        ):
            config = load_config()

        assert isinstance(config.tabs["git"], TabConfig)
        assert config.tabs["git"].panes[0].name == "lazygit"
        assert config.tabs["git"].panes[0].command == "lazygit"
        assert config.tabs["git"].panes[1].command == ["fish"]
        assert config.tabs["git"].panes[1].suspended is True
