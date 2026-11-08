"""Worktree provisioning helpers: file setup, dependency installation.

NOTE (A0 step 6, partial move): moved from utils/deps.py, converting
subprocess -> proc.run. `quiet=False` no longer streams live output --
proc.run always captures -- but no caller in this codebase ever passes
quiet=False (the default is always used), so this is unreachable in
practice.

`provision()`/`remove()`/`setup_agent_context()` (moved from commands/wt.py's
`_create_worktree_flow`/`_delete_worktree_flow`/`_setup_agent_context`, A0
wt.py pass) own only the data ops: `provision()` takes a `progress` callback
instead of printing directly, and lets `create_worktree()` exceptions
propagate -- the try/except and its `error(...)` text stay in the calling
flow. `remove()` similarly takes a `confirmed` bool instead of calling
`confirm()` itself -- both wt.py's and status.py's delete flows have their
own protected/missing/dirty checks and confirm/print text (deliberately not
unified, see A0-architecture.md's pre-flight findings), so `remove()` only
owns the `delete_worktree()` call once the caller has already confirmed.

The handoff symlink used to be set up inside git/worktree.py's
`create_worktree()`; it moves here so git/worktree.py no longer needs to
import the services-layer `handoffs` module. Every caller of
`create_worktree()` that isn't `provision()` (the `wt create` command, and
the `make_worktree` test fixture) now calls `handoffs.setup_handoff_symlink`
explicitly to keep the same behavior.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from ..config import load_config
from ..core import proc
from ..git import create_worktree, delete_worktree, get_worktree_path
from . import handoffs


def _noop(_message: str) -> None:
    pass


def setup_worktree_files(
    worktree_path: Path,
    main_repo: Path,
    *,
    progress: Callable[[str], None] = _noop,
) -> bool:
    """Symlink and copy files from main repo to worktree.

    Processes ``worktrees.symlink_files`` and ``worktrees.copy_files``
    from configuration, creating symlinks or copies in the worktree
    that point back to the main repository.

    Args:
        worktree_path: Path to the new worktree.
        main_repo: Path to the main repository.
        progress: Called with human-readable warning lines.

    Returns:
        True if all files were set up successfully.
    """
    config = load_config()
    all_ok = True

    for rel in config.worktrees.symlink_files:
        if not _setup_file(
            worktree_path, main_repo, rel, copy=False, progress=progress
        ):
            all_ok = False

    for rel in config.worktrees.copy_files:
        if not _setup_file(worktree_path, main_repo, rel, copy=True, progress=progress):
            all_ok = False

    return all_ok


def _setup_file(
    worktree_path: Path,
    main_repo: Path,
    rel: str,
    *,
    copy: bool,
    progress: Callable[[str], None] = _noop,
) -> bool:
    """Set up a single file (symlink or copy) in the worktree.

    Args:
        worktree_path: Path to the worktree.
        main_repo: Path to the main repository.
        rel: Relative path of the file.
        copy: If True, copy the file; otherwise, create a symlink.
        progress: Called with human-readable warning lines.

    Returns:
        True if successful.
    """
    if Path(rel).is_absolute():
        progress(f"Skipping absolute path: {rel}")
        return False

    source = main_repo / rel
    target = worktree_path / rel

    if not source.exists():
        progress(f"Source does not exist, skipping: {source}")
        return False

    if target.exists() or target.is_symlink():
        progress(f"Target already exists, skipping: {target}")
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
    the if_exists conditions. Each command string runs through
    `sh -c` (not subprocess's own shell=True) so it goes through
    core.proc.run like every other spawn.

    Args:
        path: Path to the worktree directory.
        quiet: Unused now that proc.run always captures; kept for signature
            compatibility with existing callers (none pass quiet=False).

    Returns:
        True if all commands succeeded or were skipped.
    """
    del quiet
    config = load_config()
    all_success = True

    for cmd in config.worktrees.post_create:
        # Check if_exists condition
        if cmd.if_exists:
            check_path = path / cmd.if_exists
            if not check_path.exists():
                continue

        result = proc.run(["sh", "-c", cmd.command], cwd=path, timeout=600)
        if not result.ok:
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
    if proc.run(["mise", "list"], cwd=path, timeout=10).ok:
        return True

    # Trust the config
    return proc.run(["mise", "trust"], cwd=path, timeout=10).ok


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


def setup_agent_context(worktree_path: Path, agent_num: int, branch_name: str) -> None:
    """Create agent context file in the worktree.

    Args:
        worktree_path: Path to the worktree.
        agent_num: Agent number.
        branch_name: Branch name.
    """
    claude_dir = worktree_path / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)

    context_file = claude_dir / "worktree-context.md"
    context_file.write_text(f"""# Agent {agent_num} Worktree Context

- **Agent**: {agent_num}
- **Branch**: {branch_name}
- **Worktree**: {worktree_path}
- **Created**: {datetime.now().isoformat()}

## Guidelines

- Work only within this worktree directory
- Commit frequently to preserve work
- This worktree is isolated from other agents
""")


def provision(
    branch: str,
    main_repo: Path,
    *,
    agent_num: int = 0,
    progress: Callable[[str], None] = _noop,
) -> Path:
    """Create a worktree, set up its files, symlink the handoff, install deps.

    Exceptions from create_worktree() (ValueError, FileExistsError, ...)
    propagate to the caller, which owns the try/except and its own error
    text (see the module docstring).

    Args:
        branch: Branch name.
        main_repo: Path to main repository.
        agent_num: Agent number; > 0 also writes a worktree-context.md.
        progress: Called with human-readable progress lines.

    Returns:
        Path to the created worktree.
    """
    progress(f"Creating worktree for: {branch}")
    path = create_worktree(branch, main_repo)
    progress(f"Created worktree at {path}")

    setup_worktree_files(path, main_repo, progress=progress)
    handoffs.setup_handoff_symlink(path, branch, main_repo)

    progress("Installing dependencies...")
    if install_dependencies(path):
        progress("Dependencies installed")
    else:
        progress("Some dependencies may have failed")

    if agent_num > 0:
        setup_agent_context(path, agent_num, branch)

    return path


def remove(branch: str, main_repo: Path, *, confirmed: bool) -> tuple[bool, str | None]:
    """Delete the worktree for a branch.

    Callers own the protected-branch/missing-worktree/dirty checks and the
    confirm() prompt (their printed text deliberately diverges, see the
    module docstring); this only performs the actual git removal, and only
    when the caller has already confirmed.

    Args:
        branch: Branch name of worktree to delete.
        main_repo: Path to main repository.
        confirmed: Whether the caller's confirmation prompt was accepted.

    Returns:
        Tuple of (deleted, error_message). error_message is set only when
        deleted is False because delete_worktree() raised.
    """
    if not confirmed:
        return False, None

    path = get_worktree_path(branch, main_repo)
    try:
        delete_worktree(path, force=True)
        return True, None
    except Exception as e:
        return False, str(e)
