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


def _swap_tiled_layout(t: TabSpec, indent: int = 1) -> str | None:
    """A `swap_tiled_layout` preset for `t`, or None when one doesn't apply.

    Zellij re-applies a swap layout automatically whenever a pane opens or
    closes and the *current* arrangement no longer satisfies it but this one
    now does (`exact_panes=N`) -- not just at tab-creation time. That's the
    only native mechanism that keeps a tab evenly split as panes come and
    go: `zellij action new-pane` has no ratio flag of its own (confirmed
    against Zellij's own `NewTiledPane`/`NewPane` action definitions -- no
    width/height/percent field, unlike floating panes), so closing one of
    two agent panes and splitting a new one back in would otherwise land at
    whatever ratio Zellij's internal heuristic picks, same as the original
    30/70 bug this whole approach exists to avoid. This re-triggers on every
    such close+reopen, for the life of the tab, with no hive code involved
    at request time.

    Two shapes from `agents_tab` are recognised. Flat (`control="none"`):
    every top-level pane a leaf, none individually sized -- `control=
    "bottom"` is *also* flat (`hive` prepended as a plain sibling) but is
    excluded by the "none sized" check, since its `hive` pane carries a
    fixed `size="25%"` an evenly-split preset would fight every time it
    re-triggered. Nested (`control="right"`): every pane a leaf except the
    last, which nests the last agent pane alongside a fixed-size `hive`
    pane -- the preset mirrors that nesting exactly, hive's own size
    untouched, and leaves only the *outer* columns (the flat agents and
    this one nested column) to Zellij's even split; the inner agent/hive
    split needs no preset since hive's fixed size already determines it.
    A Zellij pane stack has no meaningful "ratio" to preserve and renders
    without one either way.
    """
    if t.name != "agents" or t.stacked or len(t.panes) < 2:
        return None
    nested = [p for p in t.panes if p.children]
    if not nested:
        if any(p.size for p in t.panes):
            return None
        body = [f"{_pad(indent + 2)}pane split_direction={kdl_string(t.direction)} {{"]
        body += [f"{_pad(indent + 3)}pane" for _ in t.panes]
        body.append(f"{_pad(indent + 2)}}}")
        total = len(t.panes)
    elif (
        len(nested) == 1
        and nested[0] is t.panes[-1]
        and len(nested[0].children) == 2
        and not nested[0].children[0].children
        and not nested[0].children[1].children
        and nested[0].children[1].size
    ):
        hive_size = nested[0].children[1].size
        assert hive_size is not None  # the `and nested[0].children[1].size` check above
        body = [f"{_pad(indent + 2)}pane split_direction={kdl_string(t.direction)} {{"]
        body += [f"{_pad(indent + 3)}pane" for _ in t.panes[:-1]]
        body.append(
            f"{_pad(indent + 3)}pane split_direction="
            f"{kdl_string(nested[0].direction)} {{"
        )
        body.append(f"{_pad(indent + 4)}pane")
        body.append(f"{_pad(indent + 4)}pane size={kdl_string(hive_size)}")
        body.append(f"{_pad(indent + 3)}}}")
        body.append(f"{_pad(indent + 2)}}}")
        total = len(t.panes) + 1
    else:
        return None
    pad = _pad(indent)
    inner = _pad(indent + 1)
    lines = [
        f"{pad}swap_tiled_layout {{",
        f"{inner}tab exact_panes={total} {{",
        *body,
        f"{inner}}}",
        f"{pad}}}",
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
