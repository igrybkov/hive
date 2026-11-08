"""Integration tests for the fuzzy picker that drive a real prompt_toolkit app.

Unlike ``tests/test_ui_pickers_fuzzy.py`` (which mocks ``Application`` entirely), these
tests run the real ``prompt_toolkit`` event loop against a pipe input and a
``DummyOutput``, so the key bindings, filtering, rendering callbacks,
refiners, and auto-select timer are all exercised for real.
"""

from __future__ import annotations

import threading
import time
from typing import Any

import pytest
from prompt_toolkit.input import PipeInput, create_pipe_input
from prompt_toolkit.output import DummyOutput

from hive_cli.ui.pickers.fuzzy import FuzzyItem, _fuzzy_match, fuzzy_select

# ---------------------------------------------------------------------------
# Key byte constants for readability at call sites.
# ---------------------------------------------------------------------------
ENTER = "\r"
ESCAPE = "\x1b"
CTRL_C = "\x03"
CTRL_D = "\x04"  # bound to the `on_tab` callback (not the literal Tab key, see below)
CTRL_O = "\x0f"
CTRL_A = "\x01"
CTRL_S = "\x13"
CTRL_W = "\x17"
CTRL_P = "\x10"
DOWN = "\x1b[B"
UP = "\x1b[A"

DEFAULT_ITEMS = [
    FuzzyItem(text="alpha", value="a"),
    FuzzyItem(text="beta", value="b"),
    FuzzyItem(text="gamma", value="g"),
]


def _run_with_input(inp: PipeInput, **kwargs: Any) -> str | None:
    """Run ``fuzzy_select`` against an already-populated pipe input."""
    return fuzzy_select(input=inp, output=DummyOutput(), **kwargs)


def _run_in_thread(inp: PipeInput, **kwargs: Any) -> tuple[threading.Thread, dict]:
    """Start ``fuzzy_select`` on a worker thread; the result lands in the dict."""
    holder: dict[str, str | None] = {}

    def worker() -> None:
        holder["value"] = _run_with_input(inp, **kwargs)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    return thread, holder


def _finish(inp: PipeInput, thread: threading.Thread, keys: str) -> None:
    """Send ``keys`` and wait for the picker; never leave a hung app behind."""
    try:
        inp.send_text(keys)
        thread.join(timeout=3)
    finally:
        if thread.is_alive():
            inp.send_text(CTRL_C)
            thread.join(timeout=3)
    assert not thread.is_alive(), "picker thread did not finish in time"


def run_picker(keys: str, **kwargs: Any) -> str | None:
    """Queue ``keys`` on a pipe input, then run the real fuzzy picker.

    ``keys`` is sent before the application starts, so it's available as soon
    as the app begins reading input (Enter is ``"\\r"``).
    """
    with create_pipe_input() as inp:
        inp.send_text(keys)
        return _run_with_input(inp, **kwargs)


def make_items(*pairs: tuple[str, str]) -> list[FuzzyItem]:
    return [FuzzyItem(text=text, value=value) for text, value in pairs]


# ---------------------------------------------------------------------------
# _fuzzy_match unit table
# ---------------------------------------------------------------------------


class TestFuzzyMatch:
    @pytest.mark.parametrize(
        ("query", "text", "expected_match"),
        [
            ("", "anything", True),  # empty query always matches
            ("beta", "beta", True),  # exact match
            ("bet", "beta", True),  # substring prefix match
            ("eta", "beta", True),  # substring match not at start
            ("bt", "beta", True),  # scattered fuzzy match (b...t)
            ("BETA", "beta", True),  # case-insensitive
            ("beta", "BETA", True),  # case-insensitive both ways
            ("xyz", "beta", False),  # no match at all
            ("betaa", "beta", False),  # query longer than text, can't match
            ("atb", "beta", False),  # wrong order breaks fuzzy match
        ],
    )
    def test_match_result(self, query: str, text: str, expected_match: bool) -> None:
        matches, _score = _fuzzy_match(query, text)
        assert matches is expected_match

    def test_empty_query_scores_zero(self) -> None:
        assert _fuzzy_match("", "whatever") == (True, 0)

    def test_substring_match_scores_by_index_of_match(self) -> None:
        # Substring found at position 0 beats one found later.
        _, score_prefix = _fuzzy_match("bet", "beta")
        _, score_later = _fuzzy_match("eta", "beta")
        assert score_prefix == 0
        assert score_later == 1
        assert score_prefix < score_later

    def test_prefix_substring_match_beats_scattered_match(self) -> None:
        """An exact substring should score better than a scattered fuzzy hit."""
        is_match_substr, score_substr = _fuzzy_match("gam", "gamma")
        is_match_scatter, score_scatter = _fuzzy_match("gma", "gamma")
        assert is_match_substr and is_match_scatter
        assert score_substr < score_scatter

    def test_scattered_match_prefers_earlier_characters(self) -> None:
        """Among two scattered matches, hitting characters earlier scores lower."""
        # "ab" fuzzy-matches "aXb" (score low: chars close to the front)
        # and "aXXXXb" (higher score: matched chars spread further apart).
        _, score_close = _fuzzy_match("ab", "aXb")
        _, score_far = _fuzzy_match("ab", "aXXXXb")
        assert score_close < score_far


class TestFuzzyItemDefaults:
    def test_defaults_are_empty_strings(self) -> None:
        item = FuzzyItem(text="hello", value="hello-value")
        assert item.text == "hello"
        assert item.value == "hello-value"
        assert item.meta == ""
        assert item.style == ""

    def test_all_fields_can_be_set(self) -> None:
        item = FuzzyItem(text="t", value="v", meta="m", style="fg:red")
        fields = (item.text, item.value, item.meta, item.style)
        assert fields == ("t", "v", "m", "fg:red")


# ---------------------------------------------------------------------------
# Basic navigation and selection
# ---------------------------------------------------------------------------


class TestBasicSelection:
    def test_no_items_returns_none_without_ui(self) -> None:
        # Guarded before the Application is even constructed.
        assert fuzzy_select(items=[]) is None

    def test_enter_selects_first_item_by_default(self) -> None:
        assert run_picker(ENTER, items=DEFAULT_ITEMS) == "a"

    def test_typing_query_filters_then_enter_selects_match(self) -> None:
        assert run_picker(f"bet{ENTER}", items=DEFAULT_ITEMS) == "b"

    def test_query_with_no_match_then_enter_returns_none(self) -> None:
        # No matches -> filtered_items is empty -> enter's guard leaves result None.
        assert run_picker(f"zzz{ENTER}", items=DEFAULT_ITEMS) is None

    def test_down_arrow_moves_to_next_item(self) -> None:
        assert run_picker(f"{DOWN}{ENTER}", items=DEFAULT_ITEMS) == "b"

    def test_ctrl_n_moves_to_next_item_like_down(self) -> None:
        assert run_picker(f"\x0e{ENTER}", items=DEFAULT_ITEMS) == "b"

    def test_down_wraps_from_last_to_first(self) -> None:
        keys = DOWN * 3  # alpha -> beta -> gamma -> wraps to alpha
        assert run_picker(f"{keys}{ENTER}", items=DEFAULT_ITEMS) == "a"

    def test_up_arrow_wraps_from_first_to_last(self) -> None:
        assert run_picker(f"{UP}{ENTER}", items=DEFAULT_ITEMS) == "g"

    def test_up_then_down_returns_to_first(self) -> None:
        assert run_picker(f"{UP}{DOWN}{ENTER}", items=DEFAULT_ITEMS) == "a"

    def test_initial_selection_preselects_item(self) -> None:
        assert run_picker(ENTER, items=DEFAULT_ITEMS, initial_selection=2) == "g"

    def test_initial_selection_out_of_range_clamps_to_last(self) -> None:
        assert run_picker(ENTER, items=DEFAULT_ITEMS, initial_selection=99) == "g"

    def test_item_meta_is_rendered_without_error(self) -> None:
        # Exercises the meta-text branch of the items-list renderer; the
        # DummyOutput discards the bytes but the formatted-text callback
        # still runs during the render cycle.
        items = [FuzzyItem(text="alpha", value="a", meta="(2 hours ago)")]
        assert run_picker(ENTER, items=items) == "a"

    def test_backspace_after_filtering_restores_full_list(self) -> None:
        # Filter down to "gamma" only, then backspace back to empty query,
        # then move down once: full list is restored so index 1 is "beta".
        keys = f"gam\x7f\x7f\x7f{DOWN}{ENTER}"
        assert run_picker(keys, items=DEFAULT_ITEMS) == "b"

    def test_filtering_resets_selection_to_top_match(self) -> None:
        # Select "gamma" (down x2), then type a query: selection resets to 0
        # (the top of the new filtered/sorted list), so Enter picks the best match.
        keys = f"{DOWN}{DOWN}alpha{ENTER}"
        assert run_picker(keys, items=DEFAULT_ITEMS) == "a"


class TestCancellation:
    def test_ctrl_c_cancels_and_returns_none(self) -> None:
        assert run_picker(CTRL_C, items=DEFAULT_ITEMS) is None

    def test_escape_without_callback_returns_none(self) -> None:
        assert run_picker(ESCAPE, items=DEFAULT_ITEMS) is None

    def test_escape_with_callback_returning_value_uses_it(self) -> None:
        result = run_picker(ESCAPE, items=DEFAULT_ITEMS, on_escape=lambda: "went-back")
        assert result == "went-back"

    def test_escape_with_callback_returning_none_stays_in_picker(self) -> None:
        # on_escape returning None means "don't exit"; a subsequent Enter
        # should still be able to select normally.
        result = run_picker(
            f"{ESCAPE}{ENTER}", items=DEFAULT_ITEMS, on_escape=lambda: None
        )
        assert result == "a"


# ---------------------------------------------------------------------------
# Callback-bound keys
# ---------------------------------------------------------------------------


class TestCallbackBoundKeys:
    def test_ctrl_d_triggers_on_tab_callback_with_current_value(self) -> None:
        """The ``on_tab`` callback fires on Ctrl+D, not the literal Tab key.

        See the module-level note below: this looks like a naming mismatch
        between the ``on_tab`` parameter/docstring and its actual binding.
        """
        seen = []

        def on_tab(value: str) -> str | None:
            seen.append(value)
            return f"tabbed:{value}"

        result = run_picker(CTRL_D, items=DEFAULT_ITEMS, on_tab=on_tab)
        assert result == "tabbed:a"
        assert seen == ["a"]

    def test_on_tab_returning_none_stays_in_picker(self) -> None:
        result = run_picker(
            f"{CTRL_D}{ENTER}", items=DEFAULT_ITEMS, on_tab=lambda value: None
        )
        assert result == "a"

    def test_literal_tab_key_does_not_trigger_on_tab(self) -> None:
        """A literal Tab keypress is not bound to anything special.

        This documents current behavior: only Ctrl+D reaches ``on_tab``.
        Sending Tab then Enter simply selects whatever was already focused.
        """
        result = run_picker(
            f"\t{ENTER}", items=DEFAULT_ITEMS, on_tab=lambda v: f"x:{v}"
        )
        assert result == "a"

    def test_ctrl_o_triggers_on_shift_enter_callback(self) -> None:
        result = run_picker(
            CTRL_O, items=DEFAULT_ITEMS, on_shift_enter=lambda value: f"shift:{value}"
        )
        assert result == "shift:a"

    def test_ctrl_o_with_no_callback_stays_in_picker(self) -> None:
        result = run_picker(f"{CTRL_O}{ENTER}", items=DEFAULT_ITEMS)
        assert result == "a"

    def test_ctrl_a_triggers_on_ctrl_a_callback(self) -> None:
        result = run_picker(CTRL_A, items=DEFAULT_ITEMS, on_ctrl_a=lambda: "ctrl-a-val")
        assert result == "ctrl-a-val"

    def test_ctrl_s_triggers_on_ctrl_s_callback(self) -> None:
        result = run_picker(CTRL_S, items=DEFAULT_ITEMS, on_ctrl_s=lambda: "ctrl-s-val")
        assert result == "ctrl-s-val"

    def test_ctrl_w_triggers_on_ctrl_w_callback(self) -> None:
        result = run_picker(CTRL_W, items=DEFAULT_ITEMS, on_ctrl_w=lambda: "ctrl-w-val")
        assert result == "ctrl-w-val"

    def test_ctrl_p_triggers_on_ctrl_p_callback(self) -> None:
        result = run_picker(CTRL_P, items=DEFAULT_ITEMS, on_ctrl_p=lambda: "ctrl-p-val")
        assert result == "ctrl-p-val"

    def test_ctrl_p_does_not_move_selection(self) -> None:
        """Docstring notes Ctrl+P is no longer bound to up-navigation."""
        # No on_ctrl_p callback -> the keypress is a no-op, selection stays put.
        result = run_picker(f"{CTRL_P}{ENTER}", items=DEFAULT_ITEMS)
        assert result == "a"

    @pytest.mark.parametrize(
        "kwarg_name",
        ["on_ctrl_a", "on_ctrl_s", "on_ctrl_w"],
    )
    def test_callback_returning_none_stays_in_picker(self, kwarg_name: str) -> None:
        key_by_kwarg = {"on_ctrl_a": CTRL_A, "on_ctrl_s": CTRL_S, "on_ctrl_w": CTRL_W}
        kwargs = {kwarg_name: lambda: None}
        keys = f"{key_by_kwarg[kwarg_name]}{ENTER}"
        result = run_picker(keys, items=DEFAULT_ITEMS, **kwargs)
        assert result == "a"


# ---------------------------------------------------------------------------
# Refiners (run off the loop after the first paint, merged with update_items)
# ---------------------------------------------------------------------------


class TestRefiners:
    def test_refiner_updates_items_off_the_picker_thread(self) -> None:
        refined = threading.Event()
        seen: dict[str, Any] = {}

        def refiner(cancel: threading.Event) -> list[FuzzyItem]:
            seen["thread"] = threading.current_thread()
            seen["cancel_type"] = type(cancel)
            refined.set()
            return make_items(("alpha", "a"), ("beta", "b"), ("gamma", "g"))

        with create_pipe_input() as inp:
            thread, holder = _run_in_thread(
                inp, items=make_items(("alpha", "a")), refiners=[refiner]
            )
            assert refined.wait(timeout=3), "refiner never ran"
            time.sleep(0.2)  # let the loop merge the result before we move
            _finish(inp, thread, f"{DOWN}{ENTER}")

        # Down moved onto the appended "beta": the refinement was applied.
        assert holder["value"] == "b"
        assert seen["thread"] is not thread
        assert seen["thread"] is not threading.main_thread()
        assert seen["cancel_type"] is threading.Event

    def test_enter_after_refinement_selects_first_item(self) -> None:
        refined = threading.Event()

        def refiner(cancel: threading.Event) -> list[FuzzyItem]:
            refined.set()
            return make_items(("alpha", "a"), ("beta", "b"))

        with create_pipe_input() as inp:
            thread, holder = _run_in_thread(
                inp, items=make_items(("alpha", "a")), refiners=[refiner]
            )
            assert refined.wait(timeout=3)
            _finish(inp, thread, ENTER)
        assert holder["value"] == "a"

    def test_refiner_preserves_selection_of_still_present_item(self) -> None:
        refined = threading.Event()

        def refiner(cancel: threading.Event) -> list[FuzzyItem]:
            refined.set()
            # "beta" remains; "gamma" is dropped, "delta" is added.
            return make_items(("alpha", "a"), ("beta", "b"), ("delta", "d"))

        with create_pipe_input() as inp:
            thread, holder = _run_in_thread(
                inp,
                items=make_items(("alpha", "a"), ("beta", "b"), ("gamma", "g")),
                initial_selection=1,
                refiners=[refiner],
            )
            assert refined.wait(timeout=3)
            time.sleep(0.2)
            _finish(inp, thread, ENTER)
        assert holder["value"] == "b"

    def test_refiner_refreshes_metadata_in_place(self) -> None:
        refined = threading.Event()

        def refiner(cancel: threading.Event) -> list[FuzzyItem]:
            refined.set()
            return [FuzzyItem(text="alpha", value="a", meta="dirty", style="fg:red")]

        with create_pipe_input() as inp:
            thread, holder = _run_in_thread(
                inp,
                items=[FuzzyItem(text="alpha", value="a", meta="clean")],
                refiners=[refiner],
            )
            assert refined.wait(timeout=3)
            time.sleep(0.2)
            _finish(inp, thread, ENTER)
        assert holder["value"] == "a"

    def test_refiner_returning_none_keeps_items(self) -> None:
        with create_pipe_input() as inp:
            thread, holder = _run_in_thread(
                inp, items=DEFAULT_ITEMS, refiners=[lambda cancel: None]
            )
            time.sleep(0.2)
            _finish(inp, thread, f"{DOWN}{ENTER}")
        assert holder["value"] == "b"

    def test_failing_refiner_is_ignored(self) -> None:
        def refiner(cancel: threading.Event) -> list[FuzzyItem]:
            raise RuntimeError("git exploded")

        with create_pipe_input() as inp:
            thread, holder = _run_in_thread(
                inp, items=DEFAULT_ITEMS, refiners=[refiner]
            )
            time.sleep(0.2)
            _finish(inp, thread, ENTER)
        assert holder["value"] == "a"

    def test_refiners_are_cancelled_on_exit(self) -> None:
        started = threading.Event()
        seen: dict[str, Any] = {}

        def refiner(cancel: threading.Event) -> None:
            started.set()
            seen["cancelled"] = cancel.wait(2)
            return None

        with create_pipe_input() as inp:
            thread, holder = _run_in_thread(
                inp, items=DEFAULT_ITEMS, refiners=[refiner]
            )
            assert started.wait(timeout=3)
            before = time.monotonic()
            # Ctrl+C, not Escape: prompt_toolkit waits ttimeoutlen + timeoutlen
            # (1.5 s) after a lone ESC byte before acting on it.
            _finish(inp, thread, CTRL_C)
            assert time.monotonic() - before < 1.0
        assert holder["value"] is None
        assert seen.get("cancelled") is True

    def test_refiner_that_ignores_cancel_does_not_delay_exit(self) -> None:
        started = threading.Event()

        def refiner(cancel: threading.Event) -> None:
            started.set()
            time.sleep(3)  # a hung `git fetch` stand-in
            return None

        with create_pipe_input() as inp:
            thread, holder = _run_in_thread(
                inp, items=DEFAULT_ITEMS, refiners=[refiner]
            )
            assert started.wait(timeout=3)
            inp.send_text(ENTER)
            thread.join(timeout=1.5)
            assert not thread.is_alive(), "exit waited for the refiner thread"
        assert holder["value"] == "a"


# ---------------------------------------------------------------------------
# Auto-select
# ---------------------------------------------------------------------------


class TestAutoSelect:
    def test_zero_timeout_returns_instantly_without_ui(self) -> None:
        # `run_picker` still routes through the real app-session/output patch
        # even though no keys are queued: the function returns before
        # constructing the Application when auto_select_timeout <= 0, so this
        # never blocks on input.
        result = run_picker(
            "", items=DEFAULT_ITEMS, auto_select_value="b", auto_select_timeout=0
        )
        assert result == "b"

    def test_negative_timeout_also_returns_instantly(self) -> None:
        result = run_picker(
            "", items=DEFAULT_ITEMS, auto_select_value="g", auto_select_timeout=-1
        )
        assert result == "g"

    def test_short_timeout_auto_selects_when_no_keys_pressed(self) -> None:
        # Run on a background thread with a bounded join so a missed
        # app.exit() from the timer thread fails the test instead of
        # hanging the run.
        result_holder: dict[str, str | None] = {}

        with create_pipe_input() as inp:

            def worker() -> None:
                result_holder["value"] = _run_with_input(
                    inp,
                    items=DEFAULT_ITEMS,
                    auto_select_value="b",
                    auto_select_timeout=0.2,
                )

            thread = threading.Thread(target=worker, daemon=True)
            thread.start()
            # Auto-select polls on a 0.5s cadence, so a 0.2s timeout can take
            # a bit longer to fire; 5s is a generous ceiling for CI jitter.
            thread.join(timeout=5)
            assert not thread.is_alive(), "auto-select timer never fired"

        assert result_holder["value"] == "b"

    def test_keypress_cancels_auto_select(self) -> None:
        """A keypress before the timer fires cancels it; manual selection wins."""
        with create_pipe_input() as inp:
            inp.send_text(DOWN)  # cancels the timer, moves to "beta"
            time.sleep(0.05)
            inp.send_text(ENTER)

            result = _run_with_input(
                inp,
                items=DEFAULT_ITEMS,
                auto_select_value="AUTO-SENTINEL",
                auto_select_timeout=2.0,
            )

        # If cancellation had failed, the 2s timer would have overwritten the
        # manual selection with the sentinel value instead.
        assert result == "b"
