"""Per-agent hook event -> pane status mapping, and the settings hive injects
to wire each agent's own hook mechanism to `hive-hook`.

Stdlib only (shared with `hooks/entry.py`, which must start in well under
30 ms). Verified against each agent's docs on 2026-09-09:
- Claude: code.claude.com/docs/en/hooks -- event names, `hook_event_name`,
  `Notification`'s `notification_type` values.
- Codex: `notify = [...]` in config.toml fires once per turn with a
  kebab-case JSON payload as the final argv token; `type` is currently a
  single-variant enum, `"agent-turn-complete"`.
- Gemini: `.gemini/settings.json`'s `hooks` object; lifecycle event names
  (SessionStart/BeforeAgent/AfterAgent/SessionEnd) and the
  `{event: [{"hooks": [{"type": "command", "command": ...}]}]}` shape.
"""

from __future__ import annotations

from ..state.pane_state import SUMMARY_MAX_LEN

CLAUDE_EVENTS = {
    "SessionStart": "idle",
    "UserPromptSubmit": "busy",
    "PreToolUse": "busy",
    "PostToolUse": "busy",
    "PostToolUseFailure": "busy",
    "PreCompact": "busy",
    "PermissionRequest": "waiting",
    "Stop": "done",
    "StopFailure": "done",
    "SessionEnd": "exited",
}
CLAUDE_NOTIFICATIONS = {  # payload["notification_type"]; other values -> None
    "permission_prompt": "waiting",
    "agent_needs_input": "waiting",
    "idle_prompt": "idle",
}
CODEX_EVENTS = {"agent-turn-complete": "done"}  # payload["type"]
GEMINI_EVENTS = {
    "SessionStart": "idle",
    "BeforeAgent": "busy",
    "BeforeTool": "busy",
    "AfterTool": "busy",
    "AfterAgent": "done",
    "SessionEnd": "exited",
}


def status_for(agent: str, payload: dict) -> str | None:
    """None = no status change (unknown agent/event). Never raises."""
    if agent == "claude":
        name = payload.get("hook_event_name", "")
        if name == "Notification":
            return CLAUDE_NOTIFICATIONS.get(payload.get("notification_type", ""))
        return CLAUDE_EVENTS.get(name)
    if agent == "codex":
        return CODEX_EVENTS.get(payload.get("type", ""))
    if agent == "gemini":
        return GEMINI_EVENTS.get(payload.get("hook_event_name", ""))
    return None


def summary_for(agent: str, payload: dict) -> str | None:
    """A one-line hint of what the session is about, when this event carries
    one; None otherwise (unknown agent/event, or no text in the payload).

    Only Claude's `UserPromptSubmit` payload carries the literal prompt text
    today; Codex only sends a turn-complete marker and Gemini's payloads
    carry no text either, so this is `None` for both -- the control plane
    falls back to a `hive task` assignment or task.local.md for them.
    """
    if agent != "claude" or payload.get("hook_event_name") != "UserPromptSubmit":
        return None
    prompt = payload.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        return None
    return prompt.strip().splitlines()[0][:SUMMARY_MAX_LEN]


def claude_settings(hive_hook: str) -> dict:
    """JSON for `claude --settings`: one command hook per event, + Notification."""
    events = [*CLAUDE_EVENTS, "Notification"]
    # "matcher": "" = fire for every tool / notification type / session source
    # (documented for Notification; undocumented for session events, so always send "").
    return {
        "hooks": {
            e: [
                {
                    "matcher": "",
                    "hooks": [
                        {
                            "type": "command",
                            "command": f"{hive_hook} claude",
                            "timeout": 5,
                        }
                    ],
                }
            ]
            for e in events
        }
    }


def codex_notify(hive_hook: str) -> str:
    return f'notify=["{hive_hook}","codex"]'


def gemini_settings(hive_hook: str) -> dict:
    events = list(GEMINI_EVENTS)
    return {
        "hooks": {
            e: [{"hooks": [{"type": "command", "command": f"{hive_hook} gemini"}]}]
            for e in events
        }
    }
