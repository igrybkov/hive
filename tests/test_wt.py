"""Tests for the wt command."""

from __future__ import annotations

from conftest import CycloptsTestRunner

from hive_cli.app import app


class TestWtCommand:
    """Tests for hive wt command."""

    def test_wt_help(self, cli_runner: CycloptsTestRunner):
        """Test that wt --help shows help text."""
        result = cli_runner.invoke(app, ["wt", "--help"])
        assert result.exit_code == 0
        assert "Manage git worktrees" in result.output
        assert "cd" in result.output
        assert "list" in result.output
        assert "create" in result.output


class TestWtListCommand:
    """Tests for hive wt list command."""

    def test_list_shows_worktrees(self, cli_runner: CycloptsTestRunner, temp_git_repo):
        """Test that list shows worktrees."""
        result = cli_runner.invoke(app, ["wt", "list"])
        assert result.exit_code == 0
        assert "main:" in result.output
        assert str(temp_git_repo) in result.output


class TestWtPathCommand:
    """Tests for hive wt path command."""

    def test_path_main(self, cli_runner: CycloptsTestRunner, temp_git_repo):
        """Test path for main returns main repo."""
        result = cli_runner.invoke(app, ["wt", "path", "main"])
        assert result.exit_code == 0
        assert str(temp_git_repo) in result.output

    def test_path_one(self, cli_runner: CycloptsTestRunner, temp_git_repo):
        """Test path for '1' returns main repo."""
        result = cli_runner.invoke(app, ["wt", "path", "1"])
        assert result.exit_code == 0
        assert str(temp_git_repo) in result.output

    def test_path_branch(self, cli_runner: CycloptsTestRunner, temp_git_repo):
        """Test path for branch returns worktree path."""
        result = cli_runner.invoke(app, ["wt", "path", "feature-123"])
        assert result.exit_code == 0
        assert ".worktrees" in result.output
        assert "feature-123" in result.output


class TestWtBaseCommand:
    """Tests for hive wt base command."""

    def test_base_shows_directory(self, cli_runner: CycloptsTestRunner, temp_git_repo):
        """Test base shows worktrees directory."""
        result = cli_runner.invoke(app, ["wt", "base"])
        assert result.exit_code == 0
        assert ".worktrees" in result.output


class TestWtExistsCommand:
    """Tests for hive wt exists command."""

    def test_exists_main(self, cli_runner: CycloptsTestRunner, temp_git_repo):
        """Test exists returns 0 for main."""
        result = cli_runner.invoke(app, ["wt", "exists", "main"])
        assert result.exit_code == 0

    def test_exists_nonexistent(self, cli_runner: CycloptsTestRunner, temp_git_repo):
        """Test exists returns 1 for non-existent worktree."""
        result = cli_runner.invoke(app, ["wt", "exists", "nonexistent"])
        assert result.exit_code == 1


class TestWtCdCommand:
    """Tests for hive wt cd command."""

    def test_cd_main(self, cli_runner: CycloptsTestRunner, temp_git_repo):
        """Test cd main outputs main repo path."""
        result = cli_runner.invoke(app, ["wt", "cd", "main"])
        assert result.exit_code == 0
        assert str(temp_git_repo) in result.output

    def test_cd_nonexistent_branch(self, cli_runner: CycloptsTestRunner, temp_git_repo):
        """Test cd non-existent branch fails."""
        result = cli_runner.invoke(app, ["wt", "cd", "nonexistent"])
        assert result.exit_code == 1
        assert "does not exist" in result.output

    def test_cd_no_branch_non_interactive(
        self, cli_runner: CycloptsTestRunner, temp_git_repo
    ):
        """Test cd without branch in non-interactive mode fails."""
        # CycloptsTestRunner is non-interactive by default
        result = cli_runner.invoke(app, ["wt", "cd"])
        assert result.exit_code == 1
        assert "not in interactive mode" in result.output


class TestWtDeleteCommand:
    """Tests for hive wt delete command."""

    def test_delete_main_fails(self, cli_runner: CycloptsTestRunner, temp_git_repo):
        """Test delete main fails."""
        result = cli_runner.invoke(app, ["wt", "delete", "main"])
        assert result.exit_code == 1
        assert "Cannot delete main" in result.output

    def test_delete_nonexistent_fails(
        self, cli_runner: CycloptsTestRunner, temp_git_repo
    ):
        """Test delete non-existent worktree fails."""
        result = cli_runner.invoke(app, ["wt", "delete", "nonexistent"])
        assert result.exit_code == 1
        assert "does not exist" in result.output


class TestWtCreateCommand:
    """Tests for hive wt create command."""

    def test_create_main_fails(self, cli_runner: CycloptsTestRunner, temp_git_repo):
        """Test create main fails."""
        result = cli_runner.invoke(app, ["wt", "create", "main"])
        assert result.exit_code == 1

    def test_create_new_branch(self, cli_runner: CycloptsTestRunner, temp_git_repo):
        """Test create new branch worktree."""
        result = cli_runner.invoke(
            app, ["wt", "create", "test-feature", "--no-install"]
        )
        assert result.exit_code == 0
        assert "Created worktree" in result.output
        assert "test-feature" in result.output


class TestWtEnsureCommand:
    """Tests for hive wt ensure command."""

    def test_ensure_agent_1(self, cli_runner: CycloptsTestRunner, temp_git_repo):
        """Test ensure agent 1 returns main repo."""
        result = cli_runner.invoke(app, ["wt", "ensure", "1"])
        assert result.exit_code == 0
        assert str(temp_git_repo) in result.output

    def test_ensure_agent_2_non_interactive(
        self, cli_runner: CycloptsTestRunner, temp_git_repo
    ):
        """Test ensure agent 2 in non-interactive mode fails."""
        result = cli_runner.invoke(app, ["wt", "ensure", "2"])
        assert result.exit_code == 1
        assert "Interactive mode required" in result.output


class TestProfilePickerIntegration:
    """Tests for profile feature integration with the picker sentinels and runtime.

    These tests avoid the temp_git_repo fixture (which fails locally due to
    1Password-backed git commit signing) by exercising the sentinel definitions,
    runtime settings mutations, and dynamic-runner logic directly.
    """

    def test_action_change_profile_sentinel_defined(self):
        """ACTION_CHANGE_PROFILE sentinel is defined and distinct from others."""
        from hive_cli.commands.wt import (
            ACTION_CHANGE_AGENT,
            ACTION_CHANGE_PROFILE,
            ACTION_CHANGE_WORKDIR,
            ACTION_TOGGLE_SKIP_PERMISSIONS,
        )

        assert ACTION_CHANGE_PROFILE
        assert ACTION_CHANGE_PROFILE != ACTION_CHANGE_AGENT
        assert ACTION_CHANGE_PROFILE != ACTION_CHANGE_WORKDIR
        assert ACTION_CHANGE_PROFILE != ACTION_TOGGLE_SKIP_PERMISSIONS

    def test_runtime_agent_profile_can_be_set(self, monkeypatch):
        """RuntimeSettings.agent_profile field can be set and cleared."""
        from hive_cli.config import get_runtime_settings, reset_settings

        monkeypatch.delenv("HIVE_AGENT_PROFILE", raising=False)
        reset_settings()
        # Also reset runtime settings singleton
        import hive_cli.config.runtime as rt_mod

        rt_mod._runtime_settings = None

        rt = get_runtime_settings()
        assert rt.agent_profile is None

        rt.agent_profile = "work"
        assert rt.agent_profile == "work"

        rt.agent_profile = None
        assert rt.agent_profile is None

        # Cleanup
        rt_mod._runtime_settings = None
        reset_settings()

    def test_agent_profile_round_trips_in_child_env(self, monkeypatch):
        """HIVE_AGENT_PROFILE is included in build_child_env() when set."""
        import hive_cli.config.runtime as rt_mod
        from hive_cli.config import reset_settings

        monkeypatch.delenv("HIVE_AGENT_PROFILE", raising=False)
        rt_mod._runtime_settings = None

        rt = rt_mod.RuntimeSettings()
        rt.agent_profile = "work"
        env = rt.build_child_env()
        assert env.get("HIVE_AGENT_PROFILE") == "work"

        # Cleanup
        rt_mod._runtime_settings = None
        reset_settings()

    def test_agent_profile_cleared_from_child_env_when_none(self, monkeypatch):
        """HIVE_AGENT_PROFILE is removed from child env when set to None."""
        import hive_cli.config.runtime as rt_mod
        from hive_cli.config import reset_settings

        # Seed env with a stale value
        monkeypatch.setenv("HIVE_AGENT_PROFILE", "stale-profile")
        rt_mod._runtime_settings = None

        rt = rt_mod.RuntimeSettings()
        # Explicitly clear it
        rt.agent_profile = None
        env = rt.build_child_env()
        assert "HIVE_AGENT_PROFILE" not in env

        # Cleanup
        rt_mod._runtime_settings = None
        reset_settings()

    def test_interactive_selection_forces_dynamic_runner(
        self, cli_runner, monkeypatch, tmp_path
    ):
        """hive run -w=- always uses dynamic runner (so ^P profile works).

        When worktree='-' (interactive), the picker can set agent/profile/
        skip-perms after use_dynamic_runner is computed, so dynamic runner must
        always be forced. We verify by checking subprocess.run (not os.execvpe)
        is called.
        """
        from unittest.mock import patch

        from hive_cli.config import reload_config

        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

        with (
            patch("shutil.which", return_value="/usr/bin/claude"),
            patch(
                "hive_cli.commands.exec_runner.get_git_root",
                return_value=tmp_path,
            ),
            patch("hive_cli.config.loader.find_config_files", return_value=[]),
            # Provide a fake select_and_change_to_worktree that picks main
            patch(
                "hive_cli.commands.exec_runner.select_and_change_to_worktree",
                return_value=(True, "main"),
            ),
            patch("hive_cli.commands.run.subprocess.run") as mock_run,
            patch("hive_cli.commands.exec_runner.os.execvpe") as mock_execvpe,
        ):
            reload_config()
            mock_run.return_value.returncode = 0
            # Use --worktree=- (with =) so cyclopts doesn't treat '-' as a flag
            cli_runner.invoke(
                app, ["run", "-a", "claude", "--worktree=-", "--no-resume"]
            )

        # Dynamic runner uses subprocess.run, not os.execvpe
        assert mock_run.call_count >= 1
        mock_execvpe.assert_not_called()
