"""The session's live `agents_layout` override (G2): a small text file in
the session's runtime dir, not a socket -- `hive pane new` reads it from a
separate process, control plane running or not, and it must survive a
control-plane restart within the same session. Wiped with the rest of
`XDG_RUNTIME_DIR` on reboot/logout, which is the correct reset: a live
override is meant to last "for this session", not forever.
"""

from __future__ import annotations

from ..core import paths

AGENTS_LAYOUTS: tuple[str, ...] = ("split", "stacked", "tabs")


def read_agents_layout(session: str, *, default: str) -> str:
    """The live per-session override, or `default` when none was ever set
    or the file holds something unrecognized (forward/backward-compat: an
    older or newer `hive` sharing the same runtime dir)."""
    try:
        value = paths.agents_layout_file(session).read_text().strip()
    except OSError:
        return default
    return value if value in AGENTS_LAYOUTS else default


def write_agents_layout(session: str, mode: str) -> None:
    if mode not in AGENTS_LAYOUTS:
        raise ValueError(f"unknown agents layout: {mode!r}")
    path = paths.agents_layout_file(session)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_text(mode)
