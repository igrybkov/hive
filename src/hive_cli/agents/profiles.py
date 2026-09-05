"""Per-agent config-dir profile resolution: root directory + env overlay."""

from __future__ import annotations

from pathlib import Path

from ..config import get_agent_config
from ..core import paths


def get_profiles_root() -> Path:
    """Return the root directory for per-agent config profiles.

    Profiles live at ``<root>/<agent>/<profile>/`` and are passed to the agent
    via its ``config_dir_env``.  The default is ``$XDG_CONFIG_HOME/hive/profiles``
    which can be overridden by a ``profiles.root`` key in hive.yml (not yet in
    schema — reserved for future extension).

    Returns:
        Path to the profiles root directory.
    """
    return paths.xdg_config_home() / "hive" / "profiles"


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
