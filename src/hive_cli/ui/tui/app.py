"""ControlPlaneApp: the `hive status` control plane (F4).

The only place under `ui/tui` that touches the mux or a service directly --
always through `services.aio.call` so a blocking `zellij action` or socket
call never stalls the Textual event loop (`watch_session`, the one place
allowed to touch sockets/the mux itself, runs in `_pump`'s worker).

Row diffing: `rows`/`query` are reassigned (never mutated) reactive dicts;
`_paint` is the single place that turns them into `DataTable` calls, diffing
against `self._cells` so an unaffected row costs nothing. `PaneRow` does not
carry the live "now" used for its status age bucket -- `_rebucket` (a 30 s
timer) just bumps `self._now` and repaints, so idle panes still age visibly
without a genuine state change.
"""

from __future__ import annotations

import functools
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.reactive import reactive
from textual.widgets import DataTable, Footer, Header, Input

from ...git import GitSummary, get_git_status_detail, get_recent_commits
from ...layout.tabs import BUNDLED
from ...mux.base import Mux, PaneInfo, TabInfo
from ...services import aio
from ...services import session as session_service
from ...services import watch as watch_service
from ...state.pane_state import PaneState, compose_tab_name
from ...state.session_layout import AGENTS_LAYOUTS
from . import model
from .screens import ConfirmScreen, DetailScreen, HelpScreen, TabPickerScreen

HELP_TEXT = "\n".join(
    [
        "enter  Focus",
        "j/k    Move down/up",
        "n      New agent pane",
        "t      Agents tab",
        "T      Tool tab",
        "L      Agent-pane layout (split/stacked/tabs)",
        "f      Shell here",
        "x      Close pane",
        "r      Restart pane",
        "d      Detail",
        "/      Filter",
        "g      Refresh git",
        "?      Help",
        "q      Quit",
    ]
)

# (label, key) pairs: add_columns() with bare labels hands back auto column
# keys that only equal themselves (never their label text), so a later
# update_cell(row_key, "status", ...) by name would raise. Naming the keys
# ourselves keeps that call readable.
_COLUMNS = (
    ("#", "id"),
    ("pane", "pane"),
    ("agent", "agent"),
    ("worktree", "worktree"),
    ("status", "status"),
    ("git", "git"),
    ("task", "task"),
)


class ControlPlaneApp(App):
    CSS_PATH = "control_plane.tcss"
    BINDINGS = [
        ("enter", "focus_pane", "Focus"),
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
        ("n", "new_agent", "New agent"),
        ("t", "new_agents_tab", "Agents tab"),
        ("T", "tool_tab", "Tool tab"),
        ("L", "agents_layout", "Layout"),
        ("f", "floating_shell", "Shell here"),
        ("x", "close_pane", "Close"),
        ("r", "restart_pane", "Restart"),
        ("d", "detail", "Detail"),
        ("slash", "filter", "Filter"),
        ("g", "refresh_git", "Git"),
        ("question_mark", "help", "Help"),
        ("q", "quit", "Quit"),
        Binding("escape", "clear_filter", "Cancel filter", show=False),
    ]

    rows: reactive[dict[str, model.PaneRow]] = reactive(
        {}, always_update=False, init=False
    )
    query: reactive[str] = reactive("", init=False)

    def __init__(
        self,
        *,
        mux: Mux,
        session: str,
        watch: Callable = watch_service.watch_session,
        session_fns: Any = None,
        facts_fn: Callable[[], dict[str, GitSummary]] | None = None,
        tasks_fn: Callable[[list[PaneState]], dict[str, str]] | None = None,
        session_dir: Path | None = None,
        poll_s: float = 3.0,
    ) -> None:
        super().__init__()
        self._mux = mux
        self._session = session
        self._watch = watch
        self._session_fns = session_fns if session_fns is not None else session_service
        self._facts_fn = facts_fn
        self._tasks_fn = tasks_fn
        self._session_dir = session_dir
        self._poll_s = poll_s
        self._states: dict[str, PaneState] = {}
        self._panes: dict[str, PaneInfo] = {}
        self._tabs: dict[str, TabInfo] = {}
        self._facts: dict[str, GitSummary] = {}
        self._tasks: dict[str, str] = {}
        self._cells: dict[str, tuple[str, ...]] = {}
        self._last_tab_names: dict[str, str] = {}
        self._col_keys: tuple = ()
        self._now = time.time()

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield Input(placeholder="filter", id="filter")
        yield DataTable(id="panes")
        yield Footer()

    async def on_mount(self) -> None:
        table = self.query_one(DataTable)
        self._col_keys = table.add_columns(*_COLUMNS)
        table.cursor_type = "row"
        # The filter Input is display:none until "/" (action_filter) shows
        # it, but a hidden widget can still hold focus in Textual -- and a
        # focused Input eats every letter key as text, so the table (not
        # the input) must be the default focus.
        table.focus()
        self.run_worker(self._pump(), exclusive=True, name="hive-tui-pump")
        self.set_interval(30, self._rebucket)

    # -- the pump: the only place that awaits watch_session -----------------

    async def _pump(self) -> None:
        async for event in self._watch(
            self._mux,
            self._session,
            poll_s=self._poll_s,
            session_dir=self._session_dir,
            facts_fn=self._facts_fn,
        ):
            await self._reduce(event)
            self.rows = model.build_rows(
                self._states,
                self._panes,
                self._facts,
                self._tasks,
                now=self._now,
                own_pane_id=self._mux.own_pane_id(),
            )

    async def _reduce(self, event: watch_service.SessionEvent) -> None:
        if isinstance(event, watch_service.PaneAdded | watch_service.PaneStateChanged):
            self._states[event.state.pane_id] = event.state
            await self._maybe_rename_tab(event.state.tab_id)
        elif isinstance(event, watch_service.PaneRemoved):
            self._states.pop(event.pane_id, None)
        elif isinstance(event, watch_service.TabsChanged):
            self._panes = {p.id: p for p in event.panes}
            self._tabs = {t.id: t for t in event.tabs}
        elif isinstance(event, watch_service.FactsUpdated):
            self._facts = event.facts
            if self._tasks_fn is not None:
                self._tasks = self._tasks_fn(list(self._states.values()))

    async def _maybe_rename_tab(self, tab_id: str) -> None:
        if not tab_id:
            return
        siblings = [s for s in self._states.values() if s.tab_id == tab_id]
        name = compose_tab_name(siblings)
        if self._last_tab_names.get(tab_id) != name:
            self._last_tab_names[tab_id] = name
            await aio.call(self._mux.rename_tab, tab_id, name)

    # -- rendering: reassigned reactives funnel into one diffing paint ------

    def watch_rows(self, _old: object, _new: object) -> None:
        self._paint()

    def watch_query(self, _old: object, _new: object) -> None:
        self._paint()

    def _rebucket(self) -> None:
        self._now = time.time()
        self._paint()

    def _paint(self) -> None:
        table = self.query_one(DataTable)
        visible = model.filter_rows(self.rows, self.query)
        added = False
        for pane_id, row in visible.items():
            added = self._paint_row(table, pane_id, row) or added
        for pane_id in [pid for pid in self._cells if pid not in visible]:
            table.remove_row(pane_id)
            del self._cells[pane_id]
        if added:
            id_key = self._col_keys[0]
            table.sort(
                id_key, key=lambda v: int(v) if v.isdigit() and v != "0" else 999
            )

    def _paint_row(self, table: DataTable, pane_id: str, row: model.PaneRow) -> bool:
        cells = (
            str(row.hive_pane_id) if row.hive_pane_id else "—",
            model.name_cell(row),
            row.agent,
            row.worktree,
            model.status_cell(row, now=self._now),
            row.git,
            row.task,
        )
        old = self._cells.get(pane_id)
        self._cells[pane_id] = cells
        if old is None:
            table.add_row(*cells, key=pane_id)
            return True
        if old != cells:
            for key, new_value, old_value in zip(
                self._col_keys, cells, old, strict=True
            ):
                if new_value != old_value:
                    table.update_cell(pane_id, key, new_value, update_width=False)
        return False

    # -- selection ------------------------------------------------------

    def _selected_pane_id(self) -> str | None:
        table = self.query_one(DataTable)
        if table.row_count == 0:
            return None
        coordinate = table.cursor_coordinate
        return table.coordinate_to_cell_key(coordinate).row_key.value

    # -- actions --------------------------------------------------------

    async def action_focus_pane(self) -> None:
        """Only reachable when the table isn't focused (its own `enter`
        binding otherwise wins and posts RowSelected first -- see below)."""
        await self._focus_selected(self._selected_pane_id())

    def action_cursor_down(self) -> None:
        """vim-style row navigation; the DataTable has no bindings of its
        own for j/k so these bubble up from it uncontested, same as every
        other letter-key action here."""
        self.query_one(DataTable).action_cursor_down()

    def action_cursor_up(self) -> None:
        self.query_one(DataTable).action_cursor_up()

    async def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        await self._focus_selected(event.row_key.value)

    async def _focus_selected(self, pane_id: str | None) -> None:
        if pane_id is not None:
            await aio.call(self._mux.focus_pane, pane_id)

    async def action_new_agent(self) -> None:
        """Targets the selected row's tab/pane, not Zellij's ambient current
        tab -- pressing 'n' while looking at the control plane means that
        "current tab" is always the control plane's own home tab, which has
        nothing to do with whatever row is highlighted (G1). Only an agent
        row's tab is used this way: G0 made bare/tool-pane rows (shell,
        lazygit, ...) selectable too, and splitting a new agent into one of
        those tabs would break its fixed layout -- selecting one instead
        falls back to `current_tab_id` (the tab the control plane's own
        pane is physically in), same as having nothing selected at all."""
        pane_id = self._selected_pane_id()
        row = self.rows.get(pane_id) if pane_id is not None else None
        tab_id = row.tab_id if row is not None and row.hive_pane_id != 0 else None
        await aio.call(
            self._session_fns.new_agent_pane,
            mux=self._mux,
            tab_id=tab_id,
            prefer_pane_id=pane_id,
        )

    async def action_new_agents_tab(self) -> None:
        await aio.call(self._session_fns.open_tab, "agents", mux=self._mux)

    def action_tool_tab(self) -> None:
        from ...config import get_settings

        names = sorted({*BUNDLED, *get_settings().tabs})
        self.push_screen(TabPickerScreen(names), self._open_tool_tab)

    async def _open_tool_tab(self, name: str | None) -> None:
        if name:
            await aio.call(self._session_fns.open_tab, name, mux=self._mux)

    def action_agents_layout(self) -> None:
        """Picks the live agents_layout override (G2) -- affects only
        agents created from now on, never panes already open."""
        self.push_screen(TabPickerScreen(list(AGENTS_LAYOUTS)), self._set_agents_layout)

    async def _set_agents_layout(self, mode: str | None) -> None:
        if mode:
            await aio.call(
                self._session_fns.set_agents_layout, mode, session=self._session
            )

    async def action_floating_shell(self) -> None:
        worktree = self._selected_worktree()
        await aio.call(
            self._session_fns.floating_shell, mux=self._mux, worktree=worktree
        )

    def _selected_worktree(self) -> Path | None:
        pane_id = self._selected_pane_id()
        row = self.rows.get(pane_id) if pane_id is not None else None
        return Path(row.worktree) if row and row.worktree else None

    def action_close_pane(self) -> None:
        pane_id = self._selected_pane_id()
        if pane_id is None:
            return
        self.push_screen(
            ConfirmScreen(f"Close pane {pane_id}?"),
            functools.partial(self._do_close_pane, pane_id),
        )

    async def _do_close_pane(self, pane_id: str, confirmed: bool | None) -> None:
        if confirmed:
            await aio.call(self._mux.close_pane, pane_id)

    async def action_restart_pane(self) -> None:
        pane_id = self._selected_pane_id()
        if pane_id is not None:
            await aio.call(
                self._session_fns.restart_pane, pane_id, session=self._session
            )

    def action_detail(self) -> None:
        pane_id = self._selected_pane_id()
        row = self.rows.get(pane_id) if pane_id is not None else None
        if row is None or not row.worktree:
            return
        self.push_screen(DetailScreen(row, functools.partial(self._load_detail, row)))

    def _load_detail(self, row: model.PaneRow) -> str:
        path = Path(row.worktree)
        status = get_git_status_detail(path)
        commits = get_recent_commits(path)
        lines = [f"Pane c{row.hive_pane_id}  [{row.branch}]  {path}", ""]
        lines.append("Git status:")
        for name, files in (
            ("staged", status.staged),
            ("modified", status.unstaged),
            ("untracked", status.untracked),
        ):
            if files:
                lines.append(f"  {name}: {', '.join(files)}")
        if not (status.staged or status.unstaged or status.untracked):
            lines.append("  clean")
        lines.append("")
        lines.append("Recent commits:")
        if commits:
            lines.extend(f"  {c.hash} {c.message} ({c.date})" for c in commits)
        else:
            lines.append("  none")
        return "\n".join(lines)

    def action_filter(self) -> None:
        field = self.query_one("#filter", Input)
        field.display = True
        field.focus()

    def action_clear_filter(self) -> None:
        field = self.query_one("#filter", Input)
        if not field.display:
            return
        field.value = ""
        field.display = False
        self.query = ""
        self.query_one(DataTable).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        """Narrows rows live, as each character is typed, rather than
        waiting for submit -- "type to find" only feels that way if the
        table visibly reacts while the filter box is still open."""
        self.query = event.value

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.query = event.value
        field = self.query_one("#filter", Input)
        field.display = False
        self.query_one(DataTable).focus()

    async def action_refresh_git(self) -> None:
        if self._facts_fn is None:
            return
        self._facts = await aio.call(self._facts_fn)
        self.rows = model.build_rows(
            self._states,
            self._panes,
            self._facts,
            self._tasks,
            now=self._now,
            own_pane_id=self._mux.own_pane_id(),
        )

    def action_help(self) -> None:
        self.push_screen(HelpScreen(HELP_TEXT))
