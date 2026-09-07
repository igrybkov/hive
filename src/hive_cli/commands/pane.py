"""Pane command - on-demand agent panes, floating/split shells, pane management."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Annotated

from cyclopts import App, Parameter

from ..core import paths
from ..core.errors import HiveError
from ..git import get_main_repo, get_worktree_path, list_worktrees
from ..mux import get_mux
from ..mux.base import Mux
from ..mux.zellij.backend import set_pane_custom_title, set_pane_status
from ..services import session
from ..state import client
from ..ui.console import dim, error, out, prompt

pane_app = App(
    name="pane",
    help="Create and manage agent panes.",
)


def _require_mux() -> Mux:
    mux = get_mux()
    if mux is None:
        error("Not running inside a multiplexer session")
        sys.exit(1)
    return mux


def _die(exc: HiveError) -> None:
    error(str(exc))
    sys.exit(exc.exit_code)


@pane_app.command(name="new")
def new(
    agent: Annotated[
        str | None, Parameter(name=["--agent", "-a"], help="Agent to run.")
    ] = None,
    profile: Annotated[
        str | None, Parameter(name=["--profile", "-p"], help="Config profile.")
    ] = None,
    branch: Annotated[
        str | None, Parameter(name=["--branch", "-w"], help="Worktree branch.")
    ] = None,
    tab_id: Annotated[
        str | None,
        Parameter(name="--tab-id", help="Target tab id (default: the current tab)."),
    ] = None,
    focus: Annotated[
        bool, Parameter(negative="--no-focus", help="Focus the new pane.")
    ] = True,
):
    """Create a new agent pane.

    Splits into the target tab if it has room (zellij.agents_per_tab), else
    opens a fresh one-pane agents tab. Prints the new pane's id.

    Examples:
        hive pane new                    # split an agent pane into this tab
        hive pane new -a codex -w feat   # run codex on branch 'feat'
        hive pane new --no-focus         # create it without switching focus
    """
    try:
        pane_id = session.new_agent_pane(
            agent=agent, profile=profile, branch=branch, tab_id=tab_id, focus=focus
        )
    except HiveError as exc:
        _die(exc)
        return
    print(pane_id)


def _shell_worktree(branch: str | None, here: bool) -> Path | None:
    if branch:
        return get_worktree_path(branch)
    if here:
        main_repo = get_main_repo()
        resolved = session.resolve_here(
            Path.cwd(), main_repo, list_worktrees(main_repo)
        )
        if resolved is None:
            raise HiveError("not inside a worktree")
        return resolved
    return None


@pane_app.command
def shell(
    branch: Annotated[
        str | None,
        Parameter(name=["--worktree", "-w"], help="Branch of the worktree to open."),
    ] = None,
    here: Annotated[
        bool, Parameter(help="Use the worktree of the current pane's cwd.")
    ] = False,
    floating: Annotated[
        bool, Parameter(help="Open as a floating popup instead of a split pane.")
    ] = False,
):
    """Open a shell in a worktree.

    Examples:
        hive pane shell -w feat         # split pane, cwd in the 'feat' worktree
        hive pane shell --here          # split pane, cwd in this pane's worktree
        hive pane shell --here --floating  # same, as a floating popup
    """
    try:
        if floating:
            session.floating_shell(worktree=_shell_worktree(branch, False), here=here)
            return
        cwd = _shell_worktree(branch, here)
    except HiveError as exc:
        _die(exc)
        return

    mux = _require_mux()
    mux.new_pane([os.environ.get("SHELL", "/bin/sh")], cwd=str(cwd) if cwd else None)


@pane_app.command(name="list")
def list_cmd(
    as_json: Annotated[bool, Parameter(name="--json", help="Emit JSON.")] = False,
):
    """List panes in the current session, joined with live hive state.

    Examples:
        hive pane list
        hive pane list --json
    """
    mux = _require_mux()
    session_name = mux.own_session() or ""
    states = {
        s.pane_id: s for s in client.list_states(paths.session_sock_dir(session_name))
    }
    rows = []
    for p in mux.list_panes():
        state = states.get(p.id)
        rows.append(
            {
                "id": p.id,
                "tab_id": p.tab_id,
                "title": p.title,
                "agent": state.agent if state else "",
                "branch": state.branch if state else "",
                "status": state.status if state else "",
                "focused": p.focused,
            }
        )
    if as_json:
        print(json.dumps(rows))
        return
    for row in rows:
        marker = "*" if row["focused"] else " "
        out.print(
            f"{marker} {row['id']:>4}  {row['status']:<10} "
            f"{row['agent']:<10} {row['branch']:<20} {row['title']}"
        )


@pane_app.command
def focus(id: Annotated[str, Parameter(help="Pane id.")]):
    """Focus a pane by id.

    Examples:
        hive pane focus 3
    """
    _require_mux().focus_pane(id)


@pane_app.command
def close(id: Annotated[str, Parameter(help="Pane id.")]):
    """Close a pane by id.

    Examples:
        hive pane close 3
    """
    _require_mux().close_pane(id)


@pane_app.command
def restart(id: Annotated[str, Parameter(help="Pane id.")]):
    """Restart the agent in a pane (its `hive run` re-selects on the next loop).

    Examples:
        hive pane restart 3
    """
    mux = _require_mux()
    session_name = mux.own_session() or ""
    if not client.request(paths.pane_sock(session_name, id), "restart"):
        error(f"No live agent pane: {id}")
        sys.exit(1)


def _wait_for_enter() -> None:
    input()


@pane_app.command
def hold(
    command: Annotated[
        tuple[str, ...], Parameter(help="Command to run once Enter is pressed.")
    ],
):
    """Wait for Enter, then run COMMAND (start-suspended panes, F6/tmux).

    Examples:
        hive pane hold -- claude
    """
    session.hold(list(command), prompt=prompt, wait=_wait_for_enter)


@pane_app.command(name="set-status")
def set_status(
    status: Annotated[
        str | None, Parameter(help="Agent status (e.g., '[working]').")
    ] = None,
):
    """Set agent status in the pane title (same as `hive zellij set-status`).

    Examples:
        hive pane set-status "[working]"
    """
    if not set_pane_status(status):
        dim("Not running in Zellij session")


@pane_app.command(name="set-title")
def set_title(
    title: Annotated[str | None, Parameter(help="Custom title suffix.")] = None,
):
    """Set custom title suffix in the pane title (same as `hive zellij set-title`).

    Examples:
        hive pane set-title "JIRA-123"
    """
    if not set_pane_custom_title(title):
        dim("Not running in Zellij session")
