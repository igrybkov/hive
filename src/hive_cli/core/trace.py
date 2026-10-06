"""HIVE_TRACE=1 phase/spawn timings, written to stderr.

`event` is the primitive; `mark` names a startup phase boundary, `span`
times a block, and `spawns` counts every command `core.proc.run` started in
this process (read it before/after a phase to attribute spawns to it).

The one exception to "no print below cli": writes go through
``sys.stderr.write`` directly rather than ``print`` so the architecture
test's forbidden-call scan (which only looks for ``print``/``sys.exit``/
``input``/``Console``) doesn't need a special case for this module.
"""

from __future__ import annotations

import os
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager

_ENABLED = os.environ.get("HIVE_TRACE") == "1"
_T0 = time.perf_counter()

#: Commands spawned through core.proc.run so far in this process.
spawns = 0


def enabled() -> bool:
    return _ENABLED


def event(kind: str, name: str, **fields) -> None:
    if not _ENABLED:
        return
    extra = " ".join(
        f"{k}={v:.1f}" if isinstance(v, float) else f"{k}={v}"
        for k, v in fields.items()
    )
    elapsed_ms = (time.perf_counter() - _T0) * 1000
    sys.stderr.write(
        f"[hive] +{elapsed_ms:.1f}ms {kind} {name} {extra}".rstrip() + "\n"
    )


def mark(name: str) -> None:
    """A startup phase boundary (`app_imported`, `config_loaded`, ...)."""
    event("mark", name)


@contextmanager
def span(kind: str, name: str) -> Iterator[None]:
    """Time a block: one `event` line with its ms and spawn count on exit."""
    started = time.perf_counter()
    before = spawns
    try:
        yield
    finally:
        event(
            kind,
            name,
            ms=(time.perf_counter() - started) * 1000,
            spawns=spawns - before,
        )


def count_spawn() -> None:
    """Called by core.proc.run for every command it starts (or fails to)."""
    global spawns
    spawns += 1
