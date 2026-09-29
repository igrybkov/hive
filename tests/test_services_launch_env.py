"""Tests for services/launch_env.py: the env refresh applied at every agent launch."""

from __future__ import annotations

import json

import pytest

from hive_cli.config.schema import EnvConfig
from hive_cli.services import launch_env


@pytest.fixture
def no_direnv(monkeypatch):
    monkeypatch.setattr(launch_env.shutil, "which", lambda _name: None)


@pytest.fixture
def has_direnv(monkeypatch):
    monkeypatch.setattr(
        launch_env.shutil,
        "which",
        lambda name: "/usr/bin/direnv" if name == "direnv" else None,
    )


def _env0(pairs: dict[str, str]) -> str:
    return "".join(f"{k}={v}\0" for k, v in pairs.items())


# ---------------------------------------------------------------------------
# parse_env0
# ---------------------------------------------------------------------------


class TestParseEnv0:
    def test_values_may_hold_newlines_and_equals(self):
        text = "A=1\0B=x=y\0C=line1\nline2\0"
        assert launch_env.parse_env0(text) == {
            "A": "1",
            "B": "x=y",
            "C": "line1\nline2",
        }

    def test_noise_without_equals_is_skipped(self):
        assert launch_env.parse_env0("welcome to fish\nA=1\0") == {}
        assert launch_env.parse_env0("junk\0A=1\0") == {"A": "1"}

    def test_empty(self):
        assert launch_env.parse_env0("") == {}


# ---------------------------------------------------------------------------
# refresh_from_shell
# ---------------------------------------------------------------------------


class TestShellRefresh:
    def test_off_by_default_spawns_nothing(self, fake_proc, no_direnv, tmp_path):
        base = {"TOKEN": "old"}
        assert launch_env.refresh(base, cwd=tmp_path, config=EnvConfig()) == base
        assert fake_proc.calls == []

    def test_fresh_value_overrides_inherited(self, fake_proc, no_direnv, tmp_path):
        fake_proc.script(["/bin/fish"], stdout=_env0({"TOKEN": "new", "NEW": "1"}))
        base = {"TOKEN": "old", "KEEP": "k", "SHELL": "/bin/fish"}
        env = launch_env.refresh(
            base,
            cwd=tmp_path,
            config=EnvConfig(refresh_from_shell=True, project="off"),
        )
        assert env == {"TOKEN": "new", "NEW": "1", "KEEP": "k", "SHELL": "/bin/fish"}
        assert fake_proc.calls == [["/bin/fish", "-l", "-c", "env -0"]]

    def test_shell_runs_with_a_minimal_env(self, monkeypatch, no_direnv, tmp_path):
        """Inherited stale values must not reach the shell: fish globals shadow
        universals, and `export X=${X:-...}` keeps an inherited X."""
        from hive_cli.core import proc

        seen = {}

        def fake_run(argv, **kwargs):
            seen.update(kwargs)
            return proc.Result(tuple(argv), 0, "", "")

        monkeypatch.setattr(launch_env.proc, "run", fake_run)
        base = {
            "TOKEN": "old",
            "HOME": "/h",
            "USER": "u",
            "SHELL": "/bin/fish",
            "ZELLIJ_SESSION_NAME": "s",
        }
        launch_env.refresh(
            base,
            cwd=tmp_path,
            config=EnvConfig(refresh_from_shell=True, project="off", timeout=2),
        )
        assert seen["env"] == {
            "HOME": "/h",
            "USER": "u",
            "SHELL": "/bin/fish",
            "PATH": launch_env.MINIMAL_PATH,
        }
        assert seen["timeout"] == 2
        assert seen["input"] == ""  # stdin is a pipe, never the pane's tty

    def test_session_keys_are_protected(self, fake_proc, no_direnv, tmp_path):
        fresh = {
            "ZELLIJ_PANE_ID": "99",
            "HIVE_AGENT": "codex",
            "TMUX": "x",
            "PATH": "/usr/bin",
            "TERM": "dumb",
            "PWD": "/",
            "SHLVL": "1",
            "_": "/usr/bin/env",
            "__MISE_DIFF": "x",
            "TOKEN": "new",
        }
        fake_proc.script(["/bin/fish"], stdout=_env0(fresh))
        base = {
            "SHELL": "/bin/fish",
            "ZELLIJ_PANE_ID": "3",
            "HIVE_AGENT": "claude",
            "PATH": "/venv/bin:/usr/bin",
            "TERM": "xterm-256color",
        }
        env = launch_env.refresh(
            base,
            cwd=tmp_path,
            config=EnvConfig(refresh_from_shell=True, project="off"),
        )
        assert env == {**base, "TOKEN": "new"}

    def test_custom_shell_command(self, fake_proc, no_direnv, tmp_path):
        fake_proc.script(["zsh"], stdout=_env0({"A": "1"}))
        env = launch_env.refresh(
            {},
            cwd=tmp_path,
            config=EnvConfig(
                refresh_from_shell=True,
                shell_command=["zsh", "-l", "-i", "-c", "env -0"],
                project="off",
            ),
        )
        assert env == {"A": "1"}
        assert fake_proc.calls == [["zsh", "-l", "-i", "-c", "env -0"]]

    def test_failed_shell_keeps_inherited_env(self, fake_proc, no_direnv, tmp_path):
        fake_proc.script(["/bin/fish"], stdout=_env0({"TOKEN": "x"}), returncode=1)
        base = {"TOKEN": "old", "SHELL": "/bin/fish"}
        env = launch_env.refresh(
            base,
            cwd=tmp_path,
            config=EnvConfig(refresh_from_shell=True, project="off"),
        )
        assert env == base

    def test_no_shell_known_skips(self, fake_proc, no_direnv, tmp_path):
        env = launch_env.refresh(
            {"TOKEN": "old"},
            cwd=tmp_path,
            config=EnvConfig(refresh_from_shell=True, project="off"),
        )
        assert env == {"TOKEN": "old"}
        assert fake_proc.calls == []


# ---------------------------------------------------------------------------
# project env: direnv / .env
# ---------------------------------------------------------------------------


class TestProjectEnv:
    def test_auto_without_direnv_reads_dotenv(self, fake_proc, no_direnv, tmp_path):
        (tmp_path / ".env").write_text("TOKEN=from-file\nexport OTHER='q v'\n")
        env = launch_env.refresh({"TOKEN": "old"}, cwd=tmp_path, config=EnvConfig())
        assert env == {"TOKEN": "from-file", "OTHER": "q v"}
        assert fake_proc.calls == []

    def test_auto_without_env_files_is_a_noop(self, fake_proc, no_direnv, tmp_path):
        assert launch_env.refresh({"A": "1"}, cwd=tmp_path, config=EnvConfig()) == {
            "A": "1"
        }

    def test_auto_with_direnv_replaces_dotenv(self, fake_proc, has_direnv, tmp_path):
        """With direnv installed, .env is direnv's business (dotenv in .envrc)."""
        (tmp_path / ".env").write_text("FROM_DOTENV=1\n")
        (tmp_path / ".envrc").write_text("export TOKEN=x\n")
        fake_proc.script(
            ["direnv", "export", "json"],
            stdout=json.dumps({"TOKEN": "fresh", "GONE": None}),
        )
        env = launch_env.refresh(
            {"TOKEN": "old", "GONE": "stale"}, cwd=tmp_path, config=EnvConfig()
        )
        assert env == {"TOKEN": "fresh"}
        assert fake_proc.calls == [["direnv", "export", "json"]]

    def test_direnv_skipped_without_envrc(self, fake_proc, has_direnv, tmp_path):
        """No .envrc up the tree: no spawn, and no .env fallback either."""
        (tmp_path / ".env").write_text("FROM_DOTENV=1\n")
        env = launch_env.refresh({}, cwd=tmp_path, config=EnvConfig())
        assert env == {}
        assert fake_proc.calls == []

    def test_direnv_finds_envrc_in_a_parent(self, fake_proc, has_direnv, tmp_path):
        (tmp_path / ".envrc").write_text("export TOKEN=x\n")
        sub = tmp_path / "a" / "b"
        sub.mkdir(parents=True)
        fake_proc.script(["direnv"], stdout=json.dumps({"TOKEN": "fresh"}))
        env = launch_env.refresh({}, cwd=sub, config=EnvConfig())
        assert env == {"TOKEN": "fresh"}

    def test_direnv_forgets_its_cached_state(self, monkeypatch, has_direnv, tmp_path):
        """Inherited DIRENV_* would make direnv think the .envrc is loaded and
        print nothing; dropping them forces a fresh evaluation."""
        from hive_cli.core import proc

        (tmp_path / ".envrc").write_text("")
        seen = {}

        def fake_run(argv, **kwargs):
            seen.update(kwargs)
            return proc.Result(tuple(argv), 0, "", "")

        monkeypatch.setattr(launch_env.proc, "run", fake_run)
        base = {"A": "1", "DIRENV_DIFF": "x", "DIRENV_WATCHES": "y", "DIRENV_DIR": "-/"}
        launch_env.refresh(base, cwd=tmp_path, config=EnvConfig())
        assert seen["env"] == {"A": "1"}
        assert seen["cwd"] == tmp_path

    def test_blocked_envrc_changes_nothing(self, fake_proc, has_direnv, tmp_path):
        (tmp_path / ".envrc").write_text("")
        fake_proc.script(
            ["direnv"], stderr="direnv: error .envrc is blocked", returncode=1
        )
        assert launch_env.refresh({"A": "1"}, cwd=tmp_path, config=EnvConfig()) == {
            "A": "1"
        }

    def test_bad_direnv_json_changes_nothing(self, fake_proc, has_direnv, tmp_path):
        (tmp_path / ".envrc").write_text("")
        fake_proc.script(["direnv"], stdout="not json")
        assert launch_env.refresh({"A": "1"}, cwd=tmp_path, config=EnvConfig()) == {
            "A": "1"
        }

    def test_forced_dotenv_ignores_direnv(self, fake_proc, has_direnv, tmp_path):
        (tmp_path / ".env").write_text("A=2\n")
        (tmp_path / ".envrc").write_text("")
        env = launch_env.refresh(
            {"A": "1"}, cwd=tmp_path, config=EnvConfig(project="dotenv")
        )
        assert env == {"A": "2"}
        assert fake_proc.calls == []

    def test_off(self, fake_proc, has_direnv, tmp_path):
        (tmp_path / ".env").write_text("A=2\n")
        (tmp_path / ".envrc").write_text("")
        env = launch_env.refresh(
            {"A": "1"}, cwd=tmp_path, config=EnvConfig(project="off")
        )
        assert env == {"A": "1"}
        assert fake_proc.calls == []

    def test_project_env_applies_on_top_of_shell(self, fake_proc, no_direnv, tmp_path):
        (tmp_path / ".env").write_text("TOKEN=project\n")
        fake_proc.script(["/bin/fish"], stdout=_env0({"TOKEN": "shell", "B": "2"}))
        env = launch_env.refresh(
            {"SHELL": "/bin/fish"},
            cwd=tmp_path,
            config=EnvConfig(refresh_from_shell=True),
        )
        assert env == {"SHELL": "/bin/fish", "TOKEN": "project", "B": "2"}
