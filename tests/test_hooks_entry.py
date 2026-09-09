"""Tests for hive_cli.hooks.entry: the `hive-hook` executable.

Uses a real PaneStateServer on a Unix socket (short_tmp keeps the path under
the macOS AF_UNIX length limit) rather than mocking hive_cli.state.client, so
these tests exercise the actual wire protocol `hive-hook` depends on.
"""

from __future__ import annotations

import io

from hive_cli.hooks.entry import main, read_payload
from hive_cli.state import client
from hive_cli.state.pane_state import PaneState
from hive_cli.state.server import PaneStateServer


def _server(sock_path):
    server = PaneStateServer(sock_path, PaneState())
    server.start()
    return server


class TestReadPayload:
    def test_codex_argv_payload(self):
        assert read_payload(
            ["hive-hook", "codex", '{"type":"agent-turn-complete"}']
        ) == {"type": "agent-turn-complete"}

    def test_bad_json_returns_empty(self):
        assert read_payload(["hive-hook", "claude", "not json"]) == {}

    def test_non_object_json_returns_empty(self):
        assert read_payload(["hive-hook", "claude", "[1,2,3]"]) == {}

    def test_empty_argv_returns_empty(self, monkeypatch):
        monkeypatch.setattr("sys.stdin", io.StringIO(""))
        assert read_payload(["hive-hook", "claude"]) == {}


class TestMain:
    def test_claude_stdin_sets_status(self, short_tmp, monkeypatch):
        sock = short_tmp / "p.sock"
        server = _server(sock)
        monkeypatch.setenv("HIVE_PANE_SOCK", str(sock))
        monkeypatch.setattr(
            "sys.stdin", io.StringIO('{"hook_event_name":"UserPromptSubmit"}')
        )
        try:
            assert main(["hive-hook", "claude"]) == 0
            assert client.get_state(sock)["status"] == "busy"
        finally:
            server.close()

    def test_codex_argv_payload_sets_status(self, short_tmp, monkeypatch):
        sock = short_tmp / "p.sock"
        server = _server(sock)
        monkeypatch.setenv("HIVE_PANE_SOCK", str(sock))
        try:
            assert main(["hive-hook", "codex", '{"type":"agent-turn-complete"}']) == 0
            assert client.get_state(sock)["status"] == "done"
        finally:
            server.close()

    def test_unknown_event_no_change(self, short_tmp, monkeypatch):
        sock = short_tmp / "p.sock"
        server = _server(sock)
        monkeypatch.setenv("HIVE_PANE_SOCK", str(sock))
        monkeypatch.setattr(
            "sys.stdin", io.StringIO('{"hook_event_name":"SomeFutureEvent"}')
        )
        try:
            assert main(["hive-hook", "claude"]) == 0
            assert client.get_state(sock)["status"] == "selecting"
        finally:
            server.close()

    def test_no_socket_env_returns_0_without_connecting(self, monkeypatch):
        monkeypatch.delenv("HIVE_PANE_SOCK", raising=False)

        def _fail(*_args, **_kwargs):
            raise AssertionError("should not attempt a connection")

        monkeypatch.setattr(client, "set_fields", _fail)
        assert main(["hive-hook", "claude", '{"hook_event_name":"Stop"}']) == 0

    def test_dead_socket_returns_0(self, short_tmp, monkeypatch):
        sock = short_tmp / "gone.sock"
        monkeypatch.setenv("HIVE_PANE_SOCK", str(sock))
        assert main(["hive-hook", "codex", '{"type":"agent-turn-complete"}']) == 0

    def test_bad_json_returns_0(self, short_tmp, monkeypatch):
        sock = short_tmp / "p.sock"
        server = _server(sock)
        monkeypatch.setenv("HIVE_PANE_SOCK", str(sock))
        try:
            assert main(["hive-hook", "codex", "not json"]) == 0
        finally:
            server.close()

    def test_missing_agent_arg_returns_0(self, monkeypatch):
        monkeypatch.setenv("HIVE_PANE_SOCK", "/should/not/be/used.sock")
        assert main(["hive-hook"]) == 0
