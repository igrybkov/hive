"""ui/board.py: LiveBoard paints only on change; watch() is driven through a pipe."""

from __future__ import annotations

import io
import os
import threading

import pytest
from rich.console import Console
from rich.text import Text

from hive_cli.ui import board
from hive_cli.ui.board import LiveBoard


class RecordingLive:
    """Stand-in for rich.live.Live: records updates, exposes a real Console."""

    def __init__(self, console=None, **kwargs):
        self.console = console or Console(file=io.StringIO(), width=80)
        self.kwargs = kwargs
        self.updates: list[tuple[object, bool]] = []

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def update(self, renderable, *, refresh=False) -> None:
        self.updates.append((renderable, refresh))


def _board(monkeypatch) -> LiveBoard:
    """A LiveBoard over RecordingLive and its own console (never the shared one)."""
    monkeypatch.setattr(board, "Live", RecordingLive)
    return LiveBoard(Console(file=io.StringIO(), width=80))


class TestLiveBoard:
    def test_show_paints_only_on_change(self, monkeypatch):
        live_board = _board(monkeypatch)
        assert live_board.show(Text("same")) is True
        assert live_board.show(Text("same")) is False
        assert live_board.show(Text("changed")) is True
        updates = live_board._live.updates
        assert len(updates) == 2 and all(refresh for _, refresh in updates)

    def test_style_change_counts_as_change(self, monkeypatch):
        live_board = _board(monkeypatch)
        live_board.show(Text("x"))
        assert live_board.show(Text("x", style="red")) is True

    def test_resize_repaints_identical_content(self, monkeypatch):
        live_board = _board(monkeypatch)
        live_board.show(Text("x"))
        live_board._live.console.width = 40
        assert live_board.show(Text("x")) is True

    def test_live_is_alternate_screen_without_auto_refresh(self, monkeypatch):
        assert _board(monkeypatch)._live.kwargs == {
            "screen": True,
            "auto_refresh": False,
            "redirect_stdout": False,
            "redirect_stderr": False,
        }


def _quiet_console(monkeypatch) -> Console:
    """A console whose `clear` must never be called by the watch loop."""

    def clear(*_args, **_kwargs):
        raise AssertionError("console.clear() inside the watch loop")

    # force_terminal: Rich's Live only writes frames to a terminal
    console = Console(file=io.StringIO(), width=80, force_terminal=True)
    monkeypatch.setattr(console, "clear", clear)
    monkeypatch.setattr("hive_cli.ui.console.out.clear", clear)
    return console


class _Stdin:
    """A pipe standing in for the tty; `send` writes keys after the first paint."""

    def __init__(self):
        self.r, self.w = os.pipe()
        self.painted = threading.Event()
        self.closed = False

    def render(self, data):
        self.painted.set()
        return Text(repr(data))

    def send(self, *chunks: bytes, then_close: bool = False) -> None:
        def run():
            assert self.painted.wait(3), "board never painted"
            for chunk in chunks:
                os.write(self.w, chunk)
            if then_close:
                os.close(self.w)
                self.closed = True

        threading.Thread(target=run, daemon=True).start()

    def close(self) -> None:
        os.close(self.r)
        if not self.closed:
            os.close(self.w)


@pytest.fixture
def stdin():
    pipe = _Stdin()
    yield pipe
    pipe.close()


class TestWatch:
    def test_q_returns_key_and_last_data_without_clearing(self, monkeypatch, stdin):
        console = _quiet_console(monkeypatch)
        stdin.send(b"q")
        key, data = board.watch(
            lambda: [1, 2], stdin.render, interval=60, stdin=stdin.r, console=console
        )
        assert (key, data) == ("q", [1, 2])
        assert "[1, 2]" in console.file.getvalue()

    def test_r_refreshes_immediately(self, monkeypatch, stdin):
        console = _quiet_console(monkeypatch)
        calls: list[int] = []
        second = threading.Event()

        def collect():
            calls.append(1)
            if len(calls) == 2:
                second.set()
            return len(calls)

        def sender():
            assert stdin.painted.wait(3)
            os.write(stdin.w, b"r")
            assert second.wait(3), "r did not trigger a refresh"
            os.write(stdin.w, b"q")

        threading.Thread(target=sender, daemon=True).start()
        key, data = board.watch(
            collect, stdin.render, interval=60, stdin=stdin.r, console=console
        )
        assert key == "q" and len(calls) >= 2

    def test_exit_key_returns_it(self, monkeypatch, stdin):
        console = _quiet_console(monkeypatch)
        stdin.send(b"x", b"\r")  # x is ignored, Enter is an exit key
        key, data = board.watch(
            lambda: "S",
            stdin.render,
            interval=60,
            exit_keys=("\r", "\n"),
            stdin=stdin.r,
            console=console,
        )
        assert (key, data) == ("\r", "S")

    def test_ctrl_c_byte_quits(self, monkeypatch, stdin):
        console = _quiet_console(monkeypatch)
        stdin.send(b"\x03")
        key, _ = board.watch(
            lambda: 1, stdin.render, interval=60, stdin=stdin.r, console=console
        )
        assert key == "\x03"

    def test_eof_returns_none(self, monkeypatch, stdin):
        console = _quiet_console(monkeypatch)
        stdin.send(then_close=True)
        key, data = board.watch(
            lambda: 1, stdin.render, interval=60, stdin=stdin.r, console=console
        )
        assert (key, data) == (None, 1)

    def test_collect_error_propagates(self, monkeypatch, stdin):
        console = _quiet_console(monkeypatch)

        def collect():
            raise ValueError("boom")

        with pytest.raises(ValueError, match="boom"):
            board.watch(
                collect, stdin.render, interval=60, stdin=stdin.r, console=console
            )
