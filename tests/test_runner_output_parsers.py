"""The readers of the pipeline runner's output understand what it prints now (English) and what
older versions printed (Italian), so old run logs keep reading the same way.

Readers covered: the macOS app engine (tools/secondbrain/sb-app.py), the resume logic
(sb_ripresa.py), the error catalogue (sb_errori.py), the full run (sb-full.py) and the L0 refresh
(tools/cross-source/xs-l0-refresh.py). The English outcome lines come from the runner's own
esito() function, so the test follows the runner when its wording changes.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in ("tools", "tools/cross-source", "tools/util", "tools/secondbrain"):
    if str(ROOT / _p) not in sys.path:
        sys.path.insert(0, str(ROOT / _p))


def _carica(nome: str, percorso: Path):
    spec = importlib.util.spec_from_file_location(nome, percorso)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[nome] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def moduli():
    vecchio = {k: os.environ.get(k) for k in ("SBK_DATA_ROOT", "SBK_CONFIG")}
    tmp = tempfile.mkdtemp(prefix="sbk-parsers-")
    os.environ["SBK_DATA_ROOT"] = str(Path(tmp) / "data")
    os.environ["SBK_CONFIG"] = str(Path(tmp) / "sbk.config.json")
    try:
        app = _carica("sb_app_test", ROOT / "tools" / "secondbrain" / "sb-app.py")
        full = _carica("sb_full_test", ROOT / "tools" / "secondbrain" / "sb-full.py")
        yield {
            "app": app,
            "xpr": app.XPR,
            "l0r": app.L0R,
            "err": app.ERR,
            "ripresa": app.RIPRESA,
            "full": full,
            "tmp": Path(tmp),
        }
    finally:
        for k, v in vecchio.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _esito_en(xpr, **kw) -> tuple[str, int]:
    base = {
        "piano": [],
        "eseguiti": ["a"],
        "saltati": [],
        "morti": [],
        "avvisi": [],
        "coda_leggibile": True,
    }
    base.update(kw)
    return xpr.esito(modo="ingest", **base)


def _righe_en(m) -> dict[str, tuple[str, int]]:
    xpr = m["xpr"]
    return {
        "skipped": _esito_en(
            xpr,
            saltati=[xpr.Salto("l3_x", "non_scelto")],
            fonti_non_chiuse=["calendar", "slack"],
            avvisi=["something"],
        ),
        "dead": _esito_en(xpr, morti=["L2 merge"]),
        "precondition": _esito_en(
            xpr, saltati=[xpr.Salto("l3_extract", "precondizione", "model API key")]
        ),
        "only_not_chosen": _esito_en(xpr, saltati=[xpr.Salto("l3_x", "non_scelto")]),
    }


# The same outcomes as older (Italian) versions of the runner wrote them.
RIGHE_IT = {
    "skipped": (
        "Pipeline INCOMPLETA — 1/36, fonti non chiuse: calendar, slack, "
        "saltati: l3_x (non_scelto), avvisi: 1",
        2,
    ),
    "dead": ("Pipeline FALLITA — morti: L2 merge (1/36 eseguiti)", 1),
    "precondition": (
        "Pipeline INCOMPLETA — 1/36, saltati: l3_extract (precondizione) — chiave modello",
        2,
    ),
    "only_not_chosen": ("Pipeline INCOMPLETA — 1/36, saltati: l3_x (non_scelto)", 2),
}


def _log(tmp: Path, nome: str, righe: list[str]) -> Path:
    p = tmp / nome
    p.write_text("\n".join(righe) + "\n", encoding="utf-8")
    return p


def test_runner_english_words_are_the_expected_ones(moduli):
    """If the runner's wording changes, this fails first and points at the readers to update."""
    en = _righe_en(moduli)
    assert "sources not closed: calendar, slack" in en["skipped"][0]
    assert "skipped: l3_x (not chosen)" in en["skipped"][0]
    assert "warnings: 1" in en["skipped"][0]
    assert en["dead"][0].startswith("Pipeline FAILED — dead: L2 merge")
    assert "(precondition) — model API key" in en["precondition"][0]


@pytest.mark.parametrize("lingua", ["en", "it"])
def test_app_outcome_reader(moduli, lingua):
    app = moduli["app"]
    righe = _righe_en(moduli) if lingua == "en" else RIGHE_IT
    parola = "Outcome" if lingua == "en" else "Esito"
    fine = "end" if lingua == "en" else "fine"

    def esito(chiave: str, comando: str) -> dict:
        frase, rc = righe[chiave]
        log = [f"{parola}: {frase} (exit {rc})", f"── {fine} 25/11 10:00:00 · exit {rc} · 3m"]
        return app._esito_grezzo({"comando": comando, "log": "x"}, log)

    pieno = "uv run python tools/cross-source/xs-pipeline-run.py --ingest"
    e = esito("skipped", pieno)
    assert (e["esito"], e["rc"]) == ("incompleto", 2)
    assert "slack" in e["frase"]
    assert not app._solo_note_di_stato(e["frase"], [])
    e = esito("dead", pieno)
    assert e["esito"] == "fallito"
    assert app._RE_MORTI.search(e["frase"])[1].strip() == "L2 merge"
    stadio = "--single-stage" if lingua == "en" else "--solo-stadio"
    e = esito("skipped", f"{pieno.rsplit(' ', 1)[0]} --propagate {stadio} l3_x")
    assert e["esito"] == "non_partito"


@pytest.mark.parametrize("lingua", ["en", "it"])
def test_app_live_log_reader(moduli, lingua):
    app, xpr = moduli["app"], moduli["xpr"]
    a, b, c, d = list(xpr.perimetro("ingest"))[:4]
    if lingua == "en":
        righe = [
            f"10:00:00 INFO   – {c.nome} — SKIPPED (not chosen)",
            f"10:00:01 INFO   RUNNING: {a.nome} (x.py )",
            "10:00:05 ERROR   TIMEOUT after 600 s (0.2 h)",
            f"10:00:06 INFO   RUNNING: {b.nome} (y.py )",
            "10:00:07 INFO   LOCK HELD by another instance (exit 75) after 1.0 s: the stage did NOT run",
            f"10:00:08 WARNING ⏸ PAUSE before {d.nome}: resumes when the app removes it",
        ]
    else:
        righe = [
            f"10:00:00 INFO   – {c.nome} — SALTATO (non_scelto)",
            f"10:00:01 INFO   RUNNING: {a.nome} (x.py )",
            "10:00:05 ERROR   TIMEOUT dopo 600 s",
            f"10:00:06 INFO   RUNNING: {b.nome} (y.py )",
            "10:00:07 INFO   LOCK TENUTO da un'altra istanza",
            f"10:00:08 WARNING ⏸ PAUSA prima di {d.nome}: riparte quando l'app la toglie",
        ]
    out = app._leggi_orchestratore(righe, "ingest", None)
    passi = {p["id"]: p for p in out["passi"]}
    assert passi[c.id]["stato"] == "saltato"
    assert passi[a.id]["nota"] == "over the time cap"
    assert passi[b.id]["nota"] == "lock held by another instance"


@pytest.mark.parametrize("lingua", ["en", "it"])
def test_l0_refresh_readers(moduli, lingua):
    l0r, tmp = moduli["l0r"], moduli["tmp"]
    righe = _righe_en(moduli) if lingua == "en" else RIGHE_IT
    parola = "Outcome" if lingua == "en" else "Esito"

    def log(chiave: str) -> Path:
        frase, rc = righe[chiave]
        return _log(
            tmp, f"refresh-{lingua}-{chiave}.log", ["...", f"{parola}: {frase} (exit {rc})"]
        )

    assert l0r.fonti_non_chiuse(log("skipped"), 0) == "calendar, slack"
    assert l0r._precondizione_falsa(log("precondition"), 0) == "l3_extract"
    assert l0r._ingest_chiuso(log("skipped"), 0) is False
    frase, rc = righe["only_not_chosen"]
    solo = _log(
        tmp, f"refresh-{lingua}-plain.log", [f"{parola}: {frase.split(',')[0]} (exit {rc})"]
    )
    assert l0r._ingest_chiuso(solo, 0) is True


@pytest.mark.parametrize("lingua", ["en", "it"])
def test_full_run_reader(moduli, lingua):
    full, tmp = moduli["full"], moduli["tmp"]
    righe = _righe_en(moduli) if lingua == "en" else RIGHE_IT
    parola = "Outcome" if lingua == "en" else "Esito"
    frase, rc = righe["only_not_chosen"]
    assert full._chiuso(_log(tmp, f"full-{lingua}-ok.log", [f"{parola}: {frase} (exit {rc})"]), 0)
    frase, rc = righe["precondition"]
    assert not full._chiuso(
        _log(tmp, f"full-{lingua}-no.log", [f"{parola}: {frase} (exit {rc})"]), 0
    )


@pytest.mark.parametrize("lingua", ["en", "it"])
def test_resume_point_reader(moduli, lingua):
    ripresa, xpr, tmp = moduli["ripresa"], moduli["xpr"], moduli["tmp"]
    catena = [(p.id, p.nome) for p in list(xpr.perimetro("ingest"))[:3]]
    (a_id, a), (b_id, b), (c_id, c) = catena
    if lingua == "en":
        righe = [
            "── attempt 1 · 25/11 10:00:00 · cmd",
            "=== L1 Complete — 3/3 sources in 1.0s ===",
            f"10:00:01 INFO   – {a} — SKIPPED (not chosen)",
            f"10:00:02 INFO   RUNNING: {b} (y.py )",
            "10:00:03 INFO   OK in 1.0s",
        ]
    else:
        righe = [
            "── tentativo 1 · 25/11 10:00:00 · cmd",
            "=== Ripresa da x ===",
            f"10:00:01 INFO   – {a} — SALTATO (non_scelto)",
            f"10:00:02 INFO   RUNNING: {b} (y.py )",
            "10:00:03 INFO   OK in 1.0s",
        ]
    assert ripresa.punto_di_ripresa(_log(tmp, f"ripresa-{lingua}.log", righe), catena) == c_id


@pytest.mark.parametrize(
    "riga,rc",
    [
        ("Outcome: Pipeline FAILED — dead: x (1/3 run) (exit 1)", 1),
        ("Esito: Pipeline FALLITA — morti: x (exit 1)", 1),
        ("Outcome: Pipeline INCOMPLETE — 2/3, skipped: y (non_scelto) (exit 2)", 2),
        ("Esito: Pipeline INCOMPLETA — 2/3 (exit 2)", 2),
        ("Outcome: Pipeline Complete — 3/3 (exit 0)", 0),
    ],
)
def test_error_catalogue_reads_the_run_outcome(moduli, riga, rc):
    err = moduli["err"]
    assert err.rc_del_run(["10:00:00 INFO   RUNNING: x", riga]) == rc
    assert err.rc_del_run(["no outcome here"]) is None
    assert err.ultimo_tentativo(["a", "── attempt 1 · x", "b"]) == ["── attempt 1 · x", "b"]
    assert err.ultimo_tentativo(["a", "── tentativo 1 · x", "b"]) == ["── tentativo 1 · x", "b"]
