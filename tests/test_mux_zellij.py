"""Tests for hive_cli.mux.zellij.backend and hive_cli.state.legacy_files.

Regression: rename-pane defaults to the focused pane, so we must pass
--pane-id explicitly with $ZELLIJ_PANE_ID to target our own pane.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from hive_cli.mux.zellij import backend
from hive_cli.state import legacy_files


class TestRenamePane:
    def test_rename_pane_targets_current_pane(self, monkeypatch, fake_proc):
        monkeypatch.setenv("ZELLIJ", "0")
        monkeypatch.setenv("ZELLIJ_PANE_ID", "7")

        backend.rename_pane("new title")

        assert fake_proc.count("zellij", "action", "rename-pane") == 1
        cmd = fake_proc.calls[0]
        assert cmd[:3] == ["zellij", "action", "rename-pane"]
        assert "--pane-id" in cmd
        assert cmd[cmd.index("--pane-id") + 1] == "7"
        assert cmd[-1] == "new title"

    def test_rename_pane_noop_outside_zellij(self, monkeypatch, fake_proc):
        monkeypatch.delenv("ZELLIJ", raising=False)

        backend.rename_pane("ignored")

        assert fake_proc.calls == []

    def test_append_to_pane_title_targets_current_pane(self, monkeypatch, fake_proc):
        monkeypatch.setenv("ZELLIJ", "0")
        monkeypatch.setenv("ZELLIJ_PANE_ID", "12")

        assert backend.append_to_pane_title("suffix") is True

        cmd = fake_proc.calls[0]
        assert "--pane-id" in cmd
        assert cmd[cmd.index("--pane-id") + 1] == "12"
        assert cmd[-1] == " suffix"

    def test_append_to_pane_title_blank_is_noop(self, monkeypatch, fake_proc):
        monkeypatch.setenv("ZELLIJ", "0")
        monkeypatch.setenv("ZELLIJ_PANE_ID", "12")

        assert backend.append_to_pane_title("   ") is False
        assert fake_proc.calls == []


class TestLegacyFiles:
    def test_read_state_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr(legacy_files, "_STATE_ROOT", tmp_path)

        assert legacy_files.read_state("my-session", "5") == {
            "status": None,
            "branch": None,
            "custom_title": None,
        }

    def test_state_path_creates_parent(self, tmp_path, monkeypatch):
        monkeypatch.setattr(legacy_files, "_STATE_ROOT", tmp_path)

        path = legacy_files.state_path("my-session", "5")

        assert path.parent.is_dir()
        assert str(path).endswith("my-session/5.json")

    def test_read_write_round_trip(self, tmp_path, monkeypatch):
        monkeypatch.setattr(legacy_files, "_STATE_ROOT", tmp_path)
        state = {"status": "[working]", "branch": "feature-x", "custom_title": "Test"}

        legacy_files.write_state("s", "1", state)

        assert legacy_files.read_state("s", "1") == state


class TestPaneStateManagement:
    """Integration of the is_running_in_zellij gate, state, and title rebuild."""

    @pytest.fixture
    def zellij_env(self, monkeypatch, tmp_path):
        monkeypatch.setenv("ZELLIJ", "0")
        monkeypatch.setenv("ZELLIJ_SESSION_NAME", "test-session")
        monkeypatch.setenv("ZELLIJ_PANE_ID", "42")
        monkeypatch.setenv("HIVE_AGENT", "claude")
        monkeypatch.setenv("HIVE_PANE_ID", "1")
        monkeypatch.setenv("HIVE_PANE_LABEL", "Anton")
        monkeypatch.setattr(legacy_files, "_STATE_ROOT", tmp_path)

    def test_rebuild_pane_title_not_in_zellij(self, monkeypatch):
        monkeypatch.delenv("ZELLIJ", raising=False)

        assert backend.rebuild_pane_title() is False

    def test_rebuild_pane_title_minimal(self, zellij_env):
        with patch.object(backend, "rename_pane") as mock_rename:
            result = backend.rebuild_pane_title()
            assert result is True
            mock_rename.assert_called_once_with("c1: Anton [claude]")

    def test_rebuild_pane_title_fallback_to_cwd(self, monkeypatch, tmp_path):
        monkeypatch.setenv("ZELLIJ", "0")
        monkeypatch.setenv("ZELLIJ_SESSION_NAME", "test-fallback")
        monkeypatch.setenv("ZELLIJ_PANE_ID", "99")
        monkeypatch.delenv("HIVE_AGENT", raising=False)
        monkeypatch.delenv("HIVE_PANE_ID", raising=False)
        monkeypatch.setattr(legacy_files, "_STATE_ROOT", tmp_path)

        test_dir = tmp_path / "my-project"
        test_dir.mkdir()
        monkeypatch.chdir(test_dir)

        with patch.object(backend, "rename_pane") as mock_rename:
            result = backend.rebuild_pane_title()
            assert result is True
            mock_rename.assert_called_once_with(str(test_dir))

    def test_rebuild_pane_title_with_status(self, zellij_env, monkeypatch):
        legacy_files.write_state(
            "test-session",
            "42",
            {"status": "[working]", "branch": None, "custom_title": None},
        )

        with patch.object(backend, "rename_pane") as mock_rename:
            backend.rebuild_pane_title()
            mock_rename.assert_called_once_with("c1: Anton [claude] [working]")

    def test_set_pane_status(self, zellij_env):
        with patch.object(backend, "rename_pane"):
            result = backend.set_pane_status("[working]")
            assert result is True

        state = legacy_files.read_state("test-session", "42")
        assert state["status"] == "[working]"

    def test_set_pane_status_clear(self, zellij_env):
        legacy_files.write_state(
            "test-session",
            "42",
            {"status": "[working]", "branch": None, "custom_title": None},
        )

        with patch.object(backend, "rename_pane"):
            backend.set_pane_status(None)

        state = legacy_files.read_state("test-session", "42")
        assert state["status"] is None

    def test_set_pane_branch(self, zellij_env):
        with patch.object(backend, "rename_pane"):
            result = backend.set_pane_branch("feature-x")
            assert result is True

        state = legacy_files.read_state("test-session", "42")
        assert state["branch"] == "feature-x"

    def test_set_pane_custom_title(self, zellij_env):
        with patch.object(backend, "rename_pane"):
            result = backend.set_pane_custom_title("My task")
            assert result is True

        state = legacy_files.read_state("test-session", "42")
        assert state["custom_title"] == "My task"

    def test_set_pane_custom_title_replaces(self, zellij_env):
        legacy_files.write_state(
            "test-session",
            "42",
            {"status": None, "branch": None, "custom_title": "Old title"},
        )

        with patch.object(backend, "rename_pane"):
            backend.set_pane_custom_title("New title")

        state = legacy_files.read_state("test-session", "42")
        assert state["custom_title"] == "New title"
