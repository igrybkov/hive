"""Live boards: Rich Live on the alternate screen, painted only on change.

`LiveBoard.show` hashes the rendered segments (and the terminal size) and
skips `Live.update` when nothing changed, so an idle `hive status --watch`
writes zero bytes per tick: a repaint every tick makes the multiplexer
re-render the pane and its bars, and cleared lines land in scrollback.

`watch` is the loop around it. A worker thread runs `collect()` and hands
the result over a queue plus a wake pipe; the main thread owns the terminal
(raw mode, exactly one `select` per event, the board) and never touches git.
Keys: `q` or Ctrl+C quit, `r` refreshes now, any of `exit_keys` returns to
the caller, everything else is ignored. A resize repaints at once.
"""

from __future__ import annotations

import hashlib
import os
import queue
import select
import signal
import sys
import termios
import threading
import tty
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from typing import Any, TypeVar

from rich.console import Console, RenderableType
from rich.live import Live

from . import console as ui_console

T = TypeVar("T")

QUIT_KEYS = ("q", "\x03")  # raw mode delivers Ctrl+C as a byte
REFRESH_KEY = "r"


class LiveBoard:
    """Rich Live on the alternate screen that writes only when the content changed."""

    def __init__(self, console: Console | None = None):
        self._live = Live(
            console=console or ui_console.out,
            screen=True,
            auto_refresh=False,
            redirect_stdout=False,
            redirect_stderr=False,
        )
        self._digest: str | None = None

    def __enter__(self) -> LiveBoard:
        self._live.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._live.stop()

    def show(self, renderable: RenderableType) -> bool:
        """Render to segments, hash them; update only when the hash changed.

        Returns True if painted.
        """
        console = self._live.console
        options = console.options
        segments = console.render(renderable, options)
        text = "".join(s.text + str(s.style) for s in segments)
        digest = hashlib.sha1(
            f"{options.size}\0{text}".encode(), usedforsecurity=False
        ).hexdigest()
        if digest == self._digest:
            return False
        self._digest = digest
        self._live.update(renderable, refresh=True)
        return True


@contextmanager
def _raw_mode(fd: int) -> Iterator[None]:
    """Raw input on a tty; a no-op when `fd` is not a terminal (pipes, tests)."""
    try:
        old = termios.tcgetattr(fd)
    except (termios.error, OSError, ValueError):
        yield
        return
    tty.setraw(fd)
    try:
        yield
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


@contextmanager
def _repaint_on_resize(wake_w: int) -> Iterator[None]:
    """Poke the wake pipe on SIGWINCH so the board repaints for the new size."""
    if not hasattr(signal, "SIGWINCH") or (
        threading.current_thread() is not threading.main_thread()
    ):
        yield
        return

    def handler(_signum: int, _frame: object) -> None:
        try:
            os.write(wake_w, b"w")
        except OSError:
            pass

    previous = signal.signal(signal.SIGWINCH, handler)
    try:
        yield
    finally:
        signal.signal(signal.SIGWINCH, previous)


def _collector(
    collect: Callable[[], Any],
    results: queue.Queue,
    wake_w: int,
    refresh: threading.Event,
    quit_: threading.Event,
    interval: float,
) -> None:
    """Worker: collect, hand over, poke the wake pipe, wait for the interval or `r`."""
    try:
        while not quit_.is_set():
            try:
                data: Any = collect()
            except Exception as exc:  # re-raised on the main thread
                data = exc
            if quit_.is_set():
                break
            results.put(data)
            os.write(wake_w, b"x")
            refresh.wait(interval)
            refresh.clear()
    except OSError:
        pass  # the main thread has gone
    finally:
        os.close(wake_w)


def _latest(results: queue.Queue, last: Any) -> Any:
    while True:
        try:
            last = results.get_nowait()
        except queue.Empty:
            return last


def _on_wake(
    wake_r: int,
    results: queue.Queue,
    board: LiveBoard,
    render: Callable[[Any], RenderableType],
    last: Any,
) -> Any:
    """The worker (or a resize) poked the pipe: paint the latest data."""
    os.read(wake_r, 64)
    last = _latest(results, last)
    if isinstance(last, Exception):
        raise last
    if last is not None:
        board.show(render(last))
    return last


def _on_key(
    fd: int, refresh: threading.Event, exit_keys: Sequence[str]
) -> tuple[bool, str | None]:
    """(done, key): done at EOF (key None), on a quit key or an exit key."""
    key = os.read(fd, 1).decode(errors="replace")
    if not key:
        return True, None
    if key in QUIT_KEYS or key in exit_keys:
        return True, key
    if key == REFRESH_KEY:
        refresh.set()
    return False, key


def _event_loop(
    fd: int,
    wake_r: int,
    results: queue.Queue,
    board: LiveBoard,
    render: Callable[[Any], RenderableType],
    refresh: threading.Event,
    exit_keys: Sequence[str],
) -> tuple[str | None, Any]:
    last: Any = None
    while True:
        readable, _, _ = select.select([fd, wake_r], [], [])
        if wake_r in readable:
            last = _on_wake(wake_r, results, board, render, last)
        if fd in readable:
            done, key = _on_key(fd, refresh, exit_keys)
            if done:
                return key, last


def watch(
    collect: Callable[[], T],
    render: Callable[[T], RenderableType],
    *,
    interval: float = 5.0,
    exit_keys: Sequence[str] = (),
    stdin: int | None = None,
    console: Console | None = None,
) -> tuple[str | None, T | None]:
    """Collect every `interval` seconds on a worker; paint on change until a key.

    Returns (key, last_data): the key that ended the loop (`q`, Ctrl+C or
    one of `exit_keys`; None at EOF) and the most recent collected value.
    """
    fd = sys.stdin.fileno() if stdin is None else stdin
    results: queue.Queue = queue.Queue()
    wake_r, wake_w = os.pipe()
    refresh = threading.Event()
    quit_ = threading.Event()
    worker = threading.Thread(
        target=_collector,
        args=(collect, results, wake_w, refresh, quit_, interval),
        name="hive-watch",
        daemon=True,
    )
    try:
        with _raw_mode(fd), LiveBoard(console) as board, _repaint_on_resize(wake_w):
            worker.start()
            return _event_loop(fd, wake_r, results, board, render, refresh, exit_keys)
    except KeyboardInterrupt:
        return "\x03", None
    finally:
        quit_.set()
        refresh.set()
        os.close(wake_r)
