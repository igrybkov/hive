"""Layer 2: terminal multiplexer backends (Zellij, tmux).

`get_mux()` picks the backend from HIVE_MUX_BACKEND or the environment the
process runs in; None means "not inside a multiplexer" and every caller
treats that as a no-op. Backends are imported lazily so `import hive_cli.mux`
stays cheap.
"""

from __future__ import annotations

import os

from ..core.errors import HiveError
from .base import Mux, PaneInfo, TabInfo

__all__ = ["Mux", "PaneInfo", "TabInfo", "get_mux"]


def get_mux(backend: str | None = None) -> Mux | None:
    choice = backend or os.environ.get("HIVE_MUX_BACKEND") or "auto"
    # Zellij exports ZELLIJ="0" inside a session: test presence, never truthiness.
    if choice == "zellij" or (choice == "auto" and "ZELLIJ" in os.environ):
        from .zellij.backend import ZellijMux

        return ZellijMux()
    if choice == "tmux" or (choice == "auto" and os.environ.get("TMUX")):
        raise HiveError("tmux backend is not available yet")  # F6 replaces
    return None
