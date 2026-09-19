"""Argv/env assembly for launching an agent."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from .. import config
from ..core import paths
from ..core.errors import HiveError
from ..hooks import templates


def get_extra_dirs_args(agent_name: str, resolved_dirs: list[str]) -> list[str]:
    """Build CLI arguments for extra directories.

    Args:
        agent_name: Name of the agent (to look up extra_dirs_flag).
        resolved_dirs: Already-resolved absolute directory paths (see
            git.expand_path; resolving them is the caller's job since it
            needs the git-layer main repo root, which this module doesn't
            depend on).

    Returns:
        List like [flag, path1, flag, path2, ...], or [] if no dirs or
        the agent has no extra_dirs_flag configured.
    """
    if not resolved_dirs:
        return []

    settings = config.get_settings()
    agent_cfg = settings.agents.configs.get(agent_name, config.AgentConfig())
    flag = agent_cfg.extra_dirs_flag
    if not flag:
        return []

    result: list[str] = []
    for d in resolved_dirs:
        result.extend([flag, d])
    return result


def hive_hook_path() -> str:
    """Absolute path to the `hive-hook` executable.

    `shutil.which` first (the normal case: same venv/PATH as `hive` itself),
    then the sibling of the running `hive` executable (mirrors
    `core.paths.hive_executable`'s own PATH-resolution fallback -- a pane
    spawned by Zellij may not have the launching shell's PATH). Raises
    HiveError when neither exists, since `hooks.enabled` with no `hive-hook`
    to inject would silently do nothing.
    """
    found = shutil.which("hive-hook")
    if found:
        return found
    sibling = Path(paths.hive_executable()).parent / "hive-hook"
    if sibling.is_file():
        return str(sibling)
    raise HiveError(
        "hooks.enabled is true but hive-hook is not installed "
        "(not on PATH, not next to the hive executable)."
    )


def hook_args(
    agent_name: str, *, hive_hook: str, settings: config.HiveSettings
) -> list[str]:
    """CLI args wiring `agent_name`'s own hook mechanism to `hive_hook`.

    [] unless settings.hooks.enabled and the agent's hooks.mode is "cli":
    claude -> ["--settings", <compact JSON of templates.claude_settings(...)>]
    codex  -> ["-c", codex_notify(hive_hook)]
    Gemini's "profile" mode and "unsupported" agents never get CLI args here
    -- see agents/profiles.py:ensure_gemini_hooks for the profile-mode path.
    """
    if not settings.hooks.enabled:
        return []
    agent_cfg = settings.agents.configs.get(agent_name, config.AgentConfig())
    if agent_cfg.hooks.mode != "cli":
        return []
    if agent_name == "claude":
        payload = json.dumps(
            templates.claude_settings(hive_hook), separators=(",", ":")
        )
        return ["--settings", payload]
    if agent_name == "codex":
        return ["-c", templates.codex_notify(hive_hook)]
    return []
