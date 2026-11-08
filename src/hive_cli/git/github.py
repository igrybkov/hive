"""GitHub issue integration: repo detection, issue list/detail fetch, and cache.

Moved from commands/wt.py:71-297 (A0 wt.py pass), converting subprocess.run
calls to core.proc.run. proc.run turns a missing `gh`/`git` binary into
returncode 127 and a timeout into 124, so the old FileNotFoundError/
TimeoutExpired excepts are redundant with the `not result.ok` branch and
are dropped; the JSON-parsing exceptions stay.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ..config import get_runtime_settings, get_settings
from ..core import proc


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


def get_github_repo_info(main_repo: Path) -> tuple[str, str] | None:
    """Get GitHub org and repo name from git remote.

    Args:
        main_repo: Path to the main repository.

    Returns:
        Tuple of (org, repo) or None if not a GitHub repo.
    """
    result = proc.run(
        ["git", "-C", str(main_repo), "remote", "get-url", "origin"],
        timeout=10,
    )
    if not result.ok:
        return None
    remote_url = result.stdout.strip()

    # Handle both SSH and HTTPS URLs
    # git@github.com:org/repo.git or https://github.com/org/repo.git
    if "github.com" not in remote_url:
        return None

    if remote_url.startswith("git@"):
        # SSH: git@github.com:org/repo.git
        parts = remote_url.split(":")[-1].replace(".git", "").split("/")
    elif remote_url.startswith(("https://", "http://")):
        # HTTPS: https://github.com/org/repo.git
        parts = remote_url.split("github.com/")[-1].replace(".git", "").split("/")
    else:
        return None

    if len(parts) >= 2:
        return (parts[0], parts[1])
    return None


def get_issues_cache_path(main_repo: Path) -> Path | None:
    """Get the cache file path for GitHub issues.

    Args:
        main_repo: Path to the main repository.

    Returns:
        Path to cache file, or None if not a GitHub repo.
    """
    repo_info = get_github_repo_info(main_repo)
    if not repo_info:
        return None

    org, repo = repo_info
    cache_dir = Path(str(get_runtime_settings().xdg_cache_home)) / "hive"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / f"gh-{org}--{repo}-issues.json"


def load_cached_issues(cache_path: Path | None) -> list[GitHubIssue]:
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


def save_cached_issues(issues: list[GitHubIssue], cache_path: Path | None) -> None:
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


def fetch_issues(
    main_repo: Path, *, cache_path: Path | None = None
) -> list[GitHubIssue] | None:
    """Fetch GitHub issues assigned to the current user.

    Uses github.fetch_issues and github.issue_limit from config.

    Args:
        main_repo: Path to the main repository.
        cache_path: Where to save the result; computed from the remote when
            None (one `git remote get-url` spawn).

    Returns:
        List of GitHub issues if fetch succeeded (may be empty),
        or None if disabled or fetch failed.
    """
    config = get_settings()

    # Check if issue fetching is enabled
    if not config.github.fetch_issues:
        return None

    result = proc.run(
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
        cwd=main_repo,
        timeout=2,
    )
    if not result.ok:
        return None

    try:
        issues_data = json.loads(result.stdout)
        issues = [
            GitHubIssue(number=issue["number"], title=issue["title"])
            for issue in issues_data
        ]
        # Save to cache (even if empty - to clear closed issues)
        if cache_path is None:
            cache_path = get_issues_cache_path(main_repo)
        save_cached_issues(issues, cache_path)
        return issues
    except json.JSONDecodeError:
        # gh returned something that isn't JSON - silently ignore
        return None
    except Exception:
        # Any other error - silently ignore
        return None


def fetch_issue_details(
    issue_number: int, main_repo: Path
) -> GitHubIssueDetails | None:
    """Fetch full details of a GitHub issue.

    Args:
        issue_number: GitHub issue number.
        main_repo: Path to the main repository.

    Returns:
        Issue details, or None if fetch fails.
    """
    result = proc.run(
        ["gh", "issue", "view", str(issue_number), "--json", "number,title,url,body"],
        cwd=main_repo,
        timeout=5,
    )
    if not result.ok:
        return None

    try:
        data = json.loads(result.stdout)
        return GitHubIssueDetails(
            number=data["number"],
            title=data["title"],
            url=data["url"],
            body=data.get("body", "") or "",
        )
    except Exception:
        return None
