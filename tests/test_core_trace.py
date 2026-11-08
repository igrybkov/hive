"""hive_cli.core.trace: spans, marks and the spawn counter behind HIVE_TRACE=1."""

from __future__ import annotations

import sys

from hive_cli.core import proc, trace


def test_disabled_trace_writes_nothing(capsys, monkeypatch):
    monkeypatch.setattr(trace, "_ENABLED", False)
    trace.mark("app_imported")
    with trace.span("picker", "first_paint"):
        pass
    assert capsys.readouterr().err == ""


def test_mark_and_span_write_one_line_each(capsys, monkeypatch):
    monkeypatch.setattr(trace, "_ENABLED", True)
    trace.mark("app_imported")
    with trace.span("picker", "first_paint"):
        pass
    lines = capsys.readouterr().err.splitlines()
    assert len(lines) == 2
    assert lines[0].startswith("[hive] +") and "mark app_imported" in lines[0]
    assert "picker first_paint ms=" in lines[1]
    assert "spawns=0" in lines[1]


def test_proc_run_counts_spawns():
    before = trace.spawns
    proc.run([sys.executable, "-c", "pass"])
    proc.run(["definitely-not-a-binary-xyz"])  # a failed spawn still counts
    assert trace.spawns == before + 2


def test_span_reports_spawns_inside_it(capsys, monkeypatch):
    monkeypatch.setattr(trace, "_ENABLED", True)
    with trace.span("doctor", "phase"):
        proc.run([sys.executable, "-c", "pass"])
    err = capsys.readouterr().err
    assert "doctor phase" in err.splitlines()[-1]
    assert "spawns=1" in err.splitlines()[-1]
