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
    status = templates.status_for(argv[1], read_payload(argv))
    if status:
        client.set_fields(Path(sock), status=status)
    return 0
