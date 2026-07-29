"""Tests for the run command."""

from __future__ import annotations

from unittest.mock import ANY, patch

from conftest import CycloptsTestRunner

from hive_cli.app import app
from hive_cli.config import reload_config


class TestRunCommand:
    """Tests for hive run command."""

    def test_run_no_agent_available(self, cli_runner: CycloptsTestRunner, monkeypatch):
        """Test error when no agent is available."""
        monkeypatch.setenv("HIVE_AGENTS_ORDER", "claude,gemini")
        monkeypatch.delenv("AGENT", raising=False)

        with (
            patch("shutil.which", return_value=None),
            patch("hive_cli.config.loader.find_config_files", return_value=[]),
        ):
            reload_config()
            result = cli_runner.invoke(app, ["run"])
            assert result.exit_code == 1
            assert "No AI coding agent found" in result.output

    def test_run_preferred_agent_not_found(self, cli_runner: CycloptsTestRunner):
        """Test error when specified agent is not found."""
        with patch("shutil.which", return_value=None):
            result = cli_runner.invoke(app, ["run", "-a", "nonexistent"])
            assert result.exit_code == 1
            assert "nonexistent" in result.output
            assert "not available" in result.output

    def test_run_env_agent_not_found(self, cli_runner: CycloptsTestRunner, monkeypatch):
        """Test error when HIVE_AGENT env var specifies unavailable agent."""
        monkeypatch.setenv("HIVE_AGENT", "unavailable_agent")

        with patch("shutil.which", return_value=None):
            reload_config()
            result = cli_runner.invoke(app, ["run"])
            assert result.exit_code == 1
            assert "unavailable_agent" in result.output
            assert "not available" in result.output

    def test_run_agent_found_executes(
        self, cli_runner: CycloptsTestRunner, temp_git_repo
    ):
        """Test that run command calls execvp with correct args."""
        with (
            patch("shutil.which", return_value="/usr/bin/claude"),
            patch("os.execvpe") as mock_execvpe,
        ):
            cli_runner.invoke(app, ["run", "-a", "claude"])
            # execvp replaces process, so we check it was called correctly
            mock_execvpe.assert_called_once_with("claude", ["claude"], ANY)

    def test_run_passes_args_to_agent(
        self, cli_runner: CycloptsTestRunner, temp_git_repo
    ):
        """Test that arguments are passed to the agent."""
        with (
            patch("shutil.which", return_value="/usr/bin/claude"),
            patch("hive_cli.commands.exec_runner.os.execvpe") as mock_execvpe,
        ):
            # Use repeated --args to pass agent arguments in Cyclopts
            cli_runner.invoke(
                app, ["run", "-a", "claude", "--args", "--model", "--args", "opus"]
            )
            mock_execvpe.assert_called_once_with(
                "claude", ["claude", "--model", "opus"], ANY
            )

    def test_run_changes_to_git_root(
        self, cli_runner: CycloptsTestRunner, temp_git_repo
    ):
        """Test that run command changes to git root."""
        import os

        subdir = temp_git_repo / "subdir"
        subdir.mkdir()
        os.chdir(subdir)

        with (
            patch("shutil.which", return_value="/usr/bin/claude"),
            patch("os.execvpe") as mock_execvpe,
        ):
            cli_runner.invoke(app, ["run", "-a", "claude"])
            # After running, we should have changed to git root
            # The command changes dir before execvp
            mock_execvpe.assert_called_once()


class TestRunResume:
    """Tests for run command --resume flag with Claude (uses --continue)."""

    def test_run_resume_success(self, cli_runner: CycloptsTestRunner, temp_git_repo):
        """Test that --resume succeeds when agent returns 0."""
        with (
            patch("shutil.which", return_value="/usr/bin/claude"),
            patch(
                "hive_cli.commands.exec_runner.get_git_root", return_value=temp_git_repo
            ),
            patch("hive_cli.commands.run.subprocess.run") as mock_run,
            patch("hive_cli.commands.exec_runner.os.execvpe") as mock_execvpe,
        ):
            mock_run.return_value.returncode = 0
            result = cli_runner.invoke(app, ["run", "-a", "claude", "--resume"])
            # Claude uses --continue for resume
            mock_run.assert_called_once()
            call_args = mock_run.call_args[0][0]
            assert call_args == ["claude", "--continue"]
            # Should NOT fall back to execvp
            mock_execvpe.assert_not_called()
            assert result.exit_code == 0

    def test_run_resume_fallback(self, cli_runner: CycloptsTestRunner, temp_git_repo):
        """Test that --resume falls back to normal run when agent returns non-zero."""
        with (
            patch("shutil.which", return_value="/usr/bin/claude"),
            patch(
                "hive_cli.commands.exec_runner.get_git_root", return_value=temp_git_repo
            ),
            patch("hive_cli.commands.run.subprocess.run") as mock_run,
            patch("hive_cli.commands.exec_runner.os.execvpe") as mock_execvpe,
        ):
            mock_run.return_value.returncode = (
                1  # Resume failed, then fallback returns 1
            )
            cli_runner.invoke(app, ["run", "-a", "claude", "--resume"])
            # Should have tried --continue first, then fallback
            assert mock_run.call_count == 2
            # First call: resume attempt
            resume_args = mock_run.call_args_list[0][0][0]
            assert resume_args == ["claude", "--continue"]
            # Second call: fallback without resume args
            fallback_args = mock_run.call_args_list[1][0][0]
            assert fallback_args == ["claude"]
            # execvp should NOT be called (we use subprocess.run for fallback now)
            mock_execvpe.assert_not_called()

    def test_run_resume_short_flag(self, cli_runner: CycloptsTestRunner, temp_git_repo):
        """Test that -r short flag works same as --resume."""
        with (
            patch("shutil.which", return_value="/usr/bin/claude"),
            patch(
                "hive_cli.commands.exec_runner.get_git_root", return_value=temp_git_repo
            ),
            patch("hive_cli.commands.run.subprocess.run") as mock_run,
            patch("hive_cli.commands.exec_runner.os.execvpe"),
        ):
            mock_run.return_value.returncode = 0
            cli_runner.invoke(app, ["run", "-a", "claude", "-r"])
            mock_run.assert_called_once()
            call_args = mock_run.call_args[0][0]
            assert call_args == ["claude", "--continue"]

    def test_run_resume_with_extra_args(
        self, cli_runner: CycloptsTestRunner, temp_git_repo
    ):
        """Test that extra args are passed with resume."""
        with (
            patch("shutil.which", return_value="/usr/bin/claude"),
            patch(
                "hive_cli.commands.exec_runner.get_git_root", return_value=temp_git_repo
            ),
            patch("hive_cli.commands.run.subprocess.run") as mock_run,
            patch("hive_cli.commands.exec_runner.os.execvpe"),
        ):
            mock_run.return_value.returncode = 0
            # Use repeated --args to pass agent arguments in Cyclopts
            cli_runner.invoke(
                app,
                [
                    "run",
                    "-a",
                    "claude",
                    "--resume",
                    "--args",
                    "--model",
                    "--args",
                    "opus",
                ],
            )
            mock_run.assert_called_once()
            call_args = mock_run.call_args[0][0]
            assert call_args == ["claude", "--continue", "--model", "opus"]

    def test_run_resume_fallback_with_extra_args(
        self, cli_runner: CycloptsTestRunner, temp_git_repo
    ):
        """Test that fallback preserves extra args without resume."""
        with (
            patch("shutil.which", return_value="/usr/bin/claude"),
            patch(
                "hive_cli.commands.exec_runner.get_git_root", return_value=temp_git_repo
            ),
            patch("hive_cli.commands.run.subprocess.run") as mock_run,
            patch("hive_cli.commands.exec_runner.os.execvpe") as mock_execvpe,
        ):
            mock_run.return_value.returncode = 1  # Resume failed
            # Use repeated --args to pass agent arguments in Cyclopts
            cli_runner.invoke(
                app,
                [
                    "run",
                    "-a",
                    "claude",
                    "--resume",
                    "--args",
                    "--model",
                    "--args",
                    "opus",
                ],
            )
            # Fallback should have extra args but not resume args
            assert mock_run.call_count == 2
            fallback_args = mock_run.call_args_list[1][0][0]
            assert fallback_args == ["claude", "--model", "opus"]
            # execvp should NOT be called
            mock_execvpe.assert_not_called()

    def test_run_without_resume(self, cli_runner: CycloptsTestRunner, temp_git_repo):
        """Test that resume args are not added when flag is not used."""
        with (
            patch("shutil.which", return_value="/usr/bin/claude"),
            patch(
                "hive_cli.commands.exec_runner.get_git_root", return_value=temp_git_repo
            ),
            patch("hive_cli.commands.exec_runner.os.execvpe") as mock_execvpe,
        ):
            # Use repeated --args to pass agent arguments in Cyclopts
            cli_runner.invoke(
                app, ["run", "-a", "claude", "--args", "--model", "--args", "opus"]
            )
            # Should directly execvp without subprocess.run
            mock_execvpe.assert_called_once_with(
                "claude", ["claude", "--model", "opus"], ANY
            )


class TestRunResumeAgentSpecific:
    """Tests for agent-specific resume behavior."""

    def test_agent_resume_uses_subcommand(
        self, cli_runner: CycloptsTestRunner, temp_git_repo
    ):
        """Test that 'agent' (cursor) uses 'resume' subcommand."""
        with (
            patch("shutil.which", return_value="/usr/bin/agent"),
            patch(
                "hive_cli.commands.exec_runner.get_git_root", return_value=temp_git_repo
            ),
            patch("hive_cli.commands.run.subprocess.run") as mock_run,
            patch("hive_cli.commands.exec_runner.os.execvpe") as mock_execvpe,
        ):
            mock_run.return_value.returncode = 0
            result = cli_runner.invoke(app, ["run", "-a", "agent", "--resume"])
            mock_run.assert_called_once()
            call_args = mock_run.call_args[0][0]
            assert call_args == ["agent", "resume"]
            mock_execvpe.assert_not_called()
            assert result.exit_code == 0

    def test_cursor_agent_resume_uses_subcommand(
        self, cli_runner: CycloptsTestRunner, temp_git_repo
    ):
        """Test that 'cursor-agent' uses 'resume' subcommand."""
        with (
            patch("shutil.which", return_value="/usr/bin/cursor-agent"),
            patch(
                "hive_cli.commands.exec_runner.get_git_root", return_value=temp_git_repo
            ),
            patch("hive_cli.commands.run.subprocess.run") as mock_run,
            patch("hive_cli.commands.exec_runner.os.execvpe") as mock_execvpe,
        ):
            mock_run.return_value.returncode = 0
            result = cli_runner.invoke(app, ["run", "-a", "cursor-agent", "--resume"])
            mock_run.assert_called_once()
            call_args = mock_run.call_args[0][0]
            assert call_args == ["cursor-agent", "resume"]
            mock_execvpe.assert_not_called()
            assert result.exit_code == 0

    def test_codex_resume_uses_subcommand_with_last(
        self, cli_runner: CycloptsTestRunner, temp_git_repo
    ):
        """Test that 'codex' uses 'resume --last' subcommand."""
        with (
            patch("shutil.which", return_value="/usr/bin/codex"),
            patch(
                "hive_cli.commands.exec_runner.get_git_root", return_value=temp_git_repo
            ),
            patch("hive_cli.commands.run.subprocess.run") as mock_run,
            patch("hive_cli.commands.exec_runner.os.execvpe") as mock_execvpe,
        ):
            mock_run.return_value.returncode = 0
            result = cli_runner.invoke(app, ["run", "-a", "codex", "--resume"])
            mock_run.assert_called_once()
            call_args = mock_run.call_args[0][0]
            assert call_args == ["codex", "resume", "--last"]
            mock_execvpe.assert_not_called()
            assert result.exit_code == 0

    def test_copilot_resume_uses_continue(
        self, cli_runner: CycloptsTestRunner, temp_git_repo
    ):
        """Test that 'copilot' uses '--continue' flag."""
        with (
            patch("shutil.which", return_value="/usr/bin/copilot"),
            patch(
                "hive_cli.commands.exec_runner.get_git_root", return_value=temp_git_repo
            ),
            patch("hive_cli.commands.run.subprocess.run") as mock_run,
            patch("hive_cli.commands.exec_runner.os.execvpe") as mock_execvpe,
        ):
            mock_run.return_value.returncode = 0
            result = cli_runner.invoke(app, ["run", "-a", "copilot", "--resume"])
            mock_run.assert_called_once()
            call_args = mock_run.call_args[0][0]
            assert call_args == ["copilot", "--continue"]
            mock_execvpe.assert_not_called()
            assert result.exit_code == 0

    def test_gemini_resume_uses_resume_latest(
        self, cli_runner: CycloptsTestRunner, temp_git_repo
    ):
        """Test that 'gemini' uses '--resume latest' flag."""
        with (
            patch("shutil.which", return_value="/usr/bin/gemini"),
            patch(
                "hive_cli.commands.exec_runner.get_git_root", return_value=temp_git_repo
            ),
            patch("hive_cli.commands.run.subprocess.run") as mock_run,
            patch("hive_cli.commands.exec_runner.os.execvpe") as mock_execvpe,
        ):
            mock_run.return_value.returncode = 0
            result = cli_runner.invoke(app, ["run", "-a", "gemini", "--resume"])
            mock_run.assert_called_once()
            call_args = mock_run.call_args[0][0]
            assert call_args == ["gemini", "--resume", "latest"]
            mock_execvpe.assert_not_called()
            assert result.exit_code == 0

    def test_agent_resume_fallback(self, cli_runner: CycloptsTestRunner, temp_git_repo):
        """Test that agent falls back to normal run when resume fails."""
        with (
            patch("shutil.which", return_value="/usr/bin/agent"),
            patch(
                "hive_cli.commands.exec_runner.get_git_root", return_value=temp_git_repo
            ),
            patch("hive_cli.commands.run.subprocess.run") as mock_run,
            patch("hive_cli.commands.exec_runner.os.execvpe") as mock_execvpe,
        ):
            mock_run.return_value.returncode = 1  # Resume failed
            cli_runner.invoke(app, ["run", "-a", "agent", "--resume"])
            # Should have tried resume first, then fallback
            assert mock_run.call_count == 2
            resume_args = mock_run.call_args_list[0][0][0]
            assert resume_args == ["agent", "resume"]
            fallback_args = mock_run.call_args_list[1][0][0]
            assert fallback_args == ["agent"]
            # execvp should NOT be called
            mock_execvpe.assert_not_called()

    def test_codex_resume_with_extra_args(
        self, cli_runner: CycloptsTestRunner, temp_git_repo
    ):
        """Test that extra args are passed after resume args."""
        with (
            patch("shutil.which", return_value="/usr/bin/codex"),
            patch(
                "hive_cli.commands.exec_runner.get_git_root", return_value=temp_git_repo
            ),
            patch("hive_cli.commands.run.subprocess.run") as mock_run,
            patch("hive_cli.commands.exec_runner.os.execvpe"),
        ):
            mock_run.return_value.returncode = 0
            # Use repeated --args to pass agent arguments in Cyclopts
            cli_runner.invoke(
                app,
                ["run", "-a", "codex", "--resume", "--args", "--model", "--args", "o3"],
            )
            mock_run.assert_called_once()
            call_args = mock_run.call_args[0][0]
            assert call_args == ["codex", "resume", "--last", "--model", "o3"]

    def test_unknown_agent_without_resume_config(
        self, cli_runner: CycloptsTestRunner, temp_git_repo
    ):
        """Test that unknown agents run without resume args (not configured)."""
        with (
            patch("shutil.which", return_value="/usr/bin/unknown-agent"),
            patch(
                "hive_cli.commands.exec_runner.get_git_root", return_value=temp_git_repo
            ),
            patch("hive_cli.commands.run.subprocess.run") as mock_run,
            patch("hive_cli.commands.exec_runner.os.execvpe") as mock_execvpe,
        ):
            mock_run.return_value.returncode = 0
            result = cli_runner.invoke(app, ["run", "-a", "unknown-agent", "--resume"])
            # Unknown agents have no resume_args, so they run via execvp
            mock_run.assert_not_called()
            mock_execvpe.assert_called_once()
            # Runs without any resume flags since agent is not configured
            assert mock_execvpe.call_args[0][:2] == ("unknown-agent", ["unknown-agent"])
            assert result.exit_code == 0


class TestRunRestart:
    """Tests for run command --restart flag."""

    def test_run_restart_triggers_worktree_selection(
        self, cli_runner: CycloptsTestRunner, temp_git_repo
    ):
        """Test that --restart triggers interactive worktree selection."""
        with (
            patch("shutil.which", return_value="/usr/bin/claude"),
            patch(
                "hive_cli.commands.exec_runner._interactive_ensure",
                return_value=(str(temp_git_repo), "test-branch"),
            ) as mock_ensure,
            patch("hive_cli.commands.exec_runner.subprocess.run") as mock_run,
            patch("hive_cli.commands.exec_runner.is_interactive", return_value=True),
        ):
            # Simulate KeyboardInterrupt to exit the restart loop
            mock_run.side_effect = KeyboardInterrupt
            result = cli_runner.invoke(app, ["run", "-a", "claude", "--restart"])
            # Should have called _interactive_ensure for worktree selection
            mock_ensure.assert_called_once_with(
                agent_num=0,
                preselect_branch=None,
                auto_select_branch=None,
                auto_select_timeout=3.0,
            )
            assert result.exit_code == 0

    def test_run_restart_selects_worktree_on_each_iteration(
        self, cli_runner: CycloptsTestRunner, temp_git_repo
    ):
        """Test that worktree selection happens on restart iterations.

        Note: Due to CycloptsTestRunner's handling of KeyboardInterrupt, we can only
        verify the first iteration completes. The restart loop logic ensures
        that on each iteration (when reselect_each_restart is True), the
        worktree selection is called with the previously selected branch.
        """
        call_count = 0

        def mock_run_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                raise KeyboardInterrupt
            # Return a mock result
            from unittest.mock import MagicMock

            result = MagicMock()
            result.returncode = 0
            return result

        with (
            patch("shutil.which", return_value="/usr/bin/claude"),
            patch(
                "hive_cli.commands.exec_runner._interactive_ensure",
                return_value=(str(temp_git_repo), "test-branch"),
            ) as mock_ensure,
            patch(
                "hive_cli.commands.exec_runner.subprocess.run",
                side_effect=mock_run_side_effect,
            ),
            patch("hive_cli.commands.exec_runner.is_interactive", return_value=True),
        ):
            result = cli_runner.invoke(app, ["run", "-a", "claude", "--restart"])
            # Should have called _interactive_ensure at least once
            assert mock_ensure.call_count >= 1
            # First call has no preselect
            first_call_kwargs = mock_ensure.call_args_list[0][1]
            assert first_call_kwargs["agent_num"] == 0
            assert first_call_kwargs["preselect_branch"] is None
            # If there was a second call, it should have preselected branch
            if mock_ensure.call_count >= 2:
                second_call_kwargs = mock_ensure.call_args_list[1][1]
                assert second_call_kwargs["agent_num"] == 0
                assert second_call_kwargs["preselect_branch"] == "test-branch"
            assert result.exit_code == 0

    def test_run_restart_non_interactive_fails(
        self, cli_runner: CycloptsTestRunner, temp_git_repo
    ):
        """Test that --restart fails in non-interactive mode."""
        with (
            patch("shutil.which", return_value="/usr/bin/claude"),
            patch("hive_cli.commands.exec_runner.is_interactive", return_value=False),
        ):
            result = cli_runner.invoke(app, ["run", "-a", "claude", "--restart"])
            assert result.exit_code == 1
            assert "Interactive mode required" in result.output

    def test_run_restart_with_explicit_worktree_skips_selection(
        self, cli_runner: CycloptsTestRunner, temp_git_repo
    ):
        """Test that --restart with explicit -w branch skips selection."""
        with (
            patch("shutil.which", return_value="/usr/bin/claude"),
            patch(
                "hive_cli.commands.exec_runner.get_main_repo",
                return_value=temp_git_repo,
            ),
            patch(
                "hive_cli.commands.exec_runner._interactive_ensure",
                return_value=(str(temp_git_repo), "main"),
            ) as mock_ensure,
            patch("hive_cli.commands.exec_runner.subprocess.run") as mock_run,
        ):
            # Simulate KeyboardInterrupt to exit the restart loop
            mock_run.side_effect = KeyboardInterrupt
            result = cli_runner.invoke(
                app, ["run", "-a", "claude", "--restart", "-w", "main"]
            )
            # Should NOT have called _interactive_ensure
            mock_ensure.assert_not_called()
            assert result.exit_code == 0

    def test_run_help_shows_restart(self, cli_runner: CycloptsTestRunner):
        """Test that help shows --restart flag."""
        result = cli_runner.invoke(app, ["run", "--help"])
        assert result.exit_code == 0
        assert "--restart" in result.output


class TestRunExtraDirs:
    """Tests for run command extra_dirs injection."""

    def test_run_injects_extra_dirs(
        self, cli_runner: CycloptsTestRunner, temp_git_repo, monkeypatch
    ):
        """Test that extra_dirs args are injected into agent command."""
        config_file = temp_git_repo / ".hive.yml"
        config_file.write_text("""
extra_dirs:
  - /abs/shared-lib
""")

        import subprocess as real_subprocess

        with (
            patch("shutil.which", return_value="/usr/bin/claude"),
            patch(
                "hive_cli.commands.exec_runner.get_git_root", return_value=temp_git_repo
            ),
            patch("hive_cli.git.get_main_repo", return_value=temp_git_repo),
            patch(
                "hive_cli.config.loader.find_config_files",
                return_value=[config_file],
            ),
            patch.object(real_subprocess, "run") as mock_run,
            patch("hive_cli.commands.exec_runner.os.execvpe"),
        ):
            reload_config()
            mock_run.return_value.returncode = 0
            cli_runner.invoke(app, ["run", "-a", "claude"])
            agent_calls = [c for c in mock_run.call_args_list if c[0][0][0] == "claude"]
            assert len(agent_calls) >= 1
            call_args = agent_calls[0][0][0]
            assert "--add-dir" in call_args
            assert "/abs/shared-lib" in call_args

    def test_run_extra_dirs_relative_resolves_to_main_repo(
        self, cli_runner: CycloptsTestRunner, temp_git_repo, monkeypatch
    ):
        """Test that relative extra_dirs resolve against main repo root."""
        sibling = temp_git_repo.parent / "sibling"
        sibling.mkdir()

        config_file = temp_git_repo / ".hive.yml"
        config_file.write_text("""
extra_dirs:
  - ../sibling
""")

        import subprocess as real_subprocess

        with (
            patch("shutil.which", return_value="/usr/bin/claude"),
            patch(
                "hive_cli.commands.exec_runner.get_git_root", return_value=temp_git_repo
            ),
            patch("hive_cli.git.get_main_repo", return_value=temp_git_repo),
            patch(
                "hive_cli.config.loader.find_config_files",
                return_value=[config_file],
            ),
            patch.object(real_subprocess, "run") as mock_run,
            patch("hive_cli.commands.exec_runner.os.execvpe"),
        ):
            reload_config()
            mock_run.return_value.returncode = 0
            cli_runner.invoke(app, ["run", "-a", "claude"])
            agent_calls = [c for c in mock_run.call_args_list if c[0][0][0] == "claude"]
            assert len(agent_calls) >= 1
            call_args = agent_calls[0][0][0]
            assert "--add-dir" in call_args
            assert str(sibling) in call_args

    def test_run_no_extra_dirs_when_agent_has_no_flag(
        self, cli_runner: CycloptsTestRunner, temp_git_repo, monkeypatch
    ):
        """Test that agents without extra_dirs_flag don't get extra dirs."""
        config_file = temp_git_repo / ".hive.yml"
        config_file.write_text("""
agents:
  configs:
    gemini:
      extra_dirs_flag: null
extra_dirs:
  - /some/dir
""")

        with (
            patch("shutil.which", return_value="/usr/bin/gemini"),
            patch(
                "hive_cli.commands.exec_runner.get_git_root", return_value=temp_git_repo
            ),
            patch("hive_cli.git.get_main_repo", return_value=temp_git_repo),
            patch(
                "hive_cli.config.loader.find_config_files",
                return_value=[config_file],
            ),
            patch("hive_cli.commands.exec_runner.os.execvpe") as mock_execvpe,
        ):
            reload_config()
            cli_runner.invoke(app, ["run", "-a", "gemini"])
            # No extra_dirs_flag → execvp (no dynamic runner needed)
            mock_execvpe.assert_called_once()
            call_args = mock_execvpe.call_args[0][1]
            assert "/some/dir" not in call_args


class TestRunProfile:
    """Tests for run command --profile flag and profile env injection."""

    def test_run_help_shows_profile(self, cli_runner: CycloptsTestRunner):
        """Test that --help shows --profile flag."""
        result = cli_runner.invoke(app, ["run", "--help"])
        assert result.exit_code == 0
        assert "--profile" in result.output
        assert "-p" in result.output

    def test_profile_flag_injects_config_dir_env(
        self, cli_runner: CycloptsTestRunner, monkeypatch, tmp_path
    ):
        """Named profile sets the agent's config_dir_env in child environment."""
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

        captured_env: dict = {}

        def fake_run(cmd, **kwargs):
            captured_env.update(kwargs.get("env", {}))
            return type("R", (), {"returncode": 0})()

        with (
            patch("shutil.which", return_value="/usr/bin/claude"),
            patch("hive_cli.commands.exec_runner.get_git_root", return_value=tmp_path),
            patch("hive_cli.config.loader.find_config_files", return_value=[]),
            patch("hive_cli.commands.run.subprocess.run", side_effect=fake_run),
        ):
            reload_config()
            cli_runner.invoke(app, ["run", "-a", "claude", "-p", "work", "--resume"])

        expected_path = tmp_path / "hive" / "profiles" / "claude" / "work"
        assert "CLAUDE_CONFIG_DIR" in captured_env
        assert captured_env["CLAUDE_CONFIG_DIR"] == str(expected_path)

    def test_default_profile_does_not_inject_env(
        self, cli_runner: CycloptsTestRunner, monkeypatch, tmp_path
    ):
        """'default' profile string → passthrough; no CLAUDE_CONFIG_DIR injected."""
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)

        captured_env: dict = {}

        def fake_run(cmd, **kwargs):
            captured_env.update(kwargs.get("env", {}))
            return type("R", (), {"returncode": 0})()

        with (
            patch("shutil.which", return_value="/usr/bin/claude"),
            patch("hive_cli.commands.exec_runner.get_git_root", return_value=tmp_path),
            patch("hive_cli.config.loader.find_config_files", return_value=[]),
            patch("hive_cli.commands.run.subprocess.run", side_effect=fake_run),
        ):
            reload_config()
            cli_runner.invoke(app, ["run", "-a", "claude", "-p", "default", "--resume"])

        assert "CLAUDE_CONFIG_DIR" not in captured_env

    def test_gemini_profile_adds_force_file_storage(
        self, cli_runner: CycloptsTestRunner, monkeypatch, tmp_path
    ):
        """Gemini named profile injects GEMINI_FORCE_FILE_STORAGE=true as well."""
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

        captured_env: dict = {}

        def fake_run(cmd, **kwargs):
            captured_env.update(kwargs.get("env", {}))
            return type("R", (), {"returncode": 0})()

        with (
            patch("shutil.which", return_value="/usr/bin/gemini"),
            patch("hive_cli.commands.exec_runner.get_git_root", return_value=tmp_path),
            patch("hive_cli.config.loader.find_config_files", return_value=[]),
            patch("hive_cli.commands.run.subprocess.run", side_effect=fake_run),
        ):
            reload_config()
            cli_runner.invoke(app, ["run", "-a", "gemini", "-p", "work", "--resume"])

        assert "GEMINI_CLI_HOME" in captured_env
        assert captured_env.get("GEMINI_FORCE_FILE_STORAGE") == "true"

    def test_profile_env_var_read_from_env(
        self, cli_runner: CycloptsTestRunner, monkeypatch, tmp_path
    ):
        """HIVE_AGENT_PROFILE env var is picked up without --profile flag."""
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        monkeypatch.setenv("HIVE_AGENT_PROFILE", "work")

        captured_env: dict = {}

        def fake_run(cmd, **kwargs):
            captured_env.update(kwargs.get("env", {}))
            return type("R", (), {"returncode": 0})()

        with (
            patch("shutil.which", return_value="/usr/bin/claude"),
            patch("hive_cli.commands.exec_runner.get_git_root", return_value=tmp_path),
            patch("hive_cli.config.loader.find_config_files", return_value=[]),
            patch("hive_cli.commands.run.subprocess.run", side_effect=fake_run),
        ):
            reload_config()
            cli_runner.invoke(app, ["run", "-a", "claude", "--resume"])

        expected_path = tmp_path / "hive" / "profiles" / "claude" / "work"
        assert captured_env.get("CLAUDE_CONFIG_DIR") == str(expected_path)


class TestRunHelp:
    """Tests for run command help."""

    def test_run_help(self, cli_runner: CycloptsTestRunner):
        """Test that run --help shows help text."""
        result = cli_runner.invoke(app, ["run", "--help"])
        assert result.exit_code == 0
        assert "Run AI coding agent" in result.output
        assert "--agent" in result.output

    def test_run_help_shows_resume(self, cli_runner: CycloptsTestRunner):
        """Test that help shows --resume flag."""
        result = cli_runner.invoke(app, ["run", "--help"])
        assert result.exit_code == 0
        assert "--resume" in result.output
        assert "-r" in result.output
