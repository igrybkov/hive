"""Layer 2: terminal multiplexer backends (Zellij, tmux).

`get_mux()` picks the backend from an explicit override, HIVE_MUX_BACKEND,
config (`mux.backend`, "auto" by default), or the environment the process
runs in; None means "not inside a multiplexer" and every caller treats that
as a no-op. Backends are imported lazily so `import hive_cli.mux` stays
cheap. The explicit `os.environ` check (rather than relying solely on
`get_settings().mux.backend`'s own env binding) keeps this live even when
`get_settings()`'s cached singleton predates a test's `monkeypatch.setenv`.
"""

from __future__ import annotations

import os

from ..config import get_settings
from .base import Mux, PaneInfo, TabInfo

__all__ = ["Mux", "PaneInfo", "TabInfo", "get_mux"]


def get_mux(backend: str | None = None) -> Mux | None:
    choice = backend or os.environ.get("HIVE_MUX_BACKEND") or get_settings().mux.backend
    # Zellij exports ZELLIJ="0" inside a session: test presence, never truthiness.
    if choice == "zellij" or (choice == "auto" and "ZELLIJ" in os.environ):
        from .zellij.backend import ZellijMux

        return ZellijMux()
    if choice == "tmux" or (choice == "auto" and os.environ.get("TMUX")):
        from .tmux.backend import TmuxMux

        return TmuxMux()
    return None
