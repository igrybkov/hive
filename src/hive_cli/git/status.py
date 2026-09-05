"""Git facts for `hive status` and its interactive picker: no printing, no prompts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..core import proc


@dataclass
class GitStatusDetail:
    """Detailed git status for a worktree."""

    staged: list[str]  # Staged files (index)
    unstaged: list[str]  # Modified but not staged
    untracked: list[str]  # Untracked files


@dataclass
class CommitInfo:
    """Information about a commit."""

    hash: str
    message: str
    author: str
    date: str


def upstream_ahead_behind(path: Path) -> tuple[int, int]:
    """Commits ahead/behind the worktree's tracked ``@{upstream}``.

    Not a duplicate of ``analysis.commits_ahead_behind()``, which compares
    against a fixed ``origin/{default_branch}`` instead of the branch's own
    tracked upstream.

    Args:
        path: Path to the worktree.

    Returns:
        Tuple of (ahead, behind) counts.
    """
    result = proc.run(
        ["git", "-C", str(path), "rev-parse", "--abbrev-ref", "@{upstream}"],
        timeout=10,
    )
    if not result.ok:
        return 0, 0
    upstream = result.stdout.strip()

    result = proc.run(
        ["git", "-C", str(path), "rev-list", "--count", f"{upstream}..HEAD"],
        timeout=10,
    )
    try:
        ahead = int(result.stdout.strip()) if result.ok else 0
    except ValueError:
        ahead = 0

    result = proc.run(
        ["git", "-C", str(path), "rev-list", "--count", f"HEAD..{upstream}"],
        timeout=10,
    )
    try:
        behind = int(result.stdout.strip()) if result.ok else 0
    except ValueError:
        behind = 0

    return ahead, behind


def last_commit_summary(path: Path) -> tuple[str, str]:
    """Short hash and truncated subject line of a worktree's last commit.

    Args:
        path: Path to the worktree.

    Returns:
        Tuple of (short_hash, message).
    """
    result = proc.run(
        ["git", "-C", str(path), "log", "-1", "--format=%h\t%s"], timeout=10
    )
    if not result.ok:
        return "", ""
    parts = result.stdout.strip().split("\t", 1)
    if len(parts) == 2:
        return parts[0], parts[1][:50]
    return parts[0] if parts else "", ""


def _classify_status_line(line: str, detail: GitStatusDetail) -> None:
    """Sort one `git status --porcelain` line into staged/unstaged/untracked."""
    if not line:
        return
    index_status = line[0]
    worktree_status = line[1]
    filename = line[3:]

    # Staged changes (in index)
    if index_status in ("A", "M", "D", "R", "C"):
        detail.staged.append(f"{index_status} {filename}")

    # Unstaged changes (in worktree)
    if worktree_status in ("M", "D"):
        detail.unstaged.append(f"{worktree_status} {filename}")

    # Untracked files
    if index_status == "?" and worktree_status == "?":
        detail.untracked.append(filename)


def get_git_status_detail(path: Path) -> GitStatusDetail:
    """Detailed git status (staged/unstaged/untracked files) for a worktree.

    Args:
        path: Path to the worktree.

    Returns:
        GitStatusDetail with staged, unstaged, and untracked files.
    """
    detail = GitStatusDetail(staged=[], unstaged=[], untracked=[])

    result = proc.run(["git", "-C", str(path), "status", "--porcelain"], timeout=10)
    if result.ok:
        for line in result.stdout.splitlines():
            _classify_status_line(line, detail)

    return detail


def get_recent_commits(path: Path, count: int = 5) -> list[CommitInfo]:
    """Recent commits for a worktree, most recent first.

    Args:
        path: Path to the worktree.
        count: Number of commits to retrieve.

    Returns:
        List of CommitInfo objects.
    """
    commits: list[CommitInfo] = []
    result = proc.run(
        ["git", "-C", str(path), "log", f"-{count}", "--format=%h\t%s\t%an\t%cr"],
        timeout=10,
    )
    if result.ok:
        for line in result.stdout.splitlines():
            if not line:
                continue
            parts = line.split("\t")
            if len(parts) >= 4:
                commits.append(
                    CommitInfo(
                        hash=parts[0],
                        message=parts[1][:50],
                        author=parts[2],
                        date=parts[3],
                    )
                )

    return commits
