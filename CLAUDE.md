# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`hive` is a CLI for running AI coding agents (Claude, Gemini, Codex, Copilot, Cursor
Agent, …) in isolated git worktrees, with a Zellij-based multi-agent layout, agent
auto-detection, config-profile isolation (separate credentials/history per agent
per profile), and small git-analysis helpers (`diff`, `rebase-check`,
`merge-preview`). It was extracted from `igrybkov/dotfiles`
(`profiles/agents/packages/hive_cli/`) to be installable standalone.

See `README.md` for the full command and configuration reference — this file is
about internals, not usage.

## Commands

```bash
uv sync --dev                       # install deps (incl. dev group)
uv run pytest                       # run tests
uv run pytest tests/test_zellij.py -v   # single file
uv run ruff check .                 # lint
uv run ruff format .                # format (check-only: --check)
uv run pre-commit install           # optional git hooks (ruff lint+format)

uv run hive --help
uv run hive run                     # launch an agent in the current dir
uv run hive zellij                  # open the bundled multi-agent Zellij layout
```

CI (`.github/workflows/test.yml`) runs `ruff check`, `ruff format --check`, and
`pytest` on every push/PR to `main`. Releases are automated via
python-semantic-release driven by Conventional Commits — `fix:` → patch,
`feat:` → minor, `feat!:`/`BREAKING CHANGE:` → major; `chore:`/`docs:`/
`refactor:`/`test:` → no release. The version lives in
`src/hive_cli/__init__.py:__version__` and is bumped by the release bot, never by
hand. This package is **never** published to PyPI (the `Private :: Do Not Upload`
classifier in `pyproject.toml` is a deliberate guard); distribution is Git +
GitHub Releases only, installed with:

```bash
uv tool install --from git+https://github.com/igrybkov/hive.git hive-cli
```

## Architecture

Entry point: `hive_cli.app:app`, a `cyclopts.App` (`app.py`) that registers each
command module's sub-app. Commands are cyclopts apps under `commands/`; the CLI
itself does not use argparse/click.

### Config (`config/`)

Layered YAML settings, highest precedence first: `HIVE_*` env vars →
`.hive.local.yml` → `.hive.yml` → `$XDG_CONFIG_HOME/hive/hive.yml` →
package-bundled `config/default.yml`. `settings.py` (`get_settings` /
`reset_settings`) is the cache; `loader.py` finds and reads the YAML sources;
`merge.py` deep-merges them; `schema.py` defines the pydantic-settings models
(`HiveSettings`, `ZellijConfig`, `AgentsConfig`, `WorktreesConfig`, …).
`config/__init__.py` re-exports the public surface and keeps a couple of
backward-compatible wrappers (`load_config`, `reload_config`) around the newer
`get_settings`/`reset_settings` API — don't remove those without checking callers.

`RuntimeSettings` (`runtime.py`, via `get_runtime_settings()`) is separate from
`HiveSettings`: it holds per-invocation state threaded through env vars to child
processes (detected agent, active profile, Zellij pane id, workdir override from
Ctrl+W) rather than user config.

### Agent detection & config profiles

`agents/detection.py` picks the first available agent from `agents.order` (or an
explicit `-a`/`HIVE_AGENT` override). Each agent's CLI shape (resume flags,
skip-permissions flags, extra-dirs flag, config-dir env var for profile isolation)
is declared in `config/default.yml` under `agents.configs.<name>` and can be
overridden or extended per-project. `config/__init__.py:resolve_profile_env`
builds the env-var overlay for `hive run -p <profile>`: it creates the profile
directory and writes any declared `seed_files` on first use (idempotent) — this
matters because an unseeded profile dir silently defeats credential isolation for
agents that need a seeded config (e.g. Codex's `cli_auth_credentials_store =
"file"`).

### Worktree execution (`git/`, `commands/exec_runner.py`)

`git/worktree.py` and `git/repo.py` wrap `git worktree` (create/list/path
resolution, main-repo detection so commands always operate from the right root).
`exec_runner.py` is the shared "run a command in a worktree, optionally loop with
--restart" core used by `hive run`, `hive wt exec`, and `hive zellij --restart`;
`commands/wt.py` layers the interactive fuzzy picker (`utils/fuzzy.py`) on top for
`-w=-` selection.

### Zellij integration (`commands/zellij.py`, `utils/zellij.py`, `layouts/`)

The bundled multi-agent layout ships at `src/hive_cli/layouts/agent.kdl` (16 named
panes running `hive run --restart`, plus a `hive status --watch` board) and is
included in the wheel via `[tool.hatch.build] include`. `hive zellij` resolves the
configured `zellij.layout` value to something `zellij --layout` accepts — a bundled
name, a user-defined name in `~/.config/zellij/layouts/`, or an explicit path — and
launches `zellij attach --create`. `utils/zellij.py` manages pane-title state
(status/branch/custom-title segments) via `zellij action rename-pane`, always
targeting `$ZELLIJ_PANE_ID` explicitly since Zellij's rename-pane defaults to the
*focused* pane, not the calling one.

### Things to keep in mind when editing

- `tests/conftest.py` provides `CycloptsTestRunner`; `tests/*.py` import it as a
  bare `from conftest import CycloptsTestRunner` (no package `__init__.py` in
  `tests/`) — this relies on pytest's rootdir-prepend behavior. Do not add
  `tests/__init__.py`; it would break that import.
- Config settings are cached (`get_settings()`); tests that mutate env vars or
  config files mid-test must call `reload_config()` / `reset_settings()` to see
  the change.
- `os.execvpe` is used to hand off to the agent/zellij process (not
  `subprocess.run`) except in `--restart` mode, which needs the loop to observe
  exit and relaunch.
