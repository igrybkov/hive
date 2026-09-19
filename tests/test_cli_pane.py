"""CLI tests for `hive pane`: each subcommand invokes the patched service/mux
call with the parsed arguments."""

from __future__ import annotations

import json
from unittest.mock import patch

from fakes import FakeMux

from hive_cli.app import app
from hive_cli.core import paths
from hive_cli.core.errors import HiveError
from hive_cli.mux.base import PaneInfo


class TestPaneNew:
    def test_calls_service_with_parsed_args(self, cli_runner):
        with patch(
            "hive_cli.commands.pane.session.new_agent_pane", return_value="7"
        ) as m:
            result = cli_runner.invoke(
                app, ["pane", "new", "-a", "codex", "-p", "work", "-w", "feat"]
            )
        assert result.exit_code == 0
        assert "7" in result.output
        m.assert_called_once_with(
            agent="codex", profile="work", branch="feat", tab_id=None, focus=True
        )

    def test_no_focus_flag(self, cli_runner):
        with patch(
            "hive_cli.commands.pane.session.new_agent_pane", return_value="7"
        ) as m:
            cli_runner.invoke(app, ["pane", "new", "--no-focus"])
        assert m.call_args.kwargs["focus"] is False

    def test_tab_id_flag(self, cli_runner):
        with patch(
            "hive_cli.commands.pane.session.new_agent_pane", return_value="7"
        ) as m:
            cli_runner.invoke(app, ["pane", "new", "--tab-id", "t2"])
        assert m.call_args.kwargs["tab_id"] == "t2"

    def test_hive_error_prints_and_exits(self, cli_runner):
        with patch(
            "hive_cli.commands.pane.session.new_agent_pane",
            side_effect=HiveError("boom"),
        ):
            result = cli_runner.invoke(app, ["pane", "new"])
        assert result.exit_code == 1
        assert "boom" in result.output


class TestPaneShell:
    def test_branch_splits_a_pane(self, cli_runner, tmp_path):
        wt_path = tmp_path / "feat"
        wt_path.mkdir()
        mux = FakeMux(session="s")
        with (
            patch("hive_cli.commands.pane.get_mux", return_value=mux),
            patch("hive_cli.commands.pane.get_worktree_path", return_value=wt_path),
        ):
            result = cli_runner.invoke(app, ["pane", "shell", "-w", "feat"])
        assert result.exit_code == 0
        calls = mux.named("new_pane")
        assert len(calls) == 1
        assert calls[0][2]["cwd"] == str(wt_path)

    def test_floating_calls_service(self, cli_runner, tmp_path):
        wt_path = tmp_path / "feat"
        wt_path.mkdir()
        with (
            patch("hive_cli.commands.pane.session.floating_shell") as m,
            patch("hive_cli.commands.pane.get_worktree_path", return_value=wt_path),
        ):
            result = cli_runner.invoke(
                app, ["pane", "shell", "-w", "feat", "--floating"]
            )
        assert result.exit_code == 0
        m.assert_called_once_with(worktree=wt_path, here=False)

    def test_here_outside_worktree_errors(self, cli_runner, tmp_path, monkeypatch):
        outside = tmp_path / "outside"
        outside.mkdir()
        monkeypatch.chdir(outside)
        with (
            patch(
                "hive_cli.commands.pane.get_main_repo",
                return_value=tmp_path / "main",
            ),
            patch("hive_cli.commands.pane.list_worktrees", return_value=[]),
        ):
            result = cli_runner.invoke(app, ["pane", "shell", "--here"])
        assert result.exit_code == 1


class TestPaneList:
    def test_json_output(self, cli_runner):
        panes = [
            PaneInfo(
                id="3",
                tab_id="t1",
                title="c1",
                command="",
                cwd="",
                focused=True,
                exited=False,
                suspended=False,
            )
        ]
        mux = FakeMux(session="s", panes=panes)
        with patch("hive_cli.commands.pane.get_mux", return_value=mux):
            result = cli_runner.invoke(app, ["pane", "list", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data[0]["id"] == "3"
        assert data[0]["focused"] is True

    def test_table_output(self, cli_runner):
        panes = [
            PaneInfo(
                id="3",
                tab_id="t1",
                title="c1",
                command="",
                cwd="",
                focused=False,
                exited=False,
                suspended=False,
            )
        ]
        mux = FakeMux(session="s", panes=panes)
        with patch("hive_cli.commands.pane.get_mux", return_value=mux):
            result = cli_runner.invoke(app, ["pane", "list"])
        assert result.exit_code == 0
        assert "3" in result.output


class TestPaneFocusClose:
    def test_focus(self, cli_runner):
        mux = FakeMux(session="s")
        with patch("hive_cli.commands.pane.get_mux", return_value=mux):
            cli_runner.invoke(app, ["pane", "focus", "3"])
        assert mux.named("focus_pane") == [("focus_pane", ("3",), {})]

    def test_close(self, cli_runner):
        mux = FakeMux(session="s")
        with patch("hive_cli.commands.pane.get_mux", return_value=mux):
            cli_runner.invoke(app, ["pane", "close", "3"])
        assert mux.named("close_pane") == [("close_pane", ("3",), {})]


class TestPaneRestart:
    def test_calls_client_request(self, cli_runner):
        mux = FakeMux(session="s")
        with (
            patch("hive_cli.commands.pane.get_mux", return_value=mux),
            patch(
                "hive_cli.commands.pane.client.request", return_value=True
            ) as request,
        ):
            result = cli_runner.invoke(app, ["pane", "restart", "3"])
        assert result.exit_code == 0
        request.assert_called_once_with(paths.pane_sock("s", "3"), "restart")

    def test_no_live_pane_errors(self, cli_runner):
        mux = FakeMux(session="s")
        with (
            patch("hive_cli.commands.pane.get_mux", return_value=mux),
            patch("hive_cli.commands.pane.client.request", return_value=False),
        ):
            result = cli_runner.invoke(app, ["pane", "restart", "3"])
        assert result.exit_code == 1


class TestPaneLayout:
    def test_no_arg_prints_current_mode(self, cli_runner):
        mux = FakeMux(session="s")
        with (
            patch("hive_cli.commands.pane.get_mux", return_value=mux),
            patch(
                "hive_cli.commands.pane.session.get_agents_layout",
                return_value="stacked",
            ) as get,
        ):
            result = cli_runner.invoke(app, ["pane", "layout"])
        assert result.exit_code == 0
        assert "stacked" in result.output
        get.assert_called_once_with(mux=mux)

    def test_mode_arg_sets_it(self, cli_runner):
        mux = FakeMux(session="s")
        with (
            patch("hive_cli.commands.pane.get_mux", return_value=mux),
            patch(
                "hive_cli.commands.pane.session.set_agents_layout",
                return_value="tabs",
            ) as set_,
        ):
            result = cli_runner.invoke(app, ["pane", "layout", "tabs"])
        assert result.exit_code == 0
        assert "tabs" in result.output
        set_.assert_called_once_with("tabs", mux=mux)

    def test_hive_error_prints_and_exits(self, cli_runner):
        mux = FakeMux(session="s")
        with (
            patch("hive_cli.commands.pane.get_mux", return_value=mux),
            patch(
                "hive_cli.commands.pane.session.set_agents_layout",
                side_effect=HiveError("unknown agents layout: 'bogus'"),
            ),
        ):
            result = cli_runner.invoke(app, ["pane", "layout", "bogus"])
        assert result.exit_code == 1
        assert "bogus" in result.output


class TestPaneHold:
    def test_calls_service_with_argv_and_callables(self, cli_runner):
        # Mocks session.hold itself -- never let the real os.execvp default
        # (bound once at hold()'s def time, so patching os.execvp afterward
        # would not intercept it) run inside a test process.
        with patch("hive_cli.commands.pane.session.hold") as m:
            result = cli_runner.invoke(app, ["pane", "hold", "--", "some-cmd"])
        assert result.exit_code == 0
        args, kwargs = m.call_args
        assert args[0] == ["some-cmd"]
        assert callable(kwargs["prompt"]) and callable(kwargs["wait"])

    def test_renames_pane_to_hold_marker_before_waiting(self, cli_runner):
        # `TmuxMux.list_panes` keys `suspended` off `title.startswith("hold:")`,
        # so this rename has to land before `session.hold` blocks on Enter.
        mux = FakeMux(pane_id="%3")
        with (
            patch("hive_cli.commands.pane.get_mux", return_value=mux),
            patch("hive_cli.commands.pane.session.hold"),
        ):
            result = cli_runner.invoke(app, ["pane", "hold", "--", "claude"])
        assert result.exit_code == 0
        assert mux.named("rename_pane") == [("rename_pane", ("%3", "hold: claude"), {})]

    def test_no_mux_skips_rename(self, cli_runner):
        with (
            patch("hive_cli.commands.pane.get_mux", return_value=None),
            patch("hive_cli.commands.pane.session.hold") as m,
        ):
            result = cli_runner.invoke(app, ["pane", "hold", "--", "claude"])
        assert result.exit_code == 0
        m.assert_called_once()

    def test_hold_marker_carries_hive_pane_identity_under_tmux(
        self, cli_runner, monkeypatch
    ):
        """tmux has no layout-assigned pane title the way Zellij does -- an
        agent pane's `hold: ` marker is the only place its identity survives
        until `hive run` starts. Without HIVE_PANE_ID/LABEL in the title,
        services/session.py can't tell a suspended agent pane from any other
        held pane (e.g. `watch-tests`), and `new_agent_pane` duplicates it."""
        monkeypatch.setenv("HIVE_PANE_ID", "2")
        monkeypatch.setenv("HIVE_PANE_LABEL", "Bohdan")
        mux = FakeMux(pane_id="%3")
        with (
            patch("hive_cli.commands.pane.get_mux", return_value=mux),
            patch("hive_cli.commands.pane.session.hold"),
        ):
            result = cli_runner.invoke(app, ["pane", "hold", "--", "hive", "run"])
        assert result.exit_code == 0
        assert mux.named("rename_pane") == [
            ("rename_pane", ("%3", "hold: c2: Bohdan"), {})
        ]

    def test_hold_marker_without_label_omits_it(self, cli_runner, monkeypatch):
        monkeypatch.setenv("HIVE_PANE_ID", "2")
        monkeypatch.delenv("HIVE_PANE_LABEL", raising=False)
        mux = FakeMux(pane_id="%3")
        with (
            patch("hive_cli.commands.pane.get_mux", return_value=mux),
            patch("hive_cli.commands.pane.session.hold"),
        ):
            result = cli_runner.invoke(app, ["pane", "hold", "--", "hive", "run"])
        assert result.exit_code == 0
        assert mux.named("rename_pane") == [("rename_pane", ("%3", "hold: c2"), {})]


class TestPaneSetStatusTitle:
    def test_set_status_calls_backend(self, cli_runner):
        with patch("hive_cli.commands.pane.set_pane_status", return_value=True) as m:
            result = cli_runner.invoke(app, ["pane", "set-status", "[working]"])
        assert result.exit_code == 0
        m.assert_called_once_with("[working]")

    def test_set_title_not_in_zellij(self, cli_runner):
        with patch("hive_cli.commands.pane.set_pane_custom_title", return_value=False):
            result = cli_runner.invoke(app, ["pane", "set-title", "x"])
        assert "Not running in Zellij" in result.output
