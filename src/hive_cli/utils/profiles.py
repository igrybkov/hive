"""Profile selection utilities for per-agent config-dir profiles."""

from __future__ import annotations

from pathlib import Path

from rich.console import Console

from ..config import get_agent_config, get_profiles_root
from .fuzzy import FuzzyItem, fuzzy_select

# Sentinel value returned from select_profile when user creates a new profile
NEW_PROFILE_ITEM_VALUE = "__new_profile__"
# Display label for the "create new" entry
NEW_PROFILE_DISPLAY = "＋ new profile…"
# Display label for the default (passthrough) option
DEFAULT_PROFILE_DISPLAY = "<default>"
DEFAULT_PROFILE_VALUE = ""

stderr_console = Console(stderr=True)


def _seed_profile_dir(profile_dir: Path, seed_files: dict[str, str]) -> None:
    """Write seed files into a freshly created profile directory.

    Each file is only written if it does not already exist, so re-entering a
    profile creation flow never clobbers user edits.

    Args:
        profile_dir: Path to the profile directory (must already exist).
        seed_files: Mapping of filename → file contents.
    """
    for filename, contents in seed_files.items():
        target = profile_dir / filename
        if not target.exists():
            target.write_text(contents)


def create_profile(agent_name: str, profile_name: str) -> Path:
    """Create a new profile directory and write seed files.

    Args:
        agent_name: Name of the agent (e.g. ``"claude"``).
        profile_name: Name of the new profile.

    Returns:
        Path to the created profile directory.
    """
    profile_dir = get_profiles_root() / agent_name / profile_name
    profile_dir.mkdir(parents=True, exist_ok=True)

    cfg = get_agent_config(agent_name)
    if cfg.profile and cfg.profile.seed_files:
        _seed_profile_dir(profile_dir, cfg.profile.seed_files)

    return profile_dir


def list_profiles(agent_name: str) -> list[str]:
    """Return existing profile names for an agent (alphabetically sorted).

    Args:
        agent_name: Name of the agent.

    Returns:
        Sorted list of profile names (directory names under the profiles root).
    """
    root = get_profiles_root() / agent_name
    if not root.exists():
        return []
    return sorted(d.name for d in root.iterdir() if d.is_dir())


def select_profile(
    agent_name: str,
    current_profile: str | None = None,
) -> str | None:
    """Show an interactive picker to select an agent config profile.

    Returns the selected profile name (a non-empty string), an empty string
    ``""`` to signify ``<default>`` (passthrough — no config-dir override), or
    ``None`` if the user cancelled.

    If the agent does not declare ``profile.config_dir_env`` in its config, a
    warning is printed and ``None`` is returned immediately (mirrors the
    ``extra_dirs`` warn in wt.py).

    The picker lists:
    - ``<default>`` at the top (value ``""``).
    - Existing profile directories under ``$XDG_CONFIG_HOME/hive/profiles/<agent>/``.
    - A ``＋ new profile…`` entry that prompts for a name, creates the directory,
      and writes seed files.

    Args:
        agent_name: Name of the agent whose profiles to list.
        current_profile: Currently active profile name (highlighted if present).

    Returns:
        Profile name string (empty string = default), or None if cancelled.
    """
    cfg = get_agent_config(agent_name)
    if cfg.profile is None or not cfg.profile.config_dir_env:
        stderr_console.print(
            f"[yellow]Agent [bold]{agent_name}[/bold] does not support config profiles "
            f"(no config_dir_env configured).[/yellow]"
        )
        return None

    existing = list_profiles(agent_name)

    items: list[FuzzyItem] = []

    # <default> always at top
    items.append(
        FuzzyItem(
            text=DEFAULT_PROFILE_DISPLAY,
            value=DEFAULT_PROFILE_VALUE,
            meta="← current" if not current_profile else "",
            style="green" if not current_profile else "dim",
        )
    )

    # Existing profiles
    for name in existing:
        is_current = name == current_profile
        items.append(
            FuzzyItem(
                text=name,
                value=name,
                meta="← current" if is_current else "",
                style="green" if is_current else "",
            )
        )

    # "＋ new profile…" always at bottom
    items.append(
        FuzzyItem(
            text=NEW_PROFILE_DISPLAY,
            value=NEW_PROFILE_ITEM_VALUE,
            meta="",
            style="cyan",
        )
    )

    selected = fuzzy_select(
        items=items,
        prompt_text=">",
        header=f"Select profile for <b>{agent_name}</b>",
        hint="</dim><b>Enter</b><dim> select  </dim><b>Esc</b><dim> back",
    )

    if selected is None:
        return None

    # "＋ new profile…" selected → prompt for name and create
    if selected == NEW_PROFILE_ITEM_VALUE:
        return _prompt_new_profile(agent_name)

    return selected  # "" for default, or profile name


def _prompt_new_profile(agent_name: str) -> str | None:
    """Prompt the user for a new profile name, create it, and return the name.

    Args:
        agent_name: Name of the agent.

    Returns:
        New profile name if created, or None if cancelled/invalid.
    """
    stderr_console.print()
    stderr_console.print(f"[bold]Create new profile for {agent_name}[/bold]")
    stderr_console.print(
        "[dim]Profile name (letters, numbers, hyphens, underscores)[/dim]"
    )
    stderr_console.print("[dim]Press Enter with empty name to cancel.[/dim]")
    stderr_console.print()

    try:
        name = input("Profile name: ").strip()
    except (EOFError, KeyboardInterrupt):
        return None

    if not name:
        return None

    # Basic validation: allow alphanumeric, hyphens, underscores
    import re

    if not re.match(r"^[a-zA-Z0-9_-]+$", name):
        stderr_console.print(
            "[red]Invalid profile name. Use only letters, numbers, hyphens, "
            "and underscores.[/red]"
        )
        return None

    # Check for collision with reserved values
    if name == DEFAULT_PROFILE_DISPLAY or name == NEW_PROFILE_DISPLAY:
        stderr_console.print(
            "[red]That name is reserved. Choose a different name.[/red]"
        )
        return None

    profile_dir = create_profile(agent_name, name)
    stderr_console.print(
        f"[green]Created profile [bold]{name}[/bold] at {profile_dir}[/green]"
    )
    return name
