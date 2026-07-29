"""Fuzzy finder utilities using prompt_toolkit for fzf-like experience."""

from __future__ import annotations

import math
import sys
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from prompt_toolkit import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import HTML, FormattedText
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import (
    ConditionalContainer,
    FormattedTextControl,
    HSplit,
    Layout,
    ScrollablePane,
    Window,
)
from prompt_toolkit.layout.controls import BufferControl
from prompt_toolkit.layout.processors import BeforeInput
from prompt_toolkit.output import create_output


@dataclass
class FuzzyItem:
    """An item for fuzzy selection."""

    text: str  # Display text
    value: str  # Return value (e.g., branch name)
    meta: str = ""  # Extra info (dimmed)
    style: str = ""  # prompt_toolkit style string


def _fuzzy_match(query: str, text: str) -> tuple[bool, int]:
    """Check if query fuzzy-matches text and return match score.

    Returns:
        (matches, score) - matches is bool, score is lower for better matches
    """
    if not query:
        return True, 0

    query_lower = query.lower()
    text_lower = text.lower()

    # Exact substring match gets best score
    if query_lower in text_lower:
        return True, text_lower.index(query_lower)

    # Fuzzy character match
    query_idx = 0
    score = 0
    for i, char in enumerate(text_lower):
        if query_idx < len(query_lower) and char == query_lower[query_idx]:
            query_idx += 1
            score += i  # Earlier matches are better
        else:
            score += 1

    if query_idx == len(query_lower):
        return True, score
    return False, 0


def fuzzy_select(
    items: Sequence[FuzzyItem],
    prompt_text: str = "",
    header: str = "",
    hint: str = "",
    initial_selection: int = 0,
    on_escape: Callable[[], str | None] | None = None,
    on_tab: Callable[[str], str | None] | None = None,
    on_shift_enter: Callable[[str], str | None] | None = None,
    on_ctrl_a: Callable[[], str | None] | None = None,
    on_ctrl_s: Callable[[], str | None] | None = None,
    on_ctrl_w: Callable[[], str | None] | None = None,
    on_ctrl_p: Callable[[], str | None] | None = None,
    update_callbacks: list[
        tuple[Callable[[list[FuzzyItem]], None], Callable[[str], None]]
    ]
    | None = None,
    update_callbacks_ready: threading.Event | None = None,
    auto_select_value: str | None = None,
    auto_select_timeout: float = 3.0,
) -> str | None:
    """Show fuzzy finder UI and return selected value.

    Args:
        items: List of FuzzyItem to select from.
        prompt_text: Prompt text to show.
        header: Optional header text.
        hint: Custom hint text for bottom bar. If empty, uses default.
        initial_selection: Index of initially selected item.
        on_escape: Callback when ESC is pressed. If returns a string, use as result.
        on_tab: Callback when Tab is pressed with current selection value.
                If returns a string, use as result. If returns None, stay in picker.
        on_shift_enter: Callback when Ctrl+O is pressed with current selection.
            If returns a string, use as result. If returns None, stay in picker.
        on_ctrl_a: Callback when Ctrl+A is pressed.
            If returns a string, use as result. If returns None, stay in picker.
        on_ctrl_s: Callback when Ctrl+S is pressed.
            If returns a string, use as result. If returns None, stay in picker.
        on_ctrl_w: Callback when Ctrl+W is pressed.
            If returns a string, use as result. If returns None, stay in picker.
        on_ctrl_p: Callback when Ctrl+P is pressed (profile selection).
            If returns a string, use as result. If returns None, stay in picker.
            Note: Ctrl+P is no longer bound to up-navigation; use ↑ instead.
        update_callbacks: Optional list to store (update_items, update_header)
            functions. If provided, functions available immediately when picker opens.
        update_callbacks_ready: Optional threading.Event to signal when callbacks
            are ready. If provided, will be set after callbacks are populated.
        auto_select_value: If set, automatically select this value after timeout.
            Any keypress cancels the auto-select timer.
        auto_select_timeout: Seconds before auto-selection (default 3.0).

    Returns:
        Selected item's value, or None if cancelled.
    """
    if not items:
        return None

    # State - store items as mutable list for dynamic updates
    items_list: list[FuzzyItem] = list(items)
    selected_idx = min(initial_selection, len(items_list) - 1) if items_list else 0
    filtered_items: list[FuzzyItem] = list(items_list)
    header_text: str = header  # Mutable header text for dynamic updates
    base_header: str = header  # Original header without countdown
    result: str | None = None
    exiting = False  # Guard against double-exit

    # Auto-select state
    auto_select_cancelled = threading.Event()
    auto_select_active = auto_select_value is not None and auto_select_timeout > 0

    def safe_exit(event, exception=None):
        """Exit the app, guarding against double-exit."""
        nonlocal exiting
        if exiting:
            return
        exiting = True
        # Cancel auto-select timer when exiting
        auto_select_cancelled.set()
        if exception:
            event.app.exit(exception=exception)
        else:
            event.app.exit()

    def cancel_auto_select():
        """Cancel auto-select timer on any user interaction."""
        nonlocal header_text, auto_select_active
        if auto_select_active:
            auto_select_cancelled.set()
            auto_select_active = False
            # Restore original header (remove countdown)
            header_text = base_header

    # Input buffer
    search_buffer = Buffer()

    # Key bindings
    kb = KeyBindings()

    @kb.add("c-c")
    def _cancel(event):
        cancel_auto_select()
        safe_exit(event, exception=KeyboardInterrupt())

    @kb.add("escape")
    def _escape(event):
        nonlocal result
        cancel_auto_select()
        if on_escape:
            escape_result = on_escape()
            if escape_result is not None:
                result = escape_result
                safe_exit(event)
        else:
            # Default behavior: Esc exits with None (go back)
            result = None
            safe_exit(event)

    @kb.add("c-d")
    def _ctrl_d(event):
        nonlocal result
        cancel_auto_select()
        if on_tab and filtered_items:
            current_value = filtered_items[selected_idx].value
            tab_result = on_tab(current_value)
            if tab_result is not None:
                result = tab_result
                safe_exit(event)
            # If None returned, stay in picker (will refresh on next iteration)

    @kb.add("enter")
    def _select(event):
        nonlocal result
        cancel_auto_select()
        if filtered_items:
            result = filtered_items[selected_idx].value
        safe_exit(event)

    @kb.add("c-o")
    def _ctrl_o(event):
        nonlocal result
        cancel_auto_select()
        if on_shift_enter and filtered_items:
            current_value = filtered_items[selected_idx].value
            shift_result = on_shift_enter(current_value)
            if shift_result is not None:
                result = shift_result
                safe_exit(event)
            # If None returned, stay in picker

    @kb.add("c-a")
    def _ctrl_a(event):
        nonlocal result
        cancel_auto_select()
        if on_ctrl_a:
            ctrl_a_result = on_ctrl_a()
            if ctrl_a_result is not None:
                result = ctrl_a_result
                safe_exit(event)
            # If None returned, stay in picker

    @kb.add("c-s")
    def _ctrl_s(event):
        nonlocal result
        cancel_auto_select()
        if on_ctrl_s:
            ctrl_s_result = on_ctrl_s()
            if ctrl_s_result is not None:
                result = ctrl_s_result
                safe_exit(event)
            # If None returned, stay in picker

    @kb.add("c-w")
    def _ctrl_w(event):
        nonlocal result
        cancel_auto_select()
        if on_ctrl_w:
            ctrl_w_result = on_ctrl_w()
            if ctrl_w_result is not None:
                result = ctrl_w_result
                safe_exit(event)
            # If None returned, stay in picker

    @kb.add("c-p")
    def _ctrl_p(event):
        nonlocal result
        cancel_auto_select()
        if on_ctrl_p:
            ctrl_p_result = on_ctrl_p()
            if ctrl_p_result is not None:
                result = ctrl_p_result
                safe_exit(event)
            # If None returned, stay in picker

    @kb.add("up")
    def _up(event):
        nonlocal selected_idx
        cancel_auto_select()
        if filtered_items:
            selected_idx = (selected_idx - 1) % len(filtered_items)

    @kb.add("down")
    @kb.add("c-n")
    def _down(event):
        nonlocal selected_idx
        cancel_auto_select()
        if filtered_items:
            selected_idx = (selected_idx + 1) % len(filtered_items)

    def _filter_items():
        """Filter items based on search query."""
        nonlocal filtered_items, selected_idx
        query = search_buffer.text

        if not query:
            filtered_items = list(items_list)
        else:
            # Filter and sort by match score
            matches = []
            for item in items_list:
                is_match, score = _fuzzy_match(query, item.text)
                if is_match:
                    matches.append((score, item))
            matches.sort(key=lambda x: x[0])
            filtered_items = [item for _, item in matches]

        # Reset to top match whenever filter changes
        selected_idx = 0

    def _on_text_changed(_):
        """Handle text change - cancel auto-select and filter items."""
        cancel_auto_select()
        _filter_items()

    # Update filter on text change
    search_buffer.on_text_changed += _on_text_changed

    def _get_items_text():
        """Generate formatted text for items list."""
        parts = []
        for i, item in enumerate(filtered_items):
            is_selected = i == selected_idx

            if is_selected:
                prefix = "> "
                style = "reverse " + item.style
            else:
                prefix = "  "
                style = item.style

            # Main text
            parts.append((style, prefix + item.text))

            # Meta text (dimmed)
            if item.meta:
                parts.append(("dim", f" {item.meta}"))

            parts.append(("", "\n"))

        if not filtered_items:
            parts.append(("dim", "  (no matches)\n"))

        return FormattedText(parts)

    def _get_header_text():
        """Generate header text dynamically."""
        return HTML(f"<b>{header_text}</b>")

    # Layout
    header_window = Window(
        content=FormattedTextControl(_get_header_text),
        height=1,
    )

    search_window = Window(
        content=BufferControl(
            buffer=search_buffer,
            input_processors=[BeforeInput(HTML(f"<b>{prompt_text}</b> "))],
        ),
        height=1,
    )

    items_window = Window(
        content=FormattedTextControl(_get_items_text),
        wrap_lines=False,
    )

    default_hint = (
        "</dim><b>↑↓</b><dim> nav  </dim><b>Enter</b><dim> select  "
        "</dim><b>^C</b><dim> cancel"
    )
    hint_text = hint if hint else default_hint
    hint_window = Window(
        content=FormattedTextControl(HTML(f"<dim>{hint_text}</dim>")),
        height=1,
    )

    layout = Layout(
        HSplit(
            [
                ConditionalContainer(
                    header_window,
                    filter=Condition(lambda: bool(header_text)),
                ),
                search_window,
                Window(height=1, char="─"),  # Separator
                ScrollablePane(items_window),
                hint_window,
            ]
        )
    )

    # Application - output to stderr so stdout can be captured by shell
    app: Application[None] = Application(
        layout=layout,
        key_bindings=kb,
        full_screen=True,
        mouse_support=True,
        output=create_output(stdout=sys.stderr),
    )

    def update_items(new_items: list[FuzzyItem]) -> None:
        """Update items list smoothly without flickering.

        Merges changes incrementally.

        Preserves existing item positions and only updates metadata in place.
        New items are appended at the end to avoid reordering existing items.

        Args:
            new_items: New list of FuzzyItem to merge with current items.
        """
        nonlocal items_list, filtered_items, selected_idx

        # Preserve currently selected value (if any)
        selected_value = (
            filtered_items[selected_idx].value
            if filtered_items and selected_idx < len(filtered_items)
            else None
        )

        # Create a map of existing items by value for quick lookup
        existing_items_map: dict[str, int] = {}
        for idx, item in enumerate(items_list):
            existing_items_map[item.value] = idx

        # Create a map of new items by value
        new_items_map: dict[str, FuzzyItem] = {item.value: item for item in new_items}
        new_values_set = set(new_items_map.keys())

        # Remove items that are no longer present
        # (e.g., closed issues, deleted branches)
        # Do this carefully to preserve order and avoid index shifting
        items_to_remove = []
        for value, idx in existing_items_map.items():
            if value not in new_values_set:
                items_to_remove.append(idx)

        # Remove items in reverse order to avoid index shifting
        for idx in sorted(items_to_remove, reverse=True):
            items_list.pop(idx)

        # Rebuild existing_items_map after removals (indices have changed)
        existing_items_map = {}
        for idx, item in enumerate(items_list):
            existing_items_map[item.value] = idx

        # Update existing items in place (preserve position, update metadata)
        # This prevents flickering by keeping items in the same visual position
        for value, idx in existing_items_map.items():
            if value in new_items_map:
                # Update existing item's metadata and style without changing position
                new_item = new_items_map[value]
                existing_item = items_list[idx]
                # Only update if metadata or style changed to avoid unnecessary updates
                if (
                    existing_item.meta != new_item.meta
                    or existing_item.style != new_item.style
                ):
                    items_list[idx] = FuzzyItem(
                        text=existing_item.text,  # Keep original text
                        value=existing_item.value,
                        meta=new_item.meta,  # Update metadata (e.g., dirty status)
                        style=new_item.style,  # Update style (e.g., yellow for dirty)
                    )

        # Find items to append (new items not in existing list)
        # Typically remote branches and GitHub issues from fast initial load
        items_to_append: list[FuzzyItem] = []
        existing_values_set = set(existing_items_map.keys())
        for new_item in new_items:
            if new_item.value not in existing_values_set:
                items_to_append.append(new_item)

        # Append new items at the end
        # Preserves existing order, adds new ones without reordering
        # Ensures existing items stay in their visual positions
        if items_to_append:
            items_list.extend(items_to_append)

        # Re-filter based on current search query
        _filter_items()

        # Try to restore selection by finding the same value in new filtered list
        if selected_value and filtered_items:
            for i, item in enumerate(filtered_items):
                if item.value == selected_value:
                    selected_idx = i
                    break
            else:
                # Selected value not found, keep current index but clamp to bounds
                selected_idx = (
                    min(selected_idx, len(filtered_items) - 1) if filtered_items else 0
                )

        # Trigger smooth redraw (thread-safe)
        app.invalidate()

    def update_header(new_header: str) -> None:
        """Update the header text dynamically.

        Args:
            new_header: New header text to display.
        """
        nonlocal header_text
        header_text = new_header
        # Trigger smooth redraw (thread-safe)
        app.invalidate()

    # Store update functions in callback list if provided
    # (before app.run so they're available immediately)
    if update_callbacks is not None:
        update_callbacks.append((update_items, update_header))
        # Signal that callbacks are ready
        if update_callbacks_ready is not None:
            update_callbacks_ready.set()

    # Auto-select timer thread
    def auto_select_timer():
        """Countdown and auto-select if not cancelled."""
        nonlocal result, header_text
        start_time = time.monotonic()
        remaining = auto_select_timeout

        while remaining > 0 and not auto_select_cancelled.is_set():
            # Update header with countdown (ceil for display: 2.1s shows as 3s)
            seconds_left = math.ceil(remaining)
            header_text = (
                f"{base_header} "
                f"<dim>(auto-selecting </dim><yellow>{auto_select_value}</yellow>"
                f"<dim> in {seconds_left}s...)</dim>"
            )
            app.invalidate()

            # Wait for cancellation or next tick (update every 0.5s for countdown)
            if auto_select_cancelled.wait(timeout=0.5):
                return  # Cancelled

            remaining = auto_select_timeout - (time.monotonic() - start_time)

        # Timer expired without cancellation - auto-select
        if not auto_select_cancelled.is_set():
            result = auto_select_value
            # Exit the app from background thread
            app.exit()

    # Start auto-select timer if configured
    if auto_select_value is not None:
        if auto_select_timeout <= 0:
            # Instant selection (no UI shown)
            return auto_select_value
        auto_select_thread = threading.Thread(target=auto_select_timer, daemon=True)
        auto_select_thread.start()

    try:
        app.run()
    except KeyboardInterrupt:
        auto_select_cancelled.set()
        return None
    return result
