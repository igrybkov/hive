"""Interactive worktree picker and detail screen for `hive status`."""

from __future__ import annotations

import select
import sys
import termios
import tty as tty_module
from dataclasses import dataclass
from pathlib import Path

from rich.text import Text

from ...git import (
    delete_worktree,
    get_git_status_detail,
    get_main_repo,
    get_recent_commits,
    get_worktree_path,
    is_worktree_dirty,
)
from ...services import editors
from ...services import status as service_status
from ...services.status import AgentStatus
from ...utils import select_editor
from ..console import error, warn
from ..console import out as console
from ..tty import confirm
from ..views import status as status_views
from .fuzzy import FuzzyItem, fuzzy_select

# Action sentinels for interactive mode
ACTION_DELETE_PREFIX = "__delete__:"
ACTION_OPEN_IN_EDITOR_PREFIX = "__open_in_editor__:"


def _clear_screen_full() -> None:
    """Clear screen including scrollback buffer."""
    # \033[2J - clear screen
    # \033[3J - clear scrollback buffer
    # \033[H - move cursor to home
    sys.stdout.write("\033[2J\033[3J\033[H")
    sys.stdout.flush()


def _build_fuzzy_item(status: AgentStatus) -> FuzzyItem:
    """Build a FuzzyItem from an AgentStatus.

    Args:
        status: Agent status information.

    Returns:
        FuzzyItem for fuzzy selection.
    """
    # Build display text with status indicators
    dirty_indicator = "*" if status.is_dirty else ""

    ahead_behind = ""
    if status.ahead > 0:
        ahead_behind += f"+{status.ahead}"
    if status.behind > 0:
        ahead_behind += f"-{status.behind}"

    # Format: branch_name * [+2-1]
    text_parts = [status.branch]
    if dirty_indicator:
        text_parts.append(dirty_indicator)
    if ahead_behind:
        text_parts.append(f"[{ahead_behind}]")

    text = " ".join(text_parts)

    # Meta: commit info and task
    meta_parts = [f"{status.last_commit_hash} {status.last_commit_msg[:30]}"]
    if status.task:
        meta_parts.append(f"| {status.task[:30]}")
    meta = " ".join(meta_parts)

    # Style based on status
    if status.is_main:
        style = "bold cyan"
    elif status.is_dirty:
        style = "yellow"
    else:
        style = "green"

    return FuzzyItem(
        text=text,
        value=status.branch,
        meta=meta,
        style=style,
    )


# --- detail screen key handling ---


@dataclass
class _DetailState:
    """Mutable state shared by the detail screen's key handlers and renderer."""

    content_parts: list[tuple[str, str]]
    total_lines: int
    result: str | None = None
    scroll_offset: int = 0


def _scrolled_content(state: _DetailState):
    """Visible content starting at the current scroll offset."""
    from prompt_toolkit.formatted_text import FormattedText

    offset = state.scroll_offset
    parts: list[tuple[str, str]] = []
    line_count = 0

    for style, text in state.content_parts:
        for char in text:
            if char == "\n":
                line_count += 1
                if line_count > offset:
                    parts.append((style, char))
            elif line_count >= offset:
                parts.append((style, char))

    if not parts:
        # Fallback - show from beginning
        return FormattedText(state.content_parts)
    return FormattedText(parts)


def _make_result_handler(state: _DetailState, value: str):
    def handler(event):
        state.result = value
        event.app.exit()

    return handler


def _make_scroll_handler(state: _DetailState, delta: int):
    def handler(event):
        state.scroll_offset = max(
            0, min(state.total_lines - 1, state.scroll_offset + delta)
        )

    return handler


def _make_go_top_handler(state: _DetailState):
    def handler(event):
        state.scroll_offset = 0

    return handler


def _make_go_bottom_handler(state: _DetailState):
    def handler(event):
        state.scroll_offset = max(0, state.total_lines - 10)

    return handler


def _apply_detail_result(
    result: str | None, status: AgentStatus, main_repo: Path
) -> tuple[str | None, bool]:
    """Act on the detail screen's key-handler result.

    Returns:
        (outcome, should_continue): _show_worktree_detail returns ``outcome``
        unless ``should_continue`` says to rebuild the screen and loop again.
    """
    if result == "back":
        return "back", False
    if result == "quit":
        return "quit", False
    if result == "editor":
        editor = select_editor()
        if editor:
            editors.open_in_editor(status.path, editor)
        return None, True
    if result == "delete":
        _clear_screen_full()
        if _delete_worktree_flow(status.branch, main_repo):
            return "deleted", False
        return None, True
    return None, False


def _show_worktree_detail(status: AgentStatus, main_repo: Path) -> str | None:
    """Show detailed worktree info panel with actions.

    Args:
        status: Agent status for the worktree.
        main_repo: Path to main repository.

    Returns:
        Action result: "back" to return to picker, "quit" to exit, or None.
    """
    from prompt_toolkit import Application
    from prompt_toolkit.formatted_text import FormattedText
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import (
        FormattedTextControl,
        HSplit,
        Layout,
        Window,
    )
    from prompt_toolkit.output import create_output

    while True:
        # Get detailed info
        content_parts = status_views.build_detail_content(
            status,
            get_git_status_detail(status.path),
            get_recent_commits(status.path),
        )
        content_text = "".join(text for _, text in content_parts)
        state = _DetailState(
            content_parts=content_parts,
            total_lines=len(content_text.split("\n")),
        )

        # Key bindings
        kb = KeyBindings()
        kb.add("escape")(_make_result_handler(state, "back"))
        kb.add("q")(_make_result_handler(state, "quit"))
        kb.add("c-c")(_make_result_handler(state, "quit"))
        kb.add("e")(_make_result_handler(state, "editor"))
        kb.add("d")(_make_result_handler(state, "delete"))

        scroll_up = _make_scroll_handler(state, -3)
        kb.add("up")(scroll_up)
        kb.add("k")(scroll_up)
        scroll_down = _make_scroll_handler(state, 3)
        kb.add("down")(scroll_down)
        kb.add("j")(scroll_down)
        page_up = _make_scroll_handler(state, -20)
        kb.add("pageup")(page_up)
        kb.add("c-u")(page_up)
        page_down = _make_scroll_handler(state, 20)
        kb.add("pagedown")(page_down)
        kb.add("c-d")(page_down)

        go_top = _make_go_top_handler(state)
        kb.add("home")(go_top)
        kb.add("g")(go_top)
        go_bottom = _make_go_bottom_handler(state)
        kb.add("end")(go_bottom)
        kb.add("G")(go_bottom)

        # Layout
        content_window = Window(
            content=FormattedTextControl(lambda: _scrolled_content(state)),
            wrap_lines=True,
        )

        hint_text = (
            " Esc back  e editor  d delete  q quit  "
            "↑↓/jk scroll  ^U/^D page  g/G top/bottom"
        )
        hint_window = Window(
            content=FormattedTextControl(FormattedText([("fg:gray", hint_text)])),
            height=1,
        )

        layout = Layout(
            HSplit(
                [
                    content_window,
                    Window(height=1, char="─", style="fg:cyan"),
                    hint_window,
                ]
            )
        )

        # Application
        app: Application[None] = Application(
            layout=layout,
            key_bindings=kb,
            full_screen=True,
            mouse_support=True,
            output=create_output(stdout=sys.stderr),
        )

        try:
            app.run()
        except KeyboardInterrupt:
            return "quit"

        outcome, should_continue = _apply_detail_result(state.result, status, main_repo)
        if should_continue:
            continue
        return outcome


def _delete_worktree_flow(branch: str, main_repo: Path) -> bool:
    """Handle worktree deletion with confirmation.

    Args:
        branch: Branch name of worktree to delete.
        main_repo: Path to main repository.

    Returns:
        True if deleted, False otherwise.
    """
    # Can't delete main
    if branch in ("main", "master", "1"):
        warn("Cannot delete main repository")
        return False

    path = get_worktree_path(branch, main_repo)
    if not path.exists():
        warn(f"No worktree exists for '{branch}'")
        return False

    is_dirty = is_worktree_dirty(path)

    if is_dirty:
        error("Uncommitted changes will be lost!")

    if confirm(f"Delete worktree '{branch}'?"):
        try:
            delete_worktree(path, force=True)
            console.print(f"[green]Worktree '{branch}' deleted[/]")
            return True
        except Exception as e:
            error(f"Failed to delete: {e}")
            return False

    return False


def _handle_picker_selection(
    selected: str, statuses: list[AgentStatus], main_repo: Path
) -> tuple[str | None, bool]:
    """Handle one fuzzy_select result from the worktree picker.

    Returns:
        (outcome, refetch): outcome is "quit" to stop entirely, else None to
        keep looping; refetch says whether statuses should be re-collected
        before the next iteration.
    """
    if selected.startswith(ACTION_DELETE_PREFIX):
        branch_to_delete = selected[len(ACTION_DELETE_PREFIX) :]
        _delete_worktree_flow(branch_to_delete, main_repo)
        return None, True

    if selected.startswith(ACTION_OPEN_IN_EDITOR_PREFIX):
        branch_to_open = selected[len(ACTION_OPEN_IN_EDITOR_PREFIX) :]
        path_by_branch = {s.branch: s.path for s in statuses}
        worktree_path = path_by_branch.get(branch_to_open)
        if worktree_path:
            editor = select_editor()
            if editor:
                editors.open_in_editor(worktree_path, editor)
        return None, False

    status_by_branch = {s.branch: s for s in statuses}
    selected_status = status_by_branch.get(selected)
    if selected_status is None:
        return "quit", False

    result = _show_worktree_detail(selected_status, main_repo)
    if result == "quit":
        return "quit", False
    return None, result == "deleted"


def interactive_status(
    statuses: list[AgentStatus] | None = None,
    main_repo: Path | None = None,
) -> str | None:
    """Run interactive status selection.

    Args:
        statuses: Pre-collected statuses (to avoid re-fetching).
        main_repo: Main repository path.

    Returns:
        Path to selected worktree (for cd), or None if cancelled/action taken.
    """
    if main_repo is None:
        main_repo = get_main_repo()

    while True:
        # Only collect if not provided (first call) or after an action
        if statuses is None:
            statuses = service_status.collect_status(main_repo)

        if not statuses:
            error("No worktrees found")
            return None

        # Build fuzzy items from statuses
        items = [_build_fuzzy_item(s) for s in statuses]

        # Show fuzzy finder
        selected = fuzzy_select(
            items=items,
            prompt_text=">",
            header=f"Select worktree - {main_repo.name}",
            hint=(
                "</dim><b>Enter</b><dim> details  "
                "</dim><b>^O</b><dim> editor  "
                "</dim><b>^D</b><dim> delete  "
                "</dim><b>Esc</b><dim> back"
            ),
            on_tab=lambda branch: f"{ACTION_DELETE_PREFIX}{branch}",
            on_shift_enter=lambda branch: f"{ACTION_OPEN_IN_EDITOR_PREFIX}{branch}",
        )

        if selected is None:
            return None

        outcome, refetch = _handle_picker_selection(selected, statuses, main_repo)
        if outcome == "quit":
            return None
        if refetch:
            statuses = None


def _render_watch_frame(
    statuses: list[AgentStatus], main_repo: Path, compact: bool
) -> None:
    """Redraw one watch-mode frame: status board plus the keypress hint."""
    console.clear()

    if compact:
        output = status_views.build_compact_output(statuses, main_repo)
    else:
        output = status_views.build_full_output(statuses, main_repo)

    console.print(output)
    console.print()
    console.print(
        Text.from_markup(
            "[dim]Press [bold]Enter[/bold] to select worktree, "
            "[bold]q[/bold] to quit[/dim]"
        )
    )


def _wait_and_react_to_keypress(
    fd: int,
    old_settings,
    statuses: list[AgentStatus],
    main_repo: Path,
) -> bool:
    """Wait up to 2s for a keypress in watch mode and react to it.

    Returns:
        True if watch mode should quit entirely, False to redraw and
        keep watching.
    """
    for _ in range(20):  # 20 * 0.1s = 2s
        ready, _, _ = select.select([fd], [], [], 0.1)
        if not ready:
            continue

        key = sys.stdin.read(1)
        # Restore terminal before any action
        termios.tcsetattr(fd, termios.TCSANOW, old_settings)

        if key in ("\r", "\n"):
            # Enter - go to interactive mode
            console.clear()
            interactive_status(statuses=statuses, main_repo=main_repo)
            return False
        if key.lower() == "q" or key == "\x03":  # q or Ctrl+C
            return True
        # Unknown key, set raw mode again and keep waiting
        tty_module.setraw(fd)

    # Timeout - restore terminal for next display cycle
    termios.tcsetattr(fd, termios.TCSANOW, old_settings)
    return False


def watch_interactive_loop(compact: bool = False) -> None:
    """Run watch mode with interactive selection on keypress.

    Shows status board that refreshes every 2 seconds.
    Press Enter to open interactive picker, then returns to watch mode.
    Press 'q' to quit.

    Args:
        compact: If True, use single-line-per-agent format.
    """
    main_repo = get_main_repo()

    try:
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            while True:
                statuses = service_status.collect_status(main_repo)
                _render_watch_frame(statuses, main_repo, compact)

                # Set raw mode for keypress detection
                tty_module.setraw(fd)

                if _wait_and_react_to_keypress(fd, old_settings, statuses, main_repo):
                    return
        finally:
            # Always restore terminal settings
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

    except KeyboardInterrupt:
        pass
    except (OSError, EOFError):
        pass
