"""Tests for hive_cli.layout.model: frozen, hashable layout dataclasses."""

from __future__ import annotations

from hive_cli.layout.model import KeybindSpec, PaneSpec, SessionSpec, TabSpec


def test_pane_spec_frozen_and_hashable():
    pane = PaneSpec(name="c1", command=("hive", "run"))
    assert hash(pane) == hash(PaneSpec(name="c1", command=("hive", "run")))


def test_tab_spec_frozen_and_hashable():
    tab = TabSpec(name="agents", panes=(PaneSpec(name="c1", command=()),))
    assert hash(tab) == hash(tab)


def test_keybind_spec_default_empty_and_hashable():
    kb = KeybindSpec()
    assert kb.bindings == ()
    assert hash(kb) == hash(KeybindSpec())


def test_session_spec_frozen_and_hashable_with_defaults():
    session = SessionSpec(name="s", tabs=())
    assert session.options == (
        ("stacked_resize", "false"),
        ("auto_layout", "true"),
    )
    assert session.keybinds == KeybindSpec()
    assert hash(session) == hash(SessionSpec(name="s", tabs=()))
