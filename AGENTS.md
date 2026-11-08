# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## What this is

`hive` is a CLI for running AI coding agents (Codex, Gemini, Codex, Copilot, Cursor
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
uv run pytest tests/test_cli_zellij.py -v   # single file
uv run ruff check .                 # lint
uv run ruff format .                # format (check-only: --check)
uv run pre-commit install           # optional git hooks (ruff lint+format)

uv run hive --help
uv run hive run                     # launch an agent in the current dir
uv run hive zellij                  # open the bundled multi-agent Zellij layout
uv run hive doctor --timing         # phase | ms | spawns for this repo (HIVE_TRACE=1 for a full trace)
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
command module's sub-app *lazily* (a `"module:attribute"` string target per
command in `LAZY_COMMANDS`), so `import hive_cli.app` never pulls in
`wt.py`/`zellij.py`/etc — only the command that actually runs gets imported.
Commands are cyclopts apps under `commands/`; the CLI itself does not use
argparse/click.

The codebase is layered core → config/state/hooks → git/agents/layout/mux →
services → ui → commands, each layer importing only from itself or strictly
lower layers (`mux` may additionally import `layout`'s model). The full
package map, call-flow diagrams, and process/state-ownership model live in
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md); the short version:

| # | Layer | Packages | May import |
|---|---|---|---|
| 0 | core | `core/` | stdlib only |
| 1 | config / state / hooks | `config/`, `state/`, `hooks/` | core |
| 2 | domain | `git/`, `agents/`, `layout/`, `mux/` | 0–1 (`mux → layout` model only) |
| 3 | services | `services/` | 0–2; never ui/commands/rich/prompt_toolkit/textual, never print/input/sys.exit |
| 4 | ui | `ui/` | 0–3; never commands |
| 5 | cli | `commands/`, `app.py` | 0–4; never other `commands/*` modules |

`tests/test_architecture.py` enforces this by AST inspection — a violation
fails the build instead of surfacing in review. Its allow-lists (which files
may `import subprocess` directly, which packages may use rich/prompt_toolkit,
etc.) **are** the architecture; change them only together with
`docs/ARCHITECTURE.md`.

### Architecture rules

1. **Layers only point down.** core ← config/state/hooks ← git/agents/layout/
   mux ← services ← ui ← commands. `mux` may import `layout` (model); nothing
   else crosses sideways. `tests/test_architecture.py` fails the build
   otherwise.
2. **Logic lives in `services/`; commands and UIs are adapters.** A command
   function parses, calls one service or flow, prints, and returns. If a
   command or a widget needs a subprocess, a git fact, or a file, it asks a
   service for it.
3. **Services are synchronous, silent, and UI-free.** No `rich`, no
   `prompt_toolkit`, no `textual`, no `print`, no stdin, no `sys.exit`. Return
   dataclasses; raise `HiveError`. Take decisions as arguments or callables.
4. **UIs call services only through `services.aio.call` and receive pushes
   only through `services.watch.watch_session`.** No subprocess, no socket
   handling, no polling inside `ui/`.
5. **One process owns each piece of state**; others read it over the pane or
   control socket. New operations are added to `services/registry.OPS` so
   sockets, CLI and UIs expose the same thing.
6. **Every external command goes through `core.proc.run`**; agent launches
   and `execvpe` hand-offs are the only exceptions.
7. **Import modules across layers, not functions** (`from hive_cli.core import
   proc`; `proc.run(...)`) so tests can patch at the module boundary.
8. **Add features into existing homes** (see the package map in
   `docs/ARCHITECTURE.md`); a new top-level package needs a line in that map
   and in the layer table first.

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

### Worktree execution (`git/`, `services/pane.py`, `ui/flows/worktrees.py`)

`git/worktree.py` and `git/repo.py` wrap `git worktree` (create/list/path
resolution, main-repo detection so commands always operate from the right root).
`services/pane.py:run_with_resume` and `ui/flows/worktrees.py:run_in_worktree`
hold the "run a command in a worktree, optionally loop with --restart" core
used by `hive run`, `hive wt exec`, and `hive zellij --restart`;
`ui/pickers/worktrees.py` layers the interactive fuzzy picker
(`ui/pickers/fuzzy.py`) on top for `-w=-` selection.

### Zellij integration (`commands/zellij.py`, `services/session.py`, `mux/zellij/`, `layout/`)

The bundled multi-agent layout ships at `src/hive_cli/layout/bundled/agent.kdl`
(16 named panes running `hive run --restart`, plus a `hive status --watch`
board) and is included in the wheel via `[tool.hatch.build] include`.
`layout/resolve.py:resolve_layout` resolves the configured `zellij.layout`
value to something `zellij --layout` accepts — a bundled name, a user-defined
name in `~/.config/zellij/layouts/`, or an explicit path; `services/session.py`
builds the session name and attach argv and launches `zellij attach --create`.
`mux/zellij/backend.py` manages pane-title state (status/branch/custom-title
segments) via `zellij action rename-pane`, always targeting `$ZELLIJ_PANE_ID`
explicitly since Zellij's rename-pane defaults to the *focused* pane, not the
calling one.

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

### Performance and concurrency rules

1. **Never block a thread that owns input.** Code that runs a prompt_toolkit
   `Application`, a Textual `App`, or reads keys must not call `subprocess`,
   git, `gh`, the network, `time.sleep`, or a blocking socket. Do that work
   through `services.aio.call` and hand results back through
   `update_items()`/`app.invalidate()` (prompt_toolkit) or
   `post_message`/`call_from_thread` (Textual).
2. **Paint first, refine later.** Interactive commands show a usable screen
   within 100 ms of `main()` (250 ms including interpreter start) using data
   that is already known or one cheap call; everything else arrives as an
   update. No spinner or "loading" screen that waits on git.
3. **One spawn beats N.** Every external command goes through `core.proc.run`
   (traced by `HIVE_TRACE=1`, explicit `timeout`, `capture_output`, no shell).
   Prefer commands that return many facts at once (`git status --porcelain=v2
   --branch`, `list-panes --json`) over one command per fact, and one refresher
   per session (the control plane) over one per pane. Tests on hot paths use
   `fake_proc` and assert the spawn count.
4. **Push, don't poll.** State flows over the pane sockets, agent hooks, and
   multiplexer events. Where polling is unavoidable (Zellij `list-panes`), use
   ≥ 2 s intervals, a single poller per session, and skip work when nothing
   changed. Never `select()`/`sleep()` in 100 ms slices on a UI thread. Never
   use files as an IPC channel.
5. **asyncio inside apps, threads only to wrap blocking calls.** Textual code
   uses asyncio tasks (`asyncio.open_unix_connection`, `@work`); blocking
   calls go through `aio.call` / `@work(thread=True)`; `hive run` uses a
   daemon thread for its socket server. Shared mutable state needs a lock or a
   single owner; the pane's `hive run` is the single writer of that pane's
   state.
6. **Render only what changed.** Full-screen UIs run on the alternate screen
   through a diffing renderer — Textual (compositor, dirty regions,
   synchronized output), prompt_toolkit (screen diff), or Rich `Live` via
   `ui/board.LiveBoard` (one in-place write per change). Never
   `console.clear()` inside a loop, never `Live(auto_refresh=True)`, no live
   clocks or animations in an idle pane (each differing frame makes the
   multiplexer re-render the pane and its bars; show ages as buckets). State
   flows one way: a source updates the store, the view diffs the store; views
   never pull and never repaint on a timer. Multiplexer calls (`rename-pane`,
   `rename-tab`) are coalesced within 200 ms.
7. **Start fast.** `import hive_cli.app` stays under ~120 ms (`python -X
   importtime` is the test). Heavy modules (prompt_toolkit, textual,
   rich.markdown) are imported inside the functions that need them; command
   modules are registered lazily; `hive-hook`, `hive_cli.core` and
   `hive_cli.state` import only the stdlib; nothing spawns git at import or
   config-load time.
8. **Measure before optimizing.** Reproduce with `HIVE_TRACE=1` (phase
   timings and spawn counts) or `hive doctor --timing`, fix the largest number,
   re-measure, and add a test that pins the improvement.
