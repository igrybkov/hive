"""Name -> operation dispatch table, used by the control plane (F4) and CLI alike."""

from __future__ import annotations

import dataclasses
import importlib
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..core.errors import HiveError

OPS: dict[str, Callable[..., Any]] = {}

# Extended as each service module lands within this step; by the end of A0
# this covers worktrees, status, tasks, handoffs.
_MODULES: tuple[str, ...] = ()


def op(name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator: register fn under name in OPS."""

    def register(fn: Callable[..., Any]) -> Callable[..., Any]:
        OPS[name] = fn
        return fn

    return register


def load_all() -> None:
    """Import every service module so its @op-decorated functions register."""
    for mod in _MODULES:
        importlib.import_module(f"hive_cli.services.{mod}")


def call(name: str, /, **kwargs: Any) -> Any:
    """Look up and call a registered operation by name."""
    load_all()
    try:
        fn = OPS[name]
    except KeyError:
        raise HiveError(f"unknown operation: {name}") from None
    return fn(**kwargs)


def jsonable(value: Any) -> Any:
    """Convert a value into something json.dumps can handle.

    Dataclasses become dicts (recursively); Path becomes str; list/tuple/dict
    recurse into their elements; everything else passes through unchanged.
    """
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            f.name: jsonable(getattr(value, f.name)) for f in dataclasses.fields(value)
        }
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value
