"""Resolve a configured Zellij layout value to something `zellij --layout` accepts.

"agent" is the only value that renders: everything else is a static file
lookup or passthrough. Rendering the session KDL is a backend concern (see
mux/zellij/kdl.py), so it is injected as `render` rather than imported here
— layout/ (layer 2) may not import mux/ (also layer 2; only the reverse,
mux -> layout's model, is on the architecture guard's sideways allow-list).
`services/session.py` is what actually supplies the zellij renderer.
"""

from __future__ import annotations

from collections.abc import Callable
from importlib.resources import files
from pathlib import Path

from ..config.settings import HiveSettings
from ..core.paths import layouts_dir
from .model import SessionSpec
from .tabs import session_spec


def write_session_files(spec: SessionSpec, content: str) -> Path:
    """Write pre-rendered KDL text as session.kdl into layouts_dir()/<spec.name>/.

    Overwrites on every call — the session file is rewritten on every
    `hive zellij` start.
    """
    path = layouts_dir() / spec.name / "session.kdl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def resolve_layout(
    value: str | None,
    *,
    session: str,
    hive: str,
    settings: HiveSettings,
    render: Callable[[SessionSpec, str], str],
) -> str | None:
    """Resolve a configured layout to something zellij accepts.

    - None / "" -> None (zellij built-in default)
    - "agent" -> render session_spec() and write it to
      layouts_dir()/<session>/session.kdl, returning that path
    - contains "/" or ends with ".kdl" -> user-supplied path (expanduser)
    - matches a bundled layout name (e.g. "agent-16") -> its packaged path
    - otherwise -> pass the bare name through (zellij resolves it against
      its own layout dir), preserving behavior for user-defined layouts
    """
    if not value:
        return None
    if value == "agent":
        spec = session_spec(name=session, hive=hive, settings=settings)
        content = render(spec, hive)
        return str(write_session_files(spec, content))
    if "/" in value or value.endswith(".kdl"):
        return str(Path(value).expanduser())
    bundled = files("hive_cli.layout").joinpath("bundled", f"{value}.kdl")
    if bundled.is_file():
        return str(bundled)  # uv/pipx install wheels unzipped: a real fs path
    return value
