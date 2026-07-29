"""Pytest configuration and fixtures."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from io import StringIO
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from cyclopts import App


@dataclass
class Result:
    """Result from CLI invocation, similar to Click's Result."""

    exit_code: int
    output: str
    exception: Exception | None = None


class CycloptsTestRunner:
    """Test runner for Cyclopts apps, similar to Click's CliRunner."""

    def invoke(self, app: App, args: list[str]) -> Result:
        """Invoke a Cyclopts app with arguments.

        Args:
            app: The Cyclopts App to invoke.
            args: Command line arguments to pass.

        Returns:
            Result object with exit_code, output, and optional exception.
        """
        # Capture stdout/stderr
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        old_argv = sys.argv
        sys.stdout = captured_out = StringIO()
        sys.stderr = captured_err = StringIO()
        # Set sys.argv to simulate real CLI invocation
        sys.argv = ["hive", *args]

        exit_code = 0
        exception = None

        try:
            app(args)
        except SystemExit as e:
            exit_code = e.code if isinstance(e.code, int) else (1 if e.code else 0)
        except KeyboardInterrupt:
            exit_code = 0  # Treat as clean exit for tests
        except Exception as e:
            exception = e
            exit_code = 1
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr
            sys.argv = old_argv

        output = captured_out.getvalue() + captured_err.getvalue()
        return Result(exit_code=exit_code, output=output, exception=exception)


@pytest.fixture(autouse=True)
def clean_environment(tmp_path, monkeypatch):
    """Clean environment for all tests.

    Sets XDG_CONFIG_HOME to an empty temp dir to avoid picking up
    the user's global config, and clears HIVE_PANE_ID to ensure
    consistent agent_num behavior.
    """
    # Set XDG_CONFIG_HOME to empty dir to avoid global config
    xdg_dir = tmp_path / "xdg_config"
    xdg_dir.mkdir()
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg_dir))

    # Clear HIVE_PANE_ID to ensure consistent agent_num=0
    monkeypatch.delenv("HIVE_PANE_ID", raising=False)

    # Set ZELLIJ to empty to disable pane renaming in tests
    monkeypatch.delenv("ZELLIJ", raising=False)

    # Clear config-related env vars (both new HIVE_* and legacy)
    monkeypatch.delenv("AGENT", raising=False)
    monkeypatch.delenv("HIVE_AGENT", raising=False)
    monkeypatch.delenv("HIVE_AGENT_PROFILE", raising=False)
    monkeypatch.delenv("HIVE_SKIP_PERMISSIONS", raising=False)
    monkeypatch.delenv("HIVE_AGENTS_ORDER", raising=False)
    monkeypatch.delenv("HIVE_RESUME_ENABLED", raising=False)
    monkeypatch.delenv("HIVE_WORKTREES_ENABLED", raising=False)
    monkeypatch.delenv("HIVE_WORKTREES_PARENT_DIR", raising=False)
    monkeypatch.delenv("HIVE_WORKTREES_RESUME", raising=False)
    monkeypatch.delenv("HIVE_WORKTREES_SKIP_PERMISSIONS", raising=False)
    monkeypatch.delenv("HIVE_ZELLIJ_LAYOUT", raising=False)
    monkeypatch.delenv("HIVE_ZELLIJ_SESSION_NAME", raising=False)
    monkeypatch.delenv("HIVE_GITHUB_FETCH_ISSUES", raising=False)
    monkeypatch.delenv("HIVE_GITHUB_ISSUE_LIMIT", raising=False)

    # Reset settings singletons and eagerly repopulate.
    # Eagerly creating settings ensures find_git_root() subprocess call
    # happens here (outside test mock contexts), not during the test.
    from hive_cli.config import get_settings, reset_settings

    reset_settings()
    get_settings()

    import hive_cli.config.runtime as _rt_mod

    _rt_mod._runtime_settings = None


@pytest.fixture
def cli_runner() -> CycloptsTestRunner:
    """Provide a Cyclopts CLI test runner."""
    return CycloptsTestRunner()


@pytest.fixture
def temp_git_repo(tmp_path, monkeypatch):
    """Create a temporary git repository for testing."""
    import subprocess

    repo_path = tmp_path / "test-repo"
    repo_path.mkdir()

    # Initialize git repo
    subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )

    # Create initial commit
    readme = repo_path / "README.md"
    readme.write_text("# Test Repository\n")
    subprocess.run(["git", "add", "."], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )

    # Change to repo directory
    monkeypatch.chdir(repo_path)

    return repo_path
