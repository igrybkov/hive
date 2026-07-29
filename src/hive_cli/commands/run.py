"""Run command - launch AI coding agent."""

from __future__ import annotations

import subprocess
import sys
from typing import Annotated

from cyclopts import App, Parameter

from ..agents import detect_agent
from ..config import (
    KNOWN_AGENTS,
    get_agent_config,
    get_extra_dirs_args,
    get_runtime_settings,
    get_settings,
    resolve_profile_env,
)
from ..utils import error, format_yellow
from .exec_runner import run_in_worktree


def _detect_current_agent(
    preferred: str | None, extra_args: tuple[str, ...]
) -> tuple[str, list[str]] | None:
    """Detect the current agent, respecting HIVE_AGENT env var.

    Args:
        preferred: Preferred agent from CLI flag (takes precedence over env).
        extra_args: Extra arguments to pass to the agent.

    Returns:
        Tuple of (agent_name, command_list) or None if no agent found.
    """
    # Check HIVE_AGENT (set by interactive picker via Ctrl+A)
    rt = get_runtime_settings()

    # CLI flag takes precedence, then env var
    agent_to_use = preferred or rt.agent

    detected = detect_agent(preferred=agent_to_use)
    if detected is None:
        return None

    return detected.name, [detected.command, *extra_args]


def _get_pane_name_info(agent_name: str) -> tuple[str, bool]:
    """Get the pane name prefix and whether layout has the base name.

    If HIVE_PANE_ID is set, we're running in the Zellij layout which already
    defines the base pane name (e.g., "agent-1"), so we only need to append
    the branch suffix.

    Returns:
        Tuple of (prefix, layout_has_base_name).
    """
    rt = get_runtime_settings()
    if rt.pane_id:
        return f"agent-{rt.pane_id}", True
    return agent_name, False


def _complete_agent(ctx, param, incomplete):
    """Shell completion for --agent option."""
    return [agent for agent in KNOWN_AGENTS if agent.startswith(incomplete)]


run_app = App(
    name="run",
    help="Run AI coding agent in current directory.",
)


@run_app.default
def run(
    agent: Annotated[
        str | None,
        Parameter(
            name=["--agent", "-a"],
            env_var="HIVE_AGENT",
            help="Specific agent to use (overrides auto-detection).",
        ),
    ] = None,
    worktree: Annotated[
        str | None,
        Parameter(
            name=["--worktree", "-w"],
            help="Run in worktree. Use '-' for selection, or specify branch name.",
        ),
    ] = None,
    resume: Annotated[
        bool | None,
        Parameter(
            name=["--resume", "-r"],
            negative=["--no-resume", "-R"],
            help="Resume most recent conversation (default from config).",
        ),
    ] = None,
    restart: Annotated[
        bool,
        Parameter(
            help=(
                "Auto-restart the agent after it exits. "
                "Implies -w=- for worktree selection."
            )
        ),
    ] = False,
    restart_confirmation: Annotated[
        bool,
        Parameter(
            name="--restart-confirmation",
            help="Wait for Enter before each restart. Implies --restart.",
        ),
    ] = False,
    restart_delay: Annotated[
        float,
        Parameter(
            name="--restart-delay",
            help="Delay in seconds between restarts (default: 0).",
        ),
    ] = 0,
    skip_permissions: Annotated[
        bool | None,
        Parameter(
            name=["--skip-permissions", "-s"],
            negative=["--no-skip-permissions", "-S"],
            help="Skip permission prompts (default from config).",
        ),
    ] = None,
    profile: Annotated[
        str | None,
        Parameter(
            name=["--profile", "-p"],
            env_var="HIVE_AGENT_PROFILE",
            help=(
                "Agent config-dir profile to use. Redirects the agent's config/history "
                "to $XDG_CONFIG_HOME/hive/profiles/<agent>/<profile>. "
                "Omit (or use 'default') to use the agent's default config dir."
            ),
        ),
    ] = None,
    auto_select: Annotated[
        str | None,
        Parameter(
            name="--auto-select",
            help=(
                "Auto-select branch after timeout. Shows picker but auto-proceeds. "
                "Use '-' for repo's default branch. Any key cancels timer."
            ),
        ),
    ] = None,
    args: Annotated[
        tuple[str, ...],
        Parameter(
            allow_leading_hyphen=True,
            help="Additional arguments to pass to the agent.",
        ),
    ] = (),
):
    """Run AI coding agent in current directory.

    Auto-detects available AI agent based on agents.order in hive config.
    Changes to git root if available before launching the agent.

    Examples:
        hive run                      # Auto-detect and run agent
        hive run --resume             # Resume most recent conversation
        hive run -r                   # Short form of --resume
        hive run --restart            # Interactive worktree selection + auto-restart
        hive run -r --restart         # Resume with auto-restart in selected worktree
        hive run --restart -w main    # Auto-restart in main repo (skip selection)
        hive run --restart -w feat    # Auto-restart in specific worktree (no re-select)
        hive run --restart --restart-delay 2  # Add 2s delay between restarts
        hive run --restart-confirmation       # Wait for Enter before each restart
        hive run -w=-                 # Interactive worktree selection, then run
        hive run -w feature-123       # Run in specific worktree
        hive run --auto-select main   # Show picker, auto-select main after timeout
        hive run --auto-select -      # Auto-select repo's default branch
        hive run -s                   # Skip permission prompts
        hive run -a claude -s         # Use Claude with --dangerously-skip-permissions
        hive run --help               # Pass --help to the agent
        hive run -a claude            # Use Claude specifically
        HIVE_AGENT=gemini hive run    # Use Gemini via env var
        hive run -p work              # Use 'work' config profile for the agent
        hive run --profile work       # Same, long form
    """
    # Load config once at the start
    config = get_settings()

    # Determine resume behavior from config if not explicitly set
    if resume is None:
        # Use worktrees.resume if in worktree mode, otherwise resume.enabled
        if worktree is not None:
            resume = config.worktrees.resume
        else:
            resume = config.resume.enabled

    # Resolve skip-permissions: CLI flag > env var > config → write to runtime settings
    rt = get_runtime_settings()
    if skip_permissions is not None:
        # CLI flag explicitly set — write to runtime settings
        rt.skip_permissions = skip_permissions
    elif not rt.skip_permissions:
        # No CLI flag, no env var — fall back to config
        rt.skip_permissions = config.worktrees.skip_permissions

    # Resolve profile: CLI flag > HIVE_AGENT_PROFILE env var
    # (already in rt.agent_profile if set via env)
    if profile is not None:
        # Normalize "default" (or empty string) to None (passthrough semantics)
        rt.agent_profile = profile if profile and profile != "default" else None

    # Initial agent detection (for validation and pane name)
    # This may be overridden by HIVE_AGENT set during worktree selection (Ctrl+A)
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

    # Check if we need resume logic (agent has resume_args configured)
    agent_config = get_agent_config(detected.name) if resume else None
    has_resume_args = agent_config and agent_config.resume_args

    # Check if we need skip-permissions logic
    has_skip_permissions = rt.skip_permissions

    # Check if user explicitly specified -a/--agent on command line
    # (as opposed to it being populated from HIVE_AGENT env var)
    cli_specified_agent = any(
        arg.startswith("-a") or arg.startswith("--agent") for arg in sys.argv
    )

    # Create a dynamic command runner that re-detects agent on each run
    # This respects HIVE_AGENT changes from the interactive picker (Ctrl+A)
    def run_with_dynamic_agent(command: list[str]) -> int:
        """Run agent, re-detecting from HIVE_AGENT env var."""
        # If user explicitly passed -a/--agent, honor that choice
        # Otherwise, re-read HIVE_AGENT from environment (may be changed by Ctrl+A)
        preferred = agent if cli_specified_agent else None
        result = _detect_current_agent(preferred, args)
        if result is None:
            error("No agent available")
            return 1

        current_agent_name, current_cmd = result

        # Re-read skip-permissions (may be toggled by Ctrl+S in picker)
        # Get skip-permissions args and extra_args for current agent
        skip_perm_args: list[str] = []
        agent_extra_args: list[str] = []
        current_agent_config = get_agent_config(current_agent_name)
        if current_agent_config:
            if get_runtime_settings().skip_permissions:
                skip_perm_args = current_agent_config.skip_permissions_args
            agent_extra_args = current_agent_config.extra_args

        extra_dir_args = get_extra_dirs_args(current_agent_name)

        # Handle resume logic if enabled and agent has resume args
        if resume:
            current_agent_config = get_agent_config(current_agent_name)
            if current_agent_config and current_agent_config.resume_args:
                # Try resume first
                resume_cmd = [
                    current_cmd[0],
                    *current_agent_config.resume_args,
                    *skip_perm_args,
                    *agent_extra_args,
                    *extra_dir_args,
                    *args,
                ]
                child_env = get_runtime_settings().build_child_env()
                child_env.update(
                    resolve_profile_env(
                        current_agent_name,
                        get_runtime_settings().agent_profile,
                    )
                )
                result = subprocess.run(
                    resume_cmd,
                    stderr=subprocess.DEVNULL,
                    env=child_env,
                )
                if result.returncode == 0:
                    return 0
                # Resume failed, fall back to base command

        # Build final command with skip-permissions, extra_args, and extra-dirs
        injected = [*skip_perm_args, *agent_extra_args, *extra_dir_args]
        if injected:
            final_cmd = [
                current_cmd[0],
                *injected,
                *current_cmd[1:],
            ]
        else:
            final_cmd = current_cmd

        # Run the agent; inject profile env vars (config-dir redirect + creds)
        child_env = get_runtime_settings().build_child_env()
        child_env.update(
            resolve_profile_env(
                current_agent_name,
                get_runtime_settings().agent_profile,
            )
        )
        result = subprocess.run(final_cmd, env=child_env)
        return result.returncode

    # Compute extra-dirs args and extra_args for initial agent
    initial_extra_dirs = get_extra_dirs_args(detected.name)
    has_extra_dirs = bool(initial_extra_dirs)
    init_agent_config = get_agent_config(detected.name)
    initial_agent_extra_args = init_agent_config.extra_args if init_agent_config else []
    has_agent_extra_args = bool(initial_agent_extra_args)

    # Use dynamic runner when:
    # - restart/restart_confirmation mode (needs restart loop)
    # - interactive worktree selection (-w=-): the picker can mutate agent,
    #   profile, skip-permissions, and workdir after use_dynamic_runner is computed,
    #   so we must always use the dynamic runner when selection is in play.
    # - resume is enabled AND agent has resume_args (needs retry logic)
    # - skip-permissions is enabled (needs arg injection)
    # - extra_args configured (needs arg injection per agent)
    # - extra_dirs configured (needs arg injection per agent)
    # - profile is active upfront (via --profile flag or HIVE_AGENT_PROFILE env)
    has_profile = bool(rt.agent_profile)
    is_interactive_selection = worktree == "-"
    use_dynamic_runner = (
        restart
        or restart_confirmation
        or is_interactive_selection
        or has_resume_args
        or has_skip_permissions
        or has_agent_extra_args
        or has_extra_dirs
        or has_profile
    )

    # Determine auto_select settings: CLI overrides config
    auto_select_branch = auto_select
    auto_select_timeout = config.worktrees.auto_select.timeout
    if auto_select_branch is None and config.worktrees.auto_select.enabled:
        auto_select_branch = config.worktrees.auto_select.branch

    # Build initial command with skip-permissions, extra_args, and extra-dirs
    initial_skip_args: list[str] = []
    if rt.skip_permissions:
        if init_agent_config:
            initial_skip_args = init_agent_config.skip_permissions_args
    injected_args = [*initial_skip_args, *initial_agent_extra_args, *initial_extra_dirs]
    if injected_args:
        initial_cmd = [detected.command, *injected_args, *args]
    else:
        initial_cmd = [detected.command, *args]

    # Use exec_runner for worktree selection and restart loop
    exit_code = run_in_worktree(
        initial_cmd,  # Initial command (may be overridden)
        worktree=worktree,
        restart=restart,
        restart_confirmation=restart_confirmation,
        restart_delay=restart_delay,
        use_execvp=not use_dynamic_runner,
        run_command=run_with_dynamic_agent if use_dynamic_runner else None,
        restart_message="[hive] Agent exited. Restarting... (Ctrl+C to stop)",
        pane_name_prefix=_get_pane_name_info(detected.name)[0],
        layout_has_base_name=_get_pane_name_info(detected.name)[1],
        worktrees_enabled=config.worktrees.enabled,
        auto_select_branch=auto_select_branch,
        auto_select_timeout=auto_select_timeout,
    )
    sys.exit(exit_code)
