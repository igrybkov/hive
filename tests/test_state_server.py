"""Tests for hive_cli.state.server (PaneStateServer) and hive_cli.state.client.

Every test talks to a real Unix socket served from the daemon thread; sockets
live under short_tmp so the path stays under macOS's 104-byte limit.
"""

from __future__ import annotations

import signal
import threading
import time

import pytest

from hive_cli.state import client
from hive_cli.state.pane_state import PaneState
from hive_cli.state.server import PaneStateServer


@pytest.fixture
def server(short_tmp):
    changes: list[PaneState] = []
    fired = threading.Event()

    def on_change(state):
        changes.append(state)
        fired.set()

    srv = PaneStateServer(
        short_tmp / "3.sock",
        PaneState(
            session="s", pane_id="3", hive_pane_id=1, label="Anton", agent="claude"
        ),
        on_change=on_change,
        coalesce_s=0.05,
    )
    srv.start()
    srv.test_changes, srv.test_fired = changes, fired
    yield srv
    srv.close()


def test_connect_receives_state(server):
    st = client.get_state(server.sock_path)
    assert (
        st["type"] == "state" and st["pane_id"] == "3" and st["status"] == "selecting"
    )
    assert st["label"] == "Anton" and st["version"] == 0


def test_socket_file_is_private(server):
    assert server.sock_path.stat().st_mode & 0o777 == 0o600


def test_ping_pong(server):
    assert client.send(server.sock_path, {"op": "ping"}) == {"type": "pong"}


def test_set_updates_and_bumps_version(server):
    assert client.set_fields(server.sock_path, status="busy")
    st = client.get_state(server.sock_path)
    assert st["status"] == "busy" and st["version"] == 1


def test_set_reply_carries_the_new_version(server):
    reply = client.send(server.sock_path, {"op": "set", "fields": {"branch": "feat"}})
    assert reply == {"type": "ok", "version": 1}


def test_set_rejects_unknown_field_and_bad_status(server):
    assert (
        client.send(server.sock_path, {"op": "set", "fields": {"nope": 1}})["type"]
        == "error"
    )
    assert (
        client.send(server.sock_path, {"op": "set", "fields": {"status": "flying"}})[
            "type"
        ]
        == "error"
    )
    assert server.state.status == "selecting" and server.state.version == 0


def test_set_rejects_server_owned_fields_and_non_object_fields(server):
    reply = client.send(server.sock_path, {"op": "set", "fields": {"version": 9}})
    assert reply == {"type": "error", "message": "unknown field: version"}
    reply = client.send(server.sock_path, {"op": "set", "fields": "status=busy"})
    assert reply["type"] == "error"
    reply = client.send(server.sock_path, {"op": "set", "fields": {"agent_pid": "x"}})
    assert reply["type"] == "error"
    assert server.state.version == 0


def test_set_is_atomic_across_fields(server):
    reply = client.send(
        server.sock_path,
        {"op": "set", "fields": {"branch": "feat", "status": "flying"}},
    )
    assert reply["type"] == "error"
    assert server.state.branch == "" and server.state.version == 0


def test_status_since_changes_only_on_status_change(server):
    t0 = server.state.status_since
    server.update(custom_title="x")
    assert server.state.status_since == t0
    server.update(status="busy")
    assert server.state.status_since > t0
    t1 = server.state.status_since
    server.update(status="busy")
    assert server.state.status_since == t1


def test_update_rejects_unknown_field_and_bad_status(server):
    with pytest.raises(ValueError, match="unknown field: nope"):
        server.update(nope=1)
    with pytest.raises(ValueError, match="invalid status: flying"):
        server.update(status="flying")
    assert server.state.version == 0


def test_state_property_is_a_copy(server):
    copy = server.state
    copy.status = "busy"
    assert server.state.status == "selecting"


def test_subscribe_receives_pushes(server):
    events = client.subscribe(server.sock_path, timeout=2.0)
    assert next(events)["status"] == "selecting"
    server.update(status="busy")
    assert next(events)["status"] == "busy"
    server.update(custom_title="t")
    pushed = next(events)
    assert pushed["custom_title"] == "t" and pushed["version"] == 2
    events.close()


def test_subscribe_raises_timeout_error_on_silence(server):
    events = client.subscribe(server.sock_path, timeout=0.2)
    next(events)
    with pytest.raises(TimeoutError):
        next(events)


def test_restart_sets_event_and_signals_agent(server, monkeypatch):
    kills = []
    monkeypatch.setattr(
        "hive_cli.state.server.os.kill", lambda pid, sig: kills.append((pid, sig))
    )
    server.update(agent_pid=4242)
    assert client.request(server.sock_path, "restart")
    assert server.restart_requested.is_set()
    assert kills == [(4242, signal.SIGTERM)]


def test_stop_sets_event_and_skips_kill_without_agent(server, monkeypatch):
    kills = []
    monkeypatch.setattr(
        "hive_cli.state.server.os.kill", lambda pid, sig: kills.append((pid, sig))
    )
    assert client.request(server.sock_path, "stop")
    assert server.stop_requested.is_set()
    assert not server.restart_requested.is_set()
    assert kills == []


def test_request_tolerates_vanished_agent(server, monkeypatch):
    def gone(pid, sig):
        raise ProcessLookupError

    monkeypatch.setattr("hive_cli.state.server.os.kill", gone)
    server.update(agent_pid=4242)
    assert client.request(server.sock_path, "restart")


def test_on_change_is_coalesced(server):
    for i in range(5):
        server.update(custom_title=f"t{i}")
    assert server.test_fired.wait(1.0)
    time.sleep(0.15)  # allowed: negative assertion that no second fire happens
    assert [s.custom_title for s in server.test_changes] == ["t4"]


def test_close_flushes_pending_change_once(short_tmp):
    changes: list[str] = []
    srv = PaneStateServer(
        short_tmp / "8.sock",
        PaneState(pane_id="8"),
        on_change=lambda s: changes.append(s.custom_title),
        coalesce_s=5.0,
    )
    srv.start()
    srv.update(custom_title="last")
    srv.close()
    srv.close()  # idempotent
    assert changes == ["last"]
    assert not (short_tmp / "8.sock").exists()


def test_stale_socket_file_is_replaced(short_tmp):
    path = short_tmp / "9.sock"
    path.write_text("stale")
    with PaneStateServer(path, PaneState(pane_id="9")) as srv:
        assert client.get_state(srv.sock_path)["pane_id"] == "9"
    assert not path.exists()


def test_unknown_op_and_bad_json(server):
    assert client.send(server.sock_path, {"op": "bogus"}) == {
        "type": "error",
        "message": "unknown op: bogus",
    }
    assert client.get_state(server.sock_path)["pane_id"] == "3"  # server still alive


def test_bad_json_line_gets_error_and_connection_survives(server):
    import socket

    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.settimeout(1.0)
        s.connect(str(server.sock_path))
        rf = s.makefile("rb")
        rf.readline()  # greeting
        s.sendall(b"not json\n")
        assert b'"bad json"' in rf.readline()
        s.sendall(b'{"op":"ping"}\n')
        assert rf.readline() == b'{"type":"pong"}\n'


def test_get_state_when_nobody_listens(short_tmp):
    assert client.get_state(short_tmp / "none.sock") is None
    assert client.send(short_tmp / "none.sock", {"op": "ping"}) is None
    assert client.set_fields(short_tmp / "none.sock", status="busy") is False
    assert client.request(short_tmp / "none.sock", "stop") is False


def test_get_state_unlinks_dead_socket(short_tmp):
    with PaneStateServer(short_tmp / "7.sock", PaneState(pane_id="7")):
        pass  # closed: the file is gone already
    dead = short_tmp / "7.sock"
    dead.write_text("")
    assert client.get_state(dead) is None
    assert not dead.exists()


def test_list_pane_sockets_skips_control_and_dead(short_tmp):
    (short_tmp / "control.sock").write_text("")
    (short_tmp / "dead.sock").write_text("")
    with PaneStateServer(short_tmp / "1.sock", PaneState(pane_id="1")):
        assert [p.name for p in client.list_pane_sockets(short_tmp)] == ["1.sock"]
    assert not (short_tmp / "dead.sock").exists()
    assert (short_tmp / "control.sock").exists()


def test_list_states_returns_pane_states_sorted_by_socket_name(short_tmp):
    with (
        PaneStateServer(short_tmp / "2.sock", PaneState(pane_id="2", hive_pane_id=5)),
        PaneStateServer(short_tmp / "1.sock", PaneState(pane_id="1", hive_pane_id=4)),
    ):
        states = client.list_states(short_tmp)
    assert [(s.pane_id, s.hive_pane_id) for s in states] == [("1", 4), ("2", 5)]
    assert all(isinstance(s, PaneState) for s in states)


def test_list_states_on_missing_dir_is_empty(short_tmp):
    assert client.list_states(short_tmp / "nope") == []
    assert client.list_pane_sockets(short_tmp / "nope") == []
