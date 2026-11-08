"""Modal screens for the control-plane TUI (F4): confirm, detail, help, and
the bundled/user tool-tab picker. Each is self-contained (its own small
DEFAULT_CSS) so `app.py` only carries the layout for its own widgets.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import ModalScreen
from textual.widgets import Label, ListItem, ListView, Static

from ...services import aio
from .model import PaneRow


class ConfirmScreen(ModalScreen[bool]):
    """A yes/no question; dismisses with True/False."""

    DEFAULT_CSS = """
    ConfirmScreen {
        align: center middle;
    }
    ConfirmScreen > Static {
        width: auto;
        border: round $accent;
        padding: 1 2;
    }
    """
    BINDINGS = [
        Binding("y", "confirm", "Yes"),
        Binding("n", "cancel", "No"),
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    def __init__(self, question: str) -> None:
        super().__init__()
        self._question = question

    def compose(self) -> ComposeResult:
        yield Static(f"{self._question} (y/n)")

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)


class HelpScreen(ModalScreen[None]):
    """Static key-binding reference."""

    DEFAULT_CSS = """
    HelpScreen {
        align: center middle;
    }
    HelpScreen > Static {
        width: auto;
        border: round $accent;
        padding: 1 2;
    }
    """
    BINDINGS = [
        Binding("escape", "close", "Close", show=False),
        Binding("q", "close", "Close", show=False),
    ]

    def __init__(self, text: str) -> None:
        super().__init__()
        self._text = text

    def compose(self) -> ComposeResult:
        yield Static(self._text)

    def action_close(self) -> None:
        self.dismiss(None)


class TabPickerScreen(ModalScreen[str | None]):
    """Pick a bundled or user-defined tool tab by name; None on cancel."""

    DEFAULT_CSS = """
    TabPickerScreen {
        align: center middle;
    }
    TabPickerScreen > ListView {
        width: auto;
        height: auto;
        max-height: 80%;
        border: round $accent;
    }
    """
    BINDINGS = [Binding("escape", "cancel", "Cancel", show=False)]

    def __init__(self, names: Sequence[str]) -> None:
        super().__init__()
        self._names = list(names)

    def compose(self) -> ComposeResult:
        yield ListView(*(ListItem(Label(name), name=name) for name in self._names))

    def on_mount(self) -> None:
        self.query_one(ListView).focus()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        self.dismiss(event.item.name)

    def action_cancel(self) -> None:
        self.dismiss(None)


class DetailScreen(ModalScreen[None]):
    """Git status + recent commits for one pane's worktree, loaded off-thread."""

    DEFAULT_CSS = """
    DetailScreen {
        align: center middle;
    }
    DetailScreen > Static {
        width: 80%;
        height: 80%;
        border: round $accent;
        padding: 1 2;
        overflow-y: auto;
    }
    """
    BINDINGS = [
        Binding("escape", "close", "Close", show=False),
        Binding("q", "close", "Close", show=False),
    ]

    def __init__(self, row: PaneRow, detail_loader: Callable[[], str]) -> None:
        super().__init__()
        self._row = row
        self._detail_loader = detail_loader

    def compose(self) -> ComposeResult:
        yield Static("Loading...")

    async def on_mount(self) -> None:
        text = await aio.call(self._detail_loader)
        self.query_one(Static).update(text)

    def action_close(self) -> None:
        self.dismiss(None)
