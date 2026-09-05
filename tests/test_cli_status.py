"""Integration tests for the `hive status` command's CLI surface.

Drives the real CLI end to end. See test_git_status.py, test_services_status.py,
test_ui_views_status.py, and test_ui_pickers_status.py for the unit-level tests
of the modules this command composes.
"""

from __future__ import annotations

from pathlib import Path

from conftest import CycloptsTestRunner, commit_file, git

from hive_cli.app import app


class TestStatusCliOneShot:
    def test_no_worktrees_full_and_compact(
        self, cli_runner: CycloptsTestRunner, temp_git_repo
    ):
        full = cli_runner.invoke(app, ["status"])
        compact = cli_runner.invoke(app, ["status", "--compact"])
        assert full.exit_code == 0 and compact.exit_code == 0
        assert "Agent 1 (main)" in full.output
        assert "Agents" in compact.output and "main" in compact.output

    def test_two_worktrees_dirty_and_ahead(
        self,
        cli_runner: CycloptsTestRunner,
        repo_with_origin: Path,
        isolated_worktrees,
        make_worktree,
    ):
        dirty_wt = make_worktree("dirty-branch")
        (dirty_wt / "untracked.txt").write_text("wip")
        ahead_wt = make_worktree("ahead-branch")
        git("branch", "--set-upstream-to=origin/main", "ahead-branch", cwd=ahead_wt)
        commit_file(ahead_wt, "new.txt", "content", message="ahead work")

        result = cli_runner.invoke(app, ["status"])
        assert result.exit_code == 0
        assert "dirty-branch" in result.output
        assert "ahead-branch" in result.output
        assert "+1" in result.output
        assert "*" in result.output

    def test_task_and_shared_notes_shown_in_full_view(
        self, cli_runner: CycloptsTestRunner, temp_git_repo
    ):
        tasks_dir = temp_git_repo / ".claude" / "local-agents" / "tasks"
        tasks_dir.mkdir(parents=True)
        (tasks_dir / "agent-1.md").write_text("investigate the bug\n")
        (tasks_dir.parent / "shared-notes.md").write_text("## Decision\nuse X\n")

        result = cli_runner.invoke(app, ["status"])
        assert "investigate the bug" in result.output
        assert "Shared Notes" in result.output and "Decision" in result.output


class TestStatusCliInteractiveFlag:
    def test_dash_i_exits_1_even_when_a_branch_is_selected(
        self, cli_runner: CycloptsTestRunner, temp_git_repo, mocker
    ):
        # See the bug noted on TestInteractiveStatus (test_ui_pickers_status.py):
        # -i always exits 1.
        mocker.patch(
            "hive_cli.ui.pickers.status.fuzzy_select", side_effect=["main", None]
        )
        mocker.patch(
            "hive_cli.ui.pickers.status._show_worktree_detail", return_value="back"
        )
        result = cli_runner.invoke(app, ["status", "-i"])
        assert result.exit_code == 1
