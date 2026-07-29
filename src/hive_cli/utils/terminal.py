"""Terminal output utilities using Rich."""

from __future__ import annotations

from rich.console import Console

# Create console for stderr output (public so other modules can use it)
console = Console(stderr=True, highlight=False)


def print_stderr(msg: str) -> None:
    """Print message to stderr with Rich markup support."""
    console.print(msg)


def info(msg: str) -> None:
    """Print info message in blue."""
    console.print(msg, style="blue")


def success(msg: str) -> None:
    """Print success message in green."""
    console.print(msg, style="green")


def warn(msg: str) -> None:
    """Print warning message in yellow."""
    console.print(msg, style="yellow")


def error(msg: str) -> None:
    """Print error message in red."""
    console.print(msg, style="bold red")


def prompt(msg: str) -> None:
    """Print prompt message in cyan+bold (no newline)."""
    console.print(msg, style="bold cyan", end="", markup=False)
    console.file.flush()


def dim(msg: str) -> None:
    """Print dim message."""
    console.print(msg, style="dim")


def format_green(text: str) -> str:
    """Format text in green (for embedding in other output)."""
    return f"[green]{text}[/green]"


def format_yellow(text: str) -> str:
    """Format text in yellow (for embedding in other output)."""
    return f"[yellow]{text}[/yellow]"


def format_dim(text: str) -> str:
    """Format text in dim (for embedding in other output)."""
    return f"[dim]{text}[/dim]"
