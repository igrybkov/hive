"""Installed-editor discovery and launching.

NOTE (A0 step 6): open_in_editor() still calls ui.console.info() directly,
a deliberate, temporary architecture-guard violation (services -> ui isn't
sideways-ok) -- like agents/launch.py's deferred git import from step 3,
tests/test_architecture.py is red until step 10 regardless. Deferred to
step 7, when ui/pickers/editors.py exists and can pass a `progress`
callback instead (see the spec's print -> progress pattern).
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ..ui.console import info


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
