"""Tests for services/pane.py.

apply_workdir_override moved here from commands/exec_runner.py's
_apply_workdir_override (A0 step 6), dropping its leading underscore now
that it's a cross-module service function. run_loop/`_restart_loop`/
`_single_run`/`_select_for_iteration` are new: the restart-loop and
single-run bodies of commands/exec_runner.py's run_in_worktree, with
printing extracted into clear_screen/progress/confirm_restart callbacks
and Zellij pane-renaming extracted into an on_branch_selected callback.
run_in_worktree itself is still covered end-to-end via the CLI in
test_run.py/test_wt.py/test_wt_cli.py -- these tests exercise run_loop
directly with fake callbacks/pick functions.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

from hive_cli.services.pane import apply_workdir_override, run_loop

# ---------------------------------------------------------------------------
# apply_workdir_override
# ---------------------------------------------------------------------------


class TestApplyWorkdirOverride:
    def test_noop_when_no_override(self, tmp_path, monkeypatch):
        """Without rt.workdir, cwd is not changed and override list stays None."""
        from hive_cli.config import get_runtime_settings

        rt = get_runtime_settings()
        rt.workdir = None
        rt.workdir_extras_override = None

        primary = tmp_path / "primary"
        primary.mkdir()
        monkeypatch.chdir(primary)

        apply_workdir_override(primary)

        assert Path(os.getcwd()).resolve() == primary.resolve()
        assert rt.workdir_extras_override is None

    def test_swap_sets_cwd_and_extras(self, tmp_path, monkeypatch):
        """Override: cwd→chosen, primary prepended to extras, chosen dropped."""
        from hive_cli.config import get_runtime_settings, load_config

        primary = tmp_path / "primary"
        primary.mkdir()
        chosen = tmp_path / "chosen"
        chosen.mkdir()
        other = tmp_path / "other"
        other.mkdir()

        config_file = tmp_path / ".hive.yml"
        config_file.write_text(
            f"""
extra_dirs:
  - {chosen}
  - {other}
"""
        )
        load_config.cache_clear()

        rt = get_runtime_settings()
        rt.workdir = chosen
        rt.workdir_extras_override = None

        monkeypatch.chdir(primary)
        try:
            with (
                patch(
                    "hive_cli.config.loader.find_config_files",
                    return_value=[config_file],
                ),
                patch("hive_cli.git.get_main_repo", return_value=tmp_path),
            ):
                apply_workdir_override(primary)

            assert Path(os.getcwd()).resolve() == chosen.resolve()
            assert rt.workdir_extras_override == [str(primary), str(other)]
        finally:
            rt.workdir = None
            rt.workdir_extras_override = None


# ---------------------------------------------------------------------------
# run_loop
# ---------------------------------------------------------------------------


def _fake_pick_sequence(*results):
    """A `pick` stand-in that returns each of results in turn, then repeats last."""
    results = list(results)

    def pick(worktree, last_selected_branch=None, **kwargs):
        return results.pop(0) if results else results[-1]

    return pick


class TestRunLoopSingle:
    def test_single_run_execvp_path(self, monkeypatch):
        monkeypatch.setattr(
            "hive_cli.services.pane.get_runtime_settings", lambda: _FakeRT()
        )
        calls = []

        def fake_execvpe(exe, argv, env):
            calls.append((exe, argv, env))

        with patch("hive_cli.services.pane.os.execvpe", side_effect=fake_execvpe):
            result = run_loop(
                ["claude"],
                _fake_pick_sequence((True, "main")),
                runner=lambda cmd: 0,
            )

        assert result == 0
        assert calls == [("claude", ["claude"], {})]

    def test_single_run_cancelled_returns_1(self):
        result = run_loop(
            ["claude"],
            _fake_pick_sequence((False, None)),
            runner=lambda cmd: 0,
        )
        assert result == 1

    def test_single_run_custom_runner_skips_execvp(self):
        calls = []

        def custom_runner(cmd):
            calls.append(cmd)
            return 42

        with patch("hive_cli.services.pane.os.execvpe") as mock_execvpe:
            result = run_loop(
                ["claude"],
                _fake_pick_sequence((True, "main")),
                runner=custom_runner,
                run_command=custom_runner,
            )

        mock_execvpe.assert_not_called()
        assert calls == [["claude"]]
        assert result == 42

    def test_on_branch_selected_and_clear_screen_called(self):
        selected = []
        cleared = []

        run_loop(
            ["claude"],
            _fake_pick_sequence((True, "feat")),
            runner=lambda cmd: 0,
            use_execvp=False,
            on_branch_selected=selected.append,
            clear_screen=lambda: cleared.append(True),
        )

        assert selected == ["feat"]
        assert cleared == [True]


class TestRunLoopRestart:
    def test_restart_loop_runs_until_pick_fails(self):
        run_count = []

        def runner(cmd):
            run_count.append(cmd)
            return 0

        result = run_loop(
            ["claude"],
            _fake_pick_sequence((True, "main"), (True, "main"), (False, None)),
            runner=runner,
            restart=True,
            worktree="main",
        )

        assert result == 0
        assert len(run_count) == 2

    def test_restart_confirmation_calls_confirm_restart_each_time(self):
        confirm_calls = []

        run_loop(
            ["claude"],
            _fake_pick_sequence((True, "main"), (False, None)),
            runner=lambda cmd: 0,
            restart_confirmation=True,
            worktree="main",
            confirm_restart=lambda: confirm_calls.append(True),
        )

        assert confirm_calls == [True]

    def test_progress_receives_restart_message(self):
        messages = []

        run_loop(
            ["claude"],
            _fake_pick_sequence((True, "main"), (False, None)),
            runner=lambda cmd: 0,
            restart=True,
            worktree="main",
            restart_message="custom restart message",
            progress=messages.append,
        )

        assert any("custom restart message" in m for m in messages)

    def test_keyboard_interrupt_returns_0_and_reports_stopped(self):
        messages = []

        def runner(cmd):
            raise KeyboardInterrupt

        result = run_loop(
            ["claude"],
            _fake_pick_sequence((True, "main")),
            runner=runner,
            restart=True,
            worktree="main",
            progress=messages.append,
        )

        assert result == 0
        assert any("Stopped" in m for m in messages)

    def test_worktrees_disabled_does_not_force_interactive(self):
        seen_worktree = []

        def pick(worktree, last_selected_branch=None, **kwargs):
            seen_worktree.append(worktree)
            return False, None

        run_loop(
            ["claude"],
            pick,
            runner=lambda cmd: 0,
            restart=True,
            worktree=None,
            worktrees_enabled=False,
        )

        assert seen_worktree == [None]


class _FakeRT:
    agent = None
    workdir = None
    workdir_extras_override = None

    def build_child_env(self):
        return {}
