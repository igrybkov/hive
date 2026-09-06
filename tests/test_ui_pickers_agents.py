"""Tests for hive_cli.ui.pickers.agents.select_agent.

select_agent() starts a real background thread *before* calling
fuzzy_select(); the thread blocks on `update_callbacks_ready` until the
(real, interactive) fuzzy_select populates it. Our fake fuzzy_select does
that immediately, then blocks on a `done` Event that the background
thread's update_items() callback sets -- bounding the wait without any
fixed sleep, and without needing to stub threading.Thread itself.
"""

from __future__ import annotations

import threading
from unittest.mock import patch

from hive_cli.ui.pickers.agents import select_agent


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
                "hive_cli.ui.pickers.agents.get_available_agents",
                return_value=["claude", "gemini"],
            ),
            patch(
                "hive_cli.ui.pickers.agents.fuzzy_select", side_effect=fake_fuzzy_select
            ),
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
            patch("hive_cli.ui.pickers.agents.get_available_agents", return_value=[]),
            patch(
                "hive_cli.ui.pickers.agents.fuzzy_select", side_effect=fake_fuzzy_select
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
