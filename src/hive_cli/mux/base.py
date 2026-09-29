"""The multiplexer-neutral surface: what hive needs from Zellij or tmux.

`Mux` is a Protocol so backends (mux/zellij/backend.py, mux/tmux/ in F6) and
the test double (tests/fakes.py:FakeMux) need no common base class. Pane and
tab ids are normalised strings ("3", never "terminal_3"; tmux keeps its "%3").
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from ..layout.model import TabSpec


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

    def resume_pane(self, pane_id: str) -> None:
        """Start a pane's pending command: send Enter, the same keystroke a
        person would press by hand. Zellij's own `start_suspended` panes
        resume on Enter/Space/carriage-return natively; the tmux backend has
        no such primitive, so its `suspended` panes always wrap the real
        command in `hive pane hold` (F6), which blocks on reading a line
        from stdin -- an injected Enter unblocks it the same way. Either
        way this is the *only* way to make a pending pane's command actually
        start without a human at the keyboard -- `focus_pane` alone just
        moves the cursor there and leaves it dormant."""

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
        stacked: bool = False,
        width: str | None = None,
        height: str | None = None,
    ) -> str | None:
        """Create a pane running argv; returns its id. tab_id: create in that
        tab; focus=False: leave focus where it is; suspended: start-suspended.
        direction: "right", "down", or "auto" -- leave placement to the
        multiplexer's own layout engine (Zellij's auto_layout swap layouts,
        which a directional split marks dirty and switches off); backends
        without one split right.
        stacked: add to the target's Zellij pane stack instead of splitting
        (G2); backends without native stacking (tmux) ignore it and split.
        """

    def new_tab(self, spec: TabSpec, *, focus: bool = True) -> str | None:
        """Create a tab from spec; returns its id."""

    def popup(
        self,
        argv: Sequence[str],
        *,
        cwd: str | None,
        name: str,
        width: str = "80%",
        height: str = "80%",
    ) -> None: ...
