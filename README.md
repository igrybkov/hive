# hive-cli

**Hive** - Multi-agent worktree management CLI.

## Overview

`hive` is a CLI tool for managing AI coding agents and git worktrees for parallel development. It provides a unified interface for launching AI agents, managing Zellij sessions, and coordinating multi-agent workflows.

## Installation

Install from GitHub with `uv` (recommended):

```bash
uv tool install --from git+https://github.com/igrybkov/hive.git hive-cli
```

Or with `pipx`:

```bash
pipx install git+https://github.com/igrybkov/hive.git
```

For local development, install editable from a checkout:

```bash
uv tool install -e /path/to/hive
```

If you use [igrybkov/dotfiles](https://github.com/igrybkov/dotfiles), the `agents`
profile installs `hive` for you via `./dotfiles install pipx`.

## Commands

### `hive run`

Run an AI coding agent in the current directory.

```bash
hive run                      # Auto-detect and run agent
hive run --resume             # Resume most recent conversation
hive run -r                   # Short form of --resume
hive run -a claude            # Use Claude specifically
HIVE_AGENT=gemini hive run         # Use Gemini via env var

# Worktree integration
hive run -w=-                 # Interactive worktree selection, then run
hive run -w feature-123       # Run in specific worktree

# Auto-restart mode
hive run --restart            # Interactive worktree selection + auto-restart
hive run --restart -w main    # Auto-restart in main repo (no re-selection)
hive run --restart -w feat    # Auto-restart in specific worktree
hive run --restart --restart-delay 2  # Add 2s delay between restarts
hive run -r --restart         # Resume with auto-restart

# Config profiles (multiple accounts side-by-side)
hive run -p work              # Use 'work' config profile for the agent
hive run --profile personal   # Use 'personal' config profile
HIVE_AGENT_PROFILE=work hive run  # Via env var
```

**Options:**

- `-a, --agent TEXT`: Specific agent to use (overrides auto-detection)
- `-w, --worktree TEXT`: Run in worktree. Use `-` for interactive selection, or specify branch name
- `-r, --resume`: Resume most recent conversation (falls back to new session if none)
- `--restart`: Auto-restart the agent after it exits. Implies `-w=-` for interactive worktree selection
- `--restart-delay FLOAT`: Delay in seconds between restarts (default: 0)
- `-p, --profile TEXT`: Agent config profile to use (see [Config Profiles](#config-profiles))

#### Pane state sockets

Inside a Zellij session every `hive run` serves its pane's state on a Unix
socket at `$XDG_RUNTIME_DIR/hive/<session>/<pane>.sock` (or
`/tmp/hive-$UID/hive/<session>/<pane>.sock` when `XDG_RUNTIME_DIR` is unset)
and removes it when it exits. The state is one JSON object — pane and tab
ids, pane number and label, agent, profile, branch, worktree path, status
(`selecting`, `starting`, `running`, `busy`, `waiting`, `idle`, `done`,
`exited`), agent pid — and it drives the pane title and the tab name. Read it
with `nc -U <socket>`: the first line is the current state; send
`{"op":"subscribe"}` to follow changes, or
`{"op":"set","fields":{"status_text":"[x]"}}` to change it, which is what
`hive zellij set-status` does.

#### Agent hooks

Set `hooks.enabled: true` and `hive run` wires each agent's own hook/notify
mechanism to a tiny `hive-hook` executable, so the pane's `status` (and with
it the tab name and the control plane's status column) reflects busy /
waiting-for-permission / idle / done instead of only running / exited.
`hive-hook` is stdlib-only, does one socket write, and always exits `0` — a
failing hook never blocks or annoys the agent.

```yaml
hooks:
  enabled: true # off by default
```

hive never edits your global agent settings — it injects hook config three
different ways depending on the agent:

| Agent          | Wiring                                            | Notes                                                  |
| -------------- | -------------------------------------------------- | ------------------------------------------------------- |
| `claude`       | `--settings '{"hooks":{...}}'` on every launch     | Merges with `~/.claude/settings.json`; doesn't touch it |
| `codex`        | `-c notify=["<hive-hook>","codex"]` on every launch | **Replaces** any `notify` you've set in `config.toml` while hooks are enabled — hive doesn't merge notify |
| `gemini`       | Merged into the profile's `.gemini/settings.json`  | Only for a **named** `--profile`; your real `~/.gemini/settings.json` is never touched |
| `copilot`      | Not wired                                          | Copilot's hooks live in the repo's `.github/hooks`, outside hive's reach |
| `agent`/`cursor-agent` | Not wired                                  | `CURSOR_CONFIG_DIR` doesn't relocate `hooks.json`      |

For Claude and Codex ("cli" mode), hooks apply to every launch of that agent.
For Gemini ("profile" mode), they only apply when you pass `-p`/`--profile`
with a named profile (`hive run -p work`) — running with the default profile
never touches your real Gemini config. Each agent's wiring mode is
configurable per-agent under `agents.configs.<name>.hooks.mode`
(`cli` | `profile` | `unsupported`).

### `hive zellij`

Open Zellij with an AI agent layout.

```bash
hive zellij                          # Auto-detect agent
hive zellij -a claude                # Use Claude specifically
hive zellij --restart                # Auto-restart after Zellij exits
hive zellij --restart --restart-delay 1  # Restart with 1s delay
HIVE_AGENT=gemini hive zellij             # Use Gemini via env var
```

**Options:**

- `-a, --agent TEXT`: Specific agent to use (overrides auto-detection)
- `--restart`: Auto-restart Zellij after it exits
- `--restart-delay FLOAT`: Delay in seconds between restarts (default: 0)

#### Session layout

The default `zellij.layout: "agent"` renders `zellij.agents_per_tab` (1 or 2)
agent panes running `hive run --restart`, plus a `hive status --watch` board
controlled by `zellij.control_plane`: `tab` (the default) gives it its own
dedicated first tab (full, uncompacted), created right away alongside the
agents tab, which starts at tab 2 and is the one focused on attach; `right`
nests a `--compact` pane under the *last* agent
pane's own column instead (that pane on top, the control plane at the
bottom); `bottom` gives it a full-width `--compact` row under every agent
pane; `none` omits it entirely. `tab` renders **two tabs** total; every other
value renders one, with the agent panes side by side in it. It re-renders on
every `hive zellij` start — there's no static file to edit.
Further agent tabs and tool tabs are opened
on demand (see `layout/tabs.py:BUNDLED` for the bundled tool tabs — `teams`,
`shell`, `workflow`, `git`, `tests`, `nvim`); add your own or override a
bundled one with `tabs:` in config (see below).

The old 16-pane hand-maintained session is still available:

```yaml
zellij:
  layout: "agent-16"
```

#### Agent-pane layout: split, stacked, tabs

`zellij.agents_layout` picks how on-demand agents (`hive pane new`, the
control plane's `n`) relate to each other, independently of `agents_per_tab`:

- `split` (default): today's side-by-side panes.
- `stacked`: Zellij-native pane stacking instead of a split. Falls back to
  `split` when `zellij.control_plane: "right"` — nesting the status pane
  into a stack raises questions this doesn't try to answer yet.
- `tabs`: never split — once idle slots run out, every further agent opens
  a fresh one-pane tab, regardless of `agents_per_tab`. Pair with
  `agents_per_tab: 1` for a literal single-pane-per-tab session.

Switch it live for the rest of a session — without touching config — with
the control plane's `L` hotkey (picks from a list) or:

```bash
hive pane layout             # print the effective mode
hive pane layout stacked     # switch to Zellij-stacked agent panes
```

A live switch only affects agents created from then on; it never rearranges
panes already open.

#### Hotkeys

The rendered `"agent"` session ships five hotkeys — the user's own Zellij
config is never touched. All but one work without a `clear-defaults` and
without overriding any of the user's own bindings; `new_agent_pane` is the
deliberate exception: it replaces Zellij's own default `Alt n` ("new pane")
binding for the life of the session, so the muscle-memory "new pane" key
opens a hive-managed agent pane instead of a blank shell.

| Default key   | Action                       | Runs                                |
| ------------- | ----------------------------- | ------------------------------------- |
| `Alt n`       | New agent pane                 | `hive pane new`                       |
| `Alt Shift a` | New agents tab                 | `hive tab agents`                     |
| `Alt Shift s` | Floating shell here             | `hive wt exec --here -- $SHELL`       |
| `Alt m`       | Toggle control plane            | `hive status --toggle`                |
| `Alt Shift w` | Floating shell, pick a worktree | `hive wt exec --worktree - -- $SHELL` |

Change or disable them under `zellij.keybinds` in config (see
[`zellij.keybinds`](#zellijkeybinds) below) — set a key to `null` to disable
just that one binding, or `enabled: false` to disable all five.

Tool tabs (bundled and user-defined) and agent panes also open on demand
outside the hotkeys, via `hive tab`/`hive pane` — see below.

#### `hive zellij layout-path`

Print the resolved path (or name) for a Zellij layout — useful for running
`zellij --layout <path>` by hand. `agent` renders and writes its session
file on every call (there's nothing to look at until you do); `agent-16`
and other bundled/path/passthrough values are static, as before.

```bash
hive zellij layout-path              # render+resolve the configured layout
hive zellij layout-path agent        # render+resolve the "agent" layout
hive zellij layout-path agent-16     # the old 16-pane session file
zellij --layout (hive zellij layout-path)   # fish
```

### `hive session` and the tmux backend

`hive session` is the backend-neutral counterpart to `hive zellij`: it picks
Zellij or tmux the same way `get_mux()` does everywhere else — `mux.backend`
in config, `HIVE_MUX_BACKEND`, or the multiplexer the process is already
inside — falling back to Zellij when none of those apply and nothing is
running yet (the same "starting fresh" experience `hive zellij` has always
had, since `mux.backend: auto` alone can't tell you which multiplexer to
*start*).

```bash
hive session                          # Auto-detect agent and backend
HIVE_MUX_BACKEND=tmux hive session    # Force the tmux backend
```

```yaml
mux:
  backend: tmux # auto (default) | zellij | tmux
```

Enabling tmux gets you the same workflow as Zellij — agent panes, on-demand
tabs/panes, a floating shell, the control-plane toggle, live control-plane
updates — on a private tmux server (`tmux -L hive`) that never touches your
own `~/.tmux.conf`. Differences worth knowing:

| Need | Zellij | tmux |
|---|---|---|
| Create window/pane in a dir with a command | `new-tab -c`, `new-pane --cwd` | `new-window -c -n`, `split-window -h -c` |
| Floating shell / control-plane toggle | floating panes (persistent, movable) | `display-popup` (**modal** — closes when the command inside it exits) |
| Discover panes/tabs | `list-panes --json` (polled every 3s) | `list-panes`, re-run on each debounced control-mode layout event |
| Push events | none from the CLI (plugin only) | **control mode** (`tmux -C attach-session`) streams window-add/close/rename/layout-change |
| Own-pane identity | `$ZELLIJ_PANE_ID`, `$ZELLIJ_SESSION_NAME` | `$TMUX_PANE`, `tmux display -p '#S'` |
| Start-suspended pane | native | emulated: `hive pane hold -- CMD` waits for Enter, then execs |

Only `zellij.layout: "agent"` is supported under tmux (`agent-16` is a
static Zellij layout file with no tmux equivalent). The Teams tab runs
`claude --teammate-mode tmux` directly instead of wrapping it in a suspended
`hold` pane. `hive zellij` itself — including `set-status`/`set-title` and
`layout-path` — stays Zellij-only; under tmux, `hive pane set-status`/
`set-title` are no-ops (agent status still updates via hooks regardless of
backend — only the direct CLI/keybind-driven title helpers are Zellij-only).
A `run-shell` keybind (`Alt n`, etc.) inherits tmux's session but not
`$TMUX_PANE`, so on-demand panes/tabs split relative to whichever pane is
currently focused, not literally "the pane the key was pressed in."

### `hive wt`

Manage git worktrees for multi-agent development.

```bash
hive wt                  # Interactive selection (same as hive wt cd)
hive wt cd [BRANCH]      # Navigate to worktree (outputs path)
hive wt list             # List worktrees (branch:path format)
hive wt path BRANCH      # Get path for worktree
hive wt parent           # Get main repository path
hive wt create BRANCH    # Create worktree
hive wt delete BRANCH    # Delete worktree
hive wt exists BRANCH    # Check existence (exit 0/1)
hive wt base             # Get base directory for worktrees
hive wt ensure NUM       # Interactive agent workflow
```

### `hive wt exec`

Execute arbitrary commands in worktrees with optional restart loop — also
the CLI surface behind the `Alt Shift w` hotkey (`hive wt exec --worktree -
-- $SHELL`, see [Hotkeys](#hotkeys)): pick a worktree, land in a shell there.

```bash
hive wt exec -c 'ls -la'                    # Run in git root
hive wt exec -c 'npm test' -w=-             # Interactive worktree selection
hive wt exec -c 'npm test' -w feature-123   # Specific worktree
hive wt exec --here -- npm test             # Run in the current pane's worktree
hive wt exec -c 'make watch' --restart      # Auto-restart (re-select each time)
hive wt exec -c 'make watch' --restart -w=feat  # Restart in specific worktree
hive wt exec -c 'date' --restart --restart-delay 1  # Restart with delay
```

**Options:**

- `-c, --command TEXT`: Command to execute (shell string)
- Trailing positional args (after `--`): alternative to `-c` — the argv to run directly, no shell
- `-w, --worktree TEXT`: Run in worktree. Use `-` for interactive selection, `here` for the worktree of the current directory, or specify branch name
- `--here`: Same as `-w here` — run in the worktree of the current directory. Outside any worktree, warns and falls back to the interactive picker
- `--restart`: Auto-restart after exit. Implies `-w=-` for interactive worktree selection
- `--restart-delay FLOAT`: Delay in seconds between restarts (default: 0)

**Restart behavior:**

- `--restart` (no `-w`): Interactive worktree selection on EACH restart
- `--restart -w feature-123`: Stay in that worktree, no re-selection between restarts
- `--restart -w=-`: Explicit interactive selection on EACH restart

### `hive pane`

Create and manage agent panes — the CLI surface behind the `Alt n` hotkey
and `hive pane shell` behind `Alt Shift s` (see [Hotkeys](#hotkeys)).

```bash
hive pane new                       # split an agent pane into this tab
hive pane new -a codex -w feat      # ...running codex on branch 'feat'
hive pane new --tab-id t2           # into a specific tab instead of the current one
hive pane new --no-focus            # create it without switching focus
hive pane shell --here              # split shell, cwd in this pane's worktree
hive pane shell -w feat --floating  # floating popup shell in the 'feat' worktree
hive pane list                      # panes in this session + their hive state
hive pane list --json               # same, as JSON
hive pane focus 3                   # focus pane 3
hive pane close 3                   # close pane 3
hive pane restart 3                 # restart the agent running in pane 3
hive pane layout                    # print the session's live layout mode
hive pane layout stacked            # switch new agents to Zellij-stacked panes
```

`new` splits into the target tab if it has room for another agent pane
(`zellij.agents_per_tab`), else it opens a fresh one-pane agents tab —
prints the new pane's id either way (see [Agent-pane
layout](#agent-pane-layout-split-stacked-tabs) for `stacked`/`tabs`
modes). `hold -- CMD…` (used by the tmux backend for start-suspended panes)
waits for Enter before running `CMD`. `set-status`/`set-title` are the same
as `hive zellij set-status`/`set-title`, kept under both names.

### `hive tab`

Open tool tabs and agent tabs on demand — the CLI surface behind the
`Alt Shift a` hotkey.

```bash
hive tab git              # open the bundled git tab
hive tab agents           # same as Alt Shift a
hive tab mytab            # open a user-defined tab from tabs: config
hive tab agents --no-focus  # open it without switching focus
hive tab list             # list every openable tab name (bundled + user + agents)
```

Neither `hive pane` nor `hive tab` blocks: they only ask the multiplexer to
create the pane/tab and exit — the same `close_on_exit true` shape as the
hotkeys' own `Run` blocks.

### Control plane: `hive status`

On a TTY inside a multiplexer, `hive status` is the session control plane —
a Textual app with one row per pane in the session (not just started
agents: a not-yet-started agent slot shows as `idle`, a plain tool pane
like `shell`/`lazygit` shows its layout name with blank agent/git/task
columns; the control plane's own pane never gets a row), pushed live over
the pane sockets, a cheap list-panes/list-tabs poll for pane/tab discovery,
and keys to focus/create/close/restart panes and open tabs. The leading
`pane` column is the row's identity (label or layout name); `agent` is the
CLI type (`claude`, `codex`, ...) and is blank for non-agent panes. It is the one
place `hive` now fetches on a timer unprompted: every 30s it runs
`git fetch origin` (only when the pane's `FETCH_HEAD` is stale) plus
`git status`/`log` for every worktree, to refresh the git-status column —
look for it in `HIVE_TRACE=1` output if you're auditing spawns. It also
serves a control socket (`control.sock` in the session's runtime dir) that
pickers use to read the same git facts instead of fetching their own (so
the picker's periodic fetch is skipped whenever a control plane is up),
and that `hive status --toggle` (the `Alt m` hotkey) uses to find and
focus a running instance instead of starting a second one.

```bash
hive status                # the control plane (TTY + multiplexer); falls
                            # back to the one-shot table otherwise
hive status --toggle       # Alt+m's target: focus the running control
                            # plane, or start one (this pane becomes it)
hive status --plain        # one-shot Rich table, for scripts/pipes
hive status --plain -c     # ...single-line-per-agent
hive status -i             # one-shot interactive picker, outputs a path
```

| Key      | Action                                          |
| -------- | ------------------------------------------------ |
| `Enter`  | Focus the selected pane                          |
| `n`      | New agent pane, targeting the selected row's tab |
| `t`      | New agents tab (same as `hive tab agents`)       |
| `T`      | Open a tool tab (pick from bundled/user tabs)    |
| `L`      | Change the live agent-pane layout (split/stacked/tabs) |
| `f`      | Floating shell in the selected pane's worktree   |
| `x`      | Close the selected pane (confirms first)         |
| `r`      | Restart the agent in the selected pane           |
| `d`      | Git status + recent commits for the selected pane|
| `/`      | Filter rows (branch/agent/label/pane/task substring) |
| `g`      | Refresh git facts now                            |
| `?`      | Help                                             |
| `q`      | Quit                                             |

The control socket speaks the same one-JSON-object-per-line protocol as a
pane socket (see [Pane state sockets](#pane-state-sockets)); besides
`ping`/`get`, it answers `facts` (the same git summaries the TUI shows) and
`call` (dispatches any operation `hive`'s control plane registers, by name):

```bash
printf '{"op":"facts"}\n' | nc -U "$XDG_RUNTIME_DIR/hive/<session>/control.sock"
printf '{"op":"call","name":"session.open_tab","args":{"name":"git"}}\n' \
  | nc -U "$XDG_RUNTIME_DIR/hive/<session>/control.sock"
```

`hive merge-preview` and `hive task` still use the older live-board pattern
(`--watch`, `--interval SECONDS`; alternate screen, repainted only on
change, `q` quits, `r` refreshes now) — that model predates the control
plane and stays for these two single-purpose views:

```bash
hive merge-preview --watch            # file overlap between agents, live
hive merge-preview 2 -w --interval 30 # simulated merge for agent 2 every 30 s
hive task --watch                     # every agent's task file
```

### `hive doctor`

```bash
hive doctor            # versions (hive, python, git, zellij), multiplexer, agents on PATH
hive doctor --timing   # phase | ms | spawns: import, config, worktree list, git summaries, status
```

`--timing` runs each startup phase in-process and counts the commands it
spawned; the import row is measured in a fresh interpreter with
`python -X importtime`. For a full trace of any command (phase marks such as
`picker_first_paint`, every spawned command with its duration, refiner
timings) run it with `HIVE_TRACE=1`; the lines go to stderr.

### `hive completion`

Generate shell completion scripts.

```bash
hive completion fish           # Print fish completion
hive completion fish --install # Install fish completion
hive completion bash           # Print bash completion
```

## Configuration

Hive supports project-specific configuration through YAML files:

- **`.hive.yml`** - Version-controlled project configuration
- **`.hive.local.yml`** - Local overrides (add to `.gitignore`)
- **`$XDG_CONFIG_HOME/hive/hive.yml`** - Global user configuration

### Configuration Precedence

Settings are merged in order (highest to lowest priority):

1. Environment variables (`HIVE_*` prefix)
2. `.hive.local.yml` (local overrides)
3. `.hive.yml` (project config)
4. `$XDG_CONFIG_HOME/hive/hive.yml` (global config, defaults to `~/.config/hive/hive.yml`)
5. Built-in defaults

### Full Configuration Reference

```yaml
# .hive.yml - Example configuration with all options

# Agent detection and configuration
agents:
  # Priority order for auto-detection (first available wins)
  order:
    - claude
    - gemini
    - codex
    - agent # Cursor agent CLI
    - copilot

  # Per-agent configuration
  configs:
    claude:
      resume_args: ["--continue"]
      skip_permissions_args: ["--dangerously-skip-permissions"]
      extra_dirs_flag: "--add-dir"

    copilot:
      resume_args: ["--continue"]
      skip_permissions_args: ["--allow-all"]
      extra_dirs_flag: "--add-dir"

    codex:
      resume_args: ["resume", "--last"]
      skip_permissions_args: ["--full-auto"]
      extra_dirs_flag: "--add-dir"

    gemini:
      resume_args: ["--resume", "latest"]
      skip_permissions_args: ["-y"]
      extra_dirs_flag: "--include-directories"

    agent:
      resume_args: ["resume"]
      skip_permissions_args: ["-f"]

    cursor-agent:
      resume_args: ["resume"]
      skip_permissions_args: ["-f"]

    # Add custom agents as needed
    my-custom-agent:
      resume_args: ["--restore"]
      skip_permissions_args: ["--yes"]
      extra_dirs_flag: "--dir"

# Resume behavior defaults
resume:
  # Default value for --resume flag when not specified
  enabled: false

# Git worktree configuration
worktrees:
  # Set to false to disable worktrees feature entirely
  enabled: true

  # Directory template for worktrees. Supports ~ expansion and placeholders:
  #   {repo}   - repo path relative to home (e.g., Projects--dotfiles)
  #   {branch} - sanitized branch name
  parent_dir: "~/.worktrees/{repo}/{branch}"

  # Default --resume flag for worktree sessions
  resume: false

  # Default --skip-permissions flag for worktree sessions
  skip_permissions: false

  # Seconds between `git fetch origin` runs started by the worktree picker.
  # Throttled on .git/FETCH_HEAD's age, so 16 pickers share one fetch.
  fetch_interval: 300

  # Files to symlink from main repo into each new worktree (relative paths)
  symlink_files:
    - ".env"

  # Files to copy from main repo into each new worktree (relative paths)
  copy_files:
    - ".env.local"

  # Auto-select a branch in the worktree picker after a timeout.
  # Any keypress cancels the timer.
  auto_select:
    enabled: false
    branch: "-" # Use "-" for repo's default branch
    timeout: 3.0 # Seconds before auto-selection

  # Commands to run after creating a worktree
  # Each command can have an optional if_exists condition
  post_create:
    - command: "mise trust"
      if_exists: ".mise.toml"

    - command: "pnpm install --frozen-lockfile"
      if_exists: "pnpm-lock.yaml"

    - command: "yarn install --frozen-lockfile"
      if_exists: "yarn.lock"

    - command: "npm ci"
      if_exists: "package-lock.json"

    - command: "uv sync --frozen"
      if_exists: "pyproject.toml"

# Zellij terminal multiplexer configuration
zellij:
  # Layout to use. Defaults to "agent" (the multi-agent layout bundled with
  # this package). Also accepts a layout name from ~/.config/zellij/layouts/
  # or an explicit path (anything containing "/" or ending in ".kdl"). Set to
  # null to use Zellij's built-in default layout.
  # layout: "agent"

  # Session name template
  # Supports placeholders: {repo} = repository name, {agent} = agent name
  session_name: "{repo}"

  # Labels for agent panes c1..c16, in the bundled layout's order. A
  # `hive run` started on demand (outside the layout) takes the first free
  # pane number and its label from this list.
  # pane_labels: [Anton, Bohdan, Chris, Dmytro, Emily, Frank, Grygoriy, Henry,
  #               Ihor, Jake, Kateryna, Liam, Mykola, Noah, Orest, Petro]

  # Fallback names for on-demand pane numbers beyond pane_labels (c17, c18,
  # ...): one is picked at random, excluding any name already in use, so
  # opening many more agents than pane_labels has entries still gets real
  # names instead of a bare "c17". See config/default.yml for the full
  # 70-name default (Ukrainian and American first names).
  # pane_label_pool: [Andriy, Vasyl, ...]

  # Hotkeys shipped inside the rendered session file (see Hotkeys above). Set
  # a key to null to disable just that one binding, or enabled: false for all.
  keybinds:
    enabled: true
    new_agent_pane: "Alt n"
    new_agent_tab: "Alt Shift a"
    floating_shell: "Alt Shift s"
    control_plane: "Alt m"
    worktree_shell: "Alt Shift w"

  # Command the floating-shell/worktree-shell hotkeys run. null uses $SHELL.
  floating_shell_command: null

# GitHub integration
github:
  # Fetch issues assigned to you in worktree picker
  fetch_issues: true

  # Maximum number of issues to fetch
  issue_limit: 20

# Additional directories to pass to the agent via its extra_dirs_flag.
# Relative paths resolve against the main repo root.
extra_dirs: []

# Agent lifecycle hooks -> pane status (see "Agent hooks" above).
hooks:
  enabled: false
```

### Configuration Options

#### `agents.order`

- **Type:** `list[string]`
- **Default:** `["claude", "gemini", "codex", "agent", "copilot"]`
- **Description:** Priority order for agent auto-detection. First available agent wins.

#### `agents.configs.<name>.resume_args`

- **Type:** `list[string]`
- **Default:** Varies per agent
- **Description:** Arguments to prepend when using `--resume`. Set to `[]` to disable resume for an agent.

#### `agents.configs.<name>.skip_permissions_args`

- **Type:** `list[string]`
- **Default:** Varies per agent
- **Description:** Arguments to add when using `--skip-permissions` mode.

#### `agents.configs.<name>.extra_dirs_flag`

- **Type:** `string` (optional)
- **Default:** Varies per agent (`null` if not supported)
- **Description:** CLI flag the agent uses for additional directories (e.g., `--add-dir` for Claude, `--include-directories` for Gemini).

**Built-in agent defaults:**
| Agent | Resume Args | Skip Permissions Args | Extra Dirs Flag |
|-------|-------------|----------------------|-----------------|
| claude | `["--continue"]` | `["--dangerously-skip-permissions"]` | `--add-dir` |
| copilot | `["--continue"]` | `["--allow-all"]` | `--add-dir` |
| codex | `["resume", "--last"]` | `["--full-auto"]` | `--add-dir` |
| gemini | `["--resume", "latest"]` | `["-y"]` | `--include-directories` |
| agent | `["resume"]` | `["-f"]` | — |
| cursor-agent | `["resume"]` | `["-f"]` | — |

#### `resume.enabled`

- **Type:** `boolean`
- **Default:** `false`
- **Description:** Default value for `--resume` flag when not explicitly specified.

#### `worktrees.enabled`

- **Type:** `boolean`
- **Default:** `true`
- **Description:** Enable/disable worktree features. When `false`, `hive wt` commands will error.

#### `worktrees.parent_dir`

- **Type:** `string`
- **Default:** `"~/.worktrees/{repo}/{branch}"`
- **Description:** Directory template for worktrees. Supports `~` expansion and placeholders: `{repo}` (repo path name, e.g., `Projects--dotfiles`), `{branch}` (sanitized branch name). When `{repo}` is absent, a flat `{repo}--{branch}` directory is used automatically.

#### `worktrees.resume`

- **Type:** `boolean`
- **Default:** `false`
- **Description:** Default `--resume` flag for worktree sessions (separate from `resume.enabled`).

#### `worktrees.skip_permissions`

- **Type:** `boolean`
- **Default:** `false`
- **Description:** Default `--skip-permissions` flag for worktree sessions.

#### `worktrees.fetch_interval`

- **Type:** `float` (seconds)
- **Default:** `300`
- **Description:** How often the worktree picker runs `git fetch origin`.
  The picker paints from the worktree list first and refreshes branches,
  dirty/ahead/behind markers and GitHub issues in the background; the
  fetch runs only when `.git/FETCH_HEAD` is older than this, so many
  pickers starting at once (the multi-agent layout) share one fetch.
  Env: `HIVE_WORKTREES_FETCH_INTERVAL`.

#### `worktrees.auto_select`

Auto-select configuration for the worktree picker. When enabled, automatically selects a branch after a timeout. Any keypress cancels.

- **`auto_select.enabled`** (`boolean`, default `false`): Enable auto-selection.
- **`auto_select.branch`** (`string`, default `"-"`): Branch to auto-select. Use `"-"` for the repo's default branch.
- **`auto_select.timeout`** (`float`, default `3.0`): Seconds before auto-selection (0 for instant).

#### `worktrees.symlink_files`

- **Type:** `list[string]`
- **Default:** `[]`
- **Description:** Files to symlink from main repo into each new worktree. Paths are relative to the repo root. Useful for files like `.env` that should stay in sync across worktrees.

#### `worktrees.copy_files`

- **Type:** `list[string]`
- **Default:** `[]`
- **Description:** Files to copy from main repo into each new worktree. Paths are relative to the repo root. Useful for files that need independent copies per worktree.

#### `worktrees.post_create`

- **Type:** `list[object]`
- **Default:** See example above
- **Description:** Commands to run after creating a worktree.

Each item can be:

- A string: `"npm install"` (always runs)
- An object with conditions:
  ```yaml
  - command: "pnpm install"
    if_exists: "pnpm-lock.yaml"
  ```

#### `mux.backend`

- **Type:** `"auto" | "zellij" | "tmux"`
- **Default:** `"auto"` (`get_mux()` picks Zellij inside a Zellij session,
  tmux inside a tmux session, else `None`)
- **Description:** Which multiplexer `hive session` (and everything that
  calls `get_mux()`) uses. See [`hive session` and the tmux
  backend](#hive-session-and-the-tmux-backend).

#### `zellij.layout`

- **Type:** `string` (optional)
- **Default:** `"agent"` (renders the one-tab layout described in [Session
  layout](#session-layout))
- **Description:** Layout to use with `hive zellij`. Accepts: `"agent"`
  (rendered fresh on every start), `"agent-16"` (the old hand-maintained
  16-pane session, a static bundled file), the name of a layout in Zellij's
  own layout dir (`~/.config/zellij/layouts/`), or an explicit path /
  anything ending in `.kdl` (`~` is expanded). Set to `null` to use Zellij's
  built-in default layout. Run `hive zellij layout-path [name]` to see what
  a value resolves to.

#### `zellij.agents_per_tab`

- **Type:** `integer` (`1` or `2`)
- **Default:** `2`
- **Description:** Agent panes in the `"agent"` layout's tab.

#### `zellij.control_plane`

- **Type:** `string` (`"right"`, `"bottom"`, `"none"`, or `"tab"`)
- **Default:** `"tab"`
- **Description:** Where the `hive status --watch` board lives. `"right"`
  nests a `--compact` pane under the *last* agent pane's own column (that
  pane on top, the control plane at the bottom); `"bottom"` gives it a
  full-width `--compact` row under every agent pane instead; `"none"` omits
  it entirely; `"tab"` gives it its own dedicated first tab (full,
  uncompacted), created right away alongside the agents tab, which starts at
  tab 2 and is the one focused on attach.

#### `zellij.agents_layout`

- **Type:** `string` (`"split"`, `"stacked"`, or `"tabs"`)
- **Default:** `"split"`
- **Description:** Starting arrangement for on-demand agent panes (see
  [Agent-pane layout](#agent-pane-layout-split-stacked-tabs)). `"split"` is
  today's side-by-side panes; `"stacked"` uses Zellij pane stacking instead
  (falls back to `"split"` when `control_plane` is `"right"`); `"tabs"`
  never splits — once idle slots run out, every further agent opens a new
  tab, regardless of `agents_per_tab`. Switchable live for the rest of a
  session with the control plane's `L` hotkey or `hive pane layout <mode>`,
  which don't touch this config value.

#### `zellij.session_name`

- **Type:** `string`
- **Default:** `"{repo}"`
- **Description:** Session name template. Supports `{repo}` (repository name) and `{agent}` (agent name) placeholders.

#### `zellij.pane_labels`

- **Type:** `list[string]`
- **Default:** the sixteen names used by the `agent-16` layout's `c1: Anton` … `c16: Petro` panes
- **Description:** Labels for agent panes, in pane-number order. Inside a
  Zellij session, a `hive run` started outside the layout (a pane you opened
  by hand) picks the first pane number no other `hive run` in the session
  holds and takes its label from this list, so its title reads like the
  layout's own panes. Env: `HIVE_ZELLIJ_PANE_LABELS` (comma-separated).

#### `zellij.pane_label_pool`

- **Type:** `list[string]`
- **Default:** 70 names (Ukrainian and American), see `config/default.yml`
- **Description:** Fallback names for on-demand pane numbers beyond
  `pane_labels` (c17, c18, …). One is picked at random, excluding any name
  already in use by a live or pending pane in the session, so opening many
  more agents than `pane_labels` has entries still gets real names instead
  of a bare `c17`; only exhausting both lists at once falls back to that.
  Env: `HIVE_ZELLIJ_PANE_LABEL_POOL` (comma-separated).

#### `zellij.keybinds`

- **Type:** `object`
- **Default:** the five bindings in [Hotkeys](#hotkeys)
- **Description:** Hotkeys shipped inside the rendered `"agent"` session
  file — never the user's own Zellij config, except `new_agent_pane`, which
  deliberately replaces Zellij's own default `Alt n` binding.
  - **`keybinds.enabled`** (`boolean`, default `true`): master switch for all
    five bindings.
  - **`keybinds.new_agent_pane`** (`string | null`, default `"Alt n"`):
    `hive pane new`.
  - **`keybinds.new_agent_tab`** (`string | null`, default `"Alt Shift a"`):
    `hive tab agents`.
  - **`keybinds.floating_shell`** (`string | null`, default `"Alt Shift s"`):
    `hive wt exec --here`.
  - **`keybinds.control_plane`** (`string | null`, default `"Alt m"`):
    `hive status --toggle`.
  - **`keybinds.worktree_shell`** (`string | null`, default `"Alt Shift w"`):
    `hive wt exec --worktree -` — the interactive picker, then a shell.

  A key set to `null` disables just that one binding. Zellij key syntax:
  `"Alt a"`, `"Alt Shift s"`.

#### `zellij.floating_shell_command`

- **Type:** `string` (optional)
- **Default:** `null` (uses `$SHELL`)
- **Description:** Command the floating-shell and worktree-shell hotkeys
  (and `hive pane shell --floating`) run. Split with `shlex` the same way
  `tabs:` pane commands are.

#### `tabs`

- **Type:** `dict[string, TabConfig]`
- **Default:** `{}`
- **Description:** User-defined tool tabs, opened the same way as the
  bundled ones (`teams`, `shell`, `workflow`, `git`, `tests`, `nvim`). A key
  matching a bundled name overrides it; any other key adds a new tab.
  ```yaml
  tabs:
    docs:
      panes:
        - name: docs
          command: "less README.md"
        - name: shell
          suspended: true
  ```
  Each pane: `name` (required), `command` (a string, split with `shlex`, or
  a list of argv strings; omitted/empty makes a plain shell pane), `cwd`,
  `size` (`"30%"` or a cell count), `suspended` (start suspended, Enter to
  launch).

#### `github.fetch_issues`

- **Type:** `boolean`
- **Default:** `true`
- **Description:** Fetch GitHub issues in worktree picker for branch suggestions.

#### `github.issue_limit`

- **Type:** `integer`
- **Default:** `20`
- **Description:** Maximum number of issues to fetch.

#### `extra_dirs`

- **Type:** `list[string]`
- **Default:** `[]`
- **Description:** Additional directories to pass to the agent via its `extra_dirs_flag`. Relative paths resolve against the main repo root.

#### `hooks.enabled`

- **Type:** `boolean`
- **Default:** `false`
- **Description:** Wire agent lifecycle hooks to the pane's status (see [Agent hooks](#agent-hooks)).

#### `agents.configs.<name>.hooks.mode`

- **Type:** `"cli" | "profile" | "unsupported"`
- **Default:** `"unsupported"` (`"cli"` for claude/codex, `"profile"` for gemini, in the bundled defaults)
- **Description:** How hive wires this agent's hook mechanism to `hive-hook` when `hooks.enabled` is true (see [Agent hooks](#agent-hooks)).

### Environment Variables

Environment variables use the `HIVE_` prefix and take precedence over config files:

| Variable                          | Type    | Description                                    |
| --------------------------------- | ------- | ---------------------------------------------- |
| `HIVE_AGENTS_ORDER`               | CSV     | Agent priority order, e.g., `claude,gemini`    |
| `HIVE_AGENT`                      | string  | Override agent for this session (set by picker) |
| `HIVE_AGENT_PROFILE`              | string  | Active config profile name (set by picker or `--profile`) |
| `HIVE_RESUME_ENABLED`             | boolean | Enable resume by default                       |
| `HIVE_WORKTREES_ENABLED`          | boolean | Enable worktrees feature                       |
| `HIVE_WORKTREES_PARENT_DIR`       | string  | Directory template for worktrees               |
| `HIVE_WORKTREES_RESUME`           | boolean | Default resume for worktree sessions           |
| `HIVE_WORKTREES_SKIP_PERMISSIONS` | boolean | Default skip-permissions for worktree sessions |
| `HIVE_WORKTREES_FETCH_INTERVAL`   | float   | Seconds between picker-started `git fetch origin` runs |
| `HIVE_ZELLIJ_LAYOUT`              | string  | Zellij layout name                             |
| `HIVE_ZELLIJ_SESSION_NAME`        | string  | Session name template                          |
| `HIVE_GITHUB_FETCH_ISSUES`        | boolean | Fetch GitHub issues                            |
| `HIVE_GITHUB_ISSUE_LIMIT`         | integer | Max issues to fetch                            |
| `HIVE_HOOKS_ENABLED`              | boolean | Wire agent lifecycle hooks to the pane's status |
| `HIVE_MUX_BACKEND`                | `auto`\|`zellij`\|`tmux` | Multiplexer backend, overriding `mux.backend` |
| `HIVE_PANE_ID`                    | integer | Agent pane number (c1..c16); set by the layout, self-assigned by `hive run` otherwise |
| `HIVE_PANE_LABEL`                 | string  | Pane label in the title (`c1: Anton`); from `zellij.pane_labels`, falling back to `zellij.pane_label_pool`, when self-assigned |
| `HIVE_PANE_SOCK`                  | path    | Pane-state socket served by this pane's `hive run` (exported to the agent) |
| `HIVE_TRACE`                      | `1`     | Trace phase marks, spawned commands and refiner timings to stderr |

**Legacy variables** (still supported, lower precedence than `HIVE_*`):

- `AGENT`: Override agent selection for current command

### Example Configurations

**Minimal project config:**

```yaml
# .hive.yml
agents:
  order: [claude, gemini]
```

**TypeScript project:**

```yaml
# .hive.yml
worktrees:
  post_create:
    - command: "pnpm install --frozen-lockfile"
      if_exists: "pnpm-lock.yaml"
  copy_files:
    - ".env.local"
```

**Python project with uv:**

```yaml
# .hive.yml
worktrees:
  post_create:
    - command: "mise trust"
      if_exists: ".mise.toml"
    - command: "uv sync --frozen"
      if_exists: "pyproject.toml"
```

**Personal overrides (git-ignored):**

```yaml
# .hive.local.yml
resume:
  enabled: true # Always resume by default

github:
  fetch_issues: false # Don't fetch issues (faster)
```

## Config Profiles

Config profiles let you run the same agent with an isolated config directory —
separate credentials, history, settings, and session state. This is the same
idea as `alias claude-work='CLAUDE_CONFIG_DIR=~/.claude-work claude'`, but
managed interactively through the worktree picker.

### Storage layout

Profiles are stored at `$XDG_CONFIG_HOME/hive/profiles/<agent>/<profile>/`
(default: `~/.config/hive/profiles/claude/work/`). Each profile directory
**is** the agent's config home — it is passed directly to the agent via its
config-dir env var.

### Using profiles

**In the worktree picker** (`hive run -w=-` or `hive run --restart`):

| Key | Action |
|-----|--------|
| `^P` | Open profile picker |

The profile picker shows:
- `<default>` — use the agent's default config dir (no override)
- Existing profiles in `$XDG_CONFIG_HOME/hive/profiles/<agent>/`
- `＋ new profile…` — type a name to create a new profile directory

The active profile is shown in the header: `Agent 1 [claude] [profile: work]`.

**Via CLI flag:**

```bash
hive run -p work              # Use 'work' profile
hive run --profile personal   # Use 'personal' profile
HIVE_AGENT_PROFILE=work hive run  # Via env var (persists to child processes)
```

`HIVE_AGENT_PROFILE` round-trips through restart loops and nested hive calls.
Switching agent via `^A` resets the profile (profiles are agent-scoped).

### Login isolation per agent

All five supported agents redirect **config + session history** cleanly.
**Login credentials** vary:

| Agent | Config-dir var | Login isolation |
|-------|---------------|-----------------|
| `claude` | `CLAUDE_CONFIG_DIR` | ✅ Fully isolated |
| `gemini` | `GEMINI_CLI_HOME`¹ | ✅ hive sets `GEMINI_FORCE_FILE_STORAGE=true` automatically |
| `codex` | `CODEX_HOME` | ✅ hive seeds `config.toml` with `cli_auth_credentials_store = "file"` |
| `copilot` | `COPILOT_HOME` | ⚠️ Config+history isolated; auth token lives in OS Keychain (shared) |
| `agent` / `cursor-agent` | `CURSOR_CONFIG_DIR` | ⚠️ Config+chats isolated; tokens in OS Keychain (no clean env knob) |

¹ `GEMINI_CLI_HOME` is source-verified but undocumented in official Gemini CLI
docs as of nightly v0.47 — verify against your installed version.

### Per-agent config in hive.yml

You can override or extend profile config per agent:

```yaml
agents:
  configs:
    claude:
      profile:
        config_dir_env: CLAUDE_CONFIG_DIR  # override env var name if needed
    myagent:
      profile:
        config_dir_env: MYAGENT_HOME
        extra_env:
          MYAGENT_FILE_CREDS: "true"      # set when profile is active
        seed_files:
          config.toml: |                   # written on profile creation
            credentials_store = "file"
```

## Architecture

### Module Structure

```
src/hive_cli/
├── app.py                  # Main CLI app entry point
├── agents/
│   └── detection.py        # Agent auto-detection logic
├── config/                 # Configuration module
│   ├── __init__.py         # Public API (load_config, reload_config)
│   ├── schema.py           # Dataclasses for config structure
│   ├── loader.py           # YAML loading and precedence
│   ├── merge.py            # Deep merge utility
│   └── defaults.py         # Default values
├── git/
│   ├── repo.py             # Git repository utilities
│   └── worktree.py         # Worktree management
├── utils/
│   ├── terminal.py         # Terminal output helpers
│   ├── fuzzy.py            # Fuzzy finder integration
│   ├── deps.py             # Dependency installation (post_create)
│   └── ...
├── layouts/
│   └── agent.kdl           # Bundled multi-agent Zellij layout
└── commands/
    ├── run.py              # hive run command
    ├── zellij.py           # hive zellij command
    ├── wt.py               # hive wt command group
    ├── exec_runner.py      # Core worktree execution logic
    ├── options.py          # Shared CLI option decorators
    └── ...
```

### Key Components

- **`exec_runner.py`**: Core execution logic for running commands in worktrees with restart support. Used by `hive run`, `hive wt exec`, and other commands.
- **`options.py`**: Shared Click option decorators for common options like `--worktree`, `--restart`, `--restart-delay`.

## Development

```bash
# Install dev dependencies
uv sync --dev

# Run tests
uv run pytest -v

# Run linter
uv run ruff check .

# Format (check-only: --check)
uv run ruff format .
```

See `CLAUDE.md` for an architecture overview and release process.
