"""Bridge for running a synchronous service function off the event loop.

`call` runs `fn` on a daemon thread rather than asyncio's default executor:
`asyncio.run()` (which prompt_toolkit's `Application.run` uses) joins the
default executor's threads on exit, so a picker closed while a refiner sat
inside a slow `git fetch` would not return until the fetch did. A daemon
thread lets the app exit at once; the function keeps checking its `cancel`
event to stop early, and every command inside it has a timeout.
"""

from __future__ import annotations

import asyncio
import functools
import threading
import time
from collections.abc import Callable
from concurrent.futures import Executor, Future
from typing import Any

from ..core import trace

Progress = Callable[[str], None]
Cancel = threading.Event


class _DaemonThreadExecutor(Executor):
    """One daemon thread per call; never joined at loop shutdown."""

    def submit(self, fn: Callable[..., Any], /, *args: Any, **kwargs: Any) -> Future:
        future: Future = Future()

        def run() -> None:
            if not future.set_running_or_notify_cancel():
                return
            try:
                future.set_result(fn(*args, **kwargs))
            except BaseException as exc:  # delivered to the awaiting coroutine
                future.set_exception(exc)

        threading.Thread(target=run, name="hive-aio", daemon=True).start()
        return future


_EXECUTOR = _DaemonThreadExecutor()


async def call(fn: Callable[..., Any], /, *args: Any, **kwargs: Any) -> Any:
    """Run a sync service function in a daemon thread; HiveError propagates."""
    started = time.perf_counter()
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(
            _EXECUTOR, functools.partial(fn, *args, **kwargs)
        )
    finally:
        trace.event(
            "aio",
            getattr(fn, "__qualname__", repr(fn)),
            ms=(time.perf_counter() - started) * 1000,
        )
