"""Parse tmux control-mode (`tmux -C`) notification lines and stream them.

Control mode prefixes every notification with `%`; `%begin`/`%end` wrap
command replies (irrelevant here -- hive never sends commands over this
connection, only reads notifications) and `%output`/`%extended-output`
floods on every byte a pane writes, so callers must drop those cheaply
rather than react to them. `tmux_control_events` is the one place hive
spawns a long-lived subprocess outside `core.proc.run` (documented in
docs/ARCHITECTURE.md): a streamed `-C attach-session` client can't be
captured/waited like every other command.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass

LAYOUT_EVENTS = {
    "window-add",
    "window-close",
    # tmux emits this instead of "window-close" when the closed window was
    # not linked into another session -- the only case a hive session ever
    # produces (verified against a recorded transcript,
    # tests/fixtures/tmux_control.txt).
    "unlinked-window-close",
    "window-renamed",
    "layout-change",
    "session-changed",
}


@dataclass(frozen=True)
class ControlEvent:
    kind: str  # e.g. window-add, layout-change, output, exit, begin, end, unknown
    args: tuple[str, ...]


def parse_line(line: str) -> ControlEvent | None:
    """ "%window-add @3" -> ControlEvent("window-add", ("@3",)); non-% lines -> None."""
    line = line.rstrip("\n")
    if not line.startswith("%"):
        return None
    kind, *args = line[1:].split(" ")
    return ControlEvent(kind or "unknown", tuple(args))


async def tmux_control_events(
    session: str, *, server: str = "hive"
) -> AsyncIterator[ControlEvent]:
    """Attach in control mode and yield parsed notification lines.

    Keeps stdin open (tmux detaches a `-C` client on stdin EOF) and
    terminates the client when the generator is closed or exhausted.
    """
    proc = await asyncio.create_subprocess_exec(
        "tmux",
        "-L",
        server,
        "-C",
        "attach-session",
        "-t",
        session,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    assert proc.stdout is not None
    try:
        while raw := await proc.stdout.readline():
            event = parse_line(raw.decode(errors="replace"))
            if event is not None:
                yield event
    finally:
        if proc.returncode is None:
            proc.terminate()
            _ = await proc.wait()
