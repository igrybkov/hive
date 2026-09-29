"""ControlServer (F4): the control-plane socket, plus summaries_via_control."""

from __future__ import annotations

from pathlib import Path

import pytest

from hive_cli.core.errors import HiveError
from hive_cli.git import GitSummary
from hive_cli.services import registry
from hive_cli.services.facts import ControlServer, summaries_via_control
from hive_cli.state import client


def _summary(**over) -> GitSummary:
    fields = dict(
        branch="feat",
        upstream="origin/feat",
        ahead=1,
        behind=0,
        staged=0,
        modified=0,
        untracked=0,
        conflicted=0,
        last_hash="abc123",
        last_subject="msg",
        last_age="1 hour ago",
    )
    fields.update(over)
    return GitSummary(**fields)


@pytest.fixture
def facts_provider():
    box = {"value": {}}

    def provider():
        return box["value"]

    provider.box = box
    return provider


@pytest.fixture
def control(short_tmp, facts_provider):
    srv = ControlServer(short_tmp / "control.sock", pane_id="3", facts=facts_provider)
    srv.start()
    yield srv
    srv.close()


class TestGreeting:
    def test_kind_is_control(self, control):
        state = client.get_state(control.sock_path)
        assert state["type"] == "state"
        assert state["kind"] == "control"
        assert state["pane_id"] == "3"
        assert isinstance(state["hive_pid"], int)

    def test_get_op_repeats_greeting(self, control):
        reply = client.send(control.sock_path, {"op": "get"})
        assert reply["kind"] == "control"


class TestPing:
    def test_pong(self, control):
        assert client.send(control.sock_path, {"op": "ping"}) == {"type": "pong"}


class TestFacts:
    def test_returns_provider_dict_jsonencoded(self, control, facts_provider):
        facts_provider.box["value"] = {"/wt/feat": _summary()}
        reply = client.send(control.sock_path, {"op": "facts"})
        assert reply["type"] == "facts"
        assert reply["facts"]["/wt/feat"]["branch"] == "feat"
        assert reply["facts"]["/wt/feat"]["ahead"] == 1

    def test_empty_when_no_facts_yet(self, control):
        reply = client.send(control.sock_path, {"op": "facts"})
        assert reply == {"type": "facts", "facts": {}}


class TestCall:
    def test_dispatches_registered_op(self, control):
        registry.OPS["test.echo"] = lambda **kw: kw

        reply = client.send(
            control.sock_path, {"op": "call", "name": "test.echo", "args": {"x": 1}}
        )

        assert reply == {"type": "result", "value": {"x": 1}}

    def test_unknown_name_is_error(self, control):
        reply = client.send(
            control.sock_path, {"op": "call", "name": "nope.op", "args": {}}
        )
        assert reply["type"] == "error"


class TestUnknownOp:
    def test_unknown_op_is_error(self, control):
        reply = client.send(control.sock_path, {"op": "bogus"})
        assert reply == {"type": "error", "message": "unknown op: bogus"}


class TestSummariesViaControl:
    def test_round_trips_a_git_summary(self, control, facts_provider, monkeypatch):
        facts_provider.box["value"] = {"/wt/feat": _summary(staged=2)}
        monkeypatch.setattr(
            "hive_cli.services.facts.paths.control_sock",
            lambda session: control.sock_path,
        )

        result = summaries_via_control("any-session")

        assert result == {Path("/wt/feat"): _summary(staged=2)}

    def test_none_with_no_server(self, short_tmp, monkeypatch):
        monkeypatch.setattr(
            "hive_cli.services.facts.paths.control_sock",
            lambda session: short_tmp / "nope.sock",
        )
        assert summaries_via_control("any-session") is None


def test_call_op_surfaces_hive_error_message(control):
    @registry.op("test.boom")
    def _boom(**_kw):
        raise HiveError("kaboom")

    reply = client.send(
        control.sock_path, {"op": "call", "name": "test.boom", "args": {}}
    )
    assert reply == {"type": "error", "message": "kaboom"}
