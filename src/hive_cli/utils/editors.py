"""Editor picker for the "open worktree in editor" action.

NOTE (A0 step 6): EditorConfig/get_available_editors/open_in_editor moved
to services/editors.py (re-exported here so existing callers --
commands/status.py, commands/wt.py -- don't need touching this step; see
that module's docstring for why open_in_editor still prints directly).
select_editor() itself moves to ui/pickers/editors.py in step 7, once that
package exists.
"""

from __future__ import annotations

from ..services import editors
from ..ui.console import error
from .fuzzy import FuzzyItem, fuzzy_select

# Re-exported as top-level names (not `from ..services.editors import name, ...`)
# so tests/test_architecture.py's cross-layer-imports-are-modules rule holds.
EditorConfig = editors.EditorConfig
get_available_editors = editors.get_available_editors
open_in_editor = editors.open_in_editor

__all__ = [
    "EditorConfig",
    "get_available_editors",
    "open_in_editor",
    "select_editor",
]


def select_editor() -> EditorConfig | None:
    """Show picker for selecting an editor.

    Returns:
        Selected EditorConfig, or None if cancelled.
    """
    available = get_available_editors()
    if not available:
        error("No supported editors found (code, cursor, pycharm)")
        return None

    if len(available) == 1:
        return available[0]

    items = [FuzzyItem(text=e.name, value=e.command, meta="") for e in available]

    selected = fuzzy_select(
        items=items,
        prompt_text=">",
        header="Select editor",
        hint="</dim><b>Enter</b><dim> select  </dim><b>Esc</b><dim> back",
    )

    if selected is None:
        return None

    return next((e for e in available if e.command == selected), None)
