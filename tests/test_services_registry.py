"""Tests for services/registry.py -- the name -> operation dispatch table."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from hive_cli.core.errors import HiveError
from hive_cli.services import registry


def test_op_registers_and_calls():
    @registry.op("test.echo")
    def _echo(*, value):
        return value

    assert registry.call("test.echo", value=42) == 42


def test_unknown_op_is_hive_error():
    with pytest.raises(HiveError, match="unknown operation"):
        registry.call("test.does-not-exist")


def test_jsonable_dataclass_and_path():
    @dataclass
    class Point:
        x: int
        y: Path

    result = registry.jsonable(Point(x=1, y=Path("/tmp/x")))
    assert result == {"x": 1, "y": "/tmp/x"}


def test_jsonable_recurses_into_list_and_dict():
    @dataclass
    class Item:
        name: str

    result = registry.jsonable({"items": [Item(name="a"), Item(name="b")], "n": 2})
    assert result == {"items": [{"name": "a"}, {"name": "b"}], "n": 2}
