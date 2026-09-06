"""Integration tests for git/worktree.py and git/repo.py using real git repos."""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import commit_file, git

from hive_cli.git.repo import (
    change_to_git_root,
    change_to_main_repo,
    get_current_worktree_branch,
    get_git_root,
    get_main_repo,
    get_session_name,
)
from hive_cli.git.worktree import (
    create_worktree,
    delete_worktree,
    get_all_branches,
    get_current_branch,
    get_default_branch,
    is_worktree_dirty,
    list_worktrees,
    worktree_exists,
)

# ---------------------------------------------------------------------------
# git/repo.py
# ---------------------------------------------------------------------------


class TestGetGitRoot:
    def test_from_main_repo(self, temp_git_repo):
        assert get_git_root() == temp_git_repo.resolve()

    def test_from_worktree(self, make_worktree, monkeypatch):
        wt_path = make_worktree("feat-a")
        monkeypatch.chdir(wt_path)
        assert get_git_root() == wt_path.resolve()

    def test_outside_repo_returns_none(self, tmp_path, monkeypatch):
        outside = tmp_path / "not-a-repo"
        outside.mkdir()
        monkeypatch.chdir(outside)
        assert get_git_root() is None


class TestGetMainRepo:
    def test_from_main_repo(self, temp_git_repo):
        assert get_main_repo() == temp_git_repo.resolve()

    def test_from_worktree_returns_main_repo(
        self, make_worktree, temp_git_repo, monkeypatch
    ):
        wt_path = make_worktree("feat-a")
        monkeypatch.chdir(wt_path)
        assert get_main_repo() == temp_git_repo.resolve()

    def test_outside_repo_returns_cwd(self, tmp_path, monkeypatch):
        outside = tmp_path / "not-a-repo"
        outside.mkdir()
        monkeypatch.chdir(outside)
        assert get_main_repo() == outside


class TestGetSessionName:
    def test_derives_lowercase_name_from_main_repo(self, temp_git_repo):
        # temp_git_repo fixture creates a dir named "test-repo".
        assert get_session_name() == "test-repo"

    def test_replaces_spaces_and_lowercases(self, monkeypatch):
        from unittest.mock import patch

        with patch(
            "hive_cli.git.repo.get_main_repo",
            return_value=Path("/tmp/My Cool Repo"),
        ):
            assert get_session_name() == "my-cool-repo"


class TestChangeToGitRoot:
    def test_changes_directory_when_in_repo(
        self, temp_git_repo, make_worktree, monkeypatch
    ):
        wt_path = make_worktree("feat-a")
        monkeypatch.chdir(wt_path)
        result = change_to_git_root()
        assert result == wt_path.resolve()
        assert Path.cwd() == wt_path.resolve()

    def test_returns_none_outside_repo(self, tmp_path, monkeypatch):
        outside = tmp_path / "not-a-repo"
        outside.mkdir()
        monkeypatch.chdir(outside)
        assert change_to_git_root() is None
        assert Path.cwd() == outside.resolve()


class TestChangeToMainRepo:
    def test_changes_to_main_repo_from_worktree(
        self, temp_git_repo, make_worktree, monkeypatch
    ):
        wt_path = make_worktree("feat-a")
        monkeypatch.chdir(wt_path)
        result = change_to_main_repo()
        assert result == temp_git_repo.resolve()
        assert Path.cwd() == temp_git_repo.resolve()


class TestGetCurrentWorktreeBranch:
    def test_main_repo_returns_none(self, temp_git_repo):
        assert get_current_worktree_branch() is None

    def test_worktree_returns_branch(self, make_worktree, monkeypatch):
        wt_path = make_worktree("feat-a")
        monkeypatch.chdir(wt_path)
        assert get_current_worktree_branch() == "feat-a"

    def test_outside_repo_returns_none(self, tmp_path, monkeypatch):
        outside = tmp_path / "not-a-repo"
        outside.mkdir()
        monkeypatch.chdir(outside)
        assert get_current_worktree_branch() is None


# ---------------------------------------------------------------------------
# git/worktree.py
# ---------------------------------------------------------------------------


class TestListWorktreesMultiple:
    def test_lists_all_worktrees(self, temp_git_repo, make_worktree):
        make_worktree("feat-a")
        make_worktree("feat-b")

        worktrees = list_worktrees(temp_git_repo)
        branches = {wt.branch for wt in worktrees}
        assert branches == {"main", "feat-a", "feat-b"}
        assert worktrees[0].is_main is True

    def test_non_main_entries_not_marked_main(self, temp_git_repo, make_worktree):
        make_worktree("feat-a")
        worktrees = list_worktrees(temp_git_repo)
        by_branch = {wt.branch: wt for wt in worktrees}
        assert by_branch["feat-a"].is_main is False


class TestWorktreeExistsReal:
    def test_true_for_created_worktree(self, temp_git_repo, make_worktree):
        make_worktree("feat-a")
        assert worktree_exists("feat-a", temp_git_repo) is True

    def test_false_for_uncreated_branch(self, temp_git_repo):
        assert worktree_exists("never-created", temp_git_repo) is False


class TestIsWorktreeDirty:
    def test_clean_worktree_is_not_dirty(self, make_worktree):
        # make_worktree's .claude/HANDOFF.md symlink is deliberately added
        # to the repo's info/exclude (see handoffs._exclude_from_git), so a
        # freshly created worktree is genuinely clean, not just "clean but
        # for an untracked file we happen to ignore in this assertion".
        wt_path = make_worktree("feat-a")
        assert is_worktree_dirty(wt_path) is False

    def test_untracked_file_marks_dirty(self, make_worktree):
        wt_path = make_worktree("feat-a")
        (wt_path / "new-file.txt").write_text("hello")
        assert is_worktree_dirty(wt_path) is True

    def test_modified_tracked_file_marks_dirty(self, make_worktree):
        wt_path = make_worktree("feat-a")
        (wt_path / "README.md").write_text("modified content")
        assert is_worktree_dirty(wt_path) is True


class TestGetDefaultBranch:
    def test_main_branch_present(self, temp_git_repo):
        assert get_default_branch(temp_git_repo) == "main"

    def test_master_branch_present(self, temp_git_repo):
        git("branch", "-m", "main", "master", cwd=temp_git_repo)
        assert get_default_branch(temp_git_repo) == "master"

    def test_falls_back_to_origin_head(self, temp_git_repo, tmp_path):
        origin = tmp_path / "origin.git"
        import subprocess

        subprocess.run(
            ["git", "clone", "--bare", "-q", str(temp_git_repo), str(origin)],
            check=True,
            capture_output=True,
        )
        git("remote", "add", "origin", str(origin), cwd=temp_git_repo)
        git("fetch", "-q", "origin", cwd=temp_git_repo)
        git("remote", "set-head", "origin", "-a", cwd=temp_git_repo)
        # Rename the local branch away from main/master so those checks miss
        # and the origin/HEAD symbolic-ref lookup is exercised instead.
        git("branch", "-m", "main", "trunk", cwd=temp_git_repo)

        assert get_default_branch(temp_git_repo) == "main"

    def test_falls_back_to_main_when_nothing_matches(self, temp_git_repo):
        git("branch", "-m", "main", "trunk", cwd=temp_git_repo)
        assert get_default_branch(temp_git_repo) == "main"


class TestGetAllBranches:
    def test_local_and_remote_branches(self, repo_with_origin):
        git("push", "-q", "origin", "main:remote-only", cwd=repo_with_origin)
        git("branch", "local-only", cwd=repo_with_origin)
        git("fetch", "-q", "origin", cwd=repo_with_origin)

        branches = get_all_branches(repo_with_origin)
        assert "main" in branches
        assert "local-only" in branches
        assert "remote-only" in branches
        # No origin/ prefix leaks through.
        assert all(not b.startswith("origin/") for b in branches)

    def test_no_remote_returns_local_only(self, temp_git_repo):
        git("branch", "local-only", cwd=temp_git_repo)
        branches = get_all_branches(temp_git_repo)
        assert branches == ["local-only", "main"]


class TestGetCurrentBranch:
    def test_returns_current_branch(self, temp_git_repo):
        assert get_current_branch(temp_git_repo) == "main"

    def test_worktree_branch(self, make_worktree):
        wt_path = make_worktree("feat-a")
        assert get_current_branch(wt_path) == "feat-a"


class TestCreateWorktree:
    def test_existing_local_branch(self, temp_git_repo, isolated_worktrees):
        git("branch", "feat-a", cwd=temp_git_repo)
        path = create_worktree("feat-a", temp_git_repo)
        assert path.exists()
        assert get_current_branch(path) == "feat-a"

    def test_remote_only_branch(self, repo_with_origin, isolated_worktrees):
        git("push", "-q", "origin", "main:remote-feat", cwd=repo_with_origin)
        git("fetch", "-q", "origin", cwd=repo_with_origin)

        path = create_worktree("remote-feat", repo_with_origin)
        assert path.exists()
        assert get_current_branch(path) == "remote-feat"

    def test_new_branch_from_default(self, temp_git_repo, isolated_worktrees):
        path = create_worktree("brand-new", temp_git_repo)
        assert path.exists()
        assert get_current_branch(path) == "brand-new"

    def test_raises_for_main_branch(self, temp_git_repo):
        with pytest.raises(ValueError, match="main branch"):
            create_worktree("main", temp_git_repo)

    def test_raises_for_one_alias(self, temp_git_repo):
        with pytest.raises(ValueError, match="main branch"):
            create_worktree("1", temp_git_repo)

    def test_raises_when_branch_checked_out_in_main_repo(
        self, temp_git_repo, isolated_worktrees
    ):
        git("checkout", "-b", "feat-a", cwd=temp_git_repo)
        with pytest.raises(ValueError, match="already checked out"):
            create_worktree("feat-a", temp_git_repo)

    def test_raises_when_worktree_already_exists(
        self, temp_git_repo, isolated_worktrees
    ):
        create_worktree("feat-a", temp_git_repo)
        with pytest.raises(FileExistsError, match="already exists"):
            create_worktree("feat-a", temp_git_repo)


class TestDeleteWorktree:
    def test_deletes_clean_worktree(self, temp_git_repo, make_worktree):
        wt_path = make_worktree("feat-a")
        assert wt_path.exists()

        delete_worktree(wt_path)

        assert not wt_path.exists()
        assert worktree_exists("feat-a", temp_git_repo) is False

    def test_raises_for_dirty_worktree_without_force(self, make_worktree):
        wt_path = make_worktree("feat-a")
        (wt_path / "uncommitted.txt").write_text("oops")

        with pytest.raises(ValueError, match="uncommitted changes"):
            delete_worktree(wt_path)

        assert wt_path.exists()

    def test_force_deletes_dirty_worktree(self, temp_git_repo, make_worktree):
        wt_path = make_worktree("feat-a")
        (wt_path / "uncommitted.txt").write_text("oops")

        delete_worktree(wt_path, force=True)

        assert not wt_path.exists()
        assert worktree_exists("feat-a", temp_git_repo) is False


class TestCommitFileHelper:
    """Sanity check for the commit_file conftest helper used across this file."""

    def test_commit_file_creates_and_commits(self, temp_git_repo):
        sha = commit_file(temp_git_repo, "extra.txt", "content", message="add extra")
        assert sha
        assert (temp_git_repo / "extra.txt").read_text() == "content"


class TestListWorktreesHead:
    def test_main_head_comes_from_the_listing(self, temp_git_repo, make_worktree):
        make_worktree("feat-a")
        git("checkout", "-q", "-b", "topic", cwd=temp_git_repo)
        worktrees = list_worktrees(temp_git_repo)
        assert worktrees[0].is_main and worktrees[0].head == "topic"
        assert worktrees[0].branch == "main"  # hive's name for it never changes
        assert [w.head for w in worktrees[1:]] == ["feat-a"]

    def test_detached_main_has_empty_head(self, temp_git_repo):
        git("checkout", "-q", "--detach", cwd=temp_git_repo)
        assert list_worktrees(temp_git_repo)[0].head == ""


class TestGetMainRepoCache:
    def test_second_call_adds_no_spawn(self, fake_proc, tmp_path):
        fake_proc.script(
            ("git", "rev-parse", "--git-common-dir"), stdout=f"{tmp_path}/.git\n"
        )
        get_main_repo.cache_clear()

        first = get_main_repo()
        second = get_main_repo()

        assert first == second == tmp_path.resolve()
        assert fake_proc.count("git", "rev-parse") == 1

    def test_conftest_clears_the_cache_between_tests(self, temp_git_repo):
        # The previous test cached a fake path; this one must see its own repo.
        assert get_main_repo() == temp_git_repo.resolve()
