"""Tests for hive_cli.mux.tmux.control: control-mode line parsing.

Fixture: tests/fixtures/tmux_control.txt is a real transcript recorded on
this machine (tmux 3.7c) against a throwaway private server (`-L
hive-ctrl-fixture`, killed immediately after) -- safe from this sandbox's
Bash tool despite it running inside a live Zellij session, since a private
tmux server never touches that session. Recorded by piping a short-lived
`sleep` into `tmux -C attach-session` (keeps stdin open so the control
client doesn't detach on EOF) while a second shell drove `new-window` /
`rename-window` / `kill-window` / `kill-server` against the same server.
Closing the only window this way produced `%unlinked-window-close`, not
`%window-close` -- tmux's distinction for whether the window was linked
into another session, which a hive-bootstrapped session never is -- so
`LAYOUT_EVENTS` includes both spellings.
"""

from __future__ import annotations

from pathlib import Path

from hive_cli.mux.tmux.control import LAYOUT_EVENTS, ControlEvent, parse_line

FIXTURE = Path(__file__).parent / "fixtures" / "tmux_control.txt"


def test_parse_line_non_percent_returns_none():
    assert parse_line("hello world") is None
    assert parse_line("") is None


def test_parse_line_window_add():
    assert parse_line("%window-add @3") == ControlEvent("window-add", ("@3",))


def test_parse_line_no_args():
    assert parse_line("%exit") == ControlEvent("exit", ())


def test_parse_line_strips_trailing_newline():
    assert parse_line("%exit\n") == ControlEvent("exit", ())


def test_layout_events_membership():
    for kind in (
        "window-add",
        "window-close",
        "unlinked-window-close",
        "window-renamed",
        "layout-change",
        "session-changed",
    ):
        assert kind in LAYOUT_EVENTS
    assert "output" not in LAYOUT_EVENTS
    assert "begin" not in LAYOUT_EVENTS


def test_fixture_covers_every_documented_event_kind():
    lines = FIXTURE.read_text().splitlines()
    events = [e for line in lines if (e := parse_line(line)) is not None]
    kinds = {e.kind for e in events}
    for expected in (
        "begin",
        "end",
        "window-add",
        "layout-change",
        "session-changed",
        "unlinked-window-close",
    ):
        assert expected in kinds, f"fixture missing %{expected}"
    assert any(e.kind == "output" for e in events)
    assert any(e.kind == "exit" for e in events)


def test_fixture_parses_without_error():
    lines = FIXTURE.read_text().splitlines()
    for line in lines:
        parse_line(line)  # must never raise
