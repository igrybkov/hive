"""Tests for hive_cli.state.pane_state.compose_title (pure title composition)."""

from __future__ import annotations

from pathlib import Path

from hive_cli.state.pane_state import compose_title


def _title(**overrides) -> str:
    kwargs = {
        "pane_id": None,
        "pane_label": None,
        "agent": None,
        "zellij_pane_id": "1",
        "status": None,
        "branch": None,
        "custom_title": None,
        "cwd": Path("/home/user"),
        "home": Path("/home/user"),
    }
    kwargs.update(overrides)
    return compose_title(**kwargs)


def test_in_layout_minimal():
    """With pane_id + pane_label, the base name is reconstructed."""
    assert (
        _title(pane_id="1", pane_label="Anton", agent="claude") == "c1: Anton [claude]"
    )


def test_in_layout_no_label():
    assert _title(pane_id="1", agent="claude") == "c1 [claude]"


def test_fallback_to_cwd_relative_to_home():
    cwd = Path("/home/user/my-project")
    home = Path("/home/user")
    assert _title(cwd=cwd, home=home) == "~/my-project"


def test_fallback_to_absolute_cwd_outside_home():
    cwd = Path("/tmp/my-project")
    home = Path("/home/user")
    assert _title(cwd=cwd, home=home) == str(cwd)


def test_no_layout_with_agent_uses_zellij_pane_id():
    assert _title(agent="claude", zellij_pane_id="99") == "claude-99"


def test_with_status():
    assert (
        _title(pane_id="1", pane_label="Anton", agent="claude", status="[working]")
        == "c1: Anton [claude] [working]"
    )


def test_with_branch():
    assert (
        _title(pane_id="1", pane_label="Anton", agent="claude", branch="feature-branch")
        == "c1: Anton [claude] [feature-branch]"
    )


def test_with_all_components():
    title = _title(
        pane_id="1",
        pane_label="Anton",
        agent="claude",
        status="[working]",
        branch="feature-branch",
        custom_title="Fixing bug",
    )
    assert title == "c1: Anton [claude] [working] [feature-branch] Fixing bug"
