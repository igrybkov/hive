"""Run command - launch AI coding agent."""

from __future__ import annotations

import sys
from typing import Annotated

from cyclopts import App, Parameter

from ..agents import detect_agent
from ..agents.launch import get_extra_dirs_args, hive_hook_path, hook_args
from ..config import (
    KNOWN_AGENTS,
    get_agent_config,
    get_runtime_settings,
    get_settings,
)
from ..core.errors import HiveError
from ..git import expand_path, get_main_repo
from ..services import pane
from ..ui.console import error, format_yellow
from ..ui.flows.worktrees import run_in_worktree


def _resolved_extra_dirs() -> list[str]:
    """Extra-dirs override (Ctrl+W) or configured extra_dirs, as resolved paths.

    Session override (set by Ctrl+W in the picker) wins over configured
    dirs. It contains already-resolved absolute paths plus the displaced
    primary; settings.extra_dirs entries may contain "~" or be relative to
    the main repo, so those still need expand_path.
    """
    override = get_runtime_settings().workdir_extras_override
    if override is not None:
        return override
    dirs = get_settings().extra_dirs
    if not dirs:
        return []
    main_repo = get_main_repo()
    return [str(expand_path(d, main_repo)) for d in dirs]


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


def _resolve_resume_flag(config, worktree: str | None, resume: bool | None) -> bool:
    """Determine resume behavior from config if not explicitly set on the CLI."""
    if resume is not None:
        return resume
    # Use worktrees.resume if in worktree mode, otherwise resume.enabled
    if worktree is not None:
        return config.worktrees.resume
    return config.resume.enabled


def _apply_skip_permissions_and_profile(rt, config, skip_permissions, profile) -> None:
    """Resolve skip-permissions and profile onto runtime settings (mutates rt).

    skip-permissions: CLI flag > env var > config.
    profile: CLI flag > HIVE_AGENT_PROFILE env var (already in rt.agent_profile
    if set via env); "default"/empty string normalize to None (passthrough).
    """
    if skip_permissions is not None:
        rt.skip_permissions = skip_permissions
    elif not rt.skip_permissions:
        rt.skip_permissions = config.worktrees.skip_permissions

    if profile is not None:
        rt.agent_profile = profile if profile and profile != "default" else None


def _require_detected_agent(agent: str | None):
    """Detect the agent for validation/pane naming, or error and exit(1)."""
    detected = detect_agent(preferred=agent)
    if detected is not None:
        return detected
    if agent:
        error(
            f"Agent '{format_yellow(agent)}' is not available. "
            f"Is it installed and in your PATH?"
        )
    else:
        agents_list = ", ".join(KNOWN_AGENTS)
        error(f"No AI coding agent found. Install one of: {agents_list}")
    sys.exit(1)


def _make_dynamic_agent_runner(
    agent, args, resume, cli_specified_agent, ctx, hive_hook
):
    """Build the run_command callable the restart loop invokes.

    Re-detects the agent (and re-reads skip-permissions/extra args/extra
    dirs/hook args) on every call, so it respects HIVE_AGENT/Ctrl+A/Ctrl+S
    changes made by the interactive picker between restarts. `hive_hook` is
    resolved once up front (see `run()`); only whether/how it applies to the
    *current* agent needs re-checking each iteration.
    """

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

        # Ctrl+A can switch agents without restarting hive; keep the pane
        # title's [agent] segment in sync with what's about to run.
        ctx.update(agent=current_agent_name)

        # Re-read skip-permissions (may be toggled by Ctrl+S in picker)
        # Get skip-permissions args and extra_args for current agent
        skip_perm_args: list[str] = []
        agent_extra_args: list[str] = []
        current_agent_config = get_agent_config(current_agent_name)
        if current_agent_config:
            if get_runtime_settings().skip_permissions:
                skip_perm_args = current_agent_config.skip_permissions_args
            agent_extra_args = current_agent_config.extra_args

        extra_dir_args = get_extra_dirs_args(current_agent_name, _resolved_extra_dirs())
        current_hook_args = hook_args(
            current_agent_name, hive_hook=hive_hook, settings=get_settings()
        )

        return pane.run_with_resume(
            current_cmd,
            current_agent_name,
            current_agent_config,
            skip_perm_args,
            agent_extra_args,
            extra_dir_args,
            current_hook_args,
            args,
            resume,
            ctx=ctx,
        )

    return run_with_dynamic_agent


def _compute_use_dynamic_runner(
    rt,
    worktree,
    restart,
    restart_confirmation,
    has_resume_args,
    has_agent_extra_args,
    has_extra_dirs,
    has_hook_args,
) -> bool:
    """True when the restart loop needs the dynamic re-detecting runner.

    Use dynamic runner when:
    - restart/restart_confirmation mode (needs restart loop)
    - interactive worktree selection (-w=-): the picker can mutate agent,
      profile, skip-permissions, and workdir after this is computed, so we
      must always use the dynamic runner when selection is in play.
    - resume is enabled AND agent has resume_args (needs retry logic)
    - skip-permissions is enabled (needs arg injection)
    - extra_args configured (needs arg injection per agent)
    - extra_dirs configured (needs arg injection per agent)
    - hook_args configured (needs arg injection per agent; the execvp fast
      path only swaps the binary name on a Ctrl+A agent switch, so a
      baked-in claude `--settings {...}` would otherwise be handed to codex)
    - profile is active upfront (via --profile flag or HIVE_AGENT_PROFILE env)
    """
    return (
        restart
        or restart_confirmation
        or worktree == "-"
        or has_resume_args
        or rt.skip_permissions
        or has_agent_extra_args
        or has_extra_dirs
        or has_hook_args
        or bool(rt.agent_profile)
    )


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
    resume = _resolve_resume_flag(config, worktree, resume)

    rt = get_runtime_settings()
    _apply_skip_permissions_and_profile(rt, config, skip_permissions, profile)

    # Initial agent detection (for validation and pane name)
    # This may be overridden by HIVE_AGENT set during worktree selection (Ctrl+A)
    detected = _require_detected_agent(agent)

    # Check if we need resume logic (agent has resume_args configured)
    agent_config = get_agent_config(detected.name) if resume else None
    has_resume_args = agent_config and agent_config.resume_args

    # Check if user explicitly specified -a/--agent on command line
    # (as opposed to it being populated from HIVE_AGENT env var)
    cli_specified_agent = any(
        arg.startswith("-a") or arg.startswith("--agent") for arg in sys.argv
    )

    # Compute extra-dirs args and extra_args for initial agent
    initial_extra_dirs = get_extra_dirs_args(detected.name, _resolved_extra_dirs())
    has_extra_dirs = bool(initial_extra_dirs)
    init_agent_config = get_agent_config(detected.name)
    initial_agent_extra_args = init_agent_config.extra_args if init_agent_config else []
    has_agent_extra_args = bool(initial_agent_extra_args)

    # Resolve hive-hook once up front (HiveError -> a clear CLI error, not a
    # traceback) and the initial agent's hook args from it.
    hive_hook = ""
    if config.hooks.enabled:
        try:
            hive_hook = hive_hook_path()
        except HiveError as exc:
            error(str(exc))
            sys.exit(exc.exit_code)
    initial_hook_args = hook_args(detected.name, hive_hook=hive_hook, settings=config)
    has_hook_args = bool(initial_hook_args)

    use_dynamic_runner = _compute_use_dynamic_runner(
        rt,
        worktree,
        restart,
        restart_confirmation,
        has_resume_args,
        has_agent_extra_args,
        has_extra_dirs,
        has_hook_args,
    )

    # Determine auto_select settings: CLI overrides config
    auto_select_branch = auto_select
    auto_select_timeout = config.worktrees.auto_select.timeout
    if auto_select_branch is None and config.worktrees.auto_select.enabled:
        auto_select_branch = config.worktrees.auto_select.branch

    # Build initial command with skip-permissions, extra_args, extra-dirs, hooks
    initial_skip_args: list[str] = []
    if rt.skip_permissions:
        if init_agent_config:
            initial_skip_args = init_agent_config.skip_permissions_args
    injected_args = [
        *initial_skip_args,
        *initial_agent_extra_args,
        *initial_extra_dirs,
        *initial_hook_args,
    ]
    if injected_args:
        initial_cmd = [detected.command, *injected_args, *args]
    else:
        initial_cmd = [detected.command, *args]

    # Inside a multiplexer this starts the pane-state server (and self-assigns
    # a pane number when started outside the layout); run_in_worktree closes it.
    ctx = pane.open_pane_context()

    # Create a dynamic command runner that re-detects agent on each run
    # This respects HIVE_AGENT changes from the interactive picker (Ctrl+A)
    run_with_dynamic_agent = _make_dynamic_agent_runner(
        agent, args, resume, cli_specified_agent, ctx, hive_hook
    )

    # Worktree selection and restart loop
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
        ctx=ctx,
    )
    sys.exit(exit_code)
