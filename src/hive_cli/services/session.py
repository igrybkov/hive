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
from pathlib import Path

from ..config import get_settings
from ..config.settings import HiveSettings
from ..core import paths
from ..core.errors import HiveError
from ..git import WorktreeInfo, get_main_repo, list_worktrees
from ..layout.resolve import resolve_layout
from ..layout.tabs import agents_tab, resolve_tab
from ..mux import get_mux
from ..mux.base import Mux, PaneInfo
from ..mux.zellij.kdl import render_session_file
from ..state import client
from ..state.pane_state import label_for, next_free_pane_id
from . import registry
from .restart import RestartFloor

AGENTS_TAB = "agents"


def session_name(template: str, *, repo: str, agent: str) -> str:
    """Build the full Zellij session name from the configured template.

    Supports {repo} and {agent} placeholders.
    """
    return template.format(repo=repo, agent=agent)


def resolve_layout_path(
    layout: str | None, *, session: str, hive: str, settings: HiveSettings
) -> str | None:
    """`layout.resolve.resolve_layout` with the zellij KDL renderer wired in.

    The only caller-visible entry point for layout resolution: hides that
    "agent" needs a renderer at all (layout/resolve.py can't import it —
    see its module docstring).
    """
    return resolve_layout(
        layout,
        session=session,
        hive=hive,
        settings=settings,
        render=render_session_file,
    )


def attach_argv(
    layout: str | None,
    full_session_name: str,
    *,
    mux: Mux,
    hive: str,
    settings: HiveSettings,
) -> list[str]:
    """Build the `zellij [--layout ...] attach --create <session>` argv.

    Resolves the layout (rendering and writing session.kdl for "agent"),
    then defers the actual argv shape to the mux backend.
    """
    resolved = resolve_layout_path(
        layout, session=full_session_name, hive=hive, settings=settings
    )
    return mux.attach_argv(full_session_name, resolved)


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
    restart_floor: RestartFloor | None = None,
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
        restart_floor: Backoff after fast exits (default: a real one).
    """
    clean_stale_sock_dir(mux, session)
    if not restart:
        os.execvpe(cmd[0], cmd, env)
        return
    floor = restart_floor or RestartFloor()
    try:
        while True:
            floor.started()
            subprocess.run(cmd, env=env)
            on_restart()
            floor.exited()
            if restart_delay > 0:
                time.sleep(restart_delay)
    except KeyboardInterrupt:
        on_stop()


# ---------------------------------------------------------------------------
# F3: on-demand tabs/panes, floating shell, control-plane toggle
# ---------------------------------------------------------------------------


def _mux(mux: Mux | None) -> Mux:
    resolved = mux if mux is not None else get_mux()
    if resolved is None:
        raise HiveError("not inside a multiplexer")
    return resolved


def _taken_pane_ids(session: str) -> list[int]:
    return [s.hive_pane_id for s in client.list_states(paths.session_sock_dir(session))]


def agent_panes_in_tab(mux: Mux, tab_id: str, session: str) -> list[PaneInfo]:
    """Panes of the tab that have a live hive socket (client.list_states)."""
    live_ids = {s.pane_id for s in client.list_states(paths.session_sock_dir(session))}
    return [p for p in mux.list_panes() if p.tab_id == tab_id and p.id in live_ids]


def current_tab_id(mux: Mux) -> str | None:
    """`mux.current_tab_id()`, falling back to the focused pane's tab_id."""
    tab_id = mux.current_tab_id()
    if tab_id:
        return tab_id
    return next((p.tab_id for p in mux.list_panes() if p.focused), None)


@registry.op("session.new_agent_pane")
def new_agent_pane(
    *,
    mux: Mux | None = None,
    agent: str | None = None,
    profile: str | None = None,
    branch: str | None = None,
    tab_id: str | None = None,
    focus: bool = True,
    settings: HiveSettings | None = None,
) -> str:
    """Split a new agent pane into the target tab, or open a new agents tab.

    Fewer than `settings.zellij.agents_per_tab` live agent panes in the
    target tab -> split right into it; otherwise a fresh one-pane agents tab.
    """
    mux = _mux(mux)
    settings = settings or get_settings()
    session = mux.own_session() or ""
    target_tab = tab_id or current_tab_id(mux) or ""
    existing = agent_panes_in_tab(mux, target_tab, session) if target_tab else []
    hive = paths.hive_executable()
    number = next_free_pane_id(_taken_pane_ids(session))
    label = label_for(number, settings.zellij.pane_labels)

    if len(existing) < settings.zellij.agents_per_tab:
        argv = ["/usr/bin/env", f"HIVE_PANE_ID={number}"]
        if label:
            argv.append(f"HIVE_PANE_LABEL={label}")
        argv += [hive, "run", "--restart"]
        if agent:
            argv += ["-a", agent]
        if profile:
            argv += ["-p", profile]
        if branch:
            argv += ["-w", branch]
        result = mux.new_pane(
            argv, direction="right", tab_id=target_tab or None, focus=focus
        )
    else:
        spec = agents_tab(
            n=1,
            control="none",
            hive=hive,
            labels=[label] if label else [],
            first_id=number,
            focus=focus,
        )
        result = mux.new_tab(spec, focus=focus)
    if result is None:
        raise HiveError("failed to create an agent pane")
    return result


@registry.op("session.open_tab")
def open_tab(name: str, *, mux: Mux | None = None, focus: bool = True) -> str:
    """`resolve_tab(name)` -> `mux.new_tab`; `agents` opens a fresh agents tab."""
    mux = _mux(mux)
    settings = get_settings()
    hive = paths.hive_executable()
    if name == AGENTS_TAB:
        session = mux.own_session() or ""
        first_id = next_free_pane_id(_taken_pane_ids(session))
        n = settings.zellij.agents_per_tab
        labels = [
            label_for(first_id + i, settings.zellij.pane_labels) for i in range(n)
        ]
        spec = agents_tab(
            n=n,
            control="none",
            hive=hive,
            labels=labels,
            first_id=first_id,
            focus=focus,
        )
    else:
        spec = resolve_tab(name, hive=hive, user_tabs=settings.tabs)
    result = mux.new_tab(spec, focus=focus)
    if result is None:
        raise HiveError(f"failed to open tab: {name}")
    return result


def resolve_here(
    cwd: Path, main_repo: Path, worktrees: list[WorktreeInfo]
) -> Path | None:
    """The worktree (or main repo) whose path is `cwd` or a parent of it.

    None when `cwd` is outside every candidate; the longest match wins for
    nested worktree paths.
    """
    candidates = [main_repo, *(wt.path for wt in worktrees)]
    matches = [p for p in candidates if cwd == p or p in cwd.parents]
    return max(matches, key=lambda p: len(p.parts), default=None)


@registry.op("session.floating_shell")
def floating_shell(
    *,
    mux: Mux | None = None,
    worktree: Path | None = None,
    here: bool = False,
    command: list[str] | None = None,
) -> None:
    """Open a floating shell (or `command`) popup, cwd in `worktree` or `here`."""
    mux = _mux(mux)
    cwd = worktree
    if here:
        main_repo = get_main_repo()
        cwd = resolve_here(Path.cwd(), main_repo, list_worktrees(main_repo))
        if cwd is None:
            raise HiveError("not inside a worktree")
    argv = command or [os.environ.get("SHELL", "/bin/sh")]
    mux.popup(argv, cwd=str(cwd) if cwd else None, name="shell")


@registry.op("session.toggle_control_plane")
def toggle_control_plane(*, mux: Mux | None = None, session: str | None = None) -> bool:
    """Focus the running control plane if one answers on its socket.

    True when an existing control plane was found and focused; False means
    the caller should start one (the control socket itself is served by
    `hive status --watch`, F4).
    """
    mux = _mux(mux)
    session = session or mux.own_session() or ""
    state = client.get_state(paths.control_sock(session))
    pane_id = state.get("pane_id") if state else None
    if not pane_id:
        return False
    mux.focus_pane(str(pane_id))
    return True


@registry.op("session.restart_pane")
def restart_pane(
    pane_id: str, *, session: str | None = None, mux: Mux | None = None
) -> bool:
    """Ask the pane's `hive run` to restart; True when it acknowledged.

    `session` is resolved from `mux.own_session()` only when not given, so a
    caller that already knows its session (the control plane, F4) never
    needs a multiplexer just to restart a pane.
    """
    if session is None:
        session = _mux(mux).own_session() or ""
    return client.request(paths.pane_sock(session, pane_id), "restart")


def hold(
    argv: list[str],
    *,
    prompt: Callable[[str], None],
    wait: Callable[[], None],
    exec_: Callable[[str, list[str]], None] = os.execvp,
) -> int:
    """Wait for Enter on the tty, then exec `argv` (tmux start-suspended, F6).

    `prompt`/`wait` are injected so this stays print/input-free (services may
    not call print/input directly); callers supply the real console/stdin.
    """
    prompt(f"[hive] press Enter to start: {' '.join(argv)}")
    wait()
    exec_(argv[0], argv)
    return 0
