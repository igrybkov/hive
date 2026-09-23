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
# "hive" under the agent pane's column (`pane split_direction="horizontal" {
# c1 hive }`) instead of giving it a separate 30%-wide top-level column -- a
# later design change (PaneSpec.children), not a transcription slip from the
# spec. G4: a fresh agents tab is always one live agent pane, so the tab is
# just that nested container; there is nothing left to rebalance, so
# control="right" gets no swap_tiled_layout at all (`len(t.panes) < 2`).
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
            '        pane split_direction="horizontal" {',
            '            pane name="c1: Anton" {',
            '                command "/usr/bin/env"',
            '                args "HIVE_PANE_ID=1" "HIVE_PANE_LABEL=Anton" '
            '"/opt/hive" "run" "--restart"',
            "            }",
            '            pane name="hive" size="25%" {',
            '                command "/opt/hive"',
            '                args "status" "--watch" "--compact"',
            "            }",
            "        }",
            "    }",
            "}",
            "stacked_resize false",
            "auto_layout true",
            "stacked_pane_list false",
        ]
    )
    + "\n"
)


def test_render_session_golden():
    tab = agents_tab(
        first_id=1, control="right", hive="/opt/hive", label="Anton", focus=True
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


# A flat agents tab (control="none", no nested control-plane pane) -- what the
# session's own agents tab (control_plane "tab"/"none"), `open_tab("agents")`
# and `new_agent_pane`'s fresh-tab branch render. G4: always one live pane,
# plus named swap_tiled_layout presets that Zellij's auto_layout applies by
# pane count when a pane is added (and Alt+[ / Alt+] cycle through by hand):
# `split` (2 agent panes), `grid` (3: two on top, one full-width below),
# `grid-stacked` (4+: same top row, every further pane stacks in the bottom
# slot) and `stacked` (4+: one stack for the whole tab, only reachable by
# hand). The
# counts are 2 higher than the agent panes because Zellij also counts the
# default_tab_template's tab-bar and status-bar plugin panes.
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
            '    swap_tiled_layout name="split" {',
            "        tab exact_panes=4 {",
            '            pane split_direction="vertical" {',
            "                pane",
            "                pane",
            "            }",
            "        }",
            "    }",
            '    swap_tiled_layout name="grid" {',
            "        tab exact_panes=5 {",
            '            pane split_direction="horizontal" {',
            '                pane split_direction="vertical" {',
            "                    pane",
            "                    pane",
            "                }",
            "                pane",
            "            }",
            "        }",
            "    }",
            '    swap_tiled_layout name="grid-stacked" {',
            "        tab min_panes=6 {",
            '            pane split_direction="horizontal" {',
            '                pane split_direction="vertical" {',
            "                    pane",
            "                    pane",
            "                }",
            "                pane stacked=true {",
            "                    children",
            "                }",
            "            }",
            "        }",
            "    }",
            '    swap_tiled_layout name="stacked" {',
            "        tab min_panes=6 {",
            "            pane stacked=true {",
            "                children",
            "            }",
            "        }",
            "    }",
            '    tab name="agents" {',
            '        pane name="c1: Anton" {',
            '            command "/usr/bin/env"',
            '            args "HIVE_PANE_ID=1" "HIVE_PANE_LABEL=Anton" '
            '"/opt/hive" "run" "--restart"',
            "        }",
            "    }",
            "}",
        ]
    )
    + "\n"
)


def test_render_tab_file_golden_flat_agents_swap_layout():
    tab = agents_tab(first_id=1, control="none", hive="/opt/hive", label="Anton")
    out = render_tab_file(tab)
    assert out.strip() == SWAP_TAB_GOLDEN.strip()


def _preset_names(out: str) -> list[str]:
    return re.findall(r'swap_tiled_layout name="([^"]+)"', out)


def test_flat_agents_presets_names_and_order():
    tab = agents_tab(first_id=1, control="none", hive="/opt/hive", label="Anton")
    out = render_tab_file(tab)
    assert _preset_names(out) == ["split", "grid", "grid-stacked", "stacked"]


def test_split_preset_is_exact_panes_4():
    """2 agent panes + the default_tab_template's tab-bar and status-bar
    plugin panes: Zellij counts all four toward `exact_panes`, so a literal
    2 never matches (verified live on Zellij 0.45.1)."""
    out = render_tab_file(
        agents_tab(first_id=1, control="none", hive="/opt/hive", label="")
    )
    assert 'swap_tiled_layout name="split" {\n        tab exact_panes=4' in out


def test_grid_preset_is_exact_panes_5_two_top_one_bottom():
    out = render_tab_file(
        agents_tab(first_id=1, control="none", hive="/opt/hive", label="")
    )
    assert 'swap_tiled_layout name="grid" {\n        tab exact_panes=5' in out
    assert 'pane split_direction="horizontal"' in out
    assert 'pane split_direction="vertical"' in out


def test_grid_stacked_preset_stacks_the_bottom_slot_from_4_agent_panes():
    """The 4th pane joins the third in a stack under the unchanged top row,
    instead of the whole tab flipping to a stack."""
    out = render_tab_file(
        agents_tab(first_id=1, control="none", hive="/opt/hive", label="")
    )
    preset = out[out.index('swap_tiled_layout name="grid-stacked"') :]
    preset = preset[: preset.index('swap_tiled_layout name="stacked"')]
    assert "tab min_panes=6 {" in preset
    assert "exact_panes" not in preset
    top_row = (
        'pane split_direction="vertical" {\n'
        "                    pane\n"
        "                    pane\n"
        "                }"
    )
    assert top_row in preset
    assert "pane stacked=true {\n                    children" in preset


def test_stacked_preset_only_fits_4_or_more_agent_panes():
    """Zellij applies the next fitting preset *after the current one*. An
    unconstrained `stacked` right after `grid-stacked` would win when a 4-pane
    tab shrinks to 3 and flip the whole tab to a stack; with min_panes=6 it
    does not fit 3 agent panes, so the tab falls back to `grid`."""
    out = render_tab_file(
        agents_tab(first_id=1, control="none", hive="/opt/hive", label="")
    )
    stacked = out[out.index('swap_tiled_layout name="stacked"') :]
    assert "tab min_panes=6 {" in stacked
    assert "exact_panes" not in stacked
    assert "max_panes" not in stacked
    assert _preset_names(out)[-1] == "stacked"


def test_control_right_has_no_named_presets():
    """`children` would flatten the nested "hive" pane into an equal sibling,
    so control="right" gets no named cycle presets. With G4's single agent
    pane the tab is just the nested container, so its old unnamed
    exact_panes rebalance preset (a guard: needs >= 2 outer panes) is not
    emitted either -- the nested branch itself is untouched."""
    tab = agents_tab(first_id=1, control="right", hive="/opt/hive", label="Anton")
    out = render_tab_file(tab)
    assert _preset_names(out) == []
    assert "stacked=" not in out


def test_session_file_declares_each_preset_once():
    """Session file with a control tab plus the agents tab: only the agents
    tab yields presets, so each name appears exactly once."""
    control = tool_tab("nvim", hive="/opt/hive")
    agents = agents_tab(
        first_id=1, control="none", hive="/opt/hive", label="", focus=True
    )
    out = render_session_file(
        SessionSpec(name="s", tabs=(control, agents)), "/opt/hive"
    )
    assert _preset_names(out) == ["split", "grid", "grid-stacked", "stacked"]


def test_swap_layout_absent_for_control_bottom():
    """control="bottom" is flat (no nested pane) but "hive" is a plain
    sibling carrying a fixed size="25%" -- an evenly-split preset would be
    wrong for it (it would fight that fixed size every time it re-triggered),
    so this shape renders without a swap_tiled_layout at all."""
    tab = agents_tab(first_id=1, control="bottom", hive="/opt/hive", label="Anton")
    out = render_tab_file(tab)
    assert "swap_" not in out


_BUNDLED_NAMES = ["teams", "shell", "workflow", "git", "tests", "nvim"]


def test_no_stacks_or_swaps():
    agents = agents_tab(first_id=1, control="right", hive="/opt/hive", label="Anton")
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
    assert "stacked_pane_list" not in tab_file

    session = SessionSpec(name="s", tabs=(tab,))
    session_file = render_session_file(session, "/opt/hive")
    assert "stacked_resize false" in session_file
    assert "auto_layout true" in session_file
    assert "stacked_pane_list false" in session_file


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
