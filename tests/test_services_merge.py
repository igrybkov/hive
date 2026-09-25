"""services/merge.py: overlap and merge-preview facts against real repos."""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import commit_file

from hive_cli.core.errors import HiveError
from hive_cli.services import merge


class TestCollectOverlap:
    def test_main_only_has_no_overlap(self, temp_git_repo: Path):
        overlap = merge.collect_overlap(temp_git_repo)
        assert overlap.default_branch == "main"
        assert overlap.overlapping() == []

    def test_shared_file_lists_both_agents(
        self, temp_git_repo: Path, isolated_worktrees, make_worktree
    ):
        wt_a = make_worktree("agent-a")
        wt_b = make_worktree("agent-b")
        commit_file(wt_a, "shared.txt", "from a\n", "a")
        commit_file(wt_b, "shared.txt", "from b\n", "b")
        commit_file(wt_a, "only-a.txt", "a\n", "a2")

        overlap = merge.collect_overlap(temp_git_repo)

        assert overlap.overlapping() == [("shared.txt", ["agent-a", "agent-b"])]
        assert overlap.files["only-a.txt"] == ["agent-a"]


class TestResolveTarget:
    def test_agent_one_is_the_main_repo(self, temp_git_repo: Path):
        target = merge.resolve_target("1", temp_git_repo)
        assert target.path == temp_git_repo
        assert (target.branch, target.default_branch) == ("main", "main")

    def test_worktree_agent(
        self, temp_git_repo: Path, isolated_worktrees, make_worktree
    ):
        make_worktree("agent-2")
        assert merge.resolve_target("2", temp_git_repo).branch == "agent-2"

    def test_missing_worktree_raises(self, temp_git_repo: Path):
        with pytest.raises(HiveError, match="Agent 9 worktree not found"):
            merge.resolve_target("9", temp_git_repo)


class TestPreview:
    def test_clean_merge(self, temp_git_repo: Path, isolated_worktrees, make_worktree):
        wt = make_worktree("agent-2")
        commit_file(wt, "new.txt", "x\n", "add")
        result = merge.preview("2", temp_git_repo)
        assert result.target.branch == "agent-2"
        assert result.simulation.ok and not result.simulation.conflicts
        assert ("A", "new.txt") in result.simulation.changed
