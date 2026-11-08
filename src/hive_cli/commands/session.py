"""Session command - backend-neutral `hive zellij`: opens whichever
multiplexer `get_mux()` resolves (config `mux.backend`, env, or the
environment the process runs in), falling back to Zellij when nothing is
configured and no session is currently running -- the same starting-fresh
experience `hive zellij` has always had.
"""

from __future__ import annotations

import shutil
import sys
from typing import Annotated

from cyclopts import App, Parameter
from rich.console import Console

from ..agents import detect_agent
from ..config import KNOWN_AGENTS, get_runtime_settings, get_settings
from ..core.errors import HiveError
from ..core.paths import hive_executable
from ..git.repo import change_to_main_repo, get_session_name
from ..mux import get_mux
from ..services import session
from ..ui.console import error, format_yellow

console = Console()

session_app = App(
    name="session",
    help="Open the configured multiplexer (Zellij or tmux) with the AI agent layout.",
)


@session_app.default
def session_cmd(
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
        Parameter(help="Auto-restart the multiplexer after it exits."),
    ] = False,
    restart_delay: Annotated[
        float,
        Parameter(
            name="--restart-delay",
            help="Delay in seconds between restarts (default: 0).",
        ),
    ] = 0,
):
    """Open the configured multiplexer with the AI agent layout.

    Backend-neutral counterpart to `hive zellij`: picks Zellij or tmux the
    same way `get_mux()` does everywhere else (`mux.backend` config,
    HIVE_MUX_BACKEND, or the multiplexer the process is already inside),
    falling back to Zellij when none of those apply and nothing is running
    yet -- the same "starting fresh" experience `hive zellij` has always
    had, since `mux.backend: auto` alone can't tell you which multiplexer
    to *start*.

    Examples:
        hive session                          # Auto-detect agent and backend
        hive session -a claude                # Use Claude specifically
        HIVE_MUX_BACKEND=tmux hive session     # Force the tmux backend
        hive session --restart                # Auto-restart after it exits
    """
    change_to_main_repo()
    repo_name = get_session_name()

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

    rt = get_runtime_settings()
    rt.agent = detected.name

    mux = get_mux() or get_mux("zellij")
    if not shutil.which(mux.name):
        error(f"{mux.name} is not installed. Install it with: brew install {mux.name}")
        sys.exit(1)

    config = get_settings()
    full_session_name = session.session_name(
        config.zellij.session_name, repo=repo_name, agent=detected.name
    )
    hive = hive_executable()
    ensure_session = None
    try:
        if mux.name == "tmux":
            cmd, ensure_session = session.prepare_tmux_attach(
                full_session_name, mux=mux, hive=hive, settings=config
            )
        else:
            cmd = session.attach_argv(
                config.zellij.layout,
                full_session_name,
                mux=mux,
                hive=hive,
                settings=config,
            )
    except HiveError as exc:
        error(str(exc))
        sys.exit(exc.exit_code)

    child_env = rt.build_child_env()

    def on_restart() -> None:
        console.print(f"\n[hive] {mux.name} exited. Restarting... (Ctrl+C to stop)")

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
        ensure_session=ensure_session or (lambda: None),
    )
