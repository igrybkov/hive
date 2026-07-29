"""Tests for agent detection."""

from __future__ import annotations

from unittest.mock import patch

from hive_cli.agents.detection import DetectedAgent, detect_agent, get_available_agents
from hive_cli.config import get_agent_order, reload_config


class TestGetAgentOrder:
    """Tests for get_agent_order function."""

    def test_default_order(self, tmp_path, monkeypatch):
        """Test default agent order when no config or env var is set."""
        # Set XDG to empty dir to avoid global config
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        monkeypatch.delenv("HIVE_AGENTS_ORDER", raising=False)

        with patch("hive_cli.config.loader.find_config_files", return_value=[]):
            reload_config()
            order = get_agent_order()
            assert order == ["claude", "gemini", "codex", "agent", "copilot"]

    def test_custom_order(self, tmp_path, monkeypatch):
        """Test custom agent order from env var."""
        # Set XDG to empty dir to avoid global config
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        monkeypatch.setenv("HIVE_AGENTS_ORDER", "copilot,claude,gemini")
        reload_config()
        order = get_agent_order()
        assert order == ["copilot", "claude", "gemini"]

    def test_order_from_config_file(self, tmp_path, monkeypatch):
        """Test custom agent order from config file."""
        # Create config file
        config_file = tmp_path / ".hive.yml"
        config_file.write_text("agents:\n  order: [codex, copilot]\n")

        # Set XDG to empty dir to avoid global config
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        monkeypatch.delenv("HIVE_AGENTS_ORDER", raising=False)

        reload_config()
        with patch(
            "hive_cli.config.loader.find_config_files", return_value=[config_file]
        ):
            reload_config()
            order = get_agent_order()
            assert order == ["codex", "copilot"]


class TestDetectAgent:
    """Tests for detect_agent function."""

    def test_detect_preferred_agent_available(self, monkeypatch):
        """Test detecting a preferred agent that is available."""
        with patch("shutil.which", return_value="/usr/bin/claude"):
            result = detect_agent(preferred="claude")
            assert result is not None
            assert result.name == "claude"
            assert result.command == "claude"

    def test_detect_preferred_agent_not_available(self, monkeypatch):
        """Test detecting a preferred agent that is not available."""
        with patch("shutil.which", return_value=None):
            result = detect_agent(preferred="nonexistent")
            assert result is None

    def test_auto_detect_first_available(self, tmp_path, monkeypatch):
        """Test auto-detection returns first available agent."""
        # Set XDG to empty dir to avoid global config
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        monkeypatch.setenv("HIVE_AGENTS_ORDER", "claude,gemini,copilot")
        reload_config()

        def mock_which(cmd):
            # claude not available, gemini is available
            return "/usr/bin/gemini" if cmd == "gemini" else None

        with patch("shutil.which", side_effect=mock_which):
            result = detect_agent()
            assert result is not None
            assert result.name == "gemini"
            assert result.command == "gemini"

    def test_auto_detect_none_available(self, tmp_path, monkeypatch):
        """Test auto-detection when no agents are available."""
        # Set XDG to empty dir to avoid global config
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        monkeypatch.setenv("HIVE_AGENTS_ORDER", "claude,gemini,copilot")
        reload_config()

        with patch("shutil.which", return_value=None):
            result = detect_agent()
            assert result is None


class TestGetAvailableAgents:
    """Tests for get_available_agents function."""

    def test_returns_available_agents(self, tmp_path, monkeypatch):
        """Test that only available agents are returned."""
        # Set XDG to empty dir to avoid global config
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        monkeypatch.setenv("HIVE_AGENTS_ORDER", "claude,gemini,copilot,codex")
        reload_config()

        def mock_which(cmd):
            return "/usr/bin/" + cmd if cmd in ["claude", "copilot"] else None

        with patch("shutil.which", side_effect=mock_which):
            available = get_available_agents()
            assert available == ["claude", "copilot"]

    def test_empty_when_none_available(self, tmp_path, monkeypatch):
        """Test that empty list is returned when no agents available."""
        # Set XDG to empty dir to avoid global config
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        monkeypatch.setenv("HIVE_AGENTS_ORDER", "claude,gemini")
        reload_config()

        with patch("shutil.which", return_value=None):
            available = get_available_agents()
            assert available == []


class TestDetectedAgent:
    """Tests for DetectedAgent dataclass."""

    def test_creation(self):
        """Test creating a DetectedAgent instance."""
        agent = DetectedAgent(name="claude", command="claude")
        assert agent.name == "claude"
        assert agent.command == "claude"

    def test_different_name_and_command(self):
        """Test agent with different name and command."""
        agent = DetectedAgent(name="cursor", command="agent")
        assert agent.name == "cursor"
        assert agent.command == "agent"
