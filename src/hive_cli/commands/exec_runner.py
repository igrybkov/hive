"""Core execution logic for running commands in worktrees."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

from rich.console import Console

from ..config import get_runtime_settings, get_settings
from ..git import expand_path, get_git_root, get_main_repo, get_worktree_path
from ..utils import error, format_yellow, is_interactive
from ..utils.zellij import set_pane_branch
from .wt import _interactive_ensure

console = Console()

# Type alias for command runner function
CommandRunner = Callable[[list[str]], int]


def _apply_workdir_override(primary_path: Path) -> None:
    """If a Ctrl+W workdir override is active, chdir to it and compute the extras list.

    The override replaces the agent's cwd with one of the configured extra_dirs,
    and prepends the displaced primary (worktree path) to the extras list so the
    agent can still reach it. Absolute paths are stored; get_extra_dirs_args
    consumes them verbatim.
    """
    rt = get_runtime_settings()
    if rt.workdir is None:
        return

    main_repo = get_main_repo()
    resolved = [expand_path(d, main_repo) for d in get_settings().extra_dirs]
    # Drop the chosen workdir from the extras; prepend the displaced primary.
    remaining = [str(p) for p in resolved if p != rt.workdir]
    rt.workdir_extras_override = [str(primary_path), *remaining]
    os.chdir(rt.workdir)


def select_and_change_to_worktree(
    worktree: str | None,
    last_selected_branch: str | None = None,
    auto_select_branch: str | None = None,
    auto_select_timeout: float = 3.0,
) -> tuple[bool, str | None]:
    """Select worktree and change to it.

    Args:
        worktree: Branch name, '-' for interactive, or None for git root.
        last_selected_branch: Branch to pre-select in interactive mode.
        auto_select_branch: Branch to auto-select after timeout in interactive mode.
            Use "-" for repo's default branch. Any keypress cancels.
        auto_select_timeout: Seconds before auto-selection (default 3.0).

    Returns:
        Tuple of (success, selected_branch). success is False if user cancelled.
        selected_branch is the branch that was selected (for tracking across restarts).
    """
    if worktree == "-":
        # Interactive selection
        if not is_interactive():
            error("Interactive mode required for worktree selection")
            sys.exit(1)
        agent_num = get_runtime_settings().pane_id_int
        result = _interactive_ensure(
            agent_num=agent_num,
            preselect_branch=last_selected_branch,
            auto_select_branch=auto_select_branch,
            auto_select_timeout=auto_select_timeout,
        )
        if result is None:
            # User cancelled
            return False, None
        path, branch = result
        primary = Path(path)
        os.chdir(primary)
        _apply_workdir_override(primary)
        return True, branch
    elif worktree is not None:
        # Specific branch provided
        if worktree in ("main", "1"):
            worktree_path = get_main_repo()
        else:
            worktree_path = get_worktree_path(worktree)
            if not worktree_path.exists():
                error(
                    f"Worktree for '{format_yellow(worktree)}' does not exist. "
                    f"Create it first with: hive wt create {worktree}"
                )
                sys.exit(1)
        os.chdir(worktree_path)
        _apply_workdir_override(worktree_path)
        return True, worktree
    else:
        # Change to git root if available (default behavior)
        git_root = get_git_root()
        if git_root:
            os.chdir(git_root)
        return True, None


def _default_run_command(command: list[str]) -> int:
    """Default command runner using subprocess."""
    result = subprocess.run(command, env=get_runtime_settings().build_child_env())
    return result.returncode


def _update_zellij_pane_name(
    prefix: str | None, branch: str | None, *, layout_has_base_name: bool = False
) -> None:
    """Update Zellij pane name with branch info.

    Uses the structured title system to update just the branch component.
    The base name ({agent}-{pane_id}) comes from HIVE_AGENT and HIVE_PANE_ID env vars.

    Args:
        prefix: Deprecated. Previously used as pane name prefix.
        branch: Branch/worktree name. If None, branch is cleared.
        layout_has_base_name: Deprecated. Layout base name is no longer used.

    Note:
        The prefix and layout_has_base_name parameters are kept for backwards
        compatibility but are no longer used. The agent name now comes from
        HIVE_AGENT env var, which is set by `hive zellij`.
    """
    set_pane_branch(branch)


def run_in_worktree(
    command: list[str],
    *,
    worktree: str | None = None,
    restart: bool = False,
    restart_confirmation: bool = False,
    restart_delay: float = 0,
    preselect_branch: str | None = None,
    use_execvp: bool = True,
    run_command: CommandRunner | None = None,
    restart_message: str = "[hive] Command exited. Restarting... (Ctrl+C to stop)",
    pane_name_prefix: str | None = None,
    layout_has_base_name: bool = False,
    worktrees_enabled: bool = True,
    auto_select_branch: str | None = None,
    auto_select_timeout: float = 3.0,
) -> int:
    """Execute command in worktree with optional restart loop.

    Args:
        command: Command and arguments to execute.
        worktree: Branch name, '-' for interactive, None for git root.
        restart: Whether to auto-restart in a loop.
        restart_confirmation: Whether to wait for Enter before each restart.
            Implies restart=True.
        restart_delay: Seconds to wait between restarts.
        preselect_branch: Branch to pre-select in interactive mode.
        use_execvp: Use execvp for single run (replaces process).
        run_command: Optional custom command runner function. If provided,
            this function is called with the command list and should return
            an exit code. Useful for implementing retry/resume logic.
        restart_message: Message to display when restarting.
        pane_name_prefix: Prefix for Zellij pane name (e.g., agent name).
            If running in Zellij, pane will be renamed to "{prefix} [{branch}]".
        layout_has_base_name: If True, the Zellij layout already defines the base
            pane name, so only the branch suffix is appended.
        worktrees_enabled: If False, --restart won't imply -w - for worktree
            selection. Controlled by worktrees.enabled in config.
        auto_select_branch: Branch to auto-select after timeout in interactive mode.
            Use "-" for repo's default branch. Any keypress cancels.
        auto_select_timeout: Seconds before auto-selection (default 3.0).

    Returns:
        Exit code (only if restart=False and use_execvp=False).
    """
    # --restart-confirmation implies --restart
    if restart_confirmation:
        restart = True

    # --restart implies -w - (interactive selection) only when no worktree specified
    # and worktrees are enabled in config
    if restart and worktree is None and worktrees_enabled:
        worktree = "-"

    # Track last selected branch for preselection on restart
    last_selected_branch = preselect_branch

    # Determine if we should re-select on each restart
    # Re-select only when worktree is '-' (interactive mode)
    reselect_each_restart = worktree == "-"

    # Use custom runner or default
    runner = run_command or _default_run_command

    # Track if this is the first iteration (for auto-select)
    first_iteration = True

    if restart:
        # Auto-restart loop
        try:
            while True:
                # Workdir override (Ctrl+W) is session-scoped — must be re-picked
                # on each iteration so a previous run's choice doesn't leak.
                rt = get_runtime_settings()
                rt.workdir = None
                rt.workdir_extras_override = None

                if reselect_each_restart or last_selected_branch is None:
                    # Interactive selection or first run
                    # Only use auto-select on the first iteration
                    current_auto_select = (
                        auto_select_branch if first_iteration else None
                    )
                    success, selected_branch = select_and_change_to_worktree(
                        worktree,
                        last_selected_branch,
                        auto_select_branch=current_auto_select,
                        auto_select_timeout=auto_select_timeout,
                    )
                    first_iteration = False
                    if not success:
                        # User cancelled worktree selection
                        break
                    last_selected_branch = selected_branch
                    _update_zellij_pane_name(
                        pane_name_prefix,
                        selected_branch,
                        layout_has_base_name=layout_has_base_name,
                    )
                else:
                    # Specific worktree - just ensure we're in it
                    success, _ = select_and_change_to_worktree(
                        worktree, last_selected_branch
                    )
                    if not success:
                        break
                    _update_zellij_pane_name(
                        pane_name_prefix,
                        last_selected_branch,
                        layout_has_base_name=layout_has_base_name,
                    )

                console.clear()
                runner(command)
                console.print(f"\n[dim]{restart_message}[/]")
                if restart_confirmation:
                    console.print("[dim][hive] Press Enter to restart...[/]")
                    input()
                if restart_delay > 0:
                    time.sleep(restart_delay)
        except KeyboardInterrupt:
            console.print("\n[dim][hive] Stopped.[/]")
            return 0
        return 0
    else:
        # Single run
        success, selected_branch = select_and_change_to_worktree(
            worktree,
            preselect_branch,
            auto_select_branch=auto_select_branch,
            auto_select_timeout=auto_select_timeout,
        )
        if not success:
            return 1

        _update_zellij_pane_name(
            pane_name_prefix, selected_branch, layout_has_base_name=layout_has_base_name
        )

        console.clear()

        if use_execvp and run_command is None:
            # Direct exec, replacing current process (only if no custom runner)
            # Check if HIVE_AGENT was changed during worktree selection (Ctrl+A)
            # and rebuild command if needed
            final_command = command
            rt = get_runtime_settings()
            if rt.agent and command and command[0] != rt.agent:
                # Agent was changed - rebuild command with new agent
                # Keep original args (everything after the command name)
                final_command = [rt.agent, *command[1:]]
            os.execvpe(final_command[0], final_command, rt.build_child_env())
            # execvp doesn't return, but for type checker:
            return 0
        else:
            # Use subprocess/custom runner
            return runner(command)
