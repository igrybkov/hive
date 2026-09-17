"""ControlPlaneApp (F4): the Textual control plane.

Fixture sockets live at the *real* `paths.pane_sock("test", <id>)` path (the
autouse `clean_environment` fixture points XDG_RUNTIME_DIR at short_tmp), so
`watch_session`'s default `session_dir` and `session.restart_pane`'s
resolved socket path both find them without an override.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fakes import FakeMux
from textual.widgets import DataTable

from hive_cli.core import paths
from hive_cli.git import GitSummary
from hive_cli.layout.tabs import BUNDLED
from hive_cli.mux.base import PaneInfo, TabInfo
from hive_cli.services import session as session_service
from hive_cli.state.pane_state import ICONS, PaneState
from hive_cli.state.server import PaneStateServer
from hive_cli.ui.tui.app import ControlPlaneApp
from hive_cli.ui.tui.screens import DetailScreen, HelpScreen


async def _wait_for(pilot, predicate, *, tries=40, step=0.05):
    for _ in range(tries):
        if predicate():
            return
        await pilot.pause(step)
    assert predicate()


@pytest.fixture
def servers():
    srv1 = PaneStateServer(
        paths.pane_sock("test", "3"),
        PaneState(
            pane_id="3", hive_pane_id=1, tab_id="t1", agent="claude", branch="feat"
        ),
    )
    srv2 = PaneStateServer(
        paths.pane_sock("test", "4"),
        PaneState(
            pane_id="4", hive_pane_id=2, tab_id="t1", agent="codex", branch="fix"
        ),
    )
    srv1.start()
    srv2.start()
    yield srv1, srv2
    srv1.close()
    srv2.close()


@pytest.fixture
def mux():
    panes = [
        PaneInfo("3", "t1", "", "", "", False, False, False),
        PaneInfo("4", "t1", "", "", "", False, False, False),
    ]
    tabs = [TabInfo("t1", "agents", True)]
    # pane_id="9": distinct from every agent pane id these tests use ("3",
    # "4") -- build_rows (G0) excludes the mux's own_pane_id from the board,
    # so reusing "3" here would silently drop the Anton/claude row.
    return FakeMux(session="test", pane_id="9", panes=panes, tabs=tabs)


@pytest.fixture
def session_fns():
    return SimpleNamespace(
        new_agent_pane=Mock(return_value="100"),
        open_tab=Mock(return_value="tab1"),
        floating_shell=Mock(),
        restart_pane=session_service.restart_pane,
        set_agents_layout=Mock(return_value="stacked"),
    )


@pytest.fixture
def app(mux, session_fns):
    return ControlPlaneApp(mux=mux, session="test", session_fns=session_fns)


class TestRowsRender:
    async def test_two_rows(self, servers, app):
        async with app.run_test(size=(120, 30)) as pilot:
            await _wait_for(pilot, lambda: app.query_one(DataTable).row_count == 2)
            assert app.query_one(DataTable).row_count == 2


class TestPushUpdatesCell:
    async def test_status_cell_reflects_pushed_state(self, servers, app):
        srv1, _srv2 = servers
        async with app.run_test(size=(120, 30)) as pilot:
            await _wait_for(pilot, lambda: len(app.rows) == 2)

            srv1.update(status="busy")

            await _wait_for(
                pilot,
                lambda: (
                    app.rows.get("3") is not None and app.rows["3"].status == "busy"
                ),
            )
            table = app.query_one(DataTable)
            status_key = next(k for k in app._col_keys if k.value == "status")
            assert "busy" in str(table.get_cell("3", status_key))


class TestEnterFocuses:
    async def test_enter_calls_focus_pane(self, servers, app, mux):
        async with app.run_test(size=(120, 30)) as pilot:
            await _wait_for(pilot, lambda: app.query_one(DataTable).row_count == 2)
            app.query_one(DataTable).focus()
            await pilot.pause()

            await pilot.press("enter")

            await _wait_for(pilot, lambda: bool(mux.named("focus_pane")))
            assert mux.named("focus_pane")[-1][1][0] == "3"


class TestRRestarts:
    async def test_restart_requested_is_set(self, servers, app):
        srv1, _srv2 = servers
        async with app.run_test(size=(120, 30)) as pilot:
            await _wait_for(pilot, lambda: app.query_one(DataTable).row_count == 2)
            app.query_one(DataTable).focus()

            await pilot.press("r")

            await _wait_for(pilot, lambda: srv1.restart_requested.is_set())
            assert srv1.restart_requested.is_set()


class TestXConfirmsThenCloses:
    async def test_close_pane_after_confirm(self, servers, app, mux):
        async with app.run_test(size=(120, 30)) as pilot:
            await _wait_for(pilot, lambda: app.query_one(DataTable).row_count == 2)
            app.query_one(DataTable).focus()

            await pilot.press("x")
            await pilot.pause()
            await pilot.press("y")

            await _wait_for(pilot, lambda: bool(mux.named("close_pane")))
            assert mux.named("close_pane")[-1][1][0] == "3"

    async def test_cancel_does_not_close(self, servers, app, mux):
        async with app.run_test(size=(120, 30)) as pilot:
            await _wait_for(pilot, lambda: app.query_one(DataTable).row_count == 2)
            app.query_one(DataTable).focus()

            await pilot.press("x")
            await pilot.pause()
            await pilot.press("n")
            await pilot.pause(0.2)

            assert mux.named("close_pane") == []


class TestNCallsNewAgent:
    async def test_new_agent_pane_called(self, app, session_fns):
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.press("n")
            await _wait_for(pilot, lambda: session_fns.new_agent_pane.called)
            session_fns.new_agent_pane.assert_called_once()


class TestNTargetsSelectedRow:
    """G1: 'n' must target the *selected row's* tab/pane, not Zellij's
    ambient current tab -- proved here by making the two differ: t1 is the
    mux's `current_tab_id()` (its only "active" tab), but the row selected
    with 'down' belongs to t2."""

    @pytest.fixture
    def two_tab_servers(self):
        srv1 = PaneStateServer(
            paths.pane_sock("test", "3"),
            PaneState(pane_id="3", hive_pane_id=1, tab_id="t1", agent="claude"),
        )
        srv2 = PaneStateServer(
            paths.pane_sock("test", "5"),
            PaneState(pane_id="5", hive_pane_id=2, tab_id="t2", agent="codex"),
        )
        srv1.start()
        srv2.start()
        yield srv1, srv2
        srv1.close()
        srv2.close()

    @pytest.fixture
    def two_tab_app(self, session_fns):
        panes = [
            PaneInfo("3", "t1", "", "", "", False, False, False),
            PaneInfo("5", "t2", "", "", "", False, False, False),
        ]
        tabs = [TabInfo("t1", "agents", True), TabInfo("t2", "agents2", False)]
        mux = FakeMux(session="test", pane_id="9", panes=panes, tabs=tabs)
        return ControlPlaneApp(mux=mux, session="test", session_fns=session_fns)

    async def test_selects_row_in_other_tab(
        self, two_tab_servers, two_tab_app, session_fns
    ):
        assert two_tab_app._mux.current_tab_id() == "t1"  # sanity: not t2

        async with two_tab_app.run_test(size=(120, 30)) as pilot:
            await _wait_for(
                pilot, lambda: two_tab_app.query_one(DataTable).row_count == 2
            )
            two_tab_app.query_one(DataTable).focus()
            await pilot.press("down")  # row 0 is "3" (hive_pane_id=1); row 1 is "5"

            await pilot.press("n")

            await _wait_for(pilot, lambda: session_fns.new_agent_pane.called)
            _name, _args, kwargs = session_fns.new_agent_pane.mock_calls[0]
            assert kwargs["tab_id"] == "t2"
            assert kwargs["prefer_pane_id"] == "5"

    async def test_selecting_a_tool_pane_row_falls_back_to_current_tab(
        self, session_fns
    ):
        """G0 made bare/tool-pane rows (shell, lazygit, ...) selectable;
        splitting a new agent into one of those tabs would break its fixed
        layout, so selecting one must not target its tab -- falls back to
        `current_tab_id` exactly as if nothing were selected."""
        srv = PaneStateServer(
            paths.pane_sock("test", "3"),
            PaneState(pane_id="3", hive_pane_id=1, tab_id="t1", agent="claude"),
        )
        srv.start()
        try:
            panes = [
                PaneInfo("3", "t1", "", "", "", False, False, False),
                PaneInfo("9", "t2", "lazygit", "", "", False, False, False),
            ]
            tabs = [TabInfo("t1", "agents", True), TabInfo("t2", "git", False)]
            mux = FakeMux(session="test", pane_id="99", panes=panes, tabs=tabs)
            app = ControlPlaneApp(mux=mux, session="test", session_fns=session_fns)

            async with app.run_test(size=(120, 30)) as pilot:
                await _wait_for(pilot, lambda: app.query_one(DataTable).row_count == 2)
                app.query_one(DataTable).focus()
                await pilot.press("down")  # row 0: "3" (agent); row 1: "9" (lazygit)

                await pilot.press("n")

                await _wait_for(pilot, lambda: session_fns.new_agent_pane.called)
                _name, _args, kwargs = session_fns.new_agent_pane.mock_calls[0]
                assert kwargs["tab_id"] is None
                assert kwargs["prefer_pane_id"] == "9"
        finally:
            srv.close()


class TestFilter:
    async def test_typing_narrows_rows(self, servers, app):
        async with app.run_test(size=(120, 30)) as pilot:
            await _wait_for(pilot, lambda: app.query_one(DataTable).row_count == 2)

            await pilot.press("slash")
            await pilot.pause()
            for ch in "feat":
                await pilot.press(ch)
            await pilot.press("enter")

            await _wait_for(pilot, lambda: app.query_one(DataTable).row_count == 1)
            assert app.query_one(DataTable).row_count == 1

    async def test_escape_clears_filter(self, servers, app):
        async with app.run_test(size=(120, 30)) as pilot:
            await _wait_for(pilot, lambda: app.query_one(DataTable).row_count == 2)

            await pilot.press("slash")
            await pilot.pause()
            for ch in "feat":
                await pilot.press(ch)
            await pilot.press("enter")
            await _wait_for(pilot, lambda: app.query_one(DataTable).row_count == 1)

            await pilot.press("slash")
            await pilot.pause()
            await pilot.press("escape")

            await _wait_for(pilot, lambda: app.query_one(DataTable).row_count == 2)
            assert app.query_one(DataTable).row_count == 2


class TestTabRenamedOnChange:
    async def test_rename_tab_carries_busy_icon(self, servers, app, mux):
        srv1, _srv2 = servers
        async with app.run_test(size=(120, 30)) as pilot:
            await _wait_for(pilot, lambda: app.query_one(DataTable).row_count == 2)

            count_before = len(mux.named("rename_tab"))
            srv1.update(status="busy")

            await _wait_for(pilot, lambda: len(mux.named("rename_tab")) > count_before)
            name = mux.named("rename_tab")[-1][1][1]
            assert ICONS["busy"] in name


class TestQQuits:
    async def test_quit_stops_the_app(self, app):
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.press("q")
            await _wait_for(pilot, lambda: not app.is_running)
            assert not app.is_running


class TestIdleWritesNothing:
    async def test_no_paint_without_a_change(self, servers, app):
        """HeadlessDriver (used by run_test) never writes to a terminal, so
        there is nothing to spy on at that layer; the meaningful invariant
        -- no repaint without a real change -- is exercised by spying on
        `_paint` directly, with a positive control proving the spy would
        catch a real repaint.
        """
        srv1, _srv2 = servers
        async with app.run_test(size=(120, 30)) as pilot:
            await _wait_for(pilot, lambda: app.query_one(DataTable).row_count == 2)

            paint_calls: list[None] = []
            original_paint = app._paint

            def spy() -> None:
                paint_calls.append(None)
                original_paint()

            app._paint = spy

            srv1.update(status="busy")
            await _wait_for(pilot, lambda: bool(paint_calls))
            assert paint_calls  # positive control: a real change does repaint

            paint_calls.clear()
            await pilot.pause(0.6)
            assert paint_calls == []


class TestToolTab:
    async def test_pick_opens_tab(self, app, session_fns):
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.press("T")
            await pilot.pause()
            await pilot.press("enter")
            await _wait_for(pilot, lambda: session_fns.open_tab.called)
            assert session_fns.open_tab.call_args.args[0] in BUNDLED

    async def test_escape_cancels_without_opening(self, app, session_fns):
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.press("T")
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause(0.2)
            session_fns.open_tab.assert_not_called()


class TestAgentsLayout:
    """G2: 'L' opens a mode picker and changes the live per-session
    agents_layout override."""

    async def test_pick_sets_layout(self, app, session_fns):
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.press("L")
            await pilot.pause()
            await pilot.press("enter")  # first item: AGENTS_LAYOUTS[0] == "split"
            await _wait_for(pilot, lambda: session_fns.set_agents_layout.called)
            session_fns.set_agents_layout.assert_called_once_with(
                "split", session="test"
            )

    async def test_escape_cancels_without_setting(self, app, session_fns):
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.press("L")
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause(0.2)
            session_fns.set_agents_layout.assert_not_called()


class TestFloatingShell:
    async def test_calls_floating_shell(self, servers, app, session_fns):
        async with app.run_test(size=(120, 30)) as pilot:
            await _wait_for(pilot, lambda: app.query_one(DataTable).row_count == 2)
            await pilot.press("f")
            await _wait_for(pilot, lambda: session_fns.floating_shell.called)
            session_fns.floating_shell.assert_called_once_with(
                mux=app._mux, worktree=None
            )


class TestRefreshGit:
    async def test_g_refreshes_facts_into_rows(self, servers, mux, session_fns):
        summary = GitSummary(
            branch="feat",
            upstream="",
            ahead=0,
            behind=0,
            staged=0,
            modified=0,
            untracked=0,
            conflicted=0,
            last_hash="",
            last_subject="",
            last_age="",
        )
        facts_fn = Mock(return_value={"": summary})
        app = ControlPlaneApp(
            mux=mux, session="test", session_fns=session_fns, facts_fn=facts_fn
        )
        async with app.run_test(size=(120, 30)) as pilot:
            await _wait_for(pilot, lambda: app.query_one(DataTable).row_count == 2)
            calls_before = facts_fn.call_count

            await pilot.press("g")

            await _wait_for(pilot, lambda: facts_fn.call_count > calls_before)
            assert app.rows["3"].git == "✓"


class TestHelp:
    async def test_question_mark_pushes_help_screen(self, app):
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.press("question_mark")
            await pilot.pause()
            assert isinstance(app.screen, HelpScreen)
            await pilot.press("escape")
            await pilot.pause()
            assert not isinstance(app.screen, HelpScreen)


class TestDetail:
    async def test_d_pushes_detail_screen_for_worktree(
        self, mux, session_fns, tmp_path
    ):
        srv = PaneStateServer(
            paths.pane_sock("test", "3"),
            PaneState(
                pane_id="3",
                hive_pane_id=1,
                tab_id="t1",
                agent="claude",
                branch="feat",
                worktree_path=str(tmp_path),
            ),
        )
        srv.start()
        app = ControlPlaneApp(mux=mux, session="test", session_fns=session_fns)
        try:
            async with app.run_test(size=(120, 30)) as pilot:
                await _wait_for(pilot, lambda: app.query_one(DataTable).row_count >= 1)
                app.query_one(DataTable).focus()

                await pilot.press("d")

                await _wait_for(pilot, lambda: isinstance(app.screen, DetailScreen))
                assert isinstance(app.screen, DetailScreen)
        finally:
            srv.close()

    async def test_d_is_a_noop_without_a_worktree(self, servers, app):
        async with app.run_test(size=(120, 30)) as pilot:
            await _wait_for(pilot, lambda: app.query_one(DataTable).row_count == 2)
            app.query_one(DataTable).focus()

            await pilot.press("d")
            await pilot.pause(0.2)

            assert not isinstance(app.screen, DetailScreen)
