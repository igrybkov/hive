"""Tests for hive_cli.layout.resolve.resolve_layout."""

from __future__ import annotations

from pathlib import Path

from hive_cli.config.schema import ZellijConfig
from hive_cli.config.settings import HiveSettings
from hive_cli.core.paths import layouts_dir
from hive_cli.layout.resolve import resolve_layout, write_session_files
from hive_cli.layout.tabs import session_spec


def _fake_render(spec, hive) -> str:
    return f"layout {{ /* {spec.name} via {hive} */ }}\n"


def _settings() -> HiveSettings:
    return HiveSettings(zellij=ZellijConfig())


def _resolve(value, **kwargs):
    kwargs.setdefault("session", "s")
    kwargs.setdefault("hive", "/opt/hive")
    kwargs.setdefault("settings", _settings())
    kwargs.setdefault("render", _fake_render)
    return resolve_layout(value, **kwargs)


def test_none_returns_none():
    assert _resolve(None) is None


def test_empty_string_returns_none():
    assert _resolve("") is None


def test_agent_renders_and_writes_session_file():
    resolved = _resolve("agent", session="my-session")
    assert resolved == str(layouts_dir() / "my-session" / "session.kdl")
    assert Path(resolved).read_text() == "layout { /* my-session via /opt/hive */ }\n"


def test_agent_overwrites_on_repeat_calls():
    _resolve("agent", session="s")
    path = Path(layouts_dir() / "s" / "session.kdl")
    path.write_text("stale")
    _resolve("agent", session="s")
    assert path.read_text() != "stale"


def test_bundled_name_resolves_to_packaged_path():
    """ "agent-16" ships inside the package under layout/bundled/agent-16.kdl."""
    resolved = _resolve("agent-16")
    assert resolved is not None
    assert resolved.endswith("bundled/agent-16.kdl")
    assert Path(resolved).is_file()


def test_agent_16_byte_identical_to_fixture():
    resolved = _resolve("agent-16")
    fixture = Path(__file__).parent / "fixtures" / "agent-16.kdl"
    assert Path(resolved).read_bytes() == fixture.read_bytes()


def test_unknown_name_passed_through():
    """A name that isn't bundled and isn't a path is left for zellij to resolve."""
    assert _resolve("my-custom-layout") == "my-custom-layout"


def test_explicit_path_expanded(tmp_path):
    layout_file = tmp_path / "custom.kdl"
    layout_file.write_text("layout {}\n")
    assert _resolve(str(layout_file)) == str(layout_file)


def test_relative_path_with_slash_passed_through_expanded():
    assert _resolve("./layouts/custom.kdl") == str(
        Path("./layouts/custom.kdl").expanduser()
    )


def test_dot_kdl_suffix_treated_as_path():
    """Even without a "/", a ".kdl" suffix is treated as a path, not a name."""
    assert _resolve("custom.kdl") == str(Path("custom.kdl").expanduser())


def test_tilde_expansion():
    resolved = _resolve("~/layouts/custom.kdl")
    assert resolved == str(Path("~/layouts/custom.kdl").expanduser())
    assert not resolved.startswith("~")


def test_write_session_files_overwrites():
    spec = session_spec(name="s2", hive="/opt/hive", settings=_settings())
    path = write_session_files(spec, "one")
    assert path.read_text() == "one"
    write_session_files(spec, "two")
    assert path.read_text() == "two"
