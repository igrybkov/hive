"""tmux terminal multiplexer backend: `TmuxMux` on a private server (`-L
<server>`), plus the imperative session bootstrap tmux needs in place of
Zellij's declarative layout file.

Every call goes through `_tmux` (`proc.run(["tmux", "-L", server, ...])`)
and returns None/[] on failure, matching `ZellijMux`'s "a dead multiplexer
must never crash hive" contract. `list_panes`/`list_tabs` scope to
`own_session()` (cached on the instance after the first successful lookup,
since a running process's own tmux session never changes) rather than the
`-a` ("all sessions") flag: the private server can host more than one hive
session at once (one per repo), and `-a` would leak panes across them into
one repo's control plane -- a deliberate deviation from the exact argv in
F6-tmux.md, recorded in docs/ARCHITECTURE.md. A `TmuxMux(conf=...)` instance
passes `-f <conf>` on every call it makes: whichever command first touches
a not-yet-running private server starts it, and tmux only honours `-f` on
that first command -- otherwise it silently falls back to the user's own
`~/.tmux.conf` / `~/.config/tmux/tmux.conf` (verified on this machine).
Only `services/session.py`'s startup path constructs a `conf=`-bearing
instance; every other caller (via `get_mux()`) uses the bare, cheaper form
once the session is already known to exist.
"""

from __future__ import annotations

import os
from collections.abc import Iterator, Sequence
from pathlib import Path

from ...core import proc
from ...layout.model import PaneSpec, SessionSpec, TabSpec
from ..base import PaneInfo, TabInfo

_PANE_FORMAT = "\t".join(
    (
        "#{pane_id}",
        "#{window_id}",
        "#{pane_title}",
        "#{pane_current_command}",
        "#{pane_current_path}",
        "#{pane_active}",
        "#{window_active}",
        "#{pane_dead}",
    )
)
_WINDOW_FORMAT = "\t".join(("#{window_id}", "#{window_name}", "#{window_active}"))


def _pane_info(fields: list[str]) -> PaneInfo | None:
    if len(fields) != 8:
        return None
    pid, wid, title, command, cwd, pane_active, window_active, dead = fields
    return PaneInfo(
        id=pid,
        tab_id=wid,
        title=title,
        command=command,
        cwd=cwd,
        # `pane_active` alone is 1 for the active pane of *every* window, not
        # just the one the user is looking at (verified: a two-window session
        # lists two `pane_active=1` rows) -- true focus needs both.
        focused=pane_active == "1" and window_active == "1",
        exited=dead == "1",
        # Not `command == "hive"` (F6-tmux.md's own literal wording): a
        # `uv tool install`ed hive reports its interpreter as
        # #{pane_current_command} (verified: "python3.14"), never "hive".
        # The "hold: " title is unique to hive.pane.hold and sufficient alone.
        suspended=title.startswith("hold:"),
    )


def _tab_info(fields: list[str]) -> TabInfo | None:
    if len(fields) != 3:
        return None
    wid, name, active = fields
    return TabInfo(id=wid, name=name, active=active == "1")


def _iter_leaves(
    panes: Sequence[PaneSpec], direction: str
) -> Iterator[tuple[PaneSpec, str]]:
    """Depth-first (leaf, split_direction) pairs across a `PaneSpec` tree.

    tmux has no native nested layout: every pane after the first is created
    by splitting whatever tmux's "new pane becomes active" default just made
    active, so nesting can only be realized by picking the right split flag
    at each step, in the exact order the tree implies. A container's first
    leaf inherits *its parent list's* direction (it visually sits where the
    container sits, splitting off whatever came before the container); every
    other leaf in the container uses the container's *own* `direction`
    (splitting off the previous leaf within that same container).

    Invariant this relies on: a container must be the *last* element of the
    list it's in (the only real use, `agents_tab`'s control="right", nests
    "hive" under the last agent pane). A sibling placed after a container
    is not supported -- it would split off the container's last leaf, not
    the whole container -- so don't build layouts that need that.
    """
    for pane in panes:
        if not pane.children:
            yield pane, direction
            continue
        leaves = list(_iter_leaves(pane.children, pane.direction))
        yield leaves[0][0], direction  # the container's position, not its own direction
        yield from leaves[1:]


def _pane_argv(pane: PaneSpec) -> list[str]:
    """A pane's own argv: suspended wraps in `hive pane hold --`, env wraps
    the result in `/usr/bin/env K=V ...` (outermost, like Zellij's kdl.py);
    a `command=()` pane runs $SHELL."""
    argv = list(pane.command) if pane.command else [os.environ.get("SHELL", "/bin/sh")]
    if pane.suspended:
        argv = ["hive", "pane", "hold", "--", *argv]
    if pane.env:
        pairs = [f"{k}={v}" for k, v in pane.env]
        argv = ["/usr/bin/env", *pairs, *argv]
    return argv


class TmuxMux:
    """The `Mux` protocol over the `tmux` CLI on a private server (see mux/base.py)."""

    name = "tmux"

    def __init__(self, server: str = "hive", *, conf: Path | None = None) -> None:
        self.server = server
        self.conf = conf
        self._session_cache: str | None = None

    def _tmux(self, *args: str, timeout: float = 2.0) -> proc.Result | None:
        argv = ["tmux", "-L", self.server]
        if self.conf is not None:
            argv += ["-f", str(self.conf)]
        result = proc.run([*argv, *args], timeout=timeout)
        return result if result.ok else None

    def own_pane_id(self) -> str | None:
        return os.environ.get("TMUX_PANE") or None

    def own_session(self) -> str | None:
        """`display -p '#S'`, cached: a process's own tmux session is fixed
        for its lifetime, and this is the only Mux call to spawn just to
        answer "which session am I in" -- worth not repeating."""
        if self._session_cache is not None:
            return self._session_cache
        if "TMUX" not in os.environ:
            return None
        result = self._tmux("display", "-p", "#S")
        if result is None:
            return None
        self._session_cache = result.stdout.strip() or None
        return self._session_cache

    def session_exists(self, session: str) -> bool:
        return self._tmux("has-session", "-t", f"={session}") is not None

    def attach_argv(self, session: str, layout_path: str | None) -> list[str]:
        argv = ["tmux", "-L", self.server]
        if layout_path:
            argv += ["-f", layout_path]
        return [*argv, "attach-session", "-t", session]

    def list_panes(self) -> list[PaneInfo]:
        session = self.own_session()
        scope = ["-s", "-t", session] if session else ["-a"]
        result = self._tmux("list-panes", *scope, "-F", _PANE_FORMAT)
        if result is None:
            return []
        panes = (_pane_info(line.split("\t")) for line in result.stdout.splitlines())
        return [p for p in panes if p is not None]

    def list_tabs(self) -> list[TabInfo]:
        session = self.own_session()
        scope = ["-t", session] if session else ["-a"]
        result = self._tmux("list-windows", *scope, "-F", _WINDOW_FORMAT)
        if result is None:
            return []
        tabs = (_tab_info(line.split("\t")) for line in result.stdout.splitlines())
        return [t for t in tabs if t is not None]

    def focus_pane(self, pane_id: str) -> None:
        self._tmux("select-window", "-t", pane_id)
        self._tmux("select-pane", "-t", pane_id)

    def close_pane(self, pane_id: str) -> None:
        self._tmux("kill-pane", "-t", pane_id)

    def rename_pane(self, pane_id: str, title: str) -> None:
        self._tmux("select-pane", "-t", pane_id, "-T", title)

    def rename_tab(self, tab_id: str, name: str) -> None:
        self._tmux("rename-window", "-t", tab_id, name)

    def resume_pane(self, pane_id: str) -> None:
        """A `suspended` pane here is always `hive pane hold` (F6) wrapping
        the real command, blocked on `input()` -- injecting Enter unblocks
        it exactly like a person pressing it."""
        self._tmux("send-keys", "-t", pane_id, "Enter")

    def current_tab_id(self) -> str | None:
        """Not in F6-tmux.md's method table but required by the `Mux`
        protocol; mirrors `ZellijMux`'s own-pane-first-else-focused fallback."""
        pane_id = self.own_pane_id()
        panes = self.list_panes()
        if pane_id:
            match = next((p for p in panes if p.id == pane_id), None)
            if match:
                return match.tab_id
        return next((p.tab_id for p in panes if p.focused), None)

    def new_pane(
        self,
        argv: Sequence[str],
        *,
        cwd: str | None = None,
        tab_id: str | None = None,
        direction: str = "right",
        name: str | None = None,
        close_on_exit: bool = False,
        focus: bool = True,
        floating: bool = False,
        suspended: bool = False,
        stacked: bool = False,
        width: str | None = None,
        height: str | None = None,
    ) -> str | None:
        del close_on_exit  # tmux default: `remain-on-exit off`, set once in conf.py
        if direction == "auto":
            direction = "right"  # tmux has no layout engine to defer to
        del stacked  # tmux has no native pane stacking; falls back to a plain split.
        if floating:
            self.popup(
                argv,
                cwd=cwd,
                name=name or "",
                width=width or "80%",
                height=height or "80%",
            )
            return None
        real_argv = ["hive", "pane", "hold", "--", *argv] if suspended else list(argv)
        args = ["split-window", "-h" if direction == "right" else "-v"]
        if not focus:
            args.append("-d")
        if tab_id:
            args += ["-t", tab_id]
        if cwd:
            args += ["-c", cwd]
        size = width if direction == "right" else height
        if size:
            args += ["-l", size]
        result = self._tmux(*args, "-P", "-F", "#{pane_id}", "--", *real_argv)
        if result is None:
            return None
        pane_id = result.stdout.strip() or None
        if pane_id and name:
            self._tmux("select-pane", "-t", pane_id, "-T", name)
        return pane_id

    def _apply_leaves(
        self, leaves: Sequence[tuple[PaneSpec, str]], window_id: str
    ) -> None:
        """Split each (leaf, split_direction) pair from `_iter_leaves` into
        an already-created window, in order -- tmux has no native nested
        layout, so relying on its default "the new pane becomes active"
        behavior to chain each split off the previous leaf is what actually
        realizes the nesting `_iter_leaves` computed."""
        for pane, direction in leaves:
            flag = "-h" if direction == "vertical" else "-v"
            args = ["split-window", flag, "-t", window_id]
            if pane.cwd:
                args += ["-c", pane.cwd]
            if pane.size:
                args += ["-l", pane.size]
            self._tmux(*args, "-P", "-F", "#{pane_id}", "--", *_pane_argv(pane))

    def new_tab(self, spec: TabSpec, *, focus: bool = True) -> str | None:
        leaves = list(_iter_leaves(spec.panes, spec.direction))
        pane0 = leaves[0][0]
        args = ["new-window"]
        if not focus:
            args.append("-d")
        args += ["-n", spec.name]
        if pane0.cwd:
            args += ["-c", pane0.cwd]
        result = self._tmux(*args, "-P", "-F", "#{window_id}", "--", *_pane_argv(pane0))
        if result is None:
            return None
        window_id = result.stdout.strip() or None
        if window_id:
            self._apply_leaves(leaves[1:], window_id)
        return window_id

    def bootstrap(self, spec: SessionSpec) -> None:
        """Idempotent: create the session (first tab/pane inline, the rest
        via `_apply_leaves`/`new_tab`) only when it doesn't already exist."""
        if self.session_exists(spec.name):
            return
        first_tab = spec.tabs[0]
        leaves = list(_iter_leaves(first_tab.panes, first_tab.direction))
        pane0 = leaves[0][0]
        args = ["new-session", "-d", "-s", spec.name, "-n", first_tab.name]
        if pane0.cwd:
            args += ["-c", pane0.cwd]
        result = self._tmux(*args, "-P", "-F", "#{window_id}", "--", *_pane_argv(pane0))
        window_id = result.stdout.strip() if result else None
        if window_id:
            self._apply_leaves(leaves[1:], window_id)
        for tab in spec.tabs[1:]:
            self.new_tab(tab, focus=False)

    def popup(
        self,
        argv: Sequence[str],
        *,
        cwd: str | None,
        name: str,
        width: str = "80%",
        height: str = "80%",
    ) -> None:
        args = ["display-popup", "-E"]
        if cwd:
            args += ["-d", cwd]
        args += ["-w", width, "-h", height, "-T", name, "--", *argv]
        self._tmux(*args)
