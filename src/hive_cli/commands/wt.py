"""Worktree commands - manage git worktrees for multi-agent development."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated

from cyclopts import App, Parameter

from ..config import get_settings
from ..git import (
    create_worktree,
    delete_worktree,
    get_all_branches,
    get_main_repo,
    get_worktree_path,
    get_worktrees_base,
    is_worktree_dirty,
    list_worktrees,
    worktree_exists,
)
from ..services import handoffs
from ..services import worktrees as worktrees_service
from ..ui.console import error, format_yellow, info, success, warn
from ..ui.pickers.worktrees import pick_worktree
from ..ui.tty import is_interactive


def _complete_branch(ctx, param, incomplete):
    """Shell completion for branch arguments."""
    try:
        main_repo = get_main_repo()
        # Get all worktree branches
        worktrees = list_worktrees(main_repo)
        branches = [wt.branch for wt in worktrees]
        # Also add non-worktree branches
        all_branches = get_all_branches(main_repo)
        branches.extend(b for b in all_branches if b not in branches)
        return [b for b in branches if b.startswith(incomplete)]
    except Exception:
        return []


def _check_worktrees_enabled():
    """Check if worktrees are enabled in config, exit if not."""
    config = get_settings()
    if not config.worktrees.enabled:
        error("Worktrees are disabled in configuration (worktrees.enabled = false)")
        sys.exit(1)


# Cyclopts App

wt_app = App(
    name="wt",
    help="Manage git worktrees for multi-agent development.",
)


@wt_app.default
def wt_default():
    """Interactive selection (same as hive wt cd).

    Examples:
        hive wt                  # Interactive selection (same as hive wt cd)
        hive wt cd feature       # Navigate to worktree
        hive wt list             # List all worktrees
        hive wt create feat-123  # Create worktree for branch
        hive wt delete feat-123  # Delete worktree
    """
    _check_worktrees_enabled()
    cd()


@wt_app.command
def cd(
    branch: Annotated[
        str | None,
        Parameter(help="Branch name to navigate to."),
    ] = None,
):
    """Navigate to a worktree.

    Outputs the worktree path for shell integration.
    If BRANCH is not specified, shows interactive selection.

    Shell integration (fish):
        function cda
            set -l path (hive wt cd $argv)
            and cd $path
        end

    Examples:
        hive wt cd              # Interactive selection
        hive wt cd main         # Go to main repo
        hive wt cd feature-123  # Go to feature-123 worktree
    """
    _check_worktrees_enabled()

    if branch:
        # Direct navigation to specified branch
        path = get_worktree_path(branch)
        if not path.exists() and branch not in ("main", "1"):
            error(f"Worktree for '{format_yellow(branch)}' does not exist")
            sys.exit(1)
        print(str(path))
        return

    # Interactive selection
    if not is_interactive():
        error("No branch specified and not in interactive mode")
        sys.exit(1)

    result = pick_worktree(agent_num=0)
    if result:
        path, _branch = result
        print(path)
    else:
        sys.exit(1)


@wt_app.command(name="list")
def list_cmd():
    """List all worktrees in branch:path format.

    Examples:
        hive wt list
        # main:/path/to/repo
        # feature-123:/path/to/repo/.worktrees/feature-123
    """
    _check_worktrees_enabled()
    for wt in list_worktrees():
        print(f"{wt.branch}:{wt.path}")


@wt_app.command
def path(
    branch: Annotated[str, Parameter(help="Branch name to get path for.")],
):
    """Get path for a worktree.

    Examples:
        hive wt path main        # /path/to/repo
        hive wt path feature-123 # /path/to/repo/.worktrees/feature-123
    """
    _check_worktrees_enabled()
    wt_path = get_worktree_path(branch)
    print(str(wt_path))


@wt_app.command
def parent():
    """Get the main repository path (parent of all worktrees).

    Examples:
        hive wt parent  # /path/to/main/repo
    """
    _check_worktrees_enabled()
    main_repo = get_main_repo()
    print(str(main_repo))


@wt_app.command
def create(
    branch: Annotated[str, Parameter(help="Branch name to create worktree for.")],
    install: Annotated[
        bool,
        Parameter(
            name="--install",
            negative="--no-install",
            help="Install dependencies after creating worktree.",
        ),
    ] = True,
):
    """Create a new worktree for a branch.

    If the branch doesn't exist, creates it from the default branch.

    Examples:
        hive wt create feature-123
        hive wt create user/feat/update-api
        hive wt create hotfix-456 --no-install
    """
    _check_worktrees_enabled()
    try:
        main_repo = get_main_repo()
        path = create_worktree(branch, main_repo)
        success(f"Created worktree at {path}")

        worktrees_service.setup_worktree_files(path, main_repo, progress=warn)
        handoffs.setup_handoff_symlink(path, branch, main_repo)

        if install:
            info("Installing dependencies...")
            if worktrees_service.install_dependencies(path):
                success("Dependencies installed")
            else:
                warn("Some dependencies may have failed to install")

        # Output path for shell integration
        print(str(path))
    except ValueError as e:
        error(str(e))
        sys.exit(1)
    except FileExistsError as e:
        error(str(e))
        sys.exit(1)
    except Exception as e:
        error(f"Failed to create worktree: {e}")
        sys.exit(1)


@wt_app.command
def delete(
    branch: Annotated[str, Parameter(help="Branch name to delete worktree for.")],
    force: Annotated[
        bool,
        Parameter(
            name=["--force", "-f"],
            help="Force deletion even if worktree has uncommitted changes.",
        ),
    ] = False,
):
    """Delete a worktree.

    Examples:
        hive wt delete feature-123
        hive wt delete feature-123 --force
    """
    _check_worktrees_enabled()
    if branch in ("main", "1"):
        error("Cannot delete main repo worktree")
        sys.exit(1)

    path = get_worktree_path(branch)
    if not path.exists():
        error(f"Worktree for '{format_yellow(branch)}' does not exist")
        sys.exit(1)

    # Check for uncommitted changes
    if is_worktree_dirty(path) and not force:
        error("Worktree has uncommitted changes. Use --force to delete anyway")
        sys.exit(1)

    try:
        delete_worktree(path, force=force)
        success(f"Deleted worktree for '{branch}'")
    except Exception as e:
        error(f"Failed to delete worktree: {e}")
        sys.exit(1)


@wt_app.command
def exists(
    branch: Annotated[str, Parameter(help="Branch name to check.")],
):
    """Check if a worktree exists.

    Exits with code 0 if exists, 1 if not.

    Examples:
        hive wt exists feature-123 && echo "exists"
        if hive wt exists main; then echo "main exists"; fi
    """
    _check_worktrees_enabled()
    if worktree_exists(branch):
        sys.exit(0)
    else:
        sys.exit(1)


@wt_app.command
def base():
    """Get the base directory for worktrees.

    Examples:
        hive wt base
        # ~/.worktrees/Projects--myrepo (with default {repo}/{branch} template)
    """
    _check_worktrees_enabled()
    base_path = get_worktrees_base()
    print(str(base_path))


def _here_branch() -> str | None:
    """Branch of the worktree (or 'main') containing the current directory."""
    from ..services import session

    main_repo = get_main_repo()
    worktrees = list_worktrees(main_repo)
    resolved = session.resolve_here(Path.cwd(), main_repo, worktrees)
    if resolved is None:
        return None
    return next((wt.branch for wt in worktrees if wt.path == resolved), None)


@wt_app.command(name="exec")
def exec_cmd(
    *args: Annotated[
        str,
        Parameter(
            allow_leading_hyphen=True,
            help="Command and args to execute (alternative to -c; put after --).",
        ),
    ],
    command: Annotated[
        str | None,
        Parameter(
            name=["--command", "-c"],
            help="Command to execute (shell string).",
        ),
    ] = None,
    worktree: Annotated[
        str | None,
        Parameter(
            name=["--worktree", "-w"],
            help=(
                "Run in worktree. Use '-' for selection, 'here' for the "
                "worktree of the current directory, or a branch name."
            ),
        ),
    ] = None,
    here: Annotated[
        bool,
        Parameter(
            help="Run in the worktree of the current directory (same as -w here)."
        ),
    ] = False,
    restart: Annotated[
        bool,
        Parameter(
            help="Auto-restart after exit. Implies -w=- for interactive selection."
        ),
    ] = False,
    restart_confirmation: Annotated[
        bool,
        Parameter(
            name="--restart-confirmation",
            help="Wait for Enter before each restart. Implies --restart.",
        ),
    ] = False,
    restart_delay: Annotated[
        float,
        Parameter(
            name="--restart-delay",
            help="Delay in seconds between restarts (default: 0).",
        ),
    ] = 0,
):
    """Execute a command in a worktree.

    Examples:
        hive wt exec -c 'ls -la'                    # Run in git root
        hive wt exec -c 'npm test' -w=-             # Interactive worktree selection
        hive wt exec -c 'npm test' -w feature-123   # Specific worktree
        hive wt exec --here -- npm test             # Run in this worktree
        hive wt exec -c 'make watch' --restart      # Auto-restart (re-select each time)
        hive wt exec -c 'make watch' --restart -w feat  # Restart in specific worktree
        hive wt exec -c 'date' --restart --restart-delay 1
        hive wt exec -c 'npm test' --restart-confirmation  # Manual restart
    """
    import shlex

    from ..services import pane
    from ..ui.flows.worktrees import run_in_worktree

    _check_worktrees_enabled()

    if command is not None:
        try:
            cmd = shlex.split(command)
        except ValueError as e:
            error(f"Invalid command: {e}")
            sys.exit(1)
    else:
        cmd = list(args)

    if not cmd:
        error("Command cannot be empty")
        sys.exit(1)

    if here or worktree == "here":
        branch = _here_branch()
        if branch is None:
            warn("not inside a worktree, choose one")
            worktree = "-"
        else:
            worktree = branch

    exit_code = run_in_worktree(
        cmd,
        worktree=worktree,
        restart=restart,
        restart_confirmation=restart_confirmation,
        restart_delay=restart_delay,
        use_execvp=not restart and not restart_confirmation,
        layout_has_base_name=True,  # Append branch to existing pane name
        ctx=pane.null_context(),  # not an agent pane: no identity, no socket
    )
    sys.exit(exit_code)


@wt_app.command
def ensure(
    agent_num: Annotated[int, Parameter(help="Agent number.")],
):
    """Interactive agent workflow - select or create worktree.

    For agent 1, always uses main repo.
    For other agents, shows interactive selection with:
    - Fuzzy search through worktrees and branches
    - Option to create new branches (ESC)
    - Option to delete worktrees

    Examples:
        hive wt ensure 1   # Returns main repo path
        hive wt ensure 2   # Interactive selection for agent 2
    """
    _check_worktrees_enabled()
    main_repo = get_main_repo()

    # Agent 1 uses main repo
    if agent_num == 1:
        print(str(main_repo))
        return

    if not is_interactive():
        error("Interactive mode required for agent workflow")
        sys.exit(1)

    result = pick_worktree(agent_num)
    if result:
        path, _branch = result
        print(path)
    else:
        sys.exit(1)
