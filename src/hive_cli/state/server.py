"""JsonLineServer (base) and PaneStateServer: Unix-socket NDJSON servers.

`JsonLineServer` is the shared plumbing (F4): one daemon thread accepting
connections, one handler thread per connection, greeting on connect, one
`handle(msg, conn)` dispatch per line. A subclass returns None from `handle`
to take over a connection itself (PaneStateServer's `subscribe` blocks in a
queue read loop, using `conn.send`) -- the handler thread then stops reading
lines and lets the connection close.

`hive run` owns exactly one `PaneStateServer` per pane. `update()` may be
called from any thread. `on_change` runs on a timer thread, coalesced: at
most once per `coalesce_s` after the last update, with the latest state --
that is where the multiplexer rename happens, so a burst of updates costs
one `zellij action`.

Wire protocol: see state/protocol.py. Stdlib only.
"""

from __future__ import annotations

import dataclasses
import os
import queue
import signal
import socketserver
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from . import protocol
from .pane_state import CLIENT_SETTABLE, STATUSES, PaneState

PING_AFTER_S = 15.0
_KNOWN_FIELDS = frozenset(f.name for f in dataclasses.fields(PaneState))


def _error(message: str) -> dict:
    return {"type": "error", "message": message}


def _validate_client_fields(fields: object) -> str | None:
    """Reason a client `set` must be rejected, or None when it is acceptable."""
    if not isinstance(fields, dict):
        return "fields must be an object"
    for name in fields:
        if name not in CLIENT_SETTABLE:
            return f"unknown field: {name}"
    if "status" in fields and fields["status"] not in STATUSES:
        return f"invalid status: {fields['status']}"
    pid = fields.get("agent_pid", 0)
    if isinstance(pid, bool) or not isinstance(pid, int):
        return "agent_pid must be an integer"
    return None


class Connection(Protocol):
    def send(self, msg: dict) -> None: ...


class _JsonLineTCPServer(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True
    block_on_close = False  # subscriber handlers block in q.get(); do not join them

    def __init__(self, path: str, owner: JsonLineServer):
        self.owner = owner
        super().__init__(path, _JsonLineHandler)


class _JsonLineHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        owner: JsonLineServer = self.server.owner
        try:
            greeting = owner.greeting()
            if greeting is not None:
                self.send(greeting)
            for raw in self.rfile:
                msg = protocol.decode(raw)
                if msg is None:
                    self.send(_error("bad json"))
                    continue
                reply = owner.handle(msg, self)
                if reply is None:  # owner took over the connection (e.g. subscribe)
                    return
                self.send(reply)
        except OSError:
            return

    def send(self, msg: dict) -> None:
        self.wfile.write(protocol.encode(msg))


class JsonLineServer:
    """Unix-socket NDJSON server: one daemon thread, one handler thread per
    client. Subclasses implement `greeting()` (sent once, on connect; None
    skips it) and `handle(msg, conn)` (per line; None means the subclass
    took over `conn` itself and the handler should stop reading)."""

    _THREAD_NAME = "hive-jsonline-server"

    def __init__(self, sock_path: Path):
        self.sock_path = Path(sock_path)
        self._lock = threading.RLock()
        self._server: _JsonLineTCPServer | None = None
        self._thread: threading.Thread | None = None
        self._closed = False

    def greeting(self) -> dict | None:
        return None

    def handle(self, msg: dict, conn: Connection) -> dict | None:
        raise NotImplementedError

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        """Unlink a stale file, bind, chmod 0o600, listen, serve from a thread."""
        self.sock_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.sock_path.unlink()
        except FileNotFoundError:
            pass
        self._server = _JsonLineTCPServer(str(self.sock_path), self)
        os.chmod(self.sock_path, 0o600)
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            kwargs={"poll_interval": 0.2},
            daemon=True,
            name=self._THREAD_NAME,
        )
        self._thread.start()

    def close(self) -> None:
        """Stop serving, unlink the socket. Idempotent.

        `_before_close`/`_after_close` are subclass hooks run (respectively)
        before the server stops serving and after `server_close()` but
        before the socket file is unlinked.
        """
        with self._lock:
            if self._closed:
                return
            self._closed = True
        self._before_close()
        if self._server is not None:
            if self._thread is not None:  # shutdown() blocks forever if never served
                self._server.shutdown()
            self._server.server_close()
        self._after_close()
        try:
            self.sock_path.unlink()
        except OSError:
            pass

    def _before_close(self) -> None:
        """Hook: runs once, before the server stops serving."""

    def _after_close(self) -> None:
        """Hook: runs once, after server_close(), before the socket is unlinked."""

    def __enter__(self) -> JsonLineServer:
        self.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


class PaneStateServer(JsonLineServer):
    """Serves one pane's state on a Unix socket from a daemon thread.

    Thread safety: `update()` may be called from any thread; `on_change` is
    called from a timer thread, coalesced: at most once per `coalesce_s`
    after the last update, with the latest state.
    """

    _THREAD_NAME = "hive-pane-server"

    def __init__(
        self,
        sock_path: Path,
        state: PaneState,
        *,
        on_change: Callable[[PaneState], None] | None = None,
        coalesce_s: float = 0.2,
    ):
        super().__init__(sock_path)
        self.stop_requested = threading.Event()
        self.restart_requested = threading.Event()
        self._state = state
        self._on_change = on_change
        self._coalesce_s = coalesce_s
        self._subscribers: list[queue.Queue] = []
        self._timer: threading.Timer | None = None
        self._pending = False

    # -- lifecycle -----------------------------------------------------------

    def _before_close(self) -> None:
        """Cancel the coalescing timer, then flush a pending on_change now."""
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
        self.flush()

    def _after_close(self) -> None:
        with self._lock:
            for q in self._subscribers:
                q.put(None)

    # -- state -------------------------------------------------------------

    @property
    def state(self) -> PaneState:
        """A copy of the current state."""
        with self._lock:
            return dataclasses.replace(self._state)

    def update(self, **fields: object) -> PaneState:
        """Apply `fields`, bump version, push to subscribers, (re)arm on_change.

        `status_since` moves only when `status` actually changes. Raises
        ValueError for an unknown field or an invalid status.
        """
        for name in fields:
            if name not in _KNOWN_FIELDS:
                raise ValueError(f"unknown field: {name}")
        if "status" in fields and fields["status"] not in STATUSES:
            raise ValueError(f"invalid status: {fields['status']}")
        with self._lock:
            st = self._state
            if "status" in fields and fields["status"] != st.status:
                st.status_since = time.time()
            for name, value in fields.items():
                setattr(st, name, value)
            st.version += 1
            snapshot = dataclasses.replace(st)
            msg = self._state_msg()
            for q in self._subscribers:
                q.put(msg)
            self._pending = True
            if not self._closed:
                self._arm_timer()
        return snapshot

    def flush(self) -> None:
        """Run a pending on_change now (used before close so the last rename lands)."""
        with self._lock:
            if not self._pending:
                return
            self._pending = False
            snapshot = dataclasses.replace(self._state)
        if self._on_change is not None:
            self._on_change(snapshot)

    def _arm_timer(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
        self._timer = threading.Timer(self._coalesce_s, self.flush)
        self._timer.daemon = True
        self._timer.start()

    # -- protocol (called from handler threads) -----------------------------

    def greeting(self) -> dict:
        return self._state_msg()

    def handle(self, msg: dict, conn: Connection) -> dict | None:
        if msg.get("op") == "subscribe":
            self._subscribe(conn)
            return None
        return self._handle(msg)

    def _state_msg(self) -> dict:
        with self._lock:
            return {"type": "state", **self._state.to_dict()}

    def _add_subscriber(self) -> tuple[queue.Queue, dict]:
        with self._lock:
            q: queue.Queue = queue.Queue()
            self._subscribers.append(q)
            return q, self._state_msg()

    def _remove_subscriber(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._subscribers:
                self._subscribers.remove(q)

    def _subscribe(self, conn: Connection) -> None:
        q, snapshot = self._add_subscriber()
        try:
            conn.send(snapshot)
            while True:
                try:
                    item = q.get(timeout=PING_AFTER_S)
                except queue.Empty:
                    conn.send({"type": "ping"})
                    continue
                if item is None:  # server closing
                    return
                conn.send(item)
        finally:
            self._remove_subscriber(q)

    def _handle(self, msg: dict) -> dict:
        op = msg.get("op")
        if op == "ping":
            return {"type": "pong"}
        if op == "get":
            return self._state_msg()
        if op == "set":
            return self._set_from_client(msg.get("fields"))
        if op in ("restart", "stop"):
            self._request(op)
            return {"type": "ok"}
        return _error(f"unknown op: {op}")

    def _set_from_client(self, fields: object) -> dict:
        reason = _validate_client_fields(fields)
        if reason is not None:
            return _error(reason)
        state = self.update(**fields)
        return {"type": "ok", "version": state.version}

    def _request(self, op: str) -> None:
        """Flag a restart/stop and SIGTERM the agent so the run loop sees it exit."""
        (self.restart_requested if op == "restart" else self.stop_requested).set()
        with self._lock:
            pid = self._state.agent_pid
        if pid > 0:
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
