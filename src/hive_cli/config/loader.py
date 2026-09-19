"""Configuration file discovery and loading."""

from __future__ import annotations

from importlib import resources
from pathlib import Path
from typing import Any

import yaml

from ..core import paths

# Config file names
CONFIG_FILE = ".hive.yml"
LOCAL_CONFIG_FILE = ".hive.local.yml"

# Global config directory and file names
GLOBAL_CONFIG_DIR = "hive"
GLOBAL_CONFIG_FILES = ["hive.yml", "hive.yaml"]


def find_project_root(start: Path | None = None) -> Path | None:
    """Find the project root by walking up from ``start`` to the nearest `.git`.

    No subprocess spawn: `.git` is a directory in the main repo and a *file*
    (gitdir pointer) inside a linked worktree — either one marks the root.

    Args:
        start: Directory to start the walk from. Defaults to the cwd.

    Returns:
        Path to the project root, or None if no `.git` is found above start.
    """
    current = (start or Path.cwd()).resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def find_global_config() -> Path | None:
    """Find the global user configuration file.

    Searches for hive.yml or hive.yaml in $XDG_CONFIG_HOME/hive/.

    Returns:
        Path to global config file if found, None otherwise.
    """
    config_dir = paths.xdg_config_home() / GLOBAL_CONFIG_DIR

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
        git_root: Project root. If None, auto-detected (walk-up, no spawn).

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
        git_root = find_project_root()

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
