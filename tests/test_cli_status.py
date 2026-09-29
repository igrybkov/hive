"""Integration tests for the `hive status` command's CLI surface.

Drives the real CLI end to end. See test_git_status.py, test_services_status.py,
test_ui_views_status.py, and test_ui_pickers_status.py for the unit-level tests
of the modules this command composes; test_tui_app.py covers the control-plane
TUI itself.
"""

from __future__ import annotations

import threading
from pathlib import Path

from conftest import CycloptsTestRunner, commit_file, git

from hive_cli.app import app
from hive_cli.core import paths
from hive_cli.state import client


def _run_inside_zellij(monkeypatch, mocker, session: str) -> None:
    """Simulate a TTY inside a Zellij session, so `status` reaches the TUI path."""
    monkeypatch.setenv("ZELLIJ", "0")
    monkeypatch.setenv("ZELLIJ_SESSION_NAME", session)
    mocker.patch("hive_cli.commands.status.is_interactive", return_value=True)


class TestStatusCliOneShot:
    def test_no_worktrees_full_and_compact(
        self, cli_runner: CycloptsTestRunner, temp_git_repo
    ):
        full = cli_runner.invoke(app, ["status", "--plain"])
        compact = cli_runner.invoke(app, ["status", "--plain", "--compact"])
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

        result = cli_runner.invoke(app, ["status", "--plain"])
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

        result = cli_runner.invoke(app, ["status", "--plain"])
        assert "investigate the bug" in result.output
        assert "Shared Notes" in result.output and "Decision" in result.output


class TestStatusCliNoTuiFallback:
    def test_bare_status_without_a_multiplexer_is_plain(
        self, cli_runner: CycloptsTestRunner, temp_git_repo
    ):
        """No ZELLIJ/TMUX in the environment (conftest deletes them): the
        default path falls back to the one-shot table without needing
        `--plain`, and without importing textual."""
        result = cli_runner.invoke(app, ["status"])
        assert result.exit_code == 0
        assert "Agent 1 (main)" in result.output

    def test_plain_never_imports_textual(self, temp_git_repo):
        import os
        import subprocess
        import sys

        env = {
            **os.environ,
            "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
        }
        # cyclopts' App.__call__ exits the process (sys.exit) after dispatch,
        # so the module check must run in a handler, not after the call.
        code = (
            "import sys\n"
            "from hive_cli.app import app\n"
            "try:\n"
            "    app(['status', '--plain'])\n"
            "except SystemExit:\n"
            "    pass\n"
            "print('textual' in sys.modules)\n"
        )
        out = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            check=True,
            cwd=temp_git_repo,
            env=env,
        ).stdout
        assert out.strip().splitlines()[-1] == "False"


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
    def test_focuses_existing_and_skips_running_one(
        self, cli_runner: CycloptsTestRunner, temp_git_repo, mocker
    ):
        toggle = mocker.patch(
            "hive_cli.commands.status.session.toggle_control_plane", return_value=True
        )
        run = mocker.patch("hive_cli.ui.tui.app.ControlPlaneApp.run")

        result = cli_runner.invoke(app, ["status", "--toggle"])

        assert result.exit_code == 0
        toggle.assert_called_once()
        run.assert_not_called()

    def test_starts_one_when_absent(
        self, cli_runner: CycloptsTestRunner, temp_git_repo, mocker, monkeypatch
    ):
        _run_inside_zellij(monkeypatch, mocker, "toggle-test")
        mocker.patch(
            "hive_cli.commands.status.session.toggle_control_plane",
            return_value=False,
        )
        run = mocker.patch("hive_cli.ui.tui.app.ControlPlaneApp.run")

        result = cli_runner.invoke(app, ["status", "--toggle", "--interval", "2"])

        assert result.exit_code == 0
        run.assert_called_once()

    def test_no_multiplexer_falls_back_to_plain(
        self, cli_runner: CycloptsTestRunner, temp_git_repo, mocker
    ):
        mocker.patch(
            "hive_cli.commands.status.session.toggle_control_plane",
            return_value=False,
        )
        run = mocker.patch("hive_cli.ui.tui.app.ControlPlaneApp.run")

        result = cli_runner.invoke(app, ["status", "--toggle"])

        assert result.exit_code == 0
        run.assert_not_called()
        assert "Agent 1 (main)" in result.output


class TestStatusCliRunsTheControlPlane:
    def test_watch_compact_runs_it(
        self, cli_runner: CycloptsTestRunner, temp_git_repo, mocker, monkeypatch
    ):
        """`--watch --compact` is the bundled layout's control-plane pane
        command, kept accepted but folded into the same TUI path."""
        _run_inside_zellij(monkeypatch, mocker, "watch-test")
        run = mocker.patch("hive_cli.ui.tui.app.ControlPlaneApp.run")

        result = cli_runner.invoke(app, ["status", "--watch", "--compact"])

        assert result.exit_code == 0
        run.assert_called_once()

    def test_bare_status_runs_it_and_clamps_interval(
        self, cli_runner: CycloptsTestRunner, temp_git_repo, mocker, monkeypatch
    ):
        _run_inside_zellij(monkeypatch, mocker, "bare-test")
        # Patched where it is defined: commands/status.py imports it lazily
        # (inside run_control_plane) precisely so --plain never pulls in
        # textual, so there is no module-level attribute to patch there.
        app_cls = mocker.patch("hive_cli.ui.tui.app.ControlPlaneApp")

        result = cli_runner.invoke(app, ["status", "--interval", "0.1"])

        assert result.exit_code == 0
        app_cls.return_value.run.assert_called_once()
        assert app_cls.call_args.kwargs["poll_s"] == 2.0  # floored, per perf rules

    def test_starts_and_closes_a_control_server(
        self, cli_runner: CycloptsTestRunner, temp_git_repo, mocker, monkeypatch
    ):
        _run_inside_zellij(monkeypatch, mocker, "control-server-test")
        ready = threading.Event()
        proceed = threading.Event()

        def fake_run(_self) -> None:
            ready.set()
            proceed.wait(2.0)

        mocker.patch("hive_cli.ui.tui.app.ControlPlaneApp.run", fake_run)
        result_box: dict = {}

        def invoke() -> None:
            result_box["result"] = cli_runner.invoke(app, ["status"])

        thread = threading.Thread(target=invoke)
        thread.start()
        try:
            assert ready.wait(2.0)
            sock = paths.control_sock("control-server-test")
            state = client.get_state(sock)
            assert state is not None and state["kind"] == "control"
        finally:
            proceed.set()
            thread.join(2.0)

        assert result_box["result"].exit_code == 0
        assert client.get_state(paths.control_sock("control-server-test")) is None
