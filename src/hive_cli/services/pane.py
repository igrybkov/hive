"""`hive run`'s pane: identity, the pane-state server, the agent child, and the
worktree-selection restart loop around them.

Inside a multiplexer, `open_pane_context()` gives the process its pane
identity (self-assigned c<N> + label when started outside the layout), starts
the PaneStateServer on the pane socket and keeps the pane title and tab name
in sync through the server's coalesced on_change. Outside a multiplexer the
context is a no-op and the A0 behaviour is unchanged (execvpe for single
runs). `run_agent` keeps hive alive as the agent's parent so the socket
stays served; that is why it is Popen+wait rather than execvpe.

The restart loop, workdir-override plumbing and resume-then-fallback runner
moved here from commands/exec_runner.py / commands/run.py in A0; printing
and prompting are `clear_screen`/`progress`/`confirm_restart` callbacks and
the picker is the `pick` callable, so this module never imports ui/.
`subprocess` stays here (not core.proc.run, which always captures): the agent
child must inherit the tty.
"""

from __future__ import annotations

import functools
import os
import signal
import subprocess
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from ..agents.profiles import resolve_profile_env
from ..config import get_runtime_settings, get_settings
from ..core import paths, trace
from ..git import expand_path, get_main_repo
from ..mux import get_mux
from ..mux.base import Mux
from ..state import client
from ..state.pane_state import (
    PaneState,
    compose_tab_name,
    label_for,
    next_free_pane_id,
    title_for,
)
from ..state.server import PaneStateServer

CommandRunner = Callable[[list[str]], int]
Pick = Callable[..., tuple[bool, str | None]]


def _noop(*_args: object, **_kwargs: object) -> None:
    return None


# ---------------------------------------------------------------------------
# Pane identity and state server
# ---------------------------------------------------------------------------


@dataclass
class PaneContext:
    """What this process knows about the pane it runs in.

    Outside a multiplexer (or for commands that are not agent panes, see
    `null_context`) `server` is None and `update`/`close` do nothing.
    """

    mux: Mux | None
    session: str
    pane_id: str
    sock_path: Path | None
    server: PaneStateServer | None
    restore_signals: Callable[[], None] = _noop

    def update(self, **fields: object) -> None:
        if self.server:
            self.server.update(**fields)

    def close(self) -> None:
        if self.server:
            self.server.close()
        self.restore_signals()


def null_context() -> PaneContext:
    """A context that serves nothing: for `hive wt exec` and tests."""
    return PaneContext(None, "", "", None, None)


def open_pane_context(
    *, mux: Mux | None = None, labels: list[str] | None = None
) -> PaneContext:
    """Inside a multiplexer pane: assign identity, start the server.

    Outside a multiplexer: a no-op context. A `hive run` started on demand
    (no HIVE_PANE_ID) takes the first pane number no live `hive run` in the
    session holds, and that number's label from `labels`
    (default: zellij.pane_labels).
    """
    mux = mux if mux is not None else get_mux()
    rt = get_runtime_settings()
    session, pane_id = (
        (mux.own_session() or "", mux.own_pane_id() or "") if mux else ("", "")
    )
    if not (mux and session and pane_id):
        return PaneContext(mux, session, pane_id, None, None)
    session_dir = paths.session_sock_dir(session)
    session_dir.mkdir(parents=True, exist_ok=True)
    others = client.list_states(session_dir)
    if not rt.pane_id:  # started on demand: self-assign c<N> and its label
        number = next_free_pane_id([s.hive_pane_id for s in others])
        rt.pane_id = str(number)
        if labels is None:
            labels = get_settings().zellij.pane_labels
        rt.pane_label = rt.pane_label or label_for(number, labels)
    tab_id = next((p.tab_id for p in mux.list_panes() if p.id == pane_id), "")
    state = PaneState(
        session=session,
        pane_id=pane_id,
        tab_id=tab_id,
        hive_pane_id=rt.pane_id_int,
        label=rt.pane_label or "",
        agent=rt.agent or "",
        profile=rt.agent_profile or "",
        hive_pid=os.getpid(),
        status_since=time.time(),
    )
    sock = paths.pane_sock(session, pane_id)
    rt.pane_sock = str(sock)
    server = PaneStateServer(
        sock, state, on_change=lambda s: _on_change(mux, session_dir, s)
    )
    server.start()
    restore = _install_signal_handlers(server)
    return PaneContext(mux, session, pane_id, sock, server, restore)


def _on_change(mux: Mux, session_dir: Path, state: PaneState) -> None:
    """Rename the pane, and the tab from every live pane in it (timer thread)."""
    mux.rename_pane(state.pane_id, title_for(state))
    if state.tab_id:
        siblings = [
            s
            for s in client.list_states(session_dir)
            if s.tab_id == state.tab_id and s.pane_id != state.pane_id
        ]
        mux.rename_tab(state.tab_id, compose_tab_name([*siblings, state]))


def _install_signal_handlers(server: PaneStateServer) -> Callable[[], None]:
    """SIGTERM/SIGHUP: close the server (unlink the socket), then die as usual.

    Returns a callable restoring the previous handlers. Only the main thread
    may install handlers; elsewhere this is a no-op.
    """
    if threading.current_thread() is not threading.main_thread():
        return _noop

    def handler(signum: int, _frame: object) -> None:
        server.close()
        signal.signal(signum, signal.SIG_DFL)
        os.kill(os.getpid(), signum)

    previous = {
        signum: signal.signal(signum, handler)
        for signum in (signal.SIGTERM, signal.SIGHUP)
    }

    def restore() -> None:
        for signum, old in previous.items():
            signal.signal(signum, old)

    return restore


# ---------------------------------------------------------------------------
# Running the agent
# ---------------------------------------------------------------------------


def run_agent(
    argv: Sequence[str],
    env: dict[str, str],
    ctx: PaneContext | None,
    *,
    cwd: str | Path | None = None,
    stderr: int | None = None,
) -> int:
    """Popen + wait so the pane server stays up; returns the exit code.

    The tty forwards Ctrl+C to the child, whose job it is to handle the
    first one; hive only terminates the child on the second.
    """
    child = subprocess.Popen(argv, env=env, cwd=cwd, stderr=stderr)
    trace.mark("agent_started")
    if ctx:
        ctx.update(status="running", agent_pid=child.pid)
    interrupts = 0
    while True:
        try:
            code = child.wait()
            break
        except KeyboardInterrupt:
            interrupts += 1
            if interrupts >= 2:
                child.terminate()
    if ctx:
        ctx.update(status="exited", agent_pid=0)
    return code


def default_run_command(command: list[str], ctx: PaneContext | None = None) -> int:
    """Default command runner: run and wait, inheriting the tty."""
    return run_agent(command, get_runtime_settings().build_child_env(), ctx)


def run_with_resume(
    current_cmd,
    current_agent_name,
    current_agent_config,
    skip_perm_args,
    agent_extra_args,
    extra_dir_args,
    args,
    resume,
    ctx: PaneContext | None = None,
) -> int:
    """Try resume_args first when enabled/configured, else run the base command."""
    if resume and current_agent_config and current_agent_config.resume_args:
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
        if run_agent(resume_cmd, child_env, ctx, stderr=subprocess.DEVNULL) == 0:
            return 0
        # Resume failed, fall back to base command

    # Build final command with skip-permissions, extra_args, and extra-dirs
    injected = [*skip_perm_args, *agent_extra_args, *extra_dir_args]
    if injected:
        final_cmd = [current_cmd[0], *injected, *current_cmd[1:]]
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
    return run_agent(final_cmd, child_env, ctx)


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


# ---------------------------------------------------------------------------
# Worktree-selection loop
# ---------------------------------------------------------------------------


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


def _publish_starting(ctx: PaneContext, branch: str | None) -> None:
    ctx.update(status="starting", branch=branch or "", worktree_path=os.getcwd())


def _stop_requested(ctx: PaneContext) -> bool:
    return ctx.server is not None and ctx.server.stop_requested.is_set()


def _begin_iteration(ctx: PaneContext) -> None:
    """Reset per-iteration state: restart flag, Ctrl+W workdir override."""
    if ctx.server is not None:
        ctx.server.restart_requested.clear()
    # Workdir override (Ctrl+W) is session-scoped -- must be re-picked
    # on each iteration so a previous run's choice doesn't leak.
    rt = get_runtime_settings()
    rt.workdir = None
    rt.workdir_extras_override = None
    ctx.update(status="selecting")


def _restart_loop(
    command: list[str],
    pick: Pick,
    *,
    ctx: PaneContext,
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
            _begin_iteration(ctx)
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
            _publish_starting(ctx, selected_branch)

            clear_screen()
            runner(command)
            if _stop_requested(ctx):
                break
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
    ctx: PaneContext,
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
    ctx.update(status="selecting")
    success, selected_branch = pick(
        worktree,
        preselect_branch,
        auto_select_branch=auto_select_branch,
        auto_select_timeout=auto_select_timeout,
    )
    if not success:
        return 1

    on_branch_selected(selected_branch)
    _publish_starting(ctx, selected_branch)
    clear_screen()

    if use_execvp and run_command is None and ctx.server is None:
        # Direct exec, replacing current process (only if no custom runner and
        # no pane server to keep alive).
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
    runner: CommandRunner | None = None,
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
    ctx: PaneContext | None = None,
) -> int:
    """Run command in a worktree, optionally looping with --restart.

    Args:
        command: Command and arguments to execute.
        pick: Callable resolving (and chdir-ing into) a worktree: takes
            (worktree, last_selected_branch, *, auto_select_branch,
            auto_select_timeout) and returns (success, selected_branch).
        runner: Command runner used when not exec-replacing the process.
            Defaults to `default_run_command` bound to `ctx`.
        worktree: Branch name, '-' for interactive, None for git root.
        restart: Whether to auto-restart in a loop.
        restart_confirmation: Whether to wait for Enter before each restart.
            Implies restart=True.
        restart_delay: Seconds to wait between restarts.
        preselect_branch: Branch to pre-select in interactive mode.
        use_execvp: Use execvp for single run (replaces process). Ignored
            while a pane server is running (hive must stay the agent's parent).
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
        ctx: The pane context; opened here when None and always closed on
            return, so the pane socket disappears when the loop ends.

    Returns:
        Exit code (only if restart=False and use_execvp=False).
    """
    ctx = ctx if ctx is not None else open_pane_context()
    if runner is None:
        runner = functools.partial(default_run_command, ctx=ctx)

    # --restart-confirmation implies --restart
    if restart_confirmation:
        restart = True

    # --restart implies -w - (interactive selection) only when no worktree specified
    # and worktrees are enabled in config
    if restart and worktree is None and worktrees_enabled:
        worktree = "-"

    try:
        if restart:
            return _restart_loop(
                command,
                pick,
                ctx=ctx,
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
            ctx=ctx,
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
    finally:
        ctx.close()
