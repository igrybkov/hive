"""TTY input handling utilities."""

from __future__ import annotations

from rich.console import Console

stderr_console = Console(stderr=True)


def read_line_from_tty(
    prompt_text: str = "", propagate_interrupt: bool = False
) -> str | None:
    """Read a line from TTY, bypassing stdin redirection.

    Args:
        prompt_text: Optional prompt to display.
        propagate_interrupt: If True, re-raise KeyboardInterrupt instead of
            returning None. Useful when caller wants Ctrl+C to exit completely.

    Returns:
        The input line, or None if cancelled/EOF.

    Raises:
        KeyboardInterrupt: If propagate_interrupt is True and user presses Ctrl+C.
    """
    try:
        # Open /dev/tty directly to bypass any stdin redirection
        with open("/dev/tty") as tty:
            if prompt_text:
                from .terminal import prompt

                prompt(prompt_text)
            line = tty.readline()
            return line.strip() if line else None
    except KeyboardInterrupt:
        if propagate_interrupt:
            raise
        return None
    except (OSError, EOFError):
        return None


def read_single_key() -> str | None:
    """Read a single keypress from TTY.

    Returns:
        The key pressed, or None if cancelled.
    """
    try:
        import termios
        import tty as tty_module

        with open("/dev/tty") as tty_file:
            fd = tty_file.fileno()
            old_settings = termios.tcgetattr(fd)
            try:
                tty_module.setraw(fd)
                ch = tty_file.read(1)
                return ch
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
    except (OSError, EOFError, KeyboardInterrupt):
        return None


def confirm(message: str, default: bool = False) -> bool:
    """Ask for yes/no confirmation.

    Args:
        message: The confirmation message.
        default: Default value if user just presses Enter.

    Returns:
        True if confirmed, False otherwise.
    """
    from .terminal import prompt

    suffix = " [Y/n] " if default else " [y/N] "
    prompt(message + suffix)

    key = read_single_key()
    stderr_console.print()  # Newline after keypress

    if key is None:
        return False
    if key.lower() == "y":
        return True
    if key.lower() == "n":
        return False
    if key in ("\r", "\n", ""):
        return default

    return False
