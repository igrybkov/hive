"""Facts for `hive merge-preview`: file overlap between agents, simulated merges.

Silent (a `progress` callback carries the simulation's messages); the
command and its `--watch` board render the dataclasses through
ui/views/merge.py.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ..core.errors import HiveError
from ..git import (
    MergeSimulation,
    get_current_branch,
    get_default_branch,
    get_worktree_path,
    list_worktrees,
    merge_changed_files,
    simulate_merge,
)

Progress = Callable[[str], None]


def _noop(_message: str) -> None:
    return None


@dataclass(frozen=True)
class Overlap:
    """Which agents changed which files relative to the default branch."""

    default_branch: str
    files: dict[str, list[str]]  # file -> agent ids

    def overlapping(self) -> list[tuple[str, list[str]]]:
        """Files touched by more than one agent, sorted by path."""
        return [
            (path, agents)
            for path, agents in sorted(self.files.items())
            if len(agents) > 1
        ]


def collect_overlap(main_repo: Path) -> Overlap:
    """Changed files per worktree against the default branch."""
    default_branch = get_default_branch(main_repo)
    files: dict[str, list[str]] = defaultdict(list)
    for wt in list_worktrees(main_repo):
        agent_id = "1" if wt.is_main else wt.branch
        for path in merge_changed_files(wt.path, default_branch):
            files[path].append(agent_id)
    return Overlap(default_branch, dict(files))


@dataclass(frozen=True)
class MergeTarget:
    """The worktree a merge preview simulates, resolved from an agent id."""

    path: Path
    branch: str
    default_branch: str


def resolve_target(agent_id: str, main_repo: Path) -> MergeTarget:
    """Agent "1" is the main repo; others are the `agent-<id>` worktree.

    Raises HiveError when that worktree does not exist.
    """
    if agent_id == "1":
        path = main_repo
    else:
        path = get_worktree_path(f"agent-{agent_id}", main_repo)
    if not path.exists():
        raise HiveError(f"Agent {agent_id} worktree not found")
    branch = get_current_branch(path) or "detached"
    return MergeTarget(path, branch, get_default_branch(main_repo))


@dataclass(frozen=True)
class MergePreview:
    target: MergeTarget
    simulation: MergeSimulation


def preview(
    agent_id: str, main_repo: Path, *, progress: Progress = _noop
) -> MergePreview:
    """Resolve the target and simulate merging it into the default branch."""
    target = resolve_target(agent_id, main_repo)
    simulation = simulate_merge(
        target.path, main_repo, target.default_branch, progress=progress
    )
    return MergePreview(target, simulation)
