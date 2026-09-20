"""Golden tests for hive_cli.mux.zellij.kdl: layout model -> KDL text."""

from __future__ import annotations

import re

from hive_cli.layout.model import KeybindSpec, PaneSpec, SessionSpec, TabSpec
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
#
# Also post-dates the F2 spec's own golden block: control="right" now nests
# "hive" under the *last* agent pane's column (`pane split_direction=
# "horizontal" { c2 hive }`) instead of giving it a separate 30%-wide
# top-level column -- a later design change (PaneSpec.children), not a
# transcription slip from the spec.
#
# Also carries a `swap_tiled_layout`: control="right" nests the last agent
# pane alongside "hive", so Zellij's `exact_panes` constraint counts all
# three real panes (2 agents + hive) even though the outer split only has
# two columns -- the preset mirrors that nesting so it can re-trigger and
# keep those two outer columns even after a close+reopen, same as the flat
# control="none" case, without touching hive's own fixed 25%.
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
            "    swap_tiled_layout {",
            "        tab exact_panes=3 {",
            '            pane split_direction="vertical" {',
            "                pane",
            '                pane split_direction="horizontal" {',
            "                    pane",
            '                    pane size="25%"',
            "                }",
            "            }",
            "        }",
            "    }",
            '    tab name="agents" focus=true {',
            '        pane split_direction="vertical" {',
            '            pane name="c1: Anton" {',
            '                command "/usr/bin/env"',
            '                args "HIVE_PANE_ID=1" "HIVE_PANE_LABEL=Anton" '
            '"/opt/hive" "run" "--restart"',
            "            }",
            '            pane split_direction="horizontal" {',
            '                pane name="c2: Bohdan" {',
            '                    command "/usr/bin/env"',
            '                    args "HIVE_PANE_ID=2" "HIVE_PANE_LABEL=Bohdan" '
            '"/opt/hive" "run" "--restart"',
            "                    start_suspended true",
            "                }",
            '                pane name="hive" size="25%" {',
            '                    command "/opt/hive"',
            '                    args "status" "--watch" "--compact"',
            "                }",
            "            }",
            "        }",
            "    }",
            "}",
            "stacked_resize false",
            "auto_layout true",
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


# A flat, on-demand agents tab (control="none", no nested control-plane
# pane) -- what `open_tab("agents")` and `new_agent_pane`'s fresh-tab branch
# actually render. It carries three named, unconstrained `swap_tiled_layout`
# presets (vertical = side by side, horizontal = top/bottom, stacked) that
# Zellij's Alt+[ / Alt+] cycle through. Order matters: after a pane closes
# and reopens, Zellij re-applies the first preset that fits, so `vertical`
# (the tab's own side-by-side shape) comes first -- that is also what keeps
# the split even, since `new-pane` has no ratio flag of its own. No
# min_panes/max_panes: Zellij's built-in `stacked` needs min_panes=4, which
# would exclude every 2-pane agents tab.
SWAP_TAB_GOLDEN = (
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
            '    swap_tiled_layout name="vertical" {',
            "        tab {",
            '            pane split_direction="vertical" {',
            "                children",
            "            }",
            "        }",
            "    }",
            '    swap_tiled_layout name="horizontal" {',
            "        tab {",
            '            pane split_direction="horizontal" {',
            "                children",
            "            }",
            "        }",
            "    }",
            '    swap_tiled_layout name="stacked" {',
            "        tab {",
            "            pane stacked=true {",
            "                children",
            "            }",
            "        }",
            "    }",
            '    tab name="agents" {',
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
            "        }",
            "    }",
            "}",
        ]
    )
    + "\n"
)


def test_render_tab_file_golden_flat_agents_swap_layout():
    tab = agents_tab(n=2, control="none", hive="/opt/hive", labels=["Anton", "Bohdan"])
    out = render_tab_file(tab)
    assert out.strip() == SWAP_TAB_GOLDEN.strip()


def _preset_names(out: str) -> list[str]:
    return re.findall(r'swap_tiled_layout name="([^"]+)"', out)


def test_swap_layouts_present_for_single_pane_tab():
    """A one-pane agents tab (`n=1`) still carries the cycle presets: the
    tab can grow by a live split, and stacked must be reachable then."""
    tab = agents_tab(n=1, control="none", hive="/opt/hive", labels=["Anton"])
    out = render_tab_file(tab)
    assert _preset_names(out) == ["vertical", "horizontal", "stacked"]


def test_flat_agents_presets_have_no_pane_count_constraints():
    tab = agents_tab(n=2, control="none", hive="/opt/hive", labels=[])
    out = render_tab_file(tab)
    for constraint in ("exact_panes", "min_panes", "max_panes"):
        assert constraint not in out


def test_stacked_base_rotates_presets_to_start_with_stacked():
    """Zellij re-applies the *first* fitting preset after a pane count
    change, so the first one must match the tab's own shape or a close+
    reopen would flip the tab's mode."""
    tab = agents_tab(n=2, control="none", hive="/opt/hive", labels=[], stacked=True)
    out = render_tab_file(tab)
    assert _preset_names(out) == ["stacked", "vertical", "horizontal"]


def test_control_right_keeps_only_the_unnamed_rebalance_preset():
    """`children` would flatten the nested "hive" pane into an equal sibling,
    so control="right" gets no cycle presets -- just its existing preset."""
    tab = agents_tab(n=2, control="right", hive="/opt/hive", labels=["Anton", "Bohdan"])
    out = render_tab_file(tab)
    assert _preset_names(out) == []
    assert "exact_panes=3" in out


def test_session_file_declares_each_preset_once():
    """Session file with a control tab plus the agents tab: only the agents
    tab yields presets, so each name appears exactly once."""
    control = tool_tab("nvim", hive="/opt/hive")
    agents = agents_tab(n=2, control="none", hive="/opt/hive", labels=[], focus=True)
    out = render_session_file(
        SessionSpec(name="s", tabs=(control, agents)), "/opt/hive"
    )
    assert _preset_names(out) == ["vertical", "horizontal", "stacked"]


def test_swap_layout_absent_for_control_bottom():
    """control="bottom" is flat (no nested pane) but "hive" is a plain
    sibling carrying a fixed size="25%" -- an evenly-split preset would be
    wrong for it (it would fight that fixed size every time it re-triggered),
    so this shape renders without a swap_tiled_layout at all."""
    tab = agents_tab(
        n=2, control="bottom", hive="/opt/hive", labels=["Anton", "Bohdan"]
    )
    out = render_tab_file(tab)
    assert "swap_" not in out


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
    assert "auto_layout true" in session_file


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


def test_render_pane_nested_container():
    """A `children`-bearing PaneSpec renders as a nested split container:
    no `name` attribute (Zellij pane names are for leaves), `split_direction`
    from its own `direction`, `size` from its own `size` -- and each child
    indented one level deeper, recursively."""
    container = PaneSpec(
        name="",
        command=(),
        size="40%",
        direction="horizontal",
        children=(
            PaneSpec(name="top", command=("true",)),
            PaneSpec(name="bottom", command=("false",)),
        ),
    )
    out = render_pane(container, indent=1)
    assert out == "\n".join(
        [
            '    pane split_direction="horizontal" size="40%" {',
            '        pane name="top" {',
            '            command "true"',
            "        }",
            '        pane name="bottom" {',
            '            command "false"',
            "        }",
            "    }",
        ]
    )
    assert 'name=""' not in out


def test_render_pane_stacked_container_wins_over_direction():
    """G2: `stacked=True` renders `pane stacked=true { ... }` instead of a
    `split_direction` container, even when `direction` is also set."""
    container = PaneSpec(
        name="",
        command=(),
        direction="horizontal",
        stacked=True,
        children=(
            PaneSpec(name="c1", command=("true",)),
            PaneSpec(name="c2", command=("false",)),
        ),
    )
    out = render_pane(container, indent=1)
    assert out.splitlines()[0] == "    pane stacked=true {"
    assert "split_direction" not in out


def test_render_tab_body_stacked_top_level():
    tab = TabSpec(
        name="agents",
        panes=(
            PaneSpec(name="c1", command=("true",)),
            PaneSpec(name="c2", command=("false",)),
        ),
        stacked=True,
    )
    out = render_tab_body(tab)
    assert "pane stacked=true {" in out
    assert "split_direction" not in out


def test_render_tab_body_not_stacked_by_default():
    tab = TabSpec(
        name="agents",
        panes=(
            PaneSpec(name="c1", command=("true",)),
            PaneSpec(name="c2", command=("false",)),
        ),
    )
    out = render_tab_body(tab)
    assert "stacked=" not in out
