"""Shared options for commands that execute in worktrees."""

from __future__ import annotations

from typing import Annotated

from cyclopts import Parameter


def _complete_worktree(ctx, param, incomplete):
    """Shell completion for --worktree option."""
    try:
        from ..git import list_worktrees

        worktrees = list_worktrees()
        branches = [wt.branch for wt in worktrees]
        return [b for b in branches if b.startswith(incomplete)]
    except Exception:
        return []


# Type aliases for common options used across multiple commands
WorktreeOption = Annotated[
    str | None,
    Parameter(
        name=["--worktree", "-w"],
        help="Run in worktree. Use '-' for selection, or specify branch.",
    ),
]

RestartOption = Annotated[
    bool,
    Parameter(
        help="Auto-restart after exit. Implies -w=- for interactive selection.",
    ),
]

RestartConfirmationOption = Annotated[
    bool,
    Parameter(
        name="--restart-confirmation",
        help="Wait for Enter before each restart. Implies --restart.",
    ),
]

RestartDelayOption = Annotated[
    float,
    Parameter(
        name="--restart-delay",
        help="Delay in seconds between restarts (default: 0).",
    ),
]
