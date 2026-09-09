"""Tests for hive_cli.mux: get_mux(), the ZellijMux backend's argv table, and
the module-level pane-title helpers in hive_cli.mux.zellij.backend.

Every ZellijMux call goes through core.proc.run (fake_proc here) with the
exact argv verified against `zellij action <sub> --help` on 0.45.1. The
JSON fixtures were recorded from a live 0.45.1 session and trimmed to a
representative subset (see tests/fixtures/zellij_list_*.json).

Regression: rename-pane defaults to the focused pane, so we must pass
--pane-id explicitly with $ZELLIJ_PANE_ID to target our own pane.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hive_cli.layout.tabs import tool_tab
from hive_cli.mux import get_mux
from hive_cli.mux.base import PaneInfo, TabInfo
from hive_cli.mux.tmux.backend import TmuxMux
from hive_cli.mux.zellij import backend
from hive_cli.mux.zellij.backend import ZellijMux, _pane_id
from hive_cli.mux.zellij.kdl import render_tab_file
from hive_cli.state.pane_state import PaneState
from hive_cli.state.server import PaneStateServer

FIXTURES = Path(__file__).parent / "fixtures"
PANES_JSON = (FIXTURES / "zellij_list_panes.json").read_text()
TABS_JSON = (FIXTURES / "zellij_list_tabs.json").read_text()


class TestGetMux:
    def test_get_mux_matrix(self, monkeypatch):
        assert get_mux() is None
        monkeypatch.setenv("ZELLIJ", "0")  # presence, never truthiness
        assert isinstance(get_mux(), ZellijMux)
        monkeypatch.delenv("ZELLIJ")
        monkeypatch.setenv("HIVE_MUX_BACKEND", "zellij")
        assert isinstance(get_mux(), ZellijMux)
        monkeypatch.delenv("HIVE_MUX_BACKEND")
        monkeypatch.setenv("TMUX", "/tmp/tmux-501/default,123,0")
        assert isinstance(get_mux(), TmuxMux)

    def test_explicit_backend_argument_wins_over_env(self, monkeypatch):
        monkeypatch.setenv("TMUX", "/tmp/tmux-501/default,123,0")
        assert isinstance(get_mux("zellij"), ZellijMux)
        monkeypatch.setenv("ZELLIJ", "0")
        assert isinstance(get_mux("tmux"), TmuxMux)
        assert get_mux("none") is None


class TestPaneIdNormalisation:
    def test_pane_id_normalisation(self):
        assert _pane_id("terminal_3") == "3"
        assert _pane_id(" 3\n") == "3"
        assert _pane_id("plugin_1") == "1"
        assert _pane_id("terminal_12\n") == "12"
        assert _pane_id("") == ""


class TestZellijMuxIdentity:
    def test_own_ids_from_env(self, monkeypatch):
        mux = ZellijMux()
        assert mux.own_pane_id() is None and mux.own_session() is None
        monkeypatch.setenv("ZELLIJ_PANE_ID", "7")
        monkeypatch.setenv("ZELLIJ_SESSION_NAME", "s")
        assert mux.own_pane_id() == "7" and mux.own_session() == "s"
        assert mux.name == "zellij"

    def test_session_exists(self, fake_proc):
        fake_proc.script(["zellij", "list-sessions"], stdout="alpha\nbeta\n")
        mux = ZellijMux()
        assert mux.session_exists("beta") is True
        assert mux.session_exists("gamma") is False
        assert fake_proc.calls[-1] == ["zellij", "list-sessions", "--short"]

    def test_session_exists_false_when_zellij_fails(self, fake_proc):
        fake_proc.script(["zellij", "list-sessions"], returncode=1)
        assert ZellijMux().session_exists("alpha") is False

    def test_attach_argv(self, fake_proc):
        mux = ZellijMux()
        assert mux.attach_argv("s", "/l/agent.kdl") == [
            "zellij",
            "--layout",
            "/l/agent.kdl",
            "attach",
            "--create",
            "s",
        ]
        assert mux.attach_argv("s", None) == ["zellij", "attach", "--create", "s"]
        assert fake_proc.calls == []  # builds argv only, runs nothing


class TestZellijMuxActions:
    def test_focus_pane(self, fake_proc):
        ZellijMux().focus_pane("3")
        assert fake_proc.calls[-1] == ["zellij", "action", "focus-pane-id", "3"]

    def test_close_pane(self, fake_proc):
        ZellijMux().close_pane("3")
        assert fake_proc.calls[-1] == [
            "zellij",
            "action",
            "close-pane",
            "--pane-id",
            "3",
        ]

    def test_rename_pane(self, fake_proc):
        ZellijMux().rename_pane("3", "c1: Anton [claude]")
        assert fake_proc.calls[-1] == [
            "zellij",
            "action",
            "rename-pane",
            "--pane-id",
            "3",
            "c1: Anton [claude]",
        ]

    def test_rename_tab(self, fake_proc):
        ZellijMux().rename_tab("2", "feat ✳ · fix ⏳")
        assert fake_proc.calls[-1] == [
            "zellij",
            "action",
            "rename-tab",
            "--tab-id",
            "2",
            "feat ✳ · fix ⏳",
        ]

    def test_failures_are_ignored(self, fake_proc):
        fake_proc.script(["zellij"], returncode=1)
        mux = ZellijMux()
        assert mux.rename_pane("3", "t") is None
        assert mux.rename_tab("2", "n") is None
        assert mux.focus_pane("3") is None
        assert mux.close_pane("3") is None


class TestZellijMuxNewTab:
    def test_new_tab_writes_file_and_calls_new_tab(
        self, fake_proc, monkeypatch, tmp_path
    ):
        monkeypatch.setenv("ZELLIJ_SESSION_NAME", "s")
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
        fake_proc.script(["zellij", "action", "new-tab"], stdout="3\n")
        tab = tool_tab("git", hive="/opt/hive")

        result = ZellijMux().new_tab(tab)

        assert result == "3"
        expected_path = tmp_path / "hive" / "layouts" / "s" / "tab-git.kdl"
        assert expected_path.is_file()
        assert expected_path.read_text() == render_tab_file(tab)
        assert fake_proc.calls[-1] == [
            "zellij",
            "action",
            "new-tab",
            "--layout",
            str(expected_path),
            "--name",
            "git",
        ]

    def test_new_tab_no_focus_flag(self, fake_proc, monkeypatch, tmp_path):
        monkeypatch.setenv("ZELLIJ_SESSION_NAME", "s")
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
        fake_proc.script(["zellij", "action", "new-tab"], stdout="4\n")
        tab = tool_tab("nvim", hive="/opt/hive")

        ZellijMux().new_tab(tab, focus=False)

        assert fake_proc.calls[-1][-1] == "--no-focus"


class TestZellijMuxNewPane:
    def test_new_pane_returns_normalised_id(self, fake_proc):
        fake_proc.script(["zellij", "action", "new-pane"], stdout="terminal_12\n")
        assert ZellijMux().new_pane(["hive", "run"]) == "12"
        assert fake_proc.calls[-1] == [
            "zellij",
            "action",
            "new-pane",
            "--direction",
            "right",
            "--",
            "hive",
            "run",
        ]

    def test_new_pane_all_options(self, fake_proc):
        fake_proc.script(["zellij", "action", "new-pane"], stdout="terminal_5\n")
        pane = ZellijMux().new_pane(
            ["sh", "-c", "echo hi"],
            cwd="/w",
            direction="down",
            name="c9: Ihor",
            close_on_exit=True,
            suspended=True,
            width="40%",
            height="50%",
        )
        assert pane == "5"
        assert fake_proc.calls[-1] == [
            "zellij",
            "action",
            "new-pane",
            "--direction",
            "down",
            "--cwd",
            "/w",
            "--name",
            "c9: Ihor",
            "--close-on-exit",
            "--start-suspended",
            "--width",
            "40%",
            "--height",
            "50%",
            "--",
            "sh",
            "-c",
            "echo hi",
        ]

    def test_new_pane_floating_has_no_direction(self, fake_proc):
        fake_proc.script(["zellij", "action", "new-pane"], stdout="terminal_6\n")
        ZellijMux().new_pane(["sh"], floating=True)
        assert fake_proc.calls[-1] == [
            "zellij",
            "action",
            "new-pane",
            "--floating",
            "--",
            "sh",
        ]

    def test_new_pane_in_other_tab_uses_tab_id(self, fake_proc):
        """0.45.1 has `new-pane --tab-id` (verified live), so no go-to-tab dance."""
        fake_proc.script(["zellij", "action", "new-pane"], stdout="terminal_8\n")
        assert ZellijMux().new_pane(["hive", "run"], tab_id="4") == "8"
        assert fake_proc.count("zellij", "action", "go-to-tab-by-id") == 0
        cmd = fake_proc.calls[-1]
        assert cmd[cmd.index("--tab-id") + 1] == "4"

    def test_new_pane_no_focus_flag(self, fake_proc, monkeypatch):
        monkeypatch.setenv("ZELLIJ", "0")
        monkeypatch.setenv("ZELLIJ_PANE_ID", "7")
        monkeypatch.setenv("ZELLIJ_SESSION_NAME", "s")
        fake_proc.script(["zellij", "action", "new-pane"], stdout="terminal_9\n")
        ZellijMux().new_pane(["hive", "run"], focus=False)
        assert "--no-focus" in fake_proc.calls[-1]
        ZellijMux().new_pane(["hive", "run"], focus=True)
        assert "--no-focus" not in fake_proc.calls[-1]

    def test_new_pane_failure_returns_none(self, fake_proc):
        fake_proc.script(["zellij", "action", "new-pane"], returncode=1)
        assert ZellijMux().new_pane(["hive", "run"]) is None
        fake_proc.script(["zellij", "action", "new-pane"], stdout="")
        assert ZellijMux().new_pane(["hive", "run"]) is None

    def test_popup(self, fake_proc):
        ZellijMux().popup(["lazygit"], cwd="/w", name="git")
        assert fake_proc.calls[-1] == [
            "zellij",
            "action",
            "new-pane",
            "--floating",
            "--close-on-exit",
            "--name",
            "git",
            "--cwd",
            "/w",
            "--width",
            "80%",
            "--height",
            "80%",
            "--",
            "lazygit",
        ]

    def test_popup_without_cwd(self, fake_proc):
        ZellijMux().popup(["sh"], cwd=None, name="shell", width="50%", height="30%")
        cmd = fake_proc.calls[-1]
        assert "--cwd" not in cmd
        assert cmd[cmd.index("--width") + 1] == "50%"
        assert cmd[cmd.index("--height") + 1] == "30%"


class TestZellijMuxQueries:
    def test_list_panes_parses_fixture(self, fake_proc):
        fake_proc.script(["zellij", "action", "list-panes"], stdout=PANES_JSON)
        panes = ZellijMux().list_panes()
        assert fake_proc.calls[-1] == [
            "zellij",
            "action",
            "list-panes",
            "--all",
            "--json",
        ]
        raw = json.loads(PANES_JSON)
        assert len(panes) == sum(1 for p in raw if not p["is_plugin"])
        assert all(isinstance(p, PaneInfo) for p in panes)
        assert not any(p.id.startswith("terminal_") for p in panes)
        focused = next(p for p in panes if p.focused)
        assert focused == PaneInfo(
            id="0",
            tab_id="0",
            title="c1: Anton [claude] [main]",
            command=(
                "fish -c env HIVE_PANE_ID=1 HIVE_PANE_LABEL=Anton hive run --restart"
            ),
            cwd="/Users/illia/Projects/hive",
            focused=True,
            exited=False,
            suspended=False,
        )
        held = next(p for p in panes if p.title == "c2: Bohdan")
        assert held.suspended is True and held.cwd == "" and held.tab_id == "0"
        assert held.command.startswith("fish -c env HIVE_PANE_ID=2")
        assert {p.tab_id for p in panes} == {"0", "1"}

    def test_list_panes_tolerates_missing_keys(self, fake_proc):
        fake_proc.script(
            ["zellij", "action", "list-panes"],
            stdout=json.dumps([{"id": 4}, {"id": 1, "is_plugin": True}]),
        )
        assert ZellijMux().list_panes() == [
            PaneInfo(
                id="4",
                tab_id="",
                title="",
                command="",
                cwd="",
                focused=False,
                exited=False,
                suspended=False,
            )
        ]

    def test_list_panes_failure_or_bad_json_is_empty(self, fake_proc):
        fake_proc.script(["zellij", "action", "list-panes"], returncode=1)
        assert ZellijMux().list_panes() == []
        fake_proc.script(["zellij", "action", "list-panes"], stdout="nope")
        assert ZellijMux().list_panes() == []

    def test_list_tabs_parses_fixture(self, fake_proc):
        fake_proc.script(["zellij", "action", "list-tabs"], stdout=TABS_JSON)
        tabs = ZellijMux().list_tabs()
        assert fake_proc.calls[-1] == ["zellij", "action", "list-tabs", "--json"]
        assert tabs == [
            TabInfo(id="0", name="1. Chats 1-8", active=True),
            TabInfo(id="1", name="2. Chats 9-16", active=False),
            TabInfo(id="2", name="3. Teams", active=False),
        ]

    def test_list_tabs_failure_is_empty(self, fake_proc):
        fake_proc.script(["zellij", "action", "list-tabs"], returncode=1)
        assert ZellijMux().list_tabs() == []

    def test_current_tab_id_from_current_tab_info(self, fake_proc):
        fake_proc.script(
            ["zellij", "action", "current-tab-info"],
            stdout='{"position": 2, "name": "3. Teams", "active": true, "tab_id": 2}',
        )
        assert ZellijMux().current_tab_id() == "2"
        assert fake_proc.calls[-1] == [
            "zellij",
            "action",
            "current-tab-info",
            "--json",
        ]

    def test_current_tab_id_falls_back_to_focused_pane(self, fake_proc):
        fake_proc.script(["zellij", "action", "current-tab-info"], returncode=1)
        fake_proc.script(["zellij", "action", "list-panes"], stdout=PANES_JSON)
        assert ZellijMux().current_tab_id() == "0"

    def test_current_tab_id_none_when_nothing_answers(self, fake_proc):
        fake_proc.script(["zellij"], returncode=1)
        assert ZellijMux().current_tab_id() is None


class TestRenamePane:
    def test_rename_pane_targets_current_pane(self, monkeypatch, fake_proc):
        monkeypatch.setenv("ZELLIJ", "0")
        monkeypatch.setenv("ZELLIJ_PANE_ID", "7")

        backend.rename_pane("new title")

        assert fake_proc.count("zellij", "action", "rename-pane") == 1
        cmd = fake_proc.calls[0]
        assert cmd[:3] == ["zellij", "action", "rename-pane"]
        assert "--pane-id" in cmd
        assert cmd[cmd.index("--pane-id") + 1] == "7"
        assert cmd[-1] == "new title"

    def test_rename_pane_noop_outside_zellij(self, monkeypatch, fake_proc):
        monkeypatch.delenv("ZELLIJ", raising=False)

        backend.rename_pane("ignored")

        assert fake_proc.calls == []

    def test_append_to_pane_title_targets_current_pane(self, monkeypatch, fake_proc):
        monkeypatch.setenv("ZELLIJ", "0")
        monkeypatch.setenv("ZELLIJ_PANE_ID", "12")

        assert backend.append_to_pane_title("suffix") is True

        cmd = fake_proc.calls[0]
        assert "--pane-id" in cmd
        assert cmd[cmd.index("--pane-id") + 1] == "12"
        assert cmd[-1] == " suffix"

    def test_append_to_pane_title_blank_is_noop(self, monkeypatch, fake_proc):
        monkeypatch.setenv("ZELLIJ", "0")
        monkeypatch.setenv("ZELLIJ_PANE_ID", "12")

        assert backend.append_to_pane_title("   ") is False
        assert fake_proc.calls == []


class TestSetPaneFields:
    """set_pane_status/branch/custom_title: through the pane socket when a
    `hive run` serves this pane, else composed from the environment."""

    @pytest.fixture
    def zellij_env(self, monkeypatch):
        monkeypatch.setenv("ZELLIJ", "0")
        monkeypatch.setenv("ZELLIJ_SESSION_NAME", "test-session")
        monkeypatch.setenv("ZELLIJ_PANE_ID", "42")
        monkeypatch.setenv("HIVE_AGENT", "claude")
        monkeypatch.setenv("HIVE_PANE_ID", "1")
        monkeypatch.setenv("HIVE_PANE_LABEL", "Anton")

    def test_set_pane_status_uses_server_when_present(
        self, zellij_env, monkeypatch, short_tmp, fake_proc
    ):
        with PaneStateServer(short_tmp / "42.sock", PaneState(pane_id="42")) as srv:
            monkeypatch.setenv("HIVE_PANE_SOCK", str(srv.sock_path))
            assert backend.set_pane_status("[working]") is True
            assert srv.state.status_text == "[working]"
            assert backend.set_pane_branch("feat") is True
            assert srv.state.branch == "feat"
            assert backend.set_pane_custom_title(" note ") is True
            assert srv.state.custom_title == "note"
            assert backend.set_pane_status(None) is True
            assert srv.state.status_text == ""
            assert backend.rebuild_pane_title() is True
            assert srv.state.version == 5
        assert fake_proc.calls == []  # the server owns the rename; no zellij here

    def test_set_pane_status_falls_back_to_rename(self, zellij_env, fake_proc):
        assert backend.set_pane_status("[working]") is True
        assert fake_proc.calls[-1] == [
            "zellij",
            "action",
            "rename-pane",
            "--pane-id",
            "42",
            "c1: Anton [claude] [working]",
        ]

    def test_fallback_composes_each_field_alone(self, zellij_env, fake_proc):
        backend.set_pane_branch("feature-x")
        assert fake_proc.calls[-1][-1] == "c1: Anton [claude] [feature-x]"
        backend.set_pane_custom_title("My task")
        assert fake_proc.calls[-1][-1] == "c1: Anton [claude] My task"
        backend.set_pane_status(None)
        assert fake_proc.calls[-1][-1] == "c1: Anton [claude]"

    def test_rebuild_pane_title_minimal(self, zellij_env, fake_proc):
        assert backend.rebuild_pane_title() is True
        assert fake_proc.calls[-1][-1] == "c1: Anton [claude]"

    def test_rebuild_pane_title_fallback_to_cwd(self, monkeypatch, tmp_path, fake_proc):
        monkeypatch.setenv("ZELLIJ", "0")
        monkeypatch.setenv("ZELLIJ_SESSION_NAME", "test-fallback")
        monkeypatch.setenv("ZELLIJ_PANE_ID", "99")
        monkeypatch.delenv("HIVE_AGENT", raising=False)
        monkeypatch.delenv("HIVE_PANE_ID", raising=False)
        test_dir = tmp_path / "my-project"
        test_dir.mkdir()
        monkeypatch.chdir(test_dir)

        assert backend.rebuild_pane_title() is True
        cmd = fake_proc.calls[-1]
        assert cmd[-1] == str(test_dir)
        assert cmd[cmd.index("--pane-id") + 1] == "99"

    def test_not_in_zellij_returns_false(self, monkeypatch, fake_proc):
        monkeypatch.delenv("ZELLIJ", raising=False)
        assert backend.rebuild_pane_title() is False
        assert backend.set_pane_status("[working]") is False
        assert backend.set_pane_branch("feat") is False
        assert backend.set_pane_custom_title("t") is False
        assert fake_proc.calls == []
