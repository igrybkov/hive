"""Configuration file discovery and loading."""

from __future__ import annotations

import os
import subprocess
from importlib import resources
from pathlib import Path
from typing import Any

import yaml

# Config file names
CONFIG_FILE = ".hive.yml"
LOCAL_CONFIG_FILE = ".hive.local.yml"

# Global config directory and file names
GLOBAL_CONFIG_DIR = "hive"
GLOBAL_CONFIG_FILES = ["hive.yml", "hive.yaml"]


def find_git_root() -> Path | None:
    """Find the git repository root.

    Returns:
        Path to git root, or None if not in a git repository.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        )
        return Path(result.stdout.strip()).resolve()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def get_xdg_config_home() -> Path:
    """Get the XDG config home directory.

    Returns:
        Path to XDG_CONFIG_HOME, or ~/.config if not set.
    """
    xdg_config = os.environ.get("XDG_CONFIG_HOME")
    if xdg_config:
        return Path(xdg_config)
    return Path.home() / ".config"


def find_global_config() -> Path | None:
    """Find the global user configuration file.

    Searches for hive.yml or hive.yaml in $XDG_CONFIG_HOME/hive/.

    Returns:
        Path to global config file if found, None otherwise.
    """
    config_dir = get_xdg_config_home() / GLOBAL_CONFIG_DIR

    for filename in GLOBAL_CONFIG_FILES:
        path = config_dir / filename
        if path.exists():
            return path

    return None


def find_config_files(git_root: Path | None = None) -> list[Path]:
    """Find configuration files in order of precedence.

    Files are returned in load order (lowest to highest precedence):
    1. $XDG_CONFIG_HOME/hive/hive.yml (global user config)
    2. .hive.yml (version-controlled project config)
    3. .hive.local.yml (git-ignored local overrides)

    Args:
        git_root: Git repository root. If None, auto-detected.

    Returns:
        List of config file paths that exist.
    """
    files: list[Path] = []

    # Global config (lowest precedence)
    global_config = find_global_config()
    if global_config:
        files.append(global_config)

    # Project config files
    if git_root is None:
        git_root = find_git_root()

    if git_root is not None:
        for filename in [CONFIG_FILE, LOCAL_CONFIG_FILE]:
            path = git_root / filename
            if path.exists():
                files.append(path)

    return files


def load_yaml_file(path: Path) -> dict[str, Any]:
    """Load a YAML configuration file.

    Args:
        path: Path to the YAML file.

    Returns:
        Parsed YAML content as a dictionary.
    """
    with open(path) as f:
        content = yaml.safe_load(f)
        return content if content else {}


def load_default_config() -> dict[str, Any]:
    """Load the default configuration shipped with the package.

    Returns:
        Default configuration as a dictionary.
    """
    # Use importlib.resources to load the default config
    # This works whether installed as package or running from source
    try:
        # Python 3.9+ style
        config_pkg = resources.files("hive_cli.config")
        default_file = config_pkg.joinpath("default.yml")
        content = default_file.read_text()
        return yaml.safe_load(content) or {}
    except (TypeError, AttributeError):
        # Fallback for older Python or edge cases
        import hive_cli.config as config_module

        config_dir = Path(config_module.__file__).parent
        default_path = config_dir / "default.yml"
        return load_yaml_file(default_path)
