"""Tests for services/pane.py.

apply_workdir_override moved here from commands/exec_runner.py's
_apply_workdir_override (A0 step 6), dropping its leading underscore now
that it's a cross-module service function. run_loop/`_restart_loop`/
`_single_run`/`_select_for_iteration` are new: the restart-loop and
single-run bodies of commands/exec_runner.py's run_in_worktree, with
printing extracted into clear_screen/progress/confirm_restart callbacks
and Zellij pane-renaming extracted into an on_branch_selected callback.
run_in_worktree itself is still covered end-to-end via the CLI in
test_run.py/test_wt.py/test_wt_cli.py -- these tests exercise run_loop
directly with fake callbacks/pick functions.

F0 adds the pane context: open_pane_context (identity + state server),
run_agent (Popen + lifecycle updates) and the loop's status publishing,
tested against FakeMux and real pane sockets under short_tmp.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest
from fakes import FakeMux

from hive_cli.config import get_runtime_settings
from hive_cli.core import paths
from hive_cli.mux.base import PaneInfo
from hive_cli.services.pane import (
    PaneContext,
    apply_workdir_override,
    null_context,
    open_pane_context,
    run_agent,
    run_loop,
)
from hive_cli.state import client
from hive_cli.state.pane_state import PaneState
from hive_cli.state.server import PaneStateServer

# ---------------------------------------------------------------------------
# apply_workdir_override
# ---------------------------------------------------------------------------


class TestApplyWorkdirOverride:
    def test_noop_when_no_override(self, tmp_path, monkeypatch):
        """Without rt.workdir, cwd is not changed and override list stays None."""
        from hive_cli.config import get_runtime_settings

        rt = get_runtime_settings()
        rt.workdir = None
        rt.workdir_extras_override = None

        primary = tmp_path / "primary"
        primary.mkdir()
        monkeypatch.chdir(primary)

        apply_workdir_override(primary)

        assert Path(os.getcwd()).resolve() == primary.resolve()
        assert rt.workdir_extras_override is None

    def test_swap_sets_cwd_and_extras(self, tmp_path, monkeypatch):
        """Override: cwd→chosen, primary prepended to extras, chosen dropped."""
        from hive_cli.config import get_runtime_settings, load_config

        primary = tmp_path / "primary"
        primary.mkdir()
        chosen = tmp_path / "chosen"
        chosen.mkdir()
        other = tmp_path / "other"
        other.mkdir()

        config_file = tmp_path / ".hive.yml"
        config_file.write_text(
            f"""
extra_dirs:
  - {chosen}
  - {other}
"""
        )
        load_config.cache_clear()

        rt = get_runtime_settings()
        rt.workdir = chosen
        rt.workdir_extras_override = None

        monkeypatch.chdir(primary)
        try:
            with (
                patch(
                    "hive_cli.config.loader.find_config_files",
                    return_value=[config_file],
                ),
                patch("hive_cli.git.get_main_repo", return_value=tmp_path),
            ):
                apply_workdir_override(primary)

            assert Path(os.getcwd()).resolve() == chosen.resolve()
            assert rt.workdir_extras_override == [str(primary), str(other)]
        finally:
            rt.workdir = None
            rt.workdir_extras_override = None


# ---------------------------------------------------------------------------
# run_loop
# ---------------------------------------------------------------------------


def _fake_pick_sequence(*results):
    """A `pick` stand-in that returns each of results in turn, then repeats last."""
    results = list(results)

    def pick(worktree, last_selected_branch=None, **kwargs):
        return results.pop(0) if results else results[-1]

    return pick


class TestRunLoopSingle:
    def test_single_run_execvp_path(self, monkeypatch):
        monkeypatch.setattr(
            "hive_cli.services.pane.get_runtime_settings", lambda: _FakeRT()
        )
        calls = []

        def fake_execvpe(exe, argv, env):
            calls.append((exe, argv, env))

        with patch("hive_cli.services.pane.os.execvpe", side_effect=fake_execvpe):
            result = run_loop(
                ["claude"],
                _fake_pick_sequence((True, "main")),
                runner=lambda cmd: 0,
            )

        assert result == 0
        assert calls == [("claude", ["claude"], {})]

    def test_single_run_cancelled_returns_1(self):
        result = run_loop(
            ["claude"],
            _fake_pick_sequence((False, None)),
            runner=lambda cmd: 0,
        )
        assert result == 1

    def test_single_run_custom_runner_skips_execvp(self):
        calls = []

        def custom_runner(cmd):
            calls.append(cmd)
            return 42

        with patch("hive_cli.services.pane.os.execvpe") as mock_execvpe:
            result = run_loop(
                ["claude"],
                _fake_pick_sequence((True, "main")),
                runner=custom_runner,
                run_command=custom_runner,
            )

        mock_execvpe.assert_not_called()
        assert calls == [["claude"]]
        assert result == 42

    def test_on_branch_selected_and_clear_screen_called(self):
        selected = []
        cleared = []

        run_loop(
            ["claude"],
            _fake_pick_sequence((True, "feat")),
            runner=lambda cmd: 0,
            use_execvp=False,
            on_branch_selected=selected.append,
            clear_screen=lambda: cleared.append(True),
        )

        assert selected == ["feat"]
        assert cleared == [True]


class TestRunLoopRestart:
    def test_restart_loop_runs_until_pick_fails(self):
        run_count = []

        def runner(cmd):
            run_count.append(cmd)
            return 0

        result = run_loop(
            ["claude"],
            _fake_pick_sequence((True, "main"), (True, "main"), (False, None)),
            runner=runner,
            restart=True,
            worktree="main",
        )

        assert result == 0
        assert len(run_count) == 2

    def test_restart_confirmation_calls_confirm_restart_each_time(self):
        confirm_calls = []

        run_loop(
            ["claude"],
            _fake_pick_sequence((True, "main"), (False, None)),
            runner=lambda cmd: 0,
            restart_confirmation=True,
            worktree="main",
            confirm_restart=lambda: confirm_calls.append(True),
        )

        assert confirm_calls == [True]

    def test_progress_receives_restart_message(self):
        messages = []

        run_loop(
            ["claude"],
            _fake_pick_sequence((True, "main"), (False, None)),
            runner=lambda cmd: 0,
            restart=True,
            worktree="main",
            restart_message="custom restart message",
            progress=messages.append,
        )

        assert any("custom restart message" in m for m in messages)

    def test_keyboard_interrupt_returns_0_and_reports_stopped(self):
        messages = []

        def runner(cmd):
            raise KeyboardInterrupt

        result = run_loop(
            ["claude"],
            _fake_pick_sequence((True, "main")),
            runner=runner,
            restart=True,
            worktree="main",
            progress=messages.append,
        )

        assert result == 0
        assert any("Stopped" in m for m in messages)

    def test_worktrees_disabled_does_not_force_interactive(self):
        seen_worktree = []

        def pick(worktree, last_selected_branch=None, **kwargs):
            seen_worktree.append(worktree)
            return False, None

        run_loop(
            ["claude"],
            pick,
            runner=lambda cmd: 0,
            restart=True,
            worktree=None,
            worktrees_enabled=False,
        )

        assert seen_worktree == [None]


class _FakeRT:
    agent = None
    workdir = None
    workdir_extras_override = None

    def build_child_env(self):
        return {}


# ---------------------------------------------------------------------------
# open_pane_context
# ---------------------------------------------------------------------------


def _pane(pane_id: str, tab_id: str) -> PaneInfo:
    return PaneInfo(
        id=pane_id,
        tab_id=tab_id,
        title="",
        command="",
        cwd="",
        focused=True,
        exited=False,
        suspended=False,
    )


class TestOpenPaneContext:
    def test_open_context_outside_mux_is_noop(self, short_tmp):
        ctx = open_pane_context(mux=None)  # get_mux() -> None: no ZELLIJ in env
        assert ctx.server is None and ctx.sock_path is None
        ctx.update(status="busy")  # no-op
        ctx.close()
        assert list(short_tmp.rglob("*.sock")) == []  # XDG_RUNTIME_DIR
        assert get_runtime_settings().pane_sock is None

    def test_null_context_serves_nothing(self):
        ctx = null_context()
        assert ctx.server is None and ctx.mux is None
        ctx.update(status="busy")
        ctx.close()

    def test_open_context_self_assigns_identity(self, short_tmp):
        session_dir = paths.session_sock_dir("s")
        session_dir.mkdir(parents=True)
        one = PaneStateServer(
            session_dir / "1.sock", PaneState(session="s", pane_id="1", hive_pane_id=1)
        )
        two = PaneStateServer(
            session_dir / "2.sock", PaneState(session="s", pane_id="2", hive_pane_id=2)
        )
        fake = FakeMux(pane_id="3", session="s", panes=[_pane("3", "t1")])
        with one, two:
            ctx = open_pane_context(mux=fake, labels=["Anton", "Bohdan", "Chris"])
            try:
                st = ctx.server.state
                assert st.hive_pane_id == 3 and st.label == "Chris"
                assert st.tab_id == "t1" and st.session == "s" and st.pane_id == "3"
                assert st.hive_pid == os.getpid() and st.status == "selecting"
                rt = get_runtime_settings()
                assert rt.pane_id_int == 3 and rt.pane_label == "Chris"
                assert ctx.sock_path == session_dir / "3.sock"
                assert rt.pane_sock == str(ctx.sock_path)
                assert client.get_state(ctx.sock_path)["hive_pane_id"] == 3
            finally:
                ctx.close()
        assert not (session_dir / "3.sock").exists()

    def test_open_context_respects_hive_pane_id_env(self, monkeypatch):
        monkeypatch.setenv("HIVE_PANE_ID", "5")
        monkeypatch.setenv("HIVE_PANE_LABEL", "Emily")
        monkeypatch.setenv("HIVE_AGENT", "claude")
        monkeypatch.setenv("HIVE_AGENT_PROFILE", "work")
        ctx = open_pane_context(mux=FakeMux(pane_id="9", session="s"), labels=["x"])
        try:
            st = ctx.server.state
            assert st.hive_pane_id == 5 and st.label == "Emily"
            assert st.agent == "claude" and st.profile == "work"
            assert st.tab_id == ""  # pane not listed by the mux
        finally:
            ctx.close()

    def test_open_context_uses_configured_labels_by_default(self):
        ctx = open_pane_context(mux=FakeMux(pane_id="4", session="s"))
        try:
            assert ctx.server.state.hive_pane_id == 1
            assert ctx.server.state.label == "Anton"  # zellij.pane_labels[0]
        finally:
            ctx.close()

    def test_open_context_without_pane_identity_is_noop(self):
        ctx = open_pane_context(mux=FakeMux(pane_id=None, session="s"))
        assert ctx.server is None and ctx.session == "s"

    def test_close_restores_signal_handlers(self):
        import signal

        before = signal.getsignal(signal.SIGTERM)
        ctx = open_pane_context(mux=FakeMux(pane_id="4", session="s"), labels=[])
        assert signal.getsignal(signal.SIGTERM) is not before
        ctx.close()
        assert signal.getsignal(signal.SIGTERM) is before


# ---------------------------------------------------------------------------
# run_agent
# ---------------------------------------------------------------------------


class TestRunAgent:
    def test_run_agent_sets_running_then_exited(self, short_tmp):
        with PaneStateServer(short_tmp / "3.sock", PaneState(pane_id="3")) as srv:
            ctx = PaneContext(None, "s", "3", srv.sock_path, srv)
            seen = []

            class Child:
                pid = 4242

                def wait(self):
                    seen.append(srv.state)
                    return 3

            with patch(
                "hive_cli.services.pane.subprocess.Popen", return_value=Child()
            ) as popen:
                assert run_agent(["claude"], {"A": "1"}, ctx) == 3
            popen.assert_called_once_with(
                ["claude"], env={"A": "1"}, cwd=None, stderr=None
            )
            assert (seen[0].status, seen[0].agent_pid) == ("running", 4242)
            assert (srv.state.status, srv.state.agent_pid) == ("exited", 0)

    def test_run_agent_second_interrupt_terminates_child(self):
        class Child:
            pid = 1

            def __init__(self):
                self.waits = 0
                self.terminated = False

            def wait(self):
                self.waits += 1
                if self.waits <= 2:
                    raise KeyboardInterrupt
                return 130

            def terminate(self):
                self.terminated = True

        child = Child()
        with patch("hive_cli.services.pane.subprocess.Popen", return_value=child):
            assert run_agent(["a"], {}, null_context()) == 130
        assert child.terminated and child.waits == 3

    def test_run_agent_without_context(self):
        class Child:
            pid = 1

            def wait(self):
                return 0

        with patch("hive_cli.services.pane.subprocess.Popen", return_value=Child()):
            assert run_agent(["a"], {}, None, cwd="/tmp", stderr=2) == 0


# ---------------------------------------------------------------------------
# run_loop with a live pane context
# ---------------------------------------------------------------------------


def _open(tab_id="t1", labels=("Anton",)):
    fake = FakeMux(pane_id="3", session="s", panes=[_pane("3", tab_id)])
    return fake, open_pane_context(mux=fake, labels=list(labels))


class TestRunLoopLifecycle:
    def test_run_loop_publishes_lifecycle(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        wt = tmp_path / "wt"
        wt.mkdir()
        fake, ctx = _open()
        sock = ctx.sock_path
        seen = []

        def pick(worktree, last_selected_branch=None, **kwargs):
            seen.append(client.get_state(sock)["status"])
            os.chdir(wt)
            return True, "feat"

        def runner(cmd):
            seen.append(client.get_state(sock))
            return 0

        assert run_loop(["claude"], pick, runner=runner, use_execvp=False, ctx=ctx) == 0

        assert seen[0] == "selecting"
        starting = seen[1]
        assert starting["status"] == "starting" and starting["branch"] == "feat"
        assert Path(starting["worktree_path"]).resolve() == wt.resolve()
        assert not sock.exists()
        renames = fake.named("rename_pane")
        assert renames and renames[-1][1][0] == "3"
        assert "[feat]" in renames[-1][1][1]
        tabs = fake.named("rename_tab")
        assert tabs and tabs[-1][1][0] == "t1"
        assert "✖" in tabs[-1][1][1] or "·" in tabs[-1][1][1]

    def test_run_loop_default_runner_reports_running_and_exited(self, tmp_path):
        fake, ctx = _open()
        sock = ctx.sock_path
        seen = []

        class Child:
            pid = 77

            def wait(self):
                seen.append(client.get_state(sock))
                return 0

        with patch("hive_cli.services.pane.subprocess.Popen", return_value=Child()):
            run_loop(["claude"], _fake_pick_sequence((True, "main")), ctx=ctx)
        assert (seen[0]["status"], seen[0]["agent_pid"]) == ("running", 77)
        titles = [c[1][1] for c in fake.named("rename_pane")]
        assert titles and "[main]" in titles[-1]

    def test_single_run_never_execs_while_serving(self, tmp_path):
        fake, ctx = _open()
        calls = []
        with patch("hive_cli.services.pane.os.execvpe") as mock_execvpe:
            run_loop(
                ["claude"],
                _fake_pick_sequence((True, "main")),
                runner=lambda cmd: calls.append(cmd) or 0,
                use_execvp=True,
                ctx=ctx,
            )
        mock_execvpe.assert_not_called()
        assert calls == [["claude"]]

    def test_restart_request_relaunches(self):
        fake, ctx = _open()
        sock, server = ctx.sock_path, ctx.server
        picks, runs = [], []

        def pick(worktree, last_selected_branch=None, **kwargs):
            picks.append(worktree)
            return True, "main"

        def runner(cmd):
            runs.append(cmd)
            if len(runs) == 1:
                assert client.request(sock, "restart")
                assert server.restart_requested.is_set()
            else:
                assert not server.restart_requested.is_set()  # cleared per iteration
                assert client.request(sock, "stop")
            return 0

        result = run_loop(
            ["claude"], pick, runner=runner, restart=True, worktree="main", ctx=ctx
        )
        assert result == 0
        assert len(picks) == 2 and len(runs) == 2
        assert not sock.exists()

    def test_stop_request_ends_loop(self):
        fake, ctx = _open()
        sock = ctx.sock_path
        messages, runs = [], []

        def runner(cmd):
            runs.append(cmd)
            assert client.request(sock, "stop")
            return 0

        result = run_loop(
            ["claude"],
            _fake_pick_sequence((True, "main")),
            runner=runner,
            restart=True,
            worktree="main",
            restart_message="RESTARTING",
            progress=messages.append,
            ctx=ctx,
        )
        assert result == 0 and runs == [["claude"]]
        assert not any("RESTARTING" in m for m in messages)
        assert not sock.exists()

    def test_run_loop_closes_socket_when_pick_exits(self):
        fake, ctx = _open()
        sock = ctx.sock_path

        def pick(worktree, last_selected_branch=None, **kwargs):
            raise SystemExit(1)

        with pytest.raises(SystemExit):
            run_loop(["claude"], pick, runner=lambda cmd: 0, ctx=ctx)
        assert not sock.exists()
