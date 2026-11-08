"""Tests for hive_cli.ui.pickers.workdir.select_workdir."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from hive_cli.config import reload_config
from hive_cli.ui.pickers.fuzzy import FuzzyItem
from hive_cli.ui.pickers.workdir import WORKDIR_CLEAR, select_workdir


class TestSelectWorkdir:
    def test_no_extra_dirs_returns_none_without_prompting(self, temp_git_repo):
        with patch("hive_cli.ui.pickers.workdir.fuzzy_select") as mock_select:
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
            "hive_cli.ui.pickers.workdir.fuzzy_select", side_effect=fake_fuzzy_select
        ):
            result = select_workdir(current_agent="claude")

        assert result == Path(captured_items[1].value)
        assert captured_items[0].text == "Default (no override)"

    def test_selecting_default_returns_clear_sentinel(self, temp_git_repo):
        self._configure_extra_dirs(temp_git_repo, ["../sibling-one"])

        with patch(
            "hive_cli.ui.pickers.workdir.fuzzy_select",
            side_effect=lambda items, **kwargs: items[0].value,
        ):
            result = select_workdir(current_agent="claude")

        assert result is WORKDIR_CLEAR

    def test_cancel_returns_none(self, temp_git_repo):
        self._configure_extra_dirs(temp_git_repo, ["../sibling-one"])

        with patch("hive_cli.ui.pickers.workdir.fuzzy_select", return_value=None):
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
            "hive_cli.ui.pickers.workdir.fuzzy_select", side_effect=fake_fuzzy_select
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
            "hive_cli.ui.pickers.workdir.fuzzy_select", side_effect=fake_fuzzy_select
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
            "hive_cli.ui.pickers.workdir.fuzzy_select", side_effect=fake_fuzzy_select
        ):
            select_workdir(current_agent="claude")

        assert "warning" not in captured_kwargs["header"]
