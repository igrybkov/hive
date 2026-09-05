"""Integration tests for the ``hive handoff`` command group and ``handoffs.py``."""

from __future__ import annotations

import os
import stat
from pathlib import Path
from unittest.mock import patch

import pytest
from conftest import CycloptsTestRunner, git

from hive_cli.app import app
from hive_cli.commands.handoff import (
    _complete_branch,
    _create_wip_commit,
    _format_handoff_preview,
    _get_current_branch_context,
    _get_last_commit,
)
from hive_cli.handoffs import (
    clean_orphaned_handoffs,
    delete_handoff,
    ensure_handoffs_dir,
    get_handoff_file,
    get_handoffs_dir,
    has_handoff_content,
    list_handoffs,
    setup_handoff_symlink,
)

# ---------------------------------------------------------------------------
# Local helpers / fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def editor_script(tmp_path: Path) -> Path:
    """A fake $EDITOR that appends a marker line to the file it's given."""
    script = tmp_path / "fake-editor.sh"
    script.write_text('#!/bin/sh\necho "EDITED-BY-TEST" >> "$1"\n')
    script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return script


def use_editor(monkeypatch: pytest.MonkeyPatch, script: Path) -> None:
    """Point $EDITOR at ``script`` and force RuntimeSettings to re-read it."""
    monkeypatch.setenv("EDITOR", str(script))
    import hive_cli.config.runtime as runtime_mod

    runtime_mod._runtime_settings = None


def delete_cwd(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Chdir into a dir, then remove it out from under the process.

    The only reliable, non-mocked way to make ``get_main_repo()`` (and
    therefore ``_get_current_branch_context()``) actually raise: it swallows
    every git failure and falls back to ``Path.cwd()``, so a plain "not a
    git repo" directory is not enough on its own.
    """
    gone = tmp_path / "gone"
    gone.mkdir()
    monkeypatch.chdir(gone)
    os.rmdir(gone)


# ---------------------------------------------------------------------------
# hive handoff --help / default
# ---------------------------------------------------------------------------


class TestHandoffHelp:
    def test_help_lists_subcommands(self, cli_runner: CycloptsTestRunner):
        result = cli_runner.invoke(app, ["handoff", "--help"])
        assert result.exit_code == 0
        assert "Manage branch handoff notes" in result.output
        for cmd in ["list", "show", "create", "edit", "clear", "clean", "path"]:
            assert cmd in result.output


class TestHandoffDefault:
    def test_no_handoffs_then_all_empty(
        self,
        cli_runner: CycloptsTestRunner,
        temp_git_repo,
        isolated_worktrees,
        make_worktree,
    ):
        result = cli_runner.invoke(app, ["handoff"])
        assert result.exit_code == 0
        assert "No handoffs found" in result.output

        # make_worktree seeds an *empty* handoff file via setup_handoff_symlink.
        make_worktree("feat")
        result = cli_runner.invoke(app, ["handoff"])
        assert result.exit_code == 0
        assert "No active handoffs (all empty)" in result.output

    def test_shows_only_active_handoffs(
        self,
        cli_runner: CycloptsTestRunner,
        temp_git_repo,
        isolated_worktrees,
        make_worktree,
    ):
        make_worktree("feat")
        make_worktree("bare")
        result = cli_runner.invoke(
            app, ["handoff", "create", "feat", "Ready", "for", "review", "--no-commit"]
        )
        assert result.exit_code == 0

        result = cli_runner.invoke(app, ["handoff"])
        assert result.exit_code == 0
        assert "Active Handoffs" in result.output
        assert "feat" in result.output
        assert "Ready for review" in result.output
        assert "bare" not in result.output


class TestHandoffShow:
    def test_show_missing_handoff_current_and_explicit_branch(
        self, cli_runner: CycloptsTestRunner, temp_git_repo
    ):
        result = cli_runner.invoke(app, ["handoff", "show"])
        assert result.exit_code == 0
        assert "No handoff for main" in result.output

        result = cli_runner.invoke(app, ["handoff", "show", "some-branch"])
        assert result.exit_code == 0
        assert "No handoff for some-branch" in result.output

    def test_show_from_inside_worktree(
        self,
        cli_runner: CycloptsTestRunner,
        temp_git_repo,
        isolated_worktrees,
        make_worktree,
        monkeypatch,
    ):
        wt_path = make_worktree("feat")
        result = cli_runner.invoke(
            app, ["handoff", "create", "feat", "Notes", "here", "--no-commit"]
        )
        assert result.exit_code == 0

        monkeypatch.chdir(wt_path)
        result = cli_runner.invoke(app, ["handoff", "show"])
        assert result.exit_code == 0
        assert "feat" in result.output
        assert "Notes here" in result.output


class TestHandoffCreate:
    def test_create_current_branch_no_args(
        self, cli_runner: CycloptsTestRunner, temp_git_repo
    ):
        result = cli_runner.invoke(app, ["handoff", "create", "--no-commit"])
        assert result.exit_code == 0
        assert "Handoff created" in result.output

        handoff_file = temp_git_repo / ".claude" / "handoffs" / "main.md"
        content = handoff_file.read_text()
        assert "# Handoff: main" in content
        assert "[Add summary of work on this branch]" in content

    def test_create_explicit_branch_with_message(
        self, cli_runner: CycloptsTestRunner, temp_git_repo
    ):
        # NOTE: first positional token is always consumed by `branch`, not
        # `message` -- see the bug write-up in the final report.
        result = cli_runner.invoke(
            app,
            ["handoff", "create", "main", "Ready", "for", "review", "--no-commit"],
        )
        assert result.exit_code == 0

        content = (temp_git_repo / ".claude" / "handoffs" / "main.md").read_text()
        assert "Ready for review" in content

    def test_create_for_nonexistent_worktree_falls_back_to_main_repo(
        self, cli_runner: CycloptsTestRunner, temp_git_repo, isolated_worktrees
    ):
        result = cli_runner.invoke(
            app, ["handoff", "create", "ghost-branch", "--no-commit"]
        )
        assert result.exit_code == 0

        content = (
            temp_git_repo / ".claude" / "handoffs" / "ghost-branch.md"
        ).read_text()
        assert f"cd {temp_git_repo}" in content

    def test_create_from_inside_worktree_uses_current_branch(
        self,
        cli_runner: CycloptsTestRunner,
        temp_git_repo,
        isolated_worktrees,
        make_worktree,
        monkeypatch,
    ):
        wt_path = make_worktree("feat")
        monkeypatch.chdir(wt_path)
        result = cli_runner.invoke(app, ["handoff", "create", "--no-commit"])
        assert result.exit_code == 0

        content = (temp_git_repo / ".claude" / "handoffs" / "feat.md").read_text()
        assert "# Handoff: feat" in content

    def test_create_dirty_worktree_confirm_and_no_commit_flows(
        self, cli_runner: CycloptsTestRunner, temp_git_repo
    ):
        (temp_git_repo / "README.md").write_text("changed\n")

        with patch("hive_cli.commands.handoff.confirm", return_value=True):
            result = cli_runner.invoke(app, ["handoff", "create"])
        assert result.exit_code == 0
        assert "Uncommitted changes detected" in result.output
        assert "WIP commit created" in result.output
        # Folded into the WIP commit; only the new handoff file is untracked.
        assert git("status", "--short", "--", "README.md", cwd=temp_git_repo) == ""
        assert "WIP: Handoff checkpoint" in git("log", "--oneline", cwd=temp_git_repo)

        (temp_git_repo / "README.md").write_text("changed again\n")
        with patch("hive_cli.commands.handoff.confirm", return_value=False):
            result = cli_runner.invoke(app, ["handoff", "create"])
        assert "WIP commit created" not in result.output
        status = git("status", "--short", "--", "README.md", cwd=temp_git_repo)
        assert status == "M README.md"

        with patch("hive_cli.commands.handoff.confirm") as mock_confirm:
            result = cli_runner.invoke(app, ["handoff", "create", "--no-commit"])
        assert result.exit_code == 0
        mock_confirm.assert_not_called()
        assert "Uncommitted changes detected" not in result.output


class TestHandoffEdit:
    def test_edit_creates_template_then_preserves_existing_content(
        self,
        cli_runner: CycloptsTestRunner,
        temp_git_repo,
        editor_script,
        monkeypatch,
    ):
        use_editor(monkeypatch, editor_script)
        result = cli_runner.invoke(app, ["handoff", "edit"])
        assert result.exit_code == 0

        handoff_file = temp_git_repo / ".claude" / "handoffs" / "main.md"
        content = handoff_file.read_text()
        assert "# Handoff: main" in content
        assert "[Brief description of work on this branch]" in content
        assert content.count("EDITED-BY-TEST") == 1

        # Editing again must not recreate the template: content now exists.
        result = cli_runner.invoke(app, ["handoff", "edit"])
        assert result.exit_code == 0
        content = handoff_file.read_text()
        assert content.count("EDITED-BY-TEST") == 2
        assert content.count("[Brief description of work on this branch]") == 1

    def test_edit_explicit_branch_without_worktree_uses_main_repo(
        self,
        cli_runner: CycloptsTestRunner,
        temp_git_repo,
        editor_script,
        monkeypatch,
        isolated_worktrees,
    ):
        use_editor(monkeypatch, editor_script)
        result = cli_runner.invoke(app, ["handoff", "edit", "no-such-branch"])
        assert result.exit_code == 0

        content = (
            temp_git_repo / ".claude" / "handoffs" / "no-such-branch.md"
        ).read_text()
        assert f"cd {temp_git_repo}" in content
        assert "EDITED-BY-TEST" in content


class TestHandoffClear:
    def test_clear_with_and_without_content(
        self, cli_runner: CycloptsTestRunner, temp_git_repo
    ):
        result = cli_runner.invoke(app, ["handoff", "clear"])
        assert result.exit_code == 0
        assert "No handoff to clear for 'main'" in result.output

        result = cli_runner.invoke(
            app, ["handoff", "create", "main", "stuff", "--no-commit"]
        )
        assert result.exit_code == 0

        result = cli_runner.invoke(app, ["handoff", "clear"])
        assert result.exit_code == 0
        assert "Handoff cleared for 'main'" in result.output

        handoff_file = temp_git_repo / ".claude" / "handoffs" / "main.md"
        assert handoff_file.exists()
        assert handoff_file.read_text() == ""

    def test_clear_explicit_branch(self, cli_runner: CycloptsTestRunner, temp_git_repo):
        result = cli_runner.invoke(
            app, ["handoff", "create", "other", "notes", "--no-commit"]
        )
        assert result.exit_code == 0

        result = cli_runner.invoke(app, ["handoff", "clear", "other"])
        assert result.exit_code == 0
        assert "Handoff cleared for 'other'" in result.output


class TestHandoffList:
    def test_list_no_handoffs(self, cli_runner: CycloptsTestRunner, temp_git_repo):
        result = cli_runner.invoke(app, ["handoff", "list"])
        assert result.exit_code == 0
        assert "No handoff files found" in result.output

    def test_list_default_hides_empty(
        self,
        cli_runner: CycloptsTestRunner,
        temp_git_repo,
        isolated_worktrees,
        make_worktree,
    ):
        make_worktree("feat")
        result = cli_runner.invoke(
            app, ["handoff", "create", "feat", "notes", "--no-commit"]
        )
        assert result.exit_code == 0
        make_worktree("bare")

        result = cli_runner.invoke(app, ["handoff", "list"])
        assert result.exit_code == 0
        assert "feat" in result.output
        assert "active" in result.output
        assert "bare" not in result.output

    @pytest.mark.parametrize("flag", ["--all", "-a"])
    def test_list_all_flag_shows_empty_too(
        self,
        cli_runner: CycloptsTestRunner,
        temp_git_repo,
        isolated_worktrees,
        make_worktree,
        flag,
    ):
        make_worktree("bare")
        result = cli_runner.invoke(app, ["handoff", "list", flag])
        assert result.exit_code == 0
        assert "bare" in result.output
        assert "empty" in result.output


class TestHandoffClean:
    def test_no_orphans_dry_run_and_actual(
        self, cli_runner: CycloptsTestRunner, temp_git_repo
    ):
        result = cli_runner.invoke(app, ["handoff", "clean", "--dry-run"])
        assert result.exit_code == 0
        assert "No orphaned handoffs to clean" in result.output

        result = cli_runner.invoke(app, ["handoff", "clean"])
        assert result.exit_code == 0
        assert "No orphaned handoffs to clean" in result.output

    def test_dry_run_previews_then_clean_removes_orphan_keeps_real_branch(
        self,
        cli_runner: CycloptsTestRunner,
        temp_git_repo,
        isolated_worktrees,
        make_worktree,
    ):
        make_worktree("kept")
        result = cli_runner.invoke(
            app, ["handoff", "create", "ghost-branch", "--no-commit"]
        )
        assert result.exit_code == 0
        ghost_file = temp_git_repo / ".claude" / "handoffs" / "ghost-branch.md"

        result = cli_runner.invoke(app, ["handoff", "clean", "-n"])
        assert result.exit_code == 0
        assert "Would remove" in result.output
        assert "ghost-branch" in result.output
        assert ghost_file.exists()

        result = cli_runner.invoke(app, ["handoff", "clean"])
        assert result.exit_code == 0
        assert "Removed 1 orphaned handoff" in result.output
        assert "ghost-branch" in result.output
        assert not ghost_file.exists()
        assert (temp_git_repo / ".claude" / "handoffs" / "kept.md").exists()


class TestHandoffPath:
    def test_path_current_and_explicit_branch(
        self, cli_runner: CycloptsTestRunner, temp_git_repo
    ):
        result = cli_runner.invoke(app, ["handoff", "path"])
        assert result.exit_code == 0
        expected = temp_git_repo / ".claude" / "handoffs" / "main.md"
        assert str(expected) in result.output

        result = cli_runner.invoke(app, ["handoff", "path", "feature-x"])
        assert result.exit_code == 0
        assert "feature-x.md" in result.output


class TestHandoffOutsideGitRepo:
    """Every subcommand that resolves the current branch guards on
    ``_get_current_branch_context() is None`` and exits 1. Parametrized
    over subcommands instead of duplicating the (deleted-cwd) setup.
    """

    @pytest.mark.parametrize(
        "cmd_args", [["show"], ["create"], ["edit"], ["clear"], ["path"]]
    )
    def test_fails_with_not_in_git_repository(
        self, cli_runner: CycloptsTestRunner, tmp_path, monkeypatch, cmd_args
    ):
        delete_cwd(monkeypatch, tmp_path)
        result = cli_runner.invoke(app, ["handoff", *cmd_args])
        assert result.exit_code == 1
        assert "Not in a git repository" in result.output


# ---------------------------------------------------------------------------
# Private helpers in commands/handoff.py, exercised directly
# ---------------------------------------------------------------------------


class TestGetCurrentBranchContext:
    def test_returns_none_outside_any_repo(self, tmp_path, monkeypatch):
        delete_cwd(monkeypatch, tmp_path)
        assert _get_current_branch_context() is None

    def test_returns_branch_and_path_in_main_repo_and_worktree(
        self, temp_git_repo, isolated_worktrees, make_worktree, monkeypatch
    ):
        assert _get_current_branch_context() == ("main", temp_git_repo)

        wt_path = make_worktree("feat")
        monkeypatch.chdir(wt_path)
        assert _get_current_branch_context() == ("feat", wt_path)

    def test_main_repo_on_non_main_branch_still_reports_main(self, temp_git_repo):
        """Documents a bug: list_worktrees() always prepends a synthetic
        WorktreeInfo(branch="main", path=main_repo) entry, matched by
        *path* in the loop before the (correct) get_current_branch()
        lookup below it ever runs. So the main repo always reports "main"
        regardless of what's actually checked out. See the bug write-up
        in the final report.
        """
        git("checkout", "-q", "-b", "feature-x", cwd=temp_git_repo)
        assert _get_current_branch_context() == ("main", temp_git_repo)


class TestWipCommitHelpers:
    def test_get_last_commit_empty_and_populated_repo(self, tmp_path, temp_git_repo):
        empty_repo = tmp_path / "empty-repo"
        empty_repo.mkdir()
        git("init", "-q", cwd=empty_repo)
        assert _get_last_commit(empty_repo) == ""
        assert "Initial commit" in _get_last_commit(temp_git_repo)

    def test_create_wip_commit_success_default_and_custom_message(self, temp_git_repo):
        (temp_git_repo / "new.txt").write_text("data\n")
        assert _create_wip_commit(temp_git_repo) is True
        subject = git("log", "-1", "--format=%s", cwd=temp_git_repo)
        assert "WIP: Handoff checkpoint" in subject

        (temp_git_repo / "new2.txt").write_text("more\n")
        assert _create_wip_commit(temp_git_repo, "custom checkpoint") is True
        subject = git("log", "-1", "--format=%s", cwd=temp_git_repo)
        assert subject == "custom checkpoint"

    def test_create_wip_commit_failure_when_nothing_to_commit(self, temp_git_repo):
        # Working tree is clean right after temp_git_repo's initial commit.
        assert _create_wip_commit(temp_git_repo) is False


class TestFormatHandoffPreview:
    def test_missing_and_empty_file(self, capsys, tmp_path):
        _format_handoff_preview("somebranch", tmp_path / "missing.md")
        assert "No handoff for somebranch" in capsys.readouterr().out

        empty = tmp_path / "empty.md"
        empty.write_text("   \n\n")
        _format_handoff_preview("somebranch", empty)
        assert "Empty handoff for somebranch" in capsys.readouterr().out

    def test_non_empty_file(self, capsys, tmp_path):
        f = tmp_path / "content.md"
        f.write_text("# Hello\n\nSome notes here.\n")
        _format_handoff_preview("mybranch", f)
        out = capsys.readouterr().out
        assert "mybranch" in out
        assert "Hello" in out
        assert "Some notes here" in out


class TestCompleteBranch:
    def test_returns_matching_branches(
        self, temp_git_repo, isolated_worktrees, make_worktree
    ):
        make_worktree("feature-one")
        make_worktree("other")
        assert _complete_branch(None, None, "feature") == ["feature-one"]

    def test_returns_empty_list_on_failure(self, tmp_path, monkeypatch):
        delete_cwd(monkeypatch, tmp_path)
        assert _complete_branch(None, None, "") == []


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
