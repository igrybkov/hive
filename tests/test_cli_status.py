"""Integration tests for the `hive status` command.

Drives the real CLI where practical. Only the interactive prompt_toolkit UI
and the raw-terminal watch loop are patched, at the points named in the task
brief. Git is never patched. Uses the `mocker` fixture (pytest-mock, already
a dev dependency) instead of `with patch(...)` blocks to keep tests short.
"""

from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from conftest import CycloptsTestRunner, commit_file, git
from rich.console import Console, Group

from hive_cli.app import app
from hive_cli.commands.status import (
    AgentStatus,
    CommitInfo,
    GitStatusDetail,
    _build_compact_output,
    _build_detail_content,
    _build_full_output,
    _build_fuzzy_item,
    _collect_status,
    _delete_worktree_flow,
    _get_ahead_behind,
    _get_git_status_detail,
    _get_last_commit,
    _get_recent_commits,
    _get_shared_notes_summary,
    _get_task,
    _interactive_status,
    _show_worktree_detail,
    _watch_interactive_loop,
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
    """Build an AgentStatus with sane defaults for renderer tests."""
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


def render(renderable: Group) -> str:
    """Render a rich Group to plain text (styles stripped, no tty)."""
    buf = io.StringIO()
    Console(file=buf, width=100).print(renderable)
    return buf.getvalue()


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
    `prompt_toolkit` module (not `hive_cli.commands.status`) is what takes
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


# Pure renderers: _build_full_output / _build_compact_output --------------


class TestBuildFullOutput:
    @pytest.mark.parametrize(
        ("kwargs", "expected"),
        [
            ({"is_main": True, "branch": "main"}, "Agent 1 (main)"),
            ({"agent_id": "feat"}, "Agent feat"),
        ],
    )
    def test_agent_label(self, tmp_path: Path, kwargs, expected):
        assert expected in render(_build_full_output([make_status(**kwargs)], tmp_path))

    def test_dirty_marker_shown_only_when_dirty(self, tmp_path: Path):
        clean = render(_build_full_output([make_status(is_dirty=False)], tmp_path))
        dirty = render(_build_full_output([make_status(is_dirty=True)], tmp_path))
        assert "*" not in clean and "*" in dirty

    @pytest.mark.parametrize(
        ("ahead", "behind", "plus", "minus"),
        [
            (2, 0, True, False),
            (0, 3, False, True),
            (2, 3, True, True),
            (0, 0, False, False),
        ],
    )
    def test_ahead_behind_markers(self, tmp_path: Path, ahead, behind, plus, minus):
        text = render(
            _build_full_output([make_status(ahead=ahead, behind=behind)], tmp_path)
        )
        assert (f"+{ahead}" in text) is plus
        assert (f"-{behind}" in text) is minus

    def test_task_line_shown_only_when_present(self, tmp_path: Path):
        with_task = render(_build_full_output([make_status(task="fix it")], tmp_path))
        without_task = render(_build_full_output([make_status(task=None)], tmp_path))
        assert "Task:" in with_task and "fix it" in with_task
        assert "Task:" not in without_task

    def test_repo_name_in_header(self, tmp_path: Path):
        text = render(_build_full_output([], tmp_path))
        assert tmp_path.name in text
        assert "Agent Status Board" in text

    def test_shared_notes_summary_included_only_when_file_exists(self, tmp_path: Path):
        assert "Shared Notes" not in render(_build_full_output([], tmp_path))

        notes = tmp_path / ".claude" / "local-agents"
        notes.mkdir(parents=True)
        content = "intro\n\n## First\nbody\n\n## Latest\nbody\n"
        (notes / "shared-notes.md").write_text(content)
        text = render(_build_full_output([], tmp_path))
        assert "Shared Notes" in text
        assert "7 lines" in text
        assert "Latest" in text


class TestBuildCompactOutput:
    def test_single_line_per_agent_with_dirty_and_ahead_behind(self, tmp_path: Path):
        statuses = [
            make_status(is_main=True, branch="main"),
            make_status(
                agent_id="feat", branch="feat", is_dirty=True, ahead=1, behind=2
            ),
        ]
        text = render(_build_compact_output(statuses, tmp_path))
        assert "Agents" in text
        assert "main" in text and "feat" in text
        assert "*" in text
        assert "+1" in text and "-2" in text


# Pure renderers: _build_fuzzy_item / _build_detail_content ---------------


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


class TestBuildDetailContent:
    @staticmethod
    def _text(parts: list[tuple[str, str]]) -> str:
        return "".join(t for _, t in parts)

    def _build(self, status=None, git_status=None, commits=None):
        return self._text(
            _build_detail_content(
                status or make_status(),
                git_status or GitStatusDetail(staged=[], unstaged=[], untracked=[]),
                commits or [],
            )
        )

    def test_main_header_and_up_to_date(self):
        text = self._build(make_status(is_main=True, branch="main", ahead=0, behind=0))
        assert "main" in text and "(main)" in text
        assert "up to date" in text

    def test_ahead_and_behind_shown(self):
        text = self._build(make_status(ahead=2, behind=1))
        assert "2 ahead" in text and "1 behind" in text

    def test_clean_working_tree_message(self):
        assert "Working tree clean" in self._build()

    def test_staged_unstaged_untracked_sections(self):
        git_status = GitStatusDetail(
            staged=["A new.py"], unstaged=["M mod.py"], untracked=["scratch.txt"]
        )
        text = self._build(git_status=git_status)
        assert "Staged:" in text and "A new.py" in text
        assert "Modified:" in text and "M mod.py" in text
        assert "Untracked:" in text and "scratch.txt" in text

    def test_no_commits_message(self):
        assert "No commits found" in self._build()

    def test_recent_commits_listed(self):
        commits = [
            CommitInfo(hash="abc123", message="did stuff", author="A", date="1h ago")
        ]
        text = self._build(commits=commits)
        assert "abc123" in text and "did stuff" in text and "A, 1h ago" in text

    def test_task_section_only_when_present(self):
        assert "Current Task" in self._build(make_status(task="write tests"))
        assert "Current Task" not in self._build(make_status(task=None))


# Git-backed helpers against real repos (no mocks) -------------------------


class TestGitSubprocessHelpers:
    # ahead/behind, last commit, git status detail, recent commits helpers
    def test_ahead_behind_no_upstream_and_ahead(
        self, temp_git_repo: Path, repo_with_origin: Path
    ):
        assert _get_ahead_behind(temp_git_repo) == (0, 0)
        commit_file(repo_with_origin, "a.txt", "1")
        assert _get_ahead_behind(repo_with_origin) == (1, 0)

    def test_last_commit_hash_message_and_truncation(self, temp_git_repo: Path):
        commit_file(temp_git_repo, "f.txt", "x", message="a specific message")
        commit_hash, msg = _get_last_commit(temp_git_repo)
        assert commit_hash
        assert msg == "a specific message"

        commit_file(temp_git_repo, "f2.txt", "x", message="y" * 80)
        assert len(_get_last_commit(temp_git_repo)[1]) == 50

    def test_git_status_detail_clean_then_dirty(self, temp_git_repo: Path):
        assert _get_git_status_detail(temp_git_repo) == GitStatusDetail([], [], [])

        (temp_git_repo / "untracked.txt").write_text("new")
        (temp_git_repo / "README.md").write_text("modified content\n")
        (temp_git_repo / "staged.txt").write_text("staged")
        git("add", "staged.txt", cwd=temp_git_repo)

        detail = _get_git_status_detail(temp_git_repo)
        assert any("staged.txt" in f for f in detail.staged)
        assert any("README.md" in f for f in detail.unstaged)
        assert "untracked.txt" in detail.untracked

    def test_recent_commits_most_recent_first_with_count(self, temp_git_repo: Path):
        commit_file(temp_git_repo, "one.txt", "1", message="first change")
        commit_file(temp_git_repo, "two.txt", "2", message="second change")
        commits = _get_recent_commits(temp_git_repo, count=1)
        assert len(commits) == 1
        assert commits[0].message == "second change"
        assert commits[0].author == "Test User"


class TestGetTaskAndSharedNotes:
    def test_first_non_header_line_truncated_to_sixty(self, temp_git_repo: Path):
        assert _get_task(temp_git_repo, "feat") is None  # no task file yet
        tasks_dir = temp_git_repo / ".claude" / "local-agents" / "tasks"
        tasks_dir.mkdir(parents=True)
        (tasks_dir / "agent-feat.md").write_text("# Header\n\n" + "z" * 100 + "\n")
        assert _get_task(temp_git_repo, "feat") == ("z" * 100)[:60]

    def test_main_agent_uses_agent_1_filename(self, temp_git_repo: Path):
        # main worktree's agent_id is "1", so its file is agent-1.md.
        tasks_dir = temp_git_repo / ".claude" / "local-agents" / "tasks"
        tasks_dir.mkdir(parents=True)
        (tasks_dir / "agent-1.md").write_text("main repo task\n")
        assert _get_task(temp_git_repo, "1") == "main repo task"
        assert _get_task(temp_git_repo, "main") is None

    def test_missing_shared_notes_file(self, temp_git_repo: Path):
        assert _get_shared_notes_summary(temp_git_repo) == (0, None)

    @pytest.mark.parametrize(
        ("content", "expected"),
        [
            ("## First\nbody\n\n## Second\nmore\n", (5, "Second")),
            ("just text\nno headers\n", (2, None)),
        ],
    )
    def test_shared_notes_lines_and_header(self, temp_git_repo, content, expected):
        notes_dir = temp_git_repo / ".claude" / "local-agents"
        notes_dir.mkdir(parents=True)
        (notes_dir / "shared-notes.md").write_text(content)
        assert _get_shared_notes_summary(temp_git_repo) == expected


class TestCollectStatus:
    def test_main_only_repo_has_single_entry(self, temp_git_repo: Path):
        # Regression guard: a path-resolution mismatch in list_worktrees'
        # main-vs-porcelain dedupe would make main appear twice.
        statuses = _collect_status(temp_git_repo)
        assert len(statuses) == 1
        assert statuses[0].is_main is True
        assert statuses[0].agent_id == "1"

    def test_worktree_dirty_and_task_are_reflected(
        self, temp_git_repo: Path, isolated_worktrees, make_worktree
    ):
        wt_path = make_worktree("feat")
        (wt_path / "scratch.txt").write_text("dirty")
        tasks_dir = temp_git_repo / ".claude" / "local-agents" / "tasks"
        tasks_dir.mkdir(parents=True)
        (tasks_dir / "agent-feat.md").write_text("the assigned task\n")

        by_branch = {s.branch: s for s in _collect_status(temp_git_repo)}
        assert set(by_branch) == {"main", "feat"}
        assert by_branch["feat"].is_dirty is True
        assert by_branch["feat"].is_main is False
        assert by_branch["feat"].task == "the assigned task"


# CLI-level: `hive status` / `hive status --compact` -----------------------


class TestStatusCliOneShot:
    def test_no_worktrees_full_and_compact(
        self, cli_runner: CycloptsTestRunner, temp_git_repo
    ):
        full = cli_runner.invoke(app, ["status"])
        compact = cli_runner.invoke(app, ["status", "--compact"])
        assert full.exit_code == 0 and compact.exit_code == 0
        assert "Agent 1 (main)" in full.output
        assert "Agents" in compact.output and "main" in compact.output

    def test_two_worktrees_dirty_and_ahead(
        self,
        cli_runner: CycloptsTestRunner,
        repo_with_origin: Path,
        isolated_worktrees,
        make_worktree,
    ):
        dirty_wt = make_worktree("dirty-branch")
        (dirty_wt / "untracked.txt").write_text("wip")
        ahead_wt = make_worktree("ahead-branch")
        git("branch", "--set-upstream-to=origin/main", "ahead-branch", cwd=ahead_wt)
        commit_file(ahead_wt, "new.txt", "content", message="ahead work")

        result = cli_runner.invoke(app, ["status"])
        assert result.exit_code == 0
        assert "dirty-branch" in result.output
        assert "ahead-branch" in result.output
        assert "+1" in result.output
        assert "*" in result.output

    def test_task_and_shared_notes_shown_in_full_view(
        self, cli_runner: CycloptsTestRunner, temp_git_repo
    ):
        tasks_dir = temp_git_repo / ".claude" / "local-agents" / "tasks"
        tasks_dir.mkdir(parents=True)
        (tasks_dir / "agent-1.md").write_text("investigate the bug\n")
        (tasks_dir.parent / "shared-notes.md").write_text("## Decision\nuse X\n")

        result = cli_runner.invoke(app, ["status"])
        assert "investigate the bug" in result.output
        assert "Shared Notes" in result.output and "Decision" in result.output


# `_delete_worktree_flow` --------------------------------------------------


class TestDeleteWorktreeFlow:
    @pytest.mark.parametrize("branch", ["main", "master", "1", "ghost-branch"])
    def test_returns_false_without_a_valid_worktree(self, temp_git_repo: Path, branch):
        assert _delete_worktree_flow(branch, temp_git_repo) is False

    @pytest.mark.parametrize("confirmed", [True, False])
    def test_confirm_result_drives_deletion(
        self, temp_git_repo: Path, isolated_worktrees, make_worktree, mocker, confirmed
    ):
        wt_path = make_worktree("feat")
        mocker.patch("hive_cli.commands.status.confirm", return_value=confirmed)
        assert _delete_worktree_flow("feat", temp_git_repo) is confirmed
        assert wt_path.exists() is not confirmed

    def test_delete_worktree_exception_is_handled(
        self, temp_git_repo: Path, isolated_worktrees, make_worktree, mocker
    ):
        make_worktree("feat")
        mocker.patch("hive_cli.commands.status.confirm", return_value=True)
        mocker.patch(
            "hive_cli.commands.status.delete_worktree", side_effect=RuntimeError("x")
        )
        assert _delete_worktree_flow("feat", temp_git_repo) is False


# `_interactive_status` (fuzzy picker orchestration) -----------------------


class TestInteractiveStatus:
    def test_no_worktrees_at_all_returns_none(self, mocker):
        mock_error = mocker.patch("hive_cli.commands.status.error")
        result = _interactive_status(statuses=[], main_repo=Path("/tmp/x"))
        assert result is None
        mock_error.assert_called_once()

    def test_escape_from_picker_returns_none(self, temp_git_repo: Path, mocker):
        statuses = _collect_status(temp_git_repo)
        mocker.patch("hive_cli.commands.status.fuzzy_select", return_value=None)
        assert _interactive_status(statuses=statuses, main_repo=temp_git_repo) is None

    def test_selecting_worktree_then_back_reloops_then_none(
        self, temp_git_repo: Path, mocker
    ):
        # Bug (reported, not fixed): docstring/--interactive help claim this
        # "outputs path for shell cd", but no branch here ever returns one.
        statuses = _collect_status(temp_git_repo)
        branch = statuses[0].branch
        mocker.patch(
            "hive_cli.commands.status.fuzzy_select", side_effect=[branch, None]
        )
        mock_detail = mocker.patch(
            "hive_cli.commands.status._show_worktree_detail", return_value="back"
        )
        result = _interactive_status(statuses=statuses, main_repo=temp_git_repo)
        assert result is None
        mock_detail.assert_called_once()

    def test_quit_from_detail_view(self, temp_git_repo: Path, mocker):
        statuses = _collect_status(temp_git_repo)
        mocker.patch(
            "hive_cli.commands.status.fuzzy_select", return_value=statuses[0].branch
        )
        mocker.patch(
            "hive_cli.commands.status._show_worktree_detail", return_value="quit"
        )
        assert _interactive_status(statuses=statuses, main_repo=temp_git_repo) is None

    def test_delete_action_from_picker_refetches_and_continues(
        self, temp_git_repo: Path, isolated_worktrees, make_worktree, mocker
    ):
        make_worktree("feat")
        statuses = _collect_status(temp_git_repo)
        mocker.patch(
            "hive_cli.commands.status.fuzzy_select",
            side_effect=["__delete__:feat", None],
        )
        mock_delete = mocker.patch(
            "hive_cli.commands.status._delete_worktree_flow", return_value=True
        )
        result = _interactive_status(statuses=statuses, main_repo=temp_git_repo)
        assert result is None
        mock_delete.assert_called_once_with("feat", temp_git_repo)

    def test_open_in_editor_action_from_picker(self, temp_git_repo: Path, mocker):
        statuses = _collect_status(temp_git_repo)
        branch = statuses[0].branch
        mocker.patch(
            "hive_cli.commands.status.fuzzy_select",
            side_effect=[f"__open_in_editor__:{branch}", None],
        )
        mocker.patch(
            "hive_cli.commands.status.select_editor",
            return_value=MagicMock(command="code"),
        )
        mock_open = mocker.patch("hive_cli.commands.status.open_in_editor")
        result = _interactive_status(statuses=statuses, main_repo=temp_git_repo)
        assert result is None
        mock_open.assert_called_once()


class TestStatusCliInteractiveFlag:
    def test_dash_i_exits_1_even_when_a_branch_is_selected(
        self, cli_runner: CycloptsTestRunner, temp_git_repo, mocker
    ):
        # See the bug noted on TestInteractiveStatus: -i always exits 1.
        mocker.patch(
            "hive_cli.commands.status.fuzzy_select", side_effect=["main", None]
        )
        mocker.patch(
            "hive_cli.commands.status._show_worktree_detail", return_value="back"
        )
        result = cli_runner.invoke(app, ["status", "-i"])
        assert result.exit_code == 1


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
        mocker.patch("hive_cli.commands.status.select_editor", return_value=editor)
        mock_open = mocker.patch("hive_cli.commands.status.open_in_editor")
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
        mocker.patch("hive_cli.commands.status._clear_screen_full")
        mock_delete = mocker.patch(
            "hive_cli.commands.status._delete_worktree_flow", return_value=deleted
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


# `_watch_interactive_loop`: the full raw-terminal loop needs a real pty
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
        monkeypatch.setattr("hive_cli.commands.status.sys.stdin", self._NoFilenoStdin())
        _watch_interactive_loop(compact=False)  # returns instead of raising
        assert cli_runner.invoke(app, ["status", "--watch"]).exit_code == 0
