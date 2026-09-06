"""Pure pane-title composition.

Moved from utils/zellij.py's `rebuild_pane_title` (A0 step 9): the string-
building half, split out from the Zellij-specific I/O (runtime settings,
`rename_pane`) which stays in `mux/zellij/backend.py`.
"""

from __future__ import annotations

from pathlib import Path


def compose_title(
    *,
    pane_id: str | None,
    pane_label: str | None,
    agent: str | None,
    zellij_pane_id: str,
    status: str | None,
    branch: str | None,
    custom_title: str | None,
    cwd: Path,
    home: Path,
) -> str:
    """Build a pane title from layout position, agent, and stored state.

    Title format depends on context:
    - With a pane_id (in layout): c{id}: {label} [{agent}] {status} [{branch}]
      Base reconstructed from pane_id + pane_label (Zellij 0.44.1 changed
      rename-pane to full-replace instead of append-to-layout).
    - Without a pane_id: {agent}-{zellij_pane_id} {status} [{branch}]
      {custom_title}, or falls back to cwd relative to home.
    """
    parts: list[str] = []

    if pane_id:
        # Reconstruct the layout base name since rename-pane now replaces entirely.
        if pane_label:
            parts.append(f"c{pane_id}: {pane_label}")
        else:
            parts.append(f"c{pane_id}")

        if agent:
            parts.append(f"[{agent}]")
    else:
        # Not in layout - need to set the full name including prefix
        if agent:
            # Use ZELLIJ_PANE_ID as fallback for pane numbering
            parts.append(f"{agent}-{zellij_pane_id}")
        else:
            # Fallback to current directory path relative to home
            try:
                relative = cwd.relative_to(home)
                parts.append(f"~/{relative}")
            except ValueError:
                # cwd is not under home, use absolute path
                parts.append(str(cwd))

    if status:
        parts.append(status)

    if branch:
        parts.append(f"[{branch}]")

    if custom_title:
        parts.append(custom_title)

    return " ".join(parts)
