"""Interactive selection utilities.

Provides fzf-based selection with fallback to numbered menu.
"""

from __future__ import annotations

import shutil
import subprocess
import sys

from rich.console import Console

# Console for stderr output (used for selection prompts)
stderr_console = Console(stderr=True)


def has_fzf() -> bool:
    """Check if fzf is available.

    Returns:
        True if fzf is installed and available in PATH.
    """
    return shutil.which("fzf") is not None


def is_interactive() -> bool:
    """Check if we're running in an interactive terminal.

    Returns:
        True if stdin is connected to a TTY.
    """
    return sys.stdin.isatty()


def fzf_select(
    options: list[str],
    prompt: str = "Select> ",
    header: str | None = None,
) -> str | None:
    """Select an option using fzf.

    Args:
        options: List of options to choose from.
        prompt: Prompt to display.
        header: Optional header text.

    Returns:
        Selected option, or None if cancelled.
    """
    if not options:
        return None

    cmd = [
        "fzf",
        "--height=50%",
        "--reverse",
        "--border",
        f"--prompt={prompt}",
    ]
    if header:
        cmd.append(f"--header={header}")

    try:
        result = subprocess.run(
            cmd,
            input="\n".join(options),
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        # User cancelled (ESC or Ctrl-C)
        return None


def numbered_select(
    options: list[str],
    prompt: str = "Select: ",
) -> str | None:
    """Select an option using a numbered menu.

    Fallback when fzf is not available.

    Args:
        options: List of options to choose from.
        prompt: Prompt to display.

    Returns:
        Selected option, or None if cancelled or invalid.
    """
    if not options:
        return None

    # Display numbered options
    for i, opt in enumerate(options, 1):
        stderr_console.print(f"  [cyan][{i}][/] {opt}")
    stderr_console.print()

    try:
        choice = input(prompt)
        if not choice:
            return None

        idx = int(choice) - 1
        if 0 <= idx < len(options):
            return options[idx]
    except (ValueError, EOFError, KeyboardInterrupt):
        pass

    return None


def interactive_select(
    options: list[str],
    prompt: str = "Select> ",
    header: str | None = None,
) -> str | None:
    """Select an option interactively.

    Uses fzf if available, falls back to numbered menu otherwise.

    Args:
        options: List of options to choose from.
        prompt: Prompt to display.
        header: Optional header text (only used with fzf).

    Returns:
        Selected option, or None if cancelled.
    """
    if not is_interactive():
        return None

    if has_fzf():
        return fzf_select(options, prompt, header)
    return numbered_select(options, prompt)
