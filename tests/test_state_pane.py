"""Tests for hive_cli.state.pane_state: PaneState, title/tab-name composition.

The title-format assertions were moved from tests/test_zellij.py in A0
(as test_state_title.py) and now call compose_title with the F0 keyword
names (hive_pane_id/label/mux_pane_id/status_text).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hive_cli.state.pane_state import (
    ICONS,
    STATUSES,
    PaneState,
    compose_tab_name,
    compose_title,
    label_for,
    next_free_pane_id,
    pane_hive_id,
    title_for,
)


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("c2: Bohdan", 2),
        ("c2: Bohdan [claude]", 2),
        ("c12", 12),
        ("hold: c2: Bohdan", 2),  # tmux's suspended-pane title (commands/pane.py:hold)
        ("hold: c2", 2),
        ("hold: hive run --restart", None),  # a hold pane with no HIVE_PANE_ID env
        ("hive", None),
        ("", None),
    ],
)
def test_pane_hive_id_parses_zellij_and_tmux_titles(title, expected):
    assert pane_hive_id(title) == expected


def _title(**overrides) -> str:
    kwargs = {
        "hive_pane_id": 0,
        "label": "",
        "agent": "",
        "mux_pane_id": "1",
        "status_text": "",
        "branch": "",
        "custom_title": "",
        "cwd": Path("/tmp/x"),
    }
    kwargs.update(overrides)
    return compose_title(**kwargs)


# ---------------------------------------------------------------------------
# compose_title
# ---------------------------------------------------------------------------


def test_compose_title_in_layout():
    assert (
        _title(
            hive_pane_id=1,
            label="Anton",
            agent="claude",
            mux_pane_id="7",
            status_text="[working]",
            branch="feat",
            custom_title="note",
        )
        == "c1: Anton [claude] [working] [feat] note"
    )


def test_compose_title_in_layout_minimal():
    assert _title(hive_pane_id=1, label="Anton", agent="claude") == "c1: Anton [claude]"


def test_compose_title_no_label():
    assert _title(hive_pane_id=2, agent="claude") == "c2 [claude]"


def test_compose_title_outside_layout():
    assert (
        _title(hive_pane_id=0, agent="claude", mux_pane_id="7", status_text="[working]")
        == "claude-7 [working]"
    )


def test_compose_title_cwd_fallback():
    assert _title(cwd=Path.home() / "proj") == "~/proj"
    assert _title(cwd=Path("/tmp/x")) == "/tmp/x"


def test_compose_title_cwd_defaults_to_process_cwd(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    assert _title(cwd=None) == str(Path.cwd())


def test_compose_title_with_branch_only():
    assert (
        _title(hive_pane_id=1, label="Anton", agent="claude", branch="feature-branch")
        == "c1: Anton [claude] [feature-branch]"
    )


# ---------------------------------------------------------------------------
# PaneState / title_for
# ---------------------------------------------------------------------------


def test_title_for_uses_state_fields():
    state = PaneState(
        pane_id="7",
        hive_pane_id=1,
        label="Anton",
        agent="claude",
        status_text="[working]",
        branch="feat",
        custom_title="note",
    )
    assert title_for(state) == "c1: Anton [claude] [working] [feat] note"


def test_to_dict_from_dict_roundtrip():
    state = PaneState(
        session="s", pane_id="3", hive_pane_id=2, status="busy", version=4
    )
    assert PaneState.from_dict(state.to_dict()) == state


def test_from_dict_ignores_unknown_keys():
    state = PaneState.from_dict({"type": "state", "pane_id": "3", "nope": 1})
    assert state.pane_id == "3"
    assert not hasattr(state, "nope")


def test_default_status_is_selecting_and_every_status_has_an_icon():
    assert PaneState().status == "selecting"
    assert set(STATUSES) == set(ICONS)


# ---------------------------------------------------------------------------
# compose_tab_name
# ---------------------------------------------------------------------------


def test_compose_tab_name():
    states = [
        PaneState(hive_pane_id=2, label="Bohdan", status="selecting"),
        PaneState(hive_pane_id=1, branch="feature-authentication", status="busy"),
    ]
    assert compose_tab_name(states) == "feature-auth ✳ · Bohdan …"
    assert compose_tab_name([]) == "hive"


def test_compose_tab_name_falls_back_to_pane_number_and_orders_unknown_last():
    states = [
        PaneState(hive_pane_id=0, pane_id="9", status="running"),
        PaneState(hive_pane_id=3, status="exited"),
    ]
    assert compose_tab_name(states) == "c3 ✖ · c0 ✳"


# ---------------------------------------------------------------------------
# identity helpers
# ---------------------------------------------------------------------------


def test_next_free_pane_id():
    assert next_free_pane_id([]) == 1
    assert next_free_pane_id([1, 2, 4]) == 3


def test_label_for():
    labels = ["Anton", "Bohdan"]
    assert label_for(1, labels) == "Anton"
    assert label_for(2, labels) == "Bohdan"
    assert label_for(3, labels) == ""
    assert label_for(0, labels) == ""
