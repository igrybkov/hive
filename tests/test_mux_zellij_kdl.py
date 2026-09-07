"""Golden tests for hive_cli.mux.zellij.kdl: layout model -> KDL text."""

from __future__ import annotations

from hive_cli.layout.model import KeybindSpec, PaneSpec, SessionSpec
from hive_cli.layout.tabs import agents_tab, tool_tab
from hive_cli.mux.zellij.kdl import (
    kdl_string,
    render_pane,
    render_session_file,
    render_tab_body,
    render_tab_file,
)

# NOTE: the F2 spec's illustrative golden block uses `plugin
# location="zellij:tab-bar"`; the real, currently-running `agent.kdl` uses
# the bare `location="tab-bar"` (verified: src/hive_cli/layout/bundled/
# agent.kdl). Per the spec's own escape hatch ("copy the default_tab_template
# block from the current agent.kdl verbatim if it differs from the above"),
# this test uses the bare form.
SESSION_GOLDEN = (
    "\n".join(
        [
            "layout {",
            "    default_tab_template {",
            "        pane size=1 borderless=true {",
            '            plugin location="tab-bar"',
            "        }",
            "        children",
            "        pane size=2 borderless=true {",
            '            plugin location="status-bar"',
            "        }",
            "    }",
            '    tab name="agents" focus=true {',
            '        pane split_direction="vertical" {',
            '            pane name="c1: Anton" {',
            '                command "/usr/bin/env"',
            '                args "HIVE_PANE_ID=1" "HIVE_PANE_LABEL=Anton" '
            '"/opt/hive" "run" "--restart"',
            "            }",
            '            pane name="c2: Bohdan" {',
            '                command "/usr/bin/env"',
            '                args "HIVE_PANE_ID=2" "HIVE_PANE_LABEL=Bohdan" '
            '"/opt/hive" "run" "--restart"',
            "                start_suspended true",
            "            }",
            '            pane name="hive" size="30%" {',
            '                command "/opt/hive"',
            '                args "status" "--watch" "--compact"',
            "            }",
            "        }",
            "    }",
            "}",
            "stacked_resize false",
            "auto_layout false",
        ]
    )
    + "\n"
)


def test_render_session_golden():
    tab = agents_tab(
        n=2, control="right", hive="/opt/hive", labels=["Anton", "Bohdan"], focus=True
    )
    session = SessionSpec(name="s", tabs=(tab,))
    out = render_session_file(session, "/opt/hive")
    assert out.strip() == SESSION_GOLDEN.strip()


# Hand-written independently of the renderer (not pasted from its output),
# from tab 6 ("6. Git") of the pre-F2 layout/bundled/agent.kdl (now
# agent-16.kdl): lazygit 70%/suspended on top, a plain fish shell below.
GIT_TAB_GOLDEN = """\
layout {
    default_tab_template {
        pane size=1 borderless=true {
            plugin location="tab-bar"
        }
        children
        pane size=2 borderless=true {
            plugin location="status-bar"
        }
    }
    tab name="git" {
        pane split_direction="horizontal" {
            pane name="lazygit" size="70%" {
                command "fish"
                args "-c" "cd (hive wt parent) && exec lazygit"
                start_suspended true
            }
            pane name="git-shell" {
                command "fish"
                args "-c" "cd (hive wt parent) && exec fish"
            }
        }
    }
}
"""


def test_render_tab_file_golden_git():
    tab = tool_tab("git", hive="/opt/hive")
    out = render_tab_file(tab)
    assert out.strip() == GIT_TAB_GOLDEN.strip()


_BUNDLED_NAMES = ["teams", "shell", "workflow", "git", "tests", "nvim"]


def test_no_stacks_or_swaps():
    agents = agents_tab(
        n=2, control="right", hive="/opt/hive", labels=["Anton", "Bohdan"]
    )
    outputs = [render_tab_body(agents, indent=1)]
    outputs += [
        render_tab_file(tool_tab(name, hive="/opt/hive")) for name in _BUNDLED_NAMES
    ]
    for out in outputs:
        assert "stacked=" not in out
        assert "swap_" not in out


def test_options_only_in_session_file():
    tab = tool_tab("git", hive="/opt/hive")
    tab_file = render_tab_file(tab)
    assert "stacked_resize" not in tab_file
    assert "auto_layout" not in tab_file

    session = SessionSpec(name="s", tabs=(tab,))
    session_file = render_session_file(session, "/opt/hive")
    assert "stacked_resize false" in session_file
    assert "auto_layout false" in session_file


def test_kdl_string_escapes():
    assert kdl_string('a"b\\c') == '"a\\"b\\\\c"'


def test_shell_pane_has_no_command():
    pane = PaneSpec(name="shell", command=(), cwd="/repo")
    out = render_pane(pane, indent=1)
    assert out == '    pane name="shell" cwd="/repo" {\n    }'
    assert "command" not in out


def test_close_on_exit_rendered():
    pane = PaneSpec(name="p", command=("true",), close_on_exit=True)
    out = render_pane(pane, indent=1)
    assert "close_on_exit true" in out


def test_no_keybinds_block_when_empty():
    session = SessionSpec(name="s", tabs=(), keybinds=KeybindSpec())
    out = render_session_file(session, "/opt/hive")
    assert "keybinds" not in out
