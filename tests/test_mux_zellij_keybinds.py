"""Golden tests for hive_cli.mux.zellij.keybinds: KeybindSpec -> KDL text."""

from __future__ import annotations

from hive_cli.config.schema import KeybindsConfig
from hive_cli.layout.keybinds import keybind_spec
from hive_cli.layout.model import KeybindSpec, SessionSpec
from hive_cli.mux.zellij.kdl import render_session_file
from hive_cli.mux.zellij.keybinds import render

GOLDEN = """\
keybinds {
    shared_except "locked" {
        bind "Alt n" {
            Run "/opt/hive" "pane" "new" {
                floating true
                close_on_exit true
            }
        }
        bind "Alt Shift a" {
            Run "/opt/hive" "tab" "agents" {
                floating true
                close_on_exit true
            }
        }
        bind "Alt Shift s" {
            Run "/opt/hive" "wt" "exec" "--here" "--" "/bin/zsh" {
                floating true
                name "shell"
                close_on_exit true
            }
        }
        bind "Alt m" {
            Run "/opt/hive" "status" "--toggle" {
                floating true
                name "hive"
                close_on_exit true
                width "80%"
                height "80%"
            }
        }
        bind "Alt Shift w" {
            Run "/opt/hive" "wt" "exec" "--worktree" "-" "--" "/bin/zsh" {
                floating true
                name "shell"
                close_on_exit true
            }
        }
    }
}"""


def test_render_golden():
    spec = keybind_spec(KeybindsConfig(), hive="/opt/hive", shell="/bin/zsh")
    assert render(spec) == GOLDEN


def test_render_empty_spec_is_empty_string():
    assert render(KeybindSpec()) == ""


def test_no_clear_defaults():
    spec = keybind_spec(KeybindsConfig(), hive="/opt/hive", shell="/bin/zsh")
    assert "clear-defaults" not in render(spec)


def test_session_file_includes_keybinds():
    spec = keybind_spec(KeybindsConfig(), hive="/opt/hive", shell="/bin/zsh")
    session = SessionSpec(name="s", tabs=(), keybinds=spec)
    out = render_session_file(session, "/opt/hive")
    assert out.rstrip("\n").endswith(GOLDEN)
