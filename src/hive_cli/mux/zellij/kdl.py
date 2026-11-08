"""Render `layout.model` dataclasses to Zellij KDL.

Golden-tested byte-for-byte (tests/test_mux_zellij_kdl.py): 4-space indent,
LF line endings, no trailing whitespace, one trailing newline. Pane opening
tags carry only `name`, `size`, and `cwd`; everything else (`command`,
`args`, `start_suspended`, `close_on_exit`) is a body line. A pane with
`env` renders as `/usr/bin/env K=V … <command>` so Zellij needs no shell to
set the variables (see layout/tabs.py's module docstring for why that
matters for `pane_cwd` tracking).
"""

from __future__ import annotations

import textwrap

from ...layout.model import PaneSpec, SessionSpec, TabSpec
from .keybinds import render as render_keybinds

_INDENT = "    "

_DEFAULT_TAB_TEMPLATE = textwrap.indent(
    """\
default_tab_template {
    pane size=1 borderless=true {
        plugin location="tab-bar"
    }
    children
    pane size=2 borderless=true {
        plugin location="status-bar"
    }
}""",
    _INDENT,
).rstrip("\n")


# `default_tab_template`'s tab-bar and status-bar plugin panes count toward a
# swap layout's `exact_panes` (verified on Zellij 0.45.1): a preset meant for N
# agent panes must say N + 2, or it never matches and only an unconstrained
# preset ever applies. `selectable_tiled_panes_count` hides this offset.
_TEMPLATE_PANES = 2


def kdl_string(value: str) -> str:
    """Quote a KDL string literal, escaping backslashes then quotes."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _pad(indent: int) -> str:
    return _INDENT * indent


def render_pane(p: PaneSpec, indent: int = 2) -> str:
    """Render one pane node; `indent` is the depth of its own opening line.

    A pane with `children` is a nested container (no `name`, since Zellij
    pane names are for leaves): a split (`pane split_direction="..." {
    ... }`) or, when `stacked` (G2), a Zellij stack (`pane stacked=true {
    ... }`) -- `stacked` wins over `direction` when both are set. Either
    way, recurses into each child at `indent + 1`.
    """
    pad = _pad(indent)
    if p.children:
        attrs = (
            ["stacked=true"]
            if p.stacked
            else [f"split_direction={kdl_string(p.direction)}"]
        )
        if p.size:
            attrs.append(f"size={kdl_string(p.size)}")
        lines = [f"{pad}pane {' '.join(attrs)} {{"]
        lines.extend(render_pane(c, indent + 1) for c in p.children)
        lines.append(f"{pad}}}")
        return "\n".join(lines)
    inner = _pad(indent + 1)
    attrs = [f"name={kdl_string(p.name)}"]
    if p.size:
        attrs.append(f"size={kdl_string(p.size)}")
    if p.cwd:
        attrs.append(f"cwd={kdl_string(p.cwd)}")
    lines = [f"{pad}pane {' '.join(attrs)} {{"]
    if p.command:
        if p.env:
            lines.append(f'{inner}command "/usr/bin/env"')
            args = [f"{k}={v}" for k, v in p.env] + list(p.command)
        else:
            lines.append(f"{inner}command {kdl_string(p.command[0])}")
            args = list(p.command[1:])
        if args:
            lines.append(f"{inner}args {' '.join(kdl_string(a) for a in args)}")
    if p.suspended:
        lines.append(f"{inner}start_suspended true")
    if p.close_on_exit:
        lines.append(f"{inner}close_on_exit true")
    lines.append(f"{pad}}}")
    return "\n".join(lines)


def render_tab_body(t: TabSpec, indent: int = 1) -> str:
    """Render the `tab name="..." { ... }` node (no enclosing `layout {}`)."""
    pad = _pad(indent)
    attrs = [f"name={kdl_string(t.name)}"]
    if t.focus:
        attrs.append("focus=true")
    lines = [f"{pad}tab {' '.join(attrs)} {{"]
    if len(t.panes) == 1:
        lines.append(render_pane(t.panes[0], indent + 1))
    else:
        inner_pad = _pad(indent + 1)
        group_attrs = (
            "stacked=true"
            if t.stacked
            else f"split_direction={kdl_string(t.direction)}"
        )
        lines.append(f"{inner_pad}pane {group_attrs} {{")
        lines.extend(render_pane(p, indent + 2) for p in t.panes)
        lines.append(f"{inner_pad}}}")
    lines.append(f"{pad}}}")
    return "\n".join(lines)


def _stacked_preset(indent: int) -> str:
    """4+ agent panes: the whole tab as one stack, only reachable by hand."""
    return "\n".join(
        [
            f'{_pad(indent)}swap_tiled_layout name="stacked" {{',
            f"{_pad(indent + 1)}tab min_panes={4 + _TEMPLATE_PANES} {{",
            f"{_pad(indent + 2)}pane stacked=true {{",
            f"{_pad(indent + 3)}children",
            f"{_pad(indent + 2)}}}",
            f"{_pad(indent + 1)}}}",
            f"{_pad(indent)}}}",
        ]
    )


def _split_preset(indent: int) -> str:
    """2 agent panes side by side."""
    return "\n".join(
        [
            f'{_pad(indent)}swap_tiled_layout name="split" {{',
            f"{_pad(indent + 1)}tab exact_panes={2 + _TEMPLATE_PANES} {{",
            f'{_pad(indent + 2)}pane split_direction="vertical" {{',
            f"{_pad(indent + 3)}pane",
            f"{_pad(indent + 3)}pane",
            f"{_pad(indent + 2)}}}",
            f"{_pad(indent + 1)}}}",
            f"{_pad(indent)}}}",
        ]
    )


def _grid_preset(indent: int) -> str:
    """3 agent panes: 2 side by side on top, 1 full-width below.

    Zellij numbers a layout's slots breadth-first (top-left, bottom,
    top-right) and hands a new pane the last one, so the newest pane lands
    top-right. No tree shape orders the wide bottom slot last;
    `ZellijMux.new_pane` swaps the new pane down instead.
    """
    return "\n".join(
        [
            f'{_pad(indent)}swap_tiled_layout name="grid" {{',
            f"{_pad(indent + 1)}tab exact_panes={3 + _TEMPLATE_PANES} {{",
            f'{_pad(indent + 2)}pane split_direction="horizontal" {{',
            f'{_pad(indent + 3)}pane split_direction="vertical" {{',
            f"{_pad(indent + 4)}pane",
            f"{_pad(indent + 4)}pane",
            f"{_pad(indent + 3)}}}",
            f"{_pad(indent + 3)}pane",
            f"{_pad(indent + 2)}}}",
            f"{_pad(indent + 1)}}}",
            f"{_pad(indent)}}}",
        ]
    )


def _grid_stacked_preset(indent: int) -> str:
    """4+ agent panes: the grid's top row stays 2 side by side, and every
    further pane stacks in the bottom slot (pane 3 joins them there)."""
    return "\n".join(
        [
            f'{_pad(indent)}swap_tiled_layout name="grid-stacked" {{',
            f"{_pad(indent + 1)}tab min_panes={4 + _TEMPLATE_PANES} {{",
            f'{_pad(indent + 2)}pane split_direction="horizontal" {{',
            f'{_pad(indent + 3)}pane split_direction="vertical" {{',
            f"{_pad(indent + 4)}pane",
            f"{_pad(indent + 4)}pane",
            f"{_pad(indent + 3)}}}",
            f"{_pad(indent + 3)}pane stacked=true {{",
            f"{_pad(indent + 4)}children",
            f"{_pad(indent + 3)}}}",
            f"{_pad(indent + 2)}}}",
            f"{_pad(indent + 1)}}}",
            f"{_pad(indent)}}}",
        ]
    )


def _flat_agents_presets(indent: int) -> str:
    """Named `swap_tiled_layout` presets for a flat "agents" tab
    (control="none"): `split` (2 agent panes), `grid` (3), `grid-stacked`
    (4 or more: the grid with its bottom slot turned into a stack) and
    `stacked` (4 or more: the whole tab as one stack, reachable only by hand
    with Alt+[ / Alt+]).

    Zellij applies the next preset *after the current one* that fits the new
    pane count, wrapping around. That decides the order and the constraints:
    - Growing walks split -> grid -> grid-stacked, one step per added pane.
    - Shrinking from grid-stacked lands on `grid` only because `stacked`
      does not fit 3 panes. An unconstrained `stacked` right after
      `grid-stacked` would win instead and flip the whole tab to a stack.
    All of this only works for a `new-pane` without `--direction`: a
    directional split marks the tab's layout dirty and switches `auto_layout`
    off (verified on Zellij 0.45.1), which is why `new_agent_pane` passes
    direction "auto". Also part of why this beats a plain split: `zellij
    action new-pane` has no ratio flag (no width/height/percent, unlike
    floating panes), so a live split lands at whatever ratio Zellij's
    heuristic picks (the original 30/70 bug).
    """
    return "\n".join(
        [
            _split_preset(indent),
            _grid_preset(indent),
            _grid_stacked_preset(indent),
            _stacked_preset(indent),
        ]
    )


def _swap_tiled_layout(t: TabSpec, indent: int = 1) -> str | None:
    """The `swap_tiled_layout` presets for `t`, or None when none apply.

    Zellij's built-in swap layouts only back its own default layout: a
    custom `--layout` file with no swap layouts gets none, so hive supplies
    them for the tabs that need them.

    Flat agents tab (`control="none"`, no individually sized pane): the
    count-driven `split`/`grid`/`grid-stacked`/`stacked` presets
    (`_flat_agents_presets`).

    `control="right"` is the one nested shape: the agent pane nests alongside
    a fixed-size `hive` pane. `children` would flatten `hive` into an equal
    sibling, so it gets no named presets, only an unnamed `exact_panes`
    preset mirroring the nesting, which keeps the outer agent columns even
    across close+reopen. `control="bottom"` is excluded by the "none sized"
    check (its `hive` pane carries a fixed `size`, which an evenly-split
    preset would fight, zellij-org/zellij#4880) and gets no swap layouts at
    all.
    """
    if t.name != "agents":
        return None
    if not any(p.children for p in t.panes):
        if any(p.size for p in t.panes):
            return None
        return _flat_agents_presets(indent)
    nested = [p for p in t.panes if p.children]
    if (
        t.stacked
        or len(t.panes) < 2
        or len(nested) != 1
        or nested[0] is not t.panes[-1]
        or len(nested[0].children) != 2
        or nested[0].children[0].children
        or nested[0].children[1].children
        or not nested[0].children[1].size
    ):
        return None
    hive_size = nested[0].children[1].size
    assert hive_size is not None  # the `not ...size` guard above
    body = [f"{_pad(indent + 2)}pane split_direction={kdl_string(t.direction)} {{"]
    body += [f"{_pad(indent + 3)}pane" for _ in t.panes[:-1]]
    body.append(
        f"{_pad(indent + 3)}pane split_direction={kdl_string(nested[0].direction)} {{"
    )
    body.append(f"{_pad(indent + 4)}pane")
    body.append(f"{_pad(indent + 4)}pane size={kdl_string(hive_size)}")
    body.append(f"{_pad(indent + 3)}}}")
    body.append(f"{_pad(indent + 2)}}}")
    lines = [
        f"{_pad(indent)}swap_tiled_layout {{",
        f"{_pad(indent + 1)}tab exact_panes={len(t.panes) + 1} {{",
        *body,
        f"{_pad(indent + 1)}}}",
        f"{_pad(indent)}}}",
    ]
    return "\n".join(lines)


def render_tab_file(t: TabSpec) -> str:
    """`layout { tab ... }` for `zellij action new-tab --layout`."""
    lines = ["layout {", _DEFAULT_TAB_TEMPLATE]
    swap = _swap_tiled_layout(t)
    if swap:
        lines.append(swap)
    lines.append(render_tab_body(t, indent=1))
    lines.append("}")
    return "\n".join(lines) + "\n"


def render_session_file(s: SessionSpec, hive: str) -> str:
    """Full session file: `layout { ... }`, options, and keybinds (F3)."""
    lines = ["layout {", _DEFAULT_TAB_TEMPLATE]
    for t in s.tabs:
        swap = _swap_tiled_layout(t)
        if swap:
            lines.append(swap)
        lines.append(render_tab_body(t, indent=1))
    lines.append("}")
    lines.extend(f"{k} {v}" for k, v in s.options)
    keybinds = render_keybinds(s.keybinds)
    if keybinds:
        lines.append(keybinds)
    return "\n".join(lines) + "\n"
