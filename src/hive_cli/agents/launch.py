"""Argv/env assembly for launching an agent."""

from __future__ import annotations

from .. import config


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
