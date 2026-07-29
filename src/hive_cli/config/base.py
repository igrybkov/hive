"""Base settings class for Hive CLI configuration."""

from __future__ import annotations

from typing import Any

from pydantic.fields import FieldInfo
from pydantic_settings import BaseSettings, EnvSettingsSource, SettingsConfigDict


class HiveEnvSource(EnvSettingsSource):
    """Custom env settings source that handles CSV-formatted list fields.

    Pydantic-settings expects JSON for complex types (list, dict) in env vars.
    This source intercepts list[str] fields and parses comma-separated values
    instead, so HIVE_AGENTS_ORDER=codex,claude works naturally.
    """

    def prepare_field_value(
        self,
        field_name: str,
        field: FieldInfo,
        value: Any,
        value_is_complex: bool,
    ) -> Any:
        """Parse CSV strings for list fields before pydantic validation."""
        if isinstance(value, str):
            origin = getattr(field.annotation, "__origin__", None)
            if origin is list:
                return [a.strip() for a in value.split(",") if a.strip()]
        return super().prepare_field_value(field_name, field, value, value_is_complex)


class HiveBaseSettings(BaseSettings):
    """Base class for all Hive settings.

    Standardizes:
    - Mutable after construction (frozen=False)
    - Env vars override init values (source order: env_settings before init_settings)
    - CSV parsing for list fields in env vars
    - Extra fields ignored
    - reload() method for in-place re-initialization
    """

    model_config = SettingsConfigDict(frozen=False, extra="ignore")

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls,
        init_settings,
        env_settings,
        dotenv_settings,
        file_secret_settings,
    ):
        """Env vars take precedence over init kwargs (which come from YAML)."""
        return (HiveEnvSource(settings_cls), init_settings)

    def reload(self) -> None:
        """Re-initialize settings in place, re-reading env vars."""
        self.__init__()
