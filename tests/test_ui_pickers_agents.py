"""Tests for ui.pickers.agents.select_agent: items are built before the picker opens."""

from __future__ import annotations

from unittest.mock import patch

from hive_cli.ui.pickers.agents import select_agent


def _capturing_fuzzy_select(captured: dict, result):
    def fake_fuzzy_select(items, **kwargs):
        captured["items"] = items
        captured["header"] = kwargs["header"]
        return result

    return fake_fuzzy_select


class TestSelectAgent:
    def test_returns_selected_agent_and_marks_current(self):
        captured: dict = {}
        with (
            patch(
                "hive_cli.ui.pickers.agents.get_available_agents",
                return_value=["claude", "gemini"],
            ),
            patch(
                "hive_cli.ui.pickers.agents.fuzzy_select",
                side_effect=_capturing_fuzzy_select(captured, "gemini"),
            ),
        ):
            result = select_agent(current_agent="claude")

        assert result == "gemini"
        assert captured["header"] == "Select agent"
        by_value = {item.value: item for item in captured["items"]}
        assert by_value["claude"].meta == "← current"
        assert by_value["claude"].style == "green"
        assert by_value["gemini"].meta == ""

    def test_no_agents_found_shows_error_header_and_placeholder(self):
        captured: dict = {}
        with (
            patch("hive_cli.ui.pickers.agents.get_available_agents", return_value=[]),
            patch(
                "hive_cli.ui.pickers.agents.fuzzy_select",
                side_effect=_capturing_fuzzy_select(captured, None),
            ),
        ):
            result = select_agent(current_agent="claude")

        assert result is None
        assert "no agents found" in captured["header"]
        assert "No supported agents" in captured["items"][0].text

    def test_cancelled_selection_returns_none(self):
        with patch("hive_cli.ui.pickers.agents.fuzzy_select", return_value=None):
            assert select_agent(current_agent="claude") is None

    def test_empty_string_selection_treated_as_none(self):
        with patch("hive_cli.ui.pickers.agents.fuzzy_select", return_value=""):
            assert select_agent(current_agent="claude") is None
