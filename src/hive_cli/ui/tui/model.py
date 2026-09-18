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
from ...state.pane_state import ICONS, PaneState, pane_hive_id


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
    title: str = ""  # raw pane title -- name_cell()'s bare-pane fallback


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
    """Blank for a bare pane that's neither idle nor exited -- there's no
    hive status to show, and "?" would read as an error rather than "n/a"."""
    if not row.status:
        return ""
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
    own_pane_id: str | None = None,
) -> dict[str, PaneRow]:
    """One `PaneRow` per pane known either way -- a live/registered hive
    socket (`states`) or the mux's own inventory (`panes`), whichever has it
    (a state can arrive slightly ahead of the next `list-panes` poll; a
    `start_suspended` agent slot or a plain tool pane, shell, lazygit, ...,
    never gets a socket at all but is still a pane in the session and
    belongs on the board). A pane with state renders the agent columns as
    before (`_agent_row`); one without renders from `PaneInfo` alone
    (`_bare_row`): idle when Zellij still reports it held, exited when
    Zellij reports it exited, blank otherwise. `own_pane_id` (the control
    plane's own pane) is skipped -- it has no useful row of itself. Ordered
    by hive-pane-number then pane id, same as before G0 -- a pane with
    neither a state's nor a bare pane's title-parsed number sorts last.
    """

    def sort_key(pane_id: str) -> tuple[int, str]:
        state = states.get(pane_id)
        if state is not None:
            return (state.hive_pane_id or 999, pane_id)
        pane = panes.get(pane_id)
        hid = pane_hive_id(pane.title) if pane else None
        return (hid or 999, pane_id)

    rows: dict[str, PaneRow] = {}
    for pane_id in sorted(set(states) | set(panes), key=sort_key):
        if pane_id == own_pane_id:
            continue
        state = states.get(pane_id)
        pane = panes.get(pane_id)
        if state is not None:
            rows[pane_id] = _agent_row(state, pane, facts, tasks)
        elif pane is not None:
            rows[pane_id] = _bare_row(pane)
    return rows


def _agent_row(
    state: PaneState,
    pane: PaneInfo | None,
    facts: dict[str, GitSummary],
    tasks: dict[str, str],
) -> PaneRow:
    return PaneRow(
        pane_id=state.pane_id,
        hive_pane_id=state.hive_pane_id,
        label=state.label,
        title=pane.title if pane else "",
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


def _bare_row(pane: PaneInfo) -> PaneRow:
    status = "exited" if pane.exited else "idle" if pane.suspended else ""
    return PaneRow(
        pane_id=pane.id,
        hive_pane_id=pane_hive_id(pane.title) or 0,
        label="",
        title=pane.title,
        agent="",
        branch="",
        worktree="",
        status=status,
        status_since=0.0,
        git="",
        task="",
        tab_id=pane.tab_id,
        focused=pane.focused,
    )


def name_cell(row: PaneRow) -> str:
    """The board's leading identity column: a label/number for an agent
    pane, the raw layout title for anything else (shell, lazygit, ...)."""
    if row.hive_pane_id:
        return row.label or f"c{row.hive_pane_id}"
    return row.title


def filter_rows(rows: dict[str, PaneRow], query: str) -> dict[str, PaneRow]:
    """Case-insensitive substring match over branch/agent/label/title/task/
    worktree."""
    if not query:
        return rows
    q = query.lower()
    return {
        pid: row
        for pid, row in rows.items()
        if q in row.branch.lower()
        or q in row.agent.lower()
        or q in row.label.lower()
        or q in row.title.lower()
        or q in row.task.lower()
        or q in row.worktree.lower()
    }
