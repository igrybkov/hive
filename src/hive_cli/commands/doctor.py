"""Doctor command - environment facts and startup/hot-path timings."""

from __future__ import annotations

from typing import Annotated

from cyclopts import App, Parameter
from rich.table import Table

from ..git import get_main_repo
from ..services import doctor as doctor_service
from ..ui.console import out

doctor_app = App(
    name="doctor",
    help="Check hive's environment and measure startup and hot-path timings.",
)


@doctor_app.default
def doctor(
    timing: Annotated[
        bool,
        Parameter(
            name="--timing",
            help=(
                "Time each startup phase (import, config, worktree list, "
                "status collect) and count the commands it spawns."
            ),
        ),
    ] = False,
):
    """Check hive's environment and measure startup and hot-path timings.

    Examples:
        hive doctor            # versions, multiplexer, agents on PATH
        hive doctor --timing   # phase | ms | spawns for this repository
    """
    if timing:
        table = Table(title="hive doctor --timing")
        table.add_column("phase")
        table.add_column("ms", justify="right")
        table.add_column("spawns", justify="right")
        for row in doctor_service.timings(get_main_repo()):
            table.add_row(row.phase, f"{row.ms:.1f}", str(row.spawns))
        out.print(table)
        return

    table = Table(show_header=False, box=None)
    for name, value in doctor_service.environment():
        table.add_row(f"[bold]{name}[/]", value)
    out.print(table)
