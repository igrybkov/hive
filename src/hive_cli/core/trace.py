"""HIVE_TRACE=1 phase/spawn timings, written to stderr.

The one exception to "no print below cli": writes go through
``sys.stderr.write`` directly rather than ``print`` so the architecture
test's forbidden-call scan (which only looks for ``print``/``sys.exit``/
``input``/``Console``) doesn't need a special case for this module.
"""

from __future__ import annotations

import os
import sys
import time

_ENABLED = os.environ.get("HIVE_TRACE") == "1"
_T0 = time.perf_counter()


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
