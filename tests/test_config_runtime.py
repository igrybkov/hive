"""Tests for hive_cli.config.runtime: pane identity fields and the child env.

HIVE_PANE_LABEL/HIVE_PANE_SOCK became mutable, exported fields in F0 so a
`hive run` that self-assigns its pane number (started on demand) hands the
identity and its socket path to the agent child and to nested hive calls.
"""

from __future__ import annotations

from hive_cli.config import get_runtime_settings
from hive_cli.config.runtime import RuntimeSettings
from hive_cli.core import paths


def test_pane_label_from_env(monkeypatch):
    monkeypatch.setenv("HIVE_PANE_LABEL", "Anton")
    rt = RuntimeSettings()
    assert rt.pane_label == "Anton"
    rt.pane_label = "Bohdan"
    assert rt.build_child_env()["HIVE_PANE_LABEL"] == "Bohdan"


def test_pane_label_absent_is_none_and_not_exported():
    rt = RuntimeSettings()
    assert rt.pane_label is None
    assert "HIVE_PANE_LABEL" not in rt.build_child_env()


def test_pane_sock_from_env_or_derived(monkeypatch):
    monkeypatch.setenv("ZELLIJ_SESSION_NAME", "s")
    monkeypatch.setenv("ZELLIJ_PANE_ID", "3")
    monkeypatch.setenv("HIVE_PANE_SOCK", "/x/1.sock")
    assert RuntimeSettings().pane_sock == "/x/1.sock"  # explicit wins

    monkeypatch.delenv("HIVE_PANE_SOCK")
    assert RuntimeSettings().pane_sock == str(paths.pane_sock("s", "3"))

    monkeypatch.delenv("ZELLIJ_SESSION_NAME")
    assert RuntimeSettings().pane_sock is None  # needs both zellij vars
    monkeypatch.delenv("ZELLIJ_PANE_ID")
    assert RuntimeSettings().pane_sock is None


def test_pane_sock_is_not_derived_from_the_field_defaults():
    """ZELLIJ_SESSION_NAME/ZELLIJ_PANE_ID have defaults ("default"/"0"); their
    mere absence must not produce a default/0.sock path."""
    rt = RuntimeSettings()
    assert rt.zellij_session_name == "default" and rt.zellij_pane_id == "0"
    assert rt.pane_sock is None


def test_build_child_env_exports_pane_vars():
    rt = get_runtime_settings()
    rt.pane_id = "3"
    rt.pane_label = "Chris"
    rt.pane_sock = "/r/3.sock"
    env = rt.build_child_env()
    assert env["HIVE_PANE_ID"] == "3"
    assert env["HIVE_PANE_LABEL"] == "Chris"
    assert env["HIVE_PANE_SOCK"] == "/r/3.sock"


def test_build_child_env_drops_stale_pane_vars(monkeypatch):
    monkeypatch.setenv("HIVE_PANE_SOCK", "/stale.sock")
    monkeypatch.setenv("HIVE_PANE_LABEL", "Stale")
    rt = RuntimeSettings()
    rt.pane_sock = None
    rt.pane_label = None
    env = rt.build_child_env()
    assert "HIVE_PANE_SOCK" not in env and "HIVE_PANE_LABEL" not in env
