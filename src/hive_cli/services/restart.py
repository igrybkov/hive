"""Restart-loop building blocks shared by `hive run --restart`'s pane loop:
backoff after fast exits and worktree reselection per iteration.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..config import get_runtime_settings

if TYPE_CHECKING:
    from .pane import CommandRunner, PaneContext

Pick = Callable[..., tuple[bool, str | None]]


class RestartFloor:
    """Sleep after fast exits so a crashing agent can't restart in a tight loop.

    1 s after the first exit under 10 s, then 2, 4, capped at 5; a run of
    10 s or longer resets the sequence and costs nothing. `sleep`/`clock`
    default to `time.sleep`/`time.monotonic` (resolved when constructed, so
    tests may patch `time.sleep` or inject fakes).
    """

    LONG_RUN_S = 10.0
    MAX_SLEEP_S = 5.0

    def __init__(
        self,
        sleep: Callable[[float], object] | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._sleep = sleep or time.sleep
        self._clock = clock or time.monotonic
        self._started_at: float | None = None
        self._next = 1.0

    def started(self) -> None:
        self._started_at = self._clock()

    def exited(self) -> None:
        """Sleep if the run that just ended was shorter than 10 s."""
        if self._started_at is None:
            return
        run_length = self._clock() - self._started_at
        self._started_at = None
        if run_length >= self.LONG_RUN_S:
            self._next = 1.0
            return
        self._sleep(self._next)
        self._next = min(self._next * 2, self.MAX_SLEEP_S)


def select_for_iteration(
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


def begin_iteration(ctx: PaneContext) -> None:
    """Reset per-iteration state: restart flag, Ctrl+W workdir override."""
    if ctx.server is not None:
        ctx.server.restart_requested.clear()
    # Workdir override (Ctrl+W) is session-scoped -- must be re-picked
    # on each iteration so a previous run's choice doesn't leak.
    rt = get_runtime_settings()
    rt.workdir = None
    rt.workdir_extras_override = None
    ctx.update(status="selecting")


def is_stop_requested(ctx: PaneContext) -> bool:
    return ctx.server is not None and ctx.server.stop_requested.is_set()


def run_once(
    command: list[str],
    selected_branch: str | None,
    *,
    ctx: PaneContext,
    runner: CommandRunner,
    clear_screen: Callable[[], None],
    progress: Callable[[str], None],
    restart_message: str,
    restart_confirmation: bool,
    confirm_restart: Callable[[], None],
    restart_delay: float,
    restart_floor: RestartFloor,
) -> str:
    """Run `command` once for one restart-loop iteration.

    Returns "stop" (an explicit "stop" came in while the command was
    running) or "continue". A KeyboardInterrupt propagates to the caller.
    """
    ctx.update(
        status="starting", branch=selected_branch or "", worktree_path=os.getcwd()
    )
    clear_screen()
    restart_floor.started()
    runner(command)
    if is_stop_requested(ctx):
        return "stop"
    progress(f"\n[dim]{restart_message}[/]")
    restart_floor.exited()
    if restart_confirmation:
        confirm_restart()
    if restart_delay > 0:
        time.sleep(restart_delay)
    return "continue"


@dataclass
class RestartConfig:
    """Everything one restart-loop iteration needs that doesn't change
    across iterations (`last_selected_branch`/`first_iteration` do) --
    bundled so `loop_step` isn't a 17-parameter function."""

    command: list[str]
    pick: Pick
    ctx: PaneContext
    runner: CommandRunner
    restart_confirmation: bool
    restart_delay: float
    restart_message: str
    worktree: str | None
    auto_select_branch: str | None
    auto_select_timeout: float
    on_branch_selected: Callable[[str | None], None]
    clear_screen: Callable[[], None]
    progress: Callable[[str], None]
    confirm_restart: Callable[[], None]
    restart_floor: RestartFloor


def loop_step(
    rc: RestartConfig, *, last_selected_branch: str | None, first_iteration: bool
) -> tuple[bool, str | None]:
    """One restart-loop iteration. Returns (should_stop, last_selected_branch).

    A cancelled pick just ends the loop. A KeyboardInterrupt during either
    step propagates to the caller (`_restart_loop`'s own handler) instead of
    being swallowed here -- a live pane and a bare terminal behave the same.
    """
    begin_iteration(rc.ctx)
    success, selected_branch = select_for_iteration(
        rc.pick,
        worktree=rc.worktree,
        last_selected_branch=last_selected_branch,
        auto_select_branch=rc.auto_select_branch,
        auto_select_timeout=rc.auto_select_timeout,
        first_iteration=first_iteration,
        on_branch_selected=rc.on_branch_selected,
    )
    if not success:
        return True, last_selected_branch
    last_selected_branch = selected_branch

    outcome = run_once(
        rc.command,
        selected_branch,
        ctx=rc.ctx,
        runner=rc.runner,
        clear_screen=rc.clear_screen,
        progress=rc.progress,
        restart_message=rc.restart_message,
        restart_confirmation=rc.restart_confirmation,
        confirm_restart=rc.confirm_restart,
        restart_delay=rc.restart_delay,
        restart_floor=rc.restart_floor,
    )
    return outcome == "stop", last_selected_branch
