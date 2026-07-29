"""Agent detection and auto-selection."""

from __future__ import annotations

import shutil
from dataclasses import dataclass

from ..config import get_agent_order


@dataclass
class DetectedAgent:
    """Represents a detected AI coding agent."""

    name: str
    command: str  # actual command to run (might differ from name)


def detect_agent(preferred: str | None = None) -> DetectedAgent | None:
    """Auto-detect available AI coding agent.

    If preferred is specified, verify it exists and return it.
    Otherwise, try each agent in priority order based on agents.order config.

    Args:
        preferred: Specific agent to use (from --agent flag or AGENT env var)

    Returns:
        DetectedAgent if found, None if no agent is available.
    """
    if preferred:
        if shutil.which(preferred):
            return DetectedAgent(name=preferred, command=preferred)
        return None

    for agent in get_agent_order():
        if shutil.which(agent):
            return DetectedAgent(name=agent, command=agent)

    return None


def get_available_agents() -> list[str]:
    """Get list of available agents on the system.

    Returns:
        List of agent names that are available in PATH.
    """
    available = []
    for agent in get_agent_order():
        if shutil.which(agent):
            available.append(agent)
    return available
