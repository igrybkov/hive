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
    """Render one pane node; `indent` is the depth of its own opening line."""
    pad = _pad(indent)
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
        direction = kdl_string(t.direction)
        lines.append(f"{inner_pad}pane split_direction={direction} {{")
        lines.extend(render_pane(p, indent + 2) for p in t.panes)
        lines.append(f"{inner_pad}}}")
    lines.append(f"{pad}}}")
    return "\n".join(lines)


def render_tab_file(t: TabSpec) -> str:
    """`layout { tab ... }` for `zellij action new-tab --layout`."""
    lines = ["layout {", _DEFAULT_TAB_TEMPLATE, render_tab_body(t, indent=1), "}"]
    return "\n".join(lines) + "\n"


def render_session_file(s: SessionSpec, hive: str) -> str:
    """Full session file: `layout { ... }`, options, and keybinds (F3)."""
    lines = ["layout {", _DEFAULT_TAB_TEMPLATE]
    lines.extend(render_tab_body(t, indent=1) for t in s.tabs)
    lines.append("}")
    lines.extend(f"{k} {v}" for k, v in s.options)
    keybinds = render_keybinds(s.keybinds)
    if keybinds:
        lines.append(keybinds)
    return "\n".join(lines) + "\n"
