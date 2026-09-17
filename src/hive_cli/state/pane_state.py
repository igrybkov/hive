"""PaneState: the typed state one `hive run` owns for its pane, plus the pure
composition helpers built on it (pane title, tab name, on-demand identity).

Stdlib only -- shared with the socket server/client and, later, the hook
entry point. The title format is exactly what utils/zellij.rebuild_pane_title
produced before F0; see compose_title.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, fields
from pathlib import Path

SCHEMA = 1

_PANE_TITLE_ID_RE = re.compile(r"^(?:hold: )?c(\d+)(?::|$)")

STATUSES = (
    "selecting",
    "starting",
    "running",
    "busy",
    "waiting",
    "idle",
    "done",
    "exited",
)

ICONS = {
    "selecting": "…",
    "starting": "·",
    "running": "✳",
    "busy": "✳",
    "waiting": "⏳",
    "done": "✅",
    "idle": "○",
    "exited": "✖",
}

# Fields a socket client may `set`; everything else is owned by `hive run`.
CLIENT_SETTABLE = frozenset(
    {
        "status",
        "status_text",
        "custom_title",
        "branch",
        "worktree_path",
        "agent",
        "profile",
        "agent_pid",
        "tab_id",
    }
)


@dataclass
class PaneState:
    schema: int = SCHEMA
    session: str = ""
    pane_id: str = ""  # multiplexer pane id: "3" (zellij terminal_3) or "%3" (tmux)
    tab_id: str = ""
    hive_pane_id: int = 0  # HIVE_PANE_ID (c1, c2, ...); 0 = unknown
    label: str = ""  # HIVE_PANE_LABEL
    agent: str = ""
    profile: str = ""
    branch: str = ""
    worktree_path: str = ""
    status: str = "selecting"  # one of STATUSES
    status_since: float = 0.0  # time.time() of the last status change
    # Free-form text from `hive zellij set-status` (kept for compatibility).
    status_text: str = ""
    custom_title: str = ""
    agent_pid: int = 0
    hive_pid: int = 0
    version: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> PaneState:
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})


def compose_title(
    *,
    hive_pane_id: int,
    label: str,
    agent: str,
    mux_pane_id: str,
    status_text: str,
    branch: str,
    custom_title: str,
    cwd: Path | None = None,
) -> str:
    """Build a pane title from layout position, agent, and pane state.

    Exactly the string utils/zellij.rebuild_pane_title used to build:

    - In the layout (hive_pane_id > 0): ``c{id}: {label} [{agent}]`` -- the base
      name is reconstructed because Zellij >= 0.44.1's rename-pane replaces
      the whole title instead of appending to the layout-defined one.
    - Outside the layout: ``{agent}-{mux_pane_id}``, or the cwd relative to
      home (``~/proj``) / absolute when there is no agent either.

    Then, in order: ``status_text``, ``[branch]``, ``custom_title``.
    """
    parts: list[str] = []
    if hive_pane_id:
        parts.append(f"c{hive_pane_id}: {label}" if label else f"c{hive_pane_id}")
        if agent:
            parts.append(f"[{agent}]")
    elif agent:
        parts.append(f"{agent}-{mux_pane_id}")
    else:
        cwd = cwd or Path.cwd()
        try:
            parts.append(f"~/{cwd.relative_to(Path.home())}")
        except ValueError:
            parts.append(str(cwd))
    if status_text:
        parts.append(status_text)
    if branch:
        parts.append(f"[{branch}]")
    if custom_title:
        parts.append(custom_title)
    return " ".join(parts)


def title_for(state: PaneState, cwd: Path | None = None) -> str:
    return compose_title(
        hive_pane_id=state.hive_pane_id,
        label=state.label,
        agent=state.agent,
        mux_pane_id=state.pane_id,
        status_text=state.status_text,
        branch=state.branch,
        custom_title=state.custom_title,
        cwd=cwd,
    )


def compose_tab_name(states: list[PaneState]) -> str:
    """``feat-auth ✳ · fix-ci ⏳``: per pane, branch (12 chars max) or label or
    c<id> plus the status icon; ordered by hive pane number; ``hive`` if empty.
    """
    parts = []
    for s in sorted(states, key=lambda s: (s.hive_pane_id or 999, s.pane_id)):
        name = (s.branch or s.label or f"c{s.hive_pane_id}")[:12]
        parts.append(f"{name} {ICONS.get(s.status, '?')}")
    return " · ".join(parts) or "hive"


def next_free_pane_id(taken: list[int]) -> int:
    """Smallest positive pane number not in ``taken`` (for on-demand panes)."""
    n = 1
    while n in taken:
        n += 1
    return n


def label_for(pane_id: int, labels: list[str]) -> str:
    """The configured label for pane number ``pane_id`` (1-based), or ``""``."""
    return labels[pane_id - 1] if 0 < pane_id <= len(labels) else ""


def pane_hive_id(title: str) -> int | None:
    """Parse the `HIVE_PANE_ID` a layout pane was given from its `cN[: label]`
    title (agents_tab names panes this way before `hive run` ever starts and
    registers a socket -- a `start_suspended` pane has no live state yet).
    The optional `"hold: "` prefix matches the tmux backend's suspended-pane
    title (`commands/pane.py:hold`'s `_hold_identity`), which carries the
    same `cN[: label]` identity behind that marker instead of in front of it.
    """
    m = _PANE_TITLE_ID_RE.match(title)
    return int(m.group(1)) if m else None
