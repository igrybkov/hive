"""Tests for ui/pickers/status.py: the interactive worktree picker and detail screen.

Drives real prompt_toolkit KeyBindings where practical (see ScriptedApplication).
Git is never patched. Uses the `mocker` fixture (pytest-mock) instead of
`with patch(...)` blocks to keep tests short.
"""

from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from conftest import CycloptsTestRunner

from hive_cli.app import app
from hive_cli.services.status import AgentStatus
from hive_cli.ui.pickers.status import (
    _build_fuzzy_item,
    _delete_worktree_flow,
    _show_worktree_detail,
    interactive_status,
    watch_interactive_loop,
)

# Local helpers (no changes to conftest.py) -------------------------------


def make_status(
    *,
    agent_id: str = "feat",
    path: Path | None = None,
    branch: str = "feat",
    is_main: bool = False,
    is_dirty: bool = False,
    ahead: int = 0,
    behind: int = 0,
    last_commit_hash: str = "abc1234",
    last_commit_msg: str = "do a thing",
    task: str | None = None,
) -> AgentStatus:
    """Build an AgentStatus with sane defaults for picker tests."""
    return AgentStatus(
        agent_id=agent_id,
        path=path or Path("/tmp/fake-worktree"),
        branch=branch,
        is_main=is_main,
        is_dirty=is_dirty,
        ahead=ahead,
        behind=behind,
        last_commit_hash=last_commit_hash,
        last_commit_msg=last_commit_msg,
        task=task,
    )


def find_key_handler(kb, key: str):
    """Find the handler bound to `key` in a real prompt_toolkit KeyBindings."""
    for binding in kb.bindings:
        for k in binding.keys:
            if (k.value if hasattr(k, "value") else k) == key:
                return binding.handler
    raise AssertionError(f"no handler bound for key {key!r}")


class ScriptedApplication:
    """Stand-in for `prompt_toolkit.Application` inside `_show_worktree_detail`.

    That function does a *local* Application import, so patching it on the
    `prompt_toolkit` module (not `hive_cli.ui.pickers.status`) is what takes
    effect - verified empirically. Each `run()` pops one keypress list and
    invokes the matching real key-binding handlers.
    """

    def __init__(self, key_script: list[list[str]]):
        self.key_script = key_script
        self._kb = None

    def __call__(self, *args, **kwargs):
        self._kb = kwargs["key_bindings"]
        return self

    def run(self):
        for key in self.key_script.pop(0):
            find_key_handler(self._kb, key)(MagicMock())


# Pure builders: _build_fuzzy_item / _build_detail_content ----------------


class TestBuildFuzzyItem:
    @pytest.mark.parametrize(
        ("kwargs", "expected_style"),
        [
            ({"is_main": True, "branch": "main"}, "bold cyan"),
            ({"is_dirty": True}, "yellow"),
            ({"is_dirty": False}, "green"),
        ],
    )
    def test_style_by_status(self, kwargs, expected_style):
        assert _build_fuzzy_item(make_status(**kwargs)).style == expected_style

    def test_value_dirty_marker_and_ahead_behind_in_text(self):
        item = _build_fuzzy_item(make_status(is_dirty=True, ahead=2, behind=1))
        assert item.value == "feat"
        assert "*" in item.text
        assert "[+2-1]" in item.text

    def test_task_appended_to_meta_only_when_present(self):
        assert "a task" in _build_fuzzy_item(make_status(task="a task")).meta
        assert "|" not in _build_fuzzy_item(make_status(task=None)).meta


# `_delete_worktree_flow` --------------------------------------------------


class TestDeleteWorktreeFlow:
    @pytest.mark.parametrize("branch", ["main", "master", "1", "ghost-branch"])
    def test_returns_false_without_a_valid_worktree(
        self, temp_git_repo: Path, branch, mocker
    ):
        mock_confirm = mocker.patch("hive_cli.ui.pickers.status.confirm")
        assert _delete_worktree_flow(branch, temp_git_repo) is False
        mock_confirm.assert_not_called()

    @pytest.mark.parametrize("confirmed", [True, False])
    def test_confirm_result_drives_deletion(
        self, temp_git_repo: Path, isolated_worktrees, make_worktree, mocker, confirmed
    ):
        wt_path = make_worktree("feat")
        mocker.patch("hive_cli.ui.pickers.status.confirm", return_value=confirmed)
        assert _delete_worktree_flow("feat", temp_git_repo) is confirmed
        assert wt_path.exists() is not confirmed

    def test_delete_worktree_exception_is_handled(
        self, temp_git_repo: Path, isolated_worktrees, make_worktree, mocker
    ):
        make_worktree("feat")
        mocker.patch("hive_cli.ui.pickers.status.confirm", return_value=True)
        mocker.patch(
            "hive_cli.services.worktrees.delete_worktree", side_effect=RuntimeError("x")
        )
        assert _delete_worktree_flow("feat", temp_git_repo) is False


# `interactive_status` (fuzzy picker orchestration) ------------------------


class TestInteractiveStatus:
    def test_no_worktrees_at_all_returns_none(self, mocker):
        mock_error = mocker.patch("hive_cli.ui.pickers.status.error")
        result = interactive_status(statuses=[], main_repo=Path("/tmp/x"))
        assert result is None
        mock_error.assert_called_once()

    def test_escape_from_picker_returns_none(self, temp_git_repo: Path, mocker):
        from hive_cli.services.status import collect_status

        statuses = collect_status(temp_git_repo)
        mocker.patch("hive_cli.ui.pickers.status.fuzzy_select", return_value=None)
        assert interactive_status(statuses=statuses, main_repo=temp_git_repo) is None

    def test_selecting_worktree_then_back_reloops_then_none(
        self, temp_git_repo: Path, mocker
    ):
        from hive_cli.services.status import collect_status

        # Bug (reported, not fixed): docstring/--interactive help claim this
        # "outputs path for shell cd", but no branch here ever returns one.
        statuses = collect_status(temp_git_repo)
        branch = statuses[0].branch
        mocker.patch(
            "hive_cli.ui.pickers.status.fuzzy_select", side_effect=[branch, None]
        )
        mock_detail = mocker.patch(
            "hive_cli.ui.pickers.status._show_worktree_detail", return_value="back"
        )
        result = interactive_status(statuses=statuses, main_repo=temp_git_repo)
        assert result is None
        mock_detail.assert_called_once()

    def test_quit_from_detail_view(self, temp_git_repo: Path, mocker):
        from hive_cli.services.status import collect_status

        statuses = collect_status(temp_git_repo)
        mocker.patch(
            "hive_cli.ui.pickers.status.fuzzy_select", return_value=statuses[0].branch
        )
        mocker.patch(
            "hive_cli.ui.pickers.status._show_worktree_detail", return_value="quit"
        )
        assert interactive_status(statuses=statuses, main_repo=temp_git_repo) is None

    def test_delete_action_from_picker_refetches_and_continues(
        self, temp_git_repo: Path, isolated_worktrees, make_worktree, mocker
    ):
        from hive_cli.services.status import collect_status

        make_worktree("feat")
        statuses = collect_status(temp_git_repo)
        mocker.patch(
            "hive_cli.ui.pickers.status.fuzzy_select",
            side_effect=["__delete__:feat", None],
        )
        mock_delete = mocker.patch(
            "hive_cli.ui.pickers.status._delete_worktree_flow", return_value=True
        )
        result = interactive_status(statuses=statuses, main_repo=temp_git_repo)
        assert result is None
        mock_delete.assert_called_once_with("feat", temp_git_repo)

    def test_open_in_editor_action_from_picker(self, temp_git_repo: Path, mocker):
        from hive_cli.services.status import collect_status

        statuses = collect_status(temp_git_repo)
        branch = statuses[0].branch
        mocker.patch(
            "hive_cli.ui.pickers.status.fuzzy_select",
            side_effect=[f"__open_in_editor__:{branch}", None],
        )
        mocker.patch(
            "hive_cli.ui.pickers.status.select_editor",
            return_value=MagicMock(command="code"),
        )
        mock_open = mocker.patch("hive_cli.services.editors.open_in_editor")
        result = interactive_status(statuses=statuses, main_repo=temp_git_repo)
        assert result is None
        mock_open.assert_called_once()


# `_show_worktree_detail` (prompt_toolkit Application), driven via
# ScriptedApplication - see its docstring for why Application is patched at
# `prompt_toolkit.Application`.


class TestShowWorktreeDetail:
    @pytest.mark.parametrize(
        ("keys", "expected"),
        [(["escape"], "back"), (["q"], "quit"), (["c-c"], "quit")],
    )
    def test_single_key_results(self, temp_git_repo: Path, mocker, keys, expected):
        status = make_status(branch="main", is_main=True, path=temp_git_repo)
        mocker.patch("prompt_toolkit.Application", ScriptedApplication([keys]))
        assert _show_worktree_detail(status, temp_git_repo) == expected

    @pytest.mark.parametrize(
        ("editor", "opens"),
        [(MagicMock(command="code"), True), (None, False)],
    )
    def test_editor_action(self, temp_git_repo: Path, mocker, editor, opens):
        status = make_status(branch="main", is_main=True, path=temp_git_repo)
        mocker.patch(
            "prompt_toolkit.Application", ScriptedApplication([["e"], ["escape"]])
        )
        mocker.patch("hive_cli.ui.pickers.status.select_editor", return_value=editor)
        mock_open = mocker.patch("hive_cli.services.editors.open_in_editor")
        result = _show_worktree_detail(status, temp_git_repo)
        assert result == "back"
        assert mock_open.called is opens

    @pytest.mark.parametrize(
        ("deleted", "keys", "expected"),
        [(True, [["d"]], "deleted"), (False, [["d"], ["escape"]], "back")],
    )
    def test_delete_action(self, temp_git_repo: Path, mocker, deleted, keys, expected):
        status = make_status(branch="feat", path=temp_git_repo)
        mocker.patch("prompt_toolkit.Application", ScriptedApplication(keys))
        mocker.patch("hive_cli.ui.pickers.status._clear_screen_full")
        mock_delete = mocker.patch(
            "hive_cli.ui.pickers.status._delete_worktree_flow", return_value=deleted
        )
        result = _show_worktree_detail(status, temp_git_repo)
        assert result == expected
        mock_delete.assert_called_once_with("feat", temp_git_repo)

    def test_keyboard_interrupt_from_run_returns_quit(
        self, temp_git_repo: Path, mocker
    ):
        status = make_status(branch="main", is_main=True, path=temp_git_repo)

        class RaisingApplication(ScriptedApplication):
            def run(self):
                raise KeyboardInterrupt

        mocker.patch("prompt_toolkit.Application", RaisingApplication([[]]))
        assert _show_worktree_detail(status, temp_git_repo) == "quit"


# `watch_interactive_loop`: the full raw-terminal loop needs a real pty
# (termios/tty + select.select on sys.stdin.fileno()), out of scope here per
# the task brief. This covers the deterministic headless-CI path instead: a
# stdin with no real fd exits cleanly via `except (OSError, EOFError)`,
# since `io.UnsupportedOperation` is a subclass of OSError (verified below).


class TestWatchInteractiveLoopHeadless:
    class _NoFilenoStdin:
        def fileno(self):
            raise io.UnsupportedOperation("fileno")

    def test_no_tty_stdin_exits_cleanly(
        self, cli_runner: CycloptsTestRunner, temp_git_repo, monkeypatch
    ):
        monkeypatch.setattr(
            "hive_cli.ui.pickers.status.sys.stdin", self._NoFilenoStdin()
        )
        watch_interactive_loop(compact=False)  # returns instead of raising
        assert cli_runner.invoke(app, ["status", "--watch"]).exit_code == 0
