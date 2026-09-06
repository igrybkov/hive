"""The multiplexer-neutral surface: what hive needs from Zellij or tmux.

`Mux` is a Protocol so backends (mux/zellij/backend.py, mux/tmux/ in F6) and
the test double (tests/fakes.py:FakeMux) need no common base class. Pane and
tab ids are normalised strings ("3", never "terminal_3"; tmux keeps its "%3").
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class PaneInfo:
    id: str  # normalised: "3", never "terminal_3"
    tab_id: str
    title: str
    command: str
    cwd: str
    focused: bool
    exited: bool
    suspended: bool


@dataclass(frozen=True)
class TabInfo:
    id: str
    name: str
    active: bool


class Mux(Protocol):
    name: str

    def own_pane_id(self) -> str | None: ...
    def own_session(self) -> str | None: ...
    def session_exists(self, session: str) -> bool: ...
    def attach_argv(self, session: str, layout_path: str | None) -> list[str]: ...
    def list_panes(self) -> list[PaneInfo]: ...
    def list_tabs(self) -> list[TabInfo]: ...
    def focus_pane(self, pane_id: str) -> None: ...
    def close_pane(self, pane_id: str) -> None: ...
    def rename_pane(self, pane_id: str, title: str) -> None: ...
    def rename_tab(self, tab_id: str, name: str) -> None: ...
    def current_tab_id(self) -> str | None: ...

    def new_pane(
        self,
        argv: Sequence[str],
        *,
        cwd: str | None = None,
        tab_id: str | None = None,
        direction: str = "right",
        name: str | None = None,
        close_on_exit: bool = False,
        focus: bool = True,
        floating: bool = False,
        suspended: bool = False,
        width: str | None = None,
        height: str | None = None,
    ) -> str | None:
        """Create a pane running argv; returns its id. tab_id: create in that
        tab; focus=False: leave focus where it is; suspended: start-suspended.
        """

    def new_tab(self, spec: Any, *, focus: bool = True) -> str | None:
        """spec is a layout.model.TabSpec (F2)."""

    def popup(
        self,
        argv: Sequence[str],
        *,
        cwd: str | None,
        name: str,
        width: str = "80%",
        height: str = "80%",
    ) -> None: ...
