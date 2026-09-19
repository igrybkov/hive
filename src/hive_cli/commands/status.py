"""Status command - display status of all agent worktrees, and (F4) run the
control-plane TUI on a TTY inside a multiplexer.
"""

from __future__ import annotations

import functools
import sys
from pathlib import Path
from typing import Annotated

from cyclopts import App, Parameter

from ..core import paths
from ..git import GitSummary, get_main_repo
from ..mux import get_mux
from ..services import session
from ..services import status as service_status
from ..services.facts import ControlServer
from ..ui.console import out as console
from ..ui.pickers import status as status_picker
from ..ui.tty import is_interactive
from ..ui.views import status as status_views


def display_status(compact: bool = False) -> None:
    """Display agent status board (one-shot; never imports textual).

    Args:
        compact: If True, use single-line-per-agent format.
    """
    main_repo = get_main_repo()
    statuses = service_status.collect_status(main_repo)

    if compact:
        output = status_views.build_compact_output(statuses, main_repo)
    else:
        output = status_views.build_full_output(statuses, main_repo)

    console.print(output)


class _FactsBox:
    """Reassigned (never mutated) each facts refresh, so `ControlServer`'s
    `facts` callable -- called from a socket handler thread -- always reads
    a consistent, already-computed dict."""

    def __init__(self) -> None:
        self.value: dict[str, GitSummary] = {}


def _refresh_facts(main_repo: Path, box: _FactsBox) -> dict[str, GitSummary]:
    facts = service_status.compute_facts(main_repo)
    box.value = facts
    return facts


def run_control_plane(*, compact: bool = False, poll_s: float = 3.0) -> None:
    """Run the control-plane TUI, or fall back to the one-shot table.

    Order matters: no multiplexer, then not-a-tty, both fall back to the
    plain table (`compact` applies only there -- the TUI always shows every
    column). Only a real TTY inside a multiplexer gets the TUI.
    """
    mux = get_mux()
    if mux is None or not is_interactive():
        display_status(compact=compact)
        return

    # Local import: keeps textual out of `--plain` and `import hive_cli.app`.
    from ..ui.tui.app import ControlPlaneApp

    main_repo = get_main_repo()
    session_name = mux.own_session() or ""
    box = _FactsBox()
    server = ControlServer(
        paths.control_sock(session_name),
        pane_id=mux.own_pane_id() or "",
        facts=lambda: box.value,
    )
    server.start()
    try:
        app = ControlPlaneApp(
            mux=mux,
            session=session_name,
            poll_s=poll_s,
            facts_fn=functools.partial(_refresh_facts, main_repo, box),
            tasks_fn=functools.partial(service_status.tasks_for_states, main_repo),
        )
        app.run()
    finally:
        server.close()


# Cyclopts App

status_app = App(
    name="status",
    help="Display status of all agent worktrees.",
)


@status_app.default
def status(
    watch: Annotated[
        bool,
        Parameter(
            name=["--watch", "-w"],
            help="Kept for old rendered layouts; folded into the default TUI.",
        ),
    ] = False,
    compact: Annotated[
        bool,
        Parameter(
            name=["--compact", "-c"],
            help="Single-line-per-agent format (only the --plain table).",
        ),
    ] = False,
    interactive: Annotated[
        bool,
        Parameter(
            name=["--interactive", "-i"],
            help="One-shot interactive selection. Outputs path for shell cd.",
        ),
    ] = False,
    interval: Annotated[
        float,
        Parameter(
            name="--interval",
            help="Control-plane pane/tab discovery interval, floored at 2s.",
        ),
    ] = 5.0,
    toggle: Annotated[
        bool,
        Parameter(
            help=(
                "Focus the running control plane, or start one (the control "
                "plane's own pane) if none is running. For the Alt+m hotkey."
            ),
        ),
    ] = False,
    plain: Annotated[
        bool,
        Parameter(help="One-shot Rich table for scripts/pipes; never runs the TUI."),
    ] = False,
):
    """Display status of all agent worktrees, or (F4) the control plane.

    On a TTY inside a multiplexer, the default (also `--watch`/`--compact`,
    kept for old rendered layouts) is the control-plane TUI: one row per
    agent pane, pushed live, with keys to focus/create/close/restart panes
    and open tabs (press `?` in it for the full list). Outside a
    multiplexer, or without a TTY, it falls back to the one-shot table.

    Shows branch, commits, dirty status, and tasks for each agent worktree.

    Examples:
        hive status              # Control-plane TUI (TTY + multiplexer)
        hive status --plain      # One-shot full table, for scripts/pipes
        hive status --plain -c   # One-shot compact table
        hive status -i           # Interactive selection
        hive status --toggle     # Focus (or start) the control plane

    Interactive picker keybindings:
        Enter    Show detailed worktree info (git status, commits)
        Ctrl+O   Open worktree in editor
        Ctrl+D   Delete worktree
        Esc      Go back to previous screen
        Ctrl+C   Quit entirely

    Detail view keybindings:
        ↑/k      Scroll up
        ↓/j      Scroll down
        PgUp/^U  Page up
        PgDn/^D  Page down
        g/G      Go to top/bottom
        e        Open worktree in editor
        d        Delete worktree
        Esc      Go back to worktree picker
        q        Quit entirely
    """
    poll_s = max(interval, 2.0)
    if plain:
        display_status(compact=compact)
    elif toggle:
        if session.toggle_control_plane():
            return
        run_control_plane(compact=compact, poll_s=poll_s)
    elif interactive and not watch:
        # One-shot interactive mode - outputs path to stdout for shell integration
        path = status_picker.interactive_status()
        if path:
            print(path)
        else:
            sys.exit(1)
    else:
        run_control_plane(compact=compact, poll_s=poll_s)
