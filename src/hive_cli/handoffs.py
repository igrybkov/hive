"""Handoff utilities for managing branch handoff files.

Handoff files are stored centrally in the main repo's .claude/handoffs/ directory
and symlinked into worktrees for easy access.
"""

from __future__ import annotations

import os
from pathlib import Path

from .git import get_main_repo, sanitize_branch_name


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

    return handoff_file


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


def clean_orphaned_handoffs(main_repo: Path | None = None) -> list[str]:
    """Remove handoff files for branches that no longer exist.

    Args:
        main_repo: Path to main repository. If None, auto-detected.

    Returns:
        List of removed branch names.
    """
    from .git import get_all_branches, list_worktrees

    if main_repo is None:
        main_repo = get_main_repo()

    # Get all existing branches and worktrees
    all_branches = set(get_all_branches(main_repo))
    worktree_branches = {wt.branch for wt in list_worktrees(main_repo)}
    valid_branches = all_branches | worktree_branches | {"main", "master"}

    removed = []
    for branch, handoff_file in list_handoffs(main_repo):
        if branch not in valid_branches:
            handoff_file.unlink()
            removed.append(branch)

    return removed
