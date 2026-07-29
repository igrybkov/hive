"""Tests for per-agent config-dir profile utilities."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from hive_cli.config import (
    AgentConfig,
    AgentProfileConfig,
    get_profiles_root,
    reset_settings,
    resolve_profile_env,
)
from hive_cli.utils.profiles import (
    DEFAULT_PROFILE_VALUE,
    NEW_PROFILE_ITEM_VALUE,
    create_profile,
    list_profiles,
    select_profile,
)

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# get_profiles_root
# ---------------------------------------------------------------------------


class TestGetProfilesRoot:
    """Tests for get_profiles_root() helper."""

    def test_default_uses_xdg_config_home(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        root = get_profiles_root()
        assert root == tmp_path / "hive" / "profiles"

    def test_fallback_to_home_config(self, monkeypatch):
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        root = get_profiles_root()
        assert root == Path.home() / ".config" / "hive" / "profiles"


# ---------------------------------------------------------------------------
# resolve_profile_env
# ---------------------------------------------------------------------------


class TestResolveProfileEnv:
    """Tests for resolve_profile_env() helper."""

    def setup_method(self):
        """Reset settings singleton before each test."""
        reset_settings()

    def teardown_method(self):
        """Reset settings singleton after each test."""
        reset_settings()

    def test_none_profile_returns_empty(self, monkeypatch):
        """Default (None) profile returns empty dict — passthrough semantics."""
        monkeypatch.setenv("XDG_CONFIG_HOME", "/tmp/xdg")
        with patch("hive_cli.config.loader.find_config_files", return_value=[]):
            result = resolve_profile_env("claude", None)
        assert result == {}

    def test_empty_string_profile_returns_empty(self, monkeypatch):
        """Empty string profile (from <default> picker entry) returns empty dict."""
        monkeypatch.setenv("XDG_CONFIG_HOME", "/tmp/xdg")
        with patch("hive_cli.config.loader.find_config_files", return_value=[]):
            result = resolve_profile_env("claude", "")
        assert result == {}

    def test_named_profile_injects_config_dir_env(self, monkeypatch, tmp_path):
        """Named profile injects the agent's config_dir_env pointing at profile dir."""
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        with patch("hive_cli.config.loader.find_config_files", return_value=[]):
            result = resolve_profile_env("claude", "work")
        expected_path = tmp_path / "hive" / "profiles" / "claude" / "work"
        assert result == {"CLAUDE_CONFIG_DIR": str(expected_path)}

    def test_gemini_profile_adds_force_file_storage(self, monkeypatch, tmp_path):
        """Gemini profile injects both config_dir_env and GEMINI_FORCE_FILE_STORAGE."""
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        with patch("hive_cli.config.loader.find_config_files", return_value=[]):
            result = resolve_profile_env("gemini", "work")
        expected_dir = tmp_path / "hive" / "profiles" / "gemini" / "work"
        assert result["GEMINI_CLI_HOME"] == str(expected_dir)
        assert result["GEMINI_FORCE_FILE_STORAGE"] == "true"

    def test_unsupported_agent_returns_empty(self, monkeypatch, tmp_path):
        """Agent without profile config returns empty dict."""
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        with patch("hive_cli.config.loader.find_config_files", return_value=[]):
            # Use a name not in default.yml's profile map
            result = resolve_profile_env("unknown-agent", "work")
        assert result == {}

    def test_resolve_auto_creates_profile_dir(self, monkeypatch, tmp_path):
        """resolve_profile_env creates the profile dir if it doesn't exist yet.

        This ensures `hive run --profile work` works even for a never-created
        profile, so codex seed files (cli_auth_credentials_store) are written.
        """
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        expected_dir = tmp_path / "hive" / "profiles" / "claude" / "work"
        assert not expected_dir.exists()
        with patch("hive_cli.config.loader.find_config_files", return_value=[]):
            resolve_profile_env("claude", "work")
        assert expected_dir.is_dir()

    def test_resolve_seeds_hardening_files_on_creation(self, monkeypatch, tmp_path):
        """resolve_profile_env writes seed files (e.g. codex config.toml)."""
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        with patch("hive_cli.config.loader.find_config_files", return_value=[]):
            resolve_profile_env("codex", "work")
        seed = tmp_path / "hive" / "profiles" / "codex" / "work" / "config.toml"
        assert seed.exists()
        assert 'cli_auth_credentials_store = "file"' in seed.read_text()

    def test_resolve_seed_files_not_clobbered_on_re_resolve(
        self, monkeypatch, tmp_path
    ):
        """Calling resolve_profile_env twice does not overwrite existing seed files."""
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        with patch("hive_cli.config.loader.find_config_files", return_value=[]):
            resolve_profile_env("codex", "work")
        seed = tmp_path / "hive" / "profiles" / "codex" / "work" / "config.toml"
        seed.write_text("# my edits\n")
        with patch("hive_cli.config.loader.find_config_files", return_value=[]):
            resolve_profile_env("codex", "work")
        assert seed.read_text() == "# my edits\n"

    def test_inherited_var_not_clobbered_by_default(self, monkeypatch, tmp_path):
        """Passing None for profile doesn't override an already-set CLAUDE_CONFIG_DIR.

        overlay is empty — caller merges it; the existing CLAUDE_CONFIG_DIR survives.
        """
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", "/my/existing/config")
        with patch("hive_cli.config.loader.find_config_files", return_value=[]):
            overlay = resolve_profile_env("claude", None)
        # overlay is empty — caller merges it; the existing CLAUDE_CONFIG_DIR survives
        assert overlay == {}


# ---------------------------------------------------------------------------
# create_profile / list_profiles
# ---------------------------------------------------------------------------


class TestCreateProfile:
    """Tests for create_profile() utility."""

    def setup_method(self):
        reset_settings()

    def teardown_method(self):
        reset_settings()

    def test_creates_directory(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        with patch("hive_cli.config.loader.find_config_files", return_value=[]):
            path = create_profile("claude", "work")
        assert path.is_dir()
        assert path == tmp_path / "hive" / "profiles" / "claude" / "work"

    def test_writes_seed_files(self, monkeypatch, tmp_path):
        """create_profile writes codex seed file for file-based auth."""
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        with patch("hive_cli.config.loader.find_config_files", return_value=[]):
            path = create_profile("codex", "work")
        seed = path / "config.toml"
        assert seed.exists()
        assert 'cli_auth_credentials_store = "file"' in seed.read_text()

    def test_seed_files_not_clobbered(self, monkeypatch, tmp_path):
        """Existing seed files are never overwritten."""
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        with patch("hive_cli.config.loader.find_config_files", return_value=[]):
            path = create_profile("codex", "work")
        seed = path / "config.toml"
        original_content = "# my custom config\n"
        seed.write_text(original_content)
        # Create again — should not overwrite
        with patch("hive_cli.config.loader.find_config_files", return_value=[]):
            create_profile("codex", "work")
        assert seed.read_text() == original_content

    def test_idempotent(self, monkeypatch, tmp_path):
        """Calling create_profile twice does not error."""
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        with patch("hive_cli.config.loader.find_config_files", return_value=[]):
            p1 = create_profile("claude", "work")
            p2 = create_profile("claude", "work")
        assert p1 == p2


class TestListProfiles:
    """Tests for list_profiles() utility."""

    def setup_method(self):
        reset_settings()

    def teardown_method(self):
        reset_settings()

    def test_empty_when_no_profiles_dir(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        with patch("hive_cli.config.loader.find_config_files", return_value=[]):
            result = list_profiles("claude")
        assert result == []

    def test_lists_existing_profiles(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        root = tmp_path / "hive" / "profiles" / "claude"
        (root / "personal").mkdir(parents=True)
        (root / "work").mkdir(parents=True)
        with patch("hive_cli.config.loader.find_config_files", return_value=[]):
            result = list_profiles("claude")
        assert result == ["personal", "work"]  # sorted

    def test_ignores_files(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        root = tmp_path / "hive" / "profiles" / "claude"
        root.mkdir(parents=True)
        (root / "work").mkdir()
        (root / "notes.txt").write_text("not a profile")
        with patch("hive_cli.config.loader.find_config_files", return_value=[]):
            result = list_profiles("claude")
        assert result == ["work"]


# ---------------------------------------------------------------------------
# select_profile
# ---------------------------------------------------------------------------


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
            patch("hive_cli.utils.profiles.fuzzy_select", return_value=None),
        ):
            result = select_profile("claude")
        assert result is None

    def test_returns_empty_string_for_default(self, monkeypatch, tmp_path):
        """Selecting <default> returns empty string (passthrough)."""
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        with (
            patch("hive_cli.config.loader.find_config_files", return_value=[]),
            patch(
                "hive_cli.utils.profiles.fuzzy_select",
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
            patch("hive_cli.utils.profiles.fuzzy_select", return_value="work"),
        ):
            result = select_profile("claude", current_profile="work")
        assert result == "work"

    def test_new_profile_flow(self, monkeypatch, tmp_path):
        """Selecting ＋ new profile… triggers creation and returns the new name."""
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        with (
            patch("hive_cli.config.loader.find_config_files", return_value=[]),
            patch(
                "hive_cli.utils.profiles.fuzzy_select",
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
                "hive_cli.utils.profiles.fuzzy_select",
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
                "hive_cli.utils.profiles.fuzzy_select",
                return_value=NEW_PROFILE_ITEM_VALUE,
            ),
            patch("builtins.input", return_value=""),
        ):
            result = select_profile("claude")
        assert result is None
