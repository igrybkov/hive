"""Tests for services/aio.py -- running a synchronous service off the event loop."""

from __future__ import annotations

import asyncio
import threading

import pytest

from hive_cli.core.errors import HiveError
from hive_cli.services import aio


def test_call_runs_in_thread_and_returns():
    main_thread_id = threading.get_ident()
    result = asyncio.run(aio.call(threading.get_ident))
    assert result != main_thread_id


def test_hive_error_propagates():
    def _raise():
        raise HiveError("boom")

    with pytest.raises(HiveError, match="boom"):
        asyncio.run(aio.call(_raise))
