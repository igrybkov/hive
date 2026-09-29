"""Worktree path computation: templates, sanitization, and the base directory.

Split out of git/worktree.py (A0 wt.py pass) to keep that module under the
600-line cap. No dependency on worktree.py: everything here is pure path
arithmetic plus config lookups.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from ..config import load_config
from .repo import get_main_repo


def sanitize_branch_name(branch: str) -> str:
    """Sanitize branch name for filesystem use.

    Converts slashes to double dashes to avoid path collisions.

    Args:
        branch: The git branch name.

    Returns:
        A filesystem-safe version of the branch name.

    Examples:
        >>> sanitize_branch_name("user/feat/update")
        'user--feat--update'
        >>> sanitize_branch_name("feat-test")
        'feat-test'
    """
    # Replace slashes with double dash (to distinguish from single dashes)
    sanitized = branch.replace("/", "--")
    # Replace any remaining special chars (not alphanumeric, dash, underscore, dot)
    sanitized = re.sub(r"[^a-zA-Z0-9_.-]", "-", sanitized)
    # Trim leading/trailing dashes
    return sanitized.strip("-")


def expand_path(path_str: str, main_repo: Path) -> Path:
    """Expand a path string, handling ~, env vars, and relative paths.

    Args:
        path_str: Path string that may contain ~ or be relative.
        main_repo: Main repository path for resolving relative paths.

    Returns:
        Resolved absolute Path.
    """
    # Expand ~ and environment variables
    expanded = os.path.expanduser(os.path.expandvars(path_str))
    path = Path(expanded)

    # If relative, resolve against main_repo
    if not path.is_absolute():
        path = (main_repo / path).resolve()

    return path


def _path_to_name(path: Path) -> str:
    """Convert a path to a double-dash-separated name relative to home.

    Args:
        path: The path to convert.

    Returns:
        A double-dash-separated name (e.g., "Projects--dotfiles").
    """
    home = Path.home()
    try:
        relative = path.relative_to(home)
        return str(relative).replace("/", "--")
    except ValueError:
        # Path is not under home - use full path
        return str(path).lstrip("/").replace("/", "--")


def get_worktrees_base(main_repo: Path | None = None) -> Path:
    """Get the base directory for worktrees.

    Expands ~ and {repo} in worktrees.parent_dir. When {branch} is also
    present, the base is everything before the {branch} portion.

    Args:
        main_repo: Path to main repository. If None, auto-detected.

    Returns:
        Path to the worktrees base directory.
    """
    if main_repo is None:
        main_repo = get_main_repo()

    config = load_config()
    template = config.worktrees.parent_dir
    repo_name = _path_to_name(main_repo)

    if "{branch}" in template:
        # Strip from {branch} onwards to get the base
        template = template.split("{branch}")[0].rstrip("/")

    if "{repo}" in template:
        template = template.replace("{repo}", repo_name)
    elif "{branch}" not in config.worktrees.parent_dir:
        # No placeholders at all - worktrees for different repos would
        # collide, so the base already groups by repo name implicitly
        pass

    return expand_path(template, main_repo)


def compute_worktree_path(branch: str, main_repo: Path) -> Path:
    """Compute the expected worktree path from the parent_dir template.

    This is where a *new* worktree would be created. For existing worktrees,
    use git/worktree.py's get_worktree_path() instead.

    Args:
        branch: Branch name.
        main_repo: Path to main repository.

    Returns:
        Computed path based on the parent_dir template.
    """
    config = load_config()
    template = config.worktrees.parent_dir
    safe_branch = sanitize_branch_name(branch)
    repo_name = _path_to_name(main_repo)

    if "{branch}" in template:
        # Full template: expand all placeholders and return directly
        expanded = template.replace("{repo}", repo_name).replace(
            "{branch}", safe_branch
        )
        return expand_path(expanded, main_repo)

    base = get_worktrees_base(main_repo)

    if "{repo}" in template:
        # Repo in path, branch as subdirectory
        return base / safe_branch

    # No placeholders: flat format with repo prefix
    return base / f"{repo_name}--{safe_branch}"
