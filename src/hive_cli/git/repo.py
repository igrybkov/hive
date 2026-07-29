"""Git repository utilities."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


def get_git_root() -> Path | None:
    """Get the root directory of the current git repository.

    Returns:
        Resolved path to git root, or None if not in a git repository.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        )
        return Path(result.stdout.strip()).resolve()
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return None


def get_main_repo() -> Path:
    """Get the main repository path (not worktree).

    For worktrees, this returns the path to the main repository.
    For main repositories, returns the repository path.

    Returns:
        Path to the main repository, or current directory if not in a git repo.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            capture_output=True,
            text=True,
            check=True,
        )
        git_common_dir = Path(result.stdout.strip())
        # Main repo is parent of .git directory
        return git_common_dir.resolve().parent
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        try:
            return Path.cwd()
        except (FileNotFoundError, OSError):
            raise RuntimeError(
                "Current directory no longer exists — navigate to a valid path first."
            ) from None


def get_session_name() -> str:
    """Get a session name based on the repository name.

    Returns:
        Lowercase session name derived from repository directory name.
    """
    main_repo = get_main_repo()
    return main_repo.name.lower().replace(" ", "-")


def change_to_git_root() -> Path | None:
    """Change to the git root directory if available.

    Returns:
        Path to git root if changed, None otherwise.
    """
    git_root = get_git_root()
    if git_root:
        os.chdir(git_root)
        return git_root
    return None


def change_to_main_repo() -> Path:
    """Change to the main repository directory.

    Returns:
        Path to main repository.
    """
    main_repo = get_main_repo()
    os.chdir(main_repo)
    return main_repo


def get_current_worktree_branch() -> str | None:
    """Get the branch name if currently inside a worktree (not main repo).

    Returns:
        Branch name if in a worktree, None if in main repo or not in git repo.
    """
    git_root = get_git_root()
    if git_root is None:
        return None

    main_repo = get_main_repo()

    # If we're in the main repo, not a worktree
    if git_root == main_repo:
        return None

    # We're in a worktree - get the branch name
    try:
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True,
            text=True,
            check=True,
        )
        branch = result.stdout.strip()
        return branch if branch else None
    except subprocess.CalledProcessError:
        return None
