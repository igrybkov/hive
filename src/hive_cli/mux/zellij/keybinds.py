"""Render `layout.model.KeybindSpec` to a Zellij `keybinds { shared_except ... }` block.

Golden-tested byte-for-byte (tests/test_mux_zellij_keybinds.py). Wrapped in
`shared_except "locked"` so the bindings still apply while a pane is
locked-mode; never emits `clear-defaults` (zellij#4256: that would drop the
user's own Alt+n/Alt+f bindings for the life of the session).

`_quote` mirrors `mux/zellij/kdl.py:kdl_string` (kept local, not imported, to
avoid a `kdl -> keybinds -> kdl` cycle now that `kdl.py` calls `render` here).
"""

from __future__ import annotations

from ...layout.model import KeybindSpec

_INDENT = "    "


def _quote(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _render_value(value: str | bool) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return _quote(value)


def render(spec: KeybindSpec) -> str:
    """The full `keybinds { ... }` block, or "" when `spec.bindings` is empty."""
    if not spec.bindings:
        return ""
    lines = ["keybinds {", f'{_INDENT}shared_except "locked" {{']
    for key, argv, opts in spec.bindings:
        run_args = " ".join(_quote(a) for a in argv)
        lines.append(f"{_INDENT * 2}bind {_quote(key)} {{")
        lines.append(f"{_INDENT * 3}Run {run_args} {{")
        lines.extend(
            f"{_INDENT * 4}{opt} {_render_value(value)}" for opt, value in opts.items()
        )
        lines.append(f"{_INDENT * 3}}}")
        lines.append(f"{_INDENT * 2}}}")
    lines.append(f"{_INDENT}}}")
    lines.append("}")
    return "\n".join(lines)
