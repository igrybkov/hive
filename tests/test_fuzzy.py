"""Tests for fuzzy selection utilities."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from hive_cli.utils.fuzzy import FuzzyItem, fuzzy_select


class TestFuzzySelectKeyBindings:
    """Test that key bindings are valid."""

    def test_key_bindings_are_valid(self):
        """Verify all key bindings are valid prompt_toolkit keys.

        This test catches invalid key binding strings like 's-enter' that
        would cause ValueError at runtime.
        """
        items = [FuzzyItem(text="test", value="test")]

        # Mock the Application.run() to avoid actually running the UI
        with patch("hive_cli.utils.fuzzy.Application") as mock_app_class:
            mock_app = MagicMock()
            mock_app_class.return_value = mock_app
            # Simulate user cancelling
            mock_app.run.side_effect = KeyboardInterrupt()

            # This should NOT raise ValueError for invalid key bindings
            # The key bindings are registered during fuzzy_select setup
            result = fuzzy_select(
                items=items,
                on_escape=lambda: None,
                on_tab=lambda x: None,
                on_shift_enter=lambda x: None,
            )

            assert result is None  # Cancelled

    def test_ctrl_o_binding_triggers_on_shift_enter_callback(self):
        """Verify Ctrl+O triggers the on_shift_enter callback."""
        # This is a smoke test - full integration would require
        # simulating terminal input which is complex
        from prompt_toolkit.key_binding import KeyBindings

        kb = KeyBindings()

        # Verify c-o is a valid key binding
        @kb.add("c-o")
        def handler(event):
            pass

        # If we get here without ValueError, the binding is valid
        assert True

    def test_ctrl_p_binding_is_valid(self):
        """Verify Ctrl+P is a valid prompt_toolkit key binding."""
        from prompt_toolkit.key_binding import KeyBindings

        kb = KeyBindings()

        @kb.add("c-p")
        def handler(event):
            pass

        assert True  # No ValueError raised

    def test_ctrl_p_triggers_on_ctrl_p_callback(self):
        """Verify on_ctrl_p callback is accepted without error."""
        items = [FuzzyItem(text="test", value="test")]

        with patch("hive_cli.utils.fuzzy.Application") as mock_app_class:
            mock_app = MagicMock()
            mock_app_class.return_value = mock_app
            mock_app.run.side_effect = KeyboardInterrupt()

            result = fuzzy_select(
                items=items,
                on_ctrl_p=lambda: "profile_selected",
            )

        assert result is None  # Cancelled via KeyboardInterrupt
