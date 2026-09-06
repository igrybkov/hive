"""`hive doctor`: environment facts and startup/hot-path timings. No printing.

`timings()` runs each phase of a `hive run`/`hive status` start in-process,
reading `core.trace.spawns` before and after so every row says how many
commands it spawned; the import cost is measured in a fresh interpreter
(`python -X importtime`) because this process has already imported
everything. Run it with `hive doctor --timing` before and after a
performance change; assert spawn counts, not milliseconds, in tests.
"""

from __future__ import annotations

import platform
import shutil
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .. import __version__
from ..agents.detection import get_available_agents
from ..config import get_settings, reset_settings
from ..core import proc, trace
from ..core.errors import HiveError
from ..git import list_worktrees
from ..mux import get_mux
from . import status as status_service


@dataclass(frozen=True)
class Timing:
    phase: str
    ms: float
    spawns: int


def _phase(name: str, fn: Callable[[], object]) -> Timing:
    before = trace.spawns
    started = time.perf_counter()
    fn()
    return Timing(name, (time.perf_counter() - started) * 1000, trace.spawns - before)


def parse_importtime(stderr: str) -> tuple[float, float]:
    """(ms spent inside hive_cli modules, cumulative ms of `import hive_cli.app`).

    Parses `python -X importtime` output: `import time: self | cumulative | name`.
    """
    own_us = 0
    total_us = 0
    for line in stderr.splitlines():
        if not line.startswith("import time:"):
            continue
        parts = line.split("|")
        if len(parts) != 3:
            continue
        name = parts[2].strip()
        try:
            self_us = int(parts[0].split(":", 1)[1])
            cumulative_us = int(parts[1])
        except ValueError:
            continue
        if name == "hive_cli" or name.startswith("hive_cli."):
            own_us += self_us
        if name == "hive_cli.app":
            total_us = cumulative_us
    return own_us / 1000, total_us / 1000


def import_timings() -> list[Timing]:
    """Import cost of `hive_cli.app`, measured in a fresh interpreter."""
    result = proc.run(
        [sys.executable, "-X", "importtime", "-c", "import hive_cli.app"],
        timeout=30,
    )
    own_ms, total_ms = parse_importtime(result.stderr)
    return [
        Timing("import app (hive_cli modules)", own_ms, 0),
        Timing("import app (with dependencies)", total_ms, 0),
    ]


def _reload_settings() -> None:
    reset_settings()
    get_settings()


def timings(main_repo: Path) -> list[Timing]:
    """One Timing per startup/hot-path phase, in the order they happen."""
    rows = import_timings()
    rows.append(_phase("load config", _reload_settings))
    worktrees: list = []
    rows.append(
        _phase("list worktrees", lambda: worktrees.extend(list_worktrees(main_repo)))
    )
    rows.append(
        _phase("status collect", lambda: status_service.collect_status(main_repo))
    )
    return rows


def _version_of(binary: str, prefix: str) -> str:
    if shutil.which(binary) is None:
        return "not found"
    result = proc.run([binary, "--version"], timeout=5)
    if not result.ok:
        return "error"
    return result.stdout.strip().removeprefix(prefix)


def environment() -> list[tuple[str, str]]:
    """(name, value) rows: versions, multiplexer, agents on PATH."""
    try:
        mux = get_mux()
        multiplexer = mux.name if mux else "none (not inside a session)"
    except HiveError as exc:  # e.g. tmux until F6 lands
        multiplexer = str(exc)
    return [
        ("hive", __version__),
        ("python", platform.python_version()),
        ("git", _version_of("git", "git version ")),
        ("zellij", _version_of("zellij", "zellij ")),
        ("multiplexer", multiplexer),
        ("agents", ", ".join(get_available_agents()) or "none found"),
    ]
