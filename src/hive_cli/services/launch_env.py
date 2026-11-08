"""The env an agent launches with, refreshed from sources that may have changed.

A multiplexer pane inherits the env the session started with, so an expired
token or an edited shell config stays stale until the session restarts.
`refresh()` runs before every launch (each --restart iteration, each new
pane) and layers, lowest first:

1. the inherited env,
2. what a fresh login shell exports (`env.refresh_from_shell`, opt-in),
3. the launch directory's project env: `direnv export json` when direnv is
   installed and an .envrc exists, else `.env` (`env.project`).

Callers overlay hive's runtime vars and the profile env on top. Sources only
add or replace keys (direnv may also unset its own); a failing source is
traced and skipped, never fatal -- the agent still starts with what it had.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Mapping
from pathlib import Path

from ..config.schema import EnvConfig
from ..core import proc, trace

MINIMAL_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"

# What a fresh login shell gets from us. Anything else inherited could shadow
# the shell config (fish globals hide universals; `export X=${X:-...}` keeps X).
_SHELL_SEED_KEYS = (
    "HOME",
    "USER",
    "LOGNAME",
    "SHELL",
    "TERM",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "TMPDIR",
    "XDG_CONFIG_HOME",
    "XDG_DATA_HOME",
    "XDG_STATE_HOME",
    "XDG_CACHE_HOME",
)

# Keys owned by the session or the pane, never taken from the fresh shell.
# PATH stays too: the session's PATH may hold entries (a venv, a tool dir)
# the login shell doesn't set, and a stale PATH is rarely the problem.
_PROTECTED_KEYS = frozenset(
    {"PATH", "TERM", "COLORTERM", "TERM_PROGRAM", "TERM_PROGRAM_VERSION"}
    | {"PWD", "OLDPWD", "SHLVL", "_"}
)
# "__" keys are shell/tool bookkeeping (mise's __MISE_DIFF describes the
# fresh shell's PATH, which is not applied).
_PROTECTED_PREFIXES = ("ZELLIJ", "TMUX", "HIVE_", "DIRENV_", "__")


def refresh(
    base: Mapping[str, str], *, cwd: str | Path, config: EnvConfig
) -> dict[str, str]:
    """Return `base` with the configured fresh sources applied on top."""
    env = dict(base)
    if config.refresh_from_shell:
        fresh = _shell_env(base, config)
        env.update({k: v for k, v in fresh.items() if not _protected(k)})
    source = _project_source(config.project)
    if source == "direnv":
        for key, value in _direnv_env(env, Path(cwd), config.timeout).items():
            if value is None:
                env.pop(key, None)
            else:
                env[key] = value
    elif source == "dotenv":
        env.update(_dotenv_env(Path(cwd)))
    return env


def parse_env0(text: str) -> dict[str, str]:
    """Parse `env -0` output. Chunks without '=' (shell noise) are dropped."""
    env: dict[str, str] = {}
    for chunk in text.split("\0"):
        key, sep, value = chunk.partition("=")
        if sep and key and "\n" not in key:
            env[key] = value
    return env


def _protected(key: str) -> bool:
    return key in _PROTECTED_KEYS or key.startswith(_PROTECTED_PREFIXES)


def _shell_env(base: Mapping[str, str], config: EnvConfig) -> dict[str, str]:
    argv = list(config.shell_command)
    if not argv:
        shell = base.get("SHELL")
        if not shell:
            trace.event("env", "shell", error="SHELL not set")
            return {}
        argv = [shell, "-l", "-c", "env -0"]
    seed = {k: base[k] for k in _SHELL_SEED_KEYS if k in base}
    seed["PATH"] = MINIMAL_PATH
    result = proc.run(argv, env=seed, input="", timeout=config.timeout)
    if not result.ok:
        trace.event("env", "shell", error=result.stderr.strip()[:200])
        return {}
    return parse_env0(result.stdout)


def _project_source(mode: str) -> str | None:
    if mode == "off":
        return None
    if mode == "auto":
        return "direnv" if shutil.which("direnv") else "dotenv"
    return mode


def _find_envrc(cwd: Path) -> Path | None:
    for directory in (cwd, *cwd.parents):
        candidate = directory / ".envrc"
        if candidate.is_file():
            return candidate
    return None


def _direnv_env(
    env: Mapping[str, str], cwd: Path, timeout: float
) -> dict[str, str | None]:
    if _find_envrc(cwd) is None:
        return {}
    # Without the inherited DIRENV_* state direnv evaluates the .envrc anew
    # instead of reporting "already loaded" (which would keep stale values).
    clean = {k: v for k, v in env.items() if not k.startswith("DIRENV_")}
    result = proc.run(
        ["direnv", "export", "json"], cwd=cwd, env=clean, input="", timeout=timeout
    )
    if not result.ok:
        trace.event("env", "direnv", error=result.stderr.strip()[:200])
        return {}
    if not result.stdout.strip():
        return {}
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        trace.event("env", "direnv", error="unparsable output")
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        str(k): v if v is None else str(v)
        for k, v in data.items()
        if v is None or isinstance(v, str)
    }


def _dotenv_env(cwd: Path) -> dict[str, str]:
    path = cwd / ".env"
    if not path.is_file():
        return {}
    from dotenv import dotenv_values  # lazy: only launches with a .env pay for it

    return {k: v for k, v in dotenv_values(path).items() if v is not None}
