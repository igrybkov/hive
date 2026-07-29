"""Resolve a configured Zellij layout value to something `zellij --layout` accepts."""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path


def resolve_layout(value: str | None) -> str | None:
    """Resolve a configured layout to something zellij accepts.

    - None -> None (zellij built-in default)
    - contains "/" or ends with ".kdl" -> user-supplied path (expanduser)
    - matches a bundled layout name -> absolute path to the packaged .kdl
    - otherwise -> pass the bare name through (zellij resolves it against its
      own layout dir), preserving behavior for user-defined layouts
    """
    if not value:
        return None
    if "/" in value or value.endswith(".kdl"):
        return str(Path(value).expanduser())
    bundled = files("hive_cli").joinpath("layouts", f"{value}.kdl")
    if bundled.is_file():
        return str(bundled)  # uv/pipx install wheels unzipped: a real fs path
    return value
