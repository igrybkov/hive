"""Shell completion command."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Annotated, Literal

from cyclopts import App, Parameter
from rich.console import Console

console = Console()

completion_app = App(
    name="completion",
    help="Generate shell completion script.",
)


@completion_app.default
def completion(
    shell: Annotated[
        Literal["bash", "zsh", "fish"],
        Parameter(help="Shell type to generate completion for."),
    ],
    install: Annotated[
        bool,
        Parameter(
            name="--install",
            help="Install completion script to appropriate location.",
        ),
    ] = False,
):
    """Generate shell completion script.

    Examples:
        hive completion fish           # Print fish completion script
        hive completion fish --install # Install fish completion
        hive completion bash           # Print bash completion script
    """
    from ..app import app as root_app

    # Use cyclopts to generate completion script
    completion_str = root_app.meta.generate_completion(shell=shell)

    # Fix for fish: disable file completion at root level
    # This prevents files from appearing when completing commands
    # Note: Pager layout (horizontal vs vertical) is automatically determined by fish
    # based on terminal width and number of completions. To force vertical layout,
    # you can resize your terminal window narrower or set fish_pager_max_items
    if shell == "fish":
        # Get all command names from the app
        # (excluding meta commands like --help, --version)
        command_names = [
            name
            for name in root_app.meta
            if not name.startswith("--") and name not in ("-h", "-V")
        ]
        command_list = " ".join(command_names)

        # Add a rule to disable file completion when we're completing the first argument
        # (i.e., when we're at root level and haven't typed a subcommand yet)
        lines = completion_str.split("\n")

        # Find where to insert the fix
        # (after the helper function, before root-level commands)
        insert_idx = None
        for i, line in enumerate(lines):
            if line.strip() == "# Root-level commands":
                insert_idx = i
                break

        if insert_idx is not None:
            # Insert rule to disable file completion at root level
            # We check if we're completing a non-option argument and
            # no subcommand has been seen
            # This prevents files from appearing when typing 'hive <TAB>'
            # Note: Pager layout (horizontal vs vertical) is automatically
            # determined by fish based on terminal width and number of completions.
            # To force vertical layout, resize your terminal window narrower.
            fix_lines = [
                "",
                "# Disable file completion at root level (only show commands)",
                "# This prevents files from appearing when typing 'hive <TAB>'",
                (
                    f"complete -c hive -f -n "
                    f"'not __fish_seen_subcommand_from {command_list}'"
                ),
            ]
            lines[insert_idx:insert_idx] = fix_lines
            completion_str = "\n".join(lines)

            # Disable file completion for all subcommands
            # For 'config', we need to be careful - only disable files when
            # NOT completing --file option. The -F flag on 'config bootstrap --file'
            # needs to work
            subcommand_fixes = []
            for cmd in command_names:
                if cmd == "config":
                    # For config, disable files by default
                    # The -F flag on 'config bootstrap --file' will override this
                    # Fish evaluates more specific rules first, so the --file
                    # option rule takes precedence
                    subcommand_fixes.append(
                        "complete -c hive -f -n '__fish_hive_using_command config'"
                    )
                else:
                    # For all other commands, disable file completion
                    subcommand_fixes.append(
                        f"complete -c hive -f -n '__fish_hive_using_command {cmd}'"
                    )

            # Insert these rules after the root-level commands section
            # Find a good place to insert (after all command definitions)
            end_idx = None
            for i in range(len(lines) - 1, -1, -1):
                if lines[i].strip().startswith("# Options for:"):
                    # Find the last "# Options for:" section to insert after
                    end_idx = i
                    break

            if end_idx is None:
                # Fallback: insert after root-level commands section
                end_idx = insert_idx + 20

            if subcommand_fixes:
                subcommand_fix_lines = [
                    "",
                    (
                        "# Disable file completion for subcommands "
                        "(except config bootstrap --file)"
                    ),
                    (
                        "# This prevents files from appearing when completing "
                        "arguments for commands"
                    ),
                ] + subcommand_fixes
                lines[end_idx:end_idx] = subcommand_fix_lines
                completion_str = "\n".join(lines)

    if not install:
        print(completion_str)
        return

    # Install the completion script
    home = Path(os.environ.get("HOME", "~")).expanduser()

    if shell == "fish":
        completion_dir = home / ".config" / "fish" / "completions"
        completion_dir.mkdir(parents=True, exist_ok=True)
        completion_file = completion_dir / "hive.fish"
        completion_file.write_text(completion_str)
        console.print(f"Installed fish completion to {completion_file}")
    elif shell == "bash":
        # For bash, we typically write to ~/.local/share/bash-completion/completions/
        completion_dir = home / ".local" / "share" / "bash-completion" / "completions"
        completion_dir.mkdir(parents=True, exist_ok=True)
        completion_file = completion_dir / "hive"
        completion_file.write_text(completion_str)
        console.print(f"Installed bash completion to {completion_file}")
        console.print("Note: You may need to restart your shell or source the file.")
    elif shell == "zsh":
        # For zsh, write to ~/.zfunc/ (common convention)
        completion_dir = home / ".zfunc"
        completion_dir.mkdir(parents=True, exist_ok=True)
        completion_file = completion_dir / "_hive"
        completion_file.write_text(completion_str)
        console.print(f"Installed zsh completion to {completion_file}")
        console.print("Note: Ensure ~/.zfunc is in your fpath before compinit.")
    else:
        console.print(
            f"[red]Automatic installation for {shell} is not supported yet.[/]",
            file=sys.stderr,
        )
        sys.exit(1)
