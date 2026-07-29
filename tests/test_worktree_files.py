"""Tests for worktree file setup (symlink_files / copy_files)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from hive_cli.utils.deps import setup_worktree_files


def _make_config(symlink_files=None, copy_files=None):
    """Create a mock config with worktree file settings."""
    from unittest.mock import MagicMock

    config = MagicMock()
    config.worktrees.symlink_files = symlink_files or []
    config.worktrees.copy_files = copy_files or []
    return config


class TestSetupWorktreeFiles:
    """Tests for setup_worktree_files function."""

    def test_empty_config(self, tmp_path: Path):
        """No files configured — returns True immediately."""
        main = tmp_path / "main"
        wt = tmp_path / "wt"
        main.mkdir()
        wt.mkdir()

        with patch("hive_cli.utils.deps.load_config", return_value=_make_config()):
            assert setup_worktree_files(wt, main) is True

    def test_symlink_created(self, tmp_path: Path):
        """Symlink points from worktree to main repo."""
        main = tmp_path / "main"
        wt = tmp_path / "wt"
        main.mkdir()
        wt.mkdir()
        (main / ".env").write_text("SECRET=42")

        with patch(
            "hive_cli.utils.deps.load_config",
            return_value=_make_config(symlink_files=[".env"]),
        ):
            assert setup_worktree_files(wt, main) is True

        target = wt / ".env"
        assert target.is_symlink()
        assert target.resolve() == (main / ".env").resolve()
        assert target.read_text() == "SECRET=42"

    def test_copy_created(self, tmp_path: Path):
        """Copy is a regular file with same content."""
        main = tmp_path / "main"
        wt = tmp_path / "wt"
        main.mkdir()
        wt.mkdir()
        (main / ".env").write_text("SECRET=42")

        with patch(
            "hive_cli.utils.deps.load_config",
            return_value=_make_config(copy_files=[".env"]),
        ):
            assert setup_worktree_files(wt, main) is True

        target = wt / ".env"
        assert not target.is_symlink()
        assert target.read_text() == "SECRET=42"

    def test_nested_path_creates_parents(self, tmp_path: Path):
        """Nested paths like config/.env create intermediate directories."""
        main = tmp_path / "main"
        wt = tmp_path / "wt"
        main.mkdir()
        wt.mkdir()
        (main / "config").mkdir()
        (main / "config" / ".env").write_text("NESTED=1")

        with patch(
            "hive_cli.utils.deps.load_config",
            return_value=_make_config(symlink_files=["config/.env"]),
        ):
            assert setup_worktree_files(wt, main) is True

        assert (wt / "config" / ".env").is_symlink()

    def test_source_missing_warns_and_skips(self, tmp_path: Path):
        """Missing source file returns False and creates no target."""
        main = tmp_path / "main"
        wt = tmp_path / "wt"
        main.mkdir()
        wt.mkdir()

        with patch(
            "hive_cli.utils.deps.load_config",
            return_value=_make_config(symlink_files=[".env"]),
        ):
            assert setup_worktree_files(wt, main) is False

        assert not (wt / ".env").exists()

    def test_target_exists_warns_and_skips(self, tmp_path: Path):
        """Existing target is not overwritten."""
        main = tmp_path / "main"
        wt = tmp_path / "wt"
        main.mkdir()
        wt.mkdir()
        (main / ".env").write_text("NEW")
        (wt / ".env").write_text("OLD")

        with patch(
            "hive_cli.utils.deps.load_config",
            return_value=_make_config(symlink_files=[".env"]),
        ):
            assert setup_worktree_files(wt, main) is False

        assert (wt / ".env").read_text() == "OLD"

    def test_absolute_path_rejected(self, tmp_path: Path):
        """Absolute paths are skipped."""
        main = tmp_path / "main"
        wt = tmp_path / "wt"
        main.mkdir()
        wt.mkdir()

        with patch(
            "hive_cli.utils.deps.load_config",
            return_value=_make_config(symlink_files=["/etc/passwd"]),
        ):
            assert setup_worktree_files(wt, main) is False

    def test_mixed_success_and_failure(self, tmp_path: Path):
        """Returns False if any file fails, but processes all."""
        main = tmp_path / "main"
        wt = tmp_path / "wt"
        main.mkdir()
        wt.mkdir()
        (main / ".env").write_text("OK")
        # .secrets does not exist in main

        with patch(
            "hive_cli.utils.deps.load_config",
            return_value=_make_config(symlink_files=[".env", ".secrets"]),
        ):
            assert setup_worktree_files(wt, main) is False

        # .env should still have been created
        assert (wt / ".env").is_symlink()
        assert not (wt / ".secrets").exists()
