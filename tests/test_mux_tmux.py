"""Tests for hive_cli.mux.tmux.backend.TmuxMux: exact argv per method
(fake_proc), matching tests/test_mux_zellij.py's style.

`list_panes`/`list_tabs` scope to `own_session()` rather than the "-a" flag
in F6-tmux.md's method table -- a private server can host more than one
hive session (one per repo), and "-a" would leak other repos' panes into
one repo's control plane. Tests here assert the argv this backend actually
sends (see docs/ARCHITECTURE.md for the F6 divergences list), not the
literal spec table.
"""

from __future__ import annotations

from hive_cli.layout.model import PaneSpec, SessionSpec, TabSpec
from hive_cli.layout.tabs import agents_tab
from hive_cli.mux.tmux.backend import TmuxMux


def test_own_pane_id_from_env(monkeypatch):
    monkeypatch.setenv("TMUX_PANE", "%3")
    assert TmuxMux().own_pane_id() == "%3"


def test_own_pane_id_missing_env(monkeypatch):
    monkeypatch.delenv("TMUX_PANE", raising=False)
    assert TmuxMux().own_pane_id() is None


def test_own_session_requires_tmux_env(monkeypatch, fake_proc):
    monkeypatch.delenv("TMUX", raising=False)
    assert TmuxMux().own_session() is None
    assert fake_proc.calls == []


def test_own_session_queries_and_caches(monkeypatch, fake_proc):
    monkeypatch.setenv("TMUX", "/tmp/tmux-501/hive,123,0")
    fake_proc.script(("tmux", "-L", "hive", "display"), stdout="myrepo\n")
    mux = TmuxMux()
    assert mux.own_session() == "myrepo"
    assert mux.own_session() == "myrepo"
    assert fake_proc.count("tmux", "-L", "hive", "display") == 1


def test_session_exists_uses_exact_match(fake_proc):
    fake_proc.script(("tmux", "-L", "hive", "has-session"), returncode=0)
    assert TmuxMux().session_exists("myrepo") is True
    assert fake_proc.calls[-1] == ["tmux", "-L", "hive", "has-session", "-t", "=myrepo"]


def test_session_exists_false_on_nonzero(fake_proc):
    fake_proc.script(("tmux", "-L", "hive", "has-session"), returncode=1)
    assert TmuxMux().session_exists("nope") is False


def test_attach_argv_with_conf():
    argv = TmuxMux().attach_argv("myrepo", "/state/hive/layouts/myrepo/tmux.conf")
    assert argv == [
        "tmux",
        "-L",
        "hive",
        "-f",
        "/state/hive/layouts/myrepo/tmux.conf",
        "attach-session",
        "-t",
        "myrepo",
    ]


def test_attach_argv_without_conf():
    assert TmuxMux().attach_argv("myrepo", None) == [
        "tmux",
        "-L",
        "hive",
        "attach-session",
        "-t",
        "myrepo",
    ]


def test_new_pane_split_right(fake_proc, monkeypatch):
    monkeypatch.delenv("TMUX", raising=False)
    fake_proc.script(("tmux", "-L", "hive", "split-window"), stdout="%7\n")
    argv = [
        "/usr/bin/env",
        "HIVE_PANE_ID=2",
        "HIVE_PANE_LABEL=Bohdan",
        "/opt/hive",
        "run",
        "--restart",
    ]
    pane_id = TmuxMux().new_pane(argv, direction="right", tab_id="@1", cwd="/wt")
    assert pane_id == "%7"
    assert fake_proc.calls[-1] == [
        "tmux",
        "-L",
        "hive",
        "split-window",
        "-h",
        "-t",
        "@1",
        "-c",
        "/wt",
        "-P",
        "-F",
        "#{pane_id}",
        "--",
        *argv,
    ]


def test_new_pane_no_focus_adds_d(fake_proc):
    fake_proc.script(("tmux", "-L", "hive", "split-window"), stdout="%8\n")
    TmuxMux().new_pane(["cmd"], focus=False)
    assert fake_proc.calls[-1] == [
        "tmux",
        "-L",
        "hive",
        "split-window",
        "-h",
        "-d",
        "-P",
        "-F",
        "#{pane_id}",
        "--",
        "cmd",
    ]


def test_new_pane_floating_uses_popup(fake_proc):
    result = TmuxMux().new_pane(["cmd"], floating=True, name="shell", cwd="/wt")
    assert result is None
    assert fake_proc.calls[-1] == [
        "tmux",
        "-L",
        "hive",
        "display-popup",
        "-E",
        "-d",
        "/wt",
        "-w",
        "80%",
        "-h",
        "80%",
        "-T",
        "shell",
        "--",
        "cmd",
    ]


def test_new_pane_names_via_select_pane(fake_proc):
    fake_proc.script(("tmux", "-L", "hive", "split-window"), stdout="%9\n")
    TmuxMux().new_pane(["cmd"], name="worker")
    assert fake_proc.calls[-1] == [
        "tmux",
        "-L",
        "hive",
        "select-pane",
        "-t",
        "%9",
        "-T",
        "worker",
    ]


def test_new_tab_applies_all_panes(fake_proc):
    spec = agents_tab(
        n=2, control="none", hive="/opt/hive", labels=["Anton", "Bohdan"], focus=True
    )
    fake_proc.script(("tmux", "-L", "hive", "new-window"), stdout="@5\n")
    window_id = TmuxMux().new_tab(spec, focus=True)
    assert window_id == "@5"
    new_window_call = next(c for c in fake_proc.calls if c[3] == "new-window")
    assert new_window_call == [
        "tmux",
        "-L",
        "hive",
        "new-window",
        "-n",
        "agents",
        "-P",
        "-F",
        "#{window_id}",
        "--",
        "/usr/bin/env",
        "HIVE_PANE_ID=1",
        "HIVE_PANE_LABEL=Anton",
        "/opt/hive",
        "run",
        "--restart",
    ]
    split_call = next(c for c in fake_proc.calls if c[3] == "split-window")
    assert split_call[:6] == ["tmux", "-L", "hive", "split-window", "-h", "-t"]
    assert split_call[6] == "@5"
    hold_argv = split_call[split_call.index("--") + 1 :]
    assert hold_argv == [
        "/usr/bin/env",
        "HIVE_PANE_ID=2",
        "HIVE_PANE_LABEL=Bohdan",
        "hive",
        "pane",
        "hold",
        "--",
        "/opt/hive",
        "run",
        "--restart",
    ]


def test_list_panes_parses_format(monkeypatch, fake_proc):
    monkeypatch.delenv("TMUX", raising=False)
    # A `uv tool install`ed hive reports its interpreter, not "hive", as
    # #{pane_current_command} (verified on this machine: "python3.14") --
    # suspended detection must key on the "hold: " title alone.
    stdout = (
        "%0\t@0\tIllia\tbash\t/repo\t1\t1\t0\n"
        "%1\t@0\thold: claude\tpython3.14\t/repo\t0\t1\t0\n"
    )
    fake_proc.script(("tmux", "-L", "hive", "list-panes"), stdout=stdout)
    panes = TmuxMux().list_panes()
    assert len(panes) == 2
    assert panes[0].id == "%0"
    assert panes[0].tab_id == "@0"
    assert panes[0].focused is True
    assert panes[0].exited is False
    assert panes[0].suspended is False
    assert panes[1].id == "%1"
    assert panes[1].suspended is True
    assert fake_proc.calls[-1][:5] == ["tmux", "-L", "hive", "list-panes", "-a"]


def test_list_panes_focused_requires_window_active_too(fake_proc):
    # `#{pane_active}` alone is 1 for the active pane of *every* window, not
    # just the one currently in view (verified empirically against a
    # two-window session): a background window's active pane must not count
    # as focused, or a run-shell keybind (no $TMUX_PANE, see
    # current_tab_id's fallback below) would target the wrong window.
    stdout = (
        "%0\t@0\tIllia\tbash\t/repo\t1\t0\t0\n%1\t@1\tIllia\tbash\t/repo\t1\t1\t0\n"
    )
    fake_proc.script(("tmux", "-L", "hive", "list-panes"), stdout=stdout)
    panes = TmuxMux().list_panes()
    assert panes[0].focused is False
    assert panes[1].focused is True


def test_list_panes_scopes_to_own_session(monkeypatch, fake_proc):
    monkeypatch.setenv("TMUX", "/tmp/tmux-501/hive,123,0")
    fake_proc.script(("tmux", "-L", "hive", "display"), stdout="myrepo\n")
    fake_proc.script(("tmux", "-L", "hive", "list-panes"), stdout="")
    TmuxMux().list_panes()
    call = next(c for c in fake_proc.calls if c[3] == "list-panes")
    assert call[:8] == ["tmux", "-L", "hive", "list-panes", "-s", "-t", "myrepo", "-F"]


def test_current_tab_id_from_own_pane(monkeypatch, fake_proc):
    monkeypatch.setenv("TMUX_PANE", "%1")
    stdout = (
        "%0\t@0\tIllia\tbash\t/repo\t1\t0\t0\n%1\t@1\tIllia\tbash\t/repo\t1\t1\t0\n"
    )
    fake_proc.script(("tmux", "-L", "hive", "list-panes"), stdout=stdout)
    assert TmuxMux().current_tab_id() == "@1"


def test_current_tab_id_falls_back_to_focused_pane(monkeypatch, fake_proc):
    # No $TMUX_PANE (a run-shell keybind, verified empirically: run-shell
    # inherits $TMUX but not $TMUX_PANE) falls back to the focused pane --
    # which requires window_active, not just pane_active, to pick the right
    # window out of several (see test_list_panes_focused_requires_window_active_too).
    monkeypatch.delenv("TMUX_PANE", raising=False)
    stdout = (
        "%0\t@0\tIllia\tbash\t/repo\t1\t0\t0\n%1\t@1\tIllia\tbash\t/repo\t1\t1\t0\n"
    )
    fake_proc.script(("tmux", "-L", "hive", "list-panes"), stdout=stdout)
    assert TmuxMux().current_tab_id() == "@1"


def test_current_tab_id_none_when_nothing_answers(monkeypatch, fake_proc):
    monkeypatch.delenv("TMUX_PANE", raising=False)
    fake_proc.script(("tmux", "-L", "hive", "list-panes"), stdout="")
    assert TmuxMux().current_tab_id() is None


def test_focus_pane_selects_window_then_pane(fake_proc):
    TmuxMux().focus_pane("%3")
    calls = [c for c in fake_proc.calls]
    assert calls[0] == ["tmux", "-L", "hive", "select-window", "-t", "%3"]
    assert calls[1] == ["tmux", "-L", "hive", "select-pane", "-t", "%3"]


def test_bootstrap_creates_session_when_absent(fake_proc):
    fake_proc.script(("tmux", "-L", "hive", "has-session"), returncode=1)
    fake_proc.script(("tmux", "-L", "hive", "new-session"), stdout="@0\n")
    spec = SessionSpec(
        name="myrepo",
        tabs=(
            TabSpec(
                name="agents",
                panes=(PaneSpec(name="c1", command=("/opt/hive", "run", "--restart")),),
            ),
        ),
    )
    TmuxMux().bootstrap(spec)
    assert fake_proc.count("tmux", "-L", "hive", "has-session") == 1
    assert fake_proc.count("tmux", "-L", "hive", "new-session") == 1


def test_bootstrap_is_idempotent_when_session_exists(fake_proc):
    fake_proc.script(("tmux", "-L", "hive", "has-session"), returncode=0)
    spec = SessionSpec(
        name="myrepo",
        tabs=(
            TabSpec(
                name="agents",
                panes=(PaneSpec(name="c1", command=("/opt/hive", "run", "--restart")),),
            ),
        ),
    )
    TmuxMux().bootstrap(spec)
    assert fake_proc.count("tmux", "-L", "hive", "has-session") == 1
    assert fake_proc.count("tmux", "-L", "hive", "new-session") == 0


def test_conf_bearing_instance_passes_dash_f(fake_proc):
    from pathlib import Path

    fake_proc.script(("tmux", "-L", "hive", "has-session"), returncode=0)
    TmuxMux(conf=Path("/state/hive/layouts/myrepo/tmux.conf")).session_exists("myrepo")
    assert fake_proc.calls[-1] == [
        "tmux",
        "-L",
        "hive",
        "-f",
        "/state/hive/layouts/myrepo/tmux.conf",
        "has-session",
        "-t",
        "=myrepo",
    ]


def test_plain_instance_never_passes_dash_f(fake_proc):
    TmuxMux().session_exists("myrepo")
    assert "-f" not in fake_proc.calls[-1]
