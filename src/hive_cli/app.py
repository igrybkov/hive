"""Main CLI application definition."""

from __future__ import annotations

from cyclopts import App

from .commands import (
    completion,
    config_cmd,
    diff,
    handoff,
    merge,
    rebase,
    run,
    status,
    task,
    wt,
    zellij,
)

app = App(
    name="hive",
    help=(
        "Hive - Multi-agent worktree management CLI.\n\n"
        "Manage AI coding agents and git worktrees for parallel development."
    ),
    version="0.1.0",
    version_flags=["--version", "-V"],
)

# Core commands
app.command(run.run_app)
app.command(zellij.zellij_app)
app.command(wt.wt_app)
app.command(completion.completion_app)
app.command(config_cmd.config_app)

# Agent management commands
app.command(status.status_app)
app.command(task.task_app)
app.command(handoff.handoff_app)

# Git analysis commands
app.command(diff.diff_app)
app.command(rebase.rebase_check_app)
app.command(merge.merge_preview_app)
