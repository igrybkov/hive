"""Pytest configuration and fixtures."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
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


@pytest.fixture
def short_tmp():
    """A short temp path: Unix socket paths must stay under 104 bytes on macOS."""
    path = Path(tempfile.mkdtemp(prefix="hv", dir="/tmp"))
    yield path
    shutil.rmtree(path, ignore_errors=True)


@pytest.fixture(autouse=True)
def clean_environment(tmp_path, short_tmp, monkeypatch):
    """Clean environment for all tests.

    Sets XDG_CONFIG_HOME to an empty temp dir to avoid picking up
    the user's global config, and clears HIVE_PANE_ID to ensure
    consistent agent_num behavior.
    """
    # Set XDG_CONFIG_HOME to empty dir to avoid global config
    xdg_dir = tmp_path / "xdg_config"
    xdg_dir.mkdir()
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg_dir))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(short_tmp))
    for var in (
        "HIVE_PANE_LABEL",
        "HIVE_PANE_SOCK",
        "HIVE_TRACE",
        "HIVE_MUX_BACKEND",
        "ZELLIJ_PANE_ID",
        "ZELLIJ_SESSION_NAME",
        "TMUX",
        "TMUX_PANE",
    ):
        monkeypatch.delenv(var, raising=False)

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
    monkeypatch.delenv("HIVE_ZELLIJ_PANE_LABELS", raising=False)
    monkeypatch.delenv("HIVE_GITHUB_FETCH_ISSUES", raising=False)
    monkeypatch.delenv("HIVE_GITHUB_ISSUE_LIMIT", raising=False)

    # Isolate git from the developer's global config (commit signing, hooks,
    # default branch name). Worktree placement is opt-in: see isolated_worktrees.
    git_config = tmp_path / "gitconfig"
    git_config.write_text(
        "[user]\n\tname = Test User\n\temail = test@example.com\n"
        "[commit]\n\tgpgsign = false\n"
        "[init]\n\tdefaultBranch = main\n"
        "[advice]\n\tdetachedHead = false\n"
    )
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(git_config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")

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


# ---------------------------------------------------------------------------
# Git helpers for integration tests (real repositories, no mocks)
# ---------------------------------------------------------------------------


def git(*args: str, cwd: Path) -> str:
    """Run git in ``cwd`` and return stripped stdout. Raises on failure."""
    result = subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def commit_file(repo: Path, name: str, content: str, message: str | None = None) -> str:
    """Write ``name`` with ``content`` inside ``repo``, commit it, return short hash."""
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    git("add", "-A", cwd=repo)
    git("commit", "-q", "-m", message or f"update {name}", cwd=repo)
    return git("rev-parse", "--short", "HEAD", cwd=repo)


@pytest.fixture
def repo_with_origin(temp_git_repo: Path, tmp_path: Path) -> Path:
    """``temp_git_repo`` with a bare ``origin`` remote that already has ``main``.

    ``main`` tracks ``origin/main`` so ahead/behind, fetch and remote-branch
    code paths can be exercised without any network access.
    """
    origin = tmp_path / "origin.git"
    subprocess.run(
        ["git", "clone", "--bare", "-q", str(temp_git_repo), str(origin)],
        check=True,
        capture_output=True,
    )
    git("remote", "add", "origin", str(origin), cwd=temp_git_repo)
    git("fetch", "-q", "origin", cwd=temp_git_repo)
    git("branch", "--set-upstream-to=origin/main", "main", cwd=temp_git_repo)
    return temp_git_repo


@pytest.fixture
def isolated_worktrees(tmp_path: Path, monkeypatch):
    """Place worktrees created by tests under the test's temp dir, never ~/.worktrees.

    Opt-in because several config/path tests assert the default template.
    Yields the base directory.
    """
    from hive_cli.config import reset_settings

    monkeypatch.setenv(
        "HIVE_WORKTREES_PARENT_DIR",
        str(tmp_path / ".worktrees" / "{repo}" / "{branch}"),
    )
    reset_settings()
    yield tmp_path / ".worktrees"
    reset_settings()


@dataclass
class Scripted:
    stdout: str = ""
    stderr: str = ""
    returncode: int = 0


class FakeProc:
    """Stands in for hive_cli.core.proc.run: records argv, returns scripted output."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.scripts: list[tuple[tuple[str, ...], Scripted]] = []

    def script(self, prefix, *, stdout="", stderr="", returncode=0):
        self.scripts.append((tuple(prefix), Scripted(stdout, stderr, returncode)))

    def count(self, *prefix: str) -> int:
        return sum(1 for c in self.calls if tuple(c[: len(prefix)]) == prefix)

    def __call__(self, argv, **kwargs):
        from hive_cli.core import proc
        from hive_cli.core.errors import ProcError

        argv = [str(a) for a in argv]
        self.calls.append(argv)
        for prefix, s in self.scripts:
            if tuple(argv[: len(prefix)]) == prefix:
                result = proc.Result(tuple(argv), s.returncode, s.stdout, s.stderr)
                break
        else:
            result = proc.Result(tuple(argv), 0, "", "")
        if kwargs.get("check") and result.returncode != 0:
            raise ProcError(result)
        return result


@pytest.fixture
def fake_proc(monkeypatch) -> FakeProc:
    fp = FakeProc()
    monkeypatch.setattr("hive_cli.core.proc.run", fp)
    return fp


class FakeGh:
    """Fakes only `gh`-prefixed core.proc.run calls; every other argv (git,
    etc.) runs for real. Use this instead of fake_proc whenever a test needs
    a real git repo/remote alongside a scripted `gh` response -- the hard
    rule elsewhere in this suite is "never mock git".
    """

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.scripts: list[tuple[tuple[str, ...], Scripted]] = []

    def script(self, prefix, *, stdout="", stderr="", returncode=0):
        self.scripts.append((tuple(prefix), Scripted(stdout, stderr, returncode)))

    def count(self, *prefix: str) -> int:
        return sum(1 for c in self.calls if tuple(c[: len(prefix)]) == prefix)


@pytest.fixture
def fake_gh(monkeypatch) -> FakeGh:
    from hive_cli.core import proc

    real_run = proc.run
    fg = FakeGh()

    def run(argv, **kwargs):
        argv = [str(a) for a in argv]
        if argv[0] != "gh":
            return real_run(argv, **kwargs)
        fg.calls.append(argv)
        for prefix, s in fg.scripts:
            if tuple(argv[: len(prefix)]) == prefix:
                return proc.Result(tuple(argv), s.returncode, s.stdout, s.stderr)
        return proc.Result(tuple(argv), 1, "", "gh: no script matched")

    monkeypatch.setattr("hive_cli.core.proc.run", run)
    return fg


@pytest.fixture
def make_worktree(temp_git_repo: Path, isolated_worktrees: Path):
    """Factory: ``make_worktree("feat")`` creates a real worktree and returns its path.

    Uses hive's own ``create_worktree`` (path templates) plus
    ``setup_handoff_symlink`` (same two calls `wt create` makes) so worktrees
    behave exactly as in production. The branch is created from ``main``.
    """
    from hive_cli.git import create_worktree
    from hive_cli.services import handoffs

    def _make(branch: str) -> Path:
        path = create_worktree(branch, temp_git_repo)
        handoffs.setup_handoff_symlink(path, branch, temp_git_repo)
        return path

    return _make
