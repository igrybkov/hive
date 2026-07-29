"""Tests for git worktree module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from hive_cli.config import reload_config
from hive_cli.git.worktree import (
    WorktreeInfo,
    _path_to_name,
    expand_path,
    get_worktree_path,
    get_worktrees_base,
    list_worktrees,
    sanitize_branch_name,
    worktree_exists,
)


class TestSanitizeBranchName:
    """Tests for sanitize_branch_name function."""

    def test_simple_branch(self):
        """Test branch name with no special characters."""
        assert sanitize_branch_name("feature-123") == "feature-123"

    def test_branch_with_slash(self):
        """Test branch name with slashes becomes double dashes."""
        assert sanitize_branch_name("user/feat/update") == "user--feat--update"

    def test_single_slash(self):
        """Test branch with single slash."""
        assert sanitize_branch_name("user/feature") == "user--feature"

    def test_special_characters(self):
        """Test special characters are replaced with dashes."""
        assert sanitize_branch_name("feat@test!") == "feat-test"

    def test_leading_trailing_dashes_removed(self):
        """Test leading/trailing dashes are trimmed."""
        assert sanitize_branch_name("-feat-") == "feat"

    def test_underscores_preserved(self):
        """Test underscores are preserved."""
        assert sanitize_branch_name("feat_test_123") == "feat_test_123"

    def test_dots_preserved(self):
        """Test dots are preserved."""
        assert sanitize_branch_name("v1.2.3-fix") == "v1.2.3-fix"


class TestPathToName:
    """Tests for _path_to_name function."""

    def test_path_under_home(self):
        """Test path relative to home uses double-dash separator."""
        home = Path.home()
        path = home / "Projects" / "dotfiles"
        assert _path_to_name(path) == "Projects--dotfiles"

    def test_path_not_under_home(self):
        """Test path not under home uses full path with double dashes."""
        path = Path("/opt/repos/myproject")
        assert _path_to_name(path) == "opt--repos--myproject"

    def test_nested_path(self):
        """Test deeply nested path."""
        home = Path.home()
        path = home / "work" / "org" / "repo"
        assert _path_to_name(path) == "work--org--repo"


class TestGetWorktreesBase:
    """Tests for get_worktrees_base function."""

    def test_default_template_with_repo(self, monkeypatch, tmp_path):
        """Test default ~/.worktrees/{repo}/{branch} returns repo dir as base."""
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        reload_config()

        repo = Path.home() / "Projects" / "myrepo"
        with patch("hive_cli.git.worktree.get_main_repo", return_value=repo):
            base = get_worktrees_base()
            assert base == Path.home() / ".worktrees" / "Projects--myrepo"

    def test_custom_parent_dir_no_placeholders(self, monkeypatch, tmp_path):
        """Test custom parent_dir without placeholders."""
        config_file = tmp_path / ".hive.yml"
        config_file.write_text("worktrees:\n  parent_dir: custom-wt\n")

        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))

        with patch(
            "hive_cli.config.loader.find_config_files", return_value=[config_file]
        ):
            reload_config()
            with patch("hive_cli.git.worktree.get_main_repo", return_value=tmp_path):
                base = get_worktrees_base()
                assert base == tmp_path / "custom-wt"

    def test_parent_dir_with_repo_placeholder(self, monkeypatch, tmp_path):
        """Test parent_dir with {repo} placeholder expands correctly."""
        config_file = tmp_path / ".hive.yml"
        config_file.write_text('worktrees:\n  parent_dir: "~/.worktrees/{repo}"\n')

        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))

        repo = Path.home() / "Projects" / "dotfiles"
        with patch(
            "hive_cli.config.loader.find_config_files", return_value=[config_file]
        ):
            reload_config()
            with patch("hive_cli.git.worktree.get_main_repo", return_value=repo):
                base = get_worktrees_base()
                assert base == Path.home() / ".worktrees" / "Projects--dotfiles"

    def test_parent_dir_with_branch_strips_to_base(self, monkeypatch, tmp_path):
        """Test parent_dir with {branch} strips it for the base."""
        config_file = tmp_path / ".hive.yml"
        config_file.write_text('worktrees:\n  parent_dir: "~/.wt/{repo}/{branch}"\n')

        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))

        repo = Path.home() / "Projects" / "myrepo"
        with patch(
            "hive_cli.config.loader.find_config_files", return_value=[config_file]
        ):
            reload_config()
            with patch("hive_cli.git.worktree.get_main_repo", return_value=repo):
                base = get_worktrees_base()
                assert base == Path.home() / ".wt" / "Projects--myrepo"

    def test_explicit_main_repo(self, monkeypatch, tmp_path):
        """Test passing explicit main_repo."""
        config_file = tmp_path / ".hive.yml"
        config_file.write_text('worktrees:\n  parent_dir: ".worktrees"\n')

        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))

        with patch(
            "hive_cli.config.loader.find_config_files", return_value=[config_file]
        ):
            reload_config()
            base = get_worktrees_base(tmp_path)
            assert base == tmp_path / ".worktrees"


class TestGetWorktreePath:
    """Tests for get_worktree_path function."""

    def test_main_returns_main_repo(self, tmp_path):
        """Test 'main' returns main repo path."""
        path = get_worktree_path("main", tmp_path)
        assert path == tmp_path

    def test_one_returns_main_repo(self, tmp_path):
        """Test '1' returns main repo path."""
        path = get_worktree_path("1", tmp_path)
        assert path == tmp_path

    def test_template_with_repo_and_branch(self, monkeypatch, tmp_path):
        """Test full template with {repo} and {branch} placeholders."""
        config_file = tmp_path / ".hive.yml"
        config_file.write_text(
            'worktrees:\n  parent_dir: "~/.worktrees/{repo}/{branch}"\n'
        )

        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))

        repo = Path.home() / "Projects" / "dotfiles"
        with patch(
            "hive_cli.config.loader.find_config_files", return_value=[config_file]
        ):
            reload_config()
            path = get_worktree_path("feature-123", repo)
            assert path == (
                Path.home() / ".worktrees" / "Projects--dotfiles" / "feature-123"
            )

    def test_template_with_only_repo(self, monkeypatch, tmp_path):
        """Test template with {repo} only appends branch as subdir."""
        config_file = tmp_path / ".hive.yml"
        config_file.write_text('worktrees:\n  parent_dir: "~/.worktrees/{repo}"\n')

        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))

        repo = Path.home() / "Projects" / "dotfiles"
        with patch(
            "hive_cli.config.loader.find_config_files", return_value=[config_file]
        ):
            reload_config()
            path = get_worktree_path("feature-123", repo)
            assert path == (
                Path.home() / ".worktrees" / "Projects--dotfiles" / "feature-123"
            )

    def test_template_no_placeholders_uses_flat(self, monkeypatch, tmp_path):
        """Test no placeholders uses flat repo--branch format."""
        config_file = tmp_path / ".hive.yml"
        config_file.write_text('worktrees:\n  parent_dir: ".worktrees"\n')

        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))

        with patch(
            "hive_cli.config.loader.find_config_files", return_value=[config_file]
        ):
            reload_config()
            repo_name = _path_to_name(tmp_path)
            path = get_worktree_path("feature-123", tmp_path)
            assert path == tmp_path / ".worktrees" / f"{repo_name}--feature-123"

    def test_flat_template_with_both_placeholders(self, monkeypatch, tmp_path):
        """Test flat template {repo}--{branch} produces flat directory."""
        config_file = tmp_path / ".hive.yml"
        config_file.write_text(
            'worktrees:\n  parent_dir: "~/.worktrees/{repo}--{branch}"\n'
        )

        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))

        repo = Path.home() / "Projects" / "dotfiles"
        with patch(
            "hive_cli.config.loader.find_config_files", return_value=[config_file]
        ):
            reload_config()
            path = get_worktree_path("feature-123", repo)
            assert path == (
                Path.home() / ".worktrees" / "Projects--dotfiles--feature-123"
            )

    def test_branch_with_slash_sanitized(self, monkeypatch, tmp_path):
        """Test branch with slashes is sanitized in template."""
        config_file = tmp_path / ".hive.yml"
        config_file.write_text(
            'worktrees:\n  parent_dir: "~/.worktrees/{repo}/{branch}"\n'
        )

        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))

        repo = Path.home() / "Projects" / "dotfiles"
        with patch(
            "hive_cli.config.loader.find_config_files", return_value=[config_file]
        ):
            reload_config()
            path = get_worktree_path("user/feat/update", repo)
            assert path == (
                Path.home() / ".worktrees" / "Projects--dotfiles" / "user--feat--update"
            )


class TestWorktreeExists:
    """Tests for worktree_exists function."""

    def test_main_always_exists(self, tmp_path):
        """Test 'main' always returns True."""
        assert worktree_exists("main", tmp_path) is True

    def test_one_always_exists(self, tmp_path):
        """Test '1' always returns True."""
        assert worktree_exists("1", tmp_path) is True

    def test_nonexistent_branch(self, monkeypatch, tmp_path):
        """Test non-existent worktree returns False."""
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        reload_config()

        assert worktree_exists("nonexistent", tmp_path) is False

    def test_existing_worktree_from_git(self, monkeypatch, tmp_path):
        """Test existing worktree found via git worktree list."""
        wt_path = tmp_path / "old-path" / "feature-123"
        mock_worktrees = [
            WorktreeInfo(branch="main", path=tmp_path, is_main=True),
            WorktreeInfo(branch="feature-123", path=wt_path, is_main=False),
        ]
        with patch("hive_cli.git.worktree.list_worktrees", return_value=mock_worktrees):
            assert worktree_exists("feature-123", tmp_path) is True


class TestGetWorktreePathExisting:
    """Tests for get_worktree_path with existing worktrees from git."""

    def test_returns_git_path_for_existing_worktree(self, monkeypatch, tmp_path):
        """Test that existing worktrees use their actual git path, not computed."""
        actual_path = tmp_path / "some-other-location" / "feature-123"
        mock_worktrees = [
            WorktreeInfo(branch="main", path=tmp_path, is_main=True),
            WorktreeInfo(branch="feature-123", path=actual_path, is_main=False),
        ]
        with patch("hive_cli.git.worktree.list_worktrees", return_value=mock_worktrees):
            path = get_worktree_path("feature-123", tmp_path)
            assert path == actual_path

    def test_falls_back_to_computed_for_new_branch(self, monkeypatch, tmp_path):
        """Test that new branches use the computed template path."""
        config_file = tmp_path / ".hive.yml"
        config_file.write_text(
            'worktrees:\n  parent_dir: "~/.worktrees/{repo}/{branch}"\n'
        )

        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))

        repo = Path.home() / "Projects" / "dotfiles"
        mock_worktrees = [
            WorktreeInfo(branch="main", path=repo, is_main=True),
        ]
        with patch(
            "hive_cli.config.loader.find_config_files", return_value=[config_file]
        ):
            reload_config()
            with patch(
                "hive_cli.git.worktree.list_worktrees", return_value=mock_worktrees
            ):
                path = get_worktree_path("new-branch", repo)
                assert path == (
                    Path.home() / ".worktrees" / "Projects--dotfiles" / "new-branch"
                )


class TestListWorktrees:
    """Tests for list_worktrees function."""

    def test_main_repo_always_included(self, temp_git_repo):
        """Test main repo is always in the list."""
        worktrees = list_worktrees(temp_git_repo)
        assert len(worktrees) >= 1
        assert worktrees[0].branch == "main"
        assert worktrees[0].is_main is True
        assert worktrees[0].path == temp_git_repo


class TestWorktreeInfo:
    """Tests for WorktreeInfo dataclass."""

    def test_creation(self, tmp_path):
        """Test creating a WorktreeInfo instance."""
        info = WorktreeInfo(branch="feature", path=tmp_path, is_main=False)
        assert info.branch == "feature"
        assert info.path == tmp_path
        assert info.is_main is False

    def test_default_is_main(self, tmp_path):
        """Test default is_main is False."""
        info = WorktreeInfo(branch="feature", path=tmp_path)
        assert info.is_main is False


class TestExpandPath:
    """Tests for expand_path function."""

    def test_absolute_path_unchanged(self, tmp_path):
        """Absolute paths are returned as-is."""
        result = expand_path("/absolute/path", tmp_path)
        assert result == Path("/absolute/path")

    def test_tilde_expansion(self, tmp_path):
        """Tilde is expanded to home directory."""
        result = expand_path("~/some/dir", tmp_path)
        assert result == Path.home() / "some" / "dir"

    def test_relative_path_resolves_against_main_repo(self, tmp_path):
        """Relative paths resolve against the provided main_repo."""
        main_repo = tmp_path / "main-repo"
        main_repo.mkdir()
        result = expand_path("../sibling", main_repo)
        assert result == (main_repo / "../sibling").resolve()
        assert result == tmp_path / "sibling"

    def test_env_var_expansion(self, tmp_path, monkeypatch):
        """Environment variables in paths are expanded."""
        monkeypatch.setenv("MY_DIR", "expanded-dir")
        result = expand_path("$MY_DIR/sub", tmp_path)
        assert result == (tmp_path / "expanded-dir" / "sub").resolve()

    def test_dot_relative_resolves_against_main_repo(self, tmp_path):
        """Dot-relative paths resolve against main_repo."""
        result = expand_path("./subdir", tmp_path)
        assert result == (tmp_path / "subdir").resolve()
