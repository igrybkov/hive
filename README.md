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

#### `hive zellij layout-path`

Print the resolved path (or name) for a Zellij layout — useful for running
`zellij --layout <path>` by hand, since the bundled `agent` layout doesn't
exist as a file under `~/.config/zellij/layouts/` (it ships inside the
package).

```bash
hive zellij layout-path              # resolve the configured layout
hive zellij layout-path agent        # resolve the bundled "agent" layout
zellij --layout (hive zellij layout-path)   # fish
```

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

Execute arbitrary commands in worktrees with optional restart loop.

```bash
hive wt exec -c 'ls -la'                    # Run in git root
hive wt exec -c 'npm test' -w=-             # Interactive worktree selection
hive wt exec -c 'npm test' -w feature-123   # Specific worktree
hive wt exec -c 'make watch' --restart      # Auto-restart (re-select each time)
hive wt exec -c 'make watch' --restart -w=feat  # Restart in specific worktree
hive wt exec -c 'date' --restart --restart-delay 1  # Restart with delay
```

**Options:**

- `-c, --command TEXT`: Command to execute (shell string) [required]
- `-w, --worktree TEXT`: Run in worktree. Use `-` for interactive selection, or specify branch name
- `--restart`: Auto-restart after exit. Implies `-w=-` for interactive worktree selection
- `--restart-delay FLOAT`: Delay in seconds between restarts (default: 0)

**Restart behavior:**

- `--restart` (no `-w`): Interactive worktree selection on EACH restart
- `--restart -w feature-123`: Stay in that worktree, no re-selection between restarts
- `--restart -w=-`: Explicit interactive selection on EACH restart

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

# GitHub integration
github:
  # Fetch issues assigned to you in worktree picker
  fetch_issues: true

  # Maximum number of issues to fetch
  issue_limit: 20

# Additional directories to pass to the agent via its extra_dirs_flag.
# Relative paths resolve against the main repo root.
extra_dirs: []
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

#### `zellij.layout`

- **Type:** `string` (optional)
- **Default:** `"agent"` (the multi-agent layout bundled with this package)
- **Description:** Layout to use with `hive zellij`. Accepts three forms: the
  name of a layout bundled with this package (currently just `agent`), the
  name of a layout in Zellij's own layout dir (`~/.config/zellij/layouts/`),
  or an explicit path / anything ending in `.kdl` (`~` is expanded). Set to
  `null` to use Zellij's built-in default layout. Run
  `hive zellij layout-path [name]` to see what a value resolves to.

#### `zellij.session_name`

- **Type:** `string`
- **Default:** `"{repo}"`
- **Description:** Session name template. Supports `{repo}` (repository name) and `{agent}` (agent name) placeholders.

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
| `HIVE_ZELLIJ_LAYOUT`              | string  | Zellij layout name                             |
| `HIVE_ZELLIJ_SESSION_NAME`        | string  | Session name template                          |
| `HIVE_GITHUB_FETCH_ISSUES`        | boolean | Fetch GitHub issues                            |
| `HIVE_GITHUB_ISSUE_LIMIT`         | integer | Max issues to fetch                            |

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
