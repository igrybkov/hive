"""Test doubles shared across test modules (imported as `from fakes import ...`,
relying on pytest's rootdir prepend like conftest.py does)."""

from __future__ import annotations


class FakeMux:
    """Records every call; returns canned panes/tabs; hands out increasing pane ids."""

    name = "fake"

    def __init__(self, *, pane_id="3", session="test", panes=(), tabs=()):
        self.calls: list[tuple[str, tuple, dict]] = []
        self._own, self._session = pane_id, session
        self.panes, self.tabs = list(panes), list(tabs)
        self._next = 100

    def _rec(self, op, *args, **kw):
        self.calls.append((op, args, kw))

    def named(self, name):  # helper for assertions
        return [c for c in self.calls if c[0] == name]

    def own_pane_id(self):
        return self._own

    def own_session(self):
        return self._session

    def session_exists(self, s):
        self._rec("session_exists", s)
        return s == self._session

    def attach_argv(self, s, layout):
        return ["fake-attach", s, layout or ""]

    def list_panes(self):
        self._rec("list_panes")
        return list(self.panes)

    def list_tabs(self):
        self._rec("list_tabs")
        return list(self.tabs)

    def current_tab_id(self):
        return next((t.id for t in self.tabs if t.active), "t1")

    def focus_pane(self, pid):
        self._rec("focus_pane", pid)

    def close_pane(self, pid):
        self._rec("close_pane", pid)

    def rename_pane(self, pid, title):
        self._rec("rename_pane", pid, title)

    def rename_tab(self, tid, name):
        self._rec("rename_tab", tid, name)

    def resume_pane(self, pid):
        self._rec("resume_pane", pid)

    def new_pane(self, argv, **kw):
        self._rec("new_pane", tuple(argv), **kw)
        self._next += 1
        return str(self._next)

    def new_tab(self, spec, *, focus=True):
        self._rec("new_tab", spec, focus=focus)
        self._next += 1
        return f"tab{self._next}"

    def popup(self, argv, **kw):
        self._rec("popup", tuple(argv), **kw)
