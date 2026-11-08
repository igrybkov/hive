"""The handoff symlink hive creates in a worktree must never be staged by git."""

from __future__ import annotations

from pathlib import Path

from conftest import git

from hive_cli.services.handoffs import (
    HANDOFF_SYMLINK,
    _exclude_from_git,
    setup_handoff_symlink,
)


def _exclude_file(worktree: Path) -> Path:
    path = Path(git("rev-parse", "--git-path", "info/exclude", cwd=worktree))
    return path if path.is_absolute() else worktree / path


def test_symlink_is_excluded_after_worktree_creation(temp_git_repo, make_worktree):
    wt = make_worktree("feat")
    assert (wt / HANDOFF_SYMLINK).is_symlink()
    assert git("status", "--porcelain", cwd=wt) == ""
    git("add", "-A", cwd=wt)
    assert git("status", "--porcelain", cwd=wt) == ""
    assert HANDOFF_SYMLINK in _exclude_file(wt).read_text().splitlines()


def test_exclude_entry_is_idempotent(temp_git_repo, make_worktree):
    wt = make_worktree("feat")
    setup_handoff_symlink(wt, "feat", temp_git_repo)
    setup_handoff_symlink(wt, "feat", temp_git_repo)
    assert _exclude_file(wt).read_text().count(HANDOFF_SYMLINK) == 1


def test_exclude_preserves_existing_entries_without_trailing_newline(temp_git_repo):
    exclude = _exclude_file(temp_git_repo)
    exclude.parent.mkdir(parents=True, exist_ok=True)
    exclude.write_text("build/")
    _exclude_from_git(temp_git_repo, "scratch.txt")
    assert exclude.read_text() == "build/\nscratch.txt\n"


def test_exclude_is_a_noop_outside_git(tmp_path):
    plain = tmp_path / "not-a-repo"
    plain.mkdir()
    _exclude_from_git(plain, "x")
    assert list(plain.iterdir()) == []
