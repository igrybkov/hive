"""Tests for hive_cli.services.session: stale pane-socket cleanup on start."""

from __future__ import annotations

from unittest.mock import patch

from fakes import FakeMux

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
