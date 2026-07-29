"""Handoff command - manage branch handoff notes.

Handoffs are stored centrally in .claude/handoffs/{branch}.md in the main repo
and symlinked into worktrees for easy access.
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Annotated

from cyclopts import App, Parameter
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from ..config import get_runtime_settings
from ..git import (
    get_current_branch,
    get_main_repo,
    get_worktree_path,
    is_worktree_dirty,
    list_worktrees,
)
from ..handoffs import (
    clean_orphaned_handoffs,
    get_handoff_file,
    has_handoff_content,
    list_handoffs,
)
from ..utils import confirm, error, info, success, warn

# Console for output
console = Console()


def _get_current_branch_context() -> tuple[str, Path] | None:
    """Get the current branch and worktree path.

    Returns:
        Tuple of (branch, worktree_path) or None if not in a git repo.
    """
    try:
        main_repo = get_main_repo()
    except Exception:
        return None

    # Check if we're in a worktree
    cwd = Path.cwd()
    worktrees = list_worktrees(main_repo)

    for wt in worktrees:
        if cwd == wt.path or str(cwd).startswith(str(wt.path) + os.sep):
            return (wt.branch, wt.path)

    # Check if we're in the main repo
    if cwd == main_repo or str(cwd).startswith(str(main_repo) + os.sep):
        branch = get_current_branch(main_repo)
        return (branch or "main", main_repo)

    return None


def _get_last_commit(path: Path) -> str:
    """Get last commit summary.

    Args:
        path: Path to repository.

    Returns:
        Commit hash and message.
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(path), "log", "-1", "--format=%h %s"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        return ""


def _create_wip_commit(path: Path, message: str | None = None) -> bool:
    """Create a WIP commit.

    Args:
        path: Path to repository.
        message: Optional commit message.

    Returns:
        True if commit was created.
    """
    try:
        subprocess.run(
            ["git", "-C", str(path), "add", "-A"],
            check=True,
            capture_output=True,
        )
        commit_msg = message or "WIP: Handoff checkpoint"
        subprocess.run(
            ["git", "-C", str(path), "commit", "-m", commit_msg],
            check=True,
            capture_output=True,
        )
        return True
    except subprocess.CalledProcessError:
        return False


def _format_handoff_preview(branch: str, handoff_file: Path) -> None:
    """Display a handoff file with formatting.

    Args:
        branch: Branch name.
        handoff_file: Path to handoff file.
    """
    if not handoff_file.exists():
        console.print(f"[dim]No handoff for {branch}[/]")
        return

    content = handoff_file.read_text().strip()
    if not content:
        console.print(f"[dim]Empty handoff for {branch}[/]")
        return

    # Render as markdown in a panel
    md = Markdown(content)
    console.print(Panel(md, title=f"[bold cyan]{branch}[/]", border_style="cyan"))


def show_all_handoffs() -> None:
    """Display all handoffs with content."""
    main_repo = get_main_repo()
    handoffs = list_handoffs(main_repo)

    if not handoffs:
        info("No handoffs found")
        return

    # Filter to those with content
    active_handoffs = [(b, f) for b, f in handoffs if has_handoff_content(f)]

    if not active_handoffs:
        info("No active handoffs (all empty)")
        return

    console.print()
    console.print("[bold cyan]" + "=" * 60 + "[/]")
    console.print("[bold cyan]  Active Handoffs[/]")
    console.print("[bold cyan]" + "=" * 60 + "[/]")
    console.print()

    for branch, handoff_file in active_handoffs:
        _format_handoff_preview(branch, handoff_file)
        console.print()


def show_handoff(branch: str) -> None:
    """Display handoff for a specific branch.

    Args:
        branch: Branch name.
    """
    main_repo = get_main_repo()
    handoff_file = get_handoff_file(branch, main_repo)
    _format_handoff_preview(branch, handoff_file)


def create_handoff(
    branch: str,
    worktree_path: Path,
    message: str | None = None,
    commit_changes: bool = True,
) -> Path:
    """Create or update a handoff for a branch.

    Args:
        branch: Branch name.
        worktree_path: Path to the worktree.
        message: Handoff message/notes.
        commit_changes: Whether to commit uncommitted changes first.

    Returns:
        Path to the handoff file.
    """
    main_repo = get_main_repo()

    # Handle uncommitted changes
    if commit_changes and is_worktree_dirty(worktree_path):
        warn("Uncommitted changes detected:")
        result = subprocess.run(
            ["git", "-C", str(worktree_path), "status", "--short"],
            capture_output=True,
            text=True,
        )
        console.print(result.stdout)

        if confirm("Create WIP commit?"):
            if _create_wip_commit(worktree_path):
                success("WIP commit created")
            else:
                warn("Failed to create commit")
        console.print()

    # Get current state
    last_commit = _get_last_commit(worktree_path)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    # Build handoff content
    content = f"""# Handoff: {branch}

**Created:** {timestamp}
**Last Commit:** {last_commit}
**Status:** In Progress

## Summary
{message or "[Add summary of work on this branch]"}

## Accomplished
- [What was completed]

## Remaining Work
1. [Next step]
2. [Following step]

## Key Files
- [Important files and why]

## Context & Gotchas
- [Important context for whoever continues]

## How to Continue
```bash
# Navigate to worktree
cd {worktree_path}
# Or: hive wt cd {branch}

# Check current state
git status
```
"""

    # Write handoff file
    handoff_file = get_handoff_file(branch, main_repo)
    handoff_file.parent.mkdir(parents=True, exist_ok=True)
    handoff_file.write_text(content)

    return handoff_file


def edit_handoff(branch: str) -> None:
    """Edit handoff in $EDITOR.

    Args:
        branch: Branch name.
    """
    main_repo = get_main_repo()
    handoff_file = get_handoff_file(branch, main_repo)

    # Create template if doesn't exist
    if not handoff_file.exists() or not has_handoff_content(handoff_file):
        # Try to get worktree path for this branch
        worktree_path = get_worktree_path(branch, main_repo)
        if not worktree_path.exists():
            worktree_path = main_repo

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        last_commit = _get_last_commit(worktree_path)

        template = f"""# Handoff: {branch}

**Created:** {timestamp}
**Last Commit:** {last_commit}
**Status:** In Progress

## Summary
[Brief description of work on this branch]

## Accomplished
- [What was completed]
- [Key changes made]

## Remaining Work
1. [Next step]
2. [Following step]

## Key Files
- `path/to/file` - [what it does]

## Context & Gotchas
- [Important context]
- [Gotchas or tricky parts]

## How to Continue
```bash
cd {worktree_path}
git status
```
"""
        handoff_file.parent.mkdir(parents=True, exist_ok=True)
        handoff_file.write_text(template)

    editor = get_runtime_settings().editor
    subprocess.run([editor, str(handoff_file)])


def clear_handoff(branch: str) -> None:
    """Clear handoff for a branch.

    Args:
        branch: Branch name.
    """
    main_repo = get_main_repo()
    handoff_file = get_handoff_file(branch, main_repo)

    if handoff_file.exists() and has_handoff_content(handoff_file):
        # Clear content but keep file (for symlink)
        handoff_file.write_text("")
        success(f"Handoff cleared for '{branch}'")
    else:
        warn(f"No handoff to clear for '{branch}'")


# Shell completion


def _complete_branch(ctx, param, incomplete):
    """Shell completion for branch arguments."""
    try:
        main_repo = get_main_repo()
        # Get branches with handoffs
        handoffs = list_handoffs(main_repo)
        branches = [b for b, _ in handoffs]
        # Also add worktree branches
        for wt in list_worktrees(main_repo):
            if wt.branch not in branches:
                branches.append(wt.branch)
        return [b for b in branches if b.startswith(incomplete)]
    except Exception:
        return []


# Cyclopts App

handoff_app = App(
    name="handoff",
    help="Manage branch handoff notes.",
)


@handoff_app.default
def handoff_default():
    """Show all active handoffs.

    Handoffs are stored in .claude/handoffs/{branch}.md in the main repo
    and symlinked into worktrees for easy access.

    Examples:
        hive handoff              # Show all active handoffs
        hive handoff show         # Show handoff for current branch
        hive handoff create       # Create handoff for current branch
        hive handoff edit         # Edit handoff in $EDITOR
        hive handoff clear        # Clear handoff for current branch
        hive handoff list         # List all handoff files
        hive handoff clean        # Remove orphaned handoffs
    """
    show_all_handoffs()


@handoff_app.command(name="list")
def list_cmd(
    show_all: Annotated[
        bool,
        Parameter(
            name=["--all", "-a"],
            help="Show all handoffs including empty ones.",
        ),
    ] = False,
):
    """List all handoff files.

    Examples:
        hive handoff list      # List handoffs with content
        hive handoff list -a   # List all including empty
    """
    main_repo = get_main_repo()
    handoffs = list_handoffs(main_repo)

    if not handoffs:
        info("No handoff files found")
        return

    console.print()
    console.print("[bold]Handoff Files:[/]")
    console.print()

    for branch, handoff_file in handoffs:
        has_content = has_handoff_content(handoff_file)
        if not show_all and not has_content:
            continue

        status = "[green]active[/]" if has_content else "[dim]empty[/]"
        console.print(f"  {branch}: {status}")
        console.print(f"    [dim]{handoff_file}[/]")

    console.print()


@handoff_app.command
def show(
    branch: Annotated[
        str | None,
        Parameter(help="Branch name to show handoff for."),
    ] = None,
):
    """Show handoff for a branch.

    If BRANCH is not specified, shows handoff for current branch.

    Examples:
        hive handoff show              # Current branch
        hive handoff show feature-123  # Specific branch
    """
    if not branch:
        ctx = _get_current_branch_context()
        if not ctx:
            error("Not in a git repository")
            sys.exit(1)
        branch = ctx[0]

    show_handoff(branch)


@handoff_app.command
def create(
    branch: Annotated[
        str | None,
        Parameter(help="Branch name to create handoff for."),
    ] = None,
    message: Annotated[
        tuple[str, ...],
        Parameter(help="Handoff message/summary."),
    ] = (),
    no_commit: Annotated[
        bool,
        Parameter(
            name="--no-commit",
            help="Don't prompt to commit uncommitted changes.",
        ),
    ] = False,
):
    """Create or update a handoff for a branch.

    If BRANCH is not specified, uses current branch.
    If MESSAGE is provided, uses it as the summary.

    Examples:
        hive handoff create
        hive handoff create "Completed auth, need tests"
        hive handoff create feature-123 "Ready for review"
    """
    ctx = _get_current_branch_context()
    if not ctx:
        error("Not in a git repository")
        sys.exit(1)

    current_branch, worktree_path = ctx

    # If branch specified, get its worktree path
    if branch:
        main_repo = get_main_repo()
        worktree_path = get_worktree_path(branch, main_repo)
        if not worktree_path.exists():
            worktree_path = main_repo
    else:
        branch = current_branch

    message_str = " ".join(message) if message else None

    # If no message and interactive, prompt for one
    if not message_str and sys.stdin.isatty():
        info("Enter handoff summary (what was done, what remains):")
        console.print("[dim](Press Enter for template, Ctrl+D to finish multi-line)[/]")
        try:
            lines = []
            while True:
                try:
                    line = input()
                    lines.append(line)
                except EOFError:
                    break
            message_str = "\n".join(lines) if lines else None
        except KeyboardInterrupt:
            console.print()
            sys.exit(1)
        console.print()

    handoff_file = create_handoff(
        branch, worktree_path, message_str, commit_changes=not no_commit
    )

    success(f"Handoff created: {handoff_file}")
    info(f"Edit with: hive handoff edit {branch}")


@handoff_app.command
def edit(
    branch: Annotated[
        str | None,
        Parameter(help="Branch name to edit handoff for."),
    ] = None,
):
    """Edit handoff in $EDITOR.

    If BRANCH is not specified, edits handoff for current branch.
    Creates a template if no handoff exists.

    Examples:
        hive handoff edit              # Current branch
        hive handoff edit feature-123  # Specific branch
    """
    if not branch:
        ctx = _get_current_branch_context()
        if not ctx:
            error("Not in a git repository")
            sys.exit(1)
        branch = ctx[0]

    edit_handoff(branch)


@handoff_app.command
def clear(
    branch: Annotated[
        str | None,
        Parameter(help="Branch name to clear handoff for."),
    ] = None,
):
    """Clear handoff for a branch.

    Clears the content but keeps the file (for symlink integrity).

    Examples:
        hive handoff clear              # Current branch
        hive handoff clear feature-123  # Specific branch
    """
    if not branch:
        ctx = _get_current_branch_context()
        if not ctx:
            error("Not in a git repository")
            sys.exit(1)
        branch = ctx[0]

    clear_handoff(branch)


@handoff_app.command
def clean(
    dry_run: Annotated[
        bool,
        Parameter(
            name=["--dry-run", "-n"],
            help="Show what would be removed without removing.",
        ),
    ] = False,
):
    """Remove handoff files for branches that no longer exist.

    Examples:
        hive handoff clean         # Remove orphaned handoffs
        hive handoff clean -n      # Preview what would be removed
    """
    main_repo = get_main_repo()

    if dry_run:
        # Preview mode
        from ..git import get_all_branches

        all_branches = set(get_all_branches(main_repo))
        worktree_branches = {wt.branch for wt in list_worktrees(main_repo)}
        valid_branches = all_branches | worktree_branches | {"main", "master"}

        orphaned = []
        for branch, handoff_file in list_handoffs(main_repo):
            if branch not in valid_branches:
                orphaned.append((branch, handoff_file))

        if orphaned:
            console.print("[yellow]Would remove:[/]")
            for branch, path in orphaned:
                console.print(f"  {branch}: {path}")
        else:
            info("No orphaned handoffs to clean")
        return

    removed = clean_orphaned_handoffs(main_repo)

    if removed:
        success(f"Removed {len(removed)} orphaned handoff(s):")
        for branch in removed:
            console.print(f"  - {branch}")
    else:
        info("No orphaned handoffs to clean")


@handoff_app.command
def path(
    branch: Annotated[
        str | None,
        Parameter(help="Branch name to get handoff path for."),
    ] = None,
):
    """Get the path to a handoff file.

    Examples:
        hive handoff path              # Current branch
        hive handoff path feature-123  # Specific branch
    """
    if not branch:
        ctx = _get_current_branch_context()
        if not ctx:
            error("Not in a git repository")
            sys.exit(1)
        branch = ctx[0]

    main_repo = get_main_repo()
    handoff_file = get_handoff_file(branch, main_repo)
    print(str(handoff_file))
