"""XDG dirs, runtime dir, socket paths, layouts dir.

None of these create directories except ``runtime_dir()``; callers ``mkdir``.
"""

from __future__ import annotations

import os
import re
import shutil
import sys
from pathlib import Path

_SANITIZE_RE = re.compile(r"[^A-Za-z0-9._-]")


def xdg_config_home() -> Path:
    env = os.environ.get("XDG_CONFIG_HOME")
    if env:
        return Path(env)
    return Path.home() / ".config"


def xdg_state_home() -> Path:
    env = os.environ.get("XDG_STATE_HOME")
    if env:
        return Path(env)
    return Path.home() / ".local" / "state"


def runtime_dir() -> Path:
    env = os.environ.get("XDG_RUNTIME_DIR")
    if env:
        path = Path(env)
    else:
        path = Path(f"/tmp/hive-{os.getuid()}")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return path


def hive_runtime_dir() -> Path:
    return runtime_dir() / "hive"


def _sanitize(session: str) -> str:
    return _SANITIZE_RE.sub("_", session)[:32]


def _sanitize_pane_id(pane_id: str) -> str:
    """tmux pane/window ids keep their sigil ("%7", "@3"); socket file names
    can't, so swap it for a letter ("p7", "w3"). Zellij's plain-digit ids
    pass through unchanged."""
    if pane_id.startswith("%"):
        return f"p{pane_id[1:]}"
    if pane_id.startswith("@"):
        return f"w{pane_id[1:]}"
    return pane_id


def session_sock_dir(session: str) -> Path:
    return hive_runtime_dir() / _sanitize(session)


def pane_sock(session: str, pane_id: str) -> Path:
    return session_sock_dir(session) / f"{_sanitize_pane_id(pane_id)}.sock"


def control_sock(session: str) -> Path:
    return session_sock_dir(session) / "control.sock"


def agents_layout_file(session: str) -> Path:
    """Where the session's live `agents_layout` override (G2) is written --
    a small text file, not a socket, since `hive pane new` reads it from a
    separate process that may run with no control plane up at all. Unwired
    since G4 (see state/session_layout.py)."""
    return session_sock_dir(session) / "agents_layout"


def layouts_dir() -> Path:
    return xdg_state_home() / "hive" / "layouts"


def hive_executable() -> str:
    """Absolute path to this `hive` invocation, for rendering into layouts.

    A pane spawned by Zellij has no shell to resolve $PATH the way the
    process that launched `hive zellij` did, so the rendered command needs
    an absolute path. `sys.argv[0]` is normally the installed entry point;
    falls back to `shutil.which("hive")` (e.g. some test runners rewrite
    argv[0] to a non-existent path), and finally the bare name.
    """
    candidate = Path(sys.argv[0]).resolve()
    if candidate.is_file():
        return str(candidate)
    return shutil.which("hive") or "hive"
