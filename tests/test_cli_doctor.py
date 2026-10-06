"""`hive doctor` CLI surface: prints a row per phase / per environment fact."""

from __future__ import annotations

from pathlib import Path

from conftest import CycloptsTestRunner

from hive_cli.app import app
from hive_cli.services.doctor import Timing


def test_doctor_timing_prints_a_row_per_phase(cli_runner: CycloptsTestRunner, mocker):
    mocker.patch("hive_cli.commands.doctor.get_main_repo", return_value=Path("/x"))
    mocker.patch(
        "hive_cli.services.doctor.timings",
        return_value=[
            Timing("import app", 12.3, 0),
            Timing("status collect", 45.6, 7),
        ],
    )
    result = cli_runner.invoke(app, ["doctor", "--timing"])
    assert result.exit_code == 0
    assert "import app" in result.output and "12.3" in result.output
    assert "status collect" in result.output and "45.6" in result.output
    assert "7" in result.output


def test_doctor_without_flags_prints_environment(
    cli_runner: CycloptsTestRunner, mocker
):
    mocker.patch(
        "hive_cli.services.doctor.environment",
        return_value=[("git", "2.55.0"), ("agents", "claude, codex")],
    )
    result = cli_runner.invoke(app, ["doctor"])
    assert result.exit_code == 0
    assert "2.55.0" in result.output and "claude, codex" in result.output
