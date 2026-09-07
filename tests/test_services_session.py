"""Tests for hive_cli.services.session: stale pane-socket cleanup on start,
and attach_argv()'s layout resolution (F2: renders "agent" per session)."""

from __future__ import annotations

from unittest.mock import patch

from fakes import FakeMux

from hive_cli.config.schema import ZellijConfig
from hive_cli.config.settings import HiveSettings
from hive_cli.core import paths
from hive_cli.services import session


def _start(mux, name):
    with patch("hive_cli.services.session.os.execvpe") as execvpe:
        session.start(
            ["zellij", "attach", "--create", name],
            {},
            session=name,
            mux=mux,
            restart=False,
            restart_delay=0,
            on_restart=lambda: None,
            on_stop=lambda: None,
        )
    execvpe.assert_called_once()


def test_session_start_removes_stale_sock_dir():
    stale = paths.session_sock_dir("s")
    stale.mkdir(parents=True)
    (stale / "3.sock").write_text("")
    mux = FakeMux(session="other")  # "s" is not running

    _start(mux, "s")

    assert not stale.exists()
    assert mux.named("session_exists") == [("session_exists", ("s",), {})]


def test_session_start_keeps_live_session_dir():
    live = paths.session_sock_dir("s")
    live.mkdir(parents=True)
    (live / "3.sock").write_text("")

    _start(FakeMux(session="s"), "s")

    assert (live / "3.sock").exists()


def test_session_start_without_mux_skips_cleanup():
    stale = paths.session_sock_dir("s")
    stale.mkdir(parents=True)

    _start(None, "s")

    assert stale.exists()


def test_clean_stale_sock_dir_tolerates_missing_dir():
    session.clean_stale_sock_dir(FakeMux(session="other"), "never-created")


def test_restart_loop_sleeps_after_fast_exits():
    from hive_cli.services.restart import RestartFloor

    class Clock:
        now = 1000.0

        def __call__(self):
            return self.now

    clock = Clock()
    slept: list[float] = []
    restarts: list[int] = []
    stops: list[int] = []

    def on_restart():
        restarts.append(1)
        if len(restarts) == 2:
            raise KeyboardInterrupt

    def fake_run(cmd, env):
        clock.now += 0.1

    with patch("hive_cli.services.session.subprocess.run", side_effect=fake_run) as run:
        session.start(
            ["zellij", "attach", "--create", "s"],
            {},
            session="s",
            mux=None,
            restart=True,
            restart_delay=0,
            on_restart=on_restart,
            on_stop=lambda: stops.append(1),
            restart_floor=RestartFloor(sleep=slept.append, clock=clock),
        )

    assert run.call_count == 2
    assert slept == [1] and stops == [1]


def _settings() -> HiveSettings:
    return HiveSettings(zellij=ZellijConfig())


class TestAttachArgv:
    def test_start_renders_and_attaches(self):
        mux = FakeMux(session="s")
        cmd = session.attach_argv(
            "agent", "s", mux=mux, hive="/opt/hive", settings=_settings()
        )
        rendered = paths.layouts_dir() / "s" / "session.kdl"
        assert rendered.is_file()
        assert rendered.read_text().startswith("layout {")
        assert cmd == ["fake-attach", "s", str(rendered)]

    def test_start_legacy_layout(self):
        mux = FakeMux(session="s")
        cmd = session.attach_argv(
            "agent-16", "s", mux=mux, hive="/opt/hive", settings=_settings()
        )
        assert cmd[0] == "fake-attach"
        assert cmd[1] == "s"
        assert cmd[2].endswith("bundled/agent-16.kdl")

    def test_resolve_layout_path_none(self):
        mux = FakeMux(session="s")
        cmd = session.attach_argv(
            None, "s", mux=mux, hive="/opt/hive", settings=_settings()
        )
        assert cmd == ["fake-attach", "s", ""]
