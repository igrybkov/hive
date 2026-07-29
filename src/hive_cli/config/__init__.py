"""Hive CLI configuration module.

Configuration is loaded from YAML files with the following precedence
(highest to lowest):

1. Environment variables (HIVE_* prefix, e.g., HIVE_AGENTS_ORDER)
2. .hive.local.yml (local overrides, git-ignored)
3. .hive.yml (project config, version-controlled)
4. $XDG_CONFIG_HOME/hive/hive.yml (global user config)
5. Package default config (default.yml)

Environment Variables:
    HIVE_AGENTS_ORDER         - Comma-separated list of agents, e.g., 'claude,gemini'
    HIVE_RESUME_ENABLED       - Enable resume by default (true/false)
    HIVE_WORKTREES_ENABLED    - Enable worktrees feature (true/false)
    HIVE_WORKTREES_PARENT_DIR - Directory for worktrees (supports {repo}, {branch})
    HIVE_WORKTREES_RESUME     - Resume default for worktrees (true/false)
    HIVE_ZELLIJ_LAYOUT        - Zellij layout name
    HIVE_ZELLIJ_SESSION_NAME  - Session name template
    HIVE_GITHUB_FETCH_ISSUES  - Fetch GitHub issues (true/false)
    HIVE_GITHUB_ISSUE_LIMIT   - Max issues to fetch (integer)

Usage:
    from hive_cli.config import get_settings, get_runtime_settings

    settings = get_settings()
    print(settings.agents.order)
    print(settings.worktrees.parent_dir)

    rt = get_runtime_settings()
    print(rt.agent)
    print(rt.editor)
"""

from pathlib import Path

from .base import HiveBaseSettings
from .defaults import KNOWN_AGENTS
from .loader import (
    CONFIG_FILE,
    GLOBAL_CONFIG_DIR,
    GLOBAL_CONFIG_FILES,
    LOCAL_CONFIG_FILE,
    find_config_files,
    find_git_root,
    find_global_config,
    get_xdg_config_home,
    load_default_config,
    load_yaml_file,
)
from .merge import deep_merge
from .runtime import RuntimeSettings, get_runtime_settings
from .schema import (
    AgentConfig,
    AgentProfileConfig,
    AgentsConfig,
    GitHubConfig,
    HiveConfig,
    PostCreateCommand,
    ResumeConfig,
    WorktreesConfig,
    ZellijConfig,
)
from .settings import HiveSettings, MergedYamlSource, get_settings, reset_settings

# Backward-compatible constants
ENV_HIVE_AGENT = "HIVE_AGENT"


# --- Backward-compatible wrappers ---


def load_config() -> HiveSettings:
    """Load configuration (backward-compatible wrapper).

    Returns HiveSettings (which has the same field names as HiveConfig).
    """
    return get_settings()


def _load_config_cache_clear() -> None:
    """Clear settings cache (backward compat for load_config.cache_clear()).

    Resets the singleton so the next load_config() call creates fresh settings.
    """
    reset_settings()


# Attach cache_clear for backward compat with lru_cache API
load_config.cache_clear = _load_config_cache_clear  # type: ignore[attr-defined]


def reload_config() -> HiveSettings:
    """Force reload of configuration (backward-compatible wrapper).

    Clears YAML cache, re-reads env vars, returns fresh settings.
    """
    settings = get_settings()
    settings.reload()
    return settings


def get_agent_config(agent_name: str) -> AgentConfig:
    """Get configuration for a specific agent.

    Args:
        agent_name: Name of the agent.

    Returns:
        AgentConfig for the agent, or default config if not found.
    """
    settings = get_settings()
    return settings.agents.configs.get(agent_name, AgentConfig())


def get_agent_order() -> list[str]:
    """Get agent priority order.

    Uses configuration from .hive.yml/.hive.local.yml files,
    falling back to defaults.

    Returns:
        List of agent names in priority order.
    """
    settings = get_settings()
    return settings.agents.order


def get_profiles_root() -> Path:
    """Return the root directory for per-agent config profiles.

    Profiles live at ``<root>/<agent>/<profile>/`` and are passed to the agent
    via its ``config_dir_env``.  The default is ``$XDG_CONFIG_HOME/hive/profiles``
    which can be overridden by a ``profiles.root`` key in hive.yml (not yet in
    schema — reserved for future extension).

    Returns:
        Path to the profiles root directory.
    """
    xdg = get_xdg_config_home()
    return xdg / "hive" / "profiles"


def resolve_profile_env(agent_name: str, profile_name: str | None) -> dict[str, str]:
    """Build env-var overrides for the given agent + profile combination.

    Returns an empty dict when:
    - ``profile_name`` is None or empty (``<default>`` passthrough semantics).
    - The agent has no ``profile`` config or no ``config_dir_env`` declared.

    When a named profile IS active, returns a dict containing at minimum
    ``{config_dir_env: <profiles_root>/<agent>/<profile>}`` and any
    ``extra_env`` entries declared in the agent's profile config.

    Args:
        agent_name: Name of the agent (e.g. ``"claude"``).
        profile_name: Name of the selected profile, or None for default.

    Returns:
        Dict of env var name → value to overlay onto the child environment.
    """
    if not profile_name:
        return {}

    cfg = get_agent_config(agent_name)
    if cfg.profile is None or not cfg.profile.config_dir_env:
        return {}

    profile_dir = get_profiles_root() / agent_name / profile_name
    # Ensure the profile dir exists and seed files are written (idempotent).
    # This handles `hive run --profile work` for a never-created profile:
    # without mkdir+seed, the dir is empty and the agent misses hardening files
    # (e.g. codex config.toml forcing file-based auth), silently defeating
    # the credential-isolation the profile was meant to provide.
    profile_dir.mkdir(parents=True, exist_ok=True)
    if cfg.profile.seed_files:
        for filename, contents in cfg.profile.seed_files.items():
            target = profile_dir / filename
            if not target.exists():
                target.write_text(contents)

    env: dict[str, str] = {cfg.profile.config_dir_env: str(profile_dir)}
    env.update(cfg.profile.extra_env)
    return env


def get_extra_dirs_args(agent_name: str) -> list[str]:
    """Build CLI arguments for extra directories.

    Reads extra_dirs from settings, resolves each path relative to the main
    repo root (so relative paths work identically from worktrees), then
    pairs each resolved path with the agent's extra_dirs_flag.

    Args:
        agent_name: Name of the agent (to look up extra_dirs_flag).

    Returns:
        List like [flag, path1, flag, path2, ...], or [] if no dirs or
        the agent has no extra_dirs_flag configured.
    """
    from ..git import expand_path, get_main_repo

    settings = get_settings()
    # Session override (set by Ctrl+W in the picker) wins over configured dirs.
    # It contains already-resolved absolute paths plus the displaced primary.
    override = get_runtime_settings().workdir_extras_override
    dirs = override if override is not None else settings.extra_dirs
    if not dirs:
        return []

    agent_cfg = settings.agents.configs.get(agent_name, AgentConfig())
    flag = agent_cfg.extra_dirs_flag
    if not flag:
        return []

    main_repo = get_main_repo()
    result: list[str] = []
    for d in dirs:
        resolved = expand_path(d, main_repo)
        result.extend([flag, str(resolved)])
    return result


__all__ = [
    # Base
    "HiveBaseSettings",
    # New API
    "HiveSettings",
    "MergedYamlSource",
    "get_settings",
    "reset_settings",
    "RuntimeSettings",
    "get_runtime_settings",
    # Schema
    "AgentConfig",
    "AgentProfileConfig",
    "AgentsConfig",
    "GitHubConfig",
    "HiveConfig",
    "PostCreateCommand",
    "ResumeConfig",
    "WorktreesConfig",
    "ZellijConfig",
    # Loader utilities
    "CONFIG_FILE",
    "GLOBAL_CONFIG_DIR",
    "GLOBAL_CONFIG_FILES",
    "LOCAL_CONFIG_FILE",
    "find_config_files",
    "find_git_root",
    "find_global_config",
    "get_xdg_config_home",
    "load_default_config",
    "load_yaml_file",
    # Backward-compatible
    "load_config",
    "reload_config",
    # Defaults
    "KNOWN_AGENTS",
    # Merge
    "deep_merge",
    # Constants
    "ENV_HIVE_AGENT",
    # Helpers
    "get_agent_config",
    "get_agent_order",
    "get_extra_dirs_args",
    "get_profiles_root",
    "resolve_profile_env",
]
