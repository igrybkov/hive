"""Git worktree operations.

Core utilities for managing git worktrees in multi-agent workflows.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from ..config import load_config
from ..core import proc
from .repo import get_main_repo


@dataclass
class WorktreeInfo:
    """Information about a git worktree."""

    branch: str
    path: Path
    is_main: bool = False


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


def _find_existing_worktree(branch: str, main_repo: Path) -> Path | None:
    """Look up the actual path of an existing worktree from git.

    Args:
        branch: Branch name to look up.
        main_repo: Path to main repository.

    Returns:
        Actual path if worktree exists in git, None otherwise.
    """
    for wt in list_worktrees(main_repo):
        if wt.branch == branch:
            return wt.path
    return None


def _compute_worktree_path(branch: str, main_repo: Path) -> Path:
    """Compute the expected worktree path from the parent_dir template.

    This is where a *new* worktree would be created. For existing worktrees,
    use _find_existing_worktree() instead.

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


def get_worktree_path(branch: str, main_repo: Path | None = None) -> Path:
    """Get the path for a worktree given a branch name.

    First checks git's actual worktree list for existing worktrees (which may
    live at a different path than the current template would produce). Falls
    back to computing the path from the parent_dir template for new worktrees.

    Args:
        branch: Branch name (or "main"/"1" for main repo).
        main_repo: Path to main repository. If None, auto-detected.

    Returns:
        Path to the worktree directory.

    Examples:
        >>> get_worktree_path("main")  # Returns main repo path
        >>> get_worktree_path("1")     # Returns main repo path
        >>> get_worktree_path("agent-2")  # Returns .worktrees/agent-2
    """
    if main_repo is None:
        main_repo = get_main_repo()

    # Special cases: "1" or "main" returns main repo
    if branch in ("1", "main"):
        return main_repo

    # Check git's actual worktree list first
    existing = _find_existing_worktree(branch, main_repo)
    if existing is not None:
        return existing

    # No existing worktree - compute where a new one would go
    return _compute_worktree_path(branch, main_repo)


def list_worktrees(main_repo: Path | None = None) -> list[WorktreeInfo]:
    """List all git worktrees for the repository.

    Args:
        main_repo: Path to main repository. If None, auto-detected.

    Returns:
        List of WorktreeInfo objects, main repo first.
    """
    if main_repo is None:
        main_repo = get_main_repo()

    worktrees = [WorktreeInfo(branch="main", path=main_repo, is_main=True)]

    result = proc.run(
        ["git", "-C", str(main_repo), "worktree", "list", "--porcelain"],
        timeout=10,
    )
    if not result.ok:
        return worktrees

    worktrees.extend(_parse_worktree_list(result.stdout, main_repo))
    return worktrees


def _parse_worktree_list(stdout: str, main_repo: Path) -> list[WorktreeInfo]:
    """Parse `git worktree list --porcelain` output into WorktreeInfo entries.

    Args:
        stdout: Raw porcelain output.
        main_repo: Path to main repository (excluded from the result).

    Returns:
        List of non-main WorktreeInfo objects.
    """
    entries: list[WorktreeInfo] = []
    worktree_path = ""
    worktree_branch = ""

    for line in stdout.splitlines():
        if line.startswith("worktree "):
            worktree_path = line[9:]  # Remove "worktree " prefix
        elif line.startswith("branch refs/heads/"):
            worktree_branch = line[18:]  # Remove "branch refs/heads/" prefix
        elif line == "" and worktree_path:
            # End of worktree entry
            wt_path = Path(worktree_path)
            if wt_path != main_repo and worktree_branch:
                entries.append(
                    WorktreeInfo(branch=worktree_branch, path=wt_path, is_main=False)
                )
            worktree_path = ""
            worktree_branch = ""

    # Handle last entry if no trailing newline
    if worktree_path and worktree_branch:
        wt_path = Path(worktree_path)
        if wt_path != main_repo:
            entries.append(
                WorktreeInfo(branch=worktree_branch, path=wt_path, is_main=False)
            )

    return entries


def worktree_exists(branch: str, main_repo: Path | None = None) -> bool:
    """Check if a worktree exists for a branch.

    Checks git's actual worktree list, not the computed path.

    Args:
        branch: Branch name to check.
        main_repo: Path to main repository. If None, auto-detected.

    Returns:
        True if worktree exists, False otherwise.
    """
    # "main" or "1" always exists
    if branch in ("1", "main"):
        return True

    if main_repo is None:
        main_repo = get_main_repo()

    return _find_existing_worktree(branch, main_repo) is not None


def is_worktree_dirty(worktree_path: Path) -> bool:
    """Check if a worktree has uncommitted changes.

    Args:
        worktree_path: Path to the worktree.

    Returns:
        True if worktree has uncommitted changes.
    """
    result = proc.run(
        ["git", "-C", str(worktree_path), "status", "--porcelain"],
        timeout=10,
    )
    if not result.ok:
        return False
    return bool(result.stdout.strip())


def _branch_ref_exists(main_repo: Path, ref: str) -> bool:
    """Check whether a ref (e.g. refs/heads/main) exists in the repo."""
    result = proc.run(
        ["git", "-C", str(main_repo), "show-ref", "--verify", "--quiet", ref],
        timeout=10,
    )
    return result.ok


def get_default_branch(main_repo: Path) -> str:
    """Get the default branch name (main or master).

    Args:
        main_repo: Path to the repository.

    Returns:
        Default branch name ("main" or "master").
    """
    # Check for main first
    if _branch_ref_exists(main_repo, "refs/heads/main"):
        return "main"

    # Check for master
    if _branch_ref_exists(main_repo, "refs/heads/master"):
        return "master"

    # Try to get from origin/HEAD
    result = proc.run(
        ["git", "-C", str(main_repo), "symbolic-ref", "refs/remotes/origin/HEAD"],
        timeout=10,
    )
    if not result.ok:
        return "main"
    # Output is like "refs/remotes/origin/main"
    return result.stdout.strip().split("/")[-1]


def _create_worktree_for_new_branch(
    main_repo: Path, worktree_path: Path, branch: str
) -> None:
    """Create a worktree with a brand-new branch, from origin or local default.

    Args:
        main_repo: Path to main repository.
        worktree_path: Where to create the worktree.
        branch: Name of the new branch.
    """
    default_branch = get_default_branch(main_repo)

    # Try fetching from origin first
    proc.run(
        ["git", "-C", str(main_repo), "fetch", "origin", default_branch],
        timeout=60,
    )

    result = proc.run(
        [
            "git",
            "-C",
            str(main_repo),
            "worktree",
            "add",
            str(worktree_path),
            "-b",
            branch,
            f"origin/{default_branch}",
        ],
        timeout=30,
    )
    if not result.ok:
        # Fallback to local default branch
        proc.run(
            [
                "git",
                "-C",
                str(main_repo),
                "worktree",
                "add",
                str(worktree_path),
                "-b",
                branch,
                default_branch,
            ],
            timeout=30,
            check=True,
        )

    # Set up remote tracking
    proc.run(
        [
            "git",
            "-C",
            str(worktree_path),
            "config",
            f"branch.{branch}.remote",
            "origin",
        ],
        timeout=10,
    )
    proc.run(
        [
            "git",
            "-C",
            str(worktree_path),
            "config",
            f"branch.{branch}.merge",
            f"refs/heads/{branch}",
        ],
        timeout=10,
    )


def create_worktree(branch: str, main_repo: Path | None = None) -> Path:
    """Create a new worktree for a branch.

    If the branch doesn't exist, creates it from the default branch.

    Args:
        branch: Branch name for the worktree.
        main_repo: Path to main repository. If None, auto-detected.

    Returns:
        Path to the created worktree.

    Raises:
        ValueError: If branch is "main" or "1", or if branch is checked out elsewhere.
        FileExistsError: If worktree already exists.
    """
    if branch in ("main", "1"):
        raise ValueError("Cannot create worktree for main branch")

    if main_repo is None:
        main_repo = get_main_repo()

    # Check if branch is currently checked out in main repo
    current_branch = get_current_branch(main_repo)
    if current_branch == branch:
        raise ValueError(
            f"Branch '{branch}' is already checked out in the main repository"
        )

    # Use computed path (not git lookup) since we're creating a new worktree
    worktree_path = _compute_worktree_path(branch, main_repo)

    if worktree_path.exists():
        raise FileExistsError(f"Worktree already exists: {worktree_path}")

    # Ensure parent directory exists
    worktree_path.parent.mkdir(parents=True, exist_ok=True)

    local_branch_exists = _branch_ref_exists(main_repo, f"refs/heads/{branch}")
    remote_branch_exists = _branch_ref_exists(
        main_repo, f"refs/remotes/origin/{branch}"
    )

    if local_branch_exists:
        # Use existing local branch
        proc.run(
            [
                "git",
                "-C",
                str(main_repo),
                "worktree",
                "add",
                str(worktree_path),
                branch,
            ],
            timeout=30,
            check=True,
        )
    elif remote_branch_exists:
        # Create from remote branch
        proc.run(
            [
                "git",
                "-C",
                str(main_repo),
                "worktree",
                "add",
                str(worktree_path),
                "-b",
                branch,
                f"origin/{branch}",
            ],
            timeout=30,
            check=True,
        )
    else:
        _create_worktree_for_new_branch(main_repo, worktree_path, branch)

    # Setup handoff symlink for the worktree
    from ..handoffs import setup_handoff_symlink

    setup_handoff_symlink(worktree_path, branch, main_repo)

    return worktree_path


def get_current_branch(repo_path: Path) -> str | None:
    """Get the current branch name for a repository.

    Args:
        repo_path: Path to the repository.

    Returns:
        Branch name, or None if detached HEAD.
    """
    result = proc.run(
        ["git", "-C", str(repo_path), "branch", "--show-current"],
        timeout=10,
    )
    if not result.ok:
        return None
    branch = result.stdout.strip()
    return branch if branch else None


def get_all_branches(main_repo: Path | None = None) -> list[str]:
    """Get all branches (local and remote) for the repository.

    Args:
        main_repo: Path to main repository. If None, auto-detected.

    Returns:
        List of unique branch names (without origin/ prefix).
    """
    if main_repo is None:
        main_repo = get_main_repo()

    result = proc.run(
        [
            "git",
            "-C",
            str(main_repo),
            "branch",
            "-a",
            "--format=%(refname:short)",
        ],
        timeout=10,
    )
    if not result.ok:
        return []

    branches = set()
    for line in result.stdout.splitlines():
        branch = line.strip()
        if not branch:
            continue
        # Skip origin/HEAD and bare "origin" (from HEAD shortening)
        if branch in ("origin/HEAD", "origin"):
            continue
        # Remove origin/ prefix
        if branch.startswith("origin/"):
            branch = branch[7:]
        branches.add(branch)

    return sorted(branches)


def fetch_origin(main_repo: Path | None = None) -> bool:
    """Fetch from origin to get latest branch info.

    Args:
        main_repo: Path to main repository. If None, auto-detected.

    Returns:
        True if fetch succeeded.
    """
    if main_repo is None:
        main_repo = get_main_repo()

    result = proc.run(["git", "-C", str(main_repo), "fetch", "origin"], timeout=60)
    return result.ok


def delete_worktree(worktree_path: Path, force: bool = False) -> None:
    """Delete a worktree.

    Args:
        worktree_path: Path to the worktree.
        force: If True, force deletion even if dirty.

    Raises:
        ValueError: If worktree is dirty and force is False.
        core.errors.ProcError: If git operation fails.
    """
    if not force and is_worktree_dirty(worktree_path):
        raise ValueError("Worktree has uncommitted changes. Use force=True to delete.")

    main_repo = get_main_repo()

    cmd = ["git", "-C", str(main_repo), "worktree", "remove", str(worktree_path)]
    if force:
        cmd.append("--force")
    result = proc.run(cmd, timeout=30)
    if not result.ok:
        # Fallback: remove directory and prune
        import shutil

        shutil.rmtree(worktree_path, ignore_errors=True)
        proc.run(
            ["git", "-C", str(main_repo), "worktree", "prune"],
            timeout=30,
        )
