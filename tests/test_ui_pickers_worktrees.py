"""Tests for the state-threading seam in ui/pickers/worktrees.py:pick_worktree.

pick_worktree itself has no direct tests (only test_wt_cli.py mocking it out
entirely), so these pin the exact behavior the A0 wt.py pass's extraction of
_PickerState / _handle_context_action / _handle_open_in_editor introduced:
that toggling skip-permissions flips both the loop-local state and the
runtime settings mirror, and that opening a branch in an editor threads the
branch back into state.preselect_branch for the next loop iteration.
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from unittest.mock import patch

from conftest import git

from hive_cli.config.runtime import RuntimeSettings
from hive_cli.core import paths
from hive_cli.git import GitSummary
from hive_cli.git.github import GitHubIssue
from hive_cli.services.facts import ControlServer
from hive_cli.ui.console import info
from hive_cli.ui.pickers.worktree_items import ACTION_ISSUE_PREFIX, first_paint
from hive_cli.ui.pickers.worktrees import (
    ACTION_TOGGLE_SKIP_PERMISSIONS,
    _handle_context_action,
    _handle_open_in_editor,
    _PickerState,
    refine_git,
    refine_issues,
)


class TestHandleContextActionSkipPermissions:
    def test_toggle_flips_state_and_runtime(self):
        rt = RuntimeSettings()
        rt.skip_permissions = False
        state = _PickerState(
            selected_agent="claude", skip_permissions=False, preselect_branch=None
        )

        handled = _handle_context_action(ACTION_TOGGLE_SKIP_PERMISSIONS, rt, state)

        assert handled is True
        assert state.skip_permissions is True
        assert rt.skip_permissions is True

    def test_toggle_twice_returns_to_original(self):
        rt = RuntimeSettings()
        rt.skip_permissions = False
        state = _PickerState(
            selected_agent="claude", skip_permissions=False, preselect_branch=None
        )

        _handle_context_action(ACTION_TOGGLE_SKIP_PERMISSIONS, rt, state)
        _handle_context_action(ACTION_TOGGLE_SKIP_PERMISSIONS, rt, state)

        assert state.skip_permissions is False
        assert rt.skip_permissions is False


class TestHandleOpenInEditor:
    def test_sets_preselect_branch_for_existing_worktree(self, tmp_path):
        main_repo = tmp_path / "main"
        main_repo.mkdir()
        worktree_path = tmp_path / "wt"
        worktree_path.mkdir()
        state = _PickerState(
            selected_agent="claude", skip_permissions=False, preselect_branch=None
        )

        with (
            patch(
                "hive_cli.ui.pickers.worktrees.get_worktree_path",
                return_value=worktree_path,
            ),
            patch("hive_cli.ui.pickers.worktrees.select_editor", return_value="code"),
            patch("hive_cli.services.editors.open_in_editor") as mock_open,
        ):
            _handle_open_in_editor("__open_in_editor__:feature-x", main_repo, 1, state)

        mock_open.assert_called_once_with(worktree_path, "code", progress=info)
        assert state.preselect_branch == "feature-x"

    def test_no_editor_selected_leaves_preselect_branch_unset(self, tmp_path):
        main_repo = tmp_path / "main"
        main_repo.mkdir()
        worktree_path = tmp_path / "wt"
        worktree_path.mkdir()
        state = _PickerState(
            selected_agent="claude", skip_permissions=False, preselect_branch=None
        )

        with (
            patch(
                "hive_cli.ui.pickers.worktrees.get_worktree_path",
                return_value=worktree_path,
            ),
            patch("hive_cli.ui.pickers.worktrees.select_editor", return_value=None),
            patch("hive_cli.services.editors.open_in_editor") as mock_open,
        ):
            _handle_open_in_editor("__open_in_editor__:feature-x", main_repo, 1, state)

        mock_open.assert_not_called()
        assert state.preselect_branch is None


# ---------------------------------------------------------------------------
# first paint + refiners (spawn budgets with fake_proc; real repos for meta)
# ---------------------------------------------------------------------------

LISTING = """\
worktree {main}
HEAD 1111111111111111111111111111111111111111
branch refs/heads/main

worktree {main}-feat
HEAD 2222222222222222222222222222222222222222
branch refs/heads/feat

"""


class TestFirstPaintSpawns:
    def test_first_paint_is_one_spawn(self, fake_proc, tmp_path):
        main = tmp_path / "repo"
        fake_proc.script(("git", "worktree", "list"), stdout=LISTING.format(main=main))

        _sections, items, _selection = first_paint(main)

        assert fake_proc.calls == [["git", "worktree", "list", "--porcelain"]]
        assert [i.value for i in items] == ["main", "feat"]


class TestRefineGit:
    def _fresh_fetch_head(self, main: Path) -> None:
        (main / ".git").mkdir(parents=True, exist_ok=True)
        (main / ".git" / "FETCH_HEAD").write_text("")

    def test_no_fetch_when_fresh(self, fake_proc, tmp_path):
        main = tmp_path / "repo"
        self._fresh_fetch_head(main)
        fake_proc.script(("git", "worktree", "list"), stdout=LISTING.format(main=main))
        fake_proc.script(("git", "status"), stdout="# branch.head feat\n? x\n")
        fake_proc.script(
            ("git", "-C", str(main), "branch"), stdout="main\nfeat\norigin/other\n"
        )
        sections, _items, _selection = first_paint(main)

        items = refine_git(main, sections, threading.Event())

        assert fake_proc.count("git", "fetch") == 0
        assert items is not None
        by_value = {i.value: i for i in items}
        assert by_value["feat"].meta == "(dirty)" and by_value["feat"].style == "yellow"
        assert by_value["other"].style == "dim"

    def test_fetches_when_stale(self, fake_proc, tmp_path):
        main = tmp_path / "repo"
        self._fresh_fetch_head(main)
        old = time.time() - 10_000
        os.utime(main / ".git" / "FETCH_HEAD", (old, old))
        fake_proc.script(("git", "worktree", "list"), stdout=LISTING.format(main=main))
        sections, _items, _selection = first_paint(main)

        refine_git(main, sections, threading.Event())

        assert fake_proc.count("git", "fetch") == 1

    def test_returns_none_when_cancelled(self, fake_proc, tmp_path):
        main = tmp_path / "repo"
        self._fresh_fetch_head(main)
        fake_proc.script(("git", "worktree", "list"), stdout=LISTING.format(main=main))
        sections, _items, _selection = first_paint(main)
        cancel = threading.Event()
        cancel.set()

        assert refine_git(main, sections, cancel) is None
        assert fake_proc.count("git", "status") == 0

    def test_real_repo_marks_dirty_and_current(
        self, temp_git_repo, make_worktree, isolated_worktrees
    ):
        wt_path = make_worktree("feat-a")
        (wt_path / "dirty.txt").write_text("uncommitted")
        make_worktree("feat-b")
        git("branch", "plain", cwd=temp_git_repo)
        sections, _i, _s = first_paint(temp_git_repo, current_worktree_branch="feat-a")

        items = refine_git(temp_git_repo, sections, threading.Event())

        by_value = {i.value: i for i in items}
        assert by_value["feat-a"].meta == "← current (dirty)"
        assert by_value["feat-b"].meta == "" and by_value["feat-b"].style == "green"
        assert by_value["plain"].style == "dim"


class TestRefineGitViaControlSocket:
    def test_uses_control_socket_and_skips_git_entirely(
        self, fake_proc, tmp_path, short_tmp, mocker
    ):
        main = tmp_path / "repo"
        fake_proc.script(
            ("git", "worktree", "list"),
            stdout=f"worktree {main}\nHEAD 1111111111111111111111111111111111111111\n"
            "branch refs/heads/main\n\n",
        )
        sections, _items, _selection = first_paint(main)

        summary = GitSummary(
            branch="main",
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
        server = ControlServer(
            paths.control_sock("picker-test"),
            pane_id="1",
            facts=lambda: {str(main): summary},
        )
        server.start()
        fake_mux = mocker.Mock()
        fake_mux.own_session.return_value = "picker-test"
        mocker.patch("hive_cli.ui.pickers.worktrees.get_mux", return_value=fake_mux)
        try:
            items = refine_git(main, sections, threading.Event())
        finally:
            server.close()

        # No fetch, no per-worktree `git status`/`git log` -- those came from
        # the control socket instead. `get_all_branches` still runs; listing
        # branches is a picker concern the control plane doesn't answer for.
        assert fake_proc.count("git", "fetch") == 0
        assert fake_proc.count("git", "status") == 0
        by_value = {i.value: i for i in items}
        assert by_value["main"].style != "red"  # a real summary was applied


class TestRefineIssues:
    def test_none_keeps_items(self, tmp_path, mocker):
        mocker.patch("hive_cli.ui.pickers.worktrees.facts.issues", return_value=None)
        sections, _i, _s = first_paint(tmp_path)  # git fails: main only
        assert refine_issues(tmp_path, sections, threading.Event()) is None

    def test_issues_appended(self, tmp_path, mocker):
        mocker.patch(
            "hive_cli.ui.pickers.worktrees.facts.issues",
            return_value=[GitHubIssue(11, "Slow path issue")],
        )
        sections, _i, _s = first_paint(tmp_path)

        items = refine_issues(tmp_path, sections, threading.Event())

        issue_items = [i for i in items if i.value.startswith(ACTION_ISSUE_PREFIX)]
        assert len(issue_items) == 1 and "11" in issue_items[0].text

    def test_cancelled_returns_none(self, tmp_path, mocker):
        mocker.patch(
            "hive_cli.ui.pickers.worktrees.facts.issues",
            return_value=[GitHubIssue(11, "x")],
        )
        sections, _i, _s = first_paint(tmp_path)
        cancel = threading.Event()
        cancel.set()
        assert refine_issues(tmp_path, sections, cancel) is None

    def test_live_gh_fetch_through_facts(
        self, temp_git_repo, isolated_worktrees, fake_gh, mocker
    ):
        git(
            "remote",
            "add",
            "origin",
            "https://github.com/acme/widgets.git",
            cwd=temp_git_repo,
        )
        mocker.patch("hive_cli.services.facts.shutil.which", return_value="/bin/gh")
        fake_gh.script(
            ("gh", "issue", "list"), stdout='[{"number": 11, "title": "Live"}]'
        )
        sections, _i, _s = first_paint(temp_git_repo)

        items = refine_issues(temp_git_repo, sections, threading.Event())

        assert any("11" in i.text for i in items)
