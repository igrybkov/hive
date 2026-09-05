"""Utility modules for hive CLI.

NOTE (A0 step 4): this barrel is a deliberate, temporary re-export shim.
`terminal.py`/`tty.py` moved to `ui/console.py`/`ui/tty.py` (and
`selection.py`'s dead fzf/numbered-select code was deleted, keeping only
`is_interactive`, folded into `ui/tty.py`). Deleting this barrel outright
would force every remaining command module that still imports through it
to be touched now -- several of them (`status.py`, `wt.py`, `zellij.py`,
`handoff.py`, `exec_runner.py`, `merge.py`, `diff.py`, `completion.py`)
carry pre-existing complexipy violations that get fixed for real when
those modules are actually moved/slimmed in steps 5-9, so touching them
here would mean throwaway pure-extraction refactors. This barrel is
deleted in step 8, alongside that real rewrite.
"""

# Re-exported from their new ui/ home (moved in step 4).
from ..ui.console import (
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
from ..ui.tty import (
    confirm,
    is_interactive,
    read_line_from_tty,
    read_single_key,
)
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
    "info",
    "install_dependencies",
    "run_post_create_commands",
    "setup_worktree_files",
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
