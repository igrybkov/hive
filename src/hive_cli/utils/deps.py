"""Dependency installation utilities.

Handles auto-detection and installation of project dependencies
using configuration from .hive.yml or built-in defaults.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from ..config import load_config


def setup_worktree_files(worktree_path: Path, main_repo: Path) -> bool:
    """Symlink and copy files from main repo to worktree.

    Processes ``worktrees.symlink_files`` and ``worktrees.copy_files``
    from configuration, creating symlinks or copies in the worktree
    that point back to the main repository.

    Args:
        worktree_path: Path to the new worktree.
        main_repo: Path to the main repository.

    Returns:
        True if all files were set up successfully.
    """
    config = load_config()
    all_ok = True

    for rel in config.worktrees.symlink_files:
        if not _setup_file(worktree_path, main_repo, rel, copy=False):
            all_ok = False

    for rel in config.worktrees.copy_files:
        if not _setup_file(worktree_path, main_repo, rel, copy=True):
            all_ok = False

    return all_ok


def _setup_file(worktree_path: Path, main_repo: Path, rel: str, *, copy: bool) -> bool:
    """Set up a single file (symlink or copy) in the worktree.

    Args:
        worktree_path: Path to the worktree.
        main_repo: Path to the main repository.
        rel: Relative path of the file.
        copy: If True, copy the file; otherwise, create a symlink.

    Returns:
        True if successful.
    """
    from .terminal import warn

    if Path(rel).is_absolute():
        warn(f"Skipping absolute path: {rel}")
        return False

    source = main_repo / rel
    target = worktree_path / rel

    if not source.exists():
        warn(f"Source does not exist, skipping: {source}")
        return False

    if target.exists() or target.is_symlink():
        warn(f"Target already exists, skipping: {target}")
        return False

    target.parent.mkdir(parents=True, exist_ok=True)

    if copy:
        shutil.copy2(source, target)
    else:
        target.symlink_to(source)

    return True


def run_post_create_commands(path: Path, quiet: bool = True) -> bool:
    """Run post_create commands from configuration.

    Executes commands defined in worktrees.post_create, respecting
    the if_exists conditions.

    Args:
        path: Path to the worktree directory.
        quiet: If True, suppress output.

    Returns:
        True if all commands succeeded or were skipped.
    """
    config = load_config()
    all_success = True

    for cmd in config.worktrees.post_create:
        # Check if_exists condition
        if cmd.if_exists:
            check_path = path / cmd.if_exists
            if not check_path.exists():
                continue

        # Run the command
        try:
            subprocess.run(
                cmd.command,
                shell=True,
                cwd=path,
                capture_output=quiet,
                check=True,
            )
        except subprocess.CalledProcessError:
            all_success = False

    return all_success


def ensure_mise_trusted(path: Path) -> bool:
    """Ensure mise config is trusted for a path.

    Args:
        path: Path to check and trust.

    Returns:
        True if mise config was trusted or already trusted.
    """
    if not shutil.which("mise"):
        return True

    config_files = [
        path / ".mise.toml",
        path / "mise.toml",
        path / ".tool-versions",
    ]

    if not any(f.exists() for f in config_files):
        return True

    # Check if already trusted by running mise list
    try:
        subprocess.run(
            ["mise", "list"],
            cwd=path,
            capture_output=True,
            check=True,
        )
        return True
    except subprocess.CalledProcessError:
        pass

    # Trust the config
    try:
        subprocess.run(
            ["mise", "trust"],
            cwd=path,
            capture_output=True,
            check=True,
        )
        return True
    except subprocess.CalledProcessError:
        return False


def install_dependencies(path: Path, quiet: bool = True) -> bool:
    """Install project dependencies using post_create commands.

    Uses configuration from .hive.yml/.hive.local.yml for commands.

    Args:
        path: Path to the project directory.
        quiet: If True, suppress output.

    Returns:
        True if dependencies were installed successfully.
    """
    return run_post_create_commands(path, quiet=quiet)


# Legacy functions for backward compatibility


def detect_package_manager(path: Path) -> str | None:
    """Detect the package manager for a project.

    Note: This is kept for backward compatibility. New code should
    use run_post_create_commands() which handles all dependency types.

    Args:
        path: Path to the project directory.

    Returns:
        Package manager name ("pnpm", "yarn", "npm", "uv"), or None.
    """
    # Node.js package managers
    if (path / "package.json").exists():
        if (path / "pnpm-lock.yaml").exists():
            return "pnpm"
        if (path / "yarn.lock").exists():
            return "yarn"
        if (path / "package-lock.json").exists():
            return "npm"
        return "npm"  # Default for Node.js projects

    # Python with uv
    if (path / "pyproject.toml").exists() or (path / "requirements.txt").exists():
        if shutil.which("uv"):
            return "uv"

    return None
