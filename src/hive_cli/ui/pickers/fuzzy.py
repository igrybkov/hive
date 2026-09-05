"""Fuzzy finder utilities using prompt_toolkit for fzf-like experience."""

from __future__ import annotations

import math
import sys
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

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


@dataclass
class _PickerState:
    """Mutable state shared by the picker's key handlers and render callbacks."""

    items: list[FuzzyItem]
    filtered: list[FuzzyItem]
    selected_idx: int
    header_text: str
    base_header: str
    result: str | None = None
    exiting: bool = False
    auto_select_active: bool = False
    cancelled: threading.Event = field(default_factory=threading.Event)


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


def _filtered(items_list: list[FuzzyItem], query: str) -> list[FuzzyItem]:
    """Items matching ``query``, sorted by match score (always a new list)."""
    if not query:
        return list(items_list)
    matches = []
    for item in items_list:
        is_match, score = _fuzzy_match(query, item.text)
        if is_match:
            matches.append((score, item))
    matches.sort(key=lambda x: x[0])
    return [item for _, item in matches]


def _index_by_value(items_list: list[FuzzyItem]) -> dict[str, int]:
    return {item.value: idx for idx, item in enumerate(items_list)}


def _drop_missing(items_list: list[FuzzyItem], keep_values: set[str]) -> None:
    stale = [
        idx
        for value, idx in _index_by_value(items_list).items()
        if value not in keep_values
    ]
    # Remove in reverse order to avoid index shifting
    for idx in sorted(stale, reverse=True):
        items_list.pop(idx)


def _refresh_metadata(
    items_list: list[FuzzyItem], new_items_map: dict[str, FuzzyItem]
) -> None:
    """Update meta/style in place so items keep their visual position."""
    for value, idx in _index_by_value(items_list).items():
        new_item = new_items_map.get(value)
        if new_item is None:
            continue
        existing_item = items_list[idx]
        # Only update if metadata or style changed to avoid unnecessary updates
        if existing_item.meta != new_item.meta or existing_item.style != new_item.style:
            items_list[idx] = FuzzyItem(
                text=existing_item.text,  # Keep original text
                value=existing_item.value,
                meta=new_item.meta,  # Update metadata (e.g., dirty status)
                style=new_item.style,  # Update style (e.g., yellow for dirty)
            )


def _append_new(items_list: list[FuzzyItem], new_items: list[FuzzyItem]) -> None:
    """Append unseen items at the end so existing ones are never reordered."""
    existing_values = set(_index_by_value(items_list))
    items_list.extend(item for item in new_items if item.value not in existing_values)


def _merge_items(items_list: list[FuzzyItem], new_items: list[FuzzyItem]) -> None:
    """Merge ``new_items`` into ``items_list`` in place, preserving positions."""
    new_items_map = {item.value: item for item in new_items}
    _drop_missing(items_list, set(new_items_map))
    _refresh_metadata(items_list, new_items_map)
    _append_new(items_list, new_items)


def _current_selection(state: _PickerState) -> str | None:
    if state.filtered and state.selected_idx < len(state.filtered):
        return state.filtered[state.selected_idx].value
    return None


def _restore_selection(
    filtered_items: list[FuzzyItem], selected_value: str | None, previous_idx: int
) -> int:
    """Index of ``selected_value`` in the new list, else the clamped old index."""
    if not (selected_value and filtered_items):
        return previous_idx
    for i, item in enumerate(filtered_items):
        if item.value == selected_value:
            return i
    return min(previous_idx, len(filtered_items) - 1)


def _render_items(filtered_items: list[FuzzyItem], selected_idx: int) -> FormattedText:
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


def _countdown_header(
    base_header: str, auto_select_value: str, remaining: float
) -> str:
    # ceil for display: 2.1s shows as 3s
    seconds_left = math.ceil(remaining)
    return (
        f"{base_header} "
        f"<dim>(auto-selecting </dim><yellow>{auto_select_value}</yellow>"
        f"<dim> in {seconds_left}s...)</dim>"
    )


def _safe_exit(state: _PickerState, event, exception=None) -> None:
    """Exit the app, guarding against double-exit."""
    if state.exiting:
        return
    state.exiting = True
    # Cancel auto-select timer when exiting
    state.cancelled.set()
    if exception:
        event.app.exit(exception=exception)
    else:
        event.app.exit()


def _cancel_auto_select(state: _PickerState) -> None:
    """Cancel auto-select timer on any user interaction."""
    if state.auto_select_active:
        state.cancelled.set()
        state.auto_select_active = False
        # Restore original header (remove countdown)
        state.header_text = state.base_header


def _finish(state: _PickerState, event, value: str | None) -> None:
    """Store a callback's result and exit; ``None`` means stay in the picker."""
    if value is not None:
        state.result = value
        _safe_exit(state, event)


def _make_cancel_handler(state: _PickerState):
    def handler(event):
        _cancel_auto_select(state)
        _safe_exit(state, event, exception=KeyboardInterrupt())

    return handler


def _make_escape_handler(
    state: _PickerState, on_escape: Callable[[], str | None] | None
):
    def handler(event):
        _cancel_auto_select(state)
        if not on_escape:
            # Default behavior: Esc exits with None (go back)
            state.result = None
            _safe_exit(state, event)
            return
        _finish(state, event, on_escape())

    return handler


def _make_select_handler(state: _PickerState):
    def handler(event):
        _cancel_auto_select(state)
        if state.filtered:
            state.result = state.filtered[state.selected_idx].value
        _safe_exit(state, event)

    return handler


def _make_value_handler(
    state: _PickerState, callback: Callable[[str], str | None] | None
):
    """Handler passing the current selection's value to ``callback``."""

    def handler(event):
        _cancel_auto_select(state)
        if callback and state.filtered:
            _finish(state, event, callback(state.filtered[state.selected_idx].value))

    return handler


def _make_no_arg_handler(
    state: _PickerState, callback: Callable[[], str | None] | None
):
    def handler(event):
        _cancel_auto_select(state)
        if callback:
            _finish(state, event, callback())

    return handler


def _make_move_handler(state: _PickerState, delta: int):
    def handler(event):
        _cancel_auto_select(state)
        if state.filtered:
            state.selected_idx = (state.selected_idx + delta) % len(state.filtered)

    return handler


def _run_auto_select_countdown(
    state: _PickerState,
    app: Application[None],
    auto_select_value: str,
    auto_select_timeout: float,
) -> None:
    """Countdown and auto-select if not cancelled."""
    start_time = time.monotonic()
    remaining = auto_select_timeout

    while remaining > 0 and not state.cancelled.is_set():
        state.header_text = _countdown_header(
            state.base_header, auto_select_value, remaining
        )
        app.invalidate()

        # Wait for cancellation or next tick (update every 0.5s for countdown)
        if state.cancelled.wait(timeout=0.5):
            return  # Cancelled

        remaining = auto_select_timeout - (time.monotonic() - start_time)

    # Timer expired without cancellation - auto-select
    if not state.cancelled.is_set():
        state.result = auto_select_value
        # Exit the app from background thread
        app.exit()


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
    state = _PickerState(
        items=items_list,
        filtered=list(items_list),
        selected_idx=min(initial_selection, len(items_list) - 1) if items_list else 0,
        header_text=header,  # Mutable header text for dynamic updates
        base_header=header,  # Original header without countdown
        auto_select_active=auto_select_value is not None and auto_select_timeout > 0,
    )

    # Input buffer
    search_buffer = Buffer()

    # Key bindings
    kb = KeyBindings()
    kb.add("c-c")(_make_cancel_handler(state))
    kb.add("escape")(_make_escape_handler(state, on_escape))
    kb.add("c-d")(_make_value_handler(state, on_tab))
    kb.add("enter")(_make_select_handler(state))
    kb.add("c-o")(_make_value_handler(state, on_shift_enter))
    kb.add("c-a")(_make_no_arg_handler(state, on_ctrl_a))
    kb.add("c-s")(_make_no_arg_handler(state, on_ctrl_s))
    kb.add("c-w")(_make_no_arg_handler(state, on_ctrl_w))
    kb.add("c-p")(_make_no_arg_handler(state, on_ctrl_p))
    kb.add("up")(_make_move_handler(state, -1))
    move_down = _make_move_handler(state, 1)
    kb.add("c-n")(move_down)
    kb.add("down")(move_down)

    def _filter_items():
        """Filter items based on search query; reset to the top match."""
        state.filtered = _filtered(state.items, search_buffer.text)
        state.selected_idx = 0

    def _on_text_changed(_):
        """Handle text change - cancel auto-select and filter items."""
        _cancel_auto_select(state)
        _filter_items()

    # Update filter on text change
    search_buffer.on_text_changed += _on_text_changed

    def _get_items_text():
        """Generate formatted text for items list."""
        return _render_items(state.filtered, state.selected_idx)

    def _get_header_text():
        """Generate header text dynamically."""
        return HTML(f"<b>{state.header_text}</b>")

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
                    filter=Condition(lambda: bool(state.header_text)),
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
        selected_value = _current_selection(state)
        _merge_items(state.items, new_items)
        # Re-filter based on current search query
        _filter_items()
        state.selected_idx = _restore_selection(
            state.filtered, selected_value, state.selected_idx
        )
        # Trigger smooth redraw (thread-safe)
        app.invalidate()

    def update_header(new_header: str) -> None:
        """Update the header text dynamically.

        Args:
            new_header: New header text to display.
        """
        state.header_text = new_header
        # Trigger smooth redraw (thread-safe)
        app.invalidate()

    # Store update functions in callback list if provided
    # (before app.run so they're available immediately)
    if update_callbacks is not None:
        update_callbacks.append((update_items, update_header))
        # Signal that callbacks are ready
        if update_callbacks_ready is not None:
            update_callbacks_ready.set()

    # Start auto-select timer if configured
    if auto_select_value is not None:
        if auto_select_timeout <= 0:
            # Instant selection (no UI shown)
            return auto_select_value
        auto_select_thread = threading.Thread(
            target=_run_auto_select_countdown,
            args=(state, app, auto_select_value, auto_select_timeout),
            daemon=True,
        )
        auto_select_thread.start()

    try:
        app.run()
    except KeyboardInterrupt:
        state.cancelled.set()
        return None
    return state.result
