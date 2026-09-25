"""Tests for services/worktrees.py.

Moved from test_utils_misc.py (A0 step 6): the code these test now lives
in services/worktrees.py, so patch targets moved from hive_cli.utils.deps.*
to hive_cli.services.worktrees.*.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path
from unittest.mock import patch

import pytest

from hive_cli.config import reload_config
from hive_cli.git import get_current_branch, worktree_exists
from hive_cli.services.worktrees import (
    detect_package_manager,
    ensure_mise_trusted,
    install_dependencies,
    provision,
    remove,
    run_post_create_commands,
    setup_agent_context,
)

# ---------------------------------------------------------------------------
# run_post_create_commands / install_dependencies
# ---------------------------------------------------------------------------


class TestRunPostCreateCommands:
    def _configure(self, repo: Path, yaml_body: str) -> None:
        (repo / ".hive.yml").write_text(yaml_body)
        reload_config()

    def test_command_runs_when_if_exists_matches(self, temp_git_repo):
        self._configure(
            temp_git_repo,
            "worktrees:\n"
            "  post_create:\n"
            "    - command: touch created.marker\n"
            "      if_exists: README.md\n",
        )

        assert run_post_create_commands(temp_git_repo) is True
        assert (temp_git_repo / "created.marker").exists()

    def test_command_skipped_when_if_exists_missing(self, temp_git_repo):
        self._configure(
            temp_git_repo,
            "worktrees:\n"
            "  post_create:\n"
            "    - command: touch created.marker\n"
            "      if_exists: does-not-exist.txt\n",
        )

        assert run_post_create_commands(temp_git_repo) is True
        assert not (temp_git_repo / "created.marker").exists()

    def test_command_without_if_exists_always_runs(self, temp_git_repo):
        self._configure(
            temp_git_repo, "worktrees:\n  post_create:\n    - touch created.marker\n"
        )

        assert run_post_create_commands(temp_git_repo) is True
        assert (temp_git_repo / "created.marker").exists()

    def test_failing_command_returns_false_but_continues(self, temp_git_repo):
        self._configure(
            temp_git_repo,
            "worktrees:\n"
            "  post_create:\n"
            "    - command: exit 1\n"
            "    - command: touch created.marker\n",
        )

        assert run_post_create_commands(temp_git_repo) is False
        # The later, successful command still ran.
        assert (temp_git_repo / "created.marker").exists()

    def test_no_post_create_commands_returns_true(self, temp_git_repo):
        self._configure(temp_git_repo, "worktrees:\n  post_create: []\n")
        assert run_post_create_commands(temp_git_repo) is True

    def test_post_create_commands_run_through_proc(self, temp_git_repo, fake_proc):
        self._configure(
            temp_git_repo,
            "worktrees:\n"
            "  post_create:\n"
            "    - command: pnpm install\n"
            "      if_exists: README.md\n",
        )

        run_post_create_commands(temp_git_repo)

        assert fake_proc.calls == [["sh", "-c", "pnpm install"]]


class TestInstallDependencies:
    def test_delegates_to_post_create_commands(self, temp_git_repo):
        (temp_git_repo / ".hive.yml").write_text(
            "worktrees:\n  post_create:\n    - touch installed.marker\n"
        )
        reload_config()

        assert install_dependencies(temp_git_repo) is True
        assert (temp_git_repo / "installed.marker").exists()


# ---------------------------------------------------------------------------
# detect_package_manager
# ---------------------------------------------------------------------------


class TestDetectPackageManager:
    def test_pnpm_lock_detected(self, tmp_path):
        (tmp_path / "package.json").write_text("{}")
        (tmp_path / "pnpm-lock.yaml").write_text("")
        assert detect_package_manager(tmp_path) == "pnpm"

    def test_yarn_lock_detected(self, tmp_path):
        (tmp_path / "package.json").write_text("{}")
        (tmp_path / "yarn.lock").write_text("")
        assert detect_package_manager(tmp_path) == "yarn"

    def test_npm_lock_detected(self, tmp_path):
        (tmp_path / "package.json").write_text("{}")
        (tmp_path / "package-lock.json").write_text("")
        assert detect_package_manager(tmp_path) == "npm"

    def test_package_json_without_lockfile_defaults_to_npm(self, tmp_path):
        (tmp_path / "package.json").write_text("{}")
        assert detect_package_manager(tmp_path) == "npm"

    def test_python_project_with_uv_available(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("")
        with patch(
            "hive_cli.services.worktrees.shutil.which", return_value="/usr/bin/uv"
        ):
            assert detect_package_manager(tmp_path) == "uv"

    def test_python_project_without_uv_returns_none(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("")
        with patch("hive_cli.services.worktrees.shutil.which", return_value=None):
            assert detect_package_manager(tmp_path) is None

    def test_no_recognized_project_returns_none(self, tmp_path):
        assert detect_package_manager(tmp_path) is None


# ---------------------------------------------------------------------------
# ensure_mise_trusted
# ---------------------------------------------------------------------------


def _write_fake_mise(bin_dir: Path, *, list_exit: int, trust_exit: int) -> None:
    """Write a tiny fake `mise` executable that mimics list/trust exit codes."""
    script = bin_dir / "mise"
    script.write_text(
        "#!/bin/sh\n"
        f'if [ "$1" = "list" ]; then exit {list_exit}; fi\n'
        f'if [ "$1" = "trust" ]; then exit {trust_exit}; fi\n'
        "exit 0\n"
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


class TestEnsureMiseTrusted:
    def test_mise_not_installed_returns_true(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "hive_cli.services.worktrees.shutil.which", lambda _name: None
        )
        assert ensure_mise_trusted(tmp_path) is True

    def test_no_mise_config_file_returns_true_without_running_mise(
        self, tmp_path, monkeypatch
    ):
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        _write_fake_mise(bin_dir, list_exit=1, trust_exit=1)
        monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")

        project = tmp_path / "project"
        project.mkdir()
        # No .mise.toml / mise.toml / .tool-versions present.
        assert ensure_mise_trusted(project) is True

    def test_already_trusted_config_returns_true(self, tmp_path, monkeypatch):
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        _write_fake_mise(bin_dir, list_exit=0, trust_exit=1)
        monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")

        project = tmp_path / "project"
        project.mkdir()
        (project / ".mise.toml").write_text("")

        assert ensure_mise_trusted(project) is True

    def test_untrusted_config_gets_trusted(self, tmp_path, monkeypatch):
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        _write_fake_mise(bin_dir, list_exit=1, trust_exit=0)
        monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")

        project = tmp_path / "project"
        project.mkdir()
        (project / "mise.toml").write_text("")

        assert ensure_mise_trusted(project) is True

    def test_trust_command_failure_returns_false(self, tmp_path, monkeypatch):
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        _write_fake_mise(bin_dir, list_exit=1, trust_exit=1)
        monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")

        project = tmp_path / "project"
        project.mkdir()
        (project / ".tool-versions").write_text("")

        assert ensure_mise_trusted(project) is False


# ---------------------------------------------------------------------------
# setup_agent_context
# ---------------------------------------------------------------------------


class TestSetupAgentContext:
    def test_writes_context_file(self, tmp_path):
        setup_agent_context(tmp_path, agent_num=3, branch_name="feat-x")

        content = (tmp_path / ".claude" / "worktree-context.md").read_text()
        assert "Agent 3" in content
        assert "feat-x" in content
        assert str(tmp_path) in content


# ---------------------------------------------------------------------------
# provision
# ---------------------------------------------------------------------------


class TestProvision:
    def test_creates_worktree_and_symlinks_handoff(
        self, temp_git_repo, isolated_worktrees
    ):
        progress_lines: list[str] = []

        path = provision("feat-a", temp_git_repo, progress=progress_lines.append)

        assert path.exists()
        assert get_current_branch(path) == "feat-a"
        # setup_handoff_symlink creates .claude/HANDOFF.md as a symlink into
        # the central handoffs dir; just assert provision() didn't skip it.
        assert (path / ".claude" / "HANDOFF.md").is_symlink()
        assert any("Creating worktree" in line for line in progress_lines)
        assert any("Created worktree" in line for line in progress_lines)

    def test_agent_context_written_when_agent_num_positive(
        self, temp_git_repo, isolated_worktrees
    ):
        path = provision("feat-a", temp_git_repo, agent_num=2)

        context_file = path / ".claude" / "worktree-context.md"
        assert context_file.exists()
        assert "Agent 2" in context_file.read_text()

    def test_no_agent_context_when_agent_num_zero(
        self, temp_git_repo, isolated_worktrees
    ):
        path = provision("feat-a", temp_git_repo, agent_num=0)

        assert not (path / ".claude" / "worktree-context.md").exists()

    def test_raises_for_main_branch(self, temp_git_repo, isolated_worktrees):
        # provision() lets create_worktree()'s exceptions propagate; the
        # caller (a ui/flows/worktrees.py flow) owns the try/except.
        with pytest.raises(ValueError, match="main branch"):
            provision("main", temp_git_repo)


# ---------------------------------------------------------------------------
# remove
# ---------------------------------------------------------------------------


class TestRemove:
    def test_confirmed_deletes_worktree(self, temp_git_repo, make_worktree):
        wt_path = make_worktree("feat-a")

        deleted, error = remove("feat-a", temp_git_repo, confirmed=True)

        assert deleted is True
        assert error is None
        assert not wt_path.exists()
        assert worktree_exists("feat-a", temp_git_repo) is False

    def test_not_confirmed_is_a_noop(self, temp_git_repo, make_worktree):
        wt_path = make_worktree("feat-a")

        deleted, error = remove("feat-a", temp_git_repo, confirmed=False)

        assert deleted is False
        assert error is None
        assert wt_path.exists()

    def test_failure_is_reported_not_raised(self, temp_git_repo, make_worktree):
        wt_path = make_worktree("feat-a")

        with patch(
            "hive_cli.services.worktrees.delete_worktree",
            side_effect=RuntimeError("boom"),
        ):
            deleted, error = remove("feat-a", temp_git_repo, confirmed=True)

        assert deleted is False
        assert error == "boom"
        # delete_worktree was mocked, so the real worktree is untouched.
        assert wt_path.exists()
