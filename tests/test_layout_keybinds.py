"""Tests for hive_cli.layout.keybinds: config -> KeybindSpec bindings."""

from __future__ import annotations

from hive_cli.config.schema import KeybindsConfig
from hive_cli.layout.keybinds import keybind_spec


def _keys(spec):
    return [key for key, _argv, _opts in spec.bindings]


def test_defaults_produce_five_bindings():
    spec = keybind_spec(KeybindsConfig(), hive="/opt/hive", shell="/bin/zsh")
    assert _keys(spec) == [
        "Alt n",
        "Alt Shift n",
        "Alt Shift s",
        "Alt m",
        "Alt Shift w",
    ]


def test_disabled_produces_no_bindings():
    spec = keybind_spec(
        KeybindsConfig(enabled=False), hive="/opt/hive", shell="/bin/zsh"
    )
    assert spec.bindings == ()


def test_one_key_null_drops_just_that_binding():
    spec = keybind_spec(
        KeybindsConfig(control_plane=None), hive="/opt/hive", shell="/bin/zsh"
    )
    assert _keys(spec) == ["Alt n", "Alt Shift n", "Alt Shift s", "Alt Shift w"]


def test_custom_keys_pass_through():
    spec = keybind_spec(
        KeybindsConfig(new_agent_pane="Ctrl a"), hive="/opt/hive", shell="/bin/zsh"
    )
    assert _keys(spec)[0] == "Ctrl a"


def test_new_agent_pane_argv_and_opts():
    """Floating, not tiled: the runner pane itself must never become a
    third tiled pane in the target tab -- confirmed live, a briefly-tiled
    runner is what corrupts the agents-tab split ratio, not the actual
    agent-pane split/new-tab call `hive pane new` goes on to make."""
    spec = keybind_spec(KeybindsConfig(), hive="/opt/hive", shell="/bin/zsh")
    _key, argv, opts = spec.bindings[0]
    assert argv == ("/opt/hive", "pane", "new")
    assert opts == {"floating": True, "close_on_exit": True}


def test_floating_shell_splits_multi_word_command():
    spec = keybind_spec(KeybindsConfig(), hive="/opt/hive", shell="tmux new-session -A")
    _key, argv, opts = spec.bindings[2]
    assert argv == (
        "/opt/hive",
        "wt",
        "exec",
        "--here",
        "--",
        "tmux",
        "new-session",
        "-A",
    )
    assert opts == {"floating": True, "name": "shell", "close_on_exit": True}


def test_control_plane_argv_and_opts():
    spec = keybind_spec(KeybindsConfig(), hive="/opt/hive", shell="/bin/zsh")
    _key, argv, opts = spec.bindings[3]
    assert argv == ("/opt/hive", "status", "--toggle")
    assert opts == {
        "floating": True,
        "name": "hive",
        "close_on_exit": True,
        "width": "80%",
        "height": "80%",
    }


def test_worktree_shell_argv_and_opts():
    spec = keybind_spec(KeybindsConfig(), hive="/opt/hive", shell="/bin/zsh")
    key, argv, opts = spec.bindings[4]
    assert key == "Alt Shift w"
    assert argv == ("/opt/hive", "wt", "exec", "--worktree", "-", "--", "/bin/zsh")
    assert opts == {"floating": True, "name": "shell", "close_on_exit": True}
