"""Configuration schema definitions using Pydantic.

Note: Default values come from default.yml which ships with the package.
Pydantic model defaults here are only used as fallbacks during parsing.
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import SettingsConfigDict

from .base import HiveBaseSettings


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


class AgentConfig(BaseModel):
    """Configuration for a specific AI coding agent.

    Attributes:
        resume_args: Arguments to add for resume functionality.
        skip_permissions_args: Arguments to add for skip-permissions mode.
        extra_args: Arguments always appended to the agent command.
        extra_dirs_flag: CLI flag the agent uses for additional directories
            (e.g., "--add-dir" for Claude, "--directory" for Cursor).
        profile: Config-dir profile support configuration.
    """

    resume_args: Annotated[list[str], Field(default_factory=list)]
    skip_permissions_args: Annotated[list[str], Field(default_factory=list)]
    extra_args: Annotated[list[str], Field(default_factory=list)]
    extra_dirs_flag: str | None = None
    profile: AgentProfileConfig | None = None


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

    @field_validator("post_create", mode="before")
    @classmethod
    def normalize_post_create(cls, v: Any) -> Any:
        """Normalize post_create entries: strings become {"command": str}."""
        if isinstance(v, list):
            return [{"command": item} if isinstance(item, str) else item for item in v]
        return v


class ZellijConfig(HiveBaseSettings):
    """Configuration for Zellij terminal multiplexer.

    Attributes:
        layout: Layout to use, resolved by `utils.layouts.resolve_layout()`.
            Accepts three forms: the name of a layout bundled with this package
            (currently just "agent", the multi-agent layout — resolves to its
            packaged path), the name of a layout in Zellij's own layout dir
            (~/.config/zellij/layouts/, passed through as-is), or an explicit
            path / anything ending in ".kdl" (expanded via `~`). Defaults to
            "agent". Set to None to use Zellij's built-in default layout.
        session_name: Session name template.
    """

    model_config = SettingsConfigDict(env_prefix="HIVE_ZELLIJ_")

    layout: str | None = "agent"
    session_name: str = "{repo}"


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
    """

    agents: Annotated[AgentsConfig, Field(default_factory=AgentsConfig)]
    resume: Annotated[ResumeConfig, Field(default_factory=ResumeConfig)]
    worktrees: Annotated[WorktreesConfig, Field(default_factory=WorktreesConfig)]
    zellij: Annotated[ZellijConfig, Field(default_factory=ZellijConfig)]
    github: Annotated[GitHubConfig, Field(default_factory=GitHubConfig)]
    extra_dirs: Annotated[list[str], Field(default_factory=list)]
