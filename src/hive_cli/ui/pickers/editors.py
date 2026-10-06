"""Editor picker for the "open worktree in editor" action.

Moved from utils/editors.py (A0 step 9). EditorConfig/get_available_editors/
open_in_editor live in services/editors.py.
"""

from __future__ import annotations

from ...services import editors
from ..console import error
from .fuzzy import FuzzyItem, fuzzy_select


def select_editor() -> editors.EditorConfig | None:
    """Show picker for selecting an editor.

    Returns:
        Selected EditorConfig, or None if cancelled.
    """
    available = editors.get_available_editors()
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
