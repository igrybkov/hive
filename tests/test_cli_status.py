"""Integration tests for the `hive status` command's CLI surface.

Drives the real CLI end to end. See test_git_status.py, test_services_status.py,
test_ui_views_status.py, and test_ui_pickers_status.py for the unit-level tests
of the modules this command composes.
"""

from __future__ import annotations

import io
from pathlib import Path

from conftest import CycloptsTestRunner, commit_file, git
from rich.console import Console

from hive_cli.app import app


def render(renderable) -> str:
    buf = io.StringIO()
    Console(file=buf, width=100).print(renderable)
    return buf.getvalue()


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


class TestStatusCliToggle:
    def test_focuses_existing_and_skips_board(
        self, cli_runner: CycloptsTestRunner, temp_git_repo, mocker
    ):
        toggle = mocker.patch(
            "hive_cli.commands.status.session.toggle_control_plane", return_value=True
        )
        watch = mocker.patch("hive_cli.ui.board.watch")

        result = cli_runner.invoke(app, ["status", "--toggle"])

        assert result.exit_code == 0
        toggle.assert_called_once()
        watch.assert_not_called()

    def test_opens_compact_board_when_absent(
        self, cli_runner: CycloptsTestRunner, temp_git_repo, mocker
    ):
        mocker.patch(
            "hive_cli.commands.status.session.toggle_control_plane",
            return_value=False,
        )
        watch = mocker.patch("hive_cli.ui.board.watch", return_value=("q", None))

        result = cli_runner.invoke(app, ["status", "--toggle", "--interval", "2"])

        assert result.exit_code == 0
        watch.assert_called_once()
        assert watch.call_args.kwargs["interval"] == 2


class TestStatusCliWatch:
    def test_q_ends_watch_without_opening_the_picker(
        self, cli_runner: CycloptsTestRunner, temp_git_repo, mocker
    ):
        watch = mocker.patch("hive_cli.ui.board.watch", return_value=("q", None))
        picker = mocker.patch("hive_cli.ui.pickers.status.interactive_status")

        result = cli_runner.invoke(app, ["status", "--watch", "--interval", "2"])

        assert result.exit_code == 0
        assert watch.call_args.kwargs["interval"] == 2
        assert watch.call_args.kwargs["exit_keys"] == ("\r", "\n")
        picker.assert_not_called()

    def test_enter_opens_picker_then_returns_to_the_board(
        self, cli_runner: CycloptsTestRunner, temp_git_repo, mocker
    ):
        watch = mocker.patch(
            "hive_cli.ui.board.watch", side_effect=[("\r", ["S"]), ("q", None)]
        )
        picker = mocker.patch("hive_cli.ui.pickers.status.interactive_status")

        result = cli_runner.invoke(app, ["status", "-w", "-c"])

        assert result.exit_code == 0
        picker.assert_called_once_with(
            statuses=["S"], main_repo=temp_git_repo.resolve()
        )
        assert watch.call_count == 2

    def test_collect_and_render_are_wired_to_the_board(
        self, cli_runner: CycloptsTestRunner, temp_git_repo, mocker
    ):
        frames: list[str] = []

        def fake_watch(collect, render_frame, **kwargs):
            statuses = collect()
            frames.append(render(render_frame(statuses)))
            return "q", statuses

        mocker.patch("hive_cli.ui.board.watch", side_effect=fake_watch)

        result = cli_runner.invoke(app, ["status", "--watch", "--compact"])

        assert result.exit_code == 0
        assert "Agents" in frames[0] and "main" in frames[0]
        assert "Enter" in frames[0] and "q" in frames[0]
