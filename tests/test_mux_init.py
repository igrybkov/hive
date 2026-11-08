"""get_mux() backend-selection matrix: explicit override > HIVE_MUX_BACKEND
env var > get_settings().mux.backend ("auto" default) > environment
(ZELLIJ/TMUX). Every test clears both ZELLIJ and TMUX first since this
sandbox's own Bash tool runs inside a live Zellij session.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from hive_cli.mux import get_mux
from hive_cli.mux.tmux.backend import TmuxMux
from hive_cli.mux.zellij.backend import ZellijMux


@pytest.fixture(autouse=True)
def _no_multiplexer_env(monkeypatch):
    monkeypatch.delenv("ZELLIJ", raising=False)
    monkeypatch.delenv("TMUX", raising=False)
    monkeypatch.delenv("HIVE_MUX_BACKEND", raising=False)


def _stub_settings(backend: str):
    return SimpleNamespace(mux=SimpleNamespace(backend=backend))


def test_no_multiplexer_and_auto_config_returns_none(monkeypatch):
    monkeypatch.setattr("hive_cli.mux.get_settings", lambda: _stub_settings("auto"))
    assert get_mux() is None


def test_config_tmux_returns_tmux_mux(monkeypatch):
    monkeypatch.setattr("hive_cli.mux.get_settings", lambda: _stub_settings("tmux"))
    assert isinstance(get_mux(), TmuxMux)


def test_config_zellij_returns_zellij_mux(monkeypatch):
    monkeypatch.setattr("hive_cli.mux.get_settings", lambda: _stub_settings("zellij"))
    assert isinstance(get_mux(), ZellijMux)


def test_auto_with_tmux_env_returns_tmux_mux(monkeypatch):
    monkeypatch.setattr("hive_cli.mux.get_settings", lambda: _stub_settings("auto"))
    monkeypatch.setenv("TMUX", "/tmp/tmux-1/hive,1,0")
    assert isinstance(get_mux(), TmuxMux)


def test_auto_with_zellij_env_returns_zellij_mux(monkeypatch):
    monkeypatch.setattr("hive_cli.mux.get_settings", lambda: _stub_settings("auto"))
    monkeypatch.setenv("ZELLIJ", "0")
    assert isinstance(get_mux(), ZellijMux)


def test_both_env_set_and_config_zellij_forces_zellij(monkeypatch):
    monkeypatch.setattr("hive_cli.mux.get_settings", lambda: _stub_settings("zellij"))
    monkeypatch.setenv("ZELLIJ", "0")
    monkeypatch.setenv("TMUX", "/tmp/tmux-1/hive,1,0")
    assert isinstance(get_mux(), ZellijMux)


def test_env_var_beats_config(monkeypatch):
    monkeypatch.setattr("hive_cli.mux.get_settings", lambda: _stub_settings("zellij"))
    monkeypatch.setenv("HIVE_MUX_BACKEND", "tmux")
    assert isinstance(get_mux(), TmuxMux)


def test_explicit_backend_beats_everything(monkeypatch):
    monkeypatch.setattr("hive_cli.mux.get_settings", lambda: _stub_settings("tmux"))
    monkeypatch.setenv("HIVE_MUX_BACKEND", "tmux")
    assert isinstance(get_mux("zellij"), ZellijMux)
