"""Maps the five on-demand actions to the `KeybindSpec` the mux renderer needs.

Each enabled action becomes one binding: a Zellij key, the `hive` argv `Run`
should launch, and the Run-block options (`close_on_exit`, `floating`,
`name`, `width`, `height`) `mux/zellij/keybinds.py` turns into body lines. A
key set to `None` disables just that binding; `cfg.enabled = False` disables
all of them (`KeybindSpec()`, which renders no `keybinds` block at all).
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass

from ..config.schema import KeybindsConfig
from .model import KeybindSpec

ACTIONS: tuple[str, ...] = (
    "new_agent_pane",
    "new_agent_tab",
    "floating_shell",
    "control_plane",
    "worktree_shell",
)


@dataclass(frozen=True)
class Keybind:
    # new_agent_pane | new_agent_tab | floating_shell | control_plane | worktree_shell
    action: str
    key: str  # zellij syntax: "Alt a", "Alt Shift s"


def _binding(
    action: str, *, hive: str, shell: str
) -> tuple[tuple[str, ...], dict[str, str | bool]]:
    if action == "new_agent_pane":
        # floating, not tiled: `hive pane new` itself creates the real agent
        # pane via a separate mux call (split or new tab) -- if *this*
        # runner pane were tiled too, it would briefly become a third pane
        # in the target tab (Zellij has to give it some space before
        # `close_on_exit` removes it again), and closing it back out is a
        # second pane-count change that doesn't reliably restore an even
        # split (confirmed live: this is what produced the transient
        # "thirds, then 1/3 + 2/3" behavior, not the split itself).
        return (hive, "pane", "new"), {"floating": True, "close_on_exit": True}
    if action == "new_agent_tab":
        return (hive, "tab", "agents"), {"floating": True, "close_on_exit": True}
    if action == "floating_shell":
        argv = (hive, "wt", "exec", "--here", "--", *shlex.split(shell))
        return argv, {"floating": True, "name": "shell", "close_on_exit": True}
    if action == "control_plane":
        return (hive, "status", "--toggle"), {
            "floating": True,
            "name": "hive",
            "close_on_exit": True,
            "width": "80%",
            "height": "80%",
        }
    if action == "worktree_shell":
        argv = (hive, "wt", "exec", "--worktree", "-", "--", *shlex.split(shell))
        return argv, {"floating": True, "name": "shell", "close_on_exit": True}
    raise ValueError(f"unknown keybind action: {action}")


def keybind_spec(cfg: KeybindsConfig, *, hive: str, shell: str) -> KeybindSpec:
    """Enabled actions with a configured key, in `ACTIONS` order; empty if disabled."""
    if not cfg.enabled:
        return KeybindSpec()
    bindings = []
    for action in ACTIONS:
        key = getattr(cfg, action)
        if not key:
            continue
        argv, opts = _binding(action, hive=hive, shell=shell)
        bindings.append((key, argv, opts))
    return KeybindSpec(bindings=tuple(bindings))
