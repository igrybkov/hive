"""Stdlib client for pane sockets: the CLI, hooks and the control plane all
talk to a `hive run` through these. Every call is one short connection; a
socket nobody listens on (a dead file left behind by a killed `hive run`) is
unlinked on sight.
"""

from __future__ import annotations

import errno
import socket
from collections.abc import Iterator
from pathlib import Path

from . import protocol
from .pane_state import PaneState

# connect() errors that mean "a file, but no server": unlink and move on.
_DEAD_ERRNOS = frozenset({errno.ECONNREFUSED, errno.ENOTSOCK})


def _connect(sock_path: Path, timeout: float) -> socket.socket:
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect(str(sock_path))
    except OSError:
        s.close()
        raise
    return s


def _unlink(sock_path: Path) -> None:
    try:
        Path(sock_path).unlink()
    except OSError:
        pass


def send(sock_path: Path, msg: dict, *, timeout: float = 0.5) -> dict | None:
    """Connect, read the greeting, send one op, return its reply.

    None on any OSError or timeout (including "nobody listening").
    """
    try:
        with _connect(sock_path, timeout) as s, s.makefile("rb") as rf:
            if protocol.decode(rf.readline()) is None:
                return None
            s.sendall(protocol.encode(msg))
            return protocol.decode(rf.readline())
    except OSError:
        return None


def get_state(sock_path: Path, *, timeout: float = 0.5) -> dict | None:
    """The greeting `state` dict, or None when nobody is listening.

    A socket file that refuses connections is stale and gets unlinked.
    """
    try:
        with _connect(sock_path, timeout) as s, s.makefile("rb") as rf:
            return protocol.decode(rf.readline())
    except FileNotFoundError:
        return None
    except OSError as exc:
        if exc.errno in _DEAD_ERRNOS:
            _unlink(sock_path)
        return None


def set_fields(sock_path: Path, **fields: object) -> bool:
    return (send(sock_path, {"op": "set", "fields": fields}) or {}).get("type") == "ok"


def request(sock_path: Path, op: str) -> bool:
    """Send a `restart` or `stop` op; True when the server acknowledged it."""
    return (send(sock_path, {"op": op}) or {}).get("type") == "ok"


def subscribe(sock_path: Path, *, timeout: float = 2.0) -> Iterator[dict]:
    """Blocking generator of state dicts (pings filtered out).

    Yields the current state first, then one dict per change. Raises
    TimeoutError after `timeout` s of silence; returns when the server closes.
    """
    with _connect(sock_path, timeout) as s, s.makefile("rb") as rf:
        rf.readline()  # the greeting; the subscribe reply repeats the state
        s.sendall(protocol.encode({"op": "subscribe"}))
        while True:
            try:
                line = rf.readline()
            except TimeoutError as exc:
                raise TimeoutError(
                    f"no message from {sock_path} in {timeout}s"
                ) from exc
            if not line:
                return
            msg = protocol.decode(line)
            if msg is not None and msg.get("type") == "state":
                yield msg


def _candidates(session_dir: Path) -> list[Path]:
    if not session_dir.is_dir():
        return []
    return sorted(p for p in session_dir.glob("*.sock") if p.name != "control.sock")


def list_pane_sockets(session_dir: Path) -> list[Path]:
    """`*.sock` except control.sock, sorted; unlinks and skips dead sockets."""
    return [p for p in _candidates(session_dir) if get_state(p) is not None]


def list_states(session_dir: Path) -> list[PaneState]:
    """The live PaneState of every pane socket in `session_dir`."""
    states = []
    for path in _candidates(session_dir):
        data = get_state(path)
        if data is not None:
            states.append(PaneState.from_dict(data))
    return states
