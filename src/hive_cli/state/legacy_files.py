"""Legacy per-pane title-state JSON files.

Moved from utils/zellij.py's `_get_state_file`/`_read_state`/`_write_state`
(A0 step 9). Stdlib only: the `is_running_in_zellij()` gate and the
session/pane-id lookup from runtime settings stay in the caller
(`mux/zellij/backend.py`), since `state` may only depend on `core`/`state`
per tests/test_architecture.py's STDLIB_ONLY rule.

State files are stored at /tmp/hive-zellij/{session}/{pane_id}.json.
F0 replaces this file-based store; kept as-is for now.
"""

from __future__ import annotations

import json
from pathlib import Path

PaneState = dict[str, str | None]

_STATE_ROOT = Path("/tmp/hive-zellij")


def state_path(session: str, pane_id: str) -> Path:
    """Path to the pane's title-state file, creating its parent directory."""
    state_dir = _STATE_ROOT / session
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir / f"{pane_id}.json"


def read_state(session: str, pane_id: str) -> PaneState:
    """Read pane title state from file, defaulting to empty state."""
    path = state_path(session, pane_id)
    if path.exists():
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {"status": None, "branch": None, "custom_title": None}


def write_state(session: str, pane_id: str, state: PaneState) -> None:
    """Write pane title state to file."""
    state_path(session, pane_id).write_text(json.dumps(state))
