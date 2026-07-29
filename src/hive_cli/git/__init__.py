"""Git utilities for hive CLI."""

from .repo import get_current_worktree_branch, get_git_root, get_main_repo
from .worktree import (
    WorktreeInfo,
    create_worktree,
    delete_worktree,
    expand_path,
    fetch_origin,
    get_all_branches,
    get_current_branch,
    get_default_branch,
    get_worktree_path,
    get_worktrees_base,
    is_worktree_dirty,
    list_worktrees,
    sanitize_branch_name,
    worktree_exists,
)

__all__ = [
    "WorktreeInfo",
    "create_worktree",
    "delete_worktree",
    "expand_path",
    "fetch_origin",
    "get_all_branches",
    "get_current_branch",
    "get_current_worktree_branch",
    "get_default_branch",
    "get_git_root",
    "get_main_repo",
    "get_worktree_path",
    "get_worktrees_base",
    "is_worktree_dirty",
    "list_worktrees",
    "sanitize_branch_name",
    "worktree_exists",
]
