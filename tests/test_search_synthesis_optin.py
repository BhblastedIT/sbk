"""`sbk search` prints raw results by default and sends nothing to a model.

The model answer is opt-in: --synthesize for one search, or "search": {"synthesis": true} in
sbk.config.json. It runs `claude -p` with your own claude login and the log says so. --no-synthesis
is still accepted and forces raw results.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in ("tools", "tools/cross-source"):
    if str(ROOT / _p) not in sys.path:
        sys.path.insert(0, str(ROOT / _p))

_TMP = Path(tempfile.mkdtemp(prefix="sbk-search-optin-"))
CFG = _TMP / "sbk.config.json"
CFG.write_text("{}", encoding="utf-8")
os.environ["SBK_DATA_ROOT"] = str(_TMP / "data")
os.environ["SBK_CONFIG"] = str(CFG)

RESULTS = [
    {
        "source_type": "email",
        "date": "2026-01-02",
        "text": "Person A agreed on the pricing.",
        "context": "",
        "combined_score": 0.9,
        "chunk_id": "c1",
    },
]


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _set_config(cfg: dict) -> None:
    CFG.write_text(json.dumps(cfg), encoding="utf-8")
    import sbk_config

    importlib.reload(sbk_config)


@pytest.fixture
def search(monkeypatch):
    """The search engine with the index replaced by a fixed result and `claude` replaced by a recorder."""
    _set_config({})
    mod = _load("xs_l3_search_optin", "tools/cross-source/xs-l3-search.py")
    monkeypatch.setattr(
        mod, "open_lancedb", lambda: type("T", (), {"count_rows": lambda self: 1})()
    )
    monkeypatch.setattr(mod, "embed_query", lambda q: [0.0, 0.0])
    monkeypatch.setattr(mod, "hybrid_search", lambda **kw: list(RESULTS))
    monkeypatch.setattr(mod, "setup_logging", lambda **kw: None)
    claude_calls = []
    real_run = subprocess.run

    def fake_run(cmd, *a, **kw):
        if cmd and cmd[0] == "claude":
            claude_calls.append({"cmd": cmd, "input": kw.get("input", "")})
            return subprocess.CompletedProcess(
                cmd, 0, stdout=json.dumps({"result": "demo answer"}), stderr=""
            )
        return real_run(cmd, *a, **kw)

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    yield mod, claude_calls
    _set_config({})


# --- the decision ------------------------------------------------------------------------------


def test_synthesis_is_off_by_default(search):
    mod, _calls = search
    assert mod.synthesis_wanted() is False
    assert mod.synthesis_wanted(no_synthesis_flag=True) is False


def test_flag_or_config_turn_it_on_and_no_synthesis_wins(search):
    mod, _calls = search
    assert mod.synthesis_wanted(synthesize_flag=True) is True
    _set_config({"search": {"synthesis": True}})
    assert mod.synthesis_wanted() is True
    assert mod.synthesis_wanted(no_synthesis_flag=True) is False
    _set_config({"search": {"synthesis": "yes"}})  # only a real true turns it on
    assert mod.synthesis_wanted() is False


def test_config_example_ships_synthesis_off():
    cfg = json.loads((ROOT / "sbk.config.example.json").read_text(encoding="utf-8"))
    assert cfg["search"]["synthesis"] is False
    assert "_help_synthesis" in cfg["search"]


# --- xs-l3-search.py -----------------------------------------------------------------------------


def test_engine_default_prints_raw_results_and_calls_no_model(search, capsys):
    mod, calls = search
    mod.main(["pricing"])
    out = capsys.readouterr().out
    assert "## Results (1)" in out and "## Answer" not in out
    assert calls == []


def test_engine_synthesize_announces_and_uses_your_claude_login(search, capsys, caplog):
    mod, calls = search
    with caplog.at_level(logging.INFO):
        mod.main(["pricing", "--synthesize"])
    out = capsys.readouterr().out
    assert "## Answer" in out and "demo answer" in out
    assert len(calls) == 1
    assert calls[0]["cmd"][:2] == ["claude", "-p"]
    assert "Person A agreed on the pricing." in calls[0]["input"]
    assert any("with your own claude login" in r.getMessage() for r in caplog.records)
    assert not any("on the subscription" in r.getMessage() for r in caplog.records)


def test_engine_config_on_and_no_synthesis_off(search, capsys):
    mod, calls = search
    _set_config({"search": {"synthesis": True}})
    mod.main(["pricing"])
    assert len(calls) == 1
    mod.main(["pricing", "--no-synthesis"])
    assert len(calls) == 1
    assert "## Results (1)" in capsys.readouterr().out


def test_engine_refuses_both_flags(search):
    mod, _calls = search
    with pytest.raises(SystemExit) as e:
        mod.parse_args(["q", "--synthesize", "--no-synthesis"])
    assert e.value.code == 2


# --- sbk search (tools/sbk_cli.py) passes the flags through --------------------------------------


@pytest.fixture
def cli(search, monkeypatch):
    mod, calls = search
    sbk_cli = _load("sbk_cli_optin", "tools/sbk_cli.py")
    monkeypatch.setattr(sbk_cli, "_load_module", lambda name, path: mod)
    return sbk_cli, calls


def test_cli_search_default_is_raw(cli, capsys):
    sbk_cli, calls = cli
    assert sbk_cli.cmd_search(["pricing"]) == 0
    assert "## Results (1)" in capsys.readouterr().out
    assert calls == []


def test_cli_search_synthesize_flag_and_config(cli, capsys):
    sbk_cli, calls = cli
    assert sbk_cli.cmd_search(["pricing", "--synthesize"]) == 0
    assert len(calls) == 1
    _set_config({"search": {"synthesis": True}})
    assert sbk_cli.cmd_search(["pricing"]) == 0
    assert len(calls) == 2
    assert sbk_cli.cmd_search(["pricing", "--no-synthesis"]) == 0
    assert len(calls) == 2
    assert "## Answer" in capsys.readouterr().out


def test_cli_search_refuses_both_flags(cli):
    sbk_cli, _calls = cli
    with pytest.raises(SystemExit) as e:
        sbk_cli.cmd_search(["q", "--synthesize", "--no-synthesis"])
    assert e.value.code == 2


def test_cli_search_failed_answer_falls_back_to_raw(cli, capsys, monkeypatch):
    sbk_cli, _calls = cli
    mod = sbk_cli._load_module("x", Path("x"))

    def boom(cmd, *a, **kw):
        raise OSError("claude not found")

    monkeypatch.setattr(mod.subprocess, "run", boom)
    assert sbk_cli.cmd_search(["pricing", "--synthesize"]) == 0
    out = capsys.readouterr().out
    assert "The summary failed" in out and "## Results (1)" in out


# --- the masked wrapper sb-cerca.py announces what its hidden log would say ----------------------


def test_sb_cerca_announces_synthesis_only_when_asked(monkeypatch, capsys):
    cerca = _load("sb_cerca_optin", "tools/util/sb-cerca.py")
    seen = []

    class _Proc:
        def __init__(self, cmd, **kw):
            seen.append(cmd)
            self.stdout = iter(["## Results (0)\n"])

        def wait(self):
            return 0

    monkeypatch.setattr(cerca.subprocess, "Popen", _Proc)
    _set_config({})
    monkeypatch.setattr(sys, "argv", ["sb-cerca.py", "pricing"])
    assert cerca.main() == 0
    assert "your own claude login" not in capsys.readouterr().out
    monkeypatch.setattr(sys, "argv", ["sb-cerca.py", "pricing", "--synthesize"])
    assert cerca.main() == 0
    assert "with your own claude login" in capsys.readouterr().out
    _set_config({"search": {"synthesis": True}})
    monkeypatch.setattr(sys, "argv", ["sb-cerca.py", "pricing", "--grezzo"])
    assert cerca.main() == 0
    assert "your own claude login" not in capsys.readouterr().out
    assert seen[-1][-1] == "--no-synthesis"
