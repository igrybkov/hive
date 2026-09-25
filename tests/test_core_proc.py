"""hive_cli.core.proc: the one place hive spawns captured, non-interactive commands."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


def test_run_captures_stdout():
    from hive_cli.core import proc

    result = proc.run([sys.executable, "-c", "print('hi')"])
    assert result.stdout == "hi\n"
    assert result.ok


def test_missing_binary_is_127():
    from hive_cli.core import proc

    result = proc.run(["definitely-not-a-binary-xyz"])
    assert result.returncode == 127


def test_timeout_is_124():
    from hive_cli.core import proc

    result = proc.run([sys.executable, "-c", "import time; time.sleep(5)"], timeout=0.2)
    assert result.returncode == 124


def test_check_raises_proc_error():
    from hive_cli.core import proc
    from hive_cli.core.errors import ProcError

    with pytest.raises(ProcError) as exc_info:
        proc.run([sys.executable, "-c", "raise SystemExit(3)"], check=True)
    assert exc_info.value.result.returncode == 3


def test_argv_is_stringified():
    from hive_cli.core import proc

    result = proc.run([Path(sys.executable), "-c", "print('ok')"])
    assert all(isinstance(a, str) for a in result.argv)
