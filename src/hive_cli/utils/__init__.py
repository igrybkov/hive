"""Utility modules for hive CLI."""

from .agents import select_agent
from .deps import (
    detect_package_manager,
    ensure_mise_trusted,
    install_dependencies,
    run_post_create_commands,
    setup_worktree_files,
)
from .editors import (
    EditorConfig,
    get_available_editors,
    open_in_editor,
    select_editor,
)
from .fuzzy import FuzzyItem, fuzzy_select
from .layouts import resolve_layout
from .selection import fzf_select, has_fzf, interactive_select, is_interactive
from .terminal import (
    dim,
    error,
    format_dim,
    format_green,
    format_yellow,
    info,
    print_stderr,
    prompt,
    success,
    warn,
)
from .tty import confirm, read_line_from_tty, read_single_key
from .workdir import WORKDIR_CLEAR, select_workdir
from .zellij import (
    is_running_in_zellij,
    rebuild_pane_title,
    rename_pane,
    set_pane_branch,
    set_pane_custom_title,
    set_pane_status,
)

__all__ = [
    "EditorConfig",
    "FuzzyItem",
    "confirm",
    "detect_package_manager",
    "dim",
    "ensure_mise_trusted",
    "error",
    "get_available_editors",
    "format_dim",
    "format_green",
    "format_yellow",
    "fuzzy_select",
    "fzf_select",
    "has_fzf",
    "info",
    "install_dependencies",
    "run_post_create_commands",
    "setup_worktree_files",
    "interactive_select",
    "is_interactive",
    "print_stderr",
    "prompt",
    "read_line_from_tty",
    "read_single_key",
    "is_running_in_zellij",
    "open_in_editor",
    "rebuild_pane_title",
    "resolve_layout",
    "rename_pane",
    "set_pane_branch",
    "set_pane_custom_title",
    "set_pane_status",
    "select_agent",
    "select_editor",
    "select_workdir",
    "WORKDIR_CLEAR",
    "success",
    "warn",
]
