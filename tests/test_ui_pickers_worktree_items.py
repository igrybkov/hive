"""Tests for ui/pickers/worktree_items.py: the one-spawn first paint and compose."""

from __future__ import annotations

from pathlib import Path

from conftest import git

from hive_cli.git.github import GitHubIssue
from hive_cli.git.status import GitSummary
from hive_cli.git.worktree import WorktreeInfo
from hive_cli.ui.pickers.worktree_items import (
    ACTION_ISSUE_PREFIX,
    PickerItems,
    first_paint,
)


def summary(**overrides) -> GitSummary:
    base = dict(
        branch="feat",
        upstream="",
        ahead=0,
        behind=0,
        staged=0,
        modified=0,
        untracked=0,
        conflicted=0,
        last_hash="",
        last_subject="",
        last_age="",
    )
    return GitSummary(**{**base, **overrides})


class TestFirstPaint:
    def test_main_and_worktrees_listed(
        self, temp_git_repo, make_worktree, isolated_worktrees
    ):
        make_worktree("feat-a")
        make_worktree("feat-b")

        _sections, items, _selection = first_paint(temp_git_repo)

        by_value = {item.value: item for item in items}
        assert by_value["main"].text == "main"
        assert by_value["main"].meta == "[repo]"
        assert by_value["main"].style == "bold green"
        assert by_value["feat-a"].style == "green"
        assert by_value["feat-b"].style == "green"

    def test_dirty_worktree_still_shown_clean_before_refinement(
        self, temp_git_repo, make_worktree, isolated_worktrees
    ):
        wt_path = make_worktree("feat-b")
        (wt_path / "dirty.txt").write_text("uncommitted")

        _sections, items, _selection = first_paint(temp_git_repo)
        by_value = {item.value: item for item in items}

        assert by_value["feat-b"].style == "green"
        assert by_value["feat-b"].meta == ""

    def test_current_worktree_branch_marked(
        self, temp_git_repo, make_worktree, isolated_worktrees
    ):
        make_worktree("feat-a")

        _sections, items, _selection = first_paint(
            temp_git_repo, current_worktree_branch="feat-a"
        )
        by_value = {item.value: item for item in items}
        assert by_value["feat-a"].meta == "← current"

    def test_main_on_other_branch_shows_it_without_a_second_spawn(
        self, temp_git_repo, isolated_worktrees, fake_proc
    ):
        listing = f"worktree {temp_git_repo}\nHEAD abc\nbranch refs/heads/topic\n\n"
        fake_proc.script(("git", "worktree", "list"), stdout=listing)

        _sections, items, _selection = first_paint(temp_git_repo)

        assert items[0].meta == "[repo @ topic]"
        assert fake_proc.calls == [["git", "worktree", "list", "--porcelain"]]

    def test_preselect_branch_sets_initial_selection(
        self, temp_git_repo, make_worktree, isolated_worktrees
    ):
        make_worktree("feat-a")
        make_worktree("feat-b")

        _sections, items, selection = first_paint(
            temp_git_repo, preselect_branch="feat-b"
        )
        assert items[selection].value == "feat-b"

    def test_preselect_main(self, temp_git_repo, make_worktree, isolated_worktrees):
        make_worktree("feat-a")

        _sections, items, selection = first_paint(
            temp_git_repo, preselect_branch="main"
        )
        assert items[selection].value == "main"

    def test_no_worktrees_lists_main_only(self, temp_git_repo, isolated_worktrees):
        _sections, items, selection = first_paint(temp_git_repo)
        assert len(items) == 1
        assert items[0].value == "main"
        assert selection == 0

    def test_branches_are_not_part_of_the_first_paint(
        self, temp_git_repo, isolated_worktrees
    ):
        git("branch", "feat-c", cwd=temp_git_repo)
        _sections, items, _selection = first_paint(temp_git_repo)
        assert [item.value for item in items] == ["main"]


class TestPickerItemsCompose:
    def _sections(self, **kwargs) -> PickerItems:
        worktrees = [
            WorktreeInfo("main", Path("/r"), is_main=True, head="main"),
            WorktreeInfo("feat", Path("/r-feat"), head="feat"),
        ]
        return PickerItems(worktrees, None, None, **kwargs)

    def test_summaries_add_dirty_and_ahead_behind_meta(self):
        sections = self._sections(
            summaries={Path("/r-feat"): summary(untracked=1, ahead=2, behind=1)}
        )
        items, _ = sections.compose()
        feat = {i.value: i for i in items}["feat"]
        assert feat.meta == "(dirty) +2 -1"
        assert feat.style == "yellow"

    def test_current_and_dirty_meta(self):
        sections = self._sections(summaries={Path("/r-feat"): summary(modified=1)})
        sections.current_worktree_branch = "feat"
        items, _ = sections.compose()
        assert {i.value: i for i in items}["feat"].meta == "← current (dirty)"

    def test_clean_summary_keeps_worktree_green(self):
        sections = self._sections(summaries={Path("/r-feat"): summary()})
        feat = {i.value: i for i in sections.compose()[0]}["feat"]
        assert feat.meta == "" and feat.style == "green"

    def test_branches_shown_dim_and_worktree_branches_excluded(self):
        sections = self._sections(branches=["feat", "other", "main"])
        items, _ = sections.compose()
        assert [i.value for i in items] == ["main", "feat", "other"]
        assert {i.value: i for i in items}["other"].style == "dim"

    def test_branch_checked_out_in_main_repo_is_excluded(self):
        worktrees = [WorktreeInfo("main", Path("/r"), is_main=True, head="topic")]
        sections = PickerItems(worktrees, None, None, branches=["topic", "other"])
        items, _ = sections.compose()
        assert [i.value for i in items] == ["main", "other"]
        assert items[0].meta == "[repo @ topic]"

    def test_preselect_plain_branch(self):
        sections = self._sections(branches=["other"])
        sections.select_branch = "other"
        items, selection = sections.compose()
        assert items[selection].value == "other"

    def test_issues_appended_unless_a_branch_exists(self):
        sections = self._sections(
            branches=["gh-9-do-the-thing"],
            issues=[GitHubIssue(9, "Do the thing"), GitHubIssue(12, "x" * 80)],
        )
        items, _ = sections.compose()
        issue_items = [i for i in items if i.value.startswith(ACTION_ISSUE_PREFIX)]
        assert len(issue_items) == 1
        assert "12" in issue_items[0].text and issue_items[0].style == "cyan"
        assert issue_items[0].text.endswith("...")
