"""Integration tests for the git-analysis commands.

These exercise ``hive diff``, ``hive rebase-check`` and ``hive merge-preview``
through the real CLI against real git repositories (no mocked git). ``delta``
is patched out for the plain-diff scenarios only, since its presence on the
developer's machine is an environment detail, not something we can control -
see the module docstring note below for why.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import CycloptsTestRunner, commit_file, git

from hive_cli.app import app


def _commit_only(repo: Path, name: str, content: str, message: str) -> None:
    """Like ``commit_file`` but stages only ``name``, not ``-A``.

    The ``make_worktree`` fixture leaves an untracked ``.claude/HANDOFF.md``
    symlink in every worktree (see
    ``hive_cli.services.handoffs.setup_handoff_symlink``).
    ``commit_file``'s ``git add -A`` would sweep that symlink in too, making
    every pair of worktrees with any commit look like they "overlap" on
    ``.claude/HANDOFF.md`` regardless of what was actually edited. Tests that
    need a clean, single-file commit use this instead.
    """
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    git("add", name, cwd=repo)
    git("commit", "-q", "-m", message, cwd=repo)


@pytest.fixture(autouse=True)
def _no_delta(monkeypatch):
    """Force the plain-diff code path.

    ``hive diff`` shells out to the real ``delta`` pager (writing straight to
    the process's real stdout/stderr fds) whenever it is on PATH, which would
    make output assertions depend on whether the machine running the tests
    happens to have delta installed. We don't patch git itself - only the
    local helper that probes for the optional pager - so the diff computation
    and rendering still go through real git and real Rich output.
    """
    monkeypatch.setattr("hive_cli.commands.diff.has_delta", lambda: False)


# ---------------------------------------------------------------------------
# hive diff
# ---------------------------------------------------------------------------


class TestDiff:
    def test_no_worktrees_no_changes_shows_header_only(
        self, cli_runner: CycloptsTestRunner, temp_git_repo: Path
    ):
        result = cli_runner.invoke(app, ["diff"])

        assert result.exit_code == 0
        assert "Agent Diff View" in result.output
        assert "Agent 1 (main)" not in result.output

    def test_main_repo_uncommitted_change_is_shown(
        self, cli_runner: CycloptsTestRunner, temp_git_repo: Path
    ):
        (temp_git_repo / "README.md").write_text("# Test Repository\nchanged\n")

        result = cli_runner.invoke(app, ["diff"])

        assert result.exit_code == 0
        assert "Agent 1 (main)" in result.output
        assert "README.md" in result.output
        assert "changed" in result.output

    def test_worktree_with_committed_change_shows_diff(
        self,
        cli_runner: CycloptsTestRunner,
        temp_git_repo: Path,
        isolated_worktrees: Path,
        make_worktree,
    ):
        wt_path = make_worktree("feat")
        commit_file(wt_path, "newfile.txt", "hello world\n", "add newfile")

        result = cli_runner.invoke(app, ["diff"])

        assert result.exit_code == 0
        assert "Agent feat" in result.output
        assert "newfile.txt" in result.output
        assert "hello world" in result.output

    def test_worktree_with_no_changes_shows_no_changes_marker(
        self,
        cli_runner: CycloptsTestRunner,
        temp_git_repo: Path,
        isolated_worktrees: Path,
        make_worktree,
    ):
        make_worktree("idle")

        result = cli_runner.invoke(app, ["diff"])

        assert result.exit_code == 0
        assert "Agent idle" in result.output
        assert "(no changes)" in result.output

    def test_diff_files_only_shows_filenames_not_content(
        self,
        cli_runner: CycloptsTestRunner,
        temp_git_repo: Path,
        isolated_worktrees: Path,
        make_worktree,
    ):
        wt_path = make_worktree("feat")
        commit_file(wt_path, "onlyname.txt", "secret content line\n", "add file")

        result = cli_runner.invoke(app, ["diff", "--files"])

        assert result.exit_code == 0
        assert "onlyname.txt" in result.output
        assert "secret content line" not in result.output

    def test_diff_stat_shows_summary_not_content(
        self,
        cli_runner: CycloptsTestRunner,
        temp_git_repo: Path,
        isolated_worktrees: Path,
        make_worktree,
    ):
        wt_path = make_worktree("feat")
        commit_file(wt_path, "statfile.txt", "abcdefg content\n", "add file")

        result = cli_runner.invoke(app, ["diff", "-s"])

        assert result.exit_code == 0
        assert "statfile.txt" in result.output
        assert "1 +" in result.output or "1 insertion" in result.output
        assert "abcdefg content" not in result.output

    def test_multiple_worktrees_each_shown(
        self,
        cli_runner: CycloptsTestRunner,
        temp_git_repo: Path,
        isolated_worktrees: Path,
        make_worktree,
    ):
        wt_a = make_worktree("agent-a")
        wt_b = make_worktree("agent-b")
        commit_file(wt_a, "a.txt", "content a\n", "add a")
        commit_file(wt_b, "b.txt", "content b\n", "add b")

        result = cli_runner.invoke(app, ["diff"])

        assert result.exit_code == 0
        assert "Agent agent-a" in result.output
        assert "Agent agent-b" in result.output
        assert "a.txt" in result.output
        assert "b.txt" in result.output


# ---------------------------------------------------------------------------
# hive rebase-check
# ---------------------------------------------------------------------------


class TestRebaseCheck:
    def test_branch_up_to_date_after_creation(
        self,
        cli_runner: CycloptsTestRunner,
        repo_with_origin: Path,
        isolated_worktrees: Path,
        make_worktree,
    ):
        make_worktree("feat")

        result = cli_runner.invoke(app, ["rebase-check"])

        assert result.exit_code == 0
        assert "Rebase Check" in result.output
        assert "feat" in result.output
        assert "up to date" in result.output

    def test_branch_behind_after_main_advances(
        self,
        cli_runner: CycloptsTestRunner,
        repo_with_origin: Path,
        isolated_worktrees: Path,
        make_worktree,
    ):
        # Create the worktree *before* advancing main, so it is genuinely
        # behind once main gets a new commit that is pushed to origin.
        make_worktree("feat")

        commit_file(repo_with_origin, "advance.txt", "v2\n", "advance main")
        git("push", "-q", "origin", "main", cwd=repo_with_origin)

        result = cli_runner.invoke(app, ["rebase-check"])

        assert result.exit_code == 0
        assert "feat" in result.output
        assert "1 commits behind" in result.output
        assert "Changed files that may conflict" in result.output
        assert "advance.txt" in result.output

    def test_branch_many_commits_behind_recommends_rebase(
        self,
        cli_runner: CycloptsTestRunner,
        repo_with_origin: Path,
        isolated_worktrees: Path,
        make_worktree,
    ):
        make_worktree("feat")

        for i in range(5):
            commit_file(repo_with_origin, f"advance{i}.txt", "v\n", f"advance {i}")
        git("push", "-q", "origin", "main", cwd=repo_with_origin)

        result = cli_runner.invoke(app, ["rebase-check"])

        assert result.exit_code == 0
        assert "5 commits behind - rebase recommended" in result.output

    def test_ahead_commits_shown_alongside_behind(
        self,
        cli_runner: CycloptsTestRunner,
        repo_with_origin: Path,
        isolated_worktrees: Path,
        make_worktree,
    ):
        wt_path = make_worktree("feat")

        commit_file(repo_with_origin, "advance.txt", "v2\n", "advance main")
        git("push", "-q", "origin", "main", cwd=repo_with_origin)
        commit_file(wt_path, "local.txt", "local change\n", "local commit")

        result = cli_runner.invoke(app, ["rebase-check"])

        assert result.exit_code == 0
        assert "1 ahead" in result.output

    def test_fetch_flag_without_origin_does_not_crash(
        self,
        cli_runner: CycloptsTestRunner,
        temp_git_repo: Path,
        isolated_worktrees: Path,
        make_worktree,
    ):
        """No ``origin`` remote at all: ``_fetch_origin`` fails silently."""
        make_worktree("feat")

        result = cli_runner.invoke(app, ["rebase-check", "--fetch"])

        assert result.exit_code == 0
        assert "Fetching from origin" in result.output
        assert "Rebase Check" in result.output

    def test_no_worktrees_still_prints_header_and_tip(
        self, cli_runner: CycloptsTestRunner, temp_git_repo: Path
    ):
        result = cli_runner.invoke(app, ["rebase-check"])

        assert result.exit_code == 0
        assert "Rebase Check" in result.output
        assert "Tip: Run with --fetch" in result.output


# ---------------------------------------------------------------------------
# hive merge-preview
# ---------------------------------------------------------------------------


class TestMergePreviewOverlap:
    def test_no_worktrees_no_overlap(
        self, cli_runner: CycloptsTestRunner, temp_git_repo: Path
    ):
        result = cli_runner.invoke(app, ["merge-preview"])

        assert result.exit_code == 0
        assert "File Overlap Analysis" in result.output
        assert "No overlapping files" in result.output

    def test_different_files_no_overlap(
        self,
        cli_runner: CycloptsTestRunner,
        temp_git_repo: Path,
        isolated_worktrees: Path,
        make_worktree,
    ):
        wt_a = make_worktree("agent-a")
        wt_b = make_worktree("agent-b")
        _commit_only(wt_a, "a.txt", "content a\n", "add a")
        _commit_only(wt_b, "b.txt", "content b\n", "add b")

        result = cli_runner.invoke(app, ["merge-preview"])

        assert result.exit_code == 0
        assert "No overlapping files" in result.output

    def test_same_file_overlap_lists_both_agents(
        self,
        cli_runner: CycloptsTestRunner,
        temp_git_repo: Path,
        isolated_worktrees: Path,
        make_worktree,
    ):
        wt_a = make_worktree("agent-a")
        wt_b = make_worktree("agent-b")
        commit_file(wt_a, "shared.txt", "from a\n", "edit shared from a")
        commit_file(wt_b, "shared.txt", "from b\n", "edit shared from b")

        result = cli_runner.invoke(app, ["merge-preview"])

        assert result.exit_code == 0
        assert "shared.txt" in result.output
        assert "Modified by agents:" in result.output
        assert "agent-a" in result.output
        assert "agent-b" in result.output


class TestMergePreviewSingleAgent:
    def test_agent_not_found_errors(
        self, cli_runner: CycloptsTestRunner, temp_git_repo: Path
    ):
        result = cli_runner.invoke(app, ["merge-preview", "9"])

        assert result.exit_code == 1
        assert "not found" in result.output

    def test_clean_merge_reports_success_and_added_file(
        self,
        cli_runner: CycloptsTestRunner,
        temp_git_repo: Path,
        isolated_worktrees: Path,
        make_worktree,
    ):
        wt_path = make_worktree("agent-2")
        commit_file(wt_path, "brand_new.txt", "content\n", "add brand new file")

        result = cli_runner.invoke(app, ["merge-preview", "2"])

        assert result.exit_code == 0
        assert "Merge Preview: agent-2" in result.output
        assert "Merge would succeed without conflicts" in result.output
        assert "brand_new.txt" in result.output

    def test_clean_merge_reports_modified_file(
        self,
        cli_runner: CycloptsTestRunner,
        temp_git_repo: Path,
        isolated_worktrees: Path,
        make_worktree,
    ):
        wt_path = make_worktree("agent-6")
        _commit_only(
            wt_path, "README.md", "# Test Repository\nupdated\n", "edit readme"
        )

        result = cli_runner.invoke(app, ["merge-preview", "6"])

        assert result.exit_code == 0
        assert "Merge would succeed without conflicts" in result.output
        assert "~ README.md" in result.output

    def test_conflicting_merge_reports_conflict_and_exits_nonzero(
        self,
        cli_runner: CycloptsTestRunner,
        temp_git_repo: Path,
        isolated_worktrees: Path,
        make_worktree,
    ):
        wt_path = make_worktree("agent-3")
        commit_file(wt_path, "shared.txt", "changed on branch\n", "branch edit")
        commit_file(temp_git_repo, "shared.txt", "changed on main\n", "main edit")

        result = cli_runner.invoke(app, ["merge-preview", "3"])

        assert result.exit_code == 1
        assert "Merge would have conflicts" in result.output
        assert "Conflicting files" in result.output
        assert "shared.txt" in result.output

    def test_deleted_file_shown_with_minus_marker(
        self,
        cli_runner: CycloptsTestRunner,
        temp_git_repo: Path,
        isolated_worktrees: Path,
        make_worktree,
    ):
        wt_path = make_worktree("agent-4")
        git("rm", "-q", "README.md", cwd=wt_path)
        git("commit", "-q", "-m", "remove readme", cwd=wt_path)

        result = cli_runner.invoke(app, ["merge-preview", "4"])

        assert result.exit_code == 0
        assert "- README.md" in result.output

    def test_renamed_file_shown(
        self,
        cli_runner: CycloptsTestRunner,
        temp_git_repo: Path,
        isolated_worktrees: Path,
        make_worktree,
    ):
        wt_path = make_worktree("agent-5")
        git("mv", "README.md", "RENAMED.md", cwd=wt_path)
        git("commit", "-q", "-m", "rename readme", cwd=wt_path)

        result = cli_runner.invoke(app, ["merge-preview", "5"])

        assert result.exit_code == 0
        assert "README.md" in result.output
        assert "RENAMED.md" in result.output

    def test_main_agent_id_targets_main_repo(
        self, cli_runner: CycloptsTestRunner, temp_git_repo: Path
    ):
        result = cli_runner.invoke(app, ["merge-preview", "1"])

        assert result.exit_code == 0
        assert "Merge Preview:" in result.output


class TestDiffMarkupSafety:
    """Raw diff text must reach the terminal untouched by Rich markup parsing."""

    def test_square_brackets_survive(
        self, cli_runner: CycloptsTestRunner, temp_git_repo: Path, make_worktree
    ):
        wt = make_worktree("feat")
        commit_file(
            wt,
            "typed.py",
            "x: list[str] = []\n# see [docs](https://example.com)\n",
            "typed",
        )
        result = cli_runner.invoke(app, ["diff"])
        assert result.exit_code == 0
        assert "list[str]" in result.output
        assert "[docs](https://example.com)" in result.output


class TestMergeOverlapHiveManagedFiles:
    """Files hive itself drops into worktrees are never reported as overlaps."""

    def test_git_add_all_in_two_worktrees_is_not_an_overlap(
        self, cli_runner: CycloptsTestRunner, temp_git_repo: Path, make_worktree
    ):
        for name in ("feat-a", "feat-b"):
            wt = make_worktree(name)
            (wt / f"{name}.txt").write_text(name)
            git("add", "-A", cwd=wt)
            git("commit", "-q", "-m", name, cwd=wt)
        result = cli_runner.invoke(app, ["merge-preview"])
        assert result.exit_code == 0
        assert "No overlapping files" in result.output
        assert "HANDOFF.md" not in result.output

    def test_force_committed_handoff_symlink_is_ignored(
        self, cli_runner: CycloptsTestRunner, temp_git_repo: Path, make_worktree
    ):
        for name in ("feat-a", "feat-b"):
            wt = make_worktree(name)
            git("add", "-f", ".claude/HANDOFF.md", cwd=wt)
            git("commit", "-q", "-m", name, cwd=wt)
        result = cli_runner.invoke(app, ["merge-preview"])
        assert result.exit_code == 0
        assert "No overlapping files" in result.output


class TestMergePreviewWatch:
    @staticmethod
    def _fake_watch(frames: list[str]):
        import io

        from rich.console import Console

        def fake_watch(collect, render, **kwargs):
            buf = io.StringIO()
            Console(file=buf, width=100).print(render(collect()))
            frames.append(buf.getvalue())
            return "q", None

        return fake_watch

    def test_overlap_board(
        self, cli_runner: CycloptsTestRunner, temp_git_repo: Path, mocker
    ):
        frames: list[str] = []
        mocker.patch("hive_cli.ui.board.watch", side_effect=self._fake_watch(frames))
        result = cli_runner.invoke(app, ["merge-preview", "--watch"])
        assert result.exit_code == 0
        assert "File Overlap Analysis" in frames[0]
        assert "No overlapping files" in frames[0]

    def test_agent_board(
        self, cli_runner: CycloptsTestRunner, temp_git_repo: Path, mocker
    ):
        frames: list[str] = []
        mocker.patch("hive_cli.ui.board.watch", side_effect=self._fake_watch(frames))
        result = cli_runner.invoke(app, ["merge-preview", "1", "-w"])
        assert result.exit_code == 0
        assert "Merge Preview:" in frames[0]

    def test_missing_agent_errors(
        self, cli_runner: CycloptsTestRunner, temp_git_repo: Path, mocker
    ):
        mocker.patch("hive_cli.ui.board.watch", side_effect=self._fake_watch([]))
        result = cli_runner.invoke(app, ["merge-preview", "9", "--watch"])
        assert result.exit_code == 1
        assert "not found" in result.output
