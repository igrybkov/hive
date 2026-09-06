"""Zellij session naming and the attach/restart loop.

Moved from commands/zellij.py (A0 step 9, alongside the complexipy fix that
pass required). `subprocess` stays here (not `core.proc.run`, added to
SUBPROCESS_OK): the restart loop inherits the tty so zellij's own UI renders
directly in the terminal, and the non-restart path hands off to zellij
entirely via `execvpe` -- there is no captured output to return, matching
`services/pane.py`'s and `mux/zellij/backend.py`'s rationale.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from collections.abc import Callable

from ..core import paths
from ..layout.resolve import resolve_layout
from ..mux.base import Mux


def session_name(template: str, *, repo: str, agent: str) -> str:
    """Build the full Zellij session name from the configured template.

    Supports {repo} and {agent} placeholders.
    """
    return template.format(repo=repo, agent=agent)


def attach_argv(layout: str | None, full_session_name: str) -> list[str]:
    """Build the `zellij [--layout ...] attach --create <session>` argv.

    Adds --layout if configured (bundled name -> packaged path, path/`.kdl`
    -> expanded, otherwise passed through for zellij to resolve itself).
    """
    cmd = ["zellij"]
    resolved_layout = resolve_layout(layout)
    if resolved_layout:
        cmd.extend(["--layout", resolved_layout])
    cmd.extend(["attach", "--create", full_session_name])
    return cmd


def clean_stale_sock_dir(mux: Mux | None, session: str) -> None:
    """Remove the session's pane-socket dir when no such session is running.

    Sockets of a session that died with its `hive run`s (machine reboot,
    `zellij kill-session`) would otherwise linger; a live session keeps its
    dir since its panes are serving.
    """
    if mux is not None and not mux.session_exists(session):
        shutil.rmtree(paths.session_sock_dir(session), ignore_errors=True)


def start(
    cmd: list[str],
    env: dict[str, str],
    *,
    session: str,
    mux: Mux | None,
    restart: bool,
    restart_delay: float,
    on_restart: Callable[[], None],
    on_stop: Callable[[], None],
) -> None:
    """Launch zellij: hand off the process, or loop restarting it on exit.

    Args:
        cmd: The `zellij ... attach --create <session>` argv.
        env: Child environment.
        session: The full session name (for stale pane-socket cleanup).
        mux: The multiplexer backend (None skips the cleanup).
        restart: Auto-restart zellij after it exits.
        restart_delay: Seconds to wait between restarts.
        on_restart: Called after zellij exits, before each restart.
        on_stop: Called on Ctrl+C while restart-looping.
    """
    clean_stale_sock_dir(mux, session)
    if not restart:
        os.execvpe("zellij", cmd, env)
        return
    try:
        while True:
            subprocess.run(cmd, env=env)
            on_restart()
            if restart_delay > 0:
                time.sleep(restart_delay)
    except KeyboardInterrupt:
        on_stop()
