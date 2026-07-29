"""Worktree commands - manage git worktrees for multi-agent development."""

from __future__ import annotations

import json
import subprocess
import sys
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Annotated

from cyclopts import App, Parameter
from rich.console import Console

from ..agents import detect_agent
from ..config import get_agent_order, get_runtime_settings, get_settings
from ..git import (
    create_worktree,
    delete_worktree,
    fetch_origin,
    get_all_branches,
    get_current_branch,
    get_current_worktree_branch,
    get_default_branch,
    get_main_repo,
    get_worktree_path,
    get_worktrees_base,
    is_worktree_dirty,
    list_worktrees,
    worktree_exists,
)
from ..utils import (
    WORKDIR_CLEAR,
    FuzzyItem,
    confirm,
    error,
    format_yellow,
    fuzzy_select,
    info,
    install_dependencies,
    is_interactive,
    open_in_editor,
    select_agent,
    select_editor,
    select_workdir,
    setup_worktree_files,
    success,
    warn,
)
from ..utils.profiles import select_profile

console = Console()

# Special sentinels for actions that need to run outside the fuzzy finder
ACTION_NEW_BRANCH = "__new_branch__"
ACTION_DELETE_PREFIX = "__delete__:"
ACTION_OPEN_IN_EDITOR_PREFIX = "__open_in_editor__:"
ACTION_ISSUE_PREFIX = "__issue__:"
ACTION_CHANGE_AGENT = "__change_agent__"
ACTION_TOGGLE_SKIP_PERMISSIONS = "__toggle_skip_permissions__"
ACTION_CHANGE_WORKDIR = "__change_workdir__"
ACTION_CHANGE_PROFILE = "__change_profile__"

# Emoji prefix for GitHub issues to distinguish them from branches
ISSUE_EMOJI = "🎫"


@dataclass
class GitHubIssue:
    """A GitHub issue assigned to the current user."""

    number: int
    title: str

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {"number": self.number, "title": self.title}

    @classmethod
    def from_dict(cls, data: dict) -> GitHubIssue:
        """Create from dictionary."""
        return cls(number=data["number"], title=data["title"])


@dataclass
class GitHubIssueDetails:
    """Full details of a GitHub issue."""

    number: int
    title: str
    url: str
    body: str


def _get_github_repo_info(main_repo: Path) -> tuple[str, str] | None:
    """Get GitHub org and repo name from git remote.

    Args:
        main_repo: Path to the main repository.

    Returns:
        Tuple of (org, repo) or None if not a GitHub repo.
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(main_repo), "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            check=True,
        )
        remote_url = result.stdout.strip()

        # Handle both SSH and HTTPS URLs
        # git@github.com:org/repo.git or https://github.com/org/repo.git
        if "github.com" in remote_url:
            if remote_url.startswith("git@"):
                # SSH: git@github.com:org/repo.git
                parts = remote_url.split(":")[-1].replace(".git", "").split("/")
            elif remote_url.startswith("https://") or remote_url.startswith("http://"):
                # HTTPS: https://github.com/org/repo.git
                parts = (
                    remote_url.split("github.com/")[-1].replace(".git", "").split("/")
                )
            else:
                return None

            if len(parts) >= 2:
                return (parts[0], parts[1])
    except (subprocess.CalledProcessError, IndexError):
        pass
    return None


def _get_issues_cache_path(main_repo: Path) -> Path | None:
    """Get the cache file path for GitHub issues.

    Args:
        main_repo: Path to the main repository.

    Returns:
        Path to cache file, or None if not a GitHub repo.
    """
    repo_info = _get_github_repo_info(main_repo)
    if not repo_info:
        return None

    org, repo = repo_info
    cache_dir = Path(str(get_runtime_settings().xdg_cache_home)) / "hive"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / f"gh-{org}--{repo}-issues.json"


def _load_cached_issues(cache_path: Path | None) -> list[GitHubIssue]:
    """Load cached GitHub issues from disk.

    Args:
        cache_path: Path to cache file.

    Returns:
        List of cached issues, or empty list if cache doesn't exist or is invalid.
    """
    if not cache_path or not cache_path.exists():
        return []

    try:
        with open(cache_path) as f:
            data = json.load(f)
            return [GitHubIssue.from_dict(issue) for issue in data]
    except (json.JSONDecodeError, KeyError, FileNotFoundError):
        return []


def _save_cached_issues(issues: list[GitHubIssue], cache_path: Path | None) -> None:
    """Save GitHub issues to cache file.

    Args:
        issues: List of issues to cache.
        cache_path: Path to cache file.
    """
    if not cache_path:
        return

    try:
        # Ensure cache directory exists
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with open(cache_path, "w") as f:
            json.dump([issue.to_dict() for issue in issues], f, indent=2)
    except (OSError, json.JSONEncodeError):
        # Silently ignore cache write errors
        pass


def _fetch_github_issues(main_repo: Path) -> list[GitHubIssue] | None:
    """Fetch GitHub issues assigned to the current user.

    Uses github.fetch_issues and github.issue_limit from config.

    Args:
        main_repo: Path to the main repository.

    Returns:
        List of GitHub issues if fetch succeeded (may be empty),
        or None if disabled or fetch failed.
    """
    config = get_settings()

    # Check if issue fetching is enabled
    if not config.github.fetch_issues:
        return None

    try:
        result = subprocess.run(
            [
                "gh",
                "issue",
                "list",
                "--assignee",
                "@me",
                "--state",
                "open",
                "--json",
                "number,title",
                "--limit",
                str(config.github.issue_limit),
            ],
            capture_output=True,
            text=True,
            cwd=main_repo,
            timeout=2,
        )
        if result.returncode != 0:
            # Log error for debugging (but don't fail loudly)
            if result.stderr:
                # Only log if there's actual error output (not just empty)
                pass  # Silently ignore for now, but could add logging here
            return None

        issues_data = json.loads(result.stdout)
        issues = [
            GitHubIssue(number=issue["number"], title=issue["title"])
            for issue in issues_data
        ]
        # Save to cache (even if empty - to clear closed issues)
        cache_path = _get_issues_cache_path(main_repo)
        _save_cached_issues(issues, cache_path)
        return issues
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
        # gh CLI not installed, timeout, or parse error - silently ignore
        return None
    except Exception:
        # Any other error - silently ignore
        return None


def _fetch_issue_details(
    issue_number: int, main_repo: Path
) -> GitHubIssueDetails | None:
    """Fetch full details of a GitHub issue.

    Args:
        issue_number: GitHub issue number.
        main_repo: Path to the main repository.

    Returns:
        Issue details, or None if fetch fails.
    """
    try:
        result = subprocess.run(
            [
                "gh",
                "issue",
                "view",
                str(issue_number),
                "--json",
                "number,title,url,body",
            ],
            capture_output=True,
            text=True,
            cwd=main_repo,
            timeout=5,
        )
        if result.returncode != 0:
            return None

        data = json.loads(result.stdout)
        return GitHubIssueDetails(
            number=data["number"],
            title=data["title"],
            url=data["url"],
            body=data.get("body", "") or "",
        )
    except Exception:
        return None


def _write_task_file(worktree_path: Path, issue: GitHubIssueDetails) -> None:
    """Write issue details to .claude/task.md in the worktree.

    Args:
        worktree_path: Path to the worktree.
        issue: GitHub issue details.
    """
    claude_dir = worktree_path / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)

    task_file = claude_dir / "task.local.md"
    content = f"""# Task: {issue.title}

**Issue:** [#{issue.number}]({issue.url})

## Description

{issue.body if issue.body else "_No description provided._"}
"""
    task_file.write_text(content)


def _build_fuzzy_items_fast(
    main_repo: Path,
    current_worktree_branch: str | None = None,
    preselect_branch: str | None = None,
) -> tuple[list[FuzzyItem], int]:
    """Build list of items quickly.

    Skips slow operations like dirty checks and remote branches.

    Args:
        main_repo: Path to the main repository.
        current_worktree_branch: Branch of current worktree (if in one).
        preselect_branch: Branch to pre-select (overrides current_worktree_branch).

    Returns:
        Tuple of (list of FuzzyItem, initial selection index).
    """
    items: list[FuzzyItem] = []
    worktree_branches: set[str] = set()
    initial_selection = 0

    # Use preselect_branch if provided, otherwise fall back to current_worktree_branch
    select_branch = preselect_branch or current_worktree_branch

    # Get current branch of main repo - can't create worktree for it
    current_main_branch = get_current_branch(main_repo)

    # Get worktrees first (they show at top) - fast operation
    worktrees = list_worktrees(main_repo)
    for wt in worktrees:
        worktree_branches.add(wt.branch)
        # Skip dirty check for speed - will update async later

        if wt.is_main:
            if current_main_branch and current_main_branch not in ("main", "master"):
                text = "main"
                meta = f"[repo @ {current_main_branch}]"
                worktree_branches.add(current_main_branch)
            else:
                text = "main"
                meta = "[repo]"
            style = "bold green"
            if select_branch in ("main", "1"):
                initial_selection = len(items)
        else:
            text = wt.branch
            is_current = wt.branch == current_worktree_branch
            is_preselected = wt.branch == select_branch
            if is_current:
                meta = "← current"
            else:
                meta = ""
            if is_preselected:
                initial_selection = len(items)
            style = "green"  # Assume clean for speed

        items.append(FuzzyItem(text=text, value=wt.branch, meta=meta, style=style))

    # Get all branches (local + remote from existing refs)
    # This is fast, no fetch needed! Remote branches are already stored locally
    all_branches = get_all_branches(main_repo)
    for branch in all_branches:
        if branch not in worktree_branches:
            if branch == select_branch:
                initial_selection = len(items)
            items.append(FuzzyItem(text=branch, value=branch, meta="", style="dim"))

    # Load cached GitHub issues immediately (fast, no API call needed)
    cache_path = _get_issues_cache_path(main_repo)
    cached_issues = _load_cached_issues(cache_path)
    for issue in cached_issues:
        # Check if any branch starting with gh-{number}- already exists
        issue_prefix = f"gh-{issue.number}-"
        has_existing_branch = any(
            b.startswith(issue_prefix) or b == f"gh-issue-{issue.number}"
            for b in worktree_branches | set(all_branches)
        )
        if has_existing_branch:
            continue
        # Truncate long titles
        title = issue.title[:50] + "..." if len(issue.title) > 50 else issue.title
        value = f"{ACTION_ISSUE_PREFIX}{issue.number}:{issue.title}"
        items.append(
            FuzzyItem(
                text=f"{ISSUE_EMOJI} #{issue.number}: {title}",
                value=value,
                meta="",
                style="cyan",
            )
        )

    return items, initial_selection


def _build_fuzzy_items(
    main_repo: Path,
    current_worktree_branch: str | None = None,
    preselect_branch: str | None = None,
) -> tuple[list[FuzzyItem], int]:
    """Build list of items for fuzzy selection.

    Args:
        main_repo: Path to the main repository.
        current_worktree_branch: Branch of current worktree (if in one).
        preselect_branch: Branch to pre-select (overrides current_worktree_branch).

    Returns:
        Tuple of (list of FuzzyItem, initial selection index).
    """
    items: list[FuzzyItem] = []
    worktree_branches: set[str] = set()
    initial_selection = 0

    # Use preselect_branch if provided, otherwise fall back to current_worktree_branch
    select_branch = preselect_branch or current_worktree_branch

    # Get current branch of main repo - can't create worktree for it
    current_main_branch = get_current_branch(main_repo)

    # Get worktrees first (they show at top)
    worktrees = list_worktrees(main_repo)
    for wt in worktrees:
        worktree_branches.add(wt.branch)
        is_dirty = False if wt.is_main else is_worktree_dirty(wt.path)

        if wt.is_main:
            if current_main_branch and current_main_branch not in ("main", "master"):
                text = "main"
                meta = f"[repo @ {current_main_branch}]"
                # Also exclude current branch from list
                worktree_branches.add(current_main_branch)
            else:
                text = "main"
                meta = "[repo]"
            style = "bold green"
            # Check if main should be pre-selected
            if select_branch in ("main", "1"):
                initial_selection = len(items)
        else:
            text = wt.branch
            # Mark current worktree
            is_current = wt.branch == current_worktree_branch
            is_preselected = wt.branch == select_branch
            if is_current:
                meta = "← current" + (" (dirty)" if is_dirty else "")
            else:
                meta = "(dirty)" if is_dirty else ""
            if is_preselected:
                initial_selection = len(items)
            style = "yellow" if is_dirty else "green"

        items.append(FuzzyItem(text=text, value=wt.branch, meta=meta, style=style))

    # Get all branches and add those without worktrees
    all_branches = get_all_branches(main_repo)
    for branch in all_branches:
        if branch not in worktree_branches:
            # Check if this branch should be pre-selected
            if branch == select_branch:
                initial_selection = len(items)
            items.append(FuzzyItem(text=branch, value=branch, meta="", style="dim"))

    # Fetch GitHub issues assigned to user and add them
    # Issues are shown after branches with emoji prefix
    github_issues = _fetch_github_issues(main_repo)
    if github_issues is not None:
        for issue in github_issues:
            # Check if any branch starting with gh-{number}- already exists
            issue_prefix = f"gh-{issue.number}-"
            has_existing_branch = any(
                b.startswith(issue_prefix) or b == f"gh-issue-{issue.number}"
                for b in worktree_branches | set(all_branches)
            )
            if has_existing_branch:
                continue
            # Truncate long titles
            title = issue.title[:50] + "..." if len(issue.title) > 50 else issue.title
            # Value encodes issue number and full title for the prompt
            value = f"{ACTION_ISSUE_PREFIX}{issue.number}:{issue.title}"
            items.append(
                FuzzyItem(
                    text=f"{ISSUE_EMOJI} #{issue.number}: {title}",
                    value=value,
                    meta="",
                    style="cyan",
                )
            )

    return items, initial_selection


def _setup_agent_context(worktree_path: Path, agent_num: int, branch_name: str) -> None:
    """Create agent context file in the worktree.

    Args:
        worktree_path: Path to the worktree.
        agent_num: Agent number.
        branch_name: Branch name.
    """
    claude_dir = worktree_path / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)

    context_file = claude_dir / "worktree-context.md"
    context_file.write_text(f"""# Agent {agent_num} Worktree Context

- **Agent**: {agent_num}
- **Branch**: {branch_name}
- **Worktree**: {worktree_path}
- **Created**: {datetime.now().isoformat()}

## Guidelines

- Work only within this worktree directory
- Commit frequently to preserve work
- This worktree is isolated from other agents
""")


def _create_worktree_flow(branch: str, main_repo: Path, agent_num: int) -> str | None:
    """Create a worktree for a branch.

    Args:
        branch: Branch name.
        main_repo: Path to main repository.
        agent_num: Agent number.

    Returns:
        Path to created worktree, or None on failure.
    """
    info(f"Creating worktree for: {branch}")

    try:
        path = create_worktree(branch, main_repo)
        success(f"Created worktree at {path}")

        setup_worktree_files(path, main_repo)

        info("Installing dependencies...")
        if install_dependencies(path):
            success("Dependencies installed")
        else:
            warn("Some dependencies may have failed")

        if agent_num > 0:
            _setup_agent_context(path, agent_num, branch)
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


def _issue_branch_flow(
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

    result = _create_worktree_flow(branch, main_repo, agent_num)

    if result:
        # Fetch full issue details and write task file
        issue_details = _fetch_issue_details(issue_number, main_repo)
        if issue_details:
            _write_task_file(Path(result), issue_details)
            info("Created .claude/task.local.md with issue details")

    return result


def _new_branch_flow(main_repo: Path, agent_num: int) -> str | None:
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

    return _create_worktree_flow(new_branch, main_repo, agent_num)


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
        error("⚠ Uncommitted changes will be lost!")

    if confirm(f"Delete worktree '{branch}'?"):
        try:
            delete_worktree(path, force=True)
            success("Worktree deleted")
            return True
        except Exception as e:
            error(f"Failed to delete: {e}")
            return False

    return False


def _interactive_ensure(
    agent_num: int,
    preselect_branch: str | None = None,
    auto_select_branch: str | None = None,
    auto_select_timeout: float = 3.0,
) -> tuple[str, str] | None:
    """Run the interactive worktree selection with fuzzy finder.

    Args:
        agent_num: Agent number.
        preselect_branch: Branch to pre-select in the picker.
        auto_select_branch: Branch to auto-select after timeout. Use "-"
            for repo's default branch (main/master).
        auto_select_timeout: Seconds before auto-selection (default 3.0).

    Returns:
        Tuple of (path to selected/created worktree, selected branch name),
        or None if cancelled.
    """
    main_repo = get_main_repo()

    # Resolve auto_select_branch "-" to actual default branch
    resolved_auto_select: str | None = None
    if auto_select_branch is not None:
        if auto_select_branch == "-":
            resolved_auto_select = get_default_branch(main_repo)
        else:
            resolved_auto_select = auto_select_branch

    # Get current worktree branch for marking
    current_worktree_branch = get_current_worktree_branch()

    # Detect current agent, respecting HIVE_AGENT env var if set
    rt = get_runtime_settings()
    detected = detect_agent(preferred=rt.agent)
    if not detected:
        agent_list = ", ".join(get_agent_order())
        error(f"Can't find installed agent that matches configuration: {agent_list}")
        return None
    selected_agent = detected.name
    rt.agent = selected_agent

    # Track skip-permissions state from runtime settings
    skip_permissions = rt.skip_permissions

    while True:
        # Build initial items immediately (fast version - skips slow git operations)
        items, initial_selection = _build_fuzzy_items_fast(
            main_repo, current_worktree_branch, preselect_branch
        )

        # Base header text
        skip_perms_tag = " [skip-perms]" if skip_permissions else ""
        workdir_tag = f" [workdir: {rt.workdir}]" if rt.workdir else ""
        profile_tag = f" [profile: {rt.agent_profile}]" if rt.agent_profile else ""
        base_header = (
            f"Agent {agent_num} [{selected_agent}]{skip_perms_tag}"
            f"{workdir_tag}{profile_tag}"
            f" - Select worktree or branch"
        )
        # Start with "Fetching..." indicator
        header_with_indicator = f"{base_header} <dim>(Fetching...)</dim>"

        # Define escape handler - returns sentinel to trigger new branch flow
        def on_escape() -> str | None:
            return ACTION_NEW_BRANCH

        # Define tab handler - returns sentinel to trigger delete flow
        def on_tab(branch: str) -> str | None:
            return f"{ACTION_DELETE_PREFIX}{branch}"

        # Define shift+enter handler - returns sentinel to trigger open in editor
        def on_shift_enter(branch: str) -> str | None:
            return f"{ACTION_OPEN_IN_EDITOR_PREFIX}{branch}"

        # Define ctrl+a handler - returns sentinel to trigger agent change
        def on_ctrl_a() -> str | None:
            return ACTION_CHANGE_AGENT

        # Define ctrl+s handler - returns sentinel to toggle skip-permissions
        def on_ctrl_s() -> str | None:
            return ACTION_TOGGLE_SKIP_PERMISSIONS

        # Define ctrl+w handler - returns sentinel to trigger workdir override
        def on_ctrl_w() -> str | None:
            return ACTION_CHANGE_WORKDIR

        # Define ctrl+p handler - returns sentinel to trigger profile selection
        def on_ctrl_p() -> str | None:
            return ACTION_CHANGE_PROFILE

        # List to receive update functions (populated before app.run())
        update_callbacks: list = []
        update_callbacks_ready = threading.Event()

        # Start fetch and updates in background threads
        def fetch_and_update():
            """Fetch branches and update the picker when done."""
            # Wait for update functions to be populated (should be very quick, < 100ms)
            if not update_callbacks_ready.wait(timeout=1.0):
                return  # Update functions not available within 1 second, skip update

            if not update_callbacks:
                return  # Update functions not available, skip update

            update_items, update_header = update_callbacks[0]

            # Start git fetch (this is the slow part, ~3 seconds)
            fetch_origin(main_repo)

            # Remove fetching indicator immediately after fetch completes
            update_header(base_header)

            # Update items with dirty checks
            # Branches already shown, just updating metadata
            # Skip GitHub issues (they're fetched separately)
            items_with_dirty = []
            worktree_branches: set[str] = set()

            # Get worktrees and update dirty status
            worktrees = list_worktrees(main_repo)
            current_main_branch = get_current_branch(main_repo)

            for wt in worktrees:
                worktree_branches.add(wt.branch)
                is_dirty = False if wt.is_main else is_worktree_dirty(wt.path)

                if wt.is_main:
                    if current_main_branch and current_main_branch not in (
                        "main",
                        "master",
                    ):
                        text = "main"
                        meta = f"[repo @ {current_main_branch}]"
                        worktree_branches.add(current_main_branch)
                    else:
                        text = "main"
                        meta = "[repo]"
                    style = "bold green"
                else:
                    text = wt.branch
                    is_current = wt.branch == current_worktree_branch
                    if is_current:
                        meta = "← current" + (" (dirty)" if is_dirty else "")
                    else:
                        meta = "(dirty)" if is_dirty else ""
                    style = "yellow" if is_dirty else "green"

                items_with_dirty.append(
                    FuzzyItem(text=text, value=wt.branch, meta=meta, style=style)
                )

            # Add all branches (already shown, but rebuild to match structure)
            all_branches = get_all_branches(main_repo)
            for branch in all_branches:
                if branch not in worktree_branches:
                    items_with_dirty.append(
                        FuzzyItem(text=branch, value=branch, meta="", style="dim")
                    )

            # Update with dirty status (branches stay in place, only metadata changes)
            update_items(items_with_dirty)

        def fetch_github_issues():
            """Fetch GitHub issues independently and update when ready."""
            # Wait for update functions to be populated
            if not update_callbacks_ready.wait(timeout=1.0):
                return

            if not update_callbacks:
                return

            update_items, update_header = update_callbacks[0]

            # Fetch GitHub issues (independent of git fetch - happens in parallel)
            github_issues = _fetch_github_issues(main_repo)
            if github_issues is None:
                # Fetch failed - show error in header (but keep cached issues)
                update_header(f"{base_header} <red>(GitHub issues failed)</red>")
                return

            # Fetch succeeded (may be empty if all issues closed)
            # We need to update the list to remove any stale cached issues

            # Get current branch set to check for existing branches
            worktrees = list_worktrees(main_repo)
            worktree_branches = {wt.branch for wt in worktrees}
            all_branches = get_all_branches(main_repo)
            existing_branches = worktree_branches | set(all_branches)

            # Build issue items (may be empty)
            issue_items = []
            for issue in github_issues:
                # Check if any branch starting with gh-{number}- already exists
                issue_prefix = f"gh-{issue.number}-"
                has_existing_branch = any(
                    b.startswith(issue_prefix) or b == f"gh-issue-{issue.number}"
                    for b in existing_branches
                )
                if has_existing_branch:
                    continue
                # Truncate long titles
                title = (
                    issue.title[:50] + "..." if len(issue.title) > 50 else issue.title
                )
                value = f"{ACTION_ISSUE_PREFIX}{issue.number}:{issue.title}"
                issue_items.append(
                    FuzzyItem(
                        text=f"{ISSUE_EMOJI} #{issue.number}: {title}",
                        value=value,
                        meta="",
                        style="cyan",
                    )
                )

            # Always update to remove stale cached issues (even if issue_items is empty)
            # Rebuild to get current state (with dirty checks from fetch thread)
            items_with_issues, _ = _build_fuzzy_items(
                main_repo, current_worktree_branch, preselect_branch
            )
            # Update with issues (update_items merge logic will remove stale items)
            update_items(items_with_issues)

        # Start git fetch thread (updates dirty status)
        fetch_thread = threading.Thread(target=fetch_and_update, daemon=True)
        fetch_thread.start()

        # Start GitHub issues fetch thread (independent, can happen in parallel)
        issues_thread = threading.Thread(target=fetch_github_issues, daemon=True)
        issues_thread.start()

        # Show fuzzy finder immediately with fetching indicator
        # Update functions will be populated in update_callbacks before app.run()
        skip_perms_indicator = "ON" if skip_permissions else "OFF"
        selected = fuzzy_select(
            items=items,
            prompt_text=">",
            header=header_with_indicator,
            hint=(
                "</dim><b>↑↓</b><dim> nav  </dim><b>Enter</b><dim> open  "
                "</dim><b>^O</b><dim> editor  </dim><b>^D</b><dim> del  "
                "</dim><b>^A</b><dim> agent  "
                f"</dim><b>^S</b><dim> skip-perms:{skip_perms_indicator}  "
                "</dim><b>^W</b><dim> workdir  "
                "</dim><b>^P</b><dim> profile  "
                "</dim><b>Esc</b><dim> new  "
                "</dim><b>^C</b><dim> quit"
            ),
            initial_selection=initial_selection,
            on_escape=on_escape,
            on_tab=on_tab,
            on_shift_enter=on_shift_enter,
            on_ctrl_a=on_ctrl_a,
            on_ctrl_s=on_ctrl_s,
            on_ctrl_w=on_ctrl_w,
            on_ctrl_p=on_ctrl_p,
            update_callbacks=update_callbacks,
            update_callbacks_ready=update_callbacks_ready,
            auto_select_value=resolved_auto_select,
            auto_select_timeout=auto_select_timeout,
        )
        # Clear auto-select after first iteration (only auto-select on initial show)
        resolved_auto_select = None

        if selected is None:
            return None

        # Handle "new branch" action (triggered by Esc)
        if selected == ACTION_NEW_BRANCH:
            result = _new_branch_flow(main_repo, agent_num)
            if result:
                # Extract branch name from the path
                new_branch = Path(result).name
                return (result, new_branch)
            # If cancelled or failed, loop back to picker
            continue

        # Handle "change agent" action (triggered by Ctrl+A)
        if selected == ACTION_CHANGE_AGENT:
            new_agent = select_agent(current_agent=selected_agent)
            if new_agent and new_agent != selected_agent:
                selected_agent = new_agent
                rt.agent = selected_agent
                # Profile is agent-scoped; reset it when the agent changes
                rt.agent_profile = None
            # Loop back to picker (whether changed or cancelled)
            continue

        # Handle "toggle skip-permissions" action (triggered by Ctrl+S)
        if selected == ACTION_TOGGLE_SKIP_PERMISSIONS:
            skip_permissions = not skip_permissions
            rt.skip_permissions = skip_permissions
            # Loop back to picker
            continue

        # Handle "change profile" action (triggered by Ctrl+P)
        if selected == ACTION_CHANGE_PROFILE:
            new_profile = select_profile(
                agent_name=selected_agent,
                current_profile=rt.agent_profile,
            )
            if new_profile is not None:
                # "" means <default> (passthrough); any other string is a named profile
                rt.agent_profile = new_profile if new_profile else None
            # Loop back to picker
            continue

        # Handle "change workdir" action (triggered by Ctrl+W)
        if selected == ACTION_CHANGE_WORKDIR:
            if not get_settings().extra_dirs:
                warn(
                    "No extra_dirs configured — add some to hive.yml or "
                    ".hive.local.yml to enable workdir override."
                )
            else:
                new_workdir = select_workdir(
                    current_agent=selected_agent,
                    current_override=rt.workdir,
                )
                if new_workdir is WORKDIR_CLEAR:
                    rt.workdir = None
                    rt.workdir_extras_override = None
                elif new_workdir is not None:
                    rt.workdir = new_workdir
                    # Clear any stale extras override; computed at launch time.
                    rt.workdir_extras_override = None
            # Loop back to picker
            continue

        # Handle "delete" action (triggered by Tab)
        if selected.startswith(ACTION_DELETE_PREFIX):
            branch_to_delete = selected[len(ACTION_DELETE_PREFIX) :]
            _delete_worktree_flow(branch_to_delete, main_repo)
            # Always loop back to picker after delete attempt
            continue

        # Handle "open in editor" action (triggered by Shift+Enter)
        if selected.startswith(ACTION_OPEN_IN_EDITOR_PREFIX):
            branch_to_open = selected[len(ACTION_OPEN_IN_EDITOR_PREFIX) :]
            # Get the path for this branch
            if branch_to_open in ("main", "1"):
                worktree_path = main_repo
            else:
                worktree_path = get_worktree_path(branch_to_open, main_repo)
                if not worktree_path.exists():
                    # Create worktree first
                    result = _create_worktree_flow(branch_to_open, main_repo, agent_num)
                    if not result:
                        # Failed to create, go back to picker
                        continue
                    worktree_path = Path(result)

            # Show editor picker
            editor = select_editor()
            if editor is None:
                # Cancelled, go back to picker
                continue

            # Open in editor, then loop back to picker with this branch selected
            open_in_editor(worktree_path, editor)
            preselect_branch = branch_to_open
            continue

        # Handle GitHub issue selection
        if selected.startswith(ACTION_ISSUE_PREFIX):
            issue_data = selected[len(ACTION_ISSUE_PREFIX) :]
            # Parse "number:title" format
            issue_number_str, issue_title = issue_data.split(":", 1)
            issue_number = int(issue_number_str)
            result = _issue_branch_flow(issue_number, issue_title, main_repo, agent_num)
            if result:
                # Extract branch name from the path
                new_branch = Path(result).name
                return (result, new_branch)
            # If cancelled or failed, loop back to picker
            continue

        # Handle selection
        branch = selected

        # Main repo - just use it
        if branch in ("main", "1"):
            return (str(main_repo), "main")

        # Check if worktree exists
        path = get_worktree_path(branch, main_repo)
        if path.exists():
            # Existing worktree - open immediately
            is_dirty = is_worktree_dirty(path)
            if is_dirty:
                warn(f"⚠ Uncommitted changes in '{branch}'")
            return (str(path), branch)

        # Branch without worktree - create it
        result = _create_worktree_flow(branch, main_repo, agent_num)
        if result:
            return (result, branch)
        # On failure, go back to selection


# Shell completion


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

    result = _interactive_ensure(agent_num=0)
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
        path = create_worktree(branch)
        success(f"Created worktree at {path}")

        setup_worktree_files(path, get_main_repo())

        if install:
            info("Installing dependencies...")
            if install_dependencies(path):
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


@wt_app.command(name="exec")
def exec_cmd(
    command: Annotated[
        str,
        Parameter(
            name=["--command", "-c"],
            help="Command to execute (shell string).",
        ),
    ],
    worktree: Annotated[
        str | None,
        Parameter(
            name=["--worktree", "-w"],
            help="Run in worktree. Use '-' for selection, or specify branch.",
        ),
    ] = None,
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
        hive wt exec -c 'make watch' --restart      # Auto-restart (re-select each time)
        hive wt exec -c 'make watch' --restart -w feat  # Restart in specific worktree
        hive wt exec -c 'date' --restart --restart-delay 1
        hive wt exec -c 'npm test' --restart-confirmation  # Manual restart
    """
    import shlex

    from .exec_runner import run_in_worktree

    _check_worktrees_enabled()

    # Parse the command string into a list
    try:
        cmd = shlex.split(command)
    except ValueError as e:
        error(f"Invalid command: {e}")
        sys.exit(1)

    if not cmd:
        error("Command cannot be empty")
        sys.exit(1)

    exit_code = run_in_worktree(
        cmd,
        worktree=worktree,
        restart=restart,
        restart_confirmation=restart_confirmation,
        restart_delay=restart_delay,
        use_execvp=not restart and not restart_confirmation,
        layout_has_base_name=True,  # Append branch to existing pane name
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

    result = _interactive_ensure(agent_num)
    if result:
        path, _branch = result
        print(path)
    else:
        sys.exit(1)
