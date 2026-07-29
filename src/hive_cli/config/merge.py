"""Deep merge utility for configuration dictionaries."""

from __future__ import annotations

from typing import Any


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Deep merge two dictionaries.

    Nested dicts are merged recursively. Lists and other values are replaced.

    Args:
        base: Base dictionary.
        override: Dictionary with values to override.

    Returns:
        New dictionary with merged values.

    Examples:
        >>> deep_merge({"a": {"b": 1}}, {"a": {"c": 2}})
        {'a': {'b': 1, 'c': 2}}
        >>> deep_merge({"a": [1, 2]}, {"a": [3, 4]})
        {'a': [3, 4]}
    """
    result = base.copy()

    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            # Recursively merge nested dicts
            result[key] = deep_merge(result[key], value)
        else:
            # Replace value (including lists)
            result[key] = value

    return result
