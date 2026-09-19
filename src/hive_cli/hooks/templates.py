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
