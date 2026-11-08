# CHANGELOG

<!-- version list -->

## v0.2.0 (2026-11-08)

### Bug Fixes

- **arch**: Remove stale duplicate fuzzy test files
  ([`d5a25f3`](https://github.com/igrybkov/hive/commit/d5a25f386d024d957918662bc70e1b7f41edf8fb))

- **config**: Replace removed codex --full-auto with -a on-request -s workspace-write
  ([`2f56d73`](https://github.com/igrybkov/hive/commit/2f56d7371c14c2c3255f146414e334c43643e6ec))

- **diff**: Don't parse raw diff output as Rich markup
  ([`c7c9293`](https://github.com/igrybkov/hive/commit/c7c9293a18e72690946466f4c3b597540e000383))

- **handoffs**: Preserve the OSError safety net in _exclude_from_git
  ([`4307e36`](https://github.com/igrybkov/hive/commit/4307e366a7d1982497bafd49892b99329b2811dd))

- **merge**: Drop unreachable fallback text in _preview_agent_merge
  ([`ebcb07b`](https://github.com/igrybkov/hive/commit/ebcb07bcc3391238e78f89601d6f2f8714dd4cd1))

- **mux**: Tmux focused-pane detection requires window_active too
  ([`8986d86`](https://github.com/igrybkov/hive/commit/8986d86d2bc502c891dea945d4eff367720b7c99))

- **pane**: Pause instead of dying when a --restart pane's reselect is cancelled
  ([`d5a34f5`](https://github.com/igrybkov/hive/commit/d5a34f5b365581fc52d97e3cd96ede42d7c7cff4))

- **pane**: Set hold-marker pane title for tmux suspended-pane detection
  ([`2508ec2`](https://github.com/igrybkov/hive/commit/2508ec260740bb6e93ab0c13e44ec88a934e0d90))

- **session**: Open an agents tab when Alt+n is pressed in a tab with no agent
  ([`f28dab1`](https://github.com/igrybkov/hive/commit/f28dab116ade52fb4bd36fc7641028d6476edf37))

- **session**: Stop duplicating suspended agent panes, nest control plane
  ([`0acf656`](https://github.com/igrybkov/hive/commit/0acf6567f658cc92bc51cd87f84be92c889671cc))

- **tmux**: Pane-id sigil safety, hold-title detection, execvpe binary
  ([`2405fdc`](https://github.com/igrybkov/hive/commit/2405fdcc5214a37551e5a67624187039dd2ceb5e))

- **worktree**: Keep hive's handoff symlink out of git tracking
  ([`c7cfa5e`](https://github.com/igrybkov/hive/commit/c7cfa5e14dd69a07cb0e208c8356aff4be41838e))

- **zellij**: Focus the new pane after new-pane --tab-id
  ([`b0f5668`](https://github.com/igrybkov/hive/commit/b0f566846d1b3a78da00368a6f1583f7a9041740))

- **zellij**: Keep focus on the new pane after moving it to the bottom slot
  ([`f24b60b`](https://github.com/igrybkov/hive/commit/f24b60b19493c45c21d8a11e2d2c4d84d022be5b))

- **zellij**: Put the newest pane in the wide bottom slot of the 2-over-1 grid
  ([`64adbbf`](https://github.com/igrybkov/hive/commit/64adbbf3973fc3e50b61954e6569a8050223cda2))

### Chores

- **pre-commit**: Add complexipy cognitive-complexity hook
  ([`9c861f5`](https://github.com/igrybkov/hive/commit/9c861f575cbeb14187510ecdd251d8f404da624b))

- **release**: Bump version to 0.2.0
  ([`21e41b8`](https://github.com/igrybkov/hive/commit/21e41b8ac4d2da2b13ff51527eeefaa69ece1800))

### Documentation

- Correct overclaim about hive_hook_path resolution cadence
  ([`49bb6b7`](https://github.com/igrybkov/hive/commit/49bb6b75ba58d652aa841a96496ee13504a555d0))

- Document agent hooks and F5 divergences (F5 step 5)
  ([`174f42c`](https://github.com/igrybkov/hive/commit/174f42ca6075aabcb6c15cb5312be460f1fc1ae4))

- Document F6 tmux backend (F6 step 5)
  ([`1f07555`](https://github.com/igrybkov/hive/commit/1f075558af81395fbd0db867ba30e6ccf6d30a82))

- F2 layout in README + ARCHITECTURE.md (F2 step 6)
  ([`b778b35`](https://github.com/igrybkov/hive/commit/b778b35b45f27d9eb084d246b26085770c03c27e))

- F3 hotkeys, hive pane/tab, wt exec --here, status --toggle (F3 step 6)
  ([`7e5becc`](https://github.com/igrybkov/hive/commit/7e5becc4245d4741f66c62518c13b3876ea06f7f))

- Record the pane_active/window_active F6 divergence
  ([`56ccb43`](https://github.com/igrybkov/hive/commit/56ccb431440c8edc1dac7da647e2a87d53e1a988))

- **arch**: Add docs/ARCHITECTURE.md, rewrite CLAUDE.md Architecture section
  ([`179eade`](https://github.com/igrybkov/hive/commit/179eadeb4d43f4480f6140e8f3920e663a1df48b))

- **claude**: Performance rules; README --watch/doctor/fetch_interval; F1 status
  ([`09c1ca5`](https://github.com/igrybkov/hive/commit/09c1ca56f6d1d75b0420df38f11c6451e507c4b5))

### Features

- **agents**: Inject hive-hook into cli-mode agent launches (F5 step 3)
  ([`8581ff1`](https://github.com/igrybkov/hive/commit/8581ff1518b2b3666877f1f21faf4c2814dd1dbc))

- **agents**: Merge hive-hook into Gemini's profile settings.json (F5 step 4)
  ([`bdb2a54`](https://github.com/igrybkov/hive/commit/bdb2a543b41d1aa4970a5bc7a2f5bcf33d510c9f))

- **cli**: Hive pane and hive tab commands (F3 step 3)
  ([`57f65d3`](https://github.com/igrybkov/hive/commit/57f65d3682af293949b35f78ca47d0b787c22959))

- **cli**: Wt exec --here and status --toggle (F3 step 4)
  ([`35b8229`](https://github.com/igrybkov/hive/commit/35b8229ea1255d02b4ab0acfc4a3698ef9e6b33f))

- **config**: Agents_per_tab/control_plane/tabs schema for F2 layout
  ([`ca0c88c`](https://github.com/igrybkov/hive/commit/ca0c88c89262dce4989d35cf661f21c1cc5e85f9))

- **config**: HooksConfig and per-agent AgentHooksConfig (F5 step 2)
  ([`12406aa`](https://github.com/igrybkov/hive/commit/12406aa1ba9878440e6e3ca16970a03e2d849acc))

- **config**: Pane_label/pane_sock runtime fields, zellij.pane_labels
  ([`81ba049`](https://github.com/igrybkov/hive/commit/81ba049f09616da3369861fe37225b5fb7ca39f2))

- **env**: Refresh the agent env from a fresh shell and direnv/.env at each launch
  ([`331a6e7`](https://github.com/igrybkov/hive/commit/331a6e789fba58968104158483df9deaeea055a0))

- **facts**: ControlServer socket and summaries_via_control (F4 step 2)
  ([`7310fbf`](https://github.com/igrybkov/hive/commit/7310fbf3b0953c504b34e7695eba67f7468be639))

- **facts**: Fetch throttle, per-worktree summaries, cached gh issues
  ([`b8dc951`](https://github.com/igrybkov/hive/commit/b8dc95165fe277509de2f2203e51efbc6b7aafc7))

- **hooks**: Stdlib-only hive-hook entry point and per-agent templates (F5 step 1)
  ([`596799d`](https://github.com/igrybkov/hive/commit/596799d3bafad86169949826fbf53da84a732d75))

- **keybinds**: Configurable hotkeys shipped in the rendered session (F3 step 1)
  ([`c8835f8`](https://github.com/igrybkov/hive/commit/c8835f8e605d7b8d86e07bf5528c4a12fdb77e65))

- **layout**: Model dataclasses + bundled/user tabs (F2 step 1)
  ([`88cad25`](https://github.com/igrybkov/hive/commit/88cad252a48e241a5961ad3788ac3a13bb812247))

- **layout**: Render "agent" per-session, agent-16 is the old bundled file (F2 step 4)
  ([`6601858`](https://github.com/igrybkov/hive/commit/6601858cb90e8742d5a8479e226ee586fc11b03a))

- **mux**: Mux protocol, get_mux(), ZellijMux backend, FakeMux
  ([`6edb196`](https://github.com/igrybkov/hive/commit/6edb1961b9e728111ddad8d12ff5525932935669))

- **mux**: Render layout.model to Zellij KDL (F2 step 2)
  ([`24cb1b3`](https://github.com/igrybkov/hive/commit/24cb1b37bfd6da8e97a74c0b3569b740d2a4a430))

- **mux**: Stale socket-dir cleanup on session start; F0 docs
  ([`90a8105`](https://github.com/igrybkov/hive/commit/90a81051e396ca744ccee2a31222174ba9c371dd))

- **mux**: ZellijMux.new_tab renders and creates a tab (F2 step 5)
  ([`4bdde13`](https://github.com/igrybkov/hive/commit/4bdde1331cf67fabf60107c528e39118994e4897))

- **panes**: Random-pool names for on-demand panes, layout labels on suspended board rows
  ([`2e27456`](https://github.com/igrybkov/hive/commit/2e27456049b0a30f8e6fe3147cc044788f6ac5ca))

- **session**: Commands/session.py -- backend-neutral \`hive session\` (F6 step 4)
  ([`cf30953`](https://github.com/igrybkov/hive/commit/cf3095310624603aa8f2b4dd9f1a8c6169b526b9))

- **session**: On-demand pane/tab/shell/control-plane service functions (F3 step 2)
  ([`2bdfdc2`](https://github.com/igrybkov/hive/commit/2bdfdc2559a725dd9396b556cce9a2e11f0c7e18))

- **session**: Tmux attach path, restart re-bootstrap, teams-tab nesting fix
  ([`363a047`](https://github.com/igrybkov/hive/commit/363a047c24e09d4397bc49c09f6eb761d9f1c000))

- **state**: Hive run serves its pane state; delete legacy state files
  ([`01e4edf`](https://github.com/igrybkov/hive/commit/01e4edf7040e3f1f3bdb21c9c28920866005fbea))

- **state**: Pane state server and stdlib client
  ([`4d165b6`](https://github.com/igrybkov/hive/commit/4d165b670585f14e6351eb61763e311ffcee3bb6))

- **state**: PaneState model, title/tab-name composition, NDJSON protocol
  ([`723bfc4`](https://github.com/igrybkov/hive/commit/723bfc417445363b88f5bc53cc7165ddf8273152))

- **status**: Show a hook-reported session summary on the control plane
  ([`ddc8c55`](https://github.com/igrybkov/hive/commit/ddc8c55e913df1e361fbf83a65ec8da08a945c09))

- **status**: Wire the control-plane TUI into `hive status` (F4 step 5)
  ([`a6e9f67`](https://github.com/igrybkov/hive/commit/a6e9f6751df357bda5c04de8658fc8c2d458870b))

- **tmux**: TmuxMux backend, config, get_mux wiring (F6 step 1-2)
  ([`59d039f`](https://github.com/igrybkov/hive/commit/59d039f7fdef4bdff1480c3ce93d549a53c4c627))

- **tui**: ControlPlaneApp, screens, keybindings (F4 step 4)
  ([`e541840`](https://github.com/igrybkov/hive/commit/e54184011d21263970c8072ecb58db265c1d6293))

- **tui**: Live filter by worktree, vim j/k row navigation
  ([`13e9fbc`](https://github.com/igrybkov/hive/commit/13e9fbc5edf0d470be06029f1292fb4705b1aa90))

- **tui**: Pure row-building model for the control plane (F4 step 1)
  ([`ebfbafb`](https://github.com/igrybkov/hive/commit/ebfbafb47b77f73e5cbb55bed2646165d2b243dc))

- **ui**: Worktree picker reads git facts from the control socket (F4 step 6)
  ([`f592f83`](https://github.com/igrybkov/hive/commit/f592f838202e8abee7d35a6bb03fb6c93941a65f))

- **watch**: Event-driven discovery for the tmux backend (F6 step 3)
  ([`26504e5`](https://github.com/igrybkov/hive/commit/26504e587a6c0010aba712ea138ec08d981eef6f))

- **watch**: Watch_session multiplexes pane sockets, mux poll, facts (F4 step 3)
  ([`2b1fdac`](https://github.com/igrybkov/hive/commit/2b1fdacede4b9df17b08acbe62c52bd9c038d29d))

- **zellij**: Alt+[/Alt+] layout cycling presets; codex runs with --approve-for-me
  ([`851431b`](https://github.com/igrybkov/hive/commit/851431b39b48f8879f70b506837527568ec1a4d0))

- **zellij**: Live agent-layout modes, swap-layout rebalancing, dedicated control-plane tab
  ([`7dbbfcd`](https://github.com/igrybkov/hive/commit/7dbbfcde7de93e18506d69076d3f0b6eb49addf4))

- **zellij**: Uncapped agent panes, count-driven grid layout, fix Alt+n splits
  ([`966c5a3`](https://github.com/igrybkov/hive/commit/966c5a3388056345f9cefa05946a85c1d1270a19))

### Performance Improvements

- **git**: GitSummary from porcelain v2; status collect is 1 + 2N spawns
  ([`0b26a04`](https://github.com/igrybkov/hive/commit/0b26a04b4e6855788612ef4be25fb4127c9848cd))

- **pane**: Restart floor after fast exits; cache get_main_repo per process
  ([`86a143e`](https://github.com/igrybkov/hive/commit/86a143e497fea86c8753e91ad2917ef7ec97ec6c))

- **picker**: Refiners on the event loop; first paint is one spawn
  ([`da905ed`](https://github.com/igrybkov/hive/commit/da905edf092986d3352e49a0c3c5b64e30d7be50))

- **trace**: Spans, marks, spawn counter; hive doctor --timing
  ([`dd49ace`](https://github.com/igrybkov/hive/commit/dd49acee2300c1330246577e93fc310e2b3d9f4b))

- **ui**: LiveBoard; status/merge-preview/task --watch paint only on change
  ([`8070875`](https://github.com/igrybkov/hive/commit/807087563beb7e3c5d56e16db07a63f8228fa476))

### Refactoring

- **arch**: Add A0 safeguards (surface snapshot, architecture guard)
  ([`f1ab4c9`](https://github.com/igrybkov/hive/commit/f1ab4c97347a3fc70efb317a0fbee403b5e57874))

- **arch**: Add core/ layer (errors, proc, trace, paths)
  ([`0e80c7a`](https://github.com/igrybkov/hive/commit/0e80c7a186c5630bf197fa2698476bd31ff73a3d))

- **arch**: Add git/analysis.py, move rebase/diff/merge git logic there
  ([`443b6bc`](https://github.com/igrybkov/hive/commit/443b6bcffa990efcd8647a635601737a1728fbed))

- **arch**: Add services/aio.py and services/registry.py
  ([`a7fa928`](https://github.com/igrybkov/hive/commit/a7fa92813804909e5e234c266d3a70189a843b4d))

- **arch**: Add ui/console+tty, fold is_interactive, drop dead selection.py
  ([`ccec1a6`](https://github.com/igrybkov/hive/commit/ccec1a649997db768271e89d7289ee04ada26156))

- **arch**: Decouple agents/launch.py from git
  ([`55b0056`](https://github.com/igrybkov/hive/commit/55b005609c5fc6b7220e5733308ddd1d2858c37f))

- **arch**: Delete utils/ barrel, confine subprocess to services layer
  ([`65e3175`](https://github.com/igrybkov/hive/commit/65e3175206a786dc8a319ff9e6730f1a7eeb9be5))

- **arch**: Lazy command registration, kill exec_runner.py cross-import
  ([`a897505`](https://github.com/igrybkov/hive/commit/a897505d037c8b3fe15d3214ef4c1f84d4c34a13))

- **arch**: Make config/ pure (no git spawn, no subprocess import)
  ([`c83b52d`](https://github.com/igrybkov/hive/commit/c83b52d29fd64f136d9f604a9b3be71e0105b8d4))

- **arch**: Move fuzzy_select to ui/pickers/fuzzy.py
  ([`e43af32`](https://github.com/igrybkov/hive/commit/e43af3274919ebd5694a8ae5c278ae33f0ef5dce))

- **arch**: Move utils/agents.py, workdir.py, editors.py, profiles.py to ui/pickers
  ([`89299e0`](https://github.com/igrybkov/hive/commit/89299e03d351bf53fa6d8e98a9af6956bed03292))

- **arch**: Replace subprocess with proc.run across git/
  ([`7ba27f0`](https://github.com/igrybkov/hive/commit/7ba27f040d6277ae12130d03cdca28accdb13142))

- **arch**: Retire utils/zellij.py and utils/layouts.py
  ([`34accea`](https://github.com/igrybkov/hive/commit/34accea2f4cb535265724e93f24063ff4d655614))

- **arch**: Split commands/status.py into git/services/ui layers
  ([`ccbb995`](https://github.com/igrybkov/hive/commit/ccbb99591549af632701eda45a41dfee8cdad71e))

- **arch**: Split commands/wt.py into git/services/ui layers
  ([`3827469`](https://github.com/igrybkov/hive/commit/382746984497981910569e498cf96120431cec0d))

- **arch**: Split git/worktree_paths.py out of git/worktree.py
  ([`22310b1`](https://github.com/igrybkov/hive/commit/22310b13c4f6deac3338a610a1d585ce748964ef))

- **arch**: Split services/editors.py out of utils/editors.py
  ([`b386c6e`](https://github.com/igrybkov/hive/commit/b386c6e095e5f7e5f0e5ee5c7c62557aba0645cd))

- **arch**: Split services/handoffs.py out of handoffs.py
  ([`4449691`](https://github.com/igrybkov/hive/commit/44496916457387ef17ec2b8a41c418aae0a5a0ed))

- **arch**: Split services/pane.py out of commands/exec_runner.py
  ([`0202d06`](https://github.com/igrybkov/hive/commit/0202d0666e83b8e6f54d5e84b6a88ec03217da90))

- **arch**: Split services/tasks.py out of commands/task.py
  ([`fedbbac`](https://github.com/igrybkov/hive/commit/fedbbac2a85e286492d6796739b3bfe6df2e494c))

- **arch**: Split services/worktrees.py out of utils/deps.py
  ([`5a6bfee`](https://github.com/igrybkov/hive/commit/5a6bfee195ce562fbdf689e5225d9874541480e2))

### Testing

- Add git-backed integration coverage across CLI, worktrees and handoffs
  ([`324eada`](https://github.com/igrybkov/hive/commit/324eada9563a9c184059c84ba62072cb87daf552))

- Rename fuzzy picker tests to test_ui_pickers_* convention
  ([`a1ba7ec`](https://github.com/igrybkov/hive/commit/a1ba7ec2534ccfd119c5aa189235eb135f4ccda8))

- **cli**: Refresh the pane new help snapshot
  ([`8bbcbbe`](https://github.com/igrybkov/hive/commit/8bbcbbe0ffb865633b910af1d3a783d1a3e3ba60))

- **run**: Fix vacuous hooks-disabled assertion (F5 follow-up)
  ([`6cd053a`](https://github.com/igrybkov/hive/commit/6cd053ab844147870fd6d09bcc9a4ca7fbb933eb))


## v0.1.0 (2026-07-29)

### Features

- Import hive CLI from dotfiles
  ([`ce1d291`](https://github.com/igrybkov/hive/commit/ce1d29183e75adebe7d0e431a9304315318e18c2))
