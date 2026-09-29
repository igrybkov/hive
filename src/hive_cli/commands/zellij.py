"""Zellij command - open Zellij with agent layout."""

from __future__ import annotations

import shutil
import sys
from typing import Annotated

from cyclopts import App, Parameter
from rich.console import Console

from ..agents import detect_agent
from ..config import KNOWN_AGENTS, get_runtime_settings, get_settings
from ..core.paths import hive_executable
from ..git.repo import change_to_main_repo, get_session_name
from ..mux import get_mux
from ..mux.zellij.backend import set_pane_custom_title, set_pane_status
from ..services import session
from ..ui.console import error, format_yellow

console = Console()
stderr_console = Console(stderr=True)

zellij_app = App(
    name="zellij",
    help="Open Zellij with AI agent layout.",
)


@zellij_app.default
def zellij(
    agent: Annotated[
        str | None,
        Parameter(
            name=["--agent", "-a"],
            env_var="HIVE_AGENT",
            help="Specific agent to use (overrides auto-detection).",
        ),
    ] = None,
    restart: Annotated[
        bool,
        Parameter(help="Auto-restart Zellij after it exits."),
    ] = False,
    restart_delay: Annotated[
        float,
        Parameter(
            name="--restart-delay",
            help="Delay in seconds between restarts (default: 0).",
        ),
    ] = 0,
):
    """Open Zellij with AI agent layout.

    Auto-detects available AI agent and opens Zellij with the generic agent layout.
    Always runs from the main repository (not worktree).

    Examples:
        hive zellij                          # Auto-detect agent
        hive zellij -a claude                # Use Claude specifically
        hive zellij --restart                # Auto-restart after Zellij exits
        hive zellij --restart --restart-delay 1  # Restart with 1s delay
        HIVE_AGENT=gemini hive zellij         # Use Gemini via env var
    """
    # Check zellij is available
    if not shutil.which("zellij"):
        error("zellij is not installed. Install it with: brew install zellij")
        sys.exit(1)

    # Change to main repo
    change_to_main_repo()
    repo_name = get_session_name()

    # Detect agent
    detected = detect_agent(preferred=agent)

    if detected is None:
        if agent:
            error(
                f"Agent '{format_yellow(agent)}' is not available. "
                f"Is it installed and in your PATH?"
            )
        else:
            agents_list = ", ".join(KNOWN_AGENTS)
            error(f"No AI coding agent found. Install one of: {agents_list}")
        sys.exit(1)

    # Set HIVE_AGENT for child processes (hive run uses this)
    rt = get_runtime_settings()
    rt.agent = detected.name

    # Get zellij config
    config = get_settings()

    full_session_name = session.session_name(
        config.zellij.session_name, repo=repo_name, agent=detected.name
    )
    mux = get_mux("zellij")
    cmd = session.attach_argv(
        config.zellij.layout,
        full_session_name,
        mux=mux,
        hive=hive_executable(),
        settings=config,
    )
    child_env = rt.build_child_env()

    def on_restart() -> None:
        console.print("\n[hive] Zellij exited. Restarting... (Ctrl+C to stop)")

    def on_stop() -> None:
        console.print("\n[hive] Stopped.")
        sys.exit(0)

    session.start(
        cmd,
        child_env,
        session=full_session_name,
        mux=mux,
        restart=restart,
        restart_delay=restart_delay,
        on_restart=on_restart,
        on_stop=on_stop,
    )


@zellij_app.command(name="set-status")
def set_status(
    status: Annotated[
        str | None, Parameter(help="Agent status (e.g., '[working]').")
    ] = None,
):
    """Set agent status in pane title.

    Examples:
        hive zellij set-status "[working]"
        hive zellij set-status "[idle]"
        hive zellij set-status           # Clear status
    """
    if not set_pane_status(status):
        stderr_console.print("[dim]Not running in Zellij session[/dim]")


@zellij_app.command(name="set-title")
def set_title(
    title: Annotated[str | None, Parameter(help="Custom title suffix.")] = None,
):
    """Set custom title suffix in pane title.

    Examples:
        hive zellij set-title "Fixing auth bug"
        hive zellij set-title "JIRA-123"
        hive zellij set-title             # Clear custom title
    """
    if not set_pane_custom_title(title):
        stderr_console.print("[dim]Not running in Zellij session[/dim]")


@zellij_app.command(name="layout-path")
def layout_path(
    name: Annotated[
        str | None,
        Parameter(help="Layout name to resolve. Defaults to the configured layout."),
    ] = None,
    rendered: Annotated[
        bool,
        Parameter(
            name="--rendered",
            help="Explicit request for the rendered 'agent' session file "
            "(the default already renders it; kept for discoverability).",
        ),
    ] = False,
):
    """Print the resolved path (or name) for a Zellij layout.

    Useful for running `zellij --layout <path>` by hand. The bundled
    "agent" layout renders on every call (session.kdl under
    `hive doctor`'s state dir); "agent-16" and other bundled/path/passthrough
    values are static, as before.

    Examples:
        hive zellij layout-path              # resolve the configured layout
        hive zellij layout-path agent        # render+resolve the "agent" layout
        hive zellij layout-path agent-16     # the old 16-pane session file
        zellij --layout (hive zellij layout-path)
    """
    del rendered  # documented no-op: resolution below already renders "agent"
    config = get_settings()
    value = name if name is not None else config.zellij.layout
    change_to_main_repo()
    detected = detect_agent()
    full_session_name = session.session_name(
        config.zellij.session_name,
        repo=get_session_name(),
        agent=detected.name if detected else "",
    )
    resolved = session.resolve_layout_path(
        value, session=full_session_name, hive=hive_executable(), settings=config
    )
    if resolved is None:
        stderr_console.print("[dim]No layout configured[/dim]")
        sys.exit(1)
    print(resolved)
