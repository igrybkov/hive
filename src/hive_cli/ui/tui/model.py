"""Pure row-building for the control-plane TUI (F4): no textual, no I/O.

`build_rows` is the single seam between raw `watch_session` state and the
table `ControlPlaneApp` renders; every other helper composes into one cell.
Kept import-light (state/git/mux only) so it can be unit-tested without
starting an App.
"""

from __future__ import annotations

from dataclasses import dataclass

from ...git import GitSummary
from ...mux.base import PaneInfo
from ...state.pane_state import ICONS, PaneState


@dataclass(frozen=True)
class PaneRow:
    pane_id: str
    hive_pane_id: int
    label: str
    agent: str
    branch: str
    worktree: str
    status: str
    status_since: float
    git: str
    task: str
    tab_id: str
    focused: bool


def age_bucket(seconds: float) -> str:
    """``"<1m"`` under a minute, ``"Nm"`` under an hour, ``"Nh"`` under a day,
    else ``"Nd"``."""
    if seconds < 60:
        return "<1m"
    if seconds < 3600:
        return f"{int(seconds // 60)}m"
    if seconds < 86400:
        return f"{int(seconds // 3600)}h"
    return f"{int(seconds // 86400)}d"


def status_cell(row: PaneRow, *, now: float) -> str:
    icon = ICONS.get(row.status, "?")
    return f"{icon} {row.status} {age_bucket(now - row.status_since)}"


def git_cell(summary: GitSummary | None) -> str:
    """``"?"`` when unknown, ``"✓"`` when clean, else ``"±N"`` plus ahead/behind."""
    if summary is None:
        return "?"
    if not summary.dirty:
        cell = "✓"
    else:
        n = summary.staged + summary.modified + summary.untracked + summary.conflicted
        cell = f"±{n}"
    if summary.ahead:
        cell += f" ↑{summary.ahead}"
    if summary.behind:
        cell += f" ↓{summary.behind}"
    return cell


def build_rows(
    states: dict[str, PaneState],
    panes: dict[str, PaneInfo],
    facts: dict[str, GitSummary],
    tasks: dict[str, str],
    *,
    now: float,
) -> dict[str, PaneRow]:
    """One `PaneRow` per pane socket, merged with mux pane info (focused,
    tab_id), git facts (keyed by worktree path) and task summaries (keyed by
    ``str(hive_pane_id)``); returned in hive_pane_id-then-pane_id order.
    """
    ordered = sorted(states.values(), key=lambda s: (s.hive_pane_id or 999, s.pane_id))
    rows: dict[str, PaneRow] = {}
    for state in ordered:
        pane = panes.get(state.pane_id)
        rows[state.pane_id] = PaneRow(
            pane_id=state.pane_id,
            hive_pane_id=state.hive_pane_id,
            label=state.label,
            agent=state.agent,
            branch=state.branch,
            worktree=state.worktree_path,
            status=state.status,
            status_since=state.status_since,
            git=git_cell(facts.get(state.worktree_path)),
            task=tasks.get(str(state.hive_pane_id), ""),
            tab_id=pane.tab_id if pane else state.tab_id,
            focused=pane.focused if pane else False,
        )
    return rows


def filter_rows(rows: dict[str, PaneRow], query: str) -> dict[str, PaneRow]:
    """Case-insensitive substring match over branch/agent/label/task."""
    if not query:
        return rows
    q = query.lower()
    return {
        pid: row
        for pid, row in rows.items()
        if q in row.branch.lower()
        or q in row.agent.lower()
        or q in row.label.lower()
        or q in row.task.lower()
    }
