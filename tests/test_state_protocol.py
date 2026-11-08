"""Tests for hive_cli.state.protocol: one JSON object per line."""

from __future__ import annotations

from hive_cli.state import protocol


def test_encode_is_compact_newline_terminated_utf8():
    assert protocol.encode({"op": "set", "fields": {"status": "busy"}}) == (
        b'{"op":"set","fields":{"status":"busy"}}\n'
    )
    assert protocol.encode({"t": "✳"}) == '{"t":"✳"}\n'.encode()


def test_decode_roundtrip_and_tolerates_whitespace():
    assert protocol.decode(protocol.encode({"op": "ping"})) == {"op": "ping"}
    assert protocol.decode(b'  {"op":"get"}  \r\n') == {"op": "get"}


def test_decode_rejects_non_json_and_non_objects():
    assert protocol.decode(b"not json\n") is None
    assert protocol.decode(b"[1,2]\n") is None
    assert protocol.decode(b'"str"\n') is None
    assert protocol.decode(b"") is None
    assert protocol.decode(b"\xff\xfe\n") is None


def test_ops_are_the_documented_set():
    assert protocol.OPS == {"ping", "get", "set", "subscribe", "restart", "stop"}
    assert protocol.SCHEMA == 1
