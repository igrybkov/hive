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
from ..layout.model import TabSpec
from ..layout.resolve import resolve_layout
from ..layout.tabs import agents_tab, resolve_tab, session_spec
from ..mux import get_mux
from ..mux.base import Mux, PaneInfo
from ..mux.tmux.backend import TmuxMux
from ..mux.tmux.conf import render_conf
from ..mux.zellij.kdl import render_session_file
from ..state import client
from ..state.pane_state import label_for, next_free_pane_id
from ..state.pane_state import pane_hive_id as _pane_hive_id
from ..state.session_layout import read_agents_layout, write_agents_layout
from . import registry
from .restart import RestartFloor

AGENTS_TAB = "agents"


def _noop() -> None:
    return None


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


def prepare_tmux_attach(
    full_session_name: str, *, mux: Mux, hive: str, settings: HiveSettings
) -> tuple[list[str], Callable[[], None]]:
    """tmux's counterpart to `attach_argv`: render tmux.conf, return the
    attach argv plus an `ensure_session` callback for `start()` to call
    before every attach attempt.

    Unlike Zellij's `attach --create`, tmux's `attach-session` does not
    recreate a session that died between `--restart` loop iterations, so
    `ensure_session` (idempotent: `TmuxMux.bootstrap` no-ops when the
    session already exists) has to run every time, not just once here.

    Only "agent" has a tmux rendering (`layout.tabs.session_spec` ->
    `mux.tmux.conf.render_conf`, the tmux analogue of the KDL session
    file); any other configured layout has no tmux meaning and raises.
    """
    if settings.zellij.layout != "agent":
        raise HiveError(
            f"the tmux backend only supports the 'agent' layout "
            f"(configured: {settings.zellij.layout!r})",
            hint="set zellij.layout: agent, or switch mux.backend to zellij",
        )
    spec = session_spec(name=full_session_name, hive=hive, settings=settings)
    conf_dir = paths.layouts_dir() / full_session_name
    conf_dir.mkdir(parents=True, exist_ok=True)
    conf_path = conf_dir / "tmux.conf"
    conf_path.write_text(render_conf(spec, hive=hive))
    server = getattr(mux, "server", "hive")

    def ensure_session() -> None:
        TmuxMux(server=server, conf=conf_path).bootstrap(spec)

    return mux.attach_argv(full_session_name, str(conf_path)), ensure_session


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
    ensure_session: Callable[[], None] = _noop,
) -> None:
    """Launch the mux: hand off the process, or loop restarting it on exit.

    Args:
        cmd: The attach argv (`zellij [--layout ...] attach --create
            <session>`, or `tmux [-f conf] attach-session -t <session>`).
        env: Child environment.
        session: The full session name (for stale pane-socket cleanup).
        mux: The multiplexer backend (None skips the cleanup).
        restart: Auto-restart the mux after it exits.
        restart_delay: Seconds to wait between restarts.
        on_restart: Called after the mux exits, before each restart.
        on_stop: Called on Ctrl+C while restart-looping.
        restart_floor: Backoff after fast exits (default: a real one).
        ensure_session: Called before every attach attempt (`prepare_tmux_attach`'s
            bootstrap re-check; a no-op for Zellij, whose `attach --create`
            already recreates a session that died between restarts).
    """
    clean_stale_sock_dir(mux, session)
    if not restart:
        ensure_session()
        os.execvpe(cmd[0], cmd, env)
        return
    floor = restart_floor or RestartFloor()
    try:
        while True:
            ensure_session()
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


def _live_pane_ids(session: str) -> set[str]:
    return {s.pane_id for s in client.list_states(paths.session_sock_dir(session))}


def _taken_pane_ids(panes: list[PaneInfo], session: str) -> list[int]:
    live = [s.hive_pane_id for s in client.list_states(paths.session_sock_dir(session))]
    from_titles = [id_ for p in panes if (id_ := _pane_hive_id(p.title)) is not None]
    return live + from_titles


def agent_panes_in_tab(
    panes: list[PaneInfo], tab_id: str, session: str
) -> list[PaneInfo]:
    """Panes of the tab that are agent panes: a live hive socket, or a
    not-yet-started pane still carrying its layout-assigned `cN[: label]`
    title. Without the title check, a `start_suspended` pane from the
    initial agents_tab (never `hive run`, so no socket yet) is invisible
    here -- `new_agent_pane` would then split a duplicate pane into the tab
    and hand it the same HIVE_PANE_ID the suspended pane is already using."""
    live_ids = _live_pane_ids(session)
    return [
        p
        for p in panes
        if p.tab_id == tab_id
        and (p.id in live_ids or _pane_hive_id(p.title) is not None)
    ]


def current_tab_id(mux: Mux, panes: list[PaneInfo] | None = None) -> str | None:
    """`mux.current_tab_id()`, falling back to the focused pane's tab_id."""
    tab_id = mux.current_tab_id()
    if tab_id:
        return tab_id
    panes = panes if panes is not None else mux.list_panes()
    return next((p.tab_id for p in panes if p.focused), None)


def _reuse_idle_pane(
    mux: Mux,
    existing: list[PaneInfo],
    session: str,
    *,
    focus: bool,
    prefer: str | None = None,
) -> str | None:
    """Start and return an existing-but-never-started agent pane's id, or
    None when every pane in `existing` already has a live hive socket.
    `prefer`, when it names one of the idle candidates, wins over
    first-idle-found -- lets a caller that knows exactly which row the user
    selected (the control plane's `n`, G1) resume that one, not an arbitrary
    sibling idle slot in the same tab.

    `resume_pane` actually starts the pending command (the same keystroke a
    person would press), always -- not just when `focus` is set -- so this
    never merely moves the cursor onto a pane that's still sitting there
    dormant: the slot this returns is genuinely running by the time the
    caller sees its id, the same outcome as if a new pane had been spawned."""
    live_ids = _live_pane_ids(session)
    idle = [p for p in existing if p.id not in live_ids]
    if not idle:
        return None
    chosen = next((p for p in idle if p.id == prefer), idle[0])
    if focus:
        mux.focus_pane(chosen.id)
    mux.resume_pane(chosen.id)
    return chosen.id


def _refocus_before_split(
    mux: Mux, panes: list[PaneInfo], existing: list[PaneInfo], target_tab: str
) -> None:
    """Move focus onto the last agent pane before splitting a new one in,
    when the tab's active pane is something else (e.g. the control-plane
    pane) -- otherwise Zellij's `new-pane --direction right` splits *that*
    pane instead of the agents."""
    if not existing:
        return
    existing_ids = {p.id for p in existing}
    focused = next((p for p in panes if p.focused and p.tab_id == target_tab), None)
    if focused is not None and focused.id not in existing_ids:
        mux.focus_pane(existing[-1].id)


def _agent_argv(
    hive: str,
    number: int,
    label: str,
    *,
    agent: str | None,
    profile: str | None,
    branch: str | None,
) -> list[str]:
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
    return argv


@registry.op("session.new_agent_pane")
def new_agent_pane(
    *,
    mux: Mux | None = None,
    agent: str | None = None,
    profile: str | None = None,
    branch: str | None = None,
    tab_id: str | None = None,
    prefer_pane_id: str | None = None,
    focus: bool = True,
    settings: HiveSettings | None = None,
) -> str:
    """Start an idle agent slot, split a new pane into the target tab, or
    open a new, fully-provisioned agents tab -- every path ends with a
    genuinely running agent, never a pane left sitting there dormant.

    An explicit agent/profile/branch always creates a fresh pane -- an idle
    slot's command is fixed at layout time and can't take overrides. When
    that fresh pane lands in a brand-new tab, though, the override is
    currently lost anyway: `_fresh_agents_tab_spec`/`agents_tab` always
    render `hive run --restart` with no agent/profile/branch baked in
    (pre-existing; now hit on every full-tab case instead of only when the
    target tab already had `agents_per_tab` live agents).
    Otherwise, a pane already present in the target tab but never started
    (agents_tab's `start_suspended` slot, matched by `agent_panes_in_tab`
    even with no live socket yet) is resumed in place instead of duplicated
    (`_reuse_idle_pane` calls `mux.resume_pane`, the keystroke that starts
    its pending command -- not just `focus_pane`, which would only move the
    cursor there and leave it dormant) -- `prefer_pane_id`, when it names
    one of those idle candidates, is the one resumed (G1: the control plane's
    `n` passes the row the user actually selected, instead of leaving it to
    first-idle-found). Failing that, the session's live `agents_layout`
    (G2, `_agents_layout_mode`) decides what happens next: "tabs" always
    opens a fresh one-pane tab, ignoring `agents_per_tab`; otherwise, fewer
    than `settings.zellij.agents_per_tab` agent panes in the target tab ->
    split right of the *last agent pane* (`_refocus_before_split` guards
    against splitting whatever else happens to be focused there, e.g. the
    control-plane pane) -- stacked into it instead of splitting when the
    mode is "stacked". Otherwise (the target tab is full, or doesn't exist
    yet) a fresh tab opens via `_fresh_agents_tab_spec` with every
    `agents_per_tab` slot laid out at once (idle placeholders beyond the
    first) rather than one pane now and a live split later -- the tab's
    split ratio is then Zellij's static, even layout-file split, not an
    unrequestable live `new-pane` ratio. "tabs" mode still gets a genuine
    one-pane tab, since one agent per tab is that mode's point.
    """
    mux = _mux(mux)
    settings = settings or get_settings()
    session = mux.own_session() or ""
    mode = _agents_layout_mode(session, settings)
    panes = mux.list_panes()
    target_tab = tab_id or current_tab_id(mux, panes) or ""
    existing = agent_panes_in_tab(panes, target_tab, session) if target_tab else []

    if not (agent or profile or branch):
        idle_id = _reuse_idle_pane(
            mux, existing, session, focus=focus, prefer=prefer_pane_id
        )
        if idle_id is not None:
            return idle_id

    hive = paths.hive_executable()
    number = next_free_pane_id(_taken_pane_ids(panes, session))
    label = label_for(number, settings.zellij.pane_labels)

    if mode != "tabs" and len(existing) < settings.zellij.agents_per_tab:
        _refocus_before_split(mux, panes, existing, target_tab)
        argv = _agent_argv(
            hive, number, label, agent=agent, profile=profile, branch=branch
        )
        # --direction and --stacked are two different ways of saying where
        # the new pane goes; Zellij's own --stacked docs don't pair it with
        # a direction, so omit "right" rather than guess whether the CLI
        # accepts (or silently ignores, or errors on) both together.
        result = mux.new_pane(
            argv,
            direction="" if mode == "stacked" else "right",
            tab_id=target_tab or None,
            focus=focus,
            stacked=mode == "stacked",
        )
    else:
        n = 1 if mode == "tabs" else settings.zellij.agents_per_tab
        spec = _fresh_agents_tab_spec(
            hive=hive,
            first_id=number,
            n=n,
            settings=settings,
            stacked=mode == "stacked",
            focus=focus,
        )
        result = mux.new_tab(spec, focus=focus)
    if result is None:
        raise HiveError("failed to create an agent pane")
    return result


def _agents_layout_mode(session: str, settings: HiveSettings) -> str:
    return read_agents_layout(session, default=settings.zellij.agents_layout)


def _fresh_agents_tab_spec(
    *,
    hive: str,
    first_id: int,
    n: int,
    settings: HiveSettings,
    stacked: bool,
    focus: bool,
) -> TabSpec:
    """A brand-new, fully-provisioned agents tab: `n` slots starting at
    `first_id`, the first live and the rest `start_suspended` idle
    placeholders (`agents_tab`) -- rendered as one static KDL layout so
    Zellij's own even split among unsized siblings applies. Deliberately not
    built by starting with one pane and splitting the rest in later: Zellij's
    `new-pane --direction right` has no way to request a ratio
    (`--width`/`--height` require `--floating`; `resize` is relative-only),
    so a live split of a solo pane can land anywhere, not 50/50."""
    labels = [label_for(first_id + i, settings.zellij.pane_labels) for i in range(n)]
    return agents_tab(
        n=n,
        control="none",
        hive=hive,
        labels=labels,
        first_id=first_id,
        focus=focus,
        stacked=stacked,
    )


@registry.op("session.open_tab")
def open_tab(name: str, *, mux: Mux | None = None, focus: bool = True) -> str:
    """`resolve_tab(name)` -> `mux.new_tab`; `agents` opens a fresh agents tab."""
    mux = _mux(mux)
    settings = get_settings()
    hive = paths.hive_executable()
    if name == AGENTS_TAB:
        session = mux.own_session() or ""
        first_id = next_free_pane_id(_taken_pane_ids(mux.list_panes(), session))
        spec = _fresh_agents_tab_spec(
            hive=hive,
            first_id=first_id,
            n=settings.zellij.agents_per_tab,
            settings=settings,
            stacked=_agents_layout_mode(session, settings) == "stacked",
            focus=focus,
        )
    else:
        spec = resolve_tab(name, hive=hive, user_tabs=settings.tabs, backend=mux.name)
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


@registry.op("session.get_agents_layout")
def get_agents_layout(
    *,
    session: str | None = None,
    mux: Mux | None = None,
    settings: HiveSettings | None = None,
) -> str:
    """The session's effective agents_layout: the live override (G2) if one
    was set, else `settings.zellij.agents_layout`."""
    session = session or _mux(mux).own_session() or ""
    settings = settings or get_settings()
    return _agents_layout_mode(session, settings)


@registry.op("session.set_agents_layout")
def set_agents_layout(
    mode: str, *, session: str | None = None, mux: Mux | None = None
) -> str:
    """Change the session's live agents_layout override (G2) for the rest
    of the session; raises HiveError on an unrecognized mode."""
    session = session or _mux(mux).own_session() or ""
    try:
        write_agents_layout(session, mode)
    except ValueError as exc:
        raise HiveError(str(exc)) from exc
    return mode


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
