"""Tests for hive_cli.agents.profiles: profile root, env resolution, CRUD."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from hive_cli.agents.profiles import (
    create_profile,
    get_profiles_root,
    list_profiles,
    resolve_profile_env,
)
from hive_cli.config import reset_settings

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
