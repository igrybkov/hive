"""Agent selection utilities."""

from __future__ import annotations

import threading

from ..agents import get_available_agents
from .fuzzy import FuzzyItem, fuzzy_select


def select_agent(current_agent: str | None = None) -> str | None:
    """Show picker for selecting an agent.

    Args:
        current_agent: Currently selected agent (will be highlighted).

    Returns:
        Selected agent name, or None if cancelled.
    """
    # Show picker immediately with loading state
    items = [FuzzyItem(text="Loading agents...", value="", meta="", style="dim")]
    update_callbacks = []
    update_callbacks_ready = threading.Event()

    def fetch_agents():
        """Fetch available agents in background."""
        if not update_callbacks_ready.wait(timeout=1.0):
            return
        if not update_callbacks:
            return

        update_items, update_header = update_callbacks[0]

        # Get available agents (checks PATH - fast but async for consistency)
        available = get_available_agents()

        if not available:
            update_header("Select agent <red>(no agents found)</red>")
            update_items(
                [
                    FuzzyItem(
                        text="No supported agents found in PATH",
                        value="",
                        meta="",
                        style="dim red",
                    )
                ]
            )
            return

        # Build items with current agent highlighted
        agent_items = []
        for agent in available:
            is_current = agent == current_agent
            agent_items.append(
                FuzzyItem(
                    text=agent,
                    value=agent,
                    meta="← current" if is_current else "",
                    style="green" if is_current else "",
                )
            )

        update_header("Select agent")
        update_items(agent_items)

    # Start background fetch
    fetch_thread = threading.Thread(target=fetch_agents, daemon=True)
    fetch_thread.start()

    # Find initial selection
    initial_selection = 0
    # Will be updated when items load

    selected = fuzzy_select(
        items=items,
        prompt_text=">",
        header="Select agent <dim>(loading...)</dim>",
        hint="</dim><b>Enter</b><dim> select  </dim><b>Esc</b><dim> back",
        initial_selection=initial_selection,
        update_callbacks=update_callbacks,
        update_callbacks_ready=update_callbacks_ready,
    )

    return selected if selected else None
