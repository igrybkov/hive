"""HiveSettings - unified settings loaded from YAML + env vars.

Usage:
    from hive_cli.config import get_settings

    settings = get_settings()
    print(settings.agents.order)
    print(settings.worktrees.parent_dir)
"""

from __future__ import annotations

from typing import Annotated, Any, ClassVar

from pydantic import Field
from pydantic_settings import PydanticBaseSettingsSource

from . import loader
from .base import HiveBaseSettings
from .merge import deep_merge
from .schema import (
    AgentsConfig,
    GitHubConfig,
    ResumeConfig,
    WorktreesConfig,
    ZellijConfig,
)


class MergedYamlSource(PydanticBaseSettingsSource):
    """Settings source that deep-merges YAML config files.

    Loads and caches the merged result of:
    1. Package default config (default.yml)
    2. Global user config ($XDG_CONFIG_HOME/hive/hive.yml)
    3. Project config (.hive.yml)
    4. Local overrides (.hive.local.yml)

    YAML is cached because it doesn't change during a session.
    """

    _cache: ClassVar[dict[str, Any] | None] = None

    def get_field_value(self, field, field_name):
        """Required by PydanticBaseSettingsSource interface."""
        data = self._load()
        val = data.get(field_name)
        return val, field_name, False

    def __call__(self) -> dict[str, Any]:
        """Return merged YAML data."""
        return dict(self._load())

    def _load(self) -> dict[str, Any]:
        """Load and cache merged YAML config."""
        if MergedYamlSource._cache is None:
            merged = loader.load_default_config()
            for path in loader.find_config_files():
                merged = deep_merge(merged, loader.load_yaml_file(path))
            MergedYamlSource._cache = merged
        return MergedYamlSource._cache

    @classmethod
    def clear_cache(cls) -> None:
        """Clear the YAML cache. Called by reload()."""
        cls._cache = None


class HiveSettings(HiveBaseSettings):
    """Top-level Hive settings.

    Sub-configs are HiveBaseSettings subclasses with their own env_prefix,
    so they natively handle env var overrides. HiveSettings itself only
    reads from YAML (via MergedYamlSource) and passes values to sub-configs
    as init kwargs.

    Precedence per sub-config field: env var > YAML > default.
    """

    agents: Annotated[AgentsConfig, Field(default_factory=AgentsConfig)]
    resume: Annotated[ResumeConfig, Field(default_factory=ResumeConfig)]
    worktrees: Annotated[WorktreesConfig, Field(default_factory=WorktreesConfig)]
    zellij: Annotated[ZellijConfig, Field(default_factory=ZellijConfig)]
    github: Annotated[GitHubConfig, Field(default_factory=GitHubConfig)]
    extra_dirs: Annotated[list[str], Field(default_factory=list)]

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls,
        init_settings,
        env_settings,
        dotenv_settings,
        file_secret_settings,
    ):
        """Use MergedYamlSource instead of env_settings at top level.

        Env vars are handled by each sub-config's own env_prefix.
        """
        return (init_settings, MergedYamlSource(settings_cls))

    def reload(self) -> None:
        """Re-initialize settings, clearing YAML cache first."""
        MergedYamlSource.clear_cache()
        self.__init__()


# Singleton
_settings: HiveSettings | None = None


def get_settings() -> HiveSettings:
    """Get the global HiveSettings singleton.

    Returns:
        HiveSettings instance with merged YAML + env var overrides.
    """
    global _settings
    if _settings is None:
        _settings = HiveSettings()
    return _settings


def reset_settings() -> None:
    """Reset the settings singleton and clear YAML cache.

    The next call to get_settings() will create a fresh instance.
    Used by tests that need to mock config sources.
    """
    global _settings
    _settings = None
    MergedYamlSource.clear_cache()
