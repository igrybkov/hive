"""CLI-level tests for `hive wt` subcommands (cyclopts app invocation).

Split out of test_wt_flows.py to keep individual test files under the
600-line guideline; see that file for the underlying flow-function tests
these CLI commands are built on.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from hive_cli.app import app
from hive_cli.config import reload_config

# ---------------------------------------------------------------------------
# CLI: hive wt exec
# ---------------------------------------------------------------------------


class TestWtExecCli:
    def test_exec_in_specific_worktree_execs_command(
        self, cli_runner, temp_git_repo, make_worktree, isolated_worktrees
    ):
        wt_path = make_worktree("feat-a")

        with patch("hive_cli.ui.flows.worktrees.os.execvpe") as mock_execvpe:
            result = cli_runner.invoke(
                app, ["wt", "exec", "-c", "echo hi", "-w", "feat-a"]
            )

        assert result.exit_code == 0
        mock_execvpe.assert_called_once()
        final_command, argv, _env = mock_execvpe.call_args.args
        assert final_command == "echo"
        assert argv == ["echo", "hi"]
        assert Path.cwd().resolve() == wt_path.resolve()

    def test_exec_nonexistent_branch_fails(
        self, cli_runner, temp_git_repo, isolated_worktrees
    ):
        result = cli_runner.invoke(
            app, ["wt", "exec", "-c", "echo hi", "-w", "never-created"]
        )
        assert result.exit_code == 1
        assert "does not exist" in result.output


# ---------------------------------------------------------------------------
# CLI: create / exists / path / cd chain
# ---------------------------------------------------------------------------


class TestWtCreateExistsPathCdChain:
    def test_full_chain(self, cli_runner, temp_git_repo, isolated_worktrees):
        create_result = cli_runner.invoke(
            app, ["wt", "create", "feat-chain", "--no-install"]
        )
        assert create_result.exit_code == 0

        exists_result = cli_runner.invoke(app, ["wt", "exists", "feat-chain"])
        assert exists_result.exit_code == 0

        path_result = cli_runner.invoke(app, ["wt", "path", "feat-chain"])
        assert path_result.exit_code == 0
        assert "feat-chain" in path_result.output

        cd_result = cli_runner.invoke(app, ["wt", "cd", "feat-chain"])
        assert cd_result.exit_code == 0
        assert path_result.output.strip() == cd_result.output.strip()


# ---------------------------------------------------------------------------
# CLI: worktrees.enabled = false gate
# ---------------------------------------------------------------------------


class TestWorktreesDisabled:
    def test_list_command_blocked_when_disabled(self, cli_runner, temp_git_repo):
        (temp_git_repo / ".hive.yml").write_text("worktrees:\n  enabled: false\n")
        reload_config()

        result = cli_runner.invoke(app, ["wt", "list"])

        assert result.exit_code == 1
        assert "disabled" in result.output

    def test_bare_wt_invokes_cd_default(self, cli_runner, temp_git_repo):
        """`hive wt` with no subcommand behaves like `hive wt cd`."""
        result = cli_runner.invoke(app, ["wt"])

        assert result.exit_code == 1
        assert "not in interactive mode" in result.output


# ---------------------------------------------------------------------------
# CLI: parent
# ---------------------------------------------------------------------------


class TestWtParentCli:
    def test_parent_prints_main_repo(self, cli_runner, temp_git_repo):
        result = cli_runner.invoke(app, ["wt", "parent"])
        assert result.exit_code == 0
        assert str(temp_git_repo) in result.output


# ---------------------------------------------------------------------------
# CLI: create — FileExistsError branch
# ---------------------------------------------------------------------------


class TestWtCreateCliErrors:
    def test_create_twice_fails_with_already_exists(
        self, cli_runner, temp_git_repo, isolated_worktrees
    ):
        first = cli_runner.invoke(app, ["wt", "create", "feat-dup", "--no-install"])
        assert first.exit_code == 0

        second = cli_runner.invoke(app, ["wt", "create", "feat-dup", "--no-install"])
        assert second.exit_code == 1
        assert "already exists" in second.output


# ---------------------------------------------------------------------------
# CLI: delete — uncommitted changes without --force
# ---------------------------------------------------------------------------


class TestWtDeleteCliDirty:
    def test_dirty_worktree_requires_force(
        self, cli_runner, temp_git_repo, make_worktree, isolated_worktrees
    ):
        wt_path = make_worktree("feat-a")
        (wt_path / "uncommitted.txt").write_text("oops")

        result = cli_runner.invoke(app, ["wt", "delete", "feat-a"])

        assert result.exit_code == 1
        assert "uncommitted changes" in result.output
        assert wt_path.exists()

    def test_dirty_worktree_deleted_with_force(
        self, cli_runner, temp_git_repo, make_worktree, isolated_worktrees
    ):
        wt_path = make_worktree("feat-a")
        (wt_path / "uncommitted.txt").write_text("oops")

        result = cli_runner.invoke(app, ["wt", "delete", "feat-a", "--force"])

        assert result.exit_code == 0
        assert not wt_path.exists()


# ---------------------------------------------------------------------------
# CLI: exec — invalid / empty command
# ---------------------------------------------------------------------------


class TestWtExecCliErrors:
    def test_empty_command_rejected(self, cli_runner, temp_git_repo):
        result = cli_runner.invoke(app, ["wt", "exec", "-c", ""])
        assert result.exit_code == 1
        assert "cannot be empty" in result.output

    def test_invalid_shell_syntax_rejected(self, cli_runner, temp_git_repo):
        # Unbalanced quote is invalid shlex syntax.
        result = cli_runner.invoke(app, ["wt", "exec", "-c", "'unterminated"])
        assert result.exit_code == 1
        assert "Invalid command" in result.output


# ---------------------------------------------------------------------------
# CLI: cd / ensure interactive branches (with pick_worktree mocked)
# ---------------------------------------------------------------------------


class TestWtInteractiveBranches:
    def test_cd_interactive_success(self, cli_runner, temp_git_repo, tmp_path):
        target = str(tmp_path / "somewhere")
        with (
            patch("hive_cli.commands.wt.is_interactive", return_value=True),
            patch(
                "hive_cli.commands.wt.pick_worktree",
                return_value=(target, "feat-a"),
            ),
        ):
            result = cli_runner.invoke(app, ["wt", "cd"])

        assert result.exit_code == 0
        assert target in result.output

    def test_cd_interactive_cancelled(self, cli_runner, temp_git_repo):
        with (
            patch("hive_cli.commands.wt.is_interactive", return_value=True),
            patch("hive_cli.commands.wt.pick_worktree", return_value=None),
        ):
            result = cli_runner.invoke(app, ["wt", "cd"])

        assert result.exit_code == 1

    def test_ensure_agent_2_interactive_success(
        self, cli_runner, temp_git_repo, tmp_path
    ):
        target = str(tmp_path / "somewhere")
        with (
            patch("hive_cli.commands.wt.is_interactive", return_value=True),
            patch(
                "hive_cli.commands.wt.pick_worktree",
                return_value=(target, "feat-a"),
            ),
        ):
            result = cli_runner.invoke(app, ["wt", "ensure", "2"])

        assert result.exit_code == 0
        assert target in result.output

    def test_ensure_agent_2_interactive_cancelled(self, cli_runner, temp_git_repo):
        with (
            patch("hive_cli.commands.wt.is_interactive", return_value=True),
            patch("hive_cli.commands.wt.pick_worktree", return_value=None),
        ):
            result = cli_runner.invoke(app, ["wt", "ensure", "2"])

        assert result.exit_code == 1
