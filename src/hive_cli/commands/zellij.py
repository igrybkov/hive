"""Zellij command - open Zellij with agent layout."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from typing import Annotated

from cyclopts import App, Parameter
from rich.console import Console

from ..agents import detect_agent
from ..config import KNOWN_AGENTS, get_runtime_settings, get_settings
from ..git.repo import change_to_main_repo, get_session_name
from ..utils import error, format_yellow
from ..utils.layouts import resolve_layout
from ..utils.zellij import set_pane_custom_title, set_pane_status

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
    session_name = get_session_name()

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

    # Build session name from template
    # Supports {repo} and {agent} placeholders
    full_session_name = config.zellij.session_name.format(
        repo=session_name,
        agent=detected.name,
    )

    # Build zellij command
    cmd = ["zellij"]

    # Add layout if configured (bundled name -> packaged path, path/`.kdl` ->
    # expanded, otherwise passed through for zellij to resolve itself)
    resolved_layout = resolve_layout(config.zellij.layout)
    if resolved_layout:
        cmd.extend(["--layout", resolved_layout])

    cmd.extend(["attach", "--create", full_session_name])

    child_env = rt.build_child_env()

    if restart:
        # Auto-restart loop
        try:
            while True:
                subprocess.run(cmd, env=child_env)
                console.print("\n[hive] Zellij exited. Restarting... (Ctrl+C to stop)")
                if restart_delay > 0:
                    time.sleep(restart_delay)
        except KeyboardInterrupt:
            console.print("\n[hive] Stopped.")
            sys.exit(0)
    else:
        # Execute zellij, replacing the current process
        os.execvpe("zellij", cmd, child_env)


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
):
    """Print the resolved path (or name) for a Zellij layout.

    Useful for running `zellij --layout <path>` by hand, since the bundled
    "agent" layout no longer exists as a file under
    ~/.config/zellij/layouts/ — it ships inside the hive package.

    Examples:
        hive zellij layout-path              # resolve the configured layout
        hive zellij layout-path agent        # resolve the bundled "agent" layout
        zellij --layout (hive zellij layout-path)
    """
    value = name if name is not None else get_settings().zellij.layout
    resolved = resolve_layout(value)
    if resolved is None:
        stderr_console.print("[dim]No layout configured[/dim]")
        sys.exit(1)
    print(resolved)
