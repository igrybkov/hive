"""Status command - display status of all agent worktrees."""

from __future__ import annotations

import sys
from typing import Annotated

from cyclopts import App, Parameter

from ..git import get_main_repo
from ..services import session
from ..services import status as service_status
from ..ui import board
from ..ui.console import out as console
from ..ui.pickers import status as status_picker
from ..ui.views import status as status_views

ENTER_KEYS = ("\r", "\n")


def display_status(compact: bool = False) -> None:
    """Display agent status board.

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


def watch_status(compact: bool = False, interval: float = 5.0) -> None:
    """Live board (repainted only when something changed) until `q`.

    Enter leaves the board for the interactive picker and returns to it.
    """
    main_repo = get_main_repo()
    while True:
        key, statuses = board.watch(
            lambda: service_status.collect_status(main_repo),
            lambda data: status_views.build_watch_view(data, main_repo, compact),
            interval=interval,
            exit_keys=ENTER_KEYS,
        )
        if key not in ENTER_KEYS:
            return
        status_picker.interactive_status(statuses=statuses, main_repo=main_repo)


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
            help=(
                "Watch mode with interactive selection. Press Enter to select worktree."
            ),
        ),
    ] = False,
    compact: Annotated[
        bool,
        Parameter(
            name=["--compact", "-c"],
            help="Use single-line-per-agent compact format.",
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
        Parameter(name="--interval", help="Seconds between refreshes in watch mode."),
    ] = 5.0,
    toggle: Annotated[
        bool,
        Parameter(
            help=(
                "Focus the running floating control-plane pane, or open one "
                "(compact watch mode) if none is running. For the Alt+m hotkey."
            ),
        ),
    ] = False,
):
    """Display status of all agent worktrees.

    Shows branch, commits, dirty status, and tasks for each agent worktree.

    Examples:
        hive status              # Full status view (one-shot)
        hive status --compact    # Compact format (one-shot)
        hive status --watch      # Watch mode (press Enter for interactive)
        hive status -w -c        # Compact watch mode
        hive status -w --interval 2   # Refresh every 2 seconds
        hive status -i           # Interactive selection
        hive status --toggle     # Focus (or open) the floating control plane

    Watch mode keybindings:
        Enter    Open interactive worktree picker
        r        Refresh now
        q        Quit watch mode

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
    if toggle:
        if session.toggle_control_plane():
            return
        watch_status(compact=True, interval=interval)
    elif interactive and not watch:
        # One-shot interactive mode - outputs path to stdout for shell integration
        path = status_picker.interactive_status()
        if path:
            print(path)
        else:
            sys.exit(1)
    elif watch:
        # Live board; Enter opens the interactive picker and comes back
        watch_status(compact=compact, interval=interval)
    else:
        # One-shot display
        display_status(compact=compact)
