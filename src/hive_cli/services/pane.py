"""Worktree-selection restart loop and workdir-override plumbing.

Moved from commands/exec_runner.py (A0 step 6). Printing (screen clears,
restart messages, the restart-confirmation prompt) becomes
clear_screen/progress/confirm_restart callback parameters, following the
same pattern as git/analysis.py:simulate_merge's `progress` callback --
the command passes real ui.console methods; the printed text is
identical. Likewise, Zellij pane-renaming becomes an on_branch_selected
callback instead of an import of utils.zellij (that logic's permanent
home is mux/state, Step 9 -- not worth a temporary cross-layer import
here).

`select_and_change_to_worktree` stays resident in commands/exec_runner.py:
it calls ui/pickers/worktrees.py:pick_worktree (the wt.py pass's renamed,
complexipy-clean `_interactive_ensure`). run_in_worktree passes it in as
`pick`.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from pathlib import Path

from ..config import get_runtime_settings, get_settings
from ..git import expand_path, get_main_repo

CommandRunner = Callable[[list[str]], int]
Pick = Callable[..., tuple[bool, str | None]]


def _noop(*_args: object, **_kwargs: object) -> None:
    return None


def apply_workdir_override(primary_path: Path) -> None:
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


def _select_for_iteration(
    pick: Pick,
    *,
    worktree: str | None,
    last_selected_branch: str | None,
    auto_select_branch: str | None,
    auto_select_timeout: float,
    first_iteration: bool,
    on_branch_selected: Callable[[str | None], None],
) -> tuple[bool, str | None]:
    """Resolve the worktree for one restart-loop iteration.

    Re-selects interactively when worktree is '-' or nothing is pinned yet
    (only auto-selecting on the first iteration); otherwise just re-affirms
    the existing branch.
    """
    if worktree == "-" or last_selected_branch is None:
        current_auto_select = auto_select_branch if first_iteration else None
        success, selected_branch = pick(
            worktree,
            last_selected_branch,
            auto_select_branch=current_auto_select,
            auto_select_timeout=auto_select_timeout,
        )
        if success:
            on_branch_selected(selected_branch)
        return success, selected_branch

    success, _ = pick(worktree, last_selected_branch)
    if success:
        on_branch_selected(last_selected_branch)
    return success, last_selected_branch


def _restart_loop(
    command: list[str],
    pick: Pick,
    *,
    runner: CommandRunner,
    restart_confirmation: bool,
    restart_delay: float,
    restart_message: str,
    worktree: str | None,
    last_selected_branch: str | None,
    auto_select_branch: str | None,
    auto_select_timeout: float,
    on_branch_selected: Callable[[str | None], None],
    clear_screen: Callable[[], None],
    progress: Callable[[str], None],
    confirm_restart: Callable[[], None],
) -> int:
    """Re-select (or re-affirm) a worktree and re-run command until cancelled."""
    first_iteration = True

    try:
        while True:
            # Workdir override (Ctrl+W) is session-scoped — must be re-picked
            # on each iteration so a previous run's choice doesn't leak.
            rt = get_runtime_settings()
            rt.workdir = None
            rt.workdir_extras_override = None

            success, selected_branch = _select_for_iteration(
                pick,
                worktree=worktree,
                last_selected_branch=last_selected_branch,
                auto_select_branch=auto_select_branch,
                auto_select_timeout=auto_select_timeout,
                first_iteration=first_iteration,
                on_branch_selected=on_branch_selected,
            )
            first_iteration = False
            if not success:
                break
            last_selected_branch = selected_branch

            clear_screen()
            runner(command)
            progress(f"\n[dim]{restart_message}[/]")
            if restart_confirmation:
                confirm_restart()
            if restart_delay > 0:
                time.sleep(restart_delay)
    except KeyboardInterrupt:
        progress("\n[dim][hive] Stopped.[/]")
        return 0
    return 0


def _single_run(
    command: list[str],
    pick: Pick,
    *,
    runner: CommandRunner,
    run_command: CommandRunner | None,
    use_execvp: bool,
    worktree: str | None,
    preselect_branch: str | None,
    auto_select_branch: str | None,
    auto_select_timeout: float,
    on_branch_selected: Callable[[str | None], None],
    clear_screen: Callable[[], None],
) -> int:
    """Select a worktree once and run command, replacing the process if possible."""
    success, selected_branch = pick(
        worktree,
        preselect_branch,
        auto_select_branch=auto_select_branch,
        auto_select_timeout=auto_select_timeout,
    )
    if not success:
        return 1

    on_branch_selected(selected_branch)
    clear_screen()

    if use_execvp and run_command is None:
        # Direct exec, replacing current process (only if no custom runner).
        # Check if HIVE_AGENT was changed during worktree selection (Ctrl+A)
        # and rebuild command if needed.
        final_command = command
        rt = get_runtime_settings()
        if rt.agent and command and command[0] != rt.agent:
            # Agent was changed - rebuild command with new agent.
            # Keep original args (everything after the command name).
            final_command = [rt.agent, *command[1:]]
        os.execvpe(final_command[0], final_command, rt.build_child_env())
        # execvp doesn't return, but for type checker:
        return 0
    # Use subprocess/custom runner.
    return runner(command)


def run_loop(
    command: list[str],
    pick: Pick,
    *,
    runner: CommandRunner,
    worktree: str | None = None,
    restart: bool = False,
    restart_confirmation: bool = False,
    restart_delay: float = 0,
    preselect_branch: str | None = None,
    use_execvp: bool = True,
    run_command: CommandRunner | None = None,
    restart_message: str = "[hive] Command exited. Restarting... (Ctrl+C to stop)",
    worktrees_enabled: bool = True,
    auto_select_branch: str | None = None,
    auto_select_timeout: float = 3.0,
    on_branch_selected: Callable[[str | None], None] = _noop,
    clear_screen: Callable[[], None] = _noop,
    progress: Callable[[str], None] = _noop,
    confirm_restart: Callable[[], None] = _noop,
) -> int:
    """Run command in a worktree, optionally looping with --restart.

    Args:
        command: Command and arguments to execute.
        pick: Callable resolving (and chdir-ing into) a worktree: takes
            (worktree, last_selected_branch, *, auto_select_branch,
            auto_select_timeout) and returns (success, selected_branch).
        runner: Command runner used when not exec-replacing the process.
        worktree: Branch name, '-' for interactive, None for git root.
        restart: Whether to auto-restart in a loop.
        restart_confirmation: Whether to wait for Enter before each restart.
            Implies restart=True.
        restart_delay: Seconds to wait between restarts.
        preselect_branch: Branch to pre-select in interactive mode.
        use_execvp: Use execvp for single run (replaces process).
        run_command: Custom command runner, if any (None means `runner` is
            the default runner, allowing the execvp fast path).
        restart_message: Message to display when restarting.
        worktrees_enabled: If False, --restart won't imply -w - for worktree
            selection. Controlled by worktrees.enabled in config.
        auto_select_branch: Branch to auto-select after timeout in interactive mode.
            Use "-" for repo's default branch. Any keypress cancels.
        auto_select_timeout: Seconds before auto-selection (default 3.0).
        on_branch_selected: Called with the selected branch after each pick.
        clear_screen: Called before each command run.
        progress: Called with a Rich-markup message to display.
        confirm_restart: Called (and expected to block) before each restart
            when restart_confirmation is set.

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

    if restart:
        return _restart_loop(
            command,
            pick,
            runner=runner,
            restart_confirmation=restart_confirmation,
            restart_delay=restart_delay,
            restart_message=restart_message,
            worktree=worktree,
            last_selected_branch=preselect_branch,
            auto_select_branch=auto_select_branch,
            auto_select_timeout=auto_select_timeout,
            on_branch_selected=on_branch_selected,
            clear_screen=clear_screen,
            progress=progress,
            confirm_restart=confirm_restart,
        )

    return _single_run(
        command,
        pick,
        runner=runner,
        run_command=run_command,
        use_execvp=use_execvp,
        worktree=worktree,
        preselect_branch=preselect_branch,
        auto_select_branch=auto_select_branch,
        auto_select_timeout=auto_select_timeout,
        on_branch_selected=on_branch_selected,
        clear_screen=clear_screen,
    )
