"""Behaviour snapshot: every command/sub-command exists and prints the same
text as before the architecture refactor (issue #1, A0).

This is the mechanical "no behaviour change" guard for A0: exit codes alone
don't catch wrapping/wording drift, so we compare against a byte-exact
fixture captured (at COLUMNS=100) from `main` before any code moved. If a
step of A0 legitimately changes help text, both this file's expectations
and `tests/fixtures/cli_help_snapshot.txt` should be regenerated together,
never adjusted to paper over an accidental change.
"""

from __future__ import annotations

from pathlib import Path

from hive_cli.app import app

FIXTURES = Path(__file__).parent / "fixtures"

COMMANDS: dict[str, list[str]] = {
    "run": [],
    "zellij": ["set-status", "set-title", "layout-path"],
    "session": [],
    "wt": [
        "cd",
        "list",
        "path",
        "parent",
        "create",
        "delete",
        "exists",
        "base",
        "exec",
        "ensure",
    ],
    "pane": [
        "new",
        "shell",
        "list",
        "focus",
        "close",
        "restart",
        "hold",
        "set-status",
        "set-title",
    ],
    "tab": ["list"],
    "completion": [],
    "config": ["bootstrap"],
    "status": [],
    "task": ["show", "set", "edit", "clear"],
    "handoff": ["list", "show", "create", "edit", "clear", "clean", "path"],
    "diff": [],
    "rebase-check": [],
    "merge-preview": [],
    "doctor": [],
}


def _sections() -> dict[str, str]:
    """Parse tests/fixtures/cli_help_snapshot.txt into {header: body}."""
    text = (FIXTURES / "cli_help_snapshot.txt").read_text()
    sections: dict[str, str] = {}
    header = None
    body: list[str] = []
    for line in text.splitlines():
        if line.startswith("=== ") and line.endswith(" ==="):
            if header is not None:
                sections[header] = "\n".join(body)
            header = line[4:-4]
            body = []
        else:
            body.append(line)
    if header is not None:
        sections[header] = "\n".join(body)
    return sections


def test_every_command_answers_help(cli_runner, monkeypatch):
    monkeypatch.setenv("COLUMNS", "100")
    for name, subs in COMMANDS.items():
        assert cli_runner.invoke(app, [name, "--help"]).exit_code == 0, name
        for sub in subs:
            assert cli_runner.invoke(app, [name, sub, "--help"]).exit_code == 0, (
                f"{name} {sub}"
            )


def test_help_text_matches_pre_refactor_snapshot(cli_runner, monkeypatch):
    monkeypatch.setenv("COLUMNS", "100")
    sections = _sections()

    result = cli_runner.invoke(app, ["--help"])
    assert result.output.rstrip("\n") == sections["hive --help"]

    for name, subs in COMMANDS.items():
        result = cli_runner.invoke(app, [name, "--help"])
        assert result.output.rstrip("\n") == sections[f"hive {name} --help"], name
        for sub in subs:
            result = cli_runner.invoke(app, [name, sub, "--help"])
            assert (
                result.output.rstrip("\n") == sections[f"hive {name} {sub} --help"]
            ), f"{name} {sub}"


def test_version_flag(cli_runner):
    from hive_cli import __version__

    result = cli_runner.invoke(app, ["--version"])
    assert result.exit_code == 0 and __version__ in result.output


def test_bare_invocation_shows_help_and_does_not_crash(cli_runner):
    """The one argv shape ``dispatch(app, [])`` must handle: no args at all."""
    result = cli_runner.invoke(app, [])
    assert result.exit_code == 0
    assert "Usage: hive" in result.output
