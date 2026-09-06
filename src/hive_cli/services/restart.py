"""Backoff after fast exits, shared by `hive run` and `hive zellij` --restart loops."""

from __future__ import annotations

import time
from collections.abc import Callable


class RestartFloor:
    """Sleep after fast exits so a crashing agent can't restart in a tight loop.

    1 s after the first exit under 10 s, then 2, 4, capped at 5; a run of
    10 s or longer resets the sequence and costs nothing. `sleep`/`clock`
    default to `time.sleep`/`time.monotonic` (resolved when constructed, so
    tests may patch `time.sleep` or inject fakes).
    """

    LONG_RUN_S = 10.0
    MAX_SLEEP_S = 5.0

    def __init__(
        self,
        sleep: Callable[[float], object] | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._sleep = sleep or time.sleep
        self._clock = clock or time.monotonic
        self._started_at: float | None = None
        self._next = 1.0

    def started(self) -> None:
        self._started_at = self._clock()

    def exited(self) -> None:
        """Sleep if the run that just ended was shorter than 10 s."""
        if self._started_at is None:
            return
        run_length = self._clock() - self._started_at
        self._started_at = None
        if run_length >= self.LONG_RUN_S:
            self._next = 1.0
            return
        self._sleep(self._next)
        self._next = min(self._next * 2, self.MAX_SLEEP_S)
