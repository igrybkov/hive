"""hive_cli.state.session_layout: the session's live agents_layout override
(G2). XDG_RUNTIME_DIR is already isolated per test by the autouse
`clean_environment` fixture (conftest.py)."""

from __future__ import annotations

import pytest

from hive_cli.core import paths
from hive_cli.state.session_layout import read_agents_layout, write_agents_layout


def test_read_default_when_unset():
    assert read_agents_layout("s", default="split") == "split"


def test_write_then_read_roundtrips():
    write_agents_layout("s", "stacked")
    assert read_agents_layout("s", default="split") == "stacked"


def test_unrecognized_value_falls_back_to_default():
    path = paths.agents_layout_file("s")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("bogus")
    assert read_agents_layout("s", default="split") == "split"


def test_write_rejects_unknown_mode():
    with pytest.raises(ValueError):
        write_agents_layout("s", "bogus")


def test_different_sessions_are_isolated():
    write_agents_layout("s1", "tabs")
    assert read_agents_layout("s2", default="split") == "split"
    assert read_agents_layout("s1", default="split") == "tabs"
