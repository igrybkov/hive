"""RuntimeSettings - mutable runtime state read from env vars.

Centralizes all os.environ.get() calls for runtime state like
HIVE_AGENT, HIVE_PANE_ID, ZELLIJ, EDITOR, etc.

Usage:
    from hive_cli.config import get_runtime_settings

    rt = get_runtime_settings()
    print(rt.agent)       # reads HIVE_AGENT
    rt.agent = "claude"   # mutates in memory
    env = rt.build_child_env()  # env dict for subprocesses
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated

from pydantic import Field, computed_field, field_validator

from .base import HiveBaseSettings

# Fields exported to child processes via build_child_env().
_MUTABLE_FIELDS = frozenset({"agent", "agent_profile", "pane_id", "skip_permissions"})


class RuntimeSettings(HiveBaseSettings):
    """Runtime state populated from environment variables.

    Mutable fields (agent, pane_id, skip_permissions) can be changed at
    runtime and exported to child processes via build_child_env().

    Immutable context fields (in_zellij, editor, etc.) are read once
    from the parent process environment.
    """

    # --- Mutable state ---
    # validation_alias  → pydantic-settings reads this env var
    # serialization_alias → model_dump(by_alias=True) produces this key
    agent: Annotated[
        str | None,
        Field(None, validation_alias="HIVE_AGENT", serialization_alias="HIVE_AGENT"),
    ]
    agent_profile: Annotated[
        str | None,
        Field(
            None,
            validation_alias="HIVE_AGENT_PROFILE",
            serialization_alias="HIVE_AGENT_PROFILE",
        ),
    ]
    pane_id: Annotated[
        str | None,
        Field(
            None, validation_alias="HIVE_PANE_ID", serialization_alias="HIVE_PANE_ID"
        ),
    ]
    skip_permissions: Annotated[
        bool,
        Field(
            False,
            validation_alias="HIVE_SKIP_PERMISSIONS",
            serialization_alias="HIVE_SKIP_PERMISSIONS",
        ),
    ]

    # Session-scoped workdir override (set via Ctrl+W in the picker).
    # Not persisted to env; cleared between restart-loop iterations.
    # Aliased to a synthetic env name so BaseSettings doesn't read $WORKDIR.
    workdir: Annotated[
        Path | None,
        Field(None, validation_alias="_HIVE_WORKDIR_SESSION", exclude=True),
    ] = None
    workdir_extras_override: Annotated[
        list[str] | None,
        Field(None, validation_alias="_HIVE_WORKDIR_EXTRAS_SESSION", exclude=True),
    ] = None

    # --- Immutable context ---
    # Zellij sets ZELLIJ=0 when running inside a session.
    # Any non-empty string (including "0") means we're in Zellij.
    in_zellij: Annotated[bool, Field(False, validation_alias="ZELLIJ")]

    @field_validator("in_zellij", mode="before")
    @classmethod
    def parse_zellij_env(cls, v: object) -> bool:
        """Treat any non-None string as True (Zellij sets ZELLIJ=0)."""
        if isinstance(v, str):
            return True
        return bool(v) if v is not None else False

    zellij_session_name: Annotated[
        str, Field("default", validation_alias="ZELLIJ_SESSION_NAME")
    ]
    zellij_pane_id: Annotated[str, Field("0", validation_alias="ZELLIJ_PANE_ID")]
    pane_label: Annotated[str | None, Field(None, validation_alias="HIVE_PANE_LABEL")]
    editor: Annotated[str, Field("vim", validation_alias="EDITOR")]
    xdg_cache_home: Annotated[
        Path,
        Field(
            default_factory=lambda: Path.home() / ".cache",
            validation_alias="XDG_CACHE_HOME",
        ),
    ]

    @computed_field
    @property
    def pane_id_int(self) -> int:
        """Get pane ID as integer (0 if not set)."""
        return int(self.pane_id) if self.pane_id else 0

    def build_child_env(self) -> dict[str, str]:
        """Build a complete env dict for child processes.

        Uses model_dump(by_alias=True) to produce env-var-keyed dict
        from the mutable fields.  Starts with os.environ, removes stale
        mutable keys (e.g. HIVE_SKIP_PERMISSIONS=1 that was since
        toggled off), then overlays the current runtime state.
        """
        raw = self.model_dump(by_alias=True, include=_MUTABLE_FIELDS)

        env = dict(os.environ)
        # Remove all mutable keys first (handles toggled-off booleans)
        for key in raw:
            env.pop(key, None)
        # Overlay truthy values as strings
        for key, val in raw.items():
            if val is not None and val is not False:
                env[key] = str(val)
        return env


# Singleton
_runtime_settings: RuntimeSettings | None = None


def get_runtime_settings() -> RuntimeSettings:
    """Get the global RuntimeSettings singleton.

    Returns:
        RuntimeSettings instance populated from current environment.
    """
    global _runtime_settings
    if _runtime_settings is None:
        _runtime_settings = RuntimeSettings()
    return _runtime_settings
