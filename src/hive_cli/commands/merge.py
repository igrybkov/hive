"""Merge-preview command - preview potential merge conflicts between agent branches."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated

from cyclopts import App, Parameter

from ..core.errors import HiveError
from ..git import get_main_repo, simulate_merge
from ..services import merge as merge_service
from ..ui import board
from ..ui.console import error, out
from ..ui.views import merge as merge_views


def _preview_agent_merge(agent_id: str, main_repo: Path) -> bool:
    """Preview merge for a specific agent, printing progress as it goes.

    Returns:
        True if merge would succeed.
    """
    try:
        target = merge_service.resolve_target(agent_id, main_repo)
    except HiveError as exc:
        error(str(exc))
        return False

    out.print(merge_views.build_preview_header(target))
    sim = simulate_merge(
        target.path, main_repo, target.default_branch, progress=out.print
    )
    if not sim.ok:
        assert sim.error is not None  # every ok=False construction sets it
        error(sim.error)
        return False
    out.print(merge_views.build_simulation(sim))
    return not sim.conflicts


def _watch(agent_id: str | None, main_repo: Path, interval: float) -> None:
    """Live board of the overlap analysis, or of one agent's simulated merge."""
    if agent_id:
        board.watch(
            lambda: merge_service.preview(agent_id, main_repo),
            merge_views.build_preview,
            interval=interval,
        )
    else:
        board.watch(
            lambda: merge_service.collect_overlap(main_repo),
            merge_views.build_overlap,
            interval=interval,
        )


# Cyclopts App

merge_preview_app = App(
    name="merge-preview",
    help="Preview potential merge conflicts between agent branches.",
)


@merge_preview_app.default
def merge_preview(
    agent_id: Annotated[
        str | None,
        Parameter(help="Agent identifier to preview merge for."),
    ] = None,
    watch: Annotated[
        bool,
        Parameter(
            name=["--watch", "-w"],
            help="Live board, repainted only when something changes. q quits.",
        ),
    ] = False,
    interval: Annotated[
        float,
        Parameter(name="--interval", help="Seconds between refreshes in watch mode."),
    ] = 5.0,
):
    """Preview potential merge conflicts between agent branches.

    Without arguments, shows file overlap between all agents.
    With an agent ID, simulates merging that agent's branch into default branch.

    Examples:
        hive merge-preview      # Show file overlap
        hive merge-preview 2    # Simulate merge for agent 2
        hive merge-preview --watch        # Live overlap board (q quits)
        hive merge-preview 2 -w --interval 10
    """
    main_repo = get_main_repo()

    if watch:
        try:
            _watch(agent_id, main_repo, interval)
        except HiveError as exc:
            error(str(exc))
            sys.exit(1)
        return

    if agent_id:
        success = _preview_agent_merge(agent_id, main_repo)
        if not success:
            sys.exit(1)
    else:
        out.print(merge_views.build_overlap(merge_service.collect_overlap(main_repo)))
