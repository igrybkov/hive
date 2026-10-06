"""Branch handoff data layer: files, symlinks, WIP commits, current-branch lookup.

Moved from top-level handoffs.py and commands/handoff.py:41-135 (A0 step 6).
`_format_handoff_preview` (prints) stays in commands/handoff.py until
ui/views/ exists (step 7).
"""

from __future__ import annotations

import os
from pathlib import Path

from ..core import proc
from ..git import (
    get_all_branches,
    get_current_branch,
    get_main_repo,
    list_worktrees,
    sanitize_branch_name,
)

# Path of the handoff symlink inside a worktree, relative to its root.
HANDOFF_SYMLINK = ".claude/HANDOFF.md"


def get_handoffs_dir(main_repo: Path | None = None) -> Path:
    """Get the handoffs directory in the main repo.

    Args:
        main_repo: Path to main repository. If None, auto-detected.

    Returns:
        Path to handoffs directory (.claude/handoffs/).
    """
    if main_repo is None:
        main_repo = get_main_repo()
    return main_repo / ".claude" / "handoffs"


def get_handoff_file(branch: str, main_repo: Path | None = None) -> Path:
    """Get the handoff file path for a branch.

    Args:
        branch: Branch name.
        main_repo: Path to main repository. If None, auto-detected.

    Returns:
        Path to handoff file (.claude/handoffs/{branch}.md).
    """
    handoffs_dir = get_handoffs_dir(main_repo)
    # Sanitize branch name for filesystem (replace / with --)
    safe_name = sanitize_branch_name(branch)
    return handoffs_dir / f"{safe_name}.md"


def ensure_handoffs_dir(main_repo: Path | None = None) -> Path:
    """Ensure the handoffs directory exists.

    Args:
        main_repo: Path to main repository. If None, auto-detected.

    Returns:
        Path to handoffs directory.
    """
    handoffs_dir = get_handoffs_dir(main_repo)
    handoffs_dir.mkdir(parents=True, exist_ok=True)
    return handoffs_dir


def setup_handoff_symlink(worktree_path: Path, branch: str, main_repo: Path) -> Path:
    """Setup handoff file and symlink for a worktree.

    Creates:
    1. .claude/handoffs/ directory in main repo (if needed)
    2. Empty handoff file for the branch (if needed)
    3. Symlink from worktree/.claude/HANDOFF.md to the handoff file

    Args:
        worktree_path: Path to the worktree.
        branch: Branch name.
        main_repo: Path to main repository.

    Returns:
        Path to the handoff file in main repo.
    """
    # Ensure handoffs directory exists
    ensure_handoffs_dir(main_repo)

    # Get handoff file path
    handoff_file = get_handoff_file(branch, main_repo)

    # Create empty handoff file if it doesn't exist
    if not handoff_file.exists():
        handoff_file.touch()

    # Create .claude directory in worktree
    worktree_claude_dir = worktree_path / ".claude"
    worktree_claude_dir.mkdir(parents=True, exist_ok=True)

    # Create symlink
    symlink_path = worktree_claude_dir / "HANDOFF.md"

    # Remove existing symlink/file if present
    if symlink_path.is_symlink() or symlink_path.exists():
        symlink_path.unlink()

    # Calculate relative path from worktree/.claude/ to main_repo/.claude/handoffs/
    # This ensures the symlink works regardless of absolute paths
    try:
        rel_path = os.path.relpath(handoff_file, worktree_claude_dir)
        symlink_path.symlink_to(rel_path)
    except ValueError:
        # On Windows or cross-device, fall back to absolute path
        symlink_path.symlink_to(handoff_file)

    # The symlink is hive's, not the project's: keep `git add -A` from staging it.
    _exclude_from_git(worktree_path, HANDOFF_SYMLINK)

    return handoff_file


def _exclude_from_git(worktree_path: Path, rel_path: str) -> None:
    """Add ``rel_path`` to the repository's ``info/exclude`` file.

    ``git rev-parse --git-path info/exclude`` resolves to the shared exclude
    file in the common git dir even inside a linked worktree, so the entry
    applies to every worktree of the repository (which is what we want: the
    symlink is hive's in all of them). Idempotent; silently does nothing when
    git is unavailable or the file cannot be written.

    Args:
        worktree_path: Path to the worktree.
        rel_path: Path to exclude, relative to the worktree root.
    """
    try:
        result = proc.run(
            [
                "git",
                "-C",
                str(worktree_path),
                "rev-parse",
                "--git-path",
                "info/exclude",
            ],
            timeout=10,
        )
    except OSError:
        return
    if not result.ok:
        return

    exclude = Path(result.stdout.strip())
    if not exclude.is_absolute():
        exclude = worktree_path / exclude

    try:
        existing = exclude.read_text() if exclude.exists() else ""
        if rel_path in existing.splitlines():
            return
        exclude.parent.mkdir(parents=True, exist_ok=True)
        with exclude.open("a", encoding="utf-8") as fh:
            if existing and not existing.endswith("\n"):
                fh.write("\n")
            fh.write(f"{rel_path}\n")
    except OSError:
        return


def list_handoffs(main_repo: Path | None = None) -> list[tuple[str, Path]]:
    """List all handoff files.

    Args:
        main_repo: Path to main repository. If None, auto-detected.

    Returns:
        List of (branch_name, handoff_file_path) tuples.
    """
    handoffs_dir = get_handoffs_dir(main_repo)
    if not handoffs_dir.exists():
        return []

    result = []
    for f in sorted(handoffs_dir.glob("*.md")):
        # Convert sanitized name back (-- to /)
        branch = f.stem.replace("--", "/")
        result.append((branch, f))
    return result


def has_handoff_content(handoff_file: Path) -> bool:
    """Check if a handoff file has meaningful content.

    Args:
        handoff_file: Path to handoff file.

    Returns:
        True if file exists and has non-whitespace content.
    """
    if not handoff_file.exists():
        return False
    content = handoff_file.read_text().strip()
    return len(content) > 0


def delete_handoff(branch: str, main_repo: Path | None = None) -> bool:
    """Delete a handoff file.

    Args:
        branch: Branch name.
        main_repo: Path to main repository. If None, auto-detected.

    Returns:
        True if file was deleted, False if it didn't exist.
    """
    handoff_file = get_handoff_file(branch, main_repo)
    if handoff_file.exists():
        handoff_file.unlink()
        return True
    return False


def _orphaned_handoffs(main_repo: Path) -> list[tuple[str, Path]]:
    """Handoffs whose branch is no longer local, remote, or a worktree."""
    all_branches = set(get_all_branches(main_repo))
    worktree_branches = {wt.branch for wt in list_worktrees(main_repo)}
    valid_branches = all_branches | worktree_branches | {"main", "master"}
    return [
        (branch, handoff_file)
        for branch, handoff_file in list_handoffs(main_repo)
        if branch not in valid_branches
    ]


def preview_orphaned_handoffs(main_repo: Path | None = None) -> list[tuple[str, Path]]:
    """Handoffs that ``clean_orphaned_handoffs`` would remove, without removing them.

    Args:
        main_repo: Path to main repository. If None, auto-detected.

    Returns:
        List of (branch_name, handoff_file_path) tuples that are orphaned.
    """
    if main_repo is None:
        main_repo = get_main_repo()
    return _orphaned_handoffs(main_repo)


def clean_orphaned_handoffs(main_repo: Path | None = None) -> list[str]:
    """Remove handoff files for branches that no longer exist.

    Args:
        main_repo: Path to main repository. If None, auto-detected.

    Returns:
        List of removed branch names.
    """
    if main_repo is None:
        main_repo = get_main_repo()

    removed = []
    for branch, handoff_file in _orphaned_handoffs(main_repo):
        handoff_file.unlink()
        removed.append(branch)

    return removed


def get_current_branch_context() -> tuple[str, Path] | None:
    """Get the current branch and worktree path.

    Returns:
        Tuple of (branch, worktree_path) or None if not in a git repo.
    """
    try:
        main_repo = get_main_repo()
    except Exception:
        return None

    # Check if we're in a worktree
    cwd = Path.cwd()
    worktrees = list_worktrees(main_repo)

    for wt in worktrees:
        if cwd == wt.path or str(cwd).startswith(str(wt.path) + os.sep):
            return (wt.branch, wt.path)

    # Check if we're in the main repo
    if cwd == main_repo or str(cwd).startswith(str(main_repo) + os.sep):
        branch = get_current_branch(main_repo)
        return (branch or "main", main_repo)

    return None


def get_last_commit(path: Path) -> str:
    """Get last commit summary.

    Args:
        path: Path to repository.

    Returns:
        Commit hash and message.
    """
    result = proc.run(
        ["git", "-C", str(path), "log", "-1", "--format=%h %s"], timeout=10
    )
    return result.stdout.strip() if result.ok else ""


def create_wip_commit(path: Path, message: str | None = None) -> bool:
    """Create a WIP commit.

    Args:
        path: Path to repository.
        message: Optional commit message.

    Returns:
        True if commit was created.
    """
    if not proc.run(["git", "-C", str(path), "add", "-A"], timeout=30).ok:
        return False
    commit_msg = message or "WIP: Handoff checkpoint"
    return proc.run(["git", "-C", str(path), "commit", "-m", commit_msg], timeout=30).ok
