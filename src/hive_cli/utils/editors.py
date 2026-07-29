"""Editor utilities for opening worktrees in editors."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .fuzzy import FuzzyItem, fuzzy_select
from .terminal import error, info


@dataclass
class EditorConfig:
    """Configuration for an editor."""

    name: str  # Display name
    command: str  # Command to run
    chat_flag: str | None = None  # Flag to open chat/composer (if any)


# Available editors for "open in editor" action
EDITORS: list[EditorConfig] = [
    EditorConfig("VS Code", "code", None),
    EditorConfig("PyCharm", "pycharm", None),
    EditorConfig("Cursor", "cursor", "--new-window"),
]


def get_available_editors() -> list[EditorConfig]:
    """Get list of editors that are installed."""
    return [e for e in EDITORS if shutil.which(e.command)]


def select_editor() -> EditorConfig | None:
    """Show picker for selecting an editor.

    Returns:
        Selected EditorConfig, or None if cancelled.
    """
    available = get_available_editors()
    if not available:
        error("No supported editors found (code, cursor, pycharm)")
        return None

    if len(available) == 1:
        return available[0]

    items = [FuzzyItem(text=e.name, value=e.command, meta="") for e in available]

    selected = fuzzy_select(
        items=items,
        prompt_text=">",
        header="Select editor",
        hint="</dim><b>Enter</b><dim> select  </dim><b>Esc</b><dim> back",
    )

    if selected is None:
        return None

    return next((e for e in available if e.command == selected), None)


def open_in_editor(path: Path, editor: EditorConfig) -> None:
    """Open worktree in editor.

    Args:
        path: Path to the worktree.
        editor: Editor configuration.
    """
    cmd = [editor.command]
    if editor.chat_flag:
        cmd.append(editor.chat_flag)
    cmd.append(str(path))

    info(f"Opening in {editor.name}...")
    subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
