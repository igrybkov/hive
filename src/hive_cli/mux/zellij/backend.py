"""Zellij terminal multiplexer integration: pane titles via `zellij action`.

Moved from utils/zellij.py (A0 step 9). Title composition (`compose_title`)
and state persistence (`read_state`/`write_state`) split out to
`state/pane_state.py` and `state/legacy_files.py` -- this module owns the
Zellij-specific I/O: the `is_running_in_zellij()` gate, runtime-settings
lookups, and the `zellij action rename-pane` calls.
"""

from __future__ import annotations

from pathlib import Path

from ...config import get_runtime_settings
from ...core import proc
from ...state import legacy_files, pane_state


def is_running_in_zellij() -> bool:
    """Check if we're running inside a Zellij session."""
    return get_runtime_settings().in_zellij


def rename_pane(name: str) -> None:
    """Rename the current Zellij pane.

    Args:
        name: New name for the pane (always the full desired title).

    Note:
        This is a no-op if not running inside Zellij.
        Since Zellij 0.44.1, rename-pane replaces the entire pane title
        (including layout-defined names), so callers must pass the full name.

        `zellij action rename-pane` defaults to the *focused* pane, which may
        not be the pane this process runs in. We pass `--pane-id` explicitly
        from $ZELLIJ_PANE_ID so the rename always targets our own pane.
    """
    if not is_running_in_zellij():
        return

    proc.run(
        [
            "zellij",
            "action",
            "rename-pane",
            "--pane-id",
            get_runtime_settings().zellij_pane_id,
            name,
        ],
    )


def append_to_pane_title(value: str) -> bool:
    """Append value to current Zellij pane title.

    Trims whitespace from value and prepends a single space.

    Args:
        value: Value to append to the pane title.

    Returns:
        True if running in Zellij and title was updated, False otherwise.
    """
    if not is_running_in_zellij():
        return False

    value = value.strip()
    if not value:
        return False

    proc.run(
        [
            "zellij",
            "action",
            "rename-pane",
            "--pane-id",
            get_runtime_settings().zellij_pane_id,
            f" {value}",
        ],
    )
    return True


def rebuild_pane_title() -> bool:
    """Rebuild and set pane title from stored state.

    Returns:
        True if title was updated, False if not in Zellij.
    """
    if not is_running_in_zellij():
        return False

    rt = get_runtime_settings()
    session = rt.zellij_session_name
    zellij_pane_id = rt.zellij_pane_id
    state = legacy_files.read_state(session, zellij_pane_id)

    title = pane_state.compose_title(
        hive_pane_id=rt.pane_id_int,
        label=rt.pane_label or "",
        agent=rt.agent or "",
        mux_pane_id=zellij_pane_id,
        status_text=state.get("status") or "",
        branch=state.get("branch") or "",
        custom_title=state.get("custom_title") or "",
        cwd=Path.cwd(),
    )
    rename_pane(title)
    return True


def set_pane_status(status: str | None) -> bool:
    """Set agent status and rebuild title.

    Args:
        status: Status string (e.g., "[working]", "[idle]"), or None to clear.

    Returns:
        True if title was updated, False if not in Zellij.
    """
    if not is_running_in_zellij():
        return False
    rt = get_runtime_settings()
    session = rt.zellij_session_name
    zellij_pane_id = rt.zellij_pane_id
    state = legacy_files.read_state(session, zellij_pane_id)
    state["status"] = status.strip() if status else None
    legacy_files.write_state(session, zellij_pane_id, state)
    return rebuild_pane_title()


def set_pane_branch(branch: str | None) -> bool:
    """Set branch and rebuild title.

    Args:
        branch: Branch name, or None to clear.

    Returns:
        True if title was updated, False if not in Zellij.
    """
    if not is_running_in_zellij():
        return False
    rt = get_runtime_settings()
    session = rt.zellij_session_name
    zellij_pane_id = rt.zellij_pane_id
    state = legacy_files.read_state(session, zellij_pane_id)
    state["branch"] = branch.strip() if branch else None
    legacy_files.write_state(session, zellij_pane_id, state)
    return rebuild_pane_title()


def set_pane_custom_title(title: str | None) -> bool:
    """Set custom title suffix and rebuild title.

    Args:
        title: Custom title suffix, or None to clear.

    Returns:
        True if title was updated, False if not in Zellij.
    """
    if not is_running_in_zellij():
        return False
    rt = get_runtime_settings()
    session = rt.zellij_session_name
    zellij_pane_id = rt.zellij_pane_id
    state = legacy_files.read_state(session, zellij_pane_id)
    state["custom_title"] = title.strip() if title else None
    legacy_files.write_state(session, zellij_pane_id, state)
    return rebuild_pane_title()
