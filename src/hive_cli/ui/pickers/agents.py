"""Agent selection picker."""

from __future__ import annotations

from ...agents import get_available_agents
from .fuzzy import FuzzyItem, fuzzy_select


def _agent_items(available: list[str], current_agent: str | None) -> list[FuzzyItem]:
    return [
        FuzzyItem(
            text=agent,
            value=agent,
            meta="← current" if agent == current_agent else "",
            style="green" if agent == current_agent else "",
        )
        for agent in available
    ]


def select_agent(current_agent: str | None = None) -> str | None:
    """Show picker for selecting an agent.

    Availability is a PATH lookup per configured agent (microseconds), so
    the list is built before the picker opens.

    Args:
        current_agent: Currently selected agent (will be highlighted).

    Returns:
        Selected agent name, or None if cancelled.
    """
    available = get_available_agents()
    if available:
        items = _agent_items(available, current_agent)
        header = "Select agent"
    else:
        items = [
            FuzzyItem(
                text="No supported agents found in PATH",
                value="",
                meta="",
                style="dim red",
            )
        ]
        header = "Select agent <red>(no agents found)</red>"

    selected = fuzzy_select(
        items=items,
        prompt_text=">",
        header=header,
        hint="</dim><b>Enter</b><dim> select  </dim><b>Esc</b><dim> back",
    )
    return selected if selected else None
