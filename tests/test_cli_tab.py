"""CLI tests for `hive tab`."""

from __future__ import annotations

from unittest.mock import patch

from hive_cli.app import app
from hive_cli.core.errors import HiveError


class TestTabDefault:
    def test_open_tab_calls_service(self, cli_runner):
        with patch("hive_cli.commands.tab.session.open_tab", return_value="tab1") as m:
            result = cli_runner.invoke(app, ["tab", "git"])
        assert result.exit_code == 0
        m.assert_called_once_with("git", focus=True)

    def test_no_focus(self, cli_runner):
        with patch("hive_cli.commands.tab.session.open_tab", return_value="tab1") as m:
            cli_runner.invoke(app, ["tab", "git", "--no-focus"])
        assert m.call_args.kwargs["focus"] is False

    def test_agents_special_name(self, cli_runner):
        with patch("hive_cli.commands.tab.session.open_tab", return_value="tab1") as m:
            cli_runner.invoke(app, ["tab", "agents"])
        m.assert_called_once_with("agents", focus=True)

    def test_unknown_tab_is_error(self, cli_runner):
        with patch(
            "hive_cli.commands.tab.session.open_tab",
            side_effect=HiveError("unknown tab: nope"),
        ):
            result = cli_runner.invoke(app, ["tab", "nope"])
        assert result.exit_code == 1
        assert "unknown tab" in result.output


class TestTabList:
    def test_lists_bundled_user_and_agents(self, cli_runner):
        result = cli_runner.invoke(app, ["tab", "list"])
        assert result.exit_code == 0
        lines = result.output.split()
        assert "agents" in lines
        assert "git" in lines
        assert "teams" in lines
