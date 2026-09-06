"""Multi-step worktree flows: new-branch/issue-branch prompts, create, delete.

Moved from commands/wt.py (A0 wt.py pass). `create_worktree_flow` is a thin
try/except around services.worktrees.provision() -- provision() itself owns
no printing (it takes a progress callback) and lets create_worktree()'s
exceptions propagate, so this flow is the one place that turns them into
`error(...)` text, matching the original inline behavior exactly.

`delete_worktree_flow` here and ui/pickers/status.py's own `_delete_worktree_flow`
are near-duplicates with deliberately divergent printed text (see
A0-architecture.md's pre-flight findings) -- do not unify them. Both now
call services.worktrees.remove() for the actual git removal.
"""

from __future__ import annotations

from pathlib import Path

from ...git import (
    fetch_issue_details,
    get_worktree_path,
    is_worktree_dirty,
    worktree_exists,
)
from ...services import tasks
from ...services import worktrees as worktrees_service
from ..console import error, info, success, warn
from ..console import out as console
from ..tty import confirm

# Emoji prefix for GitHub issues, shown above the issue-branch prompt and
# (imported from here) next to issue items in ui/pickers/worktrees.py.
ISSUE_EMOJI = "🎫"


def create_worktree_flow(branch: str, main_repo: Path, agent_num: int) -> str | None:
    """Create a worktree for a branch.

    Args:
        branch: Branch name.
        main_repo: Path to main repository.
        agent_num: Agent number.

    Returns:
        Path to created worktree, or None on failure.
    """
    try:
        path = worktrees_service.provision(
            branch, main_repo, agent_num=agent_num, progress=info
        )
        return str(path)
    except Exception as e:
        error(f"Failed to create worktree: {e}")
        return None


def _prompt_new_branch() -> str | None:
    """Prompt user for a new branch name using prompt_toolkit.

    Returns:
        Branch name, or None if cancelled (Esc with empty input).

    Raises:
        KeyboardInterrupt: If user presses Ctrl+C.
    """
    from prompt_toolkit import prompt as pt_prompt
    from prompt_toolkit.formatted_text import HTML
    from prompt_toolkit.key_binding import KeyBindings

    # Custom key bindings for Esc behavior
    kb = KeyBindings()

    @kb.add("escape")
    def _escape(event):
        """Go back to picker if input is empty, otherwise clear input."""
        if not event.current_buffer.text:
            # Empty input - signal to go back to picker
            event.current_buffer.text = ""
            event.app.exit(result="")
        else:
            # Has text - clear it
            event.current_buffer.text = ""

    try:
        result = pt_prompt(
            HTML("<b>New branch:</b> "),
            placeholder="branch name (Esc back, ^C quit)",
            key_bindings=kb,
        ).strip()
        # Empty result means user pressed Esc with empty input
        return result if result else None
    except (KeyboardInterrupt, EOFError):
        raise KeyboardInterrupt


def _prompt_issue_branch(issue_number: int, issue_title: str) -> str | None:
    """Prompt user for a branch name for a GitHub issue.

    Shows the issue title and pre-fills the branch prefix.

    Args:
        issue_number: GitHub issue number.
        issue_title: GitHub issue title.

    Returns:
        Branch name, or None if cancelled (Esc with empty prefix).

    Raises:
        KeyboardInterrupt: If user presses Ctrl+C.
    """
    from prompt_toolkit import prompt as pt_prompt
    from prompt_toolkit.formatted_text import HTML
    from prompt_toolkit.key_binding import KeyBindings

    prefix = f"gh-{issue_number}-"

    # Custom key bindings for Esc behavior
    kb = KeyBindings()

    @kb.add("escape")
    def _escape(event):
        """Go back to picker if only prefix remains, otherwise clear to prefix."""
        if event.current_buffer.text == prefix:
            # Only prefix - signal to go back to picker
            event.current_buffer.text = ""
            event.app.exit(result="")
        else:
            # Has extra text - reset to just prefix
            event.current_buffer.text = prefix
            event.current_buffer.cursor_position = len(prefix)

    # Print issue context above the prompt
    console.print()
    console.print(f"[cyan bold]{ISSUE_EMOJI} Issue #{issue_number}[/]")
    console.print(issue_title)
    console.print()

    try:
        result = pt_prompt(
            HTML("<b>Branch:</b> "),
            default=prefix,
            placeholder="(Esc back, ^C quit)",
            key_bindings=kb,
        ).strip()
        # Empty result or just prefix means cancelled
        if not result or result == prefix:
            return None
        return result
    except (KeyboardInterrupt, EOFError):
        raise KeyboardInterrupt


def issue_branch_flow(
    issue_number: int, issue_title: str, main_repo: Path, agent_num: int
) -> str | None:
    """Handle creation of a branch for a GitHub issue.

    Args:
        issue_number: GitHub issue number.
        issue_title: GitHub issue title.
        main_repo: Path to main repository.
        agent_num: Agent number.

    Returns:
        Path to created worktree, or None if cancelled.

    Raises:
        KeyboardInterrupt: If user presses Ctrl+C.
    """
    branch = _prompt_issue_branch(issue_number, issue_title)

    if not branch:
        return None

    if branch in ("main", "master"):
        warn("Cannot create worktree for default branch")
        return None

    if worktree_exists(branch, main_repo):
        warn(f"Worktree for '{branch}' already exists")
        return None

    result = create_worktree_flow(branch, main_repo, agent_num)

    if result:
        # Fetch full issue details and write task file
        issue_details = fetch_issue_details(issue_number, main_repo)
        if issue_details:
            tasks.write_task_file(Path(result), issue_details)
            info("Created .claude/task.local.md with issue details")

    return result


def new_branch_flow(main_repo: Path, agent_num: int) -> str | None:
    """Handle creation of a new branch.

    Args:
        main_repo: Path to main repository.
        agent_num: Agent number.

    Returns:
        Path to created worktree, or None if cancelled.

    Raises:
        KeyboardInterrupt: If user presses Ctrl+C.
    """
    new_branch = _prompt_new_branch()

    if not new_branch:
        return None

    if new_branch in ("main", "master"):
        warn("Cannot create worktree for default branch")
        return None

    if worktree_exists(new_branch, main_repo):
        warn(f"Worktree for '{new_branch}' already exists")
        return None

    return create_worktree_flow(new_branch, main_repo, agent_num)


def delete_worktree_flow(branch: str, main_repo: Path) -> bool:
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

    if is_worktree_dirty(path):
        error("⚠ Uncommitted changes will be lost!")

    confirmed = confirm(f"Delete worktree '{branch}'?")
    deleted, err = worktrees_service.remove(branch, main_repo, confirmed=confirmed)
    if deleted:
        success("Worktree deleted")
        return True
    if err:
        error(f"Failed to delete: {err}")
    return False
