"""Bundled tool tabs and the agent tab for the F2 layout model.

`BUNDLED` transcribes tabs 3-8 of the old `layout/bundled/agent.kdl` (now
`agent-16.kdl`): same names, commands, args, cwd and sizes. The old file
nested splits two levels deep ("4. Shell", "5. Workflow") and used a Zellij
`stacked=true` container ("3. Teams"); those are flattened to a single-level
split here — a deliberate, documented deviation, not an oversight. (A later
change gave `PaneSpec` one level of nesting via `children` -- used only by
`agents_tab`'s control="right" to tuck "hive" under the agent pane -- but
the bundled tool tabs above were deliberately left flat, not revisited.)
"""

from __future__ import annotations

import os
import shlex
from collections.abc import Callable

from ..config.schema import PaneConfig, TabConfig
from ..config.settings import HiveSettings
from ..core.errors import HiveError
from .keybinds import keybind_spec
from .model import PaneSpec, SessionSpec, TabSpec

_TEAM_CMD = (
    "sh -c 'tmux new-session -A -s \"$ZELLIJ_SESSION_NAME-team-{n}-"
    '$(git branch --show-current | tr / -)" '
    '"env CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1 claude --teammate-mode tmux"\''
)


def agents_tab(
    *,
    first_id: int,
    control: str,
    hive: str,
    label: str = "",
    focus: bool = False,
) -> TabSpec:
    """One live agent pane (`first_id`), plus, when control != "none", a
    status column.

    A fresh tab (session bootstrap or on-demand, G4) always starts with
    exactly one agent; the user grows it with Alt+n or opens another tab with
    Alt+Shift+n. An empty `label` gets a bare "cN" name and no
    HIVE_PANE_LABEL.

    With `control="bottom"`, "hive" is a full-width row inserted *before* the
    agent pane, not appended after it: agent panes always sit after it in the
    flat split, so a newly split-in agent pane can never land adjacent to
    "hive" and sandwich it between two agents. Its size is a percentage, not a
    fixed row count, so Zellij can grow it when a sibling closes (a fixed size
    can't, which panics Zellij's screen thread on ClosePane,
    zellij-org/zellij#4880).

    With `control="right"`, "hive" is nested under the agent pane's own
    column (a horizontal split: agent pane on top, "hive" at the bottom)
    rather than getting its own full-height column; the same percentage-size
    rule applies for the same reason.
    """
    env: tuple[tuple[str, str], ...] = (("HIVE_PANE_ID", str(first_id)),)
    if label:
        env += (("HIVE_PANE_LABEL", label),)
    name = f"c{first_id}: {label}" if label else f"c{first_id}"
    agent_pane = PaneSpec(name=name, command=(hive, "run", "--restart"), env=env)

    panes = [agent_pane]
    hive_pane = PaneSpec(
        name="hive",
        command=(hive, "status", "--watch", "--compact"),
        size="25%",
    )
    if control == "bottom":
        panes.insert(0, hive_pane)
    elif control == "right":
        panes[-1] = PaneSpec(
            name="",
            command=(),
            children=(agent_pane, hive_pane),
            direction="horizontal",
        )
    direction = "horizontal" if control == "bottom" else "vertical"
    return TabSpec(
        name="agents",
        panes=tuple(panes),
        direction=direction,
        focus=focus,
    )


def _control_plane_tab(hive: str) -> TabSpec:
    """Dedicated first tab for `control_plane: "tab"`: the status board fills
    the whole tab (no `--compact`, unlike the nested "right"/"bottom" pane,
    which has to share space with an agent pane). Created eagerly alongside
    the agents tab (both ship in the same session file, rendered before
    Zellij ever starts -- there's no lazy on-demand step here) but not
    focused: the agents tab is where a session actually starts working, so
    it's the one active on attach, not this monitoring tab."""
    return TabSpec(
        name="control",
        panes=(PaneSpec(name="hive", command=(hive, "status", "--watch")),),
    )


def _fish(script: str) -> tuple[str, ...]:
    return ("fish", "-c", script)


_TEAM_CMD_TMUX = (
    "env CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1 claude --teammate-mode tmux"
)


def _teams_tab(hive: str, *, backend: str = "zellij") -> TabSpec:
    """Claude teammate mode always runs its own tmux session for its panes.

    Under Zellij that has to be a *nested* private tmux session (name keyed
    off $ZELLIJ_SESSION_NAME + branch, via `_TEAM_CMD`); under the tmux
    backend the pane is already inside the one tmux session hive itself
    manages, so nesting would either be refused ("sessions should be nested
    with care") or just confusing -- run claude directly instead.
    """
    panes = tuple(
        PaneSpec(
            name=f"team-{i}",
            command=(
                "hive",
                "wt",
                "exec",
                "--restart",
                "-w=-",
                "-c",
                _TEAM_CMD_TMUX if backend == "tmux" else _TEAM_CMD.format(n=i),
            ),
            suspended=True,
        )
        for i in range(1, 5)
    )
    return TabSpec(name="teams", panes=panes, direction="horizontal")


def _shell_tab(hive: str) -> TabSpec:
    return TabSpec(
        name="shell",
        direction="vertical",
        panes=(
            PaneSpec(
                name="shell",
                command=_fish("cd (hive wt parent) && exec fish"),
                size="35%",
            ),
            PaneSpec(name="shell-2", command=_fish("cd (hive wt parent) && exec fish")),
            PaneSpec(
                name="watch-logs",
                command=_fish("hive wt exec -c 'watch-logs' --restart -w=-"),
                suspended=True,
            ),
            PaneSpec(name="lazydocker", command=("lazydocker",), suspended=True),
        ),
    )


def _workflow_tab(hive: str) -> TabSpec:
    return TabSpec(
        name="workflow",
        direction="vertical",
        panes=(
            PaneSpec(
                name="diff",
                command=_fish(
                    "cd (hive wt parent) && hive diff --stat && echo '' && "
                    "echo 'Press Enter to see full diff...' && read && hive diff"
                ),
                suspended=True,
            ),
            PaneSpec(
                name="merge-preview",
                command=_fish(
                    "cd (hive wt parent) && "
                    "exec hive merge-preview --watch --interval 5"
                ),
                suspended=True,
            ),
            PaneSpec(
                name="rebase-check",
                command=_fish("cd (hive wt parent) && exec hive rebase-check --fetch"),
                suspended=True,
            ),
            PaneSpec(
                name="tasks",
                command=_fish(
                    "cd (hive wt parent) && exec hive task --watch --interval 5"
                ),
                suspended=True,
            ),
        ),
    )


def _git_tab(hive: str) -> TabSpec:
    return TabSpec(
        name="git",
        direction="horizontal",
        panes=(
            PaneSpec(
                name="lazygit",
                command=_fish("cd (hive wt parent) && exec lazygit"),
                size="70%",
                suspended=True,
            ),
            PaneSpec(
                name="git-shell", command=_fish("cd (hive wt parent) && exec fish")
            ),
        ),
    )


def _tests_tab(hive: str) -> TabSpec:
    return TabSpec(
        name="tests",
        panes=(
            PaneSpec(
                name="watch-tests",
                command=_fish(
                    "hive wt exec -c 'watch-tests' "
                    "--restart --restart-confirmation -w=-"
                ),
                suspended=True,
            ),
        ),
    )


def _nvim_tab(hive: str) -> TabSpec:
    return TabSpec(
        name="nvim",
        panes=(
            PaneSpec(
                name="neovim",
                command=_fish("hive wt exec -c 'nvim' --restart -w=-"),
            ),
        ),
    )


BUNDLED: dict[str, Callable[[str], TabSpec]] = {
    "teams": _teams_tab,
    "shell": _shell_tab,
    "workflow": _workflow_tab,
    "git": _git_tab,
    "tests": _tests_tab,
    "nvim": _nvim_tab,
}


def _pane_from_config(p: PaneConfig) -> PaneSpec:
    command = p.command
    if isinstance(command, str):
        command = shlex.split(command)
    return PaneSpec(
        name=p.name,
        command=tuple(command),
        cwd=p.cwd,
        size=p.size,
        suspended=p.suspended,
    )


def _tab_from_config(name: str, config: TabConfig) -> TabSpec:
    return TabSpec(name=name, panes=tuple(_pane_from_config(p) for p in config.panes))


def tool_tab(name: str, *, hive: str, backend: str = "zellij") -> TabSpec:
    """Bundled tool tabs by name; raises HiveError for an unknown name.

    `backend` only matters to "teams" (see `_teams_tab`); every other
    bundled tab ignores it.
    """
    if name not in BUNDLED:
        raise HiveError(f"unknown tab: {name}")
    if name == "teams":
        return _teams_tab(hive, backend=backend)
    return BUNDLED[name](hive)


def resolve_tab(
    name: str, *, hive: str, user_tabs: dict[str, TabConfig], backend: str = "zellij"
) -> TabSpec:
    """User `tabs:` win over bundled names."""
    if name in user_tabs:
        return _tab_from_config(name, user_tabs[name])
    return tool_tab(name, hive=hive, backend=backend)


def session_spec(*, name: str, hive: str, settings: HiveSettings) -> SessionSpec:
    """One agent pane plus a status column, plus keybinds.

    `control_plane: "tab"` renders two tabs instead of one, both created
    right away in the same session file (no on-demand step): a dedicated
    "control" tab first, then the agents tab (built with `control="none"`,
    since the status board no longer shares its space) -- the agents tab is
    the one focused on attach, since that's where a session actually starts
    working, not the monitoring tab. Every other `control_plane` value keeps
    the single-tab shape, the status board (if any) nested inside the agents
    tab itself.
    """
    dedicated_control = settings.zellij.control_plane == "tab"
    agents = agents_tab(
        first_id=1,
        control="none" if dedicated_control else settings.zellij.control_plane,
        hive=hive,
        label=settings.zellij.pane_labels[0] if settings.zellij.pane_labels else "",
        focus=True,
    )
    tabs = (_control_plane_tab(hive), agents) if dedicated_control else (agents,)
    shell = settings.zellij.floating_shell_command or os.environ.get("SHELL", "/bin/sh")
    keybinds = keybind_spec(settings.zellij.keybinds, hive=hive, shell=shell)
    return SessionSpec(name=name, tabs=tabs, keybinds=keybinds)
