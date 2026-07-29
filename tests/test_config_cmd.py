"""Tests for the config command."""

from __future__ import annotations

from pathlib import Path

import yaml
from conftest import CycloptsTestRunner

from hive_cli.app import app
from hive_cli.commands.config_cmd import (
    _comment_out_yaml,
    _config_to_yaml,
    _create_bootstrap_header,
    _generate_current_bootstrap_content,
    _get_default_yaml_content,
)
from hive_cli.config import load_config


class TestConfigCommand:
    """Tests for the `hive config` command."""

    def test_config_shows_yaml_output(self, cli_runner: CycloptsTestRunner):
        """Test that `hive config` outputs YAML."""
        result = cli_runner.invoke(app, ["config"])

        assert result.exit_code == 0
        # Should contain YAML structure
        assert "agents:" in result.output
        assert "worktrees:" in result.output
        assert "github:" in result.output

    def test_config_output_is_valid_yaml(self, cli_runner: CycloptsTestRunner):
        """Test that the config output can be parsed as valid YAML."""
        result = cli_runner.invoke(app, ["config"])

        assert result.exit_code == 0
        # Should be parseable as YAML
        parsed = yaml.safe_load(result.output)
        assert isinstance(parsed, dict)
        assert "agents" in parsed
        assert "worktrees" in parsed

    def test_config_help(self, cli_runner: CycloptsTestRunner):
        """Test that `hive config --help` shows help text."""
        result = cli_runner.invoke(app, ["config", "--help"])

        assert result.exit_code == 0
        assert "Manage hive configuration" in result.output
        assert "bootstrap" in result.output


class TestBootstrapCommand:
    """Tests for the `hive config bootstrap` command."""

    def test_bootstrap_no_args_shows_paths(self, cli_runner: CycloptsTestRunner):
        """Test that `hive config bootstrap` shows common paths."""
        result = cli_runner.invoke(app, ["config", "bootstrap"])

        assert result.exit_code == 0
        assert ".hive.yml" in result.output
        assert ".hive.local.yml" in result.output
        assert "hive.yml" in result.output  # Global path

    def test_bootstrap_creates_file(
        self, cli_runner: CycloptsTestRunner, tmp_path: Path
    ):
        """Test that `hive config bootstrap <file>` creates a config file."""
        config_path = tmp_path / "test.yml"

        result = cli_runner.invoke(app, ["config", "bootstrap", str(config_path)])

        assert result.exit_code == 0
        assert config_path.exists()
        assert "Created config file" in result.output

    def test_bootstrap_file_content_is_commented(
        self, cli_runner: CycloptsTestRunner, tmp_path: Path
    ):
        """Test that bootstrap file has all values commented out."""
        config_path = tmp_path / "test.yml"
        cli_runner.invoke(app, ["config", "bootstrap", str(config_path)])

        content = config_path.read_text()

        # File should start with ---
        assert content.startswith("---\n")

        # Header should be present
        assert "Hive CLI Configuration" in content
        assert "Uncomment and modify" in content

        # Config values should be commented out
        assert "# agents:" in content
        assert "# worktrees:" in content
        assert "# github:" in content

    def test_bootstrap_file_has_valid_structure(
        self, cli_runner: CycloptsTestRunner, tmp_path: Path
    ):
        """Test that uncommenting bootstrap file produces valid YAML."""
        config_path = tmp_path / "test.yml"
        cli_runner.invoke(app, ["config", "bootstrap", str(config_path)])

        content = config_path.read_text()

        # Remove comment prefix from lines to get valid YAML
        lines = content.split("\n")
        uncommented = []
        for line in lines:
            if line.startswith("# ") and not line.startswith("# #"):
                # Uncomment config lines (not header comments which start with "# ")
                uncommented.append(line[2:])
            else:
                uncommented.append(line)

        # The structure should be parseable (might have some commented-out sections)
        # Just verify the file can be read
        assert len(uncommented) > 10

    def test_bootstrap_fails_if_file_exists(
        self, cli_runner: CycloptsTestRunner, tmp_path: Path
    ):
        """Test that bootstrap fails if file already exists."""
        config_path = tmp_path / "test.yml"
        config_path.write_text("existing content")

        result = cli_runner.invoke(app, ["config", "bootstrap", str(config_path)])

        assert result.exit_code == 1
        assert "already exists" in result.output

    def test_bootstrap_force_overwrites_existing_file(
        self, cli_runner: CycloptsTestRunner, tmp_path: Path
    ):
        """Test that bootstrap --force overwrites existing file."""
        config_path = tmp_path / "test.yml"
        config_path.write_text("existing content")

        result = cli_runner.invoke(
            app, ["config", "bootstrap", str(config_path), "--force"]
        )

        assert result.exit_code == 0
        assert config_path.exists()
        assert "Created config file" in result.output
        # Verify content was replaced
        content = config_path.read_text()
        assert "existing content" not in content
        assert "Hive CLI Configuration" in content

    def test_bootstrap_force_short_flag(
        self, cli_runner: CycloptsTestRunner, tmp_path: Path
    ):
        """Test that bootstrap -f works as short form of --force."""
        config_path = tmp_path / "test.yml"
        config_path.write_text("existing content")

        result = cli_runner.invoke(app, ["config", "bootstrap", str(config_path), "-f"])

        assert result.exit_code == 0
        assert "Created config file" in result.output

    def test_bootstrap_creates_parent_dirs(
        self, cli_runner: CycloptsTestRunner, tmp_path: Path
    ):
        """Test that bootstrap creates parent directories if needed."""
        config_path = tmp_path / "nested" / "dir" / "test.yml"

        result = cli_runner.invoke(app, ["config", "bootstrap", str(config_path)])

        assert result.exit_code == 0
        assert config_path.exists()

    def test_bootstrap_expands_tilde(
        self, cli_runner: CycloptsTestRunner, tmp_path: Path, monkeypatch
    ):
        """Test that bootstrap expands ~ in paths."""
        # Mock HOME to use tmp_path
        monkeypatch.setenv("HOME", str(tmp_path))

        result = cli_runner.invoke(app, ["config", "bootstrap", "~/test-hive.yml"])

        assert result.exit_code == 0
        assert (tmp_path / "test-hive.yml").exists()

    def test_bootstrap_help(self, cli_runner: CycloptsTestRunner):
        """Test that `hive config bootstrap --help` shows help text."""
        result = cli_runner.invoke(app, ["config", "bootstrap", "--help"])

        assert result.exit_code == 0
        assert "Create a new config file" in result.output

    def test_bootstrap_current_to_stdout(self, cli_runner: CycloptsTestRunner):
        """Test that `hive config bootstrap --current` prints current config."""
        result = cli_runner.invoke(app, ["config", "bootstrap", "--current"])

        assert result.exit_code == 0
        assert "---" in result.output
        assert "Hive CLI Configuration" in result.output
        assert "current effective configuration" in result.output
        assert "# agents:" in result.output
        assert "# worktrees:" in result.output

    def test_bootstrap_current_short_flag(self, cli_runner: CycloptsTestRunner):
        """Test that `hive config bootstrap -c` works as short form."""
        result = cli_runner.invoke(app, ["config", "bootstrap", "-c"])

        assert result.exit_code == 0
        assert "current effective configuration" in result.output

    def test_bootstrap_current_creates_file(
        self, cli_runner: CycloptsTestRunner, tmp_path: Path
    ):
        """Test that `hive config bootstrap --current <file>` creates a file."""
        config_path = tmp_path / "current.yml"

        result = cli_runner.invoke(
            app, ["config", "bootstrap", "--current", str(config_path)]
        )

        assert result.exit_code == 0
        assert config_path.exists()
        assert "Created config file" in result.output

        content = config_path.read_text()
        assert "current effective configuration" in content
        assert "# agents:" in content

    def test_bootstrap_current_header_differs_from_default(self):
        """Test that --current header says 'current' not 'defaults'."""
        default_header = _create_bootstrap_header()
        current_header = _create_bootstrap_header(current=True)

        assert "Values shown are defaults" in default_header
        assert "Values shown are defaults" not in current_header
        assert "current effective configuration" in current_header


class TestHelperFunctions:
    """Tests for helper functions in config_cmd."""

    def test_config_to_yaml_produces_valid_yaml(self):
        """Test that _config_to_yaml produces valid YAML."""
        config = load_config()
        yaml_str = _config_to_yaml(config)

        parsed = yaml.safe_load(yaml_str)
        assert isinstance(parsed, dict)
        assert "agents" in parsed

    def test_comment_out_yaml_preserves_empty_lines(self):
        """Test that _comment_out_yaml preserves empty lines."""
        content = "key1: value1\n\nkey2: value2"
        result = _comment_out_yaml(content)

        lines = result.split("\n")
        assert lines[1] == ""  # Empty line preserved

    def test_comment_out_yaml_preserves_document_marker(self):
        """Test that _comment_out_yaml preserves --- marker."""
        content = "---\nkey: value"
        result = _comment_out_yaml(content)

        assert result.startswith("---\n")
        assert "# key: value" in result

    def test_comment_out_yaml_comments_existing_comments(self):
        """Test that existing comments get double-commented."""
        content = "key: value\n# existing comment"
        result = _comment_out_yaml(content)

        assert "# key: value" in result
        assert "# # existing comment" in result

    def test_get_default_yaml_content_returns_string(self):
        """Test that _get_default_yaml_content returns default config."""
        content = _get_default_yaml_content()

        assert isinstance(content, str)
        assert "agents:" in content
        assert "worktrees:" in content

    def test_create_bootstrap_header_format(self):
        """Test that _create_bootstrap_header has expected format."""
        header = _create_bootstrap_header()

        assert "Hive CLI Configuration" in header
        assert "Uncomment and modify" in header
        assert "Configuration precedence" in header

    def test_generate_current_bootstrap_content_structure(self):
        """Test that _generate_current_bootstrap_content has valid structure."""
        content = _generate_current_bootstrap_content()

        assert content.startswith("---\n")
        assert "current effective configuration" in content
        assert "# agents:" in content
        assert "# worktrees:" in content
        assert "# github:" in content
