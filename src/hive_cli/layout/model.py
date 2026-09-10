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
    # A non-empty `children` makes this a *container*, not a leaf: `name`,
    # `command`, `cwd`, `suspended`, `env` and `close_on_exit` are ignored,
    # and `direction` says how its children split from each other (`size`
    # still applies -- it's how much of *this spec's own* parent container
    # it takes). Used by agents_tab's control="right" to nest the "hive"
    # status pane under the last agent pane instead of beside it.
    children: tuple[PaneSpec, ...] = ()
    direction: str = "vertical"


@dataclass(frozen=True)
class TabSpec:
    name: str
    panes: tuple[PaneSpec, ...]
    direction: str = "vertical"  # split direction of the top-level container
    focus: bool = False


@dataclass(frozen=True)
class KeybindSpec:
    """One binding per (key, Run argv, Run-block options); empty = no block.

    Option values are bool (rendered bare: ``close_on_exit true``) or str
    (rendered quoted: ``name "shell"``).
    """

    bindings: tuple[tuple[str, tuple[str, ...], dict[str, str | bool]], ...] = ()


@dataclass(frozen=True)
class SessionSpec:
    name: str
    tabs: tuple[TabSpec, ...]
    options: tuple[tuple[str, str], ...] = (
        ("stacked_resize", "false"),
        ("auto_layout", "false"),
    )
    keybinds: KeybindSpec = KeybindSpec()
