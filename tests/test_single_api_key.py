"""The paid stages use one key, ANTHROPIC_API_KEY.

No queue of keys, no round-robin turn, no pause after an error, no automatic switch to a reserve
key: one client built from ANTHROPIC_API_KEY, and a rejected key stops the stage with a clear error.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in ("tools", "tools/cross-source", "tools/secondbrain"):
    if str(ROOT / _p) not in sys.path:
        sys.path.insert(0, str(ROOT / _p))

# Everything this file imports writes (if at all) under a throwaway data root.
_TMP = Path(tempfile.mkdtemp(prefix="sbk-one-key-"))
os.environ["SBK_DATA_ROOT"] = str(_TMP / "data")
os.environ["SBK_CONFIG"] = str(_TMP / "sbk.config.json")

QUEUE_NAMES = (
    "xs_chiavi",
    "SBK_CHIAVE_ANTHROPIC",
    "SBK_CHIAVI_ANTHROPIC",
    "chiave_in_uso",
    "passa_alla_riserva",
    "chiavi-anthropic",
    "_CHIAVE_DEL_LOTTO",
    "_chiave_del_run",
)


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _auth_error():
    import anthropic
    import httpx

    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return anthropic.AuthenticationError(
        "invalid x-api-key", response=httpx.Response(401, request=req), body=None
    )


# --- nothing ships or names the key queue -----------------------------------------------------


def test_key_queue_module_is_not_shipped():
    assert not (ROOT / "tools" / "cross-source" / "xs_chiavi.py").exists()


def test_no_file_reads_or_names_the_key_queue():
    files = [
        *ROOT.glob("tools/**/*.py"),
        *ROOT.glob("tools/**/*.swift"),
        *ROOT.glob("dashboard/**/*.py"),
        *ROOT.glob("tests/*.py"),
        *ROOT.glob("docs/**/*.md"),
        *ROOT.glob(".claude/**/*.md"),
        ROOT / "README.md",
        ROOT / "CLAUDE.md",
        ROOT / ".env.example",
        ROOT / "sbk.config.example.json",
    ]
    hits = []
    for f in files:
        if not f.is_file() or f.resolve() == Path(__file__).resolve():
            continue
        text = f.read_text(encoding="utf-8", errors="replace")
        hits += [f"{f.relative_to(ROOT)}: {n}" for n in QUEUE_NAMES if n in text]
    assert hits == []


# --- one client from ANTHROPIC_API_KEY ---------------------------------------------------------


@pytest.fixture
def client_mod():
    import xs_anthropic_client as m

    m.reset_client()
    yield m
    m.reset_client()


def test_client_is_built_from_anthropic_api_key(client_mod, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-not-real")
    assert client_mod.get_client().api_key == "sk-ant-test-not-real"
    for gone in (
        "chiave_in_uso",
        "usa_chiave",
        "passa_alla_riserva",
        "_chiave_dalla_coda",
        "_segna",
    ):
        assert not hasattr(client_mod, gone), gone


def test_missing_key_is_a_clear_error(client_mod, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        client_mod.get_client()


def test_rejected_key_stops_the_call_without_trying_another_key(client_mod, monkeypatch):
    import xs_l3_common
    from pipeline_decorator import PermanentAPIError

    calls = []

    class _Messages:
        def create(self, **kw):
            calls.append(kw)
            raise _auth_error()

    monkeypatch.setattr(
        client_mod, "get_client", lambda timeout=None: SimpleNamespace(messages=_Messages())
    )
    with pytest.raises(PermanentAPIError, match="ANTHROPIC_API_KEY"):
        xs_l3_common.call_claude("hello")
    assert len(calls) == 1


# --- batches: one key, nothing about keys in the state file ------------------------------------


def test_batch_is_created_once_and_a_rejected_key_is_not_retried(client_mod, monkeypatch):
    import xs_batch_api

    created = []

    class _Batches:
        def create(self, requests):
            created.append(requests)
            if len(created) == 1:
                return SimpleNamespace(id="msgbatch_demo_1")
            raise _auth_error()

    fake = SimpleNamespace(messages=SimpleNamespace(batches=_Batches()))
    monkeypatch.setattr(xs_batch_api, "_get_client", lambda: fake)
    assert xs_batch_api._crea_lotto([{"custom_id": "a"}], "demo") == "msgbatch_demo_1"
    with pytest.raises(Exception, match="invalid x-api-key"):
        xs_batch_api._crea_lotto([{"custom_id": "b"}], "demo")
    assert len(created) == 2


def test_batch_state_carries_no_key_names(tmp_path):
    import xs_batch_api

    f = tmp_path / "batch-state-demo.json"
    xs_batch_api.save_batch_state(["msgbatch_demo_1"], {"s1": "custom-1"}, f)
    assert set(json.loads(f.read_text())) == {"batch_ids", "id_mapping", "submitted_at"}
    assert xs_batch_api.load_batch_state(f) == (["msgbatch_demo_1"], {"s1": "custom-1"})
    # A state file written by an older version, with a per-batch key map, still loads.
    f.write_text(
        json.dumps(
            {"batch_ids": ["msgbatch_old"], "id_mapping": {}, "chiavi": {"msgbatch_old": "k"}}
        )
    )
    assert xs_batch_api.load_batch_state(f) == (["msgbatch_old"], {})


# --- the pipeline precondition names only ANTHROPIC_API_KEY ------------------------------------


def test_pipeline_without_key_names_only_anthropic_api_key(monkeypatch, tmp_path):
    xpr = _load("xs_pipeline_run_one_key", "tools/cross-source/xs-pipeline-run.py")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(xpr, "_TOOLS_DIR", tmp_path / "tools")  # no .env next to it
    assert xpr._chiave_api_presente() is False
    blocchi, _avvisi = xpr.precondizioni("tutto")
    msg = blocchi["chiave_api"]
    assert "ANTHROPIC_API_KEY" in msg
    assert "queue" not in msg and "xs_chiavi" not in msg
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-not-real")
    assert xpr._chiave_api_presente() is True
    blocchi, _avvisi = xpr.precondizioni("tutto")
    assert "chiave_api" not in blocchi


# --- the macOS app engine shows one key, never its value ---------------------------------------


def test_app_shows_one_key_and_never_its_value(monkeypatch, tmp_path):
    app = _load("sb_app_one_key", "tools/secondbrain/sb-app.py")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    env = tmp_path / ".env"

    [k] = app._chiavi(env)
    assert k["nome"] == "ANTHROPIC_API_KEY" and k["presente"] is False and k["origine"] is None

    env.write_text('ANTHROPIC_API_KEY=""\n', encoding="utf-8")
    assert app._chiavi(env)[0]["presente"] is False

    env.write_text("export ANTHROPIC_API_KEY=sk-ant-secret-demo-value\n", encoding="utf-8")
    [k] = app._chiavi(env)
    assert k["presente"] is True and k["origine"] == ".env" and k["paga"] is True
    assert "sk-ant-secret-demo-value" not in json.dumps(k)

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-secret-demo-value")
    [k] = app._chiavi(env)
    assert k["origine"] == "the environment"
    assert "sk-ant-secret-demo-value" not in json.dumps(k)
