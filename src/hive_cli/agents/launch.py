"""Argv/env assembly for launching an agent.

NOTE (A0 step 3, config purity): get_extra_dirs_args moved here verbatim from
config/__init__.py, including its lazy ``from ..git import ...``. That import
is a deliberate, temporary architecture-guard violation (agents -> git is not
in SIDEWAYS_OK) — tests/test_architecture.py stays red until Step 10 anyway.
It gets resolved when this module gains build_command()/Launch() and this
function's signature changes to take ``main_repo: Path`` from its caller
instead of calling hive_cli.git.get_main_repo() itself (see the A0 spec's
move-map row for commands/exec_runner.py and commands/run.py).
"""

from __future__ import annotations

from .. import config


def get_extra_dirs_args(agent_name: str) -> list[str]:
    """Build CLI arguments for extra directories.

    Reads extra_dirs from settings, resolves each path relative to the main
    repo root (so relative paths work identically from worktrees), then
    pairs each resolved path with the agent's extra_dirs_flag.

    Args:
        agent_name: Name of the agent (to look up extra_dirs_flag).

    Returns:
        List like [flag, path1, flag, path2, ...], or [] if no dirs or
        the agent has no extra_dirs_flag configured.
    """
    from ..git import expand_path, get_main_repo

    settings = config.get_settings()
    # Session override (set by Ctrl+W in the picker) wins over configured dirs.
    # It contains already-resolved absolute paths plus the displaced primary.
    override = config.get_runtime_settings().workdir_extras_override
    dirs = override if override is not None else settings.extra_dirs
    if not dirs:
        return []

    agent_cfg = settings.agents.configs.get(agent_name, config.AgentConfig())
    flag = agent_cfg.extra_dirs_flag
    if not flag:
        return []

    main_repo = get_main_repo()
    result: list[str] = []
    for d in dirs:
        resolved = expand_path(d, main_repo)
        result.extend([flag, str(resolved)])
    return result
