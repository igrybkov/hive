"""Tests for hive_cli.layout.tabs: bundled tool tabs and session_spec."""

from __future__ import annotations

import pytest

from hive_cli.config.schema import PaneConfig, TabConfig, ZellijConfig
from hive_cli.config.settings import HiveSettings
from hive_cli.core.errors import HiveError
from hive_cli.layout.tabs import (
    BUNDLED,
    agents_tab,
    resolve_tab,
    session_spec,
    tool_tab,
)


class TestBundledTabs:
    @pytest.mark.parametrize("name", list(BUNDLED))
    def test_every_bundled_name_resolves(self, name):
        tab = tool_tab(name, hive="/opt/hive")
        assert tab.name == name
        assert len(tab.panes) >= 1

    def test_unknown_name_raises(self):
        with pytest.raises(HiveError):
            tool_tab("nope", hive="/opt/hive")


class TestResolveTab:
    def test_user_tab_overrides_bundled_name(self):
        user_tabs = {
            "git": TabConfig(panes=[PaneConfig(name="custom", command="echo hi")])
        }
        tab = resolve_tab("git", hive="/opt/hive", user_tabs=user_tabs)
        assert tab.name == "git"
        assert len(tab.panes) == 1
        assert tab.panes[0].name == "custom"
        assert tab.panes[0].command == ("echo", "hi")

    def test_user_tab_adds_new_name(self):
        user_tabs = {
            "docs": TabConfig(panes=[PaneConfig(name="docs", command="less README.md")])
        }
        tab = resolve_tab("docs", hive="/opt/hive", user_tabs=user_tabs)
        assert tab.name == "docs"
        assert tab.panes[0].name == "docs"
        assert tab.panes[0].command == ("less", "README.md")

    def test_bundled_name_without_override(self):
        tab = resolve_tab("nvim", hive="/opt/hive", user_tabs={})
        assert tab.name == "nvim"

    def test_string_command_is_shlex_split(self):
        user_tabs = {
            "x": TabConfig(panes=[PaneConfig(name="p", command="fish -c 'echo hi'")])
        }
        tab = resolve_tab("x", hive="/opt/hive", user_tabs=user_tabs)
        assert tab.panes[0].command == ("fish", "-c", "echo hi")

    def test_list_command_used_as_is(self):
        user_tabs = {"x": TabConfig(panes=[PaneConfig(name="p", command=["a", "b c"])])}
        tab = resolve_tab("x", hive="/opt/hive", user_tabs=user_tabs)
        assert tab.panes[0].command == ("a", "b c")


class TestAgentsTab:
    def test_n1_has_one_agent_pane_and_control(self):
        tab = agents_tab(n=1, control="right", hive="/opt/hive", labels=["Anton"])
        assert len(tab.panes) == 2
        assert tab.panes[0].name == "c1: Anton"
        assert tab.panes[0].suspended is False
        assert tab.panes[1].name == "hive"

    def test_n2_second_pane_suspended(self):
        tab = agents_tab(
            n=2, control="right", hive="/opt/hive", labels=["Anton", "Bohdan"]
        )
        assert tab.panes[0].suspended is False
        assert tab.panes[1].suspended is True

    def test_control_none_has_no_control_pane(self):
        tab = agents_tab(
            n=2, control="none", hive="/opt/hive", labels=["Anton", "Bohdan"]
        )
        assert len(tab.panes) == 2
        assert all(p.name != "hive" for p in tab.panes)

    def test_control_bottom_puts_control_pane_last(self):
        tab = agents_tab(
            n=2, control="bottom", hive="/opt/hive", labels=["Anton", "Bohdan"]
        )
        assert tab.panes[-1].name == "hive"
        assert tab.panes[-1].size == "8"
        assert tab.direction == "horizontal"

    def test_labels_beyond_list_get_bare_name(self):
        tab = agents_tab(n=2, control="none", hive="/opt/hive", labels=["Anton"])
        assert tab.panes[1].name == "c2"
        assert tab.panes[1].env == (("HIVE_PANE_ID", "2"),)

    def test_first_id_numbers_panes(self):
        tab = agents_tab(
            n=2,
            control="none",
            hive="/opt/hive",
            labels=["Chris", "Dmytro"],
            first_id=3,
        )
        assert tab.panes[0].name == "c3: Chris"
        assert tab.panes[1].name == "c4: Dmytro"


class TestSessionSpec:
    def test_uses_settings_and_marks_focus(self):
        settings = HiveSettings(
            zellij=ZellijConfig(
                agents_per_tab=1, control_plane="none", pane_labels=["Ann"]
            )
        )
        spec = session_spec(name="s", hive="/opt/hive", settings=settings)
        assert len(spec.tabs) == 1
        assert spec.tabs[0].focus is True
        assert len(spec.tabs[0].panes) == 1
