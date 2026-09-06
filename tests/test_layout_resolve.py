"""Tests for hive_cli.layout.resolve.resolve_layout."""

from __future__ import annotations

from pathlib import Path

from hive_cli.layout.resolve import resolve_layout


def test_none_returns_none():
    assert resolve_layout(None) is None


def test_empty_string_returns_none():
    assert resolve_layout("") is None


def test_bundled_name_resolves_to_packaged_path():
    """The "agent" layout ships inside the package under layout/bundled/agent.kdl."""
    resolved = resolve_layout("agent")
    assert resolved is not None
    assert resolved.endswith("bundled/agent.kdl")
    assert Path(resolved).is_file()


def test_unknown_name_passed_through():
    """A name that isn't bundled and isn't a path is left for zellij to resolve."""
    assert resolve_layout("my-custom-layout") == "my-custom-layout"


def test_explicit_path_expanded(tmp_path):
    layout_file = tmp_path / "custom.kdl"
    layout_file.write_text("layout {}\n")
    assert resolve_layout(str(layout_file)) == str(layout_file)


def test_relative_path_with_slash_passed_through_expanded():
    assert resolve_layout("./layouts/custom.kdl") == str(
        Path("./layouts/custom.kdl").expanduser()
    )


def test_dot_kdl_suffix_treated_as_path():
    """Even without a "/", a ".kdl" suffix is treated as a path, not a name."""
    assert resolve_layout("custom.kdl") == str(Path("custom.kdl").expanduser())


def test_tilde_expansion():
    resolved = resolve_layout("~/layouts/custom.kdl")
    assert resolved == str(Path("~/layouts/custom.kdl").expanduser())
    assert not resolved.startswith("~")
