"""Rich renderables for `hive status`: pure data -> Group, no printing."""

from __future__ import annotations

import time
from pathlib import Path

from rich.console import Group
from rich.text import Text

from ...git import CommitInfo, GitStatusDetail
from ...services import status as service_status
from ...services.status import AgentStatus


def _agent_lines(status: AgentStatus) -> list[Text]:
    """The full-view block (label, branch, commit, task) for one agent."""
    lines: list[Text] = []

    if status.is_main:
        lines.append(Text.from_markup("[bold cyan]Agent 1 (main)[/]"))
    else:
        lines.append(Text.from_markup(f"[bold magenta]Agent {status.agent_id}[/]"))

    dirty_indicator = " [yellow]*[/]" if status.is_dirty else ""
    ahead_behind = ""
    if status.ahead > 0:
        ahead_behind += f"[green]+{status.ahead}[/]"
    if status.behind > 0:
        ahead_behind += f"[red]-{status.behind}[/]"
    if ahead_behind:
        ahead_behind = f" [{ahead_behind}]"

    branch_str = f"[green]{status.branch}[/]{dirty_indicator}{ahead_behind}"
    lines.append(Text.from_markup(f"  [blue]Branch:[/] {branch_str}"))
    commit_str = f"{status.last_commit_hash} {status.last_commit_msg}"
    lines.append(Text.from_markup(f"  [blue]Commit:[/] [dim]{commit_str}[/]"))

    if status.task:
        lines.append(Text.from_markup(f"  [blue]Task:[/]   {status.task}"))

    lines.append(Text(""))
    return lines


def build_full_output(statuses: list[AgentStatus], main_repo: Path) -> Group:
    """Build full status view as a renderable.

    Args:
        statuses: List of agent statuses.
        main_repo: Path to main repository.

    Returns:
        Group of Text objects for rendering.
    """
    lines: list[Text] = []
    lines.append(Text(""))
    lines.append(Text.from_markup("[bold cyan]" + "═" * 55 + "[/]"))
    lines.append(
        Text.from_markup(f"[bold cyan]  Agent Status Board - {main_repo.name}[/]")
    )
    lines.append(Text.from_markup("[bold cyan]" + "═" * 55 + "[/]"))
    lines.append(Text(""))

    for status in statuses:
        lines.extend(_agent_lines(status))

    # Shared notes summary
    line_count, last_header = service_status.get_shared_notes_summary(main_repo)
    if line_count > 0:
        lines.append(Text.from_markup("[bold yellow]Shared Notes[/]"))
        lines.append(Text.from_markup(f"[dim]{line_count} lines[/]"))
        if last_header:
            lines.append(Text.from_markup(f"  [dim]Latest: {last_header}[/]"))
        lines.append(Text(""))

    lines.append(Text.from_markup(f"[dim]Updated: {time.strftime('%H:%M:%S')}[/]"))

    return Group(*lines)


def build_compact_output(statuses: list[AgentStatus], main_repo: Path) -> Group:
    """Build compact status view as a renderable.

    Args:
        statuses: List of agent statuses.
        main_repo: Path to main repository.

    Returns:
        Group of Text objects for rendering.
    """
    lines = []
    timestamp = time.strftime("%H:%M:%S")
    lines.append(
        Text.from_markup(
            f"[bold cyan]Agents[/] [dim]{main_repo.name}[/]  [dim]{timestamp}[/]"
        )
    )

    for status in statuses:
        # Agent label
        if status.is_main:
            agent_label = "[cyan]1[/]"
        else:
            agent_label = f"[magenta]{status.agent_id}[/]"

        dirty_indicator = "[yellow]*[/]" if status.is_dirty else " "

        ahead_behind = ""
        if status.ahead > 0:
            ahead_behind += f"[green]+{status.ahead}[/]"
        if status.behind > 0:
            ahead_behind += f"[red]-{status.behind}[/]"

        # Truncate commit message for compact view
        commit_info = f"{status.last_commit_hash} {status.last_commit_msg[:40]}"

        lines.append(
            Text.from_markup(
                f"  [bold]\\[{agent_label}][/] "
                f"[green]{status.branch:<20}[/] "
                f"{dirty_indicator}{ahead_behind:<6} "
                f"[dim]{commit_info}[/]"
            )
        )

    return Group(*lines)


# --- detail screen content (pure builders, one per section) ---


def _detail_header_parts(status: AgentStatus) -> list[tuple[str, str]]:
    parts: list[tuple[str, str]] = [("bold fg:cyan", "═" * 60 + "\n")]
    if status.is_main:
        parts.append(("bold fg:cyan", f"  {status.branch}"))
        parts.append(("fg:gray", " (main)\n"))
    else:
        parts.append(("bold fg:green", f"  {status.branch}\n"))
    parts.append(("bold fg:cyan", "═" * 60 + "\n\n"))
    return parts


def _detail_path_parts(status: AgentStatus) -> list[tuple[str, str]]:
    return [("dim", "Path:  "), ("", f"{status.path}\n\n")]


def _detail_tracking_parts(status: AgentStatus) -> list[tuple[str, str]]:
    parts: list[tuple[str, str]] = [("dim", "Tracking:  ")]

    if status.ahead == 0 and status.behind == 0:
        parts.append(("fg:gray", "up to date\n\n"))
        return parts

    if status.ahead > 0:
        parts.append(("fg:green", f"{status.ahead} ahead"))
        if status.behind > 0:
            parts.append(("", ", "))
    if status.behind > 0:
        parts.append(("fg:red", f"{status.behind} behind"))
    parts.append(("", "\n\n"))
    return parts


def _detail_git_status_parts(git_status: GitStatusDetail) -> list[tuple[str, str]]:
    parts: list[tuple[str, str]] = [("bold fg:yellow", "Git Status\n")]

    has_changes = git_status.staged or git_status.unstaged or git_status.untracked
    if not has_changes:
        parts.append(("fg:gray", "  Working tree clean\n"))
        parts.append(("", "\n"))
        return parts

    if git_status.staged:
        parts.append(("fg:green", "  Staged:\n"))
        for f in git_status.staged:
            parts.append(("fg:green", f"    {f}\n"))

    if git_status.unstaged:
        parts.append(("fg:yellow", "  Modified:\n"))
        for f in git_status.unstaged:
            parts.append(("fg:yellow", f"    {f}\n"))

    if git_status.untracked:
        parts.append(("fg:red", "  Untracked:\n"))
        for f in git_status.untracked:
            parts.append(("fg:gray", f"    {f}\n"))

    parts.append(("", "\n"))
    return parts


def _detail_commits_parts(commits: list[CommitInfo]) -> list[tuple[str, str]]:
    parts: list[tuple[str, str]] = [("bold fg:yellow", "Recent Commits\n")]

    if not commits:
        parts.append(("fg:gray", "  No commits found\n"))
        parts.append(("", "\n"))
        return parts

    for commit in commits:
        parts.append(("fg:cyan", f"  {commit.hash} "))
        parts.append(("", f"{commit.message}\n"))
        parts.append(("fg:gray", f"          {commit.author}, {commit.date}\n"))
    parts.append(("", "\n"))
    return parts


def _detail_task_parts(status: AgentStatus) -> list[tuple[str, str]]:
    if not status.task:
        return []
    return [("bold fg:yellow", "Current Task\n"), ("", f"  {status.task}\n\n")]


def build_detail_content(
    status: AgentStatus, git_status: GitStatusDetail, commits: list[CommitInfo]
) -> list[tuple[str, str]]:
    """Build formatted text content for the worktree detail screen.

    Args:
        status: Agent status for the worktree.
        git_status: Detailed git status.
        commits: List of recent commits.

    Returns:
        List of (style, text) tuples for prompt_toolkit.
    """
    return [
        *_detail_header_parts(status),
        *_detail_path_parts(status),
        *_detail_tracking_parts(status),
        *_detail_git_status_parts(git_status),
        *_detail_commits_parts(commits),
        *_detail_task_parts(status),
    ]
