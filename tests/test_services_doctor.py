"""services/doctor.py: timings per phase (with spawn counts) and environment facts."""

from __future__ import annotations

import sys
from pathlib import Path

from hive_cli.services import doctor

IMPORTTIME_STDERR = """\
import time: self [us] | cumulative | imported package
import time:       100 |        100 |   _io
import time:       200 |        300 | cyclopts
import time:        50 |         50 |   hive_cli
import time:       400 |       1000 |   hive_cli.core.trace
import time:       250 |       5000 | hive_cli.app
"""


def test_parse_importtime_sums_hive_cli_self_time_and_takes_app_cumulative():
    own_ms, total_ms = doctor.parse_importtime(IMPORTTIME_STDERR)
    assert own_ms == (50 + 400 + 250) / 1000
    assert total_ms == 5.0


def test_parse_importtime_tolerates_garbage():
    assert doctor.parse_importtime("nonsense\nimport time: x | y | z\n") == (0.0, 0.0)


def test_timings_counts_spawns_per_phase(temp_git_repo: Path, mocker):
    mocker.patch(
        "hive_cli.services.doctor.import_timings",
        return_value=[doctor.Timing("import app", 1.0, 0)],
    )
    rows = {t.phase: t for t in doctor.timings(temp_git_repo)}
    assert rows["import app"].spawns == 0
    assert rows["load config"].spawns == 0
    assert rows["list worktrees"].spawns == 1
    assert rows["git summaries (1 worktrees)"].spawns == 2
    assert rows["status collect"].spawns >= 1
    assert all(t.ms >= 0 for t in rows.values())


def test_import_timings_runs_python_importtime(fake_proc):
    fake_proc.script((sys.executable,), stderr=IMPORTTIME_STDERR)
    rows = doctor.import_timings()
    assert [r.phase for r in rows] == [
        "import app (hive_cli modules)",
        "import app (with dependencies)",
    ]
    assert rows[0].ms == 0.7 and rows[1].ms == 5.0
    argv = fake_proc.calls[0]
    assert argv[1:] == ["-X", "importtime", "-c", "import hive_cli.app"]


def test_environment_reports_versions_and_agents(fake_proc, mocker):
    fake_proc.script(("git", "--version"), stdout="git version 2.55.0\n")
    mocker.patch(
        "hive_cli.services.doctor.shutil.which",
        side_effect=lambda binary: "/usr/bin/git" if binary == "git" else None,
    )
    mocker.patch(
        "hive_cli.services.doctor.get_available_agents", return_value=["claude"]
    )
    rows = dict(doctor.environment())
    assert rows["git"] == "2.55.0"
    assert rows["zellij"] == "not found"
    assert rows["agents"] == "claude"
    assert "hive" in rows and "python" in rows and "multiplexer" in rows
