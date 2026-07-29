"""Config command - manage hive configuration."""

from __future__ import annotations

import re
import sys
from importlib import resources
from pathlib import Path
from typing import Annotated

import yaml
from cyclopts import App, Parameter
from rich.console import Console
from rich.syntax import Syntax
from rich.table import Table

from ..config import (
    CONFIG_FILE,
    GLOBAL_CONFIG_DIR,
    LOCAL_CONFIG_FILE,
    get_xdg_config_home,
    load_config,
)
from ..utils import error, info, success

console = Console()


def _config_to_yaml(config) -> str:
    """Convert HiveConfig to YAML string.

    Args:
        config: HiveConfig instance.

    Returns:
        YAML string representation.
    """
    # Use model_dump() to get dict, then convert to YAML
    data = config.model_dump(mode="json")
    return yaml.dump(
        data, default_flow_style=False, sort_keys=False, allow_unicode=True
    )


def show_active_config() -> None:
    """Print the current merged configuration as YAML."""
    config = load_config()
    yaml_output = _config_to_yaml(config)

    # Use rich Syntax for colored output
    syntax = Syntax(yaml_output, "yaml", theme="monokai", line_numbers=False)
    console.print(syntax)


def show_common_paths() -> None:
    """Display common configuration paths."""
    xdg_config = get_xdg_config_home()
    global_path = xdg_config / GLOBAL_CONFIG_DIR / "hive.yml"

    console.print()
    console.print("[bold]Common configuration paths:[/]")
    console.print()

    table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
    table.add_column("Location", style="cyan")
    table.add_column("Path")
    table.add_column("Description", style="dim")

    table.add_row(
        "Project (versioned)",
        CONFIG_FILE,
        "Version-controlled project config",
    )
    table.add_row(
        "Project (local)",
        LOCAL_CONFIG_FILE,
        "Git-ignored local overrides",
    )
    table.add_row(
        "Global",
        str(global_path),
        "User-wide configuration",
    )

    console.print(table)
    console.print()
    console.print("[bold]Usage:[/]")
    console.print(f"  hive config bootstrap {CONFIG_FILE}")
    console.print(f"  hive config bootstrap {LOCAL_CONFIG_FILE}")
    console.print(f"  hive config bootstrap {global_path}")
    console.print()


def _get_default_yaml_content() -> str:
    """Read the default.yml content from the package.

    Returns:
        Contents of default.yml as a string.
    """
    try:
        # Python 3.9+ style
        config_pkg = resources.files("hive_cli.config")
        default_file = config_pkg.joinpath("default.yml")
        return default_file.read_text()
    except (TypeError, AttributeError):
        # Fallback for older Python or edge cases
        import hive_cli.config as config_module

        config_dir = Path(config_module.__file__).parent
        default_path = config_dir / "default.yml"
        return default_path.read_text()


def _comment_out_yaml(content: str) -> str:
    """Comment out all lines in YAML content for bootstrap file.

    Preserves:
    - Empty/whitespace-only lines
    - The YAML document start marker (---)

    Comments out everything else, including existing comments, so that
    when a user uncomments a section, the inline documentation comes with it.

    Args:
        content: YAML content string.

    Returns:
        YAML content with all values commented out.
    """
    lines = content.split("\n")
    result = []

    for line in lines:
        stripped = line.strip()

        # Preserve empty lines
        if not stripped:
            result.append(line)
            continue

        # Preserve document start marker
        if stripped == "---":
            result.append(line)
            continue

        # Comment out everything else (including existing comments)
        # This ensures uncommenting a section brings its documentation too
        result.append("# " + line)

    return "\n".join(result)


def _create_bootstrap_header(*, current: bool = False) -> str:
    """Create the header for a bootstrap config file.

    Args:
        current: If True, note that values are from the current effective config.

    Returns:
        Header comment string.
    """
    values_line = (
        "# Values shown are current effective configuration."
        if current
        else "# Values shown are defaults."
    )
    return f"""# Hive CLI Configuration
# Documentation: https://github.com/anthropics/hive-cli
#
# Uncomment and modify options as needed.
{values_line}
#
# Configuration precedence (highest to lowest):
#   1. Environment variables (HIVE_*)
#   2. .hive.local.yml (local overrides, git-ignored)
#   3. .hive.yml (project config, version-controlled)
#   4. $XDG_CONFIG_HOME/hive/hive.yml (global user config)
#   5. Package defaults
"""


def _generate_bootstrap_content() -> str:
    """Generate the bootstrap configuration content.

    Returns:
        Full bootstrap config string with header and commented-out defaults.
    """
    default_content = _get_default_yaml_content()

    # Remove the existing header from default.yml (up to first blank line)
    # We'll add our own header
    lines = default_content.split("\n")
    content_start = 0
    found_document_start = False
    for i, line in enumerate(lines):
        if line.strip() == "---":
            found_document_start = True
            continue
        if found_document_start and line.strip().startswith("#"):
            continue
        if found_document_start and not line.strip():
            content_start = i + 1
            break

    # If we found a valid starting point, use it; otherwise use the whole content
    if content_start > 0:
        config_lines = lines[content_start:]
        config_content = "\n".join(config_lines)
    else:
        # Remove just the --- and any leading comments/blank lines
        config_content = re.sub(r"^---\n(#[^\n]*\n)*\n*", "", default_content)

    # Comment out the config content
    commented_content = _comment_out_yaml(config_content)

    # Build final content
    final_content = "---\n" + _create_bootstrap_header() + "\n" + commented_content

    # Ensure file ends with newline
    if not final_content.endswith("\n"):
        final_content += "\n"

    return final_content


def _generate_current_bootstrap_content() -> str:
    """Generate bootstrap content from the current effective configuration.

    Returns:
        Full bootstrap config string with header and commented-out current values.
    """
    config = load_config()
    config_content = _config_to_yaml(config)

    commented_content = _comment_out_yaml(config_content)

    final_content = (
        "---\n" + _create_bootstrap_header(current=True) + "\n" + commented_content
    )

    if not final_content.endswith("\n"):
        final_content += "\n"

    return final_content


def create_bootstrap_config(
    file_path: Path | str, *, force: bool = False, current: bool = False
) -> None:
    """Create a bootstrap configuration file.

    Args:
        file_path: Path where to create the config file.
        force: If True, overwrite existing file.
        current: If True, use current effective config instead of defaults.
    """
    path = Path(file_path).expanduser().resolve()

    # Check if file already exists
    if path.exists() and not force:
        error(f"File already exists: {path}")
        info("Use --force to overwrite, or remove it first.")
        sys.exit(1)

    # Create parent directories if needed
    path.parent.mkdir(parents=True, exist_ok=True)

    content = (
        _generate_current_bootstrap_content()
        if current
        else _generate_bootstrap_content()
    )
    path.write_text(content)

    success(f"Created config file: {path}")
    info("Edit with your preferred editor to customize settings.")


# Cyclopts App

config_app = App(
    name="config",
    help="Manage hive configuration.",
)


@config_app.default
def config_default():
    """Print the current active configuration as YAML.

    Without a subcommand, prints the current active configuration
    (merged from all sources) as YAML.

    Examples:
        hive config                          # Show active config
        hive config bootstrap                # Print bootstrap to stdout
        hive config bootstrap .hive.yml      # Create project config
    """
    show_active_config()


@config_app.command
def bootstrap(
    file: Annotated[
        Path | None,
        Parameter(help="Path where to create the config file."),
    ] = None,
    *,
    force: Annotated[
        bool,
        Parameter(
            name=["--force", "-f"],
            help="Overwrite existing file.",
        ),
    ] = False,
    current: Annotated[
        bool,
        Parameter(
            name=["--current", "-c"],
            help="Use current effective config instead of defaults.",
        ),
    ] = False,
):
    """Create a new config file with documented options.

    Without FILE argument, prints the bootstrap config to stdout
    (pipe to a file or use with -o to save).

    With FILE argument, creates a new configuration file at that
    path with all options commented out and documented.

    Examples:
        hive config bootstrap                           # Print defaults to stdout
        hive config bootstrap --current                 # Print current config to stdout
        hive config bootstrap > .hive.yml               # Redirect to file
        hive config bootstrap .hive.yml                 # Create project config
        hive config bootstrap .hive.local.yml           # Create local overrides
        hive config bootstrap .hive.yml -f              # Overwrite existing
    """
    if file is None:
        content = (
            _generate_current_bootstrap_content()
            if current
            else _generate_bootstrap_content()
        )
        print(content, end="")
    else:
        create_bootstrap_config(str(file), force=force, current=current)
