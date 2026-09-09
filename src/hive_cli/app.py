"""Main CLI application definition.

Commands are registered lazily (string targets): cyclopts only imports a
command module when that command actually runs, so `hive run` never pulls
in `wt.py`/`zellij.py`/etc. This is what keeps `import hive_cli.app` light
(see tests/test_architecture.py:test_app_import_is_light) and is also why
commands/__init__.py stays a bare docstring -- an eager `from . import ...`
there would defeat the purpose just as much as one here.
"""

from __future__ import annotations

from cyclopts import App

from . import __version__
from .core import trace

app = App(
    name="hive",
    help=(
        "Hive - Multi-agent worktree management CLI.\n\n"
        "Manage AI coding agents and git worktrees for parallel development."
    ),
    version=__version__,
    version_flags=["--version", "-V"],
)

# (name, "module:attribute", help). Lazy: the module is imported only when
# the command actually runs.
LAZY_COMMANDS: list[tuple[str, str, str]] = [
    (
        "run",
        "hive_cli.commands.run:run_app",
        "Run AI coding agent in current directory.",
    ),
    (
        "zellij",
        "hive_cli.commands.zellij:zellij_app",
        "Open Zellij with AI agent layout.",
    ),
    (
        "session",
        "hive_cli.commands.session:session_app",
        "Open the configured multiplexer (Zellij or tmux) with the AI agent layout.",
    ),
    (
        "wt",
        "hive_cli.commands.wt:wt_app",
        "Manage git worktrees for multi-agent development.",
    ),
    (
        "pane",
        "hive_cli.commands.pane:pane_app",
        "Create and manage agent panes.",
    ),
    (
        "tab",
        "hive_cli.commands.tab:tab_app",
        "Open tool tabs and agent tabs on demand.",
    ),
    (
        "completion",
        "hive_cli.commands.completion:completion_app",
        "Generate shell completion script.",
    ),
    (
        "config",
        "hive_cli.commands.config_cmd:config_app",
        "Manage hive configuration.",
    ),
    (
        "status",
        "hive_cli.commands.status:status_app",
        "Display status of all agent worktrees.",
    ),
    ("task", "hive_cli.commands.task:task_app", "Manage agent tasks."),
    (
        "handoff",
        "hive_cli.commands.handoff:handoff_app",
        "Manage branch handoff notes.",
    ),
    (
        "diff",
        "hive_cli.commands.diff:diff_app",
        "Show unified diff of all agent worktrees against main branch.",
    ),
    (
        "rebase-check",
        "hive_cli.commands.rebase:rebase_check_app",
        "Check if agent worktrees need rebasing against default branch.",
    ),
    (
        "merge-preview",
        "hive_cli.commands.merge:merge_preview_app",
        "Preview potential merge conflicts between agent branches.",
    ),
    (
        "doctor",
        "hive_cli.commands.doctor:doctor_app",
        "Check hive's environment and measure startup and hot-path timings.",
    ),
]
for _name, _target, _help in LAZY_COMMANDS:
    app.command(_target, name=_name, help=_help)

trace.mark("app_imported")
