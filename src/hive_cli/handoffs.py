"""Re-export shim: handoff file management moved to services/handoffs.py.

NOTE (A0 step 6): kept here so git/worktree.py's create_worktree (the
handoff-symlink call there moves to services/worktrees.provision() in a
later pass per the move-map) doesn't need touching this step. Imports the
module (not individual functions) per tests/test_architecture.py's
test_cross_layer_imports_are_modules_not_functions.
"""

from __future__ import annotations

from .services import handoffs

clean_orphaned_handoffs = handoffs.clean_orphaned_handoffs
delete_handoff = handoffs.delete_handoff
ensure_handoffs_dir = handoffs.ensure_handoffs_dir
get_handoff_file = handoffs.get_handoff_file
get_handoffs_dir = handoffs.get_handoffs_dir
has_handoff_content = handoffs.has_handoff_content
list_handoffs = handoffs.list_handoffs
setup_handoff_symlink = handoffs.setup_handoff_symlink

__all__ = [
    "clean_orphaned_handoffs",
    "delete_handoff",
    "ensure_handoffs_dir",
    "get_handoff_file",
    "get_handoffs_dir",
    "has_handoff_content",
    "list_handoffs",
    "setup_handoff_symlink",
]
