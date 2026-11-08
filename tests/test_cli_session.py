"""Tests for the `hive session` command surface: backend-neutral `hive
zellij`, selecting Zellij or tmux the same way `get_mux()` does elsewhere.
"""

from __future__ import annotations

from unittest.mock import patch

from conftest import CycloptsTestRunner

from hive_cli.app import app
from hive_cli.config import reload_config


def _which(*available: str):
    def mock_which(cmd):
        return f"/usr/bin/{cmd}" if cmd in available else None

    return mock_which


class TestSessionCommand:
    def test_session_help_exits_zero(self, cli_runner: CycloptsTestRunner):
        result = cli_runner.invoke(app, ["session", "--help"])
        assert result.exit_code == 0

    def test_session_uses_tmux_attach_argv_when_backend_is_tmux(
        self, cli_runner: CycloptsTestRunner, temp_git_repo, monkeypatch
    ):
        monkeypatch.setenv("HIVE_MUX_BACKEND", "tmux")
        monkeypatch.delenv("ZELLIJ", raising=False)
        monkeypatch.delenv("TMUX", raising=False)
        reload_config()

        with (
            patch("shutil.which", side_effect=_which("tmux", "claude")),
            patch("os.execvpe") as mock_execvpe,
        ):
            cli_runner.invoke(app, ["session", "-a", "claude"])

        mock_execvpe.assert_called_once()
        program, argv, _env = mock_execvpe.call_args[0]
        assert program == "tmux"
        assert argv[0] == "tmux"
        assert "attach-session" in argv
        assert argv[-1] == "test-repo"
        assert "-f" in argv
        conf_path = argv[argv.index("-f") + 1]
        assert conf_path.endswith("tmux.conf")

    def test_session_falls_back_to_zellij_when_nothing_configured(
        self, cli_runner: CycloptsTestRunner, temp_git_repo, monkeypatch
    ):
        """auto + no live session -> the same "start fresh" backend `hive
        zellij` has always used, since `mux.backend: auto` alone can't tell
        `hive session` which multiplexer to start."""
        monkeypatch.delenv("HIVE_MUX_BACKEND", raising=False)
        monkeypatch.delenv("ZELLIJ", raising=False)
        monkeypatch.delenv("TMUX", raising=False)
        reload_config()

        with (
            patch("shutil.which", side_effect=_which("zellij", "claude")),
            patch("os.execvpe") as mock_execvpe,
        ):
            cli_runner.invoke(app, ["session", "-a", "claude"])

        mock_execvpe.assert_called_once()
        program, argv, _env = mock_execvpe.call_args[0]
        assert program == "zellij"
        assert argv[0] == "zellij"

    def test_session_binary_missing_errors(
        self, cli_runner: CycloptsTestRunner, temp_git_repo, monkeypatch
    ):
        monkeypatch.setenv("HIVE_MUX_BACKEND", "tmux")
        reload_config()

        with patch("shutil.which", side_effect=_which("claude")):
            result = cli_runner.invoke(app, ["session", "-a", "claude"])

        assert result.exit_code == 1
        assert "tmux" in result.output
