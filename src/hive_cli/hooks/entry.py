"""hive-hook <agent> [payload-json]: map an agent hook event to a pane status.

Always exits 0.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from hive_cli.hooks import templates
from hive_cli.state import client


def read_payload(argv: list[str]) -> dict:
    """Codex passes JSON as the last argv; Claude/Gemini pass it on stdin.

    Empty/invalid -> {}.
    """
    raw = (
        argv[2]
        if len(argv) > 2
        else (sys.stdin.read() if not sys.stdin.isatty() else "")
    )
    try:
        data = json.loads(raw) if raw.strip() else {}
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv if argv is None else argv
    if len(argv) < 2:
        return 0
    sock = os.environ.get("HIVE_PANE_SOCK")
    if not sock:
        return 0
    sock_path = Path(sock)
    payload = read_payload(argv)
    fields: dict[str, object] = {}
    status = templates.status_for(argv[1], payload)
    if status:
        fields["status"] = status
    summary = templates.summary_for(argv[1], payload)
    if summary:
        # First-prompt-wins: only claim the summary slot if nobody has yet.
        current = client.get_state(sock_path)
        if current is not None and not current.get("summary"):
            fields["summary"] = summary
    if fields:
        client.set_fields(sock_path, **fields)
    return 0
