"""Zellij terminal multiplexer backend: `ZellijMux` (every `zellij action`
hive issues) plus the module-level pane-title helpers `hive zellij
set-status`/`set-title` and the run loop use.

The set_pane_* helpers write through the pane socket when a `hive run`
serves this pane and fall back to composing the title from the environment
(see `_set`); there are no state files any more.

Every ZellijMux call goes through `proc.run(argv, timeout=2)` and ignores
failures (returns None/[]): a dead multiplexer must never crash hive. Argv
shapes were verified against `zellij action <sub> --help` on 0.45.1; notably
`new-pane` has `--tab-id` and `--no-focus` there, so creating a pane in
another tab needs no `go-to-tab-by-id` detour.
"""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from ...config import get_runtime_settings
from ...core import proc
from ...state import client
from ...state.pane_state import PaneState, title_for
from ..base import PaneInfo, TabInfo


def _pane_id(raw: str) -> str:
    """Normalise "terminal_3" / "plugin_1" / " 3\\n" to "3"."""
    raw = raw.strip()
    for prefix in ("terminal_", "plugin_"):
        if raw.startswith(prefix):
            return raw[len(prefix) :]
    return raw


def _run(argv: list[str]) -> proc.Result | None:
    """Run a zellij command; None on any failure."""
    result = proc.run(argv, timeout=2)
    return result if result.ok else None


def _json(result: proc.Result | None) -> Any:
    if result is None:
        return None
    try:
        return json.loads(result.stdout)
    except ValueError:
        return None


def _pane_info(raw: dict) -> PaneInfo:
    tab_id = raw.get("tab_id")
    return PaneInfo(
        id=_pane_id(str(raw.get("id", ""))),
        tab_id="" if tab_id is None else str(tab_id),
        title=str(raw.get("title") or ""),
        command=str(raw.get("pane_command") or raw.get("terminal_command") or ""),
        cwd=str(raw.get("pane_cwd") or ""),
        focused=bool(raw.get("is_focused")),
        exited=bool(raw.get("exited")),
        suspended=bool(raw.get("is_held")),
    )


def _tab_info(raw: dict) -> TabInfo:
    tab_id = raw.get("tab_id")
    return TabInfo(
        id="" if tab_id is None else str(tab_id),
        name=str(raw.get("name") or ""),
        active=bool(raw.get("active")),
    )


def _new_pane_options(
    *,
    cwd: str | None,
    tab_id: str | None,
    direction: str,
    name: str | None,
    close_on_exit: bool,
    focus: bool,
    floating: bool,
    suspended: bool,
    width: str | None,
    height: str | None,
) -> list[str]:
    opts: list[str] = ["--floating"] if floating else []
    if not floating and direction:
        opts += ["--direction", direction]
    if cwd:
        opts += ["--cwd", cwd]
    if name:
        opts += ["--name", name]
    if close_on_exit:
        opts.append("--close-on-exit")
    if suspended:
        opts.append("--start-suspended")
    if width:
        opts += ["--width", width]
    if height:
        opts += ["--height", height]
    if tab_id is not None:
        opts += ["--tab-id", tab_id]
    if not focus:
        opts.append("--no-focus")
    return opts


class ZellijMux:
    """The `Mux` protocol over the `zellij` CLI (see mux/base.py)."""

    name = "zellij"

    def own_pane_id(self) -> str | None:
        raw = os.environ.get("ZELLIJ_PANE_ID")
        return _pane_id(raw) if raw else None

    def own_session(self) -> str | None:
        return os.environ.get("ZELLIJ_SESSION_NAME") or None

    def session_exists(self, session: str) -> bool:
        result = _run(["zellij", "list-sessions", "--short"])
        return result is not None and session in result.stdout.splitlines()

    def attach_argv(self, session: str, layout_path: str | None) -> list[str]:
        argv = ["zellij"]
        if layout_path:
            argv += ["--layout", layout_path]
        return [*argv, "attach", "--create", session]

    def list_panes(self) -> list[PaneInfo]:
        data = _json(_run(["zellij", "action", "list-panes", "--all", "--json"]))
        if not isinstance(data, list):
            return []
        panes = [p for p in data if isinstance(p, dict) and not p.get("is_plugin")]
        return [_pane_info(p) for p in panes]

    def list_tabs(self) -> list[TabInfo]:
        data = _json(_run(["zellij", "action", "list-tabs", "--json"]))
        if not isinstance(data, list):
            return []
        return [_tab_info(t) for t in data if isinstance(t, dict)]

    def focus_pane(self, pane_id: str) -> None:
        _run(["zellij", "action", "focus-pane-id", pane_id])

    def close_pane(self, pane_id: str) -> None:
        _run(["zellij", "action", "close-pane", "--pane-id", pane_id])

    def rename_pane(self, pane_id: str, title: str) -> None:
        _run(["zellij", "action", "rename-pane", "--pane-id", pane_id, title])

    def rename_tab(self, tab_id: str, name: str) -> None:
        _run(["zellij", "action", "rename-tab", "--tab-id", tab_id, name])

    def current_tab_id(self) -> str | None:
        data = _json(_run(["zellij", "action", "current-tab-info", "--json"]))
        if isinstance(data, dict) and data.get("tab_id") is not None:
            return str(data["tab_id"])
        return next((p.tab_id for p in self.list_panes() if p.focused), None)

    def new_pane(
        self,
        argv: Sequence[str],
        *,
        cwd: str | None = None,
        tab_id: str | None = None,
        direction: str = "right",
        name: str | None = None,
        close_on_exit: bool = False,
        focus: bool = True,
        floating: bool = False,
        suspended: bool = False,
        width: str | None = None,
        height: str | None = None,
    ) -> str | None:
        """Create a pane running argv; returns its normalised id or None."""
        opts = _new_pane_options(
            cwd=cwd,
            tab_id=tab_id,
            direction=direction,
            name=name,
            close_on_exit=close_on_exit,
            focus=focus,
            floating=floating,
            suspended=suspended,
            width=width,
            height=height,
        )
        result = _run(["zellij", "action", "new-pane", *opts, "--", *argv])
        if result is None:
            return None
        return _pane_id(result.stdout) or None

    def new_tab(self, spec: Any, *, focus: bool = True) -> str | None:
        raise NotImplementedError("F2")

    def popup(
        self,
        argv: Sequence[str],
        *,
        cwd: str | None,
        name: str,
        width: str = "80%",
        height: str = "80%",
    ) -> None:
        cmd = ["zellij", "action", "new-pane", "--floating", "--close-on-exit"]
        cmd += ["--name", name]
        if cwd:
            cmd += ["--cwd", cwd]
        _run([*cmd, "--width", width, "--height", height, "--", *argv])


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
    ZellijMux().rename_pane(get_runtime_settings().zellij_pane_id, name)


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

    ZellijMux().rename_pane(get_runtime_settings().zellij_pane_id, f" {value}")
    return True


def _set(**fields: object) -> bool:
    """Apply title fields to this pane's state.

    When a `hive run` serves this pane (HIVE_PANE_SOCK, or the socket derived
    from the Zellij pane identity), the fields go through its socket and the
    server renames the pane. Otherwise (e.g. `hive zellij set-status` from a
    plain shell pane) the title is composed from the environment and the
    pane renamed directly.

    Returns:
        True if running in Zellij, False otherwise.
    """
    rt = get_runtime_settings()
    if not rt.in_zellij:
        return False
    if rt.pane_sock and client.set_fields(Path(rt.pane_sock), **fields):
        return True
    state = PaneState(
        hive_pane_id=rt.pane_id_int,
        label=rt.pane_label or "",
        agent=rt.agent or "",
        pane_id=rt.zellij_pane_id or "",
        **fields,
    )
    rename_pane(title_for(state))
    return True


def rebuild_pane_title() -> bool:
    """Rebuild and set the pane title from the current state.

    Returns:
        True if title was updated, False if not in Zellij.
    """
    return _set()


def set_pane_status(status: str | None) -> bool:
    """Set agent status and rebuild title.

    Args:
        status: Status string (e.g., "[working]", "[idle]"), or None to clear.

    Returns:
        True if title was updated, False if not in Zellij.
    """
    return _set(status_text=(status or "").strip())


def set_pane_branch(branch: str | None) -> bool:
    """Set branch and rebuild title.

    Args:
        branch: Branch name, or None to clear.

    Returns:
        True if title was updated, False if not in Zellij.
    """
    return _set(branch=(branch or "").strip())


def set_pane_custom_title(title: str | None) -> bool:
    """Set custom title suffix and rebuild title.

    Args:
        title: Custom title suffix, or None to clear.

    Returns:
        True if title was updated, False if not in Zellij.
    """
    return _set(custom_title=(title or "").strip())
