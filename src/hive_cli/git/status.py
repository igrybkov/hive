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


@dataclass(frozen=True)
class GitSummary:
    """Everything `hive status` and the picker need about one worktree.

    Produced by `git_summary` from exactly two commands; `branch` is "" when
    detached and `upstream` is "" when the branch tracks nothing (then
    ahead/behind are 0).
    """

    branch: str
    upstream: str
    ahead: int
    behind: int
    staged: int
    modified: int
    untracked: int
    conflicted: int
    last_hash: str  # short
    last_subject: str
    last_age: str  # git's %cr, e.g. "3 hours ago"

    @property
    def dirty(self) -> bool:
        return bool(self.staged or self.modified or self.untracked or self.conflicted)


def _parse_branch_header(line: str, head: dict[str, object]) -> None:
    """One `# branch.*` line of porcelain v2 into the `head` dict."""
    key, _, value = line[2:].partition(" ")
    if key == "branch.head":
        head["branch"] = "" if value == "(detached)" else value
    elif key == "branch.upstream":
        head["upstream"] = value
    elif key == "branch.ab":
        ahead, _, behind = value.partition(" ")
        head["ahead"] = int(ahead.lstrip("+") or 0)
        head["behind"] = int(behind.lstrip("-") or 0)


def parse_porcelain_v2(text: str) -> tuple[str, str, int, int, int, int, int, int]:
    """Pure parser for `git status --porcelain=v2 --branch` output.

    Returns (branch, upstream, ahead, behind, staged, modified, untracked,
    conflicted). Entry kinds: `1` ordinary, `2` rename/copy (XY: index then
    worktree status, "." = unchanged), `u` unmerged, `?` untracked, `!`
    ignored (not counted).
    """
    head: dict[str, object] = {"branch": "", "upstream": "", "ahead": 0, "behind": 0}
    staged = modified = untracked = conflicted = 0
    for line in text.splitlines():
        if line.startswith("# "):
            _parse_branch_header(line, head)
        elif line.startswith(("1 ", "2 ")):
            xy = line[2:4]
            staged += xy[0] != "."
            modified += xy[1] != "."
        elif line.startswith("u "):
            conflicted += 1
        elif line.startswith("? "):
            untracked += 1
    return (
        str(head["branch"]),
        str(head["upstream"]),
        int(head["ahead"]),  # type: ignore[call-overload]
        int(head["behind"]),  # type: ignore[call-overload]
        staged,
        modified,
        untracked,
        conflicted,
    )


def git_summary(path: Path) -> GitSummary:
    """Exactly two spawns: `status --porcelain=v2 --branch` and `log -1`."""
    status = proc.run(["git", "status", "--porcelain=v2", "--branch"], cwd=path)
    log = proc.run(["git", "log", "-1", "--format=%h%x00%s%x00%cr"], cwd=path)
    parsed = parse_porcelain_v2(status.stdout if status.ok else "")
    last_hash = last_subject = last_age = ""
    if log.ok:
        parts = log.stdout.strip("\n").split("\x00")
        if len(parts) == 3:
            last_hash, last_subject, last_age = parts
    return GitSummary(*parsed, last_hash, last_subject, last_age)


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
