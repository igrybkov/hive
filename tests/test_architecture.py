"""Architecture guard: layering, forbidden imports, size, import cost.

The allow-lists below ARE the architecture. Change them only together with
docs/ARCHITECTURE.md, never to make a failing test pass.
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "hive_cli"

LAYER: dict[str, int] = {
    "core": 0,
    "config": 1,
    "state": 1,
    "hooks": 1,
    "git": 2,
    "agents": 2,
    "layout": 2,
    "mux": 2,
    "services": 3,
    "ui": 4,
    "commands": 5,
    "app": 5,
}
SIDEWAYS_OK = {("mux", "layout"), ("hooks", "state"), ("commands", "app")}
STDLIB_ONLY = {
    "core": {"core"},
    "state": {"core", "state"},
    "hooks": {"core", "state", "hooks"},
}
UI_LIBS = {"rich", "prompt_toolkit", "textual"}
UI_LIB_HOMES = {"ui", "commands", "app"}
SUBPROCESS_OK = {
    "core/proc.py",
    "services/pane.py",  # agent child keeps the tty (Popen)
    "services/session.py",  # restart loop keeps the tty; execvpe hand-off
    "services/editors.py",  # GUI editor launch is a detached, unwaited Popen
    "git/analysis.py",  # git|delta pipe: streamed straight to the terminal
    "mux/zellij/backend.py",  # execvpe hand-off to `zellij attach`
    "mux/tmux/backend.py",
    "commands/zellij.py",
    "commands/session.py",
}
EXIT_PRINT_OK = {"ui", "commands", "app", "hooks"}
MAX_LINES = 600


def _modules() -> list[Path]:
    return sorted(SRC.rglob("*.py"))


def _rel(path: Path) -> str:
    return path.relative_to(SRC).as_posix()


def _pkg(path: Path) -> str:
    rel = path.relative_to(SRC)
    if len(rel.parts) == 1:
        return "app" if rel.stem == "app" else "hive_cli"
    return rel.parts[0]


def _hive_pkg(module: str) -> str | None:
    """Top-level hive package a module path points at; None for third-party/stdlib."""
    parts = module.split(".")
    if parts[0] != "hive_cli":
        return None
    if len(parts) > 1 and (SRC / parts[1]).is_dir():
        return parts[1]
    if len(parts) > 1 and parts[1] == "app":
        return "app"
    return "hive_cli"


def _is_stdlib(module: str) -> bool:
    return module.split(".")[0] in sys.stdlib_module_names


def _import_froms(path: Path):
    """Yield (resolved_module, [names], lineno) for every `from … import …`."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    package = ["hive_cli", *path.relative_to(SRC).parts[:-1]]
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level == 0:
                base = (node.module or "").split(".")
            else:
                base = package[: len(package) - (node.level - 1)]
                if node.module:
                    base = [*base, *node.module.split(".")]
            yield ".".join(base), [a.name for a in node.names], node.lineno


def _imports(path: Path):
    """Yield unique (module, lineno) per import; `from x import y` also yields x.y."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend((alias.name, node.lineno) for alias in node.names)
    for module, names, lineno in _import_froms(path):
        found.append((module, lineno))
        found.extend((f"{module}.{name}", lineno) for name in names)
    yield from dict.fromkeys(found)


def test_every_package_is_in_the_layer_table():
    unknown = sorted({_pkg(p) for p in _modules()} - set(LAYER) - {"hive_cli"})
    assert not unknown, (
        "packages missing from LAYER (add to the table and docs/ARCHITECTURE.md): "
        f"{unknown}"
    )


def test_layers_only_point_down():
    bad = []
    for path in _modules():
        src = _pkg(path)
        if src not in LAYER:  # reported by test_every_package_is_in_the_layer_table
            continue
        for mod, line in _imports(path):
            dst = _hive_pkg(mod)
            if dst in (None, "hive_cli", src):
                continue
            if dst not in LAYER:
                bad.append(
                    f"{_rel(path)}:{line}: import of unknown package {dst} ({mod})"
                )
                continue
            if LAYER[dst] < LAYER[src] or (src, dst) in SIDEWAYS_OK:
                continue
            bad.append(f"{_rel(path)}:{line}: {src} -> {dst} ({mod})")
    assert not bad, "\n" + "\n".join(bad)


def test_stdlib_only_packages():
    bad = []
    for path in _modules():
        allowed = STDLIB_ONLY.get(_pkg(path))
        if allowed is None:
            continue
        for mod, line in _imports(path):
            dst = _hive_pkg(mod)
            if dst is None and not _is_stdlib(mod):
                bad.append(f"{_rel(path)}:{line}: third-party import {mod}")
            elif dst is not None and dst != "hive_cli" and dst not in allowed:
                bad.append(f"{_rel(path)}:{line}: {mod}")
    assert not bad, "\n" + "\n".join(bad)


def test_ui_libraries_confined():
    bad = []
    for path in _modules():
        for mod, line in _imports(path):
            top = mod.split(".")[0]
            if top not in UI_LIBS:
                continue
            if _pkg(path) not in UI_LIB_HOMES:
                bad.append(f"{_rel(path)}:{line}: {top} outside ui/commands")
            elif top == "textual" and not _rel(path).startswith("ui/tui/"):
                bad.append(f"{_rel(path)}:{line}: textual outside ui/tui/")
    bad = list(dict.fromkeys(bad))
    assert not bad, "\n" + "\n".join(bad)


def test_subprocess_confined():
    bad = [
        f"{_rel(p)}:{line}"
        for p in _modules()
        for mod, line in _imports(p)
        if mod.split(".")[0] == "subprocess" and _rel(p) not in SUBPROCESS_OK
    ]
    assert not bad, "\n" + "\n".join(bad)


def test_commands_do_not_import_each_other():
    bad = []
    for path in _modules():
        if _pkg(path) != "commands":
            continue
        own = f"hive_cli.commands.{path.stem}"
        for mod, line in _imports(path):
            if (
                mod.startswith("hive_cli.commands.")
                and mod != "hive_cli.commands"
                and not mod.startswith(own)
            ):
                bad.append(f"{_rel(path)}:{line}: {mod}")
    assert not bad, "\n" + "\n".join(bad)


def _call_name(node: ast.Call) -> str:
    f = node.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name):
        return f"{f.value.id}.{f.attr}"
    return ""


def _forbidden_calls_in(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    bad = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node)
        if name in {"print", "exit", "sys.exit", "input", "Console"}:
            bad.append(f"{_rel(path)}:{node.lineno}: {name}()")
    return bad


def test_no_exit_print_or_console_below_cli():
    bad = []
    for path in _modules():
        if _pkg(path) in EXIT_PRINT_OK:
            continue
        bad.extend(_forbidden_calls_in(path))
    assert not bad, "\n" + "\n".join(bad)


def _module_not_function_violations(
    path: Path, module: str, names: list[str], line: int
) -> list[str]:
    bad = []
    if module == "hive_cli.core.proc":
        bad.append(
            f"{_rel(path)}:{line}: import the module: from hive_cli.core import proc"
        )
    if module.startswith("hive_cli.services."):
        for name in names:
            if name[:1].islower() and not (SRC / "services" / f"{name}.py").exists():
                bad.append(
                    f"{_rel(path)}:{line}: from {module} import {name} "
                    "(import the module)"
                )
    return bad


def test_cross_layer_imports_are_modules_not_functions():
    """`from hive_cli.core import proc` / `from ...services import x`: patchable."""
    bad = []
    for path in _modules():
        for module, names, line in _import_froms(path):
            bad.extend(_module_not_function_violations(path, module, names, line))
    assert not bad, "\n" + "\n".join(bad)


def test_module_size():
    bad = [
        f"{_rel(p)}: {n} lines"
        for p in _modules()
        if (n := len(p.read_text().splitlines())) > MAX_LINES
    ]
    assert not bad, "\n" + "\n".join(bad)


def _run_py(code: str) -> str:
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    ).stdout


def test_app_import_is_light():
    out = _run_py(
        "import sys, hive_cli.app; print('\\n'.join(sorted(m for m in sys.modules "
        "if m.split('.')[0] in ('prompt_toolkit', 'textual') "
        "or m.startswith('hive_cli.commands.'))))"
    )
    assert out.strip() == "", f"import hive_cli.app loaded:\n{out}"


@pytest.mark.skipif(
    not (SRC / "hooks" / "entry.py").exists(), reason="hooks land in F5"
)
def test_hooks_entry_is_stdlib_only():
    out = _run_py(
        "import sys; before=set(sys.modules); import hive_cli.hooks.entry; "
        "print('\\n'.join(sorted(set(sys.modules) - before)))"
    )
    bad = [
        m
        for m in out.split()
        if not (
            m.split(".")[0] in sys.stdlib_module_names
            or m == "hive_cli"
            or m.startswith(("hive_cli.core", "hive_cli.state", "hive_cli.hooks"))
        )
    ]
    assert not bad, bad
