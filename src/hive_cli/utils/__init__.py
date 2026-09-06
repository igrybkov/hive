"""Utility modules for hive CLI.

NOTE (A0 step 4): this barrel is a deliberate, temporary re-export shim.
`terminal.py`/`tty.py` moved to `ui/console.py`/`ui/tty.py` (and
`selection.py`'s dead fzf/numbered-select code was deleted, keeping only
`is_interactive`, folded into `ui/tty.py`); `zellij.py`/`layouts.py` moved
to `mux/zellij/backend.py`+`state/`/`layout/resolve.py` (step 9);
`agents.py`/`workdir.py`/`editors.py`/`profiles.py` moved to `ui/pickers/`
(+ `agents/profiles.py` for the non-UI half) in the same step. Deleting
this barrel outright would force every remaining command module that still
imports through it to be touched now -- several of them (`status.py`,
`wt.py`, `handoff.py`, `exec_runner.py`, `merge.py`, `diff.py`,
`completion.py`) carry pre-existing complexipy violations that get fixed
for real when those modules are actually moved/slimmed in steps 5-9, so
touching them here would mean throwaway pure-extraction refactors. This
barrel is deleted in step 8, alongside that real rewrite.
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
from .deps import (
    detect_package_manager,
    ensure_mise_trusted,
    install_dependencies,
    run_post_create_commands,
    setup_worktree_files,
)

__all__ = [
    "confirm",
    "detect_package_manager",
    "dim",
    "ensure_mise_trusted",
    "error",
    "format_dim",
    "format_green",
    "format_yellow",
    "info",
    "install_dependencies",
    "run_post_create_commands",
    "setup_worktree_files",
    "is_interactive",
    "print_stderr",
    "prompt",
    "read_line_from_tty",
    "read_single_key",
    "success",
    "warn",
]
