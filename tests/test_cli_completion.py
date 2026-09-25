"""Integration tests for ``hive completion``.

Runs the real cyclopts completion generator (no mocking of completion
internals). Install destinations are always redirected under a temp ``HOME``
via monkeypatch so nothing is ever written to the developer's real dotfiles.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import CycloptsTestRunner

from hive_cli.app import app


@pytest.fixture(autouse=True)
def _fake_home(tmp_path, monkeypatch):
    """Redirect ``$HOME`` so ``--install`` never touches the real machine."""
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    monkeypatch.setenv("HOME", str(home_dir))
    return home_dir


class TestCompletionPrint:
    @pytest.mark.parametrize("shell", ["bash", "zsh", "fish"])
    def test_prints_script_mentioning_hive(
        self, cli_runner: CycloptsTestRunner, shell: str
    ):
        result = cli_runner.invoke(app, ["completion", shell])

        assert result.exit_code == 0
        assert "hive" in result.output

    def test_unsupported_shell_errors(self, cli_runner: CycloptsTestRunner):
        result = cli_runner.invoke(app, ["completion", "powershell"])

        assert result.exit_code == 1
        assert "powershell" in result.output.lower() or "Invalid value" in result.output

    def test_fish_script_disables_root_level_file_completion(
        self, cli_runner: CycloptsTestRunner
    ):
        """Covers the fish-specific post-processing block in completion.py."""
        result = cli_runner.invoke(app, ["completion", "fish"])

        assert result.exit_code == 0
        assert "Disable file completion at root level" in result.output
        assert "__fish_seen_subcommand_from" in result.output
        # Known subcommands should appear in the generated disable-list.
        assert "diff" in result.output
        assert "rebase-check" in result.output

    def test_fish_script_disables_subcommand_file_completion(
        self, cli_runner: CycloptsTestRunner
    ):
        result = cli_runner.invoke(app, ["completion", "fish"])

        assert result.exit_code == 0
        assert "__fish_hive_using_command" in result.output
        assert "config bootstrap --file" in result.output


class TestCompletionInstall:
    def test_install_fish_writes_completion_file(
        self, cli_runner: CycloptsTestRunner, _fake_home: Path
    ):
        result = cli_runner.invoke(app, ["completion", "fish", "--install"])

        assert result.exit_code == 0
        target = _fake_home / ".config" / "fish" / "completions" / "hive.fish"
        assert target.exists()
        assert "hive" in target.read_text()
        assert "Installed fish completion to" in result.output

    def test_install_bash_writes_completion_file(
        self, cli_runner: CycloptsTestRunner, _fake_home: Path
    ):
        result = cli_runner.invoke(app, ["completion", "bash", "--install"])

        assert result.exit_code == 0
        target = (
            _fake_home / ".local" / "share" / "bash-completion" / "completions" / "hive"
        )
        assert target.exists()
        assert "hive" in target.read_text()
        assert "Installed bash completion to" in result.output

    def test_install_zsh_writes_completion_file(
        self, cli_runner: CycloptsTestRunner, _fake_home: Path
    ):
        result = cli_runner.invoke(app, ["completion", "zsh", "--install"])

        assert result.exit_code == 0
        target = _fake_home / ".zfunc" / "_hive"
        assert target.exists()
        assert "hive" in target.read_text()
        assert "Installed zsh completion to" in result.output

    def test_install_creates_parent_directories(
        self, cli_runner: CycloptsTestRunner, _fake_home: Path
    ):
        """Nothing under HOME pre-exists; the command must mkdir -p first."""
        assert not (_fake_home / ".config").exists()

        result = cli_runner.invoke(app, ["completion", "fish", "--install"])

        assert result.exit_code == 0
        assert (_fake_home / ".config" / "fish" / "completions").is_dir()
