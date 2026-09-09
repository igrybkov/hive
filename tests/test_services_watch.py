"""services/watch.py:watch_session -- multiplexes pane sockets, the mux poll,
and the facts refresher into one async generator of SessionEvent.
"""

from __future__ import annotations

import asyncio

import pytest
from fakes import FakeMux

from hive_cli.mux.base import PaneInfo, TabInfo
from hive_cli.services.watch import (
    FactsUpdated,
    PaneAdded,
    PaneRemoved,
    PaneStateChanged,
    TabsChanged,
    watch_session,
)
from hive_cli.state.pane_state import PaneState
from hive_cli.state.server import PaneStateServer


async def _collect_until(gen, predicate, timeout=2.0):
    events = []

    async def _run():
        async for ev in gen:
            events.append(ev)
            if predicate(events):
                return

    await asyncio.wait_for(_run(), timeout)
    return events


@pytest.fixture
def servers(short_tmp):
    srv1 = PaneStateServer(short_tmp / "3.sock", PaneState(pane_id="3", hive_pane_id=1))
    srv2 = PaneStateServer(short_tmp / "4.sock", PaneState(pane_id="4", hive_pane_id=2))
    srv1.start()
    srv2.start()
    yield srv1, srv2
    srv1.close()
    srv2.close()


@pytest.fixture
def mux():
    panes = [PaneInfo("3", "t1", "", "", "", False, False, False)]
    tabs = [TabInfo("t1", "agents", True)]
    return FakeMux(panes=panes, tabs=tabs)


class TestInitialEvents:
    async def test_two_pane_added_and_one_tabs_changed(self, servers, mux, short_tmp):
        gen = watch_session(mux, "test", poll_s=10, session_dir=short_tmp)

        def done(events):
            kinds = [type(e) for e in events]
            return kinds.count(PaneAdded) >= 2 and TabsChanged in kinds

        events = await _collect_until(gen, done)
        await gen.aclose()

        assert sum(isinstance(e, PaneAdded) for e in events) == 2
        assert any(isinstance(e, TabsChanged) for e in events)


class TestStateChangeIsPushed:
    async def test_pushed_without_extra_polling(self, servers, mux, short_tmp):
        srv1, _srv2 = servers
        gen = watch_session(mux, "test", poll_s=10, session_dir=short_tmp)

        def got_two_added(events):
            return sum(isinstance(e, PaneAdded) for e in events) >= 2

        await _collect_until(gen, got_two_added)
        calls_before = len(mux.named("list_panes"))

        srv1.update(status="busy")

        def got_busy(events):
            return any(
                isinstance(e, PaneStateChanged) and e.state.status == "busy"
                for e in events
            )

        events = await _collect_until(gen, got_busy, timeout=1.0)
        await gen.aclose()

        assert any(
            isinstance(e, PaneStateChanged) and e.state.status == "busy" for e in events
        )
        assert len(mux.named("list_panes")) == calls_before


class TestServerCloseEmitsRemoved:
    async def test_close_emits_pane_removed(self, servers, mux, short_tmp):
        srv1, _srv2 = servers
        gen = watch_session(mux, "test", poll_s=10, session_dir=short_tmp)

        def got_two_added(events):
            return sum(isinstance(e, PaneAdded) for e in events) >= 2

        await _collect_until(gen, got_two_added)

        srv1.close()

        def got_removed(events):
            return any(isinstance(e, PaneRemoved) and e.pane_id == "3" for e in events)

        events = await _collect_until(gen, got_removed, timeout=2.0)
        await gen.aclose()

        assert any(isinstance(e, PaneRemoved) and e.pane_id == "3" for e in events)


class TestNewSocketIsDiscovered:
    async def test_third_server_is_discovered(self, servers, mux, short_tmp):
        gen = watch_session(mux, "test", poll_s=0.1, session_dir=short_tmp)

        def got_two_added(events):
            return sum(isinstance(e, PaneAdded) for e in events) >= 2

        await _collect_until(gen, got_two_added)

        srv3 = PaneStateServer(
            short_tmp / "5.sock", PaneState(pane_id="5", hive_pane_id=3)
        )
        srv3.start()
        try:

            def got_pane_5(events):
                return any(
                    isinstance(e, PaneAdded) and e.state.pane_id == "5" for e in events
                )

            events = await _collect_until(gen, got_pane_5, timeout=2.0)
            await gen.aclose()

            assert any(
                isinstance(e, PaneAdded) and e.state.pane_id == "5" for e in events
            )
        finally:
            srv3.close()


class TestAcloseCancelsTasks:
    async def test_no_watch_tasks_survive(self, servers, mux, short_tmp):
        gen = watch_session(mux, "test", poll_s=10, session_dir=short_tmp)

        def got_two_added(events):
            return sum(isinstance(e, PaneAdded) for e in events) >= 2

        await _collect_until(gen, got_two_added)
        await gen.aclose()
        await asyncio.sleep(0)

        leftover = [
            t
            for t in asyncio.all_tasks()
            if not t.done() and (t.get_name() or "").startswith("hive-watch-")
        ]
        assert leftover == []


class TestFactsLoopEmits:
    async def test_facts_updated_from_facts_fn(self, mux, short_tmp):
        calls = {"n": 0}

        def facts_fn():
            calls["n"] += 1
            return {"/wt": "summary"}

        gen = watch_session(
            mux,
            "test",
            poll_s=10,
            facts_s=0.1,
            session_dir=short_tmp,
            facts_fn=facts_fn,
        )

        def got_facts(events):
            return any(isinstance(e, FactsUpdated) for e in events)

        events = await _collect_until(gen, got_facts, timeout=1.0)
        await gen.aclose()

        updates = [e for e in events if isinstance(e, FactsUpdated)]
        assert updates and updates[0].facts == {"/wt": "summary"}


class TestNoFactsFnIsNoop:
    async def test_no_facts_events_without_facts_fn(self, servers, mux, short_tmp):
        gen = watch_session(mux, "test", poll_s=0.1, facts_s=0.1, session_dir=short_tmp)

        def got_two_added(events):
            return sum(isinstance(e, PaneAdded) for e in events) >= 2

        events = await _collect_until(gen, got_two_added, timeout=1.0)
        await gen.aclose()

        assert not any(isinstance(e, FactsUpdated) for e in events)
