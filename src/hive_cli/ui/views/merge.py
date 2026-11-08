"""Rich renderables for `hive merge-preview`: pure data -> Group, no printing."""

from __future__ import annotations

from rich.console import Group
from rich.markup import escape
from rich.text import Text

from ...git import MergeSimulation
from ...services.merge import MergePreview, MergeTarget, Overlap

_RULE = "[bold cyan]" + "═" * 55 + "[/]"


def _lines(markup: list[str]) -> Group:
    return Group(*(Text.from_markup(line) for line in markup))


def build_overlap(overlap: Overlap) -> Group:
    """The file-overlap analysis: files modified by more than one agent."""
    lines = [
        _RULE,
        "[bold cyan]  File Overlap Analysis[/]",
        _RULE,
        "",
        "[yellow]Files modified by multiple agents:[/]",
        "",
    ]
    overlapping = overlap.overlapping()
    for path, agents in overlapping:
        lines.append(f"  [red]{escape(path)}[/]")
        lines.append(f"    [dim]Modified by agents: {' '.join(agents)}[/]")
    if not overlapping:
        lines.append(
            "  [green]No overlapping files - agents are working on separate areas[/]"
        )
    lines.append("")
    lines.append(
        "[dim]Tip: Run 'hive merge-preview <agent-id>' to simulate a specific merge[/]"
    )
    return _lines(lines)


def build_preview_header(target: MergeTarget) -> Group:
    return _lines(
        [
            _RULE,
            f"[bold cyan]  Merge Preview: {escape(target.branch)} → "
            f"{escape(target.default_branch)}[/]",
            _RULE,
            "",
        ]
    )


_CHANGE_MARKUP = {"A": "[green]+ {}[/]", "M": "[yellow]~ {}[/]", "D": "[red]- {}[/]"}


def build_simulation(sim: MergeSimulation) -> Group:
    """The outcome of a simulated merge (conflicts, or the files it changes)."""
    if not sim.ok:
        return _lines(
            [f"[bold red]{escape(sim.error or 'merge simulation failed')}[/]"]
        )
    if sim.conflicts:
        lines = [
            "[red]✗ Merge would have conflicts[/]",
            "",
            "[bold]Conflicting files:[/]",
        ]
        lines.extend(f"  [red]! {escape(path)}[/]" for path in sim.conflicting_files)
        return _lines(lines)
    lines = [
        "[green]✓ Merge would succeed without conflicts[/]",
        "",
        "[dim]Files that would be changed:[/]",
    ]
    for status, path in sim.changed:
        template = _CHANGE_MARKUP.get(status, f"{escape(status)} {{}}")
        lines.append("  " + template.format(escape(path)))
    return _lines(lines)


def build_preview(preview: MergePreview) -> Group:
    """Header plus outcome: one `--watch` frame for a single agent."""
    return Group(
        build_preview_header(preview.target), build_simulation(preview.simulation)
    )
