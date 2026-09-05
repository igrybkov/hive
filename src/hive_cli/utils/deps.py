"""Re-export shim: dependency installation utilities moved to services/worktrees.py.

NOTE (A0 step 6): kept here so commands/wt.py (deferred -- it carries
pre-existing complexipy violations fixed only when it's actually slimmed
in a later pass) doesn't need touching this step. Imports the module (not
individual functions) per tests/test_architecture.py's
test_cross_layer_imports_are_modules_not_functions.
"""

from __future__ import annotations

from ..services import worktrees

detect_package_manager = worktrees.detect_package_manager
ensure_mise_trusted = worktrees.ensure_mise_trusted
install_dependencies = worktrees.install_dependencies
run_post_create_commands = worktrees.run_post_create_commands
setup_worktree_files = worktrees.setup_worktree_files

__all__ = [
    "detect_package_manager",
    "ensure_mise_trusted",
    "install_dependencies",
    "run_post_create_commands",
    "setup_worktree_files",
]
