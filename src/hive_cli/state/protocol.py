"""Pane-socket wire protocol: AF_UNIX stream, one JSON object per line, UTF-8.

    on connect          S->C {"type":"state", ...PaneState fields...}
    {"op":"ping"}       S->C {"type":"pong"}
    {"op":"get"}        S->C {"type":"state", ...}
    {"op":"set",        S->C {"type":"ok","version":N}
     "fields":{...}}         | {"type":"error","message":"unknown field: x"}
                             | {"type":"error","message":"invalid status: x"}
    {"op":"subscribe"}  S->C {"type":"state", ...} now, then on every change;
                        S->C {"type":"ping"} after 15 s of silence (ignored)
    {"op":"restart"}    S->C {"type":"ok"}   (server SIGTERMs the agent)
    {"op":"stop"}       S->C {"type":"ok"}   (same, and the run loop ends)
    {"op":"bogus"}      S->C {"type":"error","message":"unknown op: bogus"}
    <not JSON>          S->C {"type":"error","message":"bad json"}

Only `pane_state.CLIENT_SETTABLE` fields may be `set`. The client closes the
connection when done; the server never closes it first except on close().
"""

from __future__ import annotations

import json

SCHEMA = 1
OPS = frozenset({"ping", "get", "set", "subscribe", "restart", "stop"})


def encode(msg: dict) -> bytes:
    return (json.dumps(msg, separators=(",", ":"), ensure_ascii=False) + "\n").encode(
        "utf-8"
    )


def decode(line: bytes) -> dict | None:
    """The JSON object on ``line``, or None when it is not one."""
    try:
        obj = json.loads(line.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    return obj if isinstance(obj, dict) else None
