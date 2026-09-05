"""Bridge for running a synchronous service function off the event loop."""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Callable
from typing import Any

from ..core import trace

Progress = Callable[[str], None]
Cancel = threading.Event


async def call(fn: Callable[..., Any], /, *args: Any, **kwargs: Any) -> Any:
    """Run a sync service function in a thread; HiveError propagates unchanged."""
    started = time.perf_counter()
    try:
        return await asyncio.to_thread(fn, *args, **kwargs)
    finally:
        trace.event(
            "aio",
            getattr(fn, "__qualname__", repr(fn)),
            ms=(time.perf_counter() - started) * 1000,
        )
