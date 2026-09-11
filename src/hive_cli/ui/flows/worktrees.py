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

`select_and_change_to_worktree`/`run_in_worktree`/`_update_zellij_pane_name`
moved verbatim from commands/exec_runner.py (A0 step 10, killing that module's
status as a cross-imported "commands" module -- run.py and wt.py both called
it directly, tripping test_commands_do_not_import_each_other). They're UI-layer
orchestration (call the interactive picker, build rich-console callbacks for
services.pane.run_loop), not business logic, so ui/ -- not services/ -- is
their home. `select_and_change_to_worktree` imports pick_worktree lazily
(function-local) since ui/pickers/worktrees.py imports this module for
create_worktree_flow -- a module-level import here would be circular.
"""

from __future__ import annotations

import functools
import os
import sys
from collections.abc import Callable
from pathlib import Path

from ...config import get_runtime_settings
from ...git import (
    fetch_issue_details,
    get_git_root,
    get_main_repo,
    get_worktree_path,
    is_worktree_dirty,
    worktree_exists,
)
from ...mux.zellij.backend import set_pane_branch
from ...services import pane, tasks
from ...services import worktrees as worktrees_service
from ..console import error, format_yellow, info, success, warn
from ..console import out as console
from ..tty import confirm, is_interactive

CommandRunner = Callable[[list[str]], int]

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


def select_and_change_to_worktree(
    worktree: str | None,
    last_selected_branch: str | None = None,
    auto_select_branch: str | None = None,
    auto_select_timeout: float = 3.0,
) -> tuple[bool, str | None]:
    """Select worktree and change to it.

    Args:
        worktree: Branch name, '-' for interactive, or None for git root.
        last_selected_branch: Branch to pre-select in interactive mode.
        auto_select_branch: Branch to auto-select after timeout in interactive mode.
            Use "-" for repo's default branch. Any keypress cancels.
        auto_select_timeout: Seconds before auto-selection (default 3.0).

    Returns:
        Tuple of (success, selected_branch). success is False if user cancelled.
        selected_branch is the branch that was selected (for tracking across restarts).
    """
    if worktree == "-":
        # Interactive selection
        if not is_interactive():
            error("Interactive mode required for worktree selection")
            sys.exit(1)
        from ..pickers.worktrees import pick_worktree

        agent_num = get_runtime_settings().pane_id_int
        result = pick_worktree(
            agent_num=agent_num,
            preselect_branch=last_selected_branch,
            auto_select_branch=auto_select_branch,
            auto_select_timeout=auto_select_timeout,
        )
        if result is None:
            # User cancelled
            return False, None
        path, branch = result
        primary = Path(path)
        os.chdir(primary)
        pane.apply_workdir_override(primary)
        return True, branch
    elif worktree is not None:
        # Specific branch provided
        if worktree in ("main", "1"):
            worktree_path = get_main_repo()
        else:
            worktree_path = get_worktree_path(worktree)
            if not worktree_path.exists():
                error(
                    f"Worktree for '{format_yellow(worktree)}' does not exist. "
                    f"Create it first with: hive wt create {worktree}"
                )
                sys.exit(1)
        os.chdir(worktree_path)
        pane.apply_workdir_override(worktree_path)
        return True, worktree
    else:
        # Change to git root if available (default behavior)
        git_root = get_git_root()
        if git_root:
            os.chdir(git_root)
        return True, None


def _update_zellij_pane_name(
    prefix: str | None, branch: str | None, *, layout_has_base_name: bool = False
) -> None:
    """Update Zellij pane name with branch info.

    Uses the structured title system to update just the branch component.
    The base name ({agent}-{pane_id}) comes from HIVE_AGENT and HIVE_PANE_ID env vars.

    Args:
        prefix: Deprecated. Previously used as pane name prefix.
        branch: Branch/worktree name. If None, branch is cleared.
        layout_has_base_name: Deprecated. Layout base name is no longer used.

    Note:
        The prefix and layout_has_base_name parameters are kept for backwards
        compatibility but are no longer used. The agent name now comes from
        HIVE_AGENT env var, which is set by `hive zellij`.
    """
    set_pane_branch(branch)


def run_in_worktree(
    command: list[str],
    *,
    worktree: str | None = None,
    restart: bool = False,
    restart_confirmation: bool = False,
    restart_delay: float = 0,
    preselect_branch: str | None = None,
    use_execvp: bool = True,
    run_command: CommandRunner | None = None,
    restart_message: str = "[hive] Command exited. Restarting... (Ctrl+C to stop)",
    pane_name_prefix: str | None = None,
    layout_has_base_name: bool = False,
    worktrees_enabled: bool = True,
    auto_select_branch: str | None = None,
    auto_select_timeout: float = 3.0,
    ctx: pane.PaneContext | None = None,
) -> int:
    """Execute command in worktree with optional restart loop.

    Args:
        command: Command and arguments to execute.
        worktree: Branch name, '-' for interactive, None for git root.
        restart: Whether to auto-restart in a loop.
        restart_confirmation: Whether to wait for Enter before each restart.
            Implies restart=True.
        restart_delay: Seconds to wait between restarts.
        preselect_branch: Branch to pre-select in interactive mode.
        use_execvp: Use execvp for single run (replaces process).
        run_command: Optional custom command runner function. If provided,
            this function is called with the command list and should return
            an exit code. Useful for implementing retry/resume logic.
        restart_message: Message to display when restarting.
        pane_name_prefix: Prefix for Zellij pane name (e.g., agent name).
            If running in Zellij, pane will be renamed to "{prefix} [{branch}]".
        layout_has_base_name: If True, the Zellij layout already defines the base
            pane name, so only the branch suffix is appended.
        worktrees_enabled: If False, --restart won't imply -w - for worktree
            selection. Controlled by worktrees.enabled in config.
        auto_select_branch: Branch to auto-select after timeout in interactive mode.
            Use "-" for repo's default branch. Any keypress cancels.
        auto_select_timeout: Seconds before auto-selection (default 3.0).
        ctx: Pane context (see services.pane.open_pane_context); opened here
            when None. Pass `pane.null_context()` for commands that are not
            agent panes.

    Returns:
        Exit code (only if restart=False and use_execvp=False).
    """
    if ctx is None:
        ctx = pane.open_pane_context()

    def on_branch_selected(branch: str | None) -> None:
        _update_zellij_pane_name(
            pane_name_prefix, branch, layout_has_base_name=layout_has_base_name
        )

    def confirm_restart() -> None:
        console.print("[dim][hive] Press Enter to restart...[/]")
        input()

    def confirm_retry() -> None:
        input()

    return pane.run_loop(
        command,
        select_and_change_to_worktree,
        runner=run_command or functools.partial(pane.default_run_command, ctx=ctx),
        worktree=worktree,
        restart=restart,
        restart_confirmation=restart_confirmation,
        restart_delay=restart_delay,
        preselect_branch=preselect_branch,
        use_execvp=use_execvp,
        run_command=run_command,
        restart_message=restart_message,
        worktrees_enabled=worktrees_enabled,
        auto_select_branch=auto_select_branch,
        auto_select_timeout=auto_select_timeout,
        on_branch_selected=on_branch_selected,
        clear_screen=console.clear,
        progress=console.print,
        confirm_restart=confirm_restart,
        confirm_retry=confirm_retry,
        ctx=ctx,
    )
