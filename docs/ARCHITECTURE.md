# Architecture

This is the architecture reference `CLAUDE.md` points to. It is copied from
the project's master plan (`.claude/plans/issue-1-tab-management.md`) and
describes the **target** layering and package map for the full `hive`
redesign (issue #1), not only what A0 built. Everything in the map below is
already in the tree, built by A0, F0, F1, F2, F3, F4, F5, or F6, or is a
pre-A0 module the refactor left in place.

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
  agents/  detection.py profiles.py launch.py        get_extra_dirs_args, hive_hook_path/hook_args (F5); no unified build_command -- see F5 divergences
  layout/  model.py tabs.py keybinds.py resolve.py bundled/*.kdl   neutral tab/pane model, bundled tab definitions, keybind spec
  mux/     base.py       Mux protocol + PaneInfo/TabInfo; get_mux()
           zellij/       backend.py (CLI calls), kdl.py (render TabSpec/SessionSpec), keybinds.py (render keybind block)
           tmux/         backend.py (TmuxMux + bootstrap), conf.py (render tmux.conf), control.py (control-mode client/parser)
  services/ worktrees.py provision/remove (git + files + post_create + handoff symlink)
            pane.py      run_loop(pick, launch, restart): state server + agent child lifecycle
            restart.py   RestartFloor: backoff after fast exits (shared by run/zellij --restart)
            session.py   start(), open_tab(), new_agent_pane(), floating_shell(), toggle_control_plane(), restart_pane(), resolve_here()
            status.py    collect_status() (1 + 2N spawns via git_summary), AgentStatus, shared-notes summary; compute_facts()/tasks_for_states() feed the control plane
            facts.py     git facts refresher: fetch_if_stale, summaries, issues; ControlServer (control socket) + summaries_via_control()
            merge.py     collect_overlap(), resolve_target(), preview() for merge-preview
            doctor.py    environment() and timings() (phase | ms | spawns) for `hive doctor`
            watch.py     watch_session() → AsyncIterator[SessionEvent]
            tasks.py handoffs.py editors.py
            registry.py  OPS: name → service callable (the surface exposed over the control socket and to external UIs)
            aio.py       call(fn, *args) = asyncio.to_thread + trace; the one adapter UIs use
  ui/      console.py    shared Console out/err, info/warn/error/success, format_*
           tty.py        raw key reads, confirm, is_interactive
           board.py      LiveBoard (Rich Live, update on change) + watch() loop behind every --watch
           pickers/      fuzzy.py (engine + refiners), worktrees.py, worktree_items.py, agents.py, profiles.py, editors.py, workdir.py, status.py
           flows/        interactive multi-step flows (create/delete worktree, new branch, issue branch) — call services
           views/        Rich renderables: status.py, merge.py, tasks.py (tables, boards, detail panels)
           tui/          Textual control plane: app.py (ControlPlaneApp), screens.py, model.py (build_rows), control_plane.tcss
  commands/ run.py zellij.py wt.py status.py task.py handoff.py diff.py rebase.py merge.py config_cmd.py completion.py doctor.py
            pane.py tab.py
            session.py     hive session: backend-neutral hive zellij, picks Zellij/tmux the way get_mux() does
  hooks/   entry.py templates.py    hive-hook: entry.main() maps an agent hook payload to a pane status via templates.status_for()
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
   the control socket carries `{"op":"call","name":"session.open_tab",
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
  `worktree_items.first_paint()`, one `git worktree list`; then two refiners
  run through `aio.call` off the picker's loop: `refine_git` fills
  dirty/ahead/behind and the branch list after a throttled fetch,
  `refine_issues` fills GitHub issues) →
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

Under tmux (F6), `services/watch.py` additionally owns one long-lived
`asyncio.create_subprocess_exec` child per watched session:
`mux/tmux/control.py:tmux_control_events` streams `tmux -C attach-session`'s
notification lines for as long as the control plane is open. This is a third
exception to rule 6 ("every external command goes through `core.proc.run`"),
alongside agent launches and `execvpe` hand-offs: `core.proc.run` captures a
bounded, waited command and returns a `Result`, which doesn't fit a streaming
client with no end and no single return value.

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

## A0/F0/F1/F2/F3/F4/F5/F6 status and divergences from this doc

A0 (issue #1, done 2026-09-05) built the layering and dependency rule above
and moved the codebase into it. F0 (done 2026-09-06) added the pane state
layer and the multiplexer protocol: `state/protocol.py`, `state/server.py`,
`state/client.py`, `mux/base.py`, `mux/__init__.py:get_mux()`, the
`ZellijMux` backend, `services/pane.py`'s `PaneContext`/`open_pane_context`/
`run_agent`, and `zellij.pane_labels`. F1 (done 2026-09-06) added tracing
(`core/trace.py` spans, marks, `spawns`), `hive doctor`, `git/status.py`'s
`GitSummary`/`parse_porcelain_v2`/`git_summary`, `services/facts.py`,
`services/merge.py`, `services/restart.py`, the picker's refiners
(`ui/pickers/fuzzy.py`, `worktree_items.py`, `worktrees.py`), `ui/board.py`
and the `--watch` boards, plus `worktrees.fetch_interval`. F2 (done
2026-09-06) added the backend-neutral layout model and its Zellij renderer:
`layout/model.py` (`PaneSpec`/`TabSpec`/`KeybindSpec`/`SessionSpec`),
`layout/tabs.py` (`agents_tab`, the bundled tool tabs, `resolve_tab`,
`session_spec`), `mux/zellij/kdl.py` (render to KDL, golden-tested),
`layout/resolve.py`'s "agent" render-on-every-start behavior,
`ZellijMux.new_tab`, and the `agents_per_tab`/`control_plane`/`tabs:`
config. `zellij.layout: "agent"` now renders a one-tab session instead of
pointing at the old static 16-pane file, which moved to `agent-16.kdl`
(`zellij.layout: "agent-16"` reproduces the old session exactly). F3 (done
2026-09-07) filled in `layout/keybinds.py` (`keybind_spec()`, mapping the
four on-demand actions to a `KeybindSpec`) and `mux/zellij/keybinds.py`
(the `keybinds { shared_except "locked" { ... } }` renderer, replacing F2's
untested inline `_render_keybinds` in `kdl.py`); `layout/tabs.py:session_spec()`
now wires them in, so every rendered `"agent"` session ships the hotkeys.
`services/session.py` gained `new_agent_pane`, `open_tab`, `resolve_here`,
`floating_shell`, `toggle_control_plane` and `hold`, the first four
registered in `services/registry.OPS` (`registry._MODULES` now loads
`"session"`, so `load_all()` is no longer a no-op); `commands/pane.py` and
`commands/tab.py` are the CLI surface over them, and `hive wt exec` gained
`--here`/a trailing positional argv and `hive status` gained `--toggle`.
F4 (done 2026-09-09) built the control plane the F3 keybind/toggle work
anticipated: `state/server.py:JsonLineServer` (extracted from
`PaneStateServer`, F0's tests unchanged), `services/facts.py:ControlServer`
(the control socket: `ping`/`get`/`facts`/`call`, the last dispatching
through `registry.OPS`) and `summaries_via_control()`, `services/watch.py`
(`watch_session()`, one `_follow` task per pane socket plus a mux-poll and
a facts-refresh loop, all funneled through one queue), and
`ui/tui/app.py:ControlPlaneApp` + `ui/tui/screens.py` + `ui/tui/model.py`
(`build_rows`/`filter_rows`/`age_bucket`/`git_cell`/`status_cell`, pure and
textual-free). `hive status` on a TTY inside a multiplexer now runs
`ControlPlaneApp` (also for `--watch`/`--compact`, kept for the bundled
layout's control-plane pane command) instead of the old Rich watch loop,
which is why `commands/status.py:watch_status()` and
`ui/views/status.py:build_watch_view()` are gone — `ui/board.py:watch()`
itself stays (`merge-preview`/`task` still use it). `toggle_control_plane()`
now actually dedupes, resolving the F3 divergence noted below.
`services/session.py` gained `restart_pane()`, also registered in
`registry.OPS`, so the control plane never touches a pane socket directly.
F5 (done 2026-09-09) added opt-in agent lifecycle hooks: `hooks/templates.py`
(per-agent hook-event → pane-status tables, plus the settings hive injects to
wire each agent's own hook mechanism to `hive-hook`) and `hooks/entry.py`
(the stdlib-only `hive-hook` console script — reads the payload, one socket
write via `state.client.set_fields`, always exits 0); `HooksConfig`
(`hooks.enabled`) and `AgentHooksConfig` (`agents.configs.<name>.hooks.mode`:
`cli` | `profile` | `unsupported`); `agents/launch.py:hive_hook_path()` +
`hook_args()`, wired into `commands/run.py` and `services/pane.py` at the
existing skip-permissions/extra_args/extra-dirs injection sites (see F5
divergences for why there's no single `build_command`); and
`agents/profiles.py:ensure_gemini_hooks()`, merged into a hive-managed
profile's `.gemini/settings.json` only for a named profile. `core/models.py`
is still missing (see the F2 divergences below for why it didn't materialize
as a separate file).

F6 (done 2026-09-09) added the tmux multiplexer backend alongside Zellij, so
the same hive workflow — agent panes, on-demand tabs/panes, floating shells,
the control-plane toggle, live control-plane updates — works under tmux with
no test needing a real tmux/zellij binary: `mux/tmux/conf.py` (`render_conf`/
`tmux_key`, golden-tested against the F6 spec's own example),
`mux/tmux/control.py` (`tmux_control_events`, `LAYOUT_EVENTS`), `mux/tmux/
backend.py` (`TmuxMux`, the full `Mux` protocol plus tmux-only `bootstrap`/
`apply_tab`), `config/schema.py:MuxConfig` (`mux.backend: auto | zellij |
tmux`, env `HIVE_MUX_BACKEND`), `mux.get_mux()`'s three-way backend
selection (config/env choice, then `$ZELLIJ`, then `$TMUX`),
`services/session.py:prepare_tmux_attach()` (renders the session's
`tmux.conf` under `layouts_dir()` and returns an idempotent `ensure_session`
closure), `services/session.py:start()` calling that closure before every
attach and every `--restart` iteration, `services/watch.py`'s tmux path
(control-mode events drive a 200 ms debounced refresh instead of Zellij's
3 s poll, alongside the same socket-scan loop that discovers new pane
sockets either way), and `commands/session.py` (`hive session`: the
backend-neutral counterpart to `hive zellij`).

F1 divergences from the package map and the F1 spec, all deliberate:

- **`services/aio.call` runs on daemon threads, not `asyncio.to_thread`.**
  prompt_toolkit's `Application.run()` is `asyncio.run()`, which joins the
  default executor on exit; with `to_thread`, pressing Enter while a refiner
  sat inside `git fetch` would have delayed the agent launch until the fetch
  returned. A private executor starting one daemon thread per call keeps the
  contract (a thread, traced) without the join.
- **The watch loop is `ui/board.watch`, not `ui/views/status.py:watch`.**
  Views stay pure; the raw-mode/select/worker loop is generic so `status`,
  `merge-preview` and `task` share it. Enter still opens the status picker
  from the board (an `exit_keys` return, then re-enter), which the spec's
  key list had dropped.
- **`--watch` is a flag plus `--interval SECONDS`** on all three commands,
  not `--watch [SECONDS]`: cyclopts has no optional-value flag, and one shape
  for the three commands is easier to remember.
- **`RestartFloor` lives in `services/restart.py`** rather than
  `services/pane.py` (the 600-line cap), imported by `pane` and `session`.
- **`hive doctor` without `--timing` prints an environment summary**
  (versions, multiplexer, agents) so the bare command does something; the
  import phase reports two rows (hive_cli modules only, and cumulative with
  dependencies), since `hive --help` is dominated by the latter.
- **The picker's first paint is the worktree list only.** Plain branches and
  cached GitHub issues arrive with the refiners (each needs a spawn); the
  "(Fetching...)" / "GitHub issues failed" header updates went with the
  `update_header` callback. `WorktreeInfo.head` carries the checked-out
  branch from the same `git worktree list` call. Issues are filtered against
  every branch known at compose time, so whichever refiner finishes last
  still yields a consistent list.
- **Startup marks sit where they are accurate:** `config_loaded` in
  `config/settings.py` (the singleton), `picker_first_paint`/`picker_refined`
  in `ui/pickers/fuzzy.py`, `agent_started` in `services/pane.run_agent`.
- Deleted as dead after F1: `git.worktree.fetch_origin`,
  `git.status.upstream_ahead_behind`, `git.status.last_commit_summary`, the
  `console.clear()` watch loop in `ui/pickers/status.py`. `list_worktrees`
  runs `git worktree list --porcelain` with `cwd=` (clean argv for spawn
  assertions) and `git_summary` likewise.

Three deliberate additions to `tests/test_architecture.py:SUBPROCESS_OK`
beyond the A0 spec's own copy of that list, each an existing behavior moved
as-is rather than a new use of `subprocess`:

- `services/session.py` — `hive zellij --restart`'s loop needs the tty and
  observes the child's exit to relaunch it; not a captured/traced call.
- `services/editors.py` — GUI editor launches (`open_in_editor`) are a
  detached, unwaited `Popen`; there is no result to capture.
- `git/analysis.py` — the `git … | delta` pipe is streamed straight to the
  terminal for interactive diff paging, not captured.

`commands/session.py` (F6's `hive session`, the backend-neutral counterpart
to `hive zellij`) and `mux/tmux/backend.py` were pre-listed in
`SUBPROCESS_OK` ahead of F6 landing; neither ended up needing `subprocess`
directly (they go through `services/session.py`/`core.proc.run` and the
`Mux` protocol like everything else), so the listing is now the same kind of
harmless over-inclusion as `mux/zellij/backend.py`, which is listed too but
no longer imports `subprocess` (every call goes through `proc.run`).
`mux/tmux/control.py`'s `tmux_control_events` is a different case: it calls
`asyncio.create_subprocess_exec` directly, not `subprocess`, so
`SUBPROCESS_OK`'s AST check never sees it — see "F6 divergences" for why
that call is exempt from rule 6 rather than an oversight.

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

F2 divergences from the package map and the F2 spec, all deliberate:

- **`layout/resolve.py` does not import `mux/zellij/kdl.py`.** The F2 spec
  has it call the renderer directly, but `layout/` and `mux/` are both
  layer 2 and the guard's sideways allow-list only permits `mux -> layout`
  (model), never the reverse. `resolve_layout()` takes the renderer as a
  `render` parameter instead; `services/session.py` (layer 3, free to
  import both) supplies `mux/zellij/kdl.render_session_file` via its
  `resolve_layout_path()` helper, which `attach_argv()` and
  `commands/zellij.py:layout_path()` both call.
- **No `layout/keybinds.py`.** F2's `KeybindSpec` is an empty-by-default
  dataclass in `layout/model.py`, same as `PaneSpec`/`TabSpec`; F3's actual
  keybind rendering is expected to land as `mux/zellij/kdl.py`'s
  `_render_keybinds` (already stubbed there, rendering nothing today) rather
  than a separate `layout/keybinds.py` module — there's no keybind-specific
  logic yet that would justify its own file. **Superseded by F3** — see below.
- **`default_tab_template`'s plugin locations have no `zellij:` prefix**
  (`plugin location="tab-bar"`, not `"zellij:tab-bar"`), matching the real
  pre-F2 `agent.kdl` (now `agent-16.kdl`) rather than the F2 spec's
  illustrative golden block, per the spec's own instruction to prefer the
  real file when the two differ.
- **The six bundled tool tabs (`teams`, `shell`, `workflow`, `git`, `tests`,
  `nvim`) are flattened to one top-level split.** `TabSpec` has exactly one
  `direction` for its whole pane list; the pre-F2 file nested splits two
  levels deep (`shell`, `workflow`) and used a Zellij `stacked=true`
  container (`teams`). Names, commands, args, cwd and sizes are unchanged;
  only the containing split structure is simpler now.
- **`hive zellij layout-path --rendered` is a documented no-op today.** The
  default already fully resolves (and, for `"agent"`, renders) every value;
  the flag exists for discoverability/forward-compatibility rather than
  changing behavior.

F3 divergences from the F3 spec, all deliberate:

- **`layout/keybinds.py` and `mux/zellij/keybinds.py` both exist after
  all**, correcting the F2 note above's prediction. `KeybindSpec.bindings`'
  run-option values widened from `dict[str, str]` to `dict[str, str | bool]`
  so a Run block can render both bare booleans (`close_on_exit true`) and
  quoted strings (`name "shell"`). The renderer is its own module (not
  `kdl.py`'s inline `_render_keybinds`, which it replaces) because
  `kdl.py:render_session_file` needs to call it — `kdl.py -> keybinds.py` is
  a one-way dependency within `mux/zellij/`, so a `keybinds.py -> kdl.py`
  import back for the shared string-quoting helper would cycle; `keybinds.py`
  keeps its own small `_quote` instead of importing `kdl.kdl_string`.
- **`services/session.hold()` takes `prompt`/`wait`/`exec_` as required (or
  defaulted-but-never-relied-on) callables**, not the spec's plain
  `print`/`input`/`os.execvp`. Two independent reasons: `services/` may not
  call `print`/`input` directly (the architecture guard AST-scans for those
  calls, `EXIT_PRINT_OK` excludes `services`), and `exec_`'s default value is
  bound once at `def` time — patching `os.execvp` after import does not
  intercept a call that goes through the stored default, so any caller that
  wants a fake exec must pass `exec_=` explicitly (`commands/pane.py`'s
  `hold` command passes real callables from `ui.console.prompt`/a local
  `input()`-wrapping function; every test that exercises the default path
  supplies its own `exec_`, and no test lets the real default run).
- **`toggle_control_plane()` was real but always returned `False` in F3.**
  Nothing before F4 served `paths.control_sock(session)` — F1's `hive status
  --watch` didn't bind a socket there. **Resolved by F4**: `ControlServer`
  now serves it for the lifetime of a running control plane, so a second
  `Alt+m` finds and focuses the first instead of starting another — see the
  F4 divergences below for what actually starts it.
- **`hive pane shell`'s non-floating case never calls
  `session.floating_shell`.** That service function always pops up
  (`mux.popup`); the command resolves the target worktree itself (reusing
  `session.resolve_here` for `--here`) and calls `mux.new_pane` directly for
  a split pane, matching the F3 spec's own parenthetical
  ("non-floating: `mux.new_pane([$SHELL], cwd=…)`").

F4 divergences from the F4 spec, all deliberate:

- **`ui/tui/` has no `screens/` or `widgets/` subpackage.** `screens.py`
  (`ConfirmScreen`/`HelpScreen`/`TabPickerScreen`/`DetailScreen`, each with
  its own small `DEFAULT_CSS`) is one file; nothing yet needs a custom
  `Widget` beyond textual's own `DataTable`/`Input`/`ListView`, so there is
  no `widgets/` package to hold one.
- **`DataTable.add_columns()` is called with `(label, key)` pairs, not bare
  labels.** Bare labels get an auto-generated `ColumnKey` that only equals
  itself (never its label text), so a later `update_cell(row_key, "status",
  …)` by name would raise; naming the keys explicitly keeps that call
  readable. `ControlPlaneApp._col_keys` holds the returned keys in column
  order.
- **`enter` is wired through `on_data_table_row_selected`, not the
  `("enter", "focus_pane", …)` binding alone.** `DataTable` binds `enter ->
  select_cursor` itself and posts `RowSelected` first; a plain (non-priority)
  app-level binding for the same key never fires while the table has focus.
  `action_focus_pane` stays reachable (e.g. focus elsewhere) but the message
  handler is what `enter` actually triggers in practice. Relatedly, the
  filter `Input` defaults to holding focus on mount even though it is
  `display: none` — and a focused `Input` eats every letter key as text — so
  `on_mount` explicitly focuses the table instead.
- **`PaneRow` does not carry the "now" used for its status age bucket.**
  `build_rows(..., now=...)` takes the parameter (matching the spec
  signature) but never reads it — `status_cell(row, now=...)` is computed at
  paint time instead, from `ControlPlaneApp._now`, which a 30 s timer
  (`_rebucket`) bumps before repainting. Baking "now" into `PaneRow` would
  make two otherwise-identical builds compare unequal, defeating the
  `always_update=False` reactive's whole point.
- **`services/session.py` gained `restart_pane(pane_id, session=, mux=)`**,
  not in the spec's interface list. `ui/tui` may not touch a pane socket
  directly (only `services/watch.py` may touch sockets/the mux from under
  `ui/`), so `action_restart_pane` needed a services-layer wrapper around
  `client.request(pane_sock, "restart")`; `commands/pane.py`'s own `restart`
  command still calls `client.request` inline; the two are not unified.
- **`--interval` now feeds `watch_session`'s pane/tab poll cadence
  (`poll_s`, floored at 2 s), not a git-refresh interval.** The control
  plane's facts refresh runs on its own fixed 30 s cadence
  (`watch_session`'s `facts_s` default, which `ControlPlaneApp` never
  overrides); nothing currently exposes that one as a flag.
- **`tasks_for_states` maps a pane to its task file by `state.branch`
  alone**, which is only an approximation of `collect_status`'s "1" for the
  main worktree, branch name otherwise: a `PaneState` carries no `is_main`
  flag, so a pane whose branch happens to be the repo's default branch
  shows no task rather than agent 1's. A pane still `selecting` (no branch
  yet) is skipped outright rather than guessed at.
- **`test_idle_writes_nothing` spies on `ControlPlaneApp._paint`, not the
  driver's `write`.** `App.run_test()` uses `HeadlessDriver`, which never
  writes to a terminal at all, so patching `write` would prove nothing; the
  test proves the real invariant — no repaint without a change — with a
  positive control (a genuine `PaneStateChanged` does trigger one).
- **`commands/status.py:watch_status()` and
  `ui/views/status.py:build_watch_view()` are deleted**, not
  `ui/board.py:watch()` (the spec's own wording, "ui/views/status.py:watch()
  is deleted," names the wrong module — `board.watch()` is the generic loop
  `merge-preview` and `task` still depend on).

F5 divergences from the F5 spec, all deliberate:

- **There is no `agents/launch.py:build_command()`.** The F5 spec (and this
  doc's own package-map line, before this update) assumed one existed for
  hook args to slot into. F0-F4 never built it: agent-command assembly is
  two separate inline sites — `commands/run.py`'s `injected_args` (feeds the
  initial/execvp command) and `services/pane.py:run_with_resume`'s
  `resume_cmd`/`injected` (feeds the dynamic-runner path) — each combining
  skip-permissions, `extra_args`, extra-dirs, and now hook args in that
  order. `hook_args()` is a plain function returning `list[str]`; both call
  sites append its result last.
- **`hooks.enabled` (with a "cli"-mode current agent) is added to
  `_compute_use_dynamic_runner`'s conditions**, not in the spec's interface
  list. The execvp fast path (`_single_run`) only swaps the binary name on a
  Ctrl+A agent switch (`[rt.agent, *command[1:]]`), keeping the rest of the
  command baked in from the *original* agent — the same reason
  `has_agent_extra_args`/`skip_permissions` already force the dynamic
  runner. Without this, a claude `--settings {...}` payload could be handed
  to codex's argv after a mid-session agent switch.
- **`hook_args()` takes an already-resolved `hive_hook: str` and a
  `settings: HiveSettings`, not just `agent: str`.** `hive_hook_path()` can
  raise `HiveError` (`hive-hook` not installed); `commands/run.py` resolves
  it once up front and fails fast with a clear CLI error rather than a
  traceback deep in the restart loop. That single resolution is only reused
  for the "cli"-mode path (Claude/Codex CLI args), which is why
  `run_with_dynamic_agent` threads the same `hive_hook` string through on
  every iteration instead of re-resolving it. The "profile"-mode path
  (Gemini) is separate: `resolve_profile_env` calls
  `launch.hive_hook_path()` itself, once per call (up to twice per
  restart-loop iteration when `--resume` is configured) -- a filesystem/PATH
  lookup, not a spawn, so repeating it is harmless but not "resolved once".
- **Codex's `notify=[...]` mechanism is now documented as "legacy" inside
  Codex's own binary strings**, superseded by a native `hooks.json` system
  with Claude-shaped event names (`PreToolUse`, `PermissionRequest`, ...).
  Verified against the installed CLI (0.153.4) and current docs on
  2026-09-09: `notify` still fires, still carries `{"type":
  "agent-turn-complete", ...}` as the final argv token exactly as documented
  — the spec's simpler single-flag approach still works and was kept as-is
  rather than adopting the newer file-based hook system, which would need a
  written-config "profile"-like mode instead of a CLI flag.
- **Gemini's hooks reference confirms the tables verified, not new ones.**
  `.gemini/settings.json`'s `hooks` object and the `SessionStart`/
  `BeforeAgent`/`BeforeTool`/`AfterTool`/`AfterAgent`/`SessionEnd` event
  names match the spec exactly (checked against geminicli.com/docs/hooks on
  2026-09-09); `gemini_settings()` and `ensure_gemini_hooks()` ship
  unchanged from the spec's shapes.

F6 divergences from the F6 spec, all deliberate:

- **`TmuxMux.list_panes`/`list_tabs` scope to `own_session()` instead of the
  spec's `-a` (all sessions on the server).** The private tmux server
  (`-L hive`) is shared across every repo/branch running under tmux, so `-a`
  would leak other repos' panes and tabs into this session's status/control
  plane. Falls back to `-a` only when `own_session()` can't be determined
  (not inside a tmux pane, e.g. `hive status` run from a plain shell).
- **`-f <conf>` is passed on every call from a conf-bearing `TmuxMux`
  instance, not just at `bootstrap`.** tmux only honors `-f` on the command
  that first creates a not-yet-running server for that socket name; rather
  than track "is this the first call," `prepare_tmux_attach`'s bootstrap
  `TmuxMux` (constructed with `conf=`) just always includes it. Harmless
  once the server exists (tmux ignores `-f` after that point) and closes a
  real bug: without it, whichever tmux subcommand happened to run first
  loaded the user's real `~/.tmux.conf`/`~/.config/tmux/tmux.conf` instead
  of hive's rendered one.
- **`LAYOUT_EVENTS` includes `unlinked-window-close`.** Verified empirically
  against a throwaway `-L` server: tmux emits `%unlinked-window-close`
  instead of `%window-close` for a window that belongs to only one session
  (true of every hive tab, since tabs are per-session windows, not linked
  across sessions) — the spec's event list only named `window-close`, which
  never actually fires for hive's layout.
- **`TmuxMux.current_tab_id()` is not in the spec's method table.** Required
  for `Mux` protocol conformance; mirrors `ZellijMux`'s own-pane-first-else-
  focused-pane fallback, which matters because a `run-shell` keybind's
  `$TMUX_PANE` is unset (verified: `run-shell` inherits `$TMUX` but not
  `$TMUX_PANE`), so `own_pane_id()` returns `None` for every on-demand
  keybind action and the code falls through to the focused pane instead —
  i.e. M-a splits into whichever pane is currently focused, not literally
  "this" pane.
- **`PaneInfo.focused` requires `#{window_active}` in addition to
  `#{pane_active}`.** `#{pane_active}` alone is `1` for the active pane of
  *every* window, not just the one in view (verified empirically: a
  two-window session lists two `pane_active=1` rows), which would have made
  `current_tab_id()`'s focused-pane fallback above pick whichever window
  `list-panes` lists first rather than the one actually in view.
- **Suspended-pane detection keys on `title.startswith("hold:")` alone**,
  not a `pane_current_command == "hive"` check the spec implied alongside
  it: `pane_current_command` reports the running interpreter (`python3.14`),
  never the literal string `"hive"`, so that half of the check could never
  match anything.
- **`layout/tabs.py`'s `_teams_tab`/`tool_tab`/`resolve_tab`, and
  `services/session.py:open_tab`, gained a `backend` parameter.** tmux has
  no native start-suspended pane, so every other suspended pane already
  routes through `hive pane hold --`; the Teams tab is the one tab whose
  command differs structurally by backend, running
  `claude --teammate-mode tmux` directly instead of wrapping it in `hold`.
- **`TmuxMux.bootstrap(self, spec)` takes one argument, not the spec's
  `bootstrap(spec, conf)` two-argument table entry.** `conf` is set once at
  `__init__` (the same instance also serves `list_panes`/`new_pane`/etc. for
  the rest of the attach), so threading it through `bootstrap` again would
  just restate constructor state.
- **`hive zellij layout-path` is not made tmux-aware.** The spec mentioned
  it printing the rendered conf path under tmux; deferred as out of scope —
  `hive session` doesn't need an equivalent introspection command yet, and
  `hive zellij` staying Zellij-only (as its name says) is simpler than
  overloading it with backend switching.
- **`hive zellij set-status`/`set-title` and `hive pane set-status`/
  `set-title` stay Zellij-only** (`mux/zellij/backend.py`'s `_set` gates on
  `rt.in_zellij`); under tmux they return `False` and print "Not running in
  Zellij session." Not a bug: F5's hook-driven status update path
  (`hive-hook` → pane socket → `PaneState`) is mux-neutral already, so the
  only thing lost under tmux is the direct CLI/keybind-driven title-segment
  helpers, which the F6 spec never asked to be ported.
- **`hive pane hold` sets the pane's title to `"hold: {command}"`** via
  `mux.rename_pane` before waiting on Enter — needed for `TmuxMux.list_panes`'s
  `title.startswith("hold:")` check to ever see a real suspended pane; the
  spec's `session.hold()` shape didn't include this, so it lives in the
  `commands/pane.py` adapter instead (services stay print/input-free, and
  `session.hold` has no `Mux` to call `rename_pane` on).

Not yet done, and not attempted this pass: an end-to-end manual check of
`HIVE_MUX_BACKEND=tmux hive session` in a real terminal (attach, all four
on-demand keybinds, the control-plane toggle, live control-plane updates
across a real control-mode stream, the Teams tab). Everything above was
verified either by the test suite (`fake_proc`/`FakeMux`, no real tmux/zellij
binary needed) or by hand against a throwaway `-L <name>` private tmux
server, killed immediately after each check.
