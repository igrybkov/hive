"""HiveError: the only way lower layers signal failure to the user."""

from __future__ import annotations


class HiveError(Exception):
    """The only exception lower layers use to report a user-facing failure."""

    def __init__(self, message: str, *, exit_code: int = 1, hint: str | None = None):
        super().__init__(message)
        self.exit_code = exit_code
        self.hint = hint


class ProcError(HiveError):
    def __init__(self, result):
        cmd = " ".join(result.argv)
        super().__init__(
            f"command failed ({result.returncode}): {cmd}\n{result.stderr.strip()}"
        )
        self.result = result
