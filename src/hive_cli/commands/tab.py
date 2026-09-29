"""Tab command - open tool tabs and agent tabs on demand."""

from __future__ import annotations

import sys
from typing import Annotated

from cyclopts import App, Parameter

from ..config import get_settings
from ..core.errors import HiveError
from ..layout.tabs import BUNDLED
from ..services import session
from ..ui.console import error

tab_app = App(
    name="tab",
    help="Open tool tabs and agent tabs on demand.",
)


@tab_app.default
def tab(
    name: Annotated[
        str, Parameter(help="Tab to open: a bundled/user-defined name, or 'agents'.")
    ],
    focus: Annotated[
        bool, Parameter(negative="--no-focus", help="Focus the new tab.")
    ] = True,
):
    """Open a tab by name.

    Examples:
        hive tab git       # open the bundled git tab
        hive tab agents    # open a fresh agents tab
        hive tab mytab     # open a user-defined tab from `tabs:` config
    """
    try:
        session.open_tab(name, focus=focus)
    except HiveError as exc:
        error(str(exc))
        sys.exit(exc.exit_code)


@tab_app.command(name="list")
def list_cmd():
    """List available tab names: 'agents', bundled tool tabs, and user-defined tabs.

    Examples:
        hive tab list
    """
    names = sorted({session.AGENTS_TAB, *BUNDLED, *get_settings().tabs})
    for name in names:
        print(name)
