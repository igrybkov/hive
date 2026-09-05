"""Tests for utils/ picker modules: tty, workdir, agents, editors.

deps.py's functions moved to services/worktrees.py in A0 step 6 and are
tested in test_services_worktrees.py; setup_worktree_files() has its own
dedicated coverage in test_worktree_files.py.
"""

from __future__ import annotations

import io
import threading
from pathlib import Path
from unittest.mock import patch

from hive_cli.config import reload_config
from hive_cli.ui.tty import confirm, read_single_key
from hive_cli.utils.agents import select_agent
from hive_cli.utils.fuzzy import FuzzyItem
from hive_cli.utils.workdir import WORKDIR_CLEAR, select_workdir

# ---------------------------------------------------------------------------
# utils/tty.py
# ---------------------------------------------------------------------------


class TestConfirm:
    def test_yes_returns_true(self):
        with patch("hive_cli.ui.tty.read_single_key", return_value="y"):
            assert confirm("Proceed?") is True

    def test_uppercase_yes_returns_true(self):
        with patch("hive_cli.ui.tty.read_single_key", return_value="Y"):
            assert confirm("Proceed?") is True

    def test_no_returns_false(self):
        with patch("hive_cli.ui.tty.read_single_key", return_value="n"):
            assert confirm("Proceed?", default=True) is False

    def test_enter_uses_default_true(self):
        with patch("hive_cli.ui.tty.read_single_key", return_value="\r"):
            assert confirm("Proceed?", default=True) is True

    def test_enter_uses_default_false(self):
        with patch("hive_cli.ui.tty.read_single_key", return_value="\n"):
            assert confirm("Proceed?", default=False) is False

    def test_unrecognized_key_returns_false(self):
        with patch("hive_cli.ui.tty.read_single_key", return_value="x"):
            assert confirm("Proceed?", default=True) is False

    def test_no_key_available_returns_false(self):
        with patch("hive_cli.ui.tty.read_single_key", return_value=None):
            assert confirm("Proceed?", default=True) is False


class TestReadSingleKey:
    def test_dev_tty_unavailable_returns_none(self):
        # In sandboxed/CI environments /dev/tty typically has no controlling
        # terminal, so open() raises OSError and read_single_key degrades
        # gracefully to None rather than raising.
        assert read_single_key() is None

    def test_returns_typed_character_when_tty_available(self, monkeypatch):
        """Simulate a real /dev/tty by faking open() + termios for this module."""

        class FakeTtyFile(io.StringIO):
            def fileno(self):
                return 99

        fake_file = FakeTtyFile("q")

        def fake_open(path, *args, **kwargs):
            if path == "/dev/tty":
                return fake_file
            raise AssertionError(f"unexpected open() call: {path}")

        monkeypatch.setattr("hive_cli.ui.tty.open", fake_open, raising=False)
        with (
            patch("termios.tcgetattr", return_value="fake-settings"),
            patch("termios.tcsetattr"),
            patch("tty.setraw"),
        ):
            assert read_single_key() == "q"

    def test_termios_failure_returns_none(self, monkeypatch):
        class FakeTtyFile(io.StringIO):
            def fileno(self):
                return 99

        fake_file = FakeTtyFile("q")

        def fake_open(path, *args, **kwargs):
            return fake_file

        monkeypatch.setattr("hive_cli.ui.tty.open", fake_open, raising=False)
        with patch("termios.tcgetattr", side_effect=OSError("no tty attrs")):
            assert read_single_key() is None


# ---------------------------------------------------------------------------
# utils/workdir.py
# ---------------------------------------------------------------------------


class TestSelectWorkdir:
    def test_no_extra_dirs_returns_none_without_prompting(self, temp_git_repo):
        with patch("hive_cli.utils.workdir.fuzzy_select") as mock_select:
            result = select_workdir(current_agent="claude")
        assert result is None
        mock_select.assert_not_called()

    def _configure_extra_dirs(self, repo: Path, dirs: list[str]) -> None:
        dirs_yaml = "\n".join(f"  - {d}" for d in dirs)
        (repo / ".hive.yml").write_text(f"extra_dirs:\n{dirs_yaml}\n")
        reload_config()

    def test_selecting_an_extra_dir_returns_its_path(self, temp_git_repo):
        self._configure_extra_dirs(temp_git_repo, ["../sibling-one", "../sibling-two"])

        captured_items: list[FuzzyItem] = []

        def fake_fuzzy_select(items, **kwargs):
            captured_items.extend(items)
            # Select the first extra dir (index 1; index 0 is "Default").
            return items[1].value

        with patch(
            "hive_cli.utils.workdir.fuzzy_select", side_effect=fake_fuzzy_select
        ):
            result = select_workdir(current_agent="claude")

        assert result == Path(captured_items[1].value)
        assert captured_items[0].text == "Default (no override)"

    def test_selecting_default_returns_clear_sentinel(self, temp_git_repo):
        self._configure_extra_dirs(temp_git_repo, ["../sibling-one"])

        with patch(
            "hive_cli.utils.workdir.fuzzy_select",
            side_effect=lambda items, **kwargs: items[0].value,
        ):
            result = select_workdir(current_agent="claude")

        assert result is WORKDIR_CLEAR

    def test_cancel_returns_none(self, temp_git_repo):
        self._configure_extra_dirs(temp_git_repo, ["../sibling-one"])

        with patch("hive_cli.utils.workdir.fuzzy_select", return_value=None):
            result = select_workdir(current_agent="claude")

        assert result is None

    def test_current_override_marked_and_preselected(self, temp_git_repo):
        self._configure_extra_dirs(temp_git_repo, ["../sibling-one", "../sibling-two"])
        main_repo = temp_git_repo
        current = (main_repo / "../sibling-two").resolve()

        captured_kwargs = {}

        def fake_fuzzy_select(items, **kwargs):
            captured_kwargs.update(kwargs)
            return None

        with patch(
            "hive_cli.utils.workdir.fuzzy_select", side_effect=fake_fuzzy_select
        ):
            select_workdir(current_agent="claude", current_override=current)

        # sibling-two is the 2nd extra dir -> index 2 (0 is "Default").
        assert captured_kwargs["initial_selection"] == 2

    def test_header_warns_when_agent_has_no_extra_dirs_flag(self, temp_git_repo):
        self._configure_extra_dirs(temp_git_repo, ["../sibling-one"])

        captured_kwargs = {}

        def fake_fuzzy_select(items, **kwargs):
            captured_kwargs.update(kwargs)
            return None

        with patch(
            "hive_cli.utils.workdir.fuzzy_select", side_effect=fake_fuzzy_select
        ):
            # "totally-unknown-agent" has no entry in agents.configs, so
            # get_agent_config() falls back to a default AgentConfig with
            # extra_dirs_flag=None.
            select_workdir(current_agent="totally-unknown-agent")

        assert "warning" in captured_kwargs["header"]

    def test_header_has_no_warning_for_agent_with_extra_dirs_flag(self, temp_git_repo):
        self._configure_extra_dirs(temp_git_repo, ["../sibling-one"])

        captured_kwargs = {}

        def fake_fuzzy_select(items, **kwargs):
            captured_kwargs.update(kwargs)
            return None

        with patch(
            "hive_cli.utils.workdir.fuzzy_select", side_effect=fake_fuzzy_select
        ):
            select_workdir(current_agent="claude")

        assert "warning" not in captured_kwargs["header"]


# ---------------------------------------------------------------------------
# utils/agents.py
# ---------------------------------------------------------------------------
#
# select_agent() starts a real background thread *before* calling
# fuzzy_select(); the thread blocks on `update_callbacks_ready` until the
# (real, interactive) fuzzy_select populates it. Our fake fuzzy_select does
# that immediately, then blocks on a `done` Event that the background
# thread's update_items() callback sets — bounding the wait without any
# fixed sleep, and without needing to stub threading.Thread itself.


class TestSelectAgent:
    def test_returns_selected_agent_and_marks_current(self):
        captured = {}
        done = threading.Event()

        def fake_fuzzy_select(
            items, update_callbacks=None, update_callbacks_ready=None, **kwargs
        ):
            def update_items(new_items):
                captured["items"] = new_items
                done.set()

            def update_header(new_header):
                captured["header"] = new_header

            update_callbacks.append((update_items, update_header))
            update_callbacks_ready.set()
            done.wait(timeout=1.0)
            return "gemini"

        with (
            patch(
                "hive_cli.utils.agents.get_available_agents",
                return_value=["claude", "gemini"],
            ),
            patch("hive_cli.utils.agents.fuzzy_select", side_effect=fake_fuzzy_select),
        ):
            result = select_agent(current_agent="claude")

        assert result == "gemini"
        assert captured["header"] == "Select agent"
        by_value = {item.value: item for item in captured["items"]}
        assert by_value["claude"].meta == "← current"
        assert by_value["claude"].style == "green"
        assert by_value["gemini"].meta == ""

    def test_no_agents_found_updates_header_with_error(self):
        captured = {}
        done = threading.Event()

        def fake_fuzzy_select(
            items, update_callbacks=None, update_callbacks_ready=None, **kwargs
        ):
            def update_items(new_items):
                captured["items"] = new_items
                done.set()

            def update_header(new_header):
                captured["header"] = new_header

            update_callbacks.append((update_items, update_header))
            update_callbacks_ready.set()
            done.wait(timeout=1.0)
            return None

        with (
            patch("hive_cli.utils.agents.get_available_agents", return_value=[]),
            patch("hive_cli.utils.agents.fuzzy_select", side_effect=fake_fuzzy_select),
        ):
            result = select_agent(current_agent="claude")

        assert result is None
        assert "no agents found" in captured["header"]
        assert "No supported agents" in captured["items"][0].text

    def test_cancelled_selection_returns_none(self):
        with patch("hive_cli.utils.agents.fuzzy_select", return_value=None):
            assert select_agent(current_agent="claude") is None

    def test_empty_string_selection_treated_as_none(self):
        with patch("hive_cli.utils.agents.fuzzy_select", return_value=""):
            assert select_agent(current_agent="claude") is None


# ---------------------------------------------------------------------------
# utils/editors.py (select_editor picker; get_available_editors/open_in_editor
# themselves are tested in test_services_editors.py, moved with their code)
# ---------------------------------------------------------------------------


class TestSelectEditorNoneAvailable:
    def test_returns_none_and_reports_error(self):
        from hive_cli.utils.editors import select_editor

        with patch("hive_cli.services.editors.shutil.which", return_value=None):
            assert select_editor() is None


class TestSelectEditorSingleAvailable:
    def test_returns_the_only_editor_without_prompting(self):
        from hive_cli.utils.editors import select_editor

        def fake_which(cmd):
            return "/usr/bin/code" if cmd == "code" else None

        with (
            patch("hive_cli.services.editors.shutil.which", side_effect=fake_which),
            patch("hive_cli.utils.editors.fuzzy_select") as mock_select,
        ):
            result = select_editor()

        assert result.command == "code"
        mock_select.assert_not_called()


class TestSelectEditorMultipleAvailable:
    def test_prompts_and_returns_chosen_editor(self):
        from hive_cli.utils.editors import select_editor

        with (
            patch("hive_cli.services.editors.shutil.which", return_value="/usr/bin/x"),
            patch("hive_cli.utils.editors.fuzzy_select", return_value="cursor"),
        ):
            result = select_editor()

        assert result.command == "cursor"

    def test_cancelled_returns_none(self):
        from hive_cli.utils.editors import select_editor

        with (
            patch("hive_cli.services.editors.shutil.which", return_value="/usr/bin/x"),
            patch("hive_cli.utils.editors.fuzzy_select", return_value=None),
        ):
            assert select_editor() is None
