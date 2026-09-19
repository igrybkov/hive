"""Tests for services/handoffs.py.

Moved from test_cli_handoff.py (A0 step 6): handoffs.py's contents and
commands/handoff.py:41-135 (`_get_current_branch_context`, `_get_last_commit`,
`_create_wip_commit`) now live in services/handoffs.py, dropping their leading
underscore now that they're cross-module service functions.
`_format_handoff_preview` stays in commands/handoff.py (tested in
test_cli_handoff.py) until ui/views/ exists (step 7).
"""

from __future__ import annotations

import os
from pathlib import Path

from conftest import git

from hive_cli.services.handoffs import (
    clean_orphaned_handoffs,
    create_wip_commit,
    delete_handoff,
    ensure_handoffs_dir,
    get_current_branch_context,
    get_handoff_file,
    get_handoffs_dir,
    get_last_commit,
    has_handoff_content,
    list_handoffs,
    preview_orphaned_handoffs,
    setup_handoff_symlink,
)


def delete_cwd(monkeypatch, tmp_path: Path) -> None:
    """Chdir into a dir, then remove it out from under the process.

    The only reliable, non-mocked way to make ``get_main_repo()`` (and
    therefore ``get_current_branch_context()``) actually raise: it swallows
    every git failure and falls back to ``Path.cwd()``, so a plain "not a
    git repo" directory is not enough on its own.
    """
    gone = tmp_path / "gone"
    gone.mkdir()
    monkeypatch.chdir(gone)
    os.rmdir(gone)


# ---------------------------------------------------------------------------
# get_current_branch_context
# ---------------------------------------------------------------------------


class TestGetCurrentBranchContext:
    def test_returns_none_outside_any_repo(self, tmp_path, monkeypatch):
        delete_cwd(monkeypatch, tmp_path)
        assert get_current_branch_context() is None

    def test_returns_branch_and_path_in_main_repo_and_worktree(
        self, temp_git_repo, isolated_worktrees, make_worktree, monkeypatch
    ):
        assert get_current_branch_context() == ("main", temp_git_repo)

        wt_path = make_worktree("feat")
        monkeypatch.chdir(wt_path)
        assert get_current_branch_context() == ("feat", wt_path)

    def test_main_repo_on_non_main_branch_still_reports_main(self, temp_git_repo):
        """Documents a bug: list_worktrees() always prepends a synthetic
        WorktreeInfo(branch="main", path=main_repo) entry, matched by
        *path* in the loop before the (correct) get_current_branch()
        lookup below it ever runs. So the main repo always reports "main"
        regardless of what's actually checked out. See the bug write-up
        in the final report.
        """
        git("checkout", "-q", "-b", "feature-x", cwd=temp_git_repo)
        assert get_current_branch_context() == ("main", temp_git_repo)


# ---------------------------------------------------------------------------
# get_last_commit / create_wip_commit
# ---------------------------------------------------------------------------


class TestWipCommitHelpers:
    def test_get_last_commit_empty_and_populated_repo(self, tmp_path, temp_git_repo):
        empty_repo = tmp_path / "empty-repo"
        empty_repo.mkdir()
        git("init", "-q", cwd=empty_repo)
        assert get_last_commit(empty_repo) == ""
        assert "Initial commit" in get_last_commit(temp_git_repo)

    def test_create_wip_commit_success_default_and_custom_message(self, temp_git_repo):
        (temp_git_repo / "new.txt").write_text("data\n")
        assert create_wip_commit(temp_git_repo) is True
        subject = git("log", "-1", "--format=%s", cwd=temp_git_repo)
        assert "WIP: Handoff checkpoint" in subject

        (temp_git_repo / "new2.txt").write_text("more\n")
        assert create_wip_commit(temp_git_repo, "custom checkpoint") is True
        subject = git("log", "-1", "--format=%s", cwd=temp_git_repo)
        assert subject == "custom checkpoint"

    def test_create_wip_commit_failure_when_nothing_to_commit(self, temp_git_repo):
        # Working tree is clean right after temp_git_repo's initial commit.
        assert create_wip_commit(temp_git_repo) is False


# ---------------------------------------------------------------------------
# handoffs.py module, exercised directly (real filesystem + git, no CLI)
# ---------------------------------------------------------------------------


class TestHandoffsModule:
    def test_setup_handoff_symlink_relative_and_idempotent(
        self, temp_git_repo, tmp_path
    ):
        worktree = tmp_path / "wt"
        worktree.mkdir()
        handoff_file = setup_handoff_symlink(worktree, "feat", temp_git_repo)
        assert handoff_file == get_handoff_file("feat", temp_git_repo)
        assert handoff_file.exists()

        symlink = worktree / ".claude" / "HANDOFF.md"
        assert symlink.is_symlink()
        assert not os.path.isabs(os.readlink(symlink))
        assert symlink.resolve() == handoff_file.resolve()

        first_target = os.readlink(symlink)
        setup_handoff_symlink(worktree, "feat", temp_git_repo)  # idempotent
        assert os.readlink(symlink) == first_target

    def test_setup_handoff_symlink_replaces_existing_regular_file(
        self, temp_git_repo, tmp_path
    ):
        worktree = tmp_path / "wt3"
        (worktree / ".claude").mkdir(parents=True)
        stale = worktree / ".claude" / "HANDOFF.md"
        stale.write_text("stale content, not a symlink")

        setup_handoff_symlink(worktree, "feat3", temp_git_repo)
        assert stale.is_symlink()

    def test_has_handoff_content_variants(self, tmp_path):
        assert has_handoff_content(tmp_path / "missing.md") is False

        empty = tmp_path / "empty.md"
        empty.write_text("   \n\n")
        assert has_handoff_content(empty) is False

        real = tmp_path / "real.md"
        real.write_text("# notes\n")
        assert has_handoff_content(real) is True

    def test_delete_handoff_removes_existing_and_reports_missing(self, temp_git_repo):
        ensure_handoffs_dir(temp_git_repo)
        f = get_handoff_file("gone", temp_git_repo)
        f.write_text("content")
        assert delete_handoff("gone", temp_git_repo) is True
        assert not f.exists()
        assert delete_handoff("gone", temp_git_repo) is False

    def test_preview_orphaned_handoffs_matches_clean_but_does_not_remove(
        self, temp_git_repo, isolated_worktrees, make_worktree
    ):
        make_worktree("kept-branch")
        ensure_handoffs_dir(temp_git_repo)
        orphan_file = get_handoff_file("long-gone", temp_git_repo)
        orphan_file.write_text("stale")

        preview = preview_orphaned_handoffs(temp_git_repo)
        assert preview == [("long-gone", orphan_file)]
        assert orphan_file.exists()

    def test_clean_orphaned_handoffs_removes_only_orphans_keeps_valid(
        self, temp_git_repo, isolated_worktrees, make_worktree
    ):
        make_worktree("kept-branch")
        ensure_handoffs_dir(temp_git_repo)
        orphan_file = get_handoff_file("long-gone", temp_git_repo)
        orphan_file.write_text("stale")
        get_handoff_file("master", temp_git_repo).write_text("keep me too")

        removed = clean_orphaned_handoffs(temp_git_repo)
        assert removed == ["long-gone"]
        assert not orphan_file.exists()
        assert get_handoff_file("kept-branch", temp_git_repo).exists()
        assert get_handoff_file("master", temp_git_repo).exists()

    def test_list_and_get_handoffs_dir_auto_detect_main_repo(self, temp_git_repo):
        assert list_handoffs(temp_git_repo) == []
        assert get_handoffs_dir() == temp_git_repo / ".claude" / "handoffs"

    def test_clean_orphaned_handoffs_auto_detects_main_repo(self, temp_git_repo):
        ensure_handoffs_dir()
        get_handoff_file("orphan-auto", temp_git_repo).write_text("stale")
        assert clean_orphaned_handoffs() == ["orphan-auto"]
