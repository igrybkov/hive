"""Pure row-building for the control-plane TUI: no textual, no I/O."""

from __future__ import annotations

import pytest

from hive_cli.git import GitSummary
from hive_cli.mux.base import PaneInfo
from hive_cli.state.pane_state import PaneState
from hive_cli.ui.tui.model import (
    PaneRow,
    age_bucket,
    build_rows,
    filter_rows,
    git_cell,
    status_cell,
)


def _summary(**over) -> GitSummary:
    fields = dict(
        branch="feat",
        upstream="origin/feat",
        ahead=0,
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


class TestAgeBucket:
    @pytest.mark.parametrize(
        "seconds,expected",
        [
            (0, "<1m"),
            (59, "<1m"),
            (60, "1m"),
            (3599, "59m"),
            (3600, "1h"),
            (86399, "23h"),
            (86400, "1d"),
        ],
    )
    def test_buckets(self, seconds, expected):
        assert age_bucket(seconds) == expected


class TestGitCell:
    def test_none_is_unknown(self):
        assert git_cell(None) == "?"

    def test_clean_is_checkmark(self):
        assert git_cell(_summary()) == "✓"

    def test_dirty_counts_changes(self):
        assert git_cell(_summary(staged=1, modified=2, untracked=1)) == "±4"

    def test_ahead_and_behind_appended(self):
        cell = git_cell(_summary(staged=1, ahead=2, behind=3))
        assert cell == "±1 ↑2 ↓3"

    def test_clean_with_ahead_only(self):
        assert git_cell(_summary(ahead=1)) == "✓ ↑1"


class TestStatusCell:
    def test_composes_icon_status_and_age(self):
        row = PaneRow(
            pane_id="3",
            hive_pane_id=1,
            label="Anton",
            agent="claude",
            branch="feat",
            worktree="/wt",
            status="busy",
            status_since=100.0,
            git="✓",
            task="",
            tab_id="t1",
            focused=False,
        )
        assert status_cell(row, now=160.0) == "✳ busy 1m"


class TestBuildRows:
    def test_merges_states_panes_facts_tasks(self):
        states = {
            "3": PaneState(
                pane_id="3",
                hive_pane_id=1,
                label="Anton",
                agent="claude",
                branch="feat",
                worktree_path="/wt/feat",
                status="busy",
                status_since=50.0,
                tab_id="t1",
            ),
        }
        panes = {
            "3": PaneInfo("3", "t1", "title", "claude", "/wt/feat", True, False, False)
        }
        facts = {"/wt/feat": _summary(staged=1)}
        tasks = {"1": "fix the bug"}

        rows = build_rows(states, panes, facts, tasks, now=110.0)

        assert set(rows) == {"3"}
        row = rows["3"]
        assert row.branch == "feat"
        assert row.git == "±1"
        assert row.task == "fix the bug"
        assert row.focused is True
        assert row.tab_id == "t1"

    def test_missing_pane_and_facts_and_tasks_are_blank(self):
        states = {"3": PaneState(pane_id="3", hive_pane_id=1, tab_id="t1")}
        rows = build_rows(states, {}, {}, {}, now=0.0)
        row = rows["3"]
        assert row.git == "?"
        assert row.task == ""
        assert row.focused is False
        assert row.tab_id == "t1"  # falls back to state.tab_id

    def test_sorted_by_hive_pane_id_then_pane_id(self):
        states = {
            "9": PaneState(pane_id="9", hive_pane_id=2),
            "3": PaneState(pane_id="3", hive_pane_id=1),
            "5": PaneState(pane_id="5", hive_pane_id=1),
        }
        rows = build_rows(states, {}, {}, {}, now=0.0)
        assert list(rows) == ["3", "5", "9"]

    def test_pane_id_zero_sorts_last(self):
        states = {
            "1": PaneState(pane_id="1", hive_pane_id=0),
            "2": PaneState(pane_id="2", hive_pane_id=1),
        }
        rows = build_rows(states, {}, {}, {}, now=0.0)
        assert list(rows) == ["2", "1"]


class TestFilterRows:
    def _rows(self):
        return {
            "3": PaneRow(
                pane_id="3",
                hive_pane_id=1,
                label="Anton",
                agent="claude",
                branch="feat-auth",
                worktree="/wt",
                status="busy",
                status_since=0.0,
                git="?",
                task="fix login",
                tab_id="t1",
                focused=False,
            ),
            "4": PaneRow(
                pane_id="4",
                hive_pane_id=2,
                label="Bohdan",
                agent="codex",
                branch="fix-ci",
                worktree="/wt2",
                status="idle",
                status_since=0.0,
                git="?",
                task="",
                tab_id="t2",
                focused=False,
            ),
        }

    def test_empty_query_returns_all(self):
        rows = self._rows()
        assert filter_rows(rows, "") == rows

    def test_matches_branch_case_insensitive(self):
        assert set(filter_rows(self._rows(), "AUTH")) == {"3"}

    def test_matches_agent(self):
        assert set(filter_rows(self._rows(), "codex")) == {"4"}

    def test_matches_label(self):
        assert set(filter_rows(self._rows(), "bohdan")) == {"4"}

    def test_matches_task(self):
        assert set(filter_rows(self._rows(), "login")) == {"3"}

    def test_no_match_is_empty(self):
        assert filter_rows(self._rows(), "nope") == {}
