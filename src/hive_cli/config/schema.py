"""Configuration schema definitions using Pydantic.

Note: Default values come from default.yml which ships with the package.
Pydantic model defaults here are only used as fallbacks during parsing.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import SettingsConfigDict

from .base import HiveBaseSettings

# Kept in sync with state/session_layout.py:AGENTS_LAYOUTS by hand -- config
# and state are sibling layer-1 packages (see docs/ARCHITECTURE.md), so
# neither may import the other; duplicating this 3-tuple is cheaper than
# adding a shared module for one constant.
_AGENTS_LAYOUTS = ("split", "stacked", "tabs")


class AgentProfileConfig(BaseModel):
    """Configuration for per-agent config-dir profiles.

    When a named profile is selected (e.g. "work"), the agent's config home is
    redirected to ``$XDG_CONFIG_HOME/hive/profiles/<agent>/<profile>/`` by
    setting ``config_dir_env``.  ``extra_env`` holds additional vars that must
    be set for that profile to fully isolate credentials (e.g.
    ``GEMINI_FORCE_FILE_STORAGE`` for gemini).  ``seed_files`` names files that
    are written into the profile directory on first creation but never
    overwritten afterward (e.g. codex ``config.toml`` to force file-based auth).

    Attributes:
        config_dir_env: Env var that points the agent at a custom config home.
        extra_env: Extra env vars set only when a named profile is active.
        seed_files: Mapping of filename → contents, written once on profile
            creation (skipped if the file already exists).
    """

    config_dir_env: str | None = None
    extra_env: Annotated[dict[str, str], Field(default_factory=dict)]
    seed_files: Annotated[dict[str, str], Field(default_factory=dict)]


class AgentHooksConfig(BaseModel):
    """How (if at all) an agent's own hook mechanism can be wired to `hive-hook`.

    Attributes:
        mode: "cli" injects hook config via a CLI flag on every launch
            (Claude's `--settings`, Codex's `-c notify=...`). "profile" merges
            hook config into the agent's hive-managed profile directory
            (Gemini's `.gemini/settings.json`) -- never the user's real config.
            "unsupported" means hive does not wire hooks for this agent.
        note: Short caveat shown alongside the mode (e.g. what "cli" replaces,
            or why the agent is unsupported).
    """

    mode: Literal["cli", "profile", "unsupported"] = "unsupported"
    note: str | None = None


class AgentConfig(BaseModel):
    """Configuration for a specific AI coding agent.

    Attributes:
        resume_args: Arguments to add for resume functionality.
        skip_permissions_args: Arguments to add for skip-permissions mode.
        extra_args: Arguments always appended to the agent command.
        extra_dirs_flag: CLI flag the agent uses for additional directories
            (e.g., "--add-dir" for Claude, "--directory" for Cursor).
        profile: Config-dir profile support configuration.
        hooks: How hive wires this agent's hook mechanism to `hive-hook`.
    """

    resume_args: Annotated[list[str], Field(default_factory=list)]
    skip_permissions_args: Annotated[list[str], Field(default_factory=list)]
    extra_args: Annotated[list[str], Field(default_factory=list)]
    extra_dirs_flag: str | None = None
    profile: AgentProfileConfig | None = None
    hooks: Annotated[AgentHooksConfig, Field(default_factory=AgentHooksConfig)]


class AgentsConfig(HiveBaseSettings):
    """Configuration for AI coding agents.

    Attributes:
        order: Priority order for agent detection.
        configs: Per-agent configuration.
    """

    model_config = SettingsConfigDict(env_prefix="HIVE_AGENTS_")

    order: Annotated[list[str], Field(default_factory=list)]
    configs: Annotated[dict[str, AgentConfig], Field(default_factory=dict)]


class ResumeConfig(HiveBaseSettings):
    """Configuration for resume behavior.

    Attributes:
        enabled: Whether --resume flag is enabled by default.
    """

    model_config = SettingsConfigDict(env_prefix="HIVE_RESUME_")

    enabled: bool = False


class PostCreateCommand(BaseModel):
    """A command to run after creating a worktree.

    Attributes:
        command: Shell command to run.
        if_exists: Only run if this file exists in the worktree.
    """

    command: str
    if_exists: str | None = None


class AutoSelectConfig(BaseModel):
    """Configuration for auto-selecting a branch in worktree picker.

    When enabled, the worktree picker will automatically select the specified
    branch after a timeout. Any keypress cancels the timer, allowing users
    to still access agent selection (Ctrl+A) and other UI features.

    Attributes:
        enabled: Whether auto-select is enabled.
        branch: Branch to auto-select. Use "-" for repo's default branch.
        timeout: Seconds before auto-selection (0 for instant).
    """

    enabled: bool = False
    branch: str = "-"
    timeout: float = 3.0


class WorktreesConfig(HiveBaseSettings):
    """Configuration for git worktrees.

    The parent_dir supports ~ expansion and placeholders:
      {repo}   - expands to a name derived from the repo's path relative to
                 home (e.g., Projects--dotfiles for ~/Projects/dotfiles).
      {branch} - expands to the sanitized branch name.

    When both {repo} and {branch} are in parent_dir the entire string is
    used as the full worktree path template.
    When only {repo} is present the branch is appended as a subdirectory.
    When neither is present the flat format {repo}--{branch} is appended.

    Attributes:
        enabled: Whether worktrees feature is enabled.
        auto_select: Auto-select configuration for worktree picker.
        parent_dir: Directory for worktrees. Supports ~, {repo}, {branch}.
        post_create: Commands to run after creating a worktree.
        copy_files: Files to copy from main repo to worktree.
        symlink_files: Files to symlink from main repo to worktree.
        resume: Default --resume flag for worktree sessions.
        skip_permissions: Default --skip-permissions flag for worktree sessions.
        fetch_interval: Seconds between `git fetch origin` runs started by the
            worktree picker (throttled on .git/FETCH_HEAD's age).
    """

    model_config = SettingsConfigDict(env_prefix="HIVE_WORKTREES_")

    enabled: bool = True
    auto_select: Annotated[AutoSelectConfig, Field(default_factory=AutoSelectConfig)]
    parent_dir: str = "~/.worktrees/{repo}/{branch}"
    post_create: Annotated[list[PostCreateCommand], Field(default_factory=list)]
    copy_files: Annotated[list[str], Field(default_factory=list)]
    symlink_files: Annotated[list[str], Field(default_factory=list)]
    resume: bool = False
    skip_permissions: bool = False
    fetch_interval: float = 300.0

    @field_validator("post_create", mode="before")
    @classmethod
    def normalize_post_create(cls, v: Any) -> Any:
        """Normalize post_create entries: strings become {"command": str}."""
        if isinstance(v, list):
            return [{"command": item} if isinstance(item, str) else item for item in v]
        return v


class KeybindsConfig(BaseModel):
    """Hotkeys shipped inside the rendered "agent" session file.

    A key set to None disables that one binding; `enabled: false` disables
    all of them. Zellij key syntax: "Alt a", "Alt Shift s".

    Attributes:
        enabled: Master switch for all keybinds below.
        new_agent_pane: Split-or-tab a new agent pane (`hive pane new`).
            Defaults to `Alt n`, replacing Zellij's own default "new pane"
            binding for the life of the session -- the one deliberate
            exception to this layout never overriding a default Zellij key.
        new_agent_tab: Open a new agents tab (`hive tab agents`).
        floating_shell: Floating shell in the current worktree (`hive wt exec --here`).
        control_plane: Toggle the floating control-plane board (`hive status --toggle`).
        worktree_shell: Floating shell in a picked worktree (`hive wt exec -w -`).
    """

    enabled: bool = True
    new_agent_pane: str | None = "Alt n"
    new_agent_tab: str | None = "Alt Shift a"
    floating_shell: str | None = "Alt Shift s"
    control_plane: str | None = "Alt m"
    worktree_shell: str | None = "Alt Shift w"


class ZellijConfig(HiveBaseSettings):
    """Configuration for Zellij terminal multiplexer.

    Attributes:
        layout: Layout to use, resolved by `layout.resolve.resolve_layout()`.
            Accepts three forms: the name of a layout bundled with this package
            (currently just "agent", the multi-agent layout — resolves to its
            packaged path), the name of a layout in Zellij's own layout dir
            (~/.config/zellij/layouts/, passed through as-is), or an explicit
            path / anything ending in ".kdl" (expanded via `~`). Defaults to
            "agent". Set to None to use Zellij's built-in default layout.
        session_name: Session name template.
        pane_labels: Names for agent panes c1..c16, in the order of the
            bundled layout (`c1: Anton` -> "Anton"). A `hive run` started on
            demand (outside the layout) takes the first free pane number and
            its label from this list.
        pane_label_pool: Fallback names for on-demand pane numbers beyond
            `pane_labels` (c17, c18, ...). One is picked at random, excluding
            any name already in use by a live or pending pane, so opening
            many more agents than `pane_labels` has entries still gets real
            names instead of a bare "c17"; only every name in both lists
            being simultaneously in use falls back to that.
        agents_per_tab: Agent panes in the rendered "agent" layout's tab (1 or 2).
        control_plane: Where the `hive status --watch` board lives: "right"
            or "bottom" nest a `--compact` pane into the agents tab; "none"
            omits it; "tab" gives it its own dedicated first tab (full,
            uncompacted) with the agents tab starting at tab 2.
        agents_layout: Starting arrangement for on-demand agent panes: "split"
            (side by side, the default), "stacked" (Zellij pane stacking), or
            "tabs" (never split -- once idle slots run out, every further
            agent opens a new tab, regardless of agents_per_tab). Switchable
            live for the rest of the session with the control plane's `L`
            hotkey or `hive pane layout <mode>`; this is just where a fresh
            session starts.
        keybinds: Hotkeys shipped inside the rendered session file.
        floating_shell_command: Command the floating-shell and
            worktree-shell hotkeys run; None uses `$SHELL`.
    """

    model_config = SettingsConfigDict(env_prefix="HIVE_ZELLIJ_")

    layout: str | None = "agent"
    session_name: str = "{repo}"
    agents_per_tab: int = 2
    control_plane: str = "tab"
    agents_layout: str = "split"
    keybinds: Annotated[KeybindsConfig, Field(default_factory=KeybindsConfig)]
    floating_shell_command: str | None = None
    pane_labels: list[str] = [
        "Anton",
        "Bohdan",
        "Chris",
        "Dmytro",
        "Emily",
        "Frank",
        "Grygoriy",
        "Henry",
        "Ihor",
        "Jake",
        "Kateryna",
        "Liam",
        "Mykola",
        "Noah",
        "Orest",
        "Petro",
    ]
    pane_label_pool: list[str] = [
        # Ukrainian (Ukrainian forms, not Russian ones -- Volodymyr not
        # Vladimir, Oleksandr not Alexander, Olena not Elena, ...)
        "Andriy",
        "Vasyl",
        "Yuriy",
        "Pavlo",
        "Mykhailo",
        "Oleh",
        "Taras",
        "Nazar",
        "Yevhen",
        "Ostap",
        "Sviatoslav",
        "Stepan",
        "Roman",
        "Yaroslav",
        "Viktor",
        "Maksym",
        "Denys",
        "Artem",
        "Kyrylo",
        "Oleksiy",
        "Oleksandr",
        "Serhiy",
        "Volodymyr",
        "Anatoliy",
        "Ivan",
        "Vitaliy",
        "Ruslan",
        "Zenon",
        "Lev",
        "Olena",
        "Olha",
        "Oksana",
        "Solomiya",
        "Yaroslava",
        "Daryna",
        # American
        "Ethan",
        "Mason",
        "Logan",
        "Lucas",
        "Jack",
        "Owen",
        "Wyatt",
        "Caleb",
        "Ryan",
        "Tyler",
        "Cody",
        "Blake",
        "Dylan",
        "Austin",
        "Cole",
        "Chase",
        "Trevor",
        "Brett",
        "Shane",
        "Derek",
        "Kyle",
        "Brandon",
        "Justin",
        "Corey",
        "Grant",
        "Miles",
        "Seth",
        "Grace",
        "Chloe",
        "Hazel",
        "Ivy",
        "Lily",
        "Ruby",
        "Nora",
        "Sadie",
    ]

    @field_validator("agents_per_tab")
    @classmethod
    def validate_agents_per_tab(cls, v: int) -> int:
        if v not in (1, 2):
            raise ValueError("zellij.agents_per_tab must be 1 or 2")
        return v

    @field_validator("control_plane")
    @classmethod
    def validate_control_plane(cls, v: str) -> str:
        if v not in ("right", "bottom", "none", "tab"):
            raise ValueError("zellij.control_plane must be right, bottom, none, or tab")
        return v

    @field_validator("agents_layout")
    @classmethod
    def validate_agents_layout(cls, v: str) -> str:
        if v not in _AGENTS_LAYOUTS:
            raise ValueError(
                f"zellij.agents_layout must be one of {', '.join(_AGENTS_LAYOUTS)}"
            )
        return v


class MuxConfig(HiveBaseSettings):
    """Which terminal multiplexer backend `hive session` (and `get_mux()`) uses.

    Attributes:
        backend: "auto" picks Zellij inside a Zellij session (`ZELLIJ` set),
            tmux inside a tmux session (`TMUX` set), else neither; "zellij"
            or "tmux" force that backend regardless of environment.
    """

    model_config = SettingsConfigDict(env_prefix="HIVE_MUX_")

    backend: Literal["auto", "zellij", "tmux"] = "auto"


class PaneConfig(BaseModel):
    """A single pane in a user-defined `tabs:` entry.

    Attributes:
        name: Pane name shown in the Zellij tab bar.
        command: Argv to run in the pane. A string is split with
            `shlex.split`; empty ("" or []) makes a plain shell pane.
        cwd: Working directory for the pane.
        size: Zellij pane size ("30%" or "20" cells).
        suspended: Start the pane suspended (Enter to launch).
    """

    name: str
    command: str | list[str] = ""
    cwd: str | None = None
    size: str | None = None
    suspended: bool = False


class TabConfig(BaseModel):
    """A user-defined tool tab, overriding or adding to `layout.tabs.BUNDLED`.

    Attributes:
        panes: Panes making up the tab.
    """

    panes: Annotated[list[PaneConfig], Field(default_factory=list)]


class HooksConfig(HiveBaseSettings):
    """Configuration for agent lifecycle hooks.

    Attributes:
        enabled: When true, hive injects hook wiring per launch (or into a
            named profile) so agent lifecycle events reach the pane socket.
    """

    model_config = SettingsConfigDict(env_prefix="HIVE_HOOKS_")

    enabled: bool = False


class GitHubConfig(HiveBaseSettings):
    """Configuration for GitHub integration.

    Attributes:
        fetch_issues: Whether to fetch GitHub issues.
        issue_limit: Maximum number of issues to fetch.
    """

    model_config = SettingsConfigDict(env_prefix="HIVE_GITHUB_")

    fetch_issues: bool = True
    issue_limit: int = 20


class HiveConfig(BaseModel):
    """Root configuration for Hive CLI.

    Kept as BaseModel for backward compatibility. HiveSettings replaces this
    as the primary settings entrypoint.

    Attributes:
        agents: Agent detection and configuration.
        resume: Resume behavior configuration.
        worktrees: Git worktree configuration.
        zellij: Zellij configuration.
        github: GitHub integration configuration.
        extra_dirs: Additional directories to pass to the agent.
            Relative paths are resolved against the main repo root.
        tabs: User-defined tool tabs, keyed by name (override or add to
            `layout.tabs.BUNDLED`).
        hooks: Agent lifecycle hooks configuration.
    """

    agents: Annotated[AgentsConfig, Field(default_factory=AgentsConfig)]
    resume: Annotated[ResumeConfig, Field(default_factory=ResumeConfig)]
    worktrees: Annotated[WorktreesConfig, Field(default_factory=WorktreesConfig)]
    zellij: Annotated[ZellijConfig, Field(default_factory=ZellijConfig)]
    tabs: Annotated[dict[str, TabConfig], Field(default_factory=dict)]
    github: Annotated[GitHubConfig, Field(default_factory=GitHubConfig)]
    extra_dirs: Annotated[list[str], Field(default_factory=list)]
    hooks: Annotated[HooksConfig, Field(default_factory=HooksConfig)]
