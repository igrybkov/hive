"""XDG dirs, runtime dir, socket paths, layouts dir.

None of these create directories except ``runtime_dir()``; callers ``mkdir``.
"""

from __future__ import annotations

import os
import re
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


def session_sock_dir(session: str) -> Path:
    return hive_runtime_dir() / _sanitize(session)


def pane_sock(session: str, pane_id: str) -> Path:
    return session_sock_dir(session) / f"{pane_id}.sock"


def control_sock(session: str) -> Path:
    return session_sock_dir(session) / "control.sock"


def layouts_dir() -> Path:
    return xdg_state_home() / "hive" / "layouts"
