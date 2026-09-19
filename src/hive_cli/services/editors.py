"""Installed-editor discovery and launching."""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path


def _noop(_message: str) -> None:
    pass


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


def open_in_editor(
    path: Path,
    editor: EditorConfig,
    *,
    progress: Callable[[str], None] = _noop,
) -> None:
    """Open worktree in editor (detached, does not wait for it to close).

    Args:
        path: Path to the worktree.
        editor: Editor configuration.
        progress: Called with a human-readable status line.
    """
    cmd = [editor.command]
    if editor.chat_flag:
        cmd.append(editor.chat_flag)
    cmd.append(str(path))

    progress(f"Opening in {editor.name}...")
    subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def edit_in_terminal_editor(editor: str, path: Path) -> None:
    """Launch a terminal $EDITOR on path, inheriting the tty.

    Blocks until the editor exits, unlike open_in_editor()'s detached GUI
    launch.

    Args:
        editor: Editor command (e.g. from RuntimeSettings.editor).
        path: File to open.
    """
    subprocess.run([editor, str(path)])
