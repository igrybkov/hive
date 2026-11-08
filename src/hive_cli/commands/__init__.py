"""CLI commands for hive.

Deliberately empty (no re-exports): app.py registers each command module
lazily via a "module:attribute" string target, and an eager `from . import
...` here would import every command module up front, defeating that (see
tests/test_architecture.py:test_app_import_is_light).
"""
