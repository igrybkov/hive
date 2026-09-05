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

from .base import HiveBaseSettings
from .defaults import KNOWN_AGENTS
from .loader import (
    CONFIG_FILE,
    GLOBAL_CONFIG_DIR,
    GLOBAL_CONFIG_FILES,
    LOCAL_CONFIG_FILE,
    find_config_files,
    find_global_config,
    find_project_root,
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
    "find_global_config",
    "find_project_root",
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
]
