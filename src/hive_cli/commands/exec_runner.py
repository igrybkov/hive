"""Core execution logic for running commands in worktrees."""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from pathlib import Path

from rich.console import Console

from ..config import get_runtime_settings
from ..git import get_git_root, get_main_repo, get_worktree_path
from ..mux.zellij.backend import set_pane_branch
from ..services import pane
from ..ui.console import error, format_yellow
from ..ui.pickers.worktrees import pick_worktree
from ..ui.tty import is_interactive

console = Console()

# Type alias for command runner function
CommandRunner = Callable[[list[str]], int]


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
        result = pick_worktree(
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
        pane.apply_workdir_override(primary)
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
        pane.apply_workdir_override(worktree_path)
        return True, worktree
    else:
        # Change to git root if available (default behavior)
        git_root = get_git_root()
        if git_root:
            os.chdir(git_root)
        return True, None


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

    def on_branch_selected(branch: str | None) -> None:
        _update_zellij_pane_name(
            pane_name_prefix, branch, layout_has_base_name=layout_has_base_name
        )

    def confirm_restart() -> None:
        console.print("[dim][hive] Press Enter to restart...[/]")
        input()

    return pane.run_loop(
        command,
        select_and_change_to_worktree,
        runner=run_command or pane.default_run_command,
        worktree=worktree,
        restart=restart,
        restart_confirmation=restart_confirmation,
        restart_delay=restart_delay,
        preselect_branch=preselect_branch,
        use_execvp=use_execvp,
        run_command=run_command,
        restart_message=restart_message,
        worktrees_enabled=worktrees_enabled,
        auto_select_branch=auto_select_branch,
        auto_select_timeout=auto_select_timeout,
        on_branch_selected=on_branch_selected,
        clear_screen=console.clear,
        progress=console.print,
        confirm_restart=confirm_restart,
    )
