"""Tests for hive_cli.hooks.templates: event -> status mapping and settings shapes."""

from __future__ import annotations

import json

import pytest

from hive_cli.hooks.templates import (
    CLAUDE_EVENTS,
    CLAUDE_NOTIFICATIONS,
    CODEX_EVENTS,
    GEMINI_EVENTS,
    claude_settings,
    codex_notify,
    gemini_settings,
    status_for,
    summary_for,
)
from hive_cli.state.pane_state import SUMMARY_MAX_LEN

# ---------------------------------------------------------------------------
# status_for
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("event, expected", list(CLAUDE_EVENTS.items()))
def test_claude_event_table(event, expected):
    assert status_for("claude", {"hook_event_name": event}) == expected


@pytest.mark.parametrize(
    "notification_type, expected", list(CLAUDE_NOTIFICATIONS.items())
)
def test_claude_notification_table(notification_type, expected):
    payload = {
        "hook_event_name": "Notification",
        "notification_type": notification_type,
    }
    assert status_for("claude", payload) == expected


def test_claude_notification_unknown_type_is_none():
    payload = {"hook_event_name": "Notification", "notification_type": "auth_success"}
    assert status_for("claude", payload) is None


@pytest.mark.parametrize("event, expected", list(CODEX_EVENTS.items()))
def test_codex_event_table(event, expected):
    assert status_for("codex", {"type": event}) == expected


@pytest.mark.parametrize("event, expected", list(GEMINI_EVENTS.items()))
def test_gemini_event_table(event, expected):
    assert status_for("gemini", {"hook_event_name": event}) == expected


def test_unknown_claude_event_is_none():
    assert status_for("claude", {"hook_event_name": "SomeFutureEvent"}) is None


def test_unknown_codex_event_is_none():
    assert status_for("codex", {"type": "something-else"}) is None


def test_unknown_gemini_event_is_none():
    assert status_for("gemini", {"hook_event_name": "SomeFutureEvent"}) is None


def test_unknown_agent_is_none():
    assert status_for("copilot", {"hook_event_name": "Stop"}) is None


def test_empty_payload_is_none():
    assert status_for("claude", {}) is None
    assert status_for("codex", {}) is None
    assert status_for("gemini", {}) is None


# ---------------------------------------------------------------------------
# summary_for
# ---------------------------------------------------------------------------


def test_summary_for_claude_user_prompt_submit():
    payload = {"hook_event_name": "UserPromptSubmit", "prompt": "fix the login bug"}
    assert summary_for("claude", payload) == "fix the login bug"


def test_summary_for_takes_first_line_only():
    payload = {
        "hook_event_name": "UserPromptSubmit",
        "prompt": "first line\nsecond line",
    }
    assert summary_for("claude", payload) == "first line"


def test_summary_for_truncates_long_prompts():
    payload = {"hook_event_name": "UserPromptSubmit", "prompt": "z" * 80}
    assert summary_for("claude", payload) == "z" * SUMMARY_MAX_LEN


def test_summary_for_none_when_prompt_missing():
    assert summary_for("claude", {"hook_event_name": "UserPromptSubmit"}) is None


def test_summary_for_none_when_prompt_blank():
    payload = {"hook_event_name": "UserPromptSubmit", "prompt": "   "}
    assert summary_for("claude", payload) is None


def test_summary_for_none_on_other_claude_events():
    assert summary_for("claude", {"hook_event_name": "Stop", "prompt": "x"}) is None


def test_summary_for_none_for_codex_and_gemini():
    assert summary_for("codex", {"type": "agent-turn-complete"}) is None
    assert summary_for("gemini", {"hook_event_name": "BeforeAgent"}) is None


# ---------------------------------------------------------------------------
# claude_settings
# ---------------------------------------------------------------------------


def test_claude_settings_has_one_entry_per_event_plus_notification():
    settings = claude_settings("/x/hive-hook")
    expected_events = {*CLAUDE_EVENTS, "Notification"}
    assert set(settings["hooks"]) == expected_events


def test_claude_settings_every_entry_has_matcher_and_timeout():
    settings = claude_settings("/x/hive-hook")
    for event, entries in settings["hooks"].items():
        assert len(entries) == 1
        entry = entries[0]
        assert entry["matcher"] == ""
        assert len(entry["hooks"]) == 1
        hook = entry["hooks"][0]
        assert hook["type"] == "command"
        assert hook["command"] == "/x/hive-hook claude"
        assert hook["timeout"] == 5


def test_claude_settings_is_json_serializable():
    settings = claude_settings("/x/hive-hook")
    assert json.loads(json.dumps(settings)) == settings


# ---------------------------------------------------------------------------
# codex_notify
# ---------------------------------------------------------------------------


def test_codex_notify_format():
    assert codex_notify("/x/hive-hook") == 'notify=["/x/hive-hook","codex"]'


# ---------------------------------------------------------------------------
# gemini_settings
# ---------------------------------------------------------------------------


def test_gemini_settings_has_one_entry_per_event():
    settings = gemini_settings("/x/hive-hook")
    assert set(settings["hooks"]) == set(GEMINI_EVENTS)


def test_gemini_settings_command_shape():
    settings = gemini_settings("/x/hive-hook")
    for event, entries in settings["hooks"].items():
        assert len(entries) == 1
        hook = entries[0]["hooks"][0]
        assert hook["type"] == "command"
        assert hook["command"] == "/x/hive-hook gemini"
