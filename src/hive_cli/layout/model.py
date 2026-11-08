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
    # Only meaningful alongside `children`: renders a Zellij stack
    # (`pane stacked=true { ... }`) instead of a `split_direction` container.
    # Takes precedence over `direction` when both are set (G2).
    stacked: bool = False


@dataclass(frozen=True)
class TabSpec:
    name: str
    panes: tuple[PaneSpec, ...]
    direction: str = "vertical"  # split direction of the top-level container
    # Stack the top-level pane group instead of splitting it (G2); ignored
    # when there's only one pane (nothing to stack).
    stacked: bool = False
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
    # auto_layout true (G3): Zellij applies the tab's swap layout when a pane
    # is added -- the same re-tile Alt+[/Alt+] does manually. A directional
    # `new-pane` marks the layout dirty and disables it. F2 turned this off
    # because the bundled agent-16.kdl's hand-maintained swap_tiled_layout only
    # matched one exact pane count. hive's flat agents tab now defines
    # count-driven named presets (mux/zellij/kdl.py `_flat_agents_presets`);
    # the preset blocks are layout-scoped, so other tabs in the same session
    # file see them too.
    # stacked_pane_list false (G4) works around Zellij 0.45's stacked-pane
    # list rendering bugs (#4656, #4370, #3110, #3675); harmless when
    # nothing in the session is stacked.
    options: tuple[tuple[str, str], ...] = (
        ("stacked_resize", "false"),
        ("auto_layout", "true"),
        ("stacked_pane_list", "false"),
    )
    keybinds: KeybindSpec = KeybindSpec()
