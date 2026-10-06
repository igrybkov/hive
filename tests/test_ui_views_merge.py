"""ui/views/merge.py: pure renderables for the overlap analysis and previews."""

from __future__ import annotations

import io
from pathlib import Path

from rich.console import Console

from hive_cli.git import MergeSimulation
from hive_cli.services.merge import MergePreview, MergeTarget, Overlap
from hive_cli.ui.views import merge as views


def render(renderable) -> str:
    buf = io.StringIO()
    Console(file=buf, width=100).print(renderable)
    return buf.getvalue()


def test_overlap_lists_shared_files_or_says_none():
    none = render(views.build_overlap(Overlap("main", {"a.txt": ["x"]})))
    assert "File Overlap Analysis" in none and "No overlapping files" in none

    shared = render(
        views.build_overlap(Overlap("main", {"s.txt": ["x", "y"], "a": ["x"]}))
    )
    assert "s.txt" in shared and "Modified by agents: x y" in shared
    assert "a\n" not in shared.replace("Analysis", "")


def test_preview_header_and_outcomes():
    target = MergeTarget(Path("/w"), "feat", "main")
    assert "Merge Preview: feat → main" in render(views.build_preview_header(target))

    ok = MergeSimulation(ok=True, changed=[("A", "n.txt"), ("M", "m.txt"), ("D", "d")])
    text = render(views.build_simulation(ok))
    assert "would succeed" in text and "+ n.txt" in text and "~ m.txt" in text
    assert "- d" in text

    conflict = MergeSimulation(ok=True, conflicts=True, conflicting_files=["c.txt"])
    text = render(views.build_simulation(conflict))
    assert "would have conflicts" in text and "! c.txt" in text

    failed = MergeSimulation(ok=False, error="clone failed")
    assert "clone failed" in render(views.build_simulation(failed))


def test_preview_combines_header_and_outcome():
    preview = MergePreview(
        MergeTarget(Path("/w"), "feat", "main"), MergeSimulation(ok=True)
    )
    text = render(views.build_preview(preview))
    assert "Merge Preview: feat" in text and "would succeed" in text


def test_paths_with_brackets_survive_markup():
    text = render(views.build_overlap(Overlap("main", {"x[1].py": ["a", "b"]})))
    assert "x[1].py" in text
