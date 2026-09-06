# Architecture

This is the architecture reference `CLAUDE.md` points to. It is copied from
the project's master plan (`.claude/plans/issue-1-tab-management.md`) and
describes the **target** layering and package map for the full `hive`
redesign (issue #1), not only what A0 built. Package-map entries tagged
`[F1]`/`[F3]`/`[F4]`/`[F5]`/`[F6]` don't exist yet — they land with those
later features. Everything untagged is either already in the tree (built by
A0) or is a pre-A0 module the refactor left in place.

## Layers and the dependency rule

Every module belongs to exactly one layer and may import only from its own
layer (with the exceptions noted) or from lower layers. The rule is enforced
by `tests/test_architecture.py` (AST-based), so a violation fails CI instead
of being a review comment.

| # | Layer | Packages | Responsibility | May import | Never |
|---|---|---|---|---|---|
| 0 | core | `core/` | stdlib-only primitives: paths, `proc.run`, trace, errors, shared dataclasses | stdlib | anything in hive, pydantic, rich |
| 1 | config | `config/` | settings (pydantic) and per-invocation `RuntimeSettings`; pure: no git, no subprocess | core | git, subprocess |
| 1 | state | `state/` | `PaneState`, socket protocol, server, client (stdlib only — shared with `hive-hook`) | core | config, pydantic, rich |
| 1 | hooks | `hooks/` | `hive-hook` entry point; must start in < 30 ms | core, state | everything else |
| 2 | domain | `git/`, `agents/`, `layout/`, `mux/` | facts and effects on one external system each: git/gh, agent binaries & profiles, the neutral layout model, the multiplexer | core, config, state; `mux → layout` (model only) | each other otherwise; ui, commands, rich, prompt_toolkit |
| 3 | services | `services/` | use-cases that compose layer 2: provisioning a worktree, running an agent in a pane, session/tab/pane operations, status facts, tasks, handoffs, the session event stream | 0–2 | ui, commands, rich, prompt_toolkit, textual; `print`, `input`, `sys.exit` |
| 4 | ui | `ui/` | everything that draws or reads keys: console messages, pickers, live boards, the Textual control plane, interactive flows | 0–3 | commands |
| 5 | cli | `commands/`, `app.py` | cyclopts apps: parse → call services / ui → print → exit code | 0–4 | other `commands/*` modules (except `app` and completion) |

Two conventions make the rule cheap to follow: `core/models.py` holds the
dataclasses that more than one layer-2 package needs (`WorktreeInfo`,
`GitSummary`, `PaneInfo`, `TabSpec`, `PaneSpec`), and `core/errors.py`
defines `HiveError(message, exit_code=1)` — the *only* way lower layers signal
failure to the user. `app.dispatch()` turns it into a message and exit code;
no layer below `commands/` calls `sys.exit`.

**Import style rule (makes tests patchable):** across layers, import
*modules*, not functions: `from hive_cli.core import proc` then `proc.run(…)`;
`from hive_cli.services import worktrees` then `worktrees.provision(…)`.
Tests patch `hive_cli.core.proc.run` and `hive_cli.services.worktrees.provision`
and those patches only take effect when call sites look the name up at call
time. Types and dataclasses may be imported by name.

## Package map (target)

```
hive_cli/
  __init__.py            __version__ only (hooks and tests rely on it staying empty)
  app.py                 composition root: lazy command registration, dispatch()/main() → HiveError → exit code
  core/    paths.py      XDG dirs, runtime dir, socket paths, layouts dir
           proc.py       run(argv, *, cwd, timeout, env) → Result; the only subprocess wrapper for captured commands; traced
           trace.py      HIVE_TRACE=1 phase/spawn timings (stderr)
           errors.py     HiveError, ProcError
           models.py     shared dataclasses
  config/  schema.py settings.py loader.py merge.py runtime.py   (loader finds the project root by walking up to .git — no spawn)
  state/   pane_state.py PaneState, compose_title, compose_tab_name
           protocol.py   NDJSON ops (get/set/subscribe/restart/stop/ping/call), encode/decode
           server.py     PaneStateServer (hive run)          client.py  send/get_state/set_fields/list_pane_sockets
  git/     repo.py worktree.py status.py github.py analysis.py   (facts + effects on git/gh; no prompts, no prints)
  agents/  detection.py profiles.py launch.py        launch.build_command(agent, opts) → Launch(argv, env); F5 adds hook args
  layout/  model.py tabs.py keybinds.py resolve.py bundled/*.kdl   neutral tab/pane model, bundled tab definitions, keybind spec
  mux/     base.py       Mux protocol + PaneInfo/TabInfo; get_mux()
           zellij/       backend.py (CLI calls), kdl.py (render TabSpec/SessionSpec), keybinds.py (render keybind block)
           tmux/         backend.py, conf.py, control.py (control-mode parser)                       [F6]
  services/ worktrees.py provision/remove (git + files + post_create + handoff symlink)
            pane.py      run_loop(pick, launch, restart): state server + agent child lifecycle
            session.py   start(), open_tab(), new_agent_pane(), floating_shell(), toggle_control_plane(), resolve_here()
            status.py    collect_status(), AgentStatus, shared-notes summary
            facts.py     git facts refresher (fetch throttle, summaries, gh issues) + control-socket service  [F1/F4]
            watch.py     watch_session() → AsyncIterator[SessionEvent]                               [F4]
            tasks.py handoffs.py editors.py
            registry.py  OPS: name → service callable (the surface exposed over the control socket and to external UIs)
            aio.py       call(fn, *args) = asyncio.to_thread + trace; the one adapter UIs use
  ui/      console.py    shared Console out/err, info/warn/error/success, format_*
           tty.py        raw key reads, confirm, is_interactive
           board.py      LiveBoard (Rich Live, update on change)                                   [F1]
           pickers/      fuzzy.py (engine), worktrees.py, agents.py, profiles.py, editors.py, workdir.py, status.py
           flows/        interactive multi-step flows (create/delete worktree, new branch, issue branch) — call services
           views/        Rich renderables: status tables, handoff preview, detail panels
           tui/          Textual control plane: app.py, screens/, widgets/, model.py (build_rows)  [F4]
  commands/ run.py zellij.py wt.py status.py task.py handoff.py diff.py rebase.py merge.py config_cmd.py completion.py
            pane.py tab.py session.py                                                              [F3, F6]
  hooks/   entry.py templates.py                                                                   [F5]
```

## How parts connect

**Three call surfaces, one implementation.** Every operation hive can perform
exists once, as a function in `services/`. It is reachable three ways:

1. **In-process** — the CLI calls it directly (`hive wt create X` →
   `services.worktrees.provision("X")`); a UI calls it through
   `services.aio.call` (below). Command modules never shell out to `hive` and
   never import each other; they share services.
2. **Over a socket** — `state/protocol.py` defines the ops. Pane sockets carry
   the per-pane ops (`get`, `set`, `subscribe`, `restart`, `stop`, `ping`);
   the control socket (F4) carries `{"op":"call","name":"session.open_tab",
   "args":{…}}` which dispatches through `services/registry.OPS` — so a Rust
   plugin, a script, or another terminal drives hive with the same functions
   and no `hive` process.
3. **The `hive` CLI** — for humans, multiplexer keybinds (`Run hive pane new`,
   short-lived), and scripts.

**The non-blocking contract.** Services are plain synchronous functions:
typed arguments in, dataclasses out, `HiveError` on failure. They may block on
I/O (that is their job) but never on a UI thread, because UIs only reach them
through one adapter:

```python
# services/aio.py
async def call(fn, /, *args, **kwargs):
    """Run a service off the event loop. Trace-timed; HiveError passes through."""
    return await asyncio.to_thread(fn, *args, **kwargs)
```

prompt_toolkit 3 and Textual both run on asyncio, so the same adapter serves
the pickers (`get_app().create_background_task(...)` then `invalidate()`) and
the control plane (`@work` / `await aio.call(...)`, then `post_message`).
Long operations take two optional keyword arguments, `progress:
Callable[[str], None]` and `cancel: threading.Event`, and check `cancel`
between steps; time-bounded I/O goes through `core.proc.run(timeout=…)`.
Nothing in `services/` knows which UI (or none) is on the other end.

**Events flow the other way through one stream.** `services/watch.py`
exposes `watch_session(mux, session) -> AsyncIterator[SessionEvent]`
(`PaneStateChanged`, `PaneAdded`, `PaneRemoved`, `TabsChanged`,
`FactsUpdated`). It multiplexes the pane sockets (`subscribe`), the mux
(Zellij: `list_panes` poll every 3 s; tmux: control-mode events) and the facts
refresher. UIs subscribe and reduce events into their own store; they never
poll sockets or the mux themselves.

```
              commands (hive …)            keybinds (Run hive …)         hooks (hive-hook)
                    │ direct                       │ CLI                        │ socket set
                    ▼                              ▼                            ▼
   ui/* ── aio.call ──▶  services/*  ──▶  git/ agents/ layout/ mux/  ──▶  git · agent binaries · zellij/tmux
     ▲                    │    ▲                                  ▲
     │ SessionEvent       │    │ registry.OPS (op: call)          │ PaneState (hive run's server)
     └── watch_session ◀──┘    └── control socket ◀── plugin/script/other UI
```

Two worked flows:

- **`hive run` in a pane.** `commands/run.py` parses flags →
  `ui/pickers/worktrees.pick_worktree()` (first paint from
  `services.worktrees.list()`, then `aio.call(services.facts.summaries)` fills
  dirty/ahead/behind and `aio.call(git.github.issues)` fills issues) →
  `services.pane.run_loop(pick=pick_worktree, launch=agents.launch.build_command,
  restart=…)` starts the `PaneStateServer`, updates `selecting → starting →
  running → exited`, and renames pane/tab via `mux`. The loop receives the
  picker as a callable, so `services/` never imports `ui/`.
- **Control plane presses `n`.** `ui/tui` → `await aio.call(
  services.session.new_agent_pane)` → split-or-new-tab decision from
  `mux.list_panes()` + live pane states → `mux.new_pane(...)` → a fresh
  `hive run` process starts its server → `watch_session` yields `PaneAdded`
  → the store gains a row → one `DataTable.add_row`. No polling, no `hive`
  subprocess from the UI.

### UI isolation and adding a UI

Rules (all enforced by the architecture test where mechanically checkable):

- `services/` and below never import `rich`, `prompt_toolkit`, `textual`,
  never `print`, never read stdin, never `sys.exit`. They return data or raise
  `HiveError`. Interactive decisions are made *before* calling a service (the
  flow gathers the answer and passes it) or *injected* as a callable (the run
  loop's `pick`).
- `ui/` never imports `commands/`. Views are pure functions from data to Rich
  renderables (`ui/views/*`) so any UI can reuse them; pickers use one engine
  (`ui/pickers/fuzzy.py`) and receive item builders as functions; flows
  (`ui/flows/*`) are the only place that mixes prompting with service calls.
- Every UI gets data the same two ways: `aio.call(service)` for requests,
  `watch_session()` for pushes. A UI that needs a fact nobody serves yet adds
  a service, not a subprocess.
- Rendering follows the "Rendering model" section (master plan): alternate
  screen through a diffing renderer; write only what changed.

To add a UI (a Textual dashboard, a Rust plugin, a web page): create
`ui/<name>/` (or an external process speaking the socket protocol), consume
`services` via `aio.call` / `registry.OPS`, subscribe to `watch_session` /
the control socket, reuse `ui/views` for anything already rendered elsewhere,
and add a thin `commands/<name>.py` to launch it. Nothing else changes.

### Process model and state ownership

| Process | Lifetime | Owns (single writer) | Talks to |
|---|---|---|---|
| `hive zellij` / `hive session` | until it `exec`s the multiplexer (or its restart loop) | rendered layout/config files for the session | mux attach |
| `hive run` (one per agent pane) | the pane's lifetime | that pane's `PaneState` + socket; the agent child process | mux (rename pane/tab), the picker UI on its own tty |
| agent binary (claude/codex/…) | one run | its tty | `hive-hook` → pane socket |
| `hive status` (control plane) | while open | control socket: facts cache, `registry.OPS` dispatch | pane sockets (subscribe), mux (poll / control mode) |
| `hive pane` / `hive tab` / `hive wt exec` from a keybind | < 1 s | nothing | mux, pane sockets |
| `hive-hook` | < 30 ms | nothing | pane socket |

Threads and async, in one line each: `hive run` = main thread runs the picker
and waits on the child, one daemon thread serves the socket; UIs = asyncio
loop + `to_thread` workers; everything else is single-threaded and
synchronous. A piece of state has exactly one owning process; everyone else
reads it over the socket.

### Extension checklists

- **New command**: `commands/<x>.py` (cyclopts app, ≤ ~40 lines per command
  function) + the logic in `services/` (+ `ui/views` if it renders a table);
  register lazily in `app.py`; test the service directly and the command via
  `CycloptsTestRunner` with the service patched.
- **New mux backend**: `mux/<name>/backend.py` implementing `Mux`, its
  renderers for `TabSpec`/`SessionSpec`/keybinds, a `watch_session` source if
  it can push events; register in `mux.get_mux()`; argv-exactness tests with
  `core.proc.run` patched.
- **New tool tab**: an entry in `layout/tabs.py` (bundled) or `tabs:` in
  hive.yml; nothing else.
- **New picker**: `ui/pickers/<x>.py` using the fuzzy engine; data from a
  service; long fetches via `aio.call` + `update_items`.
- **New agent**: `config/default.yml` block (`agents.configs.<name>`), and a
  hook template in `hooks/templates.py` if it has hooks.
- **New socket op**: add it to `state/protocol.py` and, if it is a service,
  to `services/registry.OPS`.

### Testing strategy

| Layer | How | Doubles |
|---|---|---|
| core, state | unit; real sockets in `short_tmp` | none |
| config | unit with temp YAML files and env | none |
| git | real temp repos (`git init`, local `origin`) | `fake_proc` only for spawn-count assertions |
| agents, layout, mux | unit; mux tested for **argv exactness** with `fake_proc`; parsers tested against recorded fixtures in `tests/fixtures/` | `FakeMux` (records calls) for callers |
| services | unit against `FakeMux`, temp repos, a real `PaneStateServer` | no CLI runner |
| ui | Textual `run_test()` pilot; prompt_toolkit `create_pipe_input` | services patched at the `hive_cli.services.<mod>.<fn>` boundary |
| commands | `CycloptsTestRunner` (`tests/conftest.py`) with services patched — thin | — |

Test fixtures shared by every spec (added in A0): `short_tmp` (short path
for sockets), `fake_proc` (records and scripts `core.proc.run`), `temp_git_repo`
(exists), `FakeMux` (F0), `pane_server` (F0). Every test file runs in CI with
no zellij, tmux, gh or network.

## A0/F0 status and divergences from this doc

A0 (issue #1, done 2026-09-05) built the layering and dependency rule above
and moved the codebase into it. F0 (done 2026-09-06) added the pane state
layer and the multiplexer protocol: `state/protocol.py`, `state/server.py`,
`state/client.py`, `mux/base.py`, `mux/__init__.py:get_mux()`, the
`ZellijMux` backend, `services/pane.py`'s `PaneContext`/`open_pane_context`/
`run_agent`, and `zellij.pane_labels`. Still missing are the `[F1]`/`[F2]`/
`[F3]`/`[F4]`/`[F5]`/`[F6]` entries and the untagged pieces `core/models.py`,
`layout/model.py`, `layout/tabs.py`, `layout/keybinds.py`,
`services/facts.py`, `services/watch.py`. `services/aio.py` and
`services/registry.py` exist as unwired stubs (`registry._MODULES = ()`, so
`load_all()` is currently a no-op) — a later feature finishes hooking them
up.

Three deliberate additions to `tests/test_architecture.py:SUBPROCESS_OK`
beyond the A0 spec's own copy of that list, each an existing behavior moved
as-is rather than a new use of `subprocess`:

- `services/session.py` — `hive zellij --restart`'s loop needs the tty and
  observes the child's exit to relaunch it; not a captured/traced call.
- `services/editors.py` — GUI editor launches (`open_in_editor`) are a
  detached, unwaited `Popen`; there is no result to capture.
- `git/analysis.py` — the `git … | delta` pipe is streamed straight to the
  terminal for interactive diff paging, not captured.

`commands/session.py` is also pre-listed in `SUBPROCESS_OK`; the file itself
is `[F3]` work and doesn't exist yet. `mux/zellij/backend.py` is listed too
but no longer imports `subprocess` (every call goes through `proc.run`).

F0 divergences from the package map and the F0 spec, all deliberate:

- **No `agents/launch.build_command() → Launch`.** A0 kept `commands/run.py`'s
  argv assembly and `services/pane.run_with_resume(...)`'s positional
  signature; F0 threads a `PaneContext` through them (`ctx=`) instead of
  introducing `Launch`. `run_loop(command, pick, ..., ctx=None)` opens the
  context when not given and always closes it; `run_agent(argv, env, ctx)`
  is the one Popen+wait.
- **`hive wt exec` is not an agent pane.** It calls `run_in_worktree` with
  `pane.null_context()`, so it never self-assigns a pane number nor serves a
  socket (the bundled layout's `neovim` pane runs through it).
- **`ZellijMux.new_pane` uses `--tab-id` and `--no-focus`.** The spec
  claimed 0.45.1 lacked both; `zellij action new-pane --help` on 0.45.1 has
  them and a live probe confirmed `--tab-id` works, so there is no
  `go-to-tab-by-id` detour. `list-panes --all --json` reports integer
  `id`/`tab_id` (normalised to strings), `is_held` for start-suspended panes
  and `pane_cwd`/`pane_command` only for running panes.
- **`services/session.start(session=, mux=)`** owns the stale socket-dir
  cleanup (`clean_stale_sock_dir`) rather than `commands/zellij.py`.
- **`RuntimeSettings.pane_sock`** is a mutable field (read from
  `HIVE_PANE_SOCK`, derived by an after-validator only when both
  `ZELLIJ_SESSION_NAME` and `ZELLIJ_PANE_ID` are actually in the env), not a
  pure computed property, because `open_pane_context` assigns it.

One accepted cosmetic deviation: `services/worktrees.py:_setup_file`'s
messages moved from a direct `warn()` call to a `progress` callback,
consistent with the "services are UI-free" rule. `commands/wt.py` passes
`progress=warn` (unchanged styling), but `ui/flows/worktrees.py`'s
`create_worktree_flow` passes `progress=info`, so those three lines render
with `info` styling instead of `warn` on that one path. No test asserts the
exact text; flagged here rather than adding a second callback for a
cosmetic-only edge path.
