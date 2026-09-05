"""Git analysis helpers: rebase status, diffs, merge-conflict simulation.

Pure git logic -- no printing. `simulate_merge` takes a `progress` callback
for incremental status lines instead of printing directly; the printed text
itself is unchanged, only which layer calls Console has moved (see
docs/ARCHITECTURE.md).
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from ..core import proc

Progress = Callable[[str], None]


def _noop(_msg: str) -> None:
    pass


# --- rebase-check helpers (commands/rebase.py) ---


def fetch_branch(main_repo: Path, branch: str) -> bool:
    """Fetch a single branch from origin, quietly.

    Distinct from worktree.fetch_origin(), which fetches everything.

    Args:
        main_repo: Path to main repository.
        branch: Branch name to fetch.

    Returns:
        True if fetch succeeded.
    """
    result = proc.run(
        ["git", "-C", str(main_repo), "fetch", "origin", branch, "--quiet"],
        timeout=60,
    )
    return result.ok


def commits_ahead_behind(path: Path, default_branch: str) -> tuple[int, int]:
    """Get commits ahead/behind origin/default_branch.

    Args:
        path: Path to worktree.
        default_branch: Default branch name.

    Returns:
        Tuple of (ahead, behind) counts.
    """
    result = proc.run(
        [
            "git",
            "-C",
            str(path),
            "rev-list",
            "--count",
            f"HEAD..origin/{default_branch}",
        ],
        timeout=10,
    )
    try:
        behind = int(result.stdout.strip()) if result.ok else 0
    except ValueError:
        behind = 0

    result = proc.run(
        [
            "git",
            "-C",
            str(path),
            "rev-list",
            "--count",
            f"origin/{default_branch}..HEAD",
        ],
        timeout=10,
    )
    try:
        ahead = int(result.stdout.strip()) if result.ok else 0
    except ValueError:
        ahead = 0

    return ahead, behind


def changed_files(path: Path, default_branch: str, limit: int = 5) -> list[str]:
    """Get changed files that may conflict.

    Args:
        path: Path to worktree.
        default_branch: Default branch name.
        limit: Maximum number of files to return.

    Returns:
        List of changed file names.
    """
    result = proc.run(
        ["git", "-C", str(path), "diff", "--name-only", f"origin/{default_branch}"],
        timeout=10,
    )
    if not result.ok:
        return []
    return result.stdout.strip().splitlines()[:limit]


# --- diff helpers (commands/diff.py) ---


def has_delta() -> bool:
    """Check if delta pager is available."""
    return shutil.which("delta") is not None


def get_diff(
    path: Path,
    default_branch: str,
    stat: bool = False,
    files_only: bool = False,
) -> str:
    """Get diff for a worktree.

    Args:
        path: Path to worktree.
        default_branch: Default branch to diff against.
        stat: If True, show diffstat.
        files_only: If True, show only changed file names.

    Returns:
        Diff output string.
    """
    cmd = ["git", "-C", str(path), "diff"]

    if files_only:
        cmd.append("--name-only")
    elif stat:
        cmd.append("--stat")

    cmd.append(default_branch)

    result = proc.run(cmd, timeout=10)
    return result.stdout if result.ok else ""


def show_diff_with_delta(path: Path, default_branch: str) -> bool:
    """Stream a diff through the delta pager.

    Raw subprocess (not proc.run): the git process's stdout is piped
    directly into delta's stdin so delta can render straight to the
    terminal -- there is no captured output to return.

    Args:
        path: Path to worktree.
        default_branch: Default branch to diff against.

    Returns:
        True if diff was shown.
    """
    try:
        git_proc = subprocess.Popen(
            ["git", "-C", str(path), "diff", default_branch],
            stdout=subprocess.PIPE,
        )
        delta_proc = subprocess.Popen(
            ["delta"],
            stdin=git_proc.stdout,
        )
        git_proc.stdout.close()
        delta_proc.communicate()
        return True
    except subprocess.CalledProcessError:
        return False


# --- merge-preview helpers (commands/merge.py) ---

# Files hive itself places into every worktree (see handoffs.setup_handoff_symlink).
# They end up committed by `git add -A` and would be reported as a false overlap.
HIVE_MANAGED_FILES = frozenset({".claude/HANDOFF.md"})


def merge_changed_files(path: Path, default_branch: str) -> list[str]:
    """Get files changed compared to default branch.

    Args:
        path: Path to worktree.
        default_branch: Default branch name.

    Returns:
        List of changed file names, excluding files managed by hive itself.
    """
    result = proc.run(
        ["git", "-C", str(path), "diff", "--name-only", default_branch],
        timeout=10,
    )
    if not result.ok:
        return []
    return [
        f
        for f in result.stdout.strip().splitlines()
        if f and f not in HIVE_MANAGED_FILES
    ]


@dataclass
class MergeSimulation:
    """Result of simulating a merge in a throwaway clone."""

    ok: bool
    error: str | None = None
    conflicts: bool = False
    changed: list[tuple[str, str]] = field(default_factory=list)
    conflicting_files: list[str] = field(default_factory=list)


def _clone_and_checkout(
    main_repo: Path, temp_path: Path, default_branch: str, progress: Progress
) -> str | None:
    """Clone main_repo into temp_path and check out default_branch.

    Returns:
        An error message on failure, None on success.
    """
    progress("[cyan]Attempting merge simulation...[/]")
    progress("")

    result = proc.run(
        ["git", "clone", "--quiet", "--shared", str(main_repo), str(temp_path)],
        timeout=30,
    )
    if not result.ok:
        return "Failed to create test environment"

    result = proc.run(
        ["git", "-C", str(temp_path), "checkout", "--quiet", default_branch],
        timeout=30,
    )
    if not result.ok:
        return f"Failed to checkout {default_branch}"

    return None


def _collect_merge_success(temp_path: Path) -> list[tuple[str, str]]:
    """Collect (status, file_path) pairs for a merge that succeeded."""
    result = proc.run(
        ["git", "-C", str(temp_path), "diff", "--cached", "--name-status"],
        timeout=10,
    )
    changed = []
    for line in result.stdout.strip().splitlines():
        if not line:
            continue
        parts = line.split("\t", 1)
        if len(parts) == 2:
            changed.append((parts[0], parts[1]))
    return changed


def _collect_merge_conflicts(temp_path: Path) -> list[str]:
    """Collect conflicting file paths for a merge that failed."""
    result = proc.run(
        ["git", "-C", str(temp_path), "diff", "--name-only", "--diff-filter=U"],
        timeout=10,
    )
    return [line for line in result.stdout.strip().splitlines() if line]


def simulate_merge(
    path: Path,
    main_repo: Path,
    default_branch: str,
    *,
    progress: Progress = _noop,
) -> MergeSimulation:
    """Simulate merging path's branch into default_branch in a throwaway clone.

    Args:
        path: Path to the worktree whose branch is being merged.
        main_repo: Path to main repository (cloned with --shared).
        default_branch: Branch to merge into.
        progress: Callback for incremental status lines.

    Returns:
        MergeSimulation describing the outcome.
    """
    result = proc.run(["git", "-C", str(path), "rev-parse", "HEAD"], timeout=10)
    if not result.ok:
        return MergeSimulation(ok=False, error="Failed to get branch commit")
    branch_commit = result.stdout.strip()

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)

        error = _clone_and_checkout(main_repo, temp_path, default_branch, progress)
        if error is not None:
            return MergeSimulation(ok=False, error=error)

        merge_result = proc.run(
            [
                "git",
                "-C",
                str(temp_path),
                "merge",
                "--no-commit",
                "--no-ff",
                branch_commit,
            ],
            timeout=30,
        )

        if merge_result.ok:
            changed = _collect_merge_success(temp_path)
            proc.run(["git", "-C", str(temp_path), "merge", "--abort"], timeout=10)
            return MergeSimulation(ok=True, conflicts=False, changed=changed)

        conflicting_files = _collect_merge_conflicts(temp_path)
        proc.run(["git", "-C", str(temp_path), "merge", "--abort"], timeout=10)
        return MergeSimulation(
            ok=True, conflicts=True, conflicting_files=conflicting_files
        )
