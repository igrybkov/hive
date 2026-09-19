"""Git and GitHub facts refreshed off the UI thread, plus the control-plane
socket (F4) that shares them across the session.

The picker's refiners and `hive doctor` call these; nothing here prints or
prompts, every command has a timeout, and the loops check `cancel` so a
closed picker never keeps a thread busy. `.git/FETCH_HEAD` belongs to git:
hive reads its mtime to throttle fetches and never writes it.
"""

from __future__ import annotations

import os
import shutil
import threading
import time
from collections.abc import Callable
from pathlib import Path

from ..config import get_settings
from ..core import paths, proc
from ..core.errors import HiveError
from ..git import GitHubIssue, GitSummary, WorktreeInfo, git_summary
from ..git import github as github_facts
from ..state import client
from ..state.server import Connection, JsonLineServer
from . import registry


def fetch_if_stale(
    main_repo: Path, interval_s: float, *, now: float | None = None
) -> bool:
    """Run `git fetch origin` unless FETCH_HEAD is younger than interval_s.

    Returns True when a fetch ran and succeeded.
    """
    fetch_head = main_repo / ".git" / "FETCH_HEAD"
    current = time.time() if now is None else now
    try:
        if current - fetch_head.stat().st_mtime < interval_s:
            return False
    except OSError:
        pass  # never fetched here: fetch now
    return proc.run(["git", "fetch", "origin"], cwd=main_repo, timeout=60).ok


def summaries(
    worktrees: list[WorktreeInfo], *, cancel: threading.Event | None = None
) -> dict[Path, GitSummary]:
    """`git_summary` per worktree (two spawns each); stops early when cancelled."""
    out: dict[Path, GitSummary] = {}
    for wt in worktrees:
        if cancel is not None and cancel.is_set():
            break
        out[wt.path] = git_summary(wt.path)
    return out


def _is_fresh(path: Path, max_age_s: float) -> bool:
    try:
        return time.time() - path.stat().st_mtime < max_age_s
    except OSError:
        return False


def issues(main_repo: Path, *, max_age_s: float = 60.0) -> list[GitHubIssue] | None:
    """Cached gh issues, refreshed only when gh is on PATH and the cache is
    older than max_age_s.

    None means "nothing to show": issues disabled in config, no gh, not a
    GitHub remote, or a failed refresh with nothing cached. A failed refresh
    keeps serving the stale cache.
    """
    if not get_settings().github.fetch_issues or shutil.which("gh") is None:
        return None
    cache_path = github_facts.get_issues_cache_path(main_repo)
    if cache_path is None:
        return None
    if _is_fresh(cache_path, max_age_s):
        return github_facts.load_cached_issues(cache_path)
    fetched = github_facts.fetch_issues(main_repo, cache_path=cache_path)
    if fetched is not None:
        return fetched
    return github_facts.load_cached_issues(cache_path) if cache_path.exists() else None


# ---------------------------------------------------------------------------
# F4: the control-plane socket
# ---------------------------------------------------------------------------


class ControlServer(JsonLineServer):
    """The control plane's socket: `paths.control_sock(session)`.

    `facts` is called on a handler thread on every `{"op":"facts"}`; callers
    keep it cheap (return the latest already-computed dict, never fetch).
    """

    _THREAD_NAME = "hive-control-server"

    def __init__(
        self,
        sock_path: Path,
        *,
        pane_id: str,
        facts: Callable[[], dict[str, GitSummary]],
    ):
        super().__init__(sock_path)
        self._pane_id = pane_id
        self._facts = facts

    def greeting(self) -> dict:
        return {
            "type": "state",
            "kind": "control",
            "pane_id": self._pane_id,
            "hive_pid": os.getpid(),
        }

    def handle(self, msg: dict, conn: Connection) -> dict:
        op = msg.get("op")
        if op == "ping":
            return {"type": "pong"}
        if op == "get":
            return self.greeting()
        if op == "facts":
            return {"type": "facts", "facts": registry.jsonable(self._facts())}
        if op == "call":
            return self._call(msg)
        return {"type": "error", "message": f"unknown op: {op}"}

    def _call(self, msg: dict) -> dict:
        name = msg.get("name")
        args = msg.get("args") or {}
        if not isinstance(name, str) or not isinstance(args, dict):
            return {"type": "error", "message": "bad call"}
        try:
            value = registry.call(name, **args)
        except HiveError as exc:
            return {"type": "error", "message": str(exc)}
        return {"type": "result", "value": registry.jsonable(value)}


def summaries_via_control(
    session: str, *, timeout: float = 0.5
) -> dict[Path, GitSummary] | None:
    """Ask a running control plane for its facts; None when no control plane
    answers (the caller should fetch/compute them itself)."""
    reply = client.send(paths.control_sock(session), {"op": "facts"}, timeout=timeout)
    if reply is None or reply.get("type") != "facts":
        return None
    return {Path(p): GitSummary(**d) for p, d in reply["facts"].items()}
