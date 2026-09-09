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
from ..mux.tmux.control import LAYOUT_EVENTS, ControlEvent, tmux_control_events
from ..state import client, protocol
from ..state.pane_state import PaneState
from . import aio

_DEBOUNCE_S = 0.2


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


async def _start_new_follows(
    session_dir: Path,
    queue: asyncio.Queue[SessionEvent],
    tasks: dict[str, asyncio.Task],
) -> None:
    """One pass of `_discover`'s socket-dir scan: start `_follow` for any
    pane socket not already followed. Never touches the mux."""
    socks = await aio.call(client.list_pane_sockets, session_dir)
    for sock in socks:
        if sock.name not in tasks:
            tasks[sock.name] = asyncio.create_task(
                _follow(sock, queue), name=f"hive-watch-follow-{sock.stem}"
            )


async def _scan_sockets_loop(
    session_dir: Path,
    poll_s: float,
    queue: asyncio.Queue[SessionEvent],
    tasks: dict[str, asyncio.Task],
) -> None:
    """tmux: a socket-dir scan on the ordinary poll_s cadence, decoupled
    from `mux.list_panes`/`list_tabs` (those only run on a debounced
    control-mode event, per `_discover_events`). A newly split pane's
    hive-run socket can appear well after the layout-change event that
    created the pane -- without this, PaneAdded would only ever fire on
    the next unrelated layout event, if one ever comes. This never spawns
    tmux, so it doesn't count against "no list-panes polling"."""
    while True:
        await _start_new_follows(session_dir, queue, tasks)
        await asyncio.sleep(poll_s)


async def _refresh_tabs(
    mux: Mux,
    session_dir: Path,
    queue: asyncio.Queue[SessionEvent],
    tasks: dict[str, asyncio.Task],
    last: tuple[tuple[PaneInfo, ...], tuple[TabInfo, ...]] | None,
) -> tuple[tuple[PaneInfo, ...], tuple[TabInfo, ...]]:
    """One `list_panes`/`list_tabs` pass (plus a socket scan): pushes
    TabsChanged and returns the new snapshot only when it differs."""
    await _start_new_follows(session_dir, queue, tasks)
    panes, tabs = await aio.call(mux.list_panes), await aio.call(mux.list_tabs)
    current = (tuple(panes), tuple(tabs))
    if current != last:
        await queue.put(TabsChanged(tuple(tabs), tuple(panes)))
    return current


async def _debounced_refresh_loop(
    mux: Mux,
    session_dir: Path,
    events: AsyncIterator[ControlEvent],
    queue: asyncio.Queue[SessionEvent],
    tasks: dict[str, asyncio.Task],
    last: tuple[tuple[PaneInfo, ...], tuple[TabInfo, ...]],
) -> None:
    """Consume control-mode events; on each LAYOUT_EVENTS hit, (re)schedule
    one refresh after `_DEBOUNCE_S` -- a burst of events (a split creates
    both a layout-change and a window-add) collapses to a single refresh.

    A pending refresh outlives the loop when `events` ends on its own (only
    a finite test double does this in practice -- the real control-mode
    stream never ends short of the session dying); it is cancelled instead
    when this coroutine itself is cancelled (the real `aclose()` shutdown
    path), so `watch_session`'s "cancel every task it started" holds.
    """
    pending: asyncio.Task | None = None

    async def _refresh_after_debounce() -> None:
        nonlocal last
        await asyncio.sleep(_DEBOUNCE_S)
        last = await _refresh_tabs(mux, session_dir, queue, tasks, last)

    try:
        async for event in events:
            if event.kind not in LAYOUT_EVENTS:
                continue
            if pending is not None:
                pending.cancel()
            pending = asyncio.create_task(
                _refresh_after_debounce(), name="hive-watch-tmux-debounce"
            )
        if pending is not None:
            await pending
    except asyncio.CancelledError:
        if pending is not None:
            pending.cancel()
        raise
    finally:
        aclose = getattr(events, "aclose", None)
        if aclose is not None:
            await aclose()


async def _discover_events(
    mux: Mux,
    session_dir: Path,
    events: AsyncIterator[ControlEvent],
    poll_s: float,
    queue: asyncio.Queue[SessionEvent],
    tasks: dict[str, asyncio.Task],
) -> None:
    """tmux: no `list_panes`/`list_tabs` polling -- one refresh runs
    immediately, then only on a debounced control-mode layout event. A
    parallel, mux-call-free socket scan keeps sockets discovered promptly."""
    last = await _refresh_tabs(mux, session_dir, queue, tasks, None)
    scan_task = asyncio.create_task(
        _scan_sockets_loop(session_dir, poll_s, queue, tasks),
        name="hive-watch-tmux-scan",
    )
    try:
        await _debounced_refresh_loop(mux, session_dir, events, queue, tasks, last)
    finally:
        scan_task.cancel()
        await asyncio.gather(scan_task, return_exceptions=True)


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
    events: AsyncIterator[ControlEvent] | None = None,
) -> AsyncIterator[SessionEvent]:
    """Multiplexes discovery and `_facts_loop` through one queue; both run
    immediately, then every poll_s/facts_s. Cancelling the generator
    (aclose) cancels every task it started.

    `mux.name == "tmux"`: discovery is event-driven, not polled (see
    `_discover_events`) -- `events` defaults to the real
    `tmux_control_events(session)` and is only ever overridden by tests.
    Every other backend keeps the original poll loop (`_discover`).
    """
    session_dir = (
        session_dir if session_dir is not None else paths.session_sock_dir(session)
    )
    queue: asyncio.Queue[SessionEvent] = asyncio.Queue()
    tasks: dict[str, asyncio.Task] = {}
    if mux.name == "tmux":
        event_source = (
            events
            if events is not None
            else tmux_control_events(session, server=getattr(mux, "server", "hive"))
        )
        discover = _discover_events(
            mux, session_dir, event_source, poll_s, queue, tasks
        )
    else:
        discover = _discover(mux, session_dir, poll_s, queue, tasks)
    runner = [
        asyncio.create_task(discover, name="hive-watch-discover"),
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
