"""Backend-neutral layout model: panes, tabs, sessions.

Frozen dataclasses so a `SessionSpec` can be built, compared, and hashed like
any other value; `mux/zellij/kdl.py` is the only place that knows how to turn
one into text.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PaneSpec:
    name: str
    command: tuple[str, ...]  # argv; () = a plain shell pane
    cwd: str | None = None
    size: str | None = None  # "30%" or "20" (cells)
    suspended: bool = False  # zellij start_suspended
    env: tuple[tuple[str, str], ...] = ()  # rendered as /usr/bin/env K=V … argv
    close_on_exit: bool = False


@dataclass(frozen=True)
class TabSpec:
    name: str
    panes: tuple[PaneSpec, ...]
    direction: str = "vertical"  # split direction of the top-level container
    focus: bool = False


@dataclass(frozen=True)
class KeybindSpec:  # filled in F3; F2 renders an empty block
    bindings: tuple[tuple[str, tuple[str, ...], dict[str, str]], ...] = ()


@dataclass(frozen=True)
class SessionSpec:
    name: str
    tabs: tuple[TabSpec, ...]
    options: tuple[tuple[str, str], ...] = (
        ("stacked_resize", "false"),
        ("auto_layout", "false"),
    )
    keybinds: KeybindSpec = KeybindSpec()
