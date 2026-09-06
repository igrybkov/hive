"""Tests for the `hive zellij` command surface."""

from __future__ import annotations

from unittest.mock import patch

from conftest import CycloptsTestRunner

from hive_cli.app import app
from hive_cli.config import reload_config


class TestZellijCommand:
    """Tests for hive zellij command."""

    def test_zellij_not_installed(self, cli_runner: CycloptsTestRunner):
        """Test error when zellij is not installed."""
        with patch("shutil.which", return_value=None):
            result = cli_runner.invoke(app, ["zellij"])
            assert result.exit_code == 1
            assert "zellij is not installed" in result.output

    def test_zellij_no_agent_available(
        self, cli_runner: CycloptsTestRunner, monkeypatch
    ):
        """Test error when no agent is available."""
        monkeypatch.setenv("HIVE_AGENTS_ORDER", "claude,gemini")
        monkeypatch.delenv("AGENT", raising=False)

        def mock_which(cmd):
            return "/usr/bin/zellij" if cmd == "zellij" else None

        with (
            patch("shutil.which", side_effect=mock_which),
            patch("hive_cli.config.loader.find_config_files", return_value=[]),
        ):
            reload_config()
            result = cli_runner.invoke(app, ["zellij"])
            assert result.exit_code == 1
            assert "No AI coding agent found" in result.output

    def test_zellij_preferred_agent_not_found(self, cli_runner: CycloptsTestRunner):
        """Test error when specified agent is not found."""

        def mock_which(cmd):
            return "/usr/bin/zellij" if cmd == "zellij" else None

        with patch("shutil.which", side_effect=mock_which):
            result = cli_runner.invoke(app, ["zellij", "-a", "nonexistent"])
            assert result.exit_code == 1
            assert "nonexistent" in result.output
            assert "not available" in result.output

    def test_zellij_launches_with_agent(
        self, cli_runner: CycloptsTestRunner, temp_git_repo
    ):
        """Test zellij launches with the bundled 'agent' layout and correct session."""

        def mock_which(cmd):
            if cmd in ["zellij", "claude"]:
                return f"/usr/bin/{cmd}"
            return None

        with (
            patch("shutil.which", side_effect=mock_which),
            patch("os.execvpe") as mock_execvpe,
        ):
            cli_runner.invoke(app, ["zellij", "-a", "claude"])
            mock_execvpe.assert_called_once()
            call_args = mock_execvpe.call_args
            assert call_args[0][0] == "zellij"
            cmd_list = call_args[0][1]
            assert cmd_list[0] == "zellij"
            # Default layout "agent" resolves to the bundled packaged .kdl path
            assert "--layout" in cmd_list
            layout_arg = cmd_list[cmd_list.index("--layout") + 1]
            assert layout_arg.endswith("bundled/agent.kdl")
            assert "attach" in cmd_list
            assert "--create" in cmd_list
            # Default session name is the repo name (no agent suffix)
            session_name = cmd_list[-1]
            assert session_name == "test-repo"

    def test_zellij_uses_configured_layout(
        self, cli_runner: CycloptsTestRunner, temp_git_repo, monkeypatch
    ):
        """Test that zellij uses layout from config when specified.

        "custom-layout" has no "/", doesn't end in ".kdl", and isn't a bundled
        layout name, so resolve_layout() passes it through unchanged for
        zellij to resolve against its own layout dir.
        """
        monkeypatch.setenv("HIVE_ZELLIJ_LAYOUT", "custom-layout")

        reload_config()

        def mock_which(cmd):
            if cmd in ["zellij", "claude"]:
                return f"/usr/bin/{cmd}"
            return None

        with (
            patch("shutil.which", side_effect=mock_which),
            patch("os.execvpe") as mock_execvpe,
        ):
            cli_runner.invoke(app, ["zellij", "-a", "claude"])
            mock_execvpe.assert_called_once()
            cmd_list = mock_execvpe.call_args[0][1]
            assert "--layout" in cmd_list
            layout_idx = cmd_list.index("--layout")
            assert cmd_list[layout_idx + 1] == "custom-layout"

    def test_zellij_sets_agent_env(self, cli_runner: CycloptsTestRunner, temp_git_repo):
        """Test that HIVE_AGENT env var is passed to child process."""

        def mock_which(cmd):
            if cmd in ["zellij", "claude"]:
                return f"/usr/bin/{cmd}"
            return None

        captured_env = {}

        def capture_execvpe(cmd, args, env):
            captured_env["HIVE_AGENT"] = env.get("HIVE_AGENT")
            raise SystemExit(0)

        with (
            patch("shutil.which", side_effect=mock_which),
            patch("os.execvpe", side_effect=capture_execvpe),
        ):
            cli_runner.invoke(app, ["zellij", "-a", "claude"])
            assert captured_env["HIVE_AGENT"] == "claude"


class TestZellijHelp:
    """Tests for zellij command help."""

    def test_zellij_help(self, cli_runner: CycloptsTestRunner):
        """Test that zellij --help shows help text."""
        result = cli_runner.invoke(app, ["zellij", "--help"])
        assert result.exit_code == 0
        assert "Open Zellij with AI agent layout" in result.output
        assert "--agent" in result.output

    def test_zellij_help_shows_subcommands(self, cli_runner: CycloptsTestRunner):
        """Test that zellij --help shows set-status and set-title subcommands."""
        result = cli_runner.invoke(app, ["zellij", "--help"])
        assert result.exit_code == 0
        assert "set-status" in result.output
        assert "set-title" in result.output


class TestSetStatusCommand:
    """Tests for hive zellij set-status command."""

    def test_set_status_not_in_zellij(
        self, cli_runner: CycloptsTestRunner, monkeypatch
    ):
        """Test set-status shows message when not in Zellij."""
        monkeypatch.delenv("ZELLIJ", raising=False)

        result = cli_runner.invoke(app, ["zellij", "set-status", "[working]"])
        assert "Not running in Zellij session" in result.output

    def test_set_status_in_zellij(self, cli_runner: CycloptsTestRunner, monkeypatch):
        """Test set-status works when in Zellij."""
        monkeypatch.setenv("ZELLIJ", "0")
        monkeypatch.setenv("ZELLIJ_SESSION_NAME", "test")
        monkeypatch.setenv("ZELLIJ_PANE_ID", "1")
        monkeypatch.setenv("HIVE_AGENT", "claude")
        monkeypatch.setenv("HIVE_PANE_ID", "1")

        with patch("hive_cli.mux.zellij.backend.rename_pane"):
            result = cli_runner.invoke(app, ["zellij", "set-status", "[working]"])
            assert "Not running in Zellij session" not in result.output


class TestSetTitleCommand:
    """Tests for hive zellij set-title command."""

    def test_set_title_not_in_zellij(self, cli_runner: CycloptsTestRunner, monkeypatch):
        """Test set-title shows message when not in Zellij."""
        monkeypatch.delenv("ZELLIJ", raising=False)

        result = cli_runner.invoke(app, ["zellij", "set-title", "My task"])
        assert "Not running in Zellij session" in result.output

    def test_set_title_in_zellij(self, cli_runner: CycloptsTestRunner, monkeypatch):
        """Test set-title works when in Zellij."""
        monkeypatch.setenv("ZELLIJ", "0")
        monkeypatch.setenv("ZELLIJ_SESSION_NAME", "test")
        monkeypatch.setenv("ZELLIJ_PANE_ID", "1")
        monkeypatch.setenv("HIVE_AGENT", "claude")
        monkeypatch.setenv("HIVE_PANE_ID", "1")

        with patch("hive_cli.mux.zellij.backend.rename_pane"):
            result = cli_runner.invoke(app, ["zellij", "set-title", "My task"])
            assert "Not running in Zellij session" not in result.output


class TestLayoutPathCommand:
    """Tests for hive zellij layout-path command."""

    def test_layout_path_default_resolves_bundled_agent(
        self, cli_runner: CycloptsTestRunner
    ):
        """With no argument, resolves the configured (default "agent") layout."""
        result = cli_runner.invoke(app, ["zellij", "layout-path"])
        assert result.exit_code == 0
        assert result.output.strip().endswith("bundled/agent.kdl")

    def test_layout_path_explicit_name(self, cli_runner: CycloptsTestRunner):
        result = cli_runner.invoke(app, ["zellij", "layout-path", "agent"])
        assert result.exit_code == 0
        assert result.output.strip().endswith("bundled/agent.kdl")

    def test_layout_path_unknown_name_passed_through(
        self, cli_runner: CycloptsTestRunner
    ):
        result = cli_runner.invoke(app, ["zellij", "layout-path", "my-layout"])
        assert result.exit_code == 0
        assert result.output.strip() == "my-layout"

    def test_layout_path_none_configured_errors(
        self, cli_runner: CycloptsTestRunner, monkeypatch
    ):
        monkeypatch.setenv("HIVE_ZELLIJ_LAYOUT", "")
        reload_config()

        result = cli_runner.invoke(app, ["zellij", "layout-path"])
        assert result.exit_code == 1
        assert "No layout configured" in result.output
