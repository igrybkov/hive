"""Status collection for `hive status`: no printing, no rich, no prompts.

AgentStatus lives here rather than in commands/status.py because it is the
shared data model the ui/ layer (views and the interactive picker) also
needs.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..config import get_settings
from ..git import GitSummary, git_summary, list_worktrees
from ..state.pane_state import PaneState
from . import facts as facts_service


@dataclass
class AgentStatus:
    """Status information for an agent worktree."""

    agent_id: str
    path: Path
    branch: str
    is_main: bool
    is_dirty: bool
    ahead: int
    behind: int
    last_commit_hash: str
    last_commit_msg: str
    task: str | None


def _get_task(main_repo: Path, agent_id: str) -> str | None:
    """First non-empty, non-header line of an agent's task file, if any.

    Args:
        main_repo: Path to main repository.
        agent_id: Agent identifier.

    Returns:
        First non-empty, non-header line of task file, or None.
    """
    task_file = (
        main_repo / ".claude" / "local-agents" / "tasks" / f"agent-{agent_id}.md"
    )
    if not task_file.exists():
        return None

    try:
        content = task_file.read_text()
        for line in content.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                return line[:60]
        return None
    except OSError:
        return None


def collect_status(main_repo: Path) -> list[AgentStatus]:
    """Collect status for every agent worktree under main_repo.

    One `git worktree list` plus two commands per worktree (`git_summary`).

    Args:
        main_repo: Path to main repository.

    Returns:
        List of AgentStatus objects.
    """
    statuses: list[AgentStatus] = []
    for wt in list_worktrees(main_repo):
        summary = git_summary(wt.path)
        if wt.is_main:
            agent_id = "1"
            branch = summary.branch or "main"  # detached HEAD shows as main
        else:
            agent_id = wt.branch
            branch = wt.branch
        statuses.append(
            AgentStatus(
                agent_id=agent_id,
                path=wt.path,
                branch=branch,
                is_main=wt.is_main,
                is_dirty=summary.dirty,
                ahead=summary.ahead,
                behind=summary.behind,
                last_commit_hash=summary.last_hash,
                last_commit_msg=summary.last_subject[:50],
                task=_get_task(main_repo, agent_id),
            )
        )
    return statuses


def task_summary_for(main_repo: Path, agent_id: str) -> str:
    """Public wrapper around `_get_task`: "" (never None) when there is none."""
    return _get_task(main_repo, agent_id) or ""


def compute_facts(main_repo: Path) -> dict[str, GitSummary]:
    """Throttled fetch + per-worktree summaries, keyed by worktree path (str).

    The control plane's (F4) facts refresher: `services.facts.fetch_if_stale`
    then `.summaries`, reshaped from `dict[Path, GitSummary]` to the
    `dict[str, GitSummary]` `watch.FactsUpdated`/`ControlServer.facts` use.
    """
    worktrees = list_worktrees(main_repo)
    facts_service.fetch_if_stale(main_repo, get_settings().worktrees.fetch_interval)
    return {
        str(path): summary
        for path, summary in facts_service.summaries(worktrees).items()
    }


def tasks_for_states(main_repo: Path, states: list[PaneState]) -> dict[str, str]:
    """Task summaries keyed by `str(hive_pane_id)`, for the control plane (F4).

    A pane's task file is keyed by its worktree's agent id ("1" for main, the
    branch name otherwise -- see `collect_status`); a pane still `selecting`
    (no branch yet) has no worktree, so it gets no task rather than main's.
    """
    return {
        str(state.hive_pane_id): task_summary_for(main_repo, state.branch)
        for state in states
        if state.branch and state.hive_pane_id
    }


def get_shared_notes_summary(main_repo: Path) -> tuple[int, str | None]:
    """Line count and latest ``## `` header of the shared-notes file, if any.

    Args:
        main_repo: Path to main repository.

    Returns:
        Tuple of (line_count, last_entry_header).
    """
    notes_file = main_repo / ".claude" / "local-agents" / "shared-notes.md"
    if not notes_file.exists():
        return 0, None

    try:
        content = notes_file.read_text()
        lines = content.splitlines()
        line_count = len(lines)

        # Find last ## header
        last_header = None
        for line in reversed(lines):
            if line.startswith("## "):
                last_header = line[3:]
                break

        return line_count, last_header
    except OSError:
        return 0, None
