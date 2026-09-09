"""watch_session: multiplexes pane sockets, mux polling and the facts
refresher (F4) into one async generator of SessionEvent.

The only place in the control plane that touches sockets or the mux
directly -- `ui/tui` calls services through `services.aio.call` only.
Every task this starts is named ``hive-watch-*`` and cancelled (then
awaited) when the generator is closed, so `aclose()` leaves nothing running.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from pathlib import Path

from ..core import paths
from ..git import GitSummary
from ..mux.base import Mux, PaneInfo, TabInfo
from ..state import client, protocol
from ..state.pane_state import PaneState
from . import aio


@dataclass(frozen=True)
class PaneAdded:
    state: PaneState


@dataclass(frozen=True)
class PaneStateChanged:
    state: PaneState


@dataclass(frozen=True)
class PaneRemoved:
    pane_id: str


@dataclass(frozen=True)
class TabsChanged:
    tabs: tuple[TabInfo, ...]
    panes: tuple[PaneInfo, ...]


@dataclass(frozen=True)
class FactsUpdated:
    facts: dict[str, GitSummary]  # key: worktree path as str


SessionEvent = PaneAdded | PaneStateChanged | PaneRemoved | TabsChanged | FactsUpdated


async def _follow(sock: Path, queue: asyncio.Queue[SessionEvent]) -> None:
    """Subscribe to one pane socket, pushing PaneAdded then PaneStateChanged.

    The greeting and the subscribe reply both carry the current state at the
    same version; dedupe on version so that pair produces exactly one
    PaneAdded, not a spurious PaneStateChanged right behind it. Swallows a
    dead/vanished socket; always emits PaneRemoved on the way out, keyed by
    the pane's own (raw, un-sanitised) id from the last state seen -- not
    `sock.stem`, which for tmux ids is the sanitised socket filename
    (`paths.pane_sock`: "%7" -> "p7.sock") and would never match the "%7"
    key `_reduce`'s state dict actually uses.
    """
    writer: asyncio.StreamWriter | None = None
    last_version: int | None = None
    last_pane_id: str | None = None
    try:
        reader, writer = await asyncio.open_unix_connection(str(sock))
        writer.write(protocol.encode({"op": "subscribe"}))
        await writer.drain()
        while line := await reader.readline():
            msg = protocol.decode(line)
            if not msg or msg.get("type") != "state":
                continue
            state = PaneState.from_dict(msg)
            if state.version == last_version:
                continue
            event = (
                PaneAdded(state) if last_version is None else PaneStateChanged(state)
            )
            last_version = state.version
            last_pane_id = state.pane_id
            await queue.put(event)
    except (ConnectionRefusedError, FileNotFoundError, OSError):
        pass
    finally:
        if writer is not None:
            writer.close()
        await queue.put(PaneRemoved(last_pane_id or sock.stem))


async def _discover(
    mux: Mux,
    session_dir: Path,
    poll_s: float,
    queue: asyncio.Queue[SessionEvent],
    tasks: dict[str, asyncio.Task],
) -> None:
    """Every poll_s: start a `_follow` task for each new pane socket, and
    push TabsChanged when mux.list_panes/list_tabs differ from last time."""
    last: tuple[tuple[PaneInfo, ...], tuple[TabInfo, ...]] | None = None
    while True:
        socks = await aio.call(client.list_pane_sockets, session_dir)
        for sock in socks:
            if sock.name not in tasks:
                tasks[sock.name] = asyncio.create_task(
                    _follow(sock, queue), name=f"hive-watch-follow-{sock.stem}"
                )
        panes, tabs = await aio.call(mux.list_panes), await aio.call(mux.list_tabs)
        current = (tuple(panes), tuple(tabs))
        if current != last:
            last = current
            await queue.put(TabsChanged(tuple(tabs), tuple(panes)))
        await asyncio.sleep(poll_s)


async def _facts_loop(
    facts_fn: Callable[[], dict[str, GitSummary]] | None,
    facts_s: float,
    queue: asyncio.Queue[SessionEvent],
) -> None:
    """Every facts_s, push a fresh FactsUpdated; a no-op without facts_fn."""
    if facts_fn is None:
        return
    while True:
        facts = await aio.call(facts_fn)
        await queue.put(FactsUpdated(facts))
        await asyncio.sleep(facts_s)


async def watch_session(
    mux: Mux,
    session: str,
    *,
    poll_s: float = 3.0,
    facts_s: float = 30.0,
    session_dir: Path | None = None,
    facts_fn: Callable[[], dict[str, GitSummary]] | None = None,
) -> AsyncIterator[SessionEvent]:
    """Multiplexes `_discover` and `_facts_loop` through one queue; both run
    immediately, then every poll_s/facts_s. Cancelling the generator
    (aclose) cancels every task it started.
    """
    session_dir = (
        session_dir if session_dir is not None else paths.session_sock_dir(session)
    )
    queue: asyncio.Queue[SessionEvent] = asyncio.Queue()
    tasks: dict[str, asyncio.Task] = {}
    runner = [
        asyncio.create_task(
            _discover(mux, session_dir, poll_s, queue, tasks),
            name="hive-watch-discover",
        ),
        asyncio.create_task(
            _facts_loop(facts_fn, facts_s, queue), name="hive-watch-facts"
        ),
    ]
    try:
        while True:
            yield await queue.get()
    finally:
        for task in [*runner, *tasks.values()]:
            task.cancel()
        await asyncio.gather(*runner, *tasks.values(), return_exceptions=True)
