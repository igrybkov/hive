"""hive_cli.core.paths: XDG dirs, runtime dir, socket paths, layouts dir."""

from __future__ import annotations

import os


def test_xdg_config_home_env_and_default(monkeypatch, tmp_path):
    from hive_cli.core import paths

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    assert paths.xdg_config_home() == tmp_path / "cfg"

    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert paths.xdg_config_home() == tmp_path / ".config"


def test_runtime_dir_prefers_env_then_tmp(monkeypatch, short_tmp):
    from hive_cli.core import paths

    monkeypatch.setenv("XDG_RUNTIME_DIR", str(short_tmp))
    assert paths.runtime_dir() == short_tmp

    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    assert paths.runtime_dir() == paths.Path(f"/tmp/hive-{os.getuid()}")


def test_session_sock_dir_sanitizes(monkeypatch, short_tmp):
    from hive_cli.core import paths

    monkeypatch.setenv("XDG_RUNTIME_DIR", str(short_tmp))
    result = paths.session_sock_dir("my repo/x")
    assert result == paths.hive_runtime_dir() / "my_repo_x"


def test_pane_sock_path_is_short(monkeypatch):
    from hive_cli.core import paths

    monkeypatch.setenv("XDG_RUNTIME_DIR", "/tmp/hvabc")
    sock = paths.pane_sock("a" * 32, "12345")
    assert len(str(sock)) <= 100
    assert sock.name == "12345.sock"
