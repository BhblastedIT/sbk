"""The macOS app's background Claude Code sessions use your own `claude` login, only with consent.

- Nothing starts without "app": {"claude_sessions": true} in sbk.config.json (or SBK_APP_CLAUDE=1),
  and SBK_APP_CLAUDE=0 wins over the config.
- With consent, the session runs the `claude` you have (here a fake one), with your environment.
- No ClickUp id is built in: the Tasks import and the Inspiration task need ids from sbk.config.json.
- The Pages view shows every page on your own Claude account.
- sb-motore.py answers stato, cose, pagine and inspiration in an empty environment.

Every check runs in a child process with a temporary HOME, data root and config, because the
modules read their paths and sbk.config.json when they are imported.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "tools" / "secondbrain"


@pytest.fixture
def clean(tmp_path):
    home = tmp_path / "home"
    data = tmp_path / "data"
    home.mkdir()
    data.mkdir()
    cfg = tmp_path / "sbk.config.json"
    cfg.write_text("{}", encoding="utf-8")
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(home),
        "TMPDIR": str(tmp_path),
        "SBK_DATA_ROOT": str(data),
        "SBK_CONFIG": str(cfg),
        "SB_INSPIRATION_RADICE": str(tmp_path / "inspiration"),
        "SB_ATTIVITA_DIR": str(tmp_path / "attivita"),
        "SB_COSE_DIR": str(tmp_path / "cose"),
        "SB_PAGINE_BASE": str(tmp_path / "pagine"),
        "SB_FINTO_LEASE": "1",
    }
    return tmp_path, cfg, env


def _run(env: dict, code: str, timeout: int = 120) -> dict:
    """Run `code` with tools/secondbrain importable; it must print one JSON line last."""
    prelude = f"import sys, json\nsys.path[:0] = [{str(APP)!r}, {str(ROOT / 'tools')!r}]\n"
    r = subprocess.run(
        [sys.executable, "-c", prelude + textwrap.dedent(code)],
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(env["TMPDIR"]),
    )
    assert r.returncode == 0, r.stderr[-2000:]
    return json.loads(r.stdout.strip().splitlines()[-1])


def _fake_claude(tmp: Path) -> Path:
    """A stand-in for `claude`: it records its arguments and prints a JSON result."""
    fake = tmp / "fake-claude"
    fake.write_text(
        "#!/bin/sh\n"
        f'printf "%s\\n" "$@" > "{tmp}/claude-args.txt"\n'
        'echo \'{"type":"result","subtype":"success","is_error":false,"num_turns":1,"result":"ok"}\'\n',
        encoding="utf-8",
    )
    fake.chmod(0o755)
    return fake


def test_consent_off_by_default_and_env_wins(clean):
    tmp, cfg, env = clean
    code = """
        import sb_own_claude as o
        print(json.dumps({"allowed": o.allowed()}))
    """
    assert _run(env, code) == {"allowed": False}
    cfg.write_text(json.dumps({"app": {"claude_sessions": True}}), encoding="utf-8")
    assert _run(env, code) == {"allowed": True}
    assert _run({**env, "SBK_APP_CLAUDE": "0"}, code) == {"allowed": False}
    cfg.write_text("{}", encoding="utf-8")
    assert _run({**env, "SBK_APP_CLAUDE": "1"}, code) == {"allowed": True}


def test_own_claude_cli_status_and_help(clean):
    _tmp, _cfg, env = clean
    for args in (["--help"], ["status"]):
        r = subprocess.run(
            [sys.executable, str(APP / "sb_own_claude.py"), *args],
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert r.returncode == 0, r.stderr
    assert "allowed: no" in r.stdout


def test_tasks_request_stops_without_consent_and_starts_nothing(clean):
    tmp, _cfg, env = clean
    env = {**env, "SB_CLAUDE_CLI": str(_fake_claude(tmp))}
    out = _run(
        env,
        f"""
        from pathlib import Path
        import sb_attivita_voce as V
        cart = Path({str(tmp / "req")!r}); cart.mkdir()
        rc = V._sessione(cart, "20261125-120000-x", {{"via": "testo"}}, "move the test to Monday")
        st = json.loads((cart / "STATO.json").read_text())
        print(json.dumps({{"rc": rc, "stato": st["stato"], "motivo": st["motivo"]}}))
        """,
    )
    assert out["rc"] == 2 and out["stato"] == "non_riuscita"
    assert "claude_sessions" in out["motivo"]
    assert not (tmp / "claude-args.txt").exists()


def test_inspiration_session_stops_without_consent(clean):
    tmp, _cfg, env = clean
    env = {**env, "SB_CLAUDE_CLI": str(_fake_claude(tmp))}
    out = _run(
        env,
        f"""
        from pathlib import Path
        import sb_inspiration_azioni as I
        I.CASA_ARCHIVIO.mkdir(parents=True, exist_ok=True)
        cart = Path({str(tmp / "idea")!r}); cart.mkdir()
        rc = I._sessione_sottofondo(cart, "Idea", "SESSIONE-COMPRENSIONE.md", "Read", "", "comprensione", ["x1"])
        es = json.loads((cart / "ESITO.json").read_text())
        print(json.dumps({{"rc": rc, "codice": es.get("codice"), "motivo": es.get("motivo")}}))
        """,
    )
    assert out["rc"] == 2 and out["codice"] == "senza-consenso"
    assert "claude_sessions" in out["motivo"]
    assert not (tmp / "claude-args.txt").exists()


def test_inspiration_session_with_consent_runs_your_own_claude(clean):
    tmp, cfg, env = clean
    cfg.write_text(json.dumps({"app": {"claude_sessions": True, "claude_model": "sonnet"}}))
    env = {**env, "SB_CLAUDE_CLI": str(_fake_claude(tmp))}
    out = _run(
        env,
        f"""
        from pathlib import Path
        import sb_inspiration_azioni as I
        I.CASA_ARCHIVIO.mkdir(parents=True, exist_ok=True)
        cart = Path({str(tmp / "idea")!r}); cart.mkdir()
        rc = I._sessione_sottofondo(cart, "Idea", "SESSIONE-COMPRENSIONE.md", "Read", "", "comprensione", ["x1"])
        proc = json.loads((cart / "processo.json").read_text())
        print(json.dumps({{"rc": rc, "claude_esito": json.loads((cart / "claude-esito.json").read_text()),
                          "sessione": proc.get("sessione_id", ""), "account": "account" in proc}}))
        """,
    )
    args = (tmp / "claude-args.txt").read_text().split("\n")
    assert "-p" in args and args[args.index("--model") + 1] == "sonnet"
    assert out["claude_esito"]["result"] == "ok"
    assert out["sessione"].startswith("inspiration-comprensione-") and not out["account"]


def test_background_loops_wait_for_consent(clean):
    tmp, _cfg, env = clean
    out = _run(
        env,
        """
        import sb_inspiration_azioni as I
        I.CASA_ARCHIVIO.mkdir(parents=True, exist_ok=True)
        I._scrivi_json(I.SMISTAMENTO_GIRO, {"acceso": True})
        sorting = I.smistamento_giro()
        I._scrivi_json(I.ARRETRATI_GIRO, {"impostazioni": {"voci_per_gruppo": 2, "equivalente_per_sessione": 1}})
        backlog = I.arretrati_giro("accendi")
        cfg = I._leggi_cfg(I.ARRETRATI_GIRO)
        print(json.dumps({"sorting": sorting, "backlog": backlog, "acceso": cfg.get("acceso"),
                          "codice": (cfg.get("fermo") or {}).get("codice")}))
        """,
    )
    assert out["sorting"].startswith("sorting waits") and "claude_sessions" in out["sorting"]
    assert out["acceso"] is False and out["codice"] == "senza-consenso"


def test_no_built_in_clickup_ids(clean):
    _tmp, _cfg, env = clean
    out = _run(
        env,
        """
        import os
        os.environ.pop("SB_CLICKUP_FINTO", None)
        import sb_cose as C, sb_attivita as A, sb_inspiration_azioni as I
        try:
            C._leggi_clickup(); lista = "read"
        except C.Errore as e:
            lista = e.chiave
        imp = A.importa()
        try:
            I.crea_task({"id": "x1", "titolo": "t", "url": "", "pareri": [],
                         "destinazione": {}, "lavorazione": {"perche": {}, "piano": {}, "domande": []}}, "/tmp/x")
            task = "created"
        except I.Errore as e:
            task = str(e)
        print(json.dumps({"LISTA": C.LISTA, "lista": lista, "importa": imp, "BACKLOG": I.BACKLOG,
                          "OWNER": I.OWNER_CLICKUP, "task": task}))
        """,
    )
    assert out["LISTA"] == "" and out["lista"] == "errore_lista"
    assert out["importa"]["ok"] is False and "tasks_list" in out["importa"]["errore"]
    assert out["BACKLOG"] == "" and out["OWNER"] == ""
    assert "clickup_lists" in out["task"]


def test_clickup_ids_from_config(clean):
    _tmp, cfg, env = clean
    cfg.write_text(
        json.dumps(
            {
                "clickup": {"tasks_list": "901", "user_id": "42"},
                "inspiration": {"clickup_lists": {"main": "902"}},
            }
        )
    )
    out = _run(
        env,
        """
        import sb_cose as C, sb_inspiration_azioni as I
        d = I.task_proposta({"id": "x1", "titolo": "t", "url": "", "pareri": [], "destinazione": {},
                             "lavorazione": {"perche": {}, "piano": {}, "domande": []}}, "/tmp/x")
        print(json.dumps({"LISTA": C.LISTA, "BACKLOG": I.BACKLOG, "assignees": d["assignees"]}))
        """,
    )
    assert out == {"LISTA": "901", "BACKLOG": "902", "assignees": [42]}


def test_pages_are_on_your_own_account(clean):
    tmp, _cfg, env = clean
    base = tmp / "pagine"
    base.mkdir()
    row = {
        "id": "a1",
        "url": "https://claude.ai/artifact/a1",
        "titolo": "Demo page",
        "ultima": "2026-11-20T10:00:00+00:00",
        "account": None,
        "certezza": "non_noto",
    }
    (base / "registro.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
    out = _run(
        env,
        """
        import sb_pagine as P
        s = P.stato()
        p = s["pagine"][0]
        print(json.dumps({"principale": p["principale"], "frase": p["frase_account"], "account": p["account"],
                          "solo_online": p["solo_online"], "gruppi": [a["titolo"] for a in s["account"]],
                          "spiegazione": s["spiegazione"]}))
        """,
    )
    assert out["principale"] is True and out["account"]
    assert out["frase"] == "Online with your Claude account"
    assert out["gruppi"] == ["On your Claude account"]
    assert "no longer known" not in out["spiegazione"]


def test_no_account_rotation_in_the_app():
    pattern = (
        "AccountPool",
        "account_runner",
        "POOL_SWITCH",
        "quota-effective",
        "autorotate",
        "SB_PANE_KEY",
    )
    hits = []
    for p in APP.rglob("*"):
        if (
            p.is_file()
            and p.suffix in (".py", ".swift", ".md", ".json")
            and "__pycache__" not in p.parts
        ):
            text = p.read_text(encoding="utf-8", errors="replace")
            hits += [f"{p.relative_to(ROOT)}: {w}" for w in pattern if w in text]
    assert not hits, hits


@pytest.mark.parametrize("cmd", [["stato"], ["cose"], ["pagine"], ["inspiration"]])
def test_motore_answers_in_a_clean_env(clean, cmd):
    _tmp, _cfg, env = clean
    r = subprocess.run(
        [sys.executable, str(APP / "sb-motore.py"), *cmd],
        env={k: v for k, v in env.items() if not k.startswith("SB_")} | {"SB_FINTO_LEASE": "1"},
        capture_output=True,
        text=True,
        timeout=240,
    )
    assert r.returncode == 0, r.stderr[-2000:]
    assert json.loads(r.stdout.strip().splitlines()[-1])
