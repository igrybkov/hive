"""Status command - display status of all agent worktrees."""

from __future__ import annotations

import select
import subprocess
import sys
import termios
import time
import tty as tty_module
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

from cyclopts import App, Parameter
from rich.console import Console, Group
from rich.text import Text

from ..git import (
    delete_worktree,
    get_current_branch,
    get_main_repo,
    get_worktree_path,
    is_worktree_dirty,
    list_worktrees,
)
from ..utils import (
    FuzzyItem,
    confirm,
    error,
    fuzzy_select,
    open_in_editor,
    select_editor,
    warn,
)

# Console for output (stdout for status display)
console = Console()


def _clear_screen_full() -> None:
    """Clear screen including scrollback buffer."""
    # \033[2J - clear screen
    # \033[3J - clear scrollback buffer
    # \033[H - move cursor to home
    sys.stdout.write("\033[2J\033[3J\033[H")
    sys.stdout.flush()


@dataclass
class AgentStatus:
    """Status information for an agent worktree."""

    agent_id: str
    path: Path
    branch: str
    is_main: bool
    is_dirty: bool
    ahead: int
    behind: int
    last_commit_hash: str
    last_commit_msg: str
    task: str | None


def _get_ahead_behind(path: Path) -> tuple[int, int]:
    """Get commits ahead/behind upstream.

    Args:
        path: Path to the worktree.

    Returns:
        Tuple of (ahead, behind) counts.
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--abbrev-ref", "@{upstream}"],
            capture_output=True,
            text=True,
            check=True,
        )
        upstream = result.stdout.strip()
    except subprocess.CalledProcessError:
        return 0, 0

    try:
        result = subprocess.run(
            ["git", "-C", str(path), "rev-list", "--count", f"{upstream}..HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        ahead = int(result.stdout.strip())
    except (subprocess.CalledProcessError, ValueError):
        ahead = 0

    try:
        result = subprocess.run(
            ["git", "-C", str(path), "rev-list", "--count", f"HEAD..{upstream}"],
            capture_output=True,
            text=True,
            check=True,
        )
        behind = int(result.stdout.strip())
    except (subprocess.CalledProcessError, ValueError):
        behind = 0

    return ahead, behind


def _get_last_commit(path: Path) -> tuple[str, str]:
    """Get last commit hash and message.

    Args:
        path: Path to the worktree.

    Returns:
        Tuple of (short_hash, message).
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(path), "log", "-1", "--format=%h\t%s"],
            capture_output=True,
            text=True,
            check=True,
        )
        parts = result.stdout.strip().split("\t", 1)
        if len(parts) == 2:
            return parts[0], parts[1][:50]
        return parts[0] if parts else "", ""
    except subprocess.CalledProcessError:
        return "", ""


@dataclass
class GitStatusDetail:
    """Detailed git status for a worktree."""

    staged: list[str]  # Staged files (index)
    unstaged: list[str]  # Modified but not staged
    untracked: list[str]  # Untracked files


@dataclass
class CommitInfo:
    """Information about a commit."""

    hash: str
    message: str
    author: str
    date: str


def _get_git_status_detail(path: Path) -> GitStatusDetail:
    """Get detailed git status for a worktree.

    Args:
        path: Path to the worktree.

    Returns:
        GitStatusDetail with staged, unstaged, and untracked files.
    """
    staged = []
    unstaged = []
    untracked = []

    try:
        result = subprocess.run(
            ["git", "-C", str(path), "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=True,
        )
        for line in result.stdout.splitlines():
            if not line:
                continue
            index_status = line[0]
            worktree_status = line[1]
            filename = line[3:]

            # Staged changes (in index)
            if index_status in ("A", "M", "D", "R", "C"):
                staged.append(f"{index_status} {filename}")

            # Unstaged changes (in worktree)
            if worktree_status in ("M", "D"):
                unstaged.append(f"{worktree_status} {filename}")

            # Untracked files
            if index_status == "?" and worktree_status == "?":
                untracked.append(filename)

    except subprocess.CalledProcessError:
        pass

    return GitStatusDetail(staged=staged, unstaged=unstaged, untracked=untracked)


def _get_recent_commits(path: Path, count: int = 5) -> list[CommitInfo]:
    """Get recent commits for a worktree.

    Args:
        path: Path to the worktree.
        count: Number of commits to retrieve.

    Returns:
        List of CommitInfo objects.
    """
    commits = []
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(path),
                "log",
                f"-{count}",
                "--format=%h\t%s\t%an\t%cr",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        for line in result.stdout.splitlines():
            if not line:
                continue
            parts = line.split("\t")
            if len(parts) >= 4:
                commits.append(
                    CommitInfo(
                        hash=parts[0],
                        message=parts[1][:50],
                        author=parts[2],
                        date=parts[3],
                    )
                )
    except subprocess.CalledProcessError:
        pass

    return commits


def _get_task(main_repo: Path, agent_id: str) -> str | None:
    """Get task content for an agent.

    Args:
        main_repo: Path to main repository.
        agent_id: Agent identifier.

    Returns:
        First non-empty, non-header line of task file, or None.
    """
    task_file = (
        main_repo / ".claude" / "local-agents" / "tasks" / f"agent-{agent_id}.md"
    )
    if not task_file.exists():
        return None

    try:
        content = task_file.read_text()
        for line in content.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                return line[:60]
        return None
    except OSError:
        return None


def _collect_status(main_repo: Path) -> list[AgentStatus]:
    """Collect status for all agent worktrees.

    Args:
        main_repo: Path to main repository.

    Returns:
        List of AgentStatus objects.
    """
    statuses = []
    worktrees = list_worktrees(main_repo)

    for wt in worktrees:
        if wt.is_main:
            agent_id = "1"
            # For main repo, check if on non-default branch
            current = get_current_branch(wt.path)
            branch = current if current else "main"
        else:
            # Use branch name as agent ID
            agent_id = wt.branch
            branch = wt.branch

        ahead, behind = _get_ahead_behind(wt.path)
        commit_hash, commit_msg = _get_last_commit(wt.path)

        statuses.append(
            AgentStatus(
                agent_id=agent_id,
                path=wt.path,
                branch=branch,
                is_main=wt.is_main,
                is_dirty=is_worktree_dirty(wt.path),
                ahead=ahead,
                behind=behind,
                last_commit_hash=commit_hash,
                last_commit_msg=commit_msg,
                task=_get_task(main_repo, agent_id),
            )
        )

    return statuses


def _get_shared_notes_summary(main_repo: Path) -> tuple[int, str | None]:
    """Get shared notes summary.

    Args:
        main_repo: Path to main repository.

    Returns:
        Tuple of (line_count, last_entry_header).
    """
    notes_file = main_repo / ".claude" / "local-agents" / "shared-notes.md"
    if not notes_file.exists():
        return 0, None

    try:
        content = notes_file.read_text()
        lines = content.splitlines()
        line_count = len(lines)

        # Find last ## header
        last_header = None
        for line in reversed(lines):
            if line.startswith("## "):
                last_header = line[3:]
                break

        return line_count, last_header
    except OSError:
        return 0, None


def _build_full_output(statuses: list[AgentStatus], main_repo: Path) -> Group:
    """Build full status view as a renderable.

    Args:
        statuses: List of agent statuses.
        main_repo: Path to main repository.

    Returns:
        Group of Text objects for rendering.
    """
    lines = []
    lines.append(Text(""))
    lines.append(Text.from_markup("[bold cyan]" + "═" * 55 + "[/]"))
    lines.append(
        Text.from_markup(f"[bold cyan]  Agent Status Board - {main_repo.name}[/]")
    )
    lines.append(Text.from_markup("[bold cyan]" + "═" * 55 + "[/]"))
    lines.append(Text(""))

    for status in statuses:
        # Agent label
        if status.is_main:
            lines.append(Text.from_markup("[bold cyan]Agent 1 (main)[/]"))
        else:
            lines.append(Text.from_markup(f"[bold magenta]Agent {status.agent_id}[/]"))

        # Branch line
        dirty_indicator = " [yellow]*[/]" if status.is_dirty else ""
        ahead_behind = ""
        if status.ahead > 0:
            ahead_behind += f"[green]+{status.ahead}[/]"
        if status.behind > 0:
            ahead_behind += f"[red]-{status.behind}[/]"
        if ahead_behind:
            ahead_behind = f" [{ahead_behind}]"

        branch_str = f"[green]{status.branch}[/]{dirty_indicator}{ahead_behind}"
        lines.append(Text.from_markup(f"  [blue]Branch:[/] {branch_str}"))
        commit_str = f"{status.last_commit_hash} {status.last_commit_msg}"
        lines.append(Text.from_markup(f"  [blue]Commit:[/] [dim]{commit_str}[/]"))

        if status.task:
            lines.append(Text.from_markup(f"  [blue]Task:[/]   {status.task}"))

        lines.append(Text(""))

    # Shared notes summary
    line_count, last_header = _get_shared_notes_summary(main_repo)
    if line_count > 0:
        lines.append(Text.from_markup("[bold yellow]Shared Notes[/]"))
        lines.append(Text.from_markup(f"[dim]{line_count} lines[/]"))
        if last_header:
            lines.append(Text.from_markup(f"  [dim]Latest: {last_header}[/]"))
        lines.append(Text(""))

    lines.append(Text.from_markup(f"[dim]Updated: {time.strftime('%H:%M:%S')}[/]"))

    return Group(*lines)


def _display_full(statuses: list[AgentStatus], main_repo: Path) -> None:
    """Display full status view.

    Args:
        statuses: List of agent statuses.
        main_repo: Path to main repository.
    """
    output = _build_full_output(statuses, main_repo)
    console.print(output)


def _build_compact_output(statuses: list[AgentStatus], main_repo: Path) -> Group:
    """Build compact status view as a renderable.

    Args:
        statuses: List of agent statuses.
        main_repo: Path to main repository.

    Returns:
        Group of Text objects for rendering.
    """
    lines = []
    timestamp = time.strftime("%H:%M:%S")
    lines.append(
        Text.from_markup(
            f"[bold cyan]Agents[/] [dim]{main_repo.name}[/]  [dim]{timestamp}[/]"
        )
    )

    for status in statuses:
        # Agent label
        if status.is_main:
            agent_label = "[cyan]1[/]"
        else:
            agent_label = f"[magenta]{status.agent_id}[/]"

        dirty_indicator = "[yellow]*[/]" if status.is_dirty else " "

        ahead_behind = ""
        if status.ahead > 0:
            ahead_behind += f"[green]+{status.ahead}[/]"
        if status.behind > 0:
            ahead_behind += f"[red]-{status.behind}[/]"

        # Truncate commit message for compact view
        commit_info = f"{status.last_commit_hash} {status.last_commit_msg[:40]}"

        lines.append(
            Text.from_markup(
                f"  [bold]\\[{agent_label}][/] "
                f"[green]{status.branch:<20}[/] "
                f"{dirty_indicator}{ahead_behind:<6} "
                f"[dim]{commit_info}[/]"
            )
        )

    return Group(*lines)


def _display_compact(statuses: list[AgentStatus], main_repo: Path) -> None:
    """Display compact status view (single line per agent).

    Args:
        statuses: List of agent statuses.
        main_repo: Path to main repository.
    """
    output = _build_compact_output(statuses, main_repo)
    console.print(output)


def _build_status_output(compact: bool = False) -> Group:
    """Build status output as a renderable.

    Args:
        compact: If True, use single-line-per-agent format.

    Returns:
        Renderable Group for display.
    """
    main_repo = get_main_repo()
    statuses = _collect_status(main_repo)

    if compact:
        return _build_compact_output(statuses, main_repo)
    else:
        return _build_full_output(statuses, main_repo)


def display_status(compact: bool = False) -> None:
    """Display agent status board.

    Args:
        compact: If True, use single-line-per-agent format.
    """
    output = _build_status_output(compact=compact)
    console.print(output)


# Action sentinels for interactive mode
ACTION_DELETE_PREFIX = "__delete__:"
ACTION_OPEN_IN_EDITOR_PREFIX = "__open_in_editor__:"


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


def _build_detail_content(
    status: AgentStatus, git_status: GitStatusDetail, commits: list[CommitInfo]
) -> list[tuple[str, str]]:
    """Build formatted text content for detail view.

    Args:
        status: Agent status for the worktree.
        git_status: Detailed git status.
        commits: List of recent commits.

    Returns:
        List of (style, text) tuples for prompt_toolkit.
    """
    parts: list[tuple[str, str]] = []

    # Branch header
    parts.append(("bold fg:cyan", "═" * 60 + "\n"))
    if status.is_main:
        parts.append(("bold fg:cyan", f"  {status.branch}"))
        parts.append(("fg:gray", " (main)\n"))
    else:
        parts.append(("bold fg:green", f"  {status.branch}\n"))
    parts.append(("bold fg:cyan", "═" * 60 + "\n\n"))

    # Path
    parts.append(("dim", "Path:  "))
    parts.append(("", f"{status.path}\n\n"))

    # Tracking status
    parts.append(("dim", "Tracking:  "))
    if status.ahead > 0 or status.behind > 0:
        if status.ahead > 0:
            parts.append(("fg:green", f"{status.ahead} ahead"))
            if status.behind > 0:
                parts.append(("", ", "))
        if status.behind > 0:
            parts.append(("fg:red", f"{status.behind} behind"))
        parts.append(("", "\n\n"))
    else:
        parts.append(("fg:gray", "up to date\n\n"))

    # Git status section
    parts.append(("bold fg:yellow", "Git Status\n"))
    has_changes = git_status.staged or git_status.unstaged or git_status.untracked
    if not has_changes:
        parts.append(("fg:gray", "  Working tree clean\n"))
    else:
        if git_status.staged:
            parts.append(("fg:green", "  Staged:\n"))
            for f in git_status.staged:
                parts.append(("fg:green", f"    {f}\n"))

        if git_status.unstaged:
            parts.append(("fg:yellow", "  Modified:\n"))
            for f in git_status.unstaged:
                parts.append(("fg:yellow", f"    {f}\n"))

        if git_status.untracked:
            parts.append(("fg:red", "  Untracked:\n"))
            for f in git_status.untracked:
                parts.append(("fg:gray", f"    {f}\n"))
    parts.append(("", "\n"))

    # Recent commits
    parts.append(("bold fg:yellow", "Recent Commits\n"))
    if commits:
        for commit in commits:
            parts.append(("fg:cyan", f"  {commit.hash} "))
            parts.append(("", f"{commit.message}\n"))
            parts.append(("fg:gray", f"          {commit.author}, {commit.date}\n"))
    else:
        parts.append(("fg:gray", "  No commits found\n"))
    parts.append(("", "\n"))

    # Task (if any)
    if status.task:
        parts.append(("bold fg:yellow", "Current Task\n"))
        parts.append(("", f"  {status.task}\n\n"))

    return parts


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
        git_status = _get_git_status_detail(status.path)
        commits = _get_recent_commits(status.path)

        # Build content
        content_parts = _build_detail_content(status, git_status, commits)

        # Convert to lines for scrolling
        content_text = "".join(text for _, text in content_parts)
        total_lines = len(content_text.split("\n"))

        # State
        result: str | None = None
        scroll_offset = [0]  # Use list for mutability in closures

        def get_content():
            """Get scrolled content."""
            offset = scroll_offset[0]
            # Build visible content starting from offset
            parts: list[tuple[str, str]] = []
            line_count = 0

            for style, text in content_parts:
                for char in text:
                    if char == "\n":
                        line_count += 1
                        if line_count > offset:
                            parts.append((style, char))
                    elif line_count >= offset:
                        parts.append((style, char))

            if not parts:
                # Fallback - show from beginning
                return FormattedText(content_parts)
            return FormattedText(parts)

        # Key bindings
        kb = KeyBindings()

        @kb.add("escape")
        def _escape(event):
            nonlocal result
            result = "back"
            event.app.exit()

        @kb.add("q")
        def _quit(event):
            nonlocal result
            result = "quit"
            event.app.exit()

        @kb.add("c-c")
        def _ctrl_c(event):
            nonlocal result
            result = "quit"
            event.app.exit()

        @kb.add("e")
        def _editor(event):
            nonlocal result
            result = "editor"
            event.app.exit()

        @kb.add("d")
        def _delete(event):
            nonlocal result
            result = "delete"
            event.app.exit()

        # Scroll bindings
        @kb.add("up")
        @kb.add("k")
        def _scroll_up(event):
            scroll_offset[0] = max(0, scroll_offset[0] - 3)

        @kb.add("down")
        @kb.add("j")
        def _scroll_down(event):
            scroll_offset[0] = min(total_lines - 1, scroll_offset[0] + 3)

        @kb.add("pageup")
        @kb.add("c-u")
        def _page_up(event):
            scroll_offset[0] = max(0, scroll_offset[0] - 20)

        @kb.add("pagedown")
        @kb.add("c-d")
        def _page_down(event):
            scroll_offset[0] = min(total_lines - 1, scroll_offset[0] + 20)

        @kb.add("home")
        @kb.add("g")
        def _go_top(event):
            scroll_offset[0] = 0

        @kb.add("end")
        @kb.add("G")
        def _go_bottom(event):
            scroll_offset[0] = max(0, total_lines - 10)

        # Layout
        content_window = Window(
            content=FormattedTextControl(get_content),
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

        # Handle result
        if result == "back":
            return "back"
        elif result == "quit":
            return "quit"
        elif result == "editor":
            editor = select_editor()
            if editor:
                open_in_editor(status.path, editor)
            # Stay in detail view after editor
            continue
        elif result == "delete":
            _clear_screen_full()
            deleted = _delete_worktree_flow(status.branch, main_repo)
            if deleted:
                return "deleted"
            # Stay in detail view if cancelled
            continue

        return None


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


def _interactive_status(
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
            statuses = _collect_status(main_repo)

        if not statuses:
            error("No worktrees found")
            return None

        # Build fuzzy items from statuses
        items = [_build_fuzzy_item(s) for s in statuses]

        # Build lookups by branch
        path_by_branch = {s.branch: s.path for s in statuses}
        status_by_branch = {s.branch: s for s in statuses}

        # Action handlers
        def on_delete(branch: str) -> str | None:
            return f"{ACTION_DELETE_PREFIX}{branch}"

        def on_editor(branch: str) -> str | None:
            return f"{ACTION_OPEN_IN_EDITOR_PREFIX}{branch}"

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
            on_tab=on_delete,
            on_shift_enter=on_editor,
        )

        if selected is None:
            return None

        # Handle delete action
        if selected.startswith(ACTION_DELETE_PREFIX):
            branch_to_delete = selected[len(ACTION_DELETE_PREFIX) :]
            _delete_worktree_flow(branch_to_delete, main_repo)
            statuses = None  # Re-fetch after delete
            continue

        # Handle open in editor action
        if selected.startswith(ACTION_OPEN_IN_EDITOR_PREFIX):
            branch_to_open = selected[len(ACTION_OPEN_IN_EDITOR_PREFIX) :]
            worktree_path = path_by_branch.get(branch_to_open)
            if worktree_path:
                editor = select_editor()
                if editor:
                    open_in_editor(worktree_path, editor)
            # No need to re-fetch, state unchanged
            continue

        # Normal selection - show detail view
        selected_status = status_by_branch.get(selected)
        if selected_status:
            result = _show_worktree_detail(selected_status, main_repo)
            if result == "quit":
                return None
            elif result == "deleted":
                statuses = None  # Re-fetch after delete
            # "back" or anything else - continue loop
            continue

        return None


def _watch_interactive_loop(compact: bool = False) -> None:
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
                # Build and display status with hint
                statuses = _collect_status(main_repo)

                # Clear screen and show status
                console.clear()

                if compact:
                    output = _build_compact_output(statuses, main_repo)
                else:
                    output = _build_full_output(statuses, main_repo)

                console.print(output)
                console.print()
                console.print(
                    Text.from_markup(
                        "[dim]Press [bold]Enter[/bold] to select worktree, "
                        "[bold]q[/bold] to quit[/dim]"
                    )
                )

                # Set raw mode for keypress detection
                tty_module.setraw(fd)

                # Wait for keypress or timeout (2 seconds)
                for _ in range(20):  # 20 * 0.1s = 2s
                    ready, _, _ = select.select([fd], [], [], 0.1)
                    if ready:
                        key = sys.stdin.read(1)
                        # Restore terminal before any action
                        termios.tcsetattr(fd, termios.TCSANOW, old_settings)

                        if key in ("\r", "\n"):
                            # Enter - go to interactive mode
                            console.clear()
                            _interactive_status(statuses=statuses, main_repo=main_repo)
                            break
                        elif key.lower() == "q":
                            return
                        elif key == "\x03":  # Ctrl+C
                            return
                        else:
                            # Unknown key, set raw mode again and continue
                            tty_module.setraw(fd)
                else:
                    # Timeout - restore terminal for next display cycle
                    termios.tcsetattr(fd, termios.TCSANOW, old_settings)

        finally:
            # Always restore terminal settings
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

    except KeyboardInterrupt:
        pass
    except (OSError, EOFError):
        pass


# Cyclopts App

status_app = App(
    name="status",
    help="Display status of all agent worktrees.",
)


@status_app.default
def status(
    watch: Annotated[
        bool,
        Parameter(
            name=["--watch", "-w"],
            help=(
                "Watch mode with interactive selection. Press Enter to select worktree."
            ),
        ),
    ] = False,
    compact: Annotated[
        bool,
        Parameter(
            name=["--compact", "-c"],
            help="Use single-line-per-agent compact format.",
        ),
    ] = False,
    interactive: Annotated[
        bool,
        Parameter(
            name=["--interactive", "-i"],
            help="One-shot interactive selection. Outputs path for shell cd.",
        ),
    ] = False,
):
    """Display status of all agent worktrees.

    Shows branch, commits, dirty status, and tasks for each agent worktree.

    Examples:
        hive status              # Full status view (one-shot)
        hive status --compact    # Compact format (one-shot)
        hive status --watch      # Watch mode (press Enter for interactive)
        hive status -w -c        # Compact watch mode
        hive status -i           # Interactive selection

    Watch mode keybindings:
        Enter    Open interactive worktree picker
        q        Quit watch mode

    Interactive picker keybindings:
        Enter    Show detailed worktree info (git status, commits)
        Ctrl+O   Open worktree in editor
        Ctrl+D   Delete worktree
        Esc      Go back to previous screen
        Ctrl+C   Quit entirely

    Detail view keybindings:
        ↑/k      Scroll up
        ↓/j      Scroll down
        PgUp/^U  Page up
        PgDn/^D  Page down
        g/G      Go to top/bottom
        e        Open worktree in editor
        d        Delete worktree
        Esc      Go back to worktree picker
        q        Quit entirely
    """
    if interactive and not watch:
        # One-shot interactive mode - outputs path to stdout for shell integration
        path = _interactive_status()
        if path:
            print(path)
        else:
            sys.exit(1)
    elif watch:
        # Watch mode with interactive selection on Enter
        _watch_interactive_loop(compact=compact)
    else:
        # One-shot display
        display_status(compact=compact)
