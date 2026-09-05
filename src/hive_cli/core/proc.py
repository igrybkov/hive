"""The one place hive spawns captured, non-interactive commands."""

from __future__ import annotations

import subprocess
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from . import trace
from .errors import ProcError


@dataclass(frozen=True)
class Result:
    argv: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


def run(
    argv: Sequence[str | Path],
    *,
    cwd: str | Path | None = None,
    timeout: float = 10.0,
    env: Mapping[str, str] | None = None,
    input: str | None = None,
    check: bool = False,
) -> Result:
    """Run argv without a shell, capture text output; raise only if ``check`` fails."""
    args = tuple(str(a) for a in argv)
    started = time.perf_counter()
    try:
        cp = subprocess.run(
            args,
            cwd=cwd,
            env=env,
            input=input,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        result = Result(args, cp.returncode, cp.stdout, cp.stderr)
    except FileNotFoundError:
        result = Result(args, 127, "", f"{args[0]}: command not found")
    except subprocess.TimeoutExpired as exc:
        result = Result(args, 124, exc.stdout or "", f"timed out after {timeout}s")
    trace.event(
        "proc", args[0], ms=(time.perf_counter() - started) * 1000, rc=result.returncode
    )
    if check and not result.ok:
        raise ProcError(result)
    return result
