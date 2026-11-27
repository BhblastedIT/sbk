"""A newcomer's first --ingest on an empty data root: missing inputs are "nothing to do yet".

One regression check per stop found by running the real --ingest on a fresh install with demo
sources only (a demo SQLite, a Telegram export, a vCard, a LinkedIn export):

- L1 skips a source with no folder under the data root (never downloaded or imported) at once,
  without attempts and without a failure; with nothing downloaded at all the stages after L1
  are skipped as "nothing to read yet" and the run closes in a moment, exit 0.
- the L0 age says "not downloaded yet" instead of "age not measurable", and the KB alarm does
  not fire on a fresh install.
- the merge closes when nobody starts a contact yet, and when its result is empty.
- the entity-map cleanup builds the first map; episodes, KNOWS, the subject index, Person Deep
  Context, RQ-00, the fact index, the attachment scan and the birthday calendars run or close
  cleanly with nothing yet; the protections for data that already exists stay.
- the LinkedIn step works from the data export alone; the inventory closes with no source.
- the signal-quality note names only scores that really come from an earlier run.
- the manual sources in the plan text come from the registry, the same six the L0 refresh lists.
- the app's status verdict does not say "in step" on a fresh install.

Every check runs in a subprocess with its own SBK_DATA_ROOT, HOME and config. Demo data only, no
network, no model key, no Keychain.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CS = ROOT / "tools" / "cross-source"


def _env(tmp: Path, config: dict | None) -> dict:
    cfg = tmp / "sbk.config.json"
    cfg.write_text(json.dumps(config or {}), encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("SBK_", "ANTHROPIC_"))}
    (tmp / "home").mkdir(exist_ok=True)
    env.update(
        HOME=str(tmp / "home"),
        SBK_DATA_ROOT=str(tmp / "data"),
        SBK_CONFIG=str(cfg),
        PYTHON_KEYRING_BACKEND="keyring.backends.fail.Keyring",
        PYTHONPATH=os.pathsep.join(
            [str(ROOT / "tools"), str(CS), str(ROOT / "tools" / "secondbrain")]
        ),
    )
    return env


def _run(args: list[str], tmp: Path, config: dict | None = None, timeout: int = 180):
    return subprocess.run(
        [sys.executable, *args],
        cwd=str(ROOT),
        env=_env(tmp, config),
        capture_output=True,
        text=True,
        timeout=timeout,
        stdin=subprocess.DEVNULL,
    )


def _py(code: str, tmp: Path, config: dict | None = None):
    return _run(["-c", textwrap.dedent(code)], tmp, config)


def _load(name: str, rel: str, var: str = "m") -> str:
    return f"""
import importlib.util, sys
spec = importlib.util.spec_from_file_location({name!r}, {str(ROOT / rel)!r})
{var} = importlib.util.module_from_spec(spec)
sys.modules[{name!r}] = {var}
spec.loader.exec_module({var})
"""


_RUNNER = _load("xs_pipeline_run_t", "tools/cross-source/xs-pipeline-run.py")
_OWNER = {"owner": "Alex Demo", "own_names": ["Alex Demo"], "own_emails": ["alex@example.com"]}


def _out(r) -> str:
    return (r.stdout or "") + (r.stderr or "")


def _ok(r) -> None:
    assert r.returncode == 0 and r.stdout.strip().endswith("ok"), _out(r)[-3000:]


def _plugin_contacts(data: Path, plugin: str, rows: list[dict]) -> None:
    import pandas as pd

    d = data / plugin / "processed"
    d.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(d / "plugin-contacts.parquet", index=False)


_DEMO_PEOPLE = [
    {"source": "databases", "name": "Nora Quinn", "email": "nora@acme.example", "phone": ""},
    {"source": "databases", "name": "Leo Park", "email": "leo@globex.example", "phone": ""},
]


# --------------------------------------------------------------------------- the pipeline runner


def test_l1_skips_a_source_never_downloaded_without_attempts(tmp_path):
    (tmp_path / "data" / "telegram").mkdir(parents=True)
    _ok(
        _py(
            _RUNNER
            + """
import logging
logging.disable(logging.CRITICAL)
chiamati = []
def finto(name, script_path, *a, **k):
    chiamati.append(name)
    return True
m.run_script = finto
r = m.run_l1_pipeline()
assert chiamati == ["telegram"], chiamati
assert r["errors"] == [], r
assert "l1_phase1" in r["phases_run"], r
assert r["niente_scaricato"] is False, r
print("ok")
""",
            tmp_path,
            {**_OWNER, "enabled_sources": ["telegram", "contacts", "linkedin"]},
        )
    )


def test_l1_with_nothing_downloaded_runs_nothing(tmp_path):
    _ok(
        _py(
            _RUNNER
            + """
import logging
logging.disable(logging.CRITICAL)
def finto(*a, **k):
    raise AssertionError("no L1 script may run when nothing was downloaded")
m.run_script = finto
r = m.run_l1_pipeline()
assert r["errors"] == [] and r["niente_scaricato"] is True, r
assert m.Salto("l2_merge", "niente_da_leggere").innocuo
assert m.MOTIVI_EN["niente_da_leggere"] == "nothing to read yet"
print("ok")
""",
            tmp_path,
            _OWNER,
        )
    )


def test_ingest_on_an_empty_data_root_closes_at_once(tmp_path):
    r = _run([str(CS / "xs-pipeline-run.py"), "--ingest"], tmp_path, _OWNER)
    out = _out(r)
    assert r.returncode == 0, out[-3000:]
    assert "nothing to read yet" in out
    assert "attempt 2/2" not in out and "LINE STOP" not in out and "Traceback" not in out
    assert "age not measurable" not in out
    assert "I don't know when the KB last received data" not in out
    assert "not downloaded yet" in out
    assert not (tmp_path / "data" / "enriched" / "contacts-merged.parquet").exists()


def test_manual_sources_in_the_plan_match_the_l0_refresh(tmp_path):
    _ok(
        _py(
            _RUNNER
            + _load("xs_l0_refresh_t", "tools/cross-source/xs-l0-refresh.py", var="r0")
            + """
assert m.SORGENTI_A_MANO == ", ".join(sorted(r0.MANUALI)), (m.SORGENTI_A_MANO, sorted(r0.MANUALI))
perche = m.CATENA_PER_ID["l0_download"].perche_fuori
assert m.SORGENTI_A_MANO in perche and "WhatsApp, voice memos and LinkedIn stay manual" not in perche
print("ok")
""",
            tmp_path,
            _OWNER,
        )
    )


def test_search_index_failure_does_not_stop_the_line():
    src = (CS / "xs-pipeline-run.py").read_text(encoding="utf-8")
    i = src.index('"l3_index", ["--incremental"] if index_incremental else []')
    assert "ferma_la_linea=False" in src[i : i + 120]
    # a stage that stopped alone is reported once, not again as "planned and never run"
    assert "set(fonti_ferme)" in src


def test_a_stage_that_stopped_alone_is_declared_in_the_outcome(tmp_path):
    _ok(
        _py(
            _RUNNER
            + """
testo, rc = m.esito(
    piano=["l3_graph", "l3_index", "l3_decay"],
    eseguiti=["l3_graph", "l3_decay"],
    saltati=[],
    morti=[],
    avvisi=[],
    coda_leggibile=True,
    modo="ingest",
    fonti_non_chiuse=["l3_index"],
)
assert rc == m.EXIT_INCOMPLETO, (testo, rc)
assert "vanished" not in testo and "sources not closed: l3_index" in testo, testo
print("ok")
""",
            tmp_path,
            _OWNER,
        )
    )


def test_resume_counts_nothing_to_read_as_closed():
    src = (ROOT / "tools" / "secondbrain" / "sb_ripresa.py").read_text(encoding="utf-8")
    i = src.index("_SALTI_CHIUSI")
    assert '"nothing to read yet"' in src[i : i + 400] and '"niente_da_leggere"' in src[i : i + 400]


# --------------------------------------------------------------------------- L2 stages


def test_merge_with_no_source_that_starts_a_contact(tmp_path):
    r = _run([str(CS / "xs-l2-merge.py")], tmp_path, _OWNER)
    assert r.returncode == 0, _out(r)[-3000:]
    assert "Nothing to merge yet" in _out(r)
    assert not (tmp_path / "data" / "enriched" / "contacts-merged.parquet").exists()


def test_merge_keeps_refusing_when_an_earlier_book_exists(tmp_path):
    enr = tmp_path / "data" / "enriched"
    enr.mkdir(parents=True)
    (enr / "contacts-merged.parquet").write_bytes(b"not read")
    r = _run([str(CS / "xs-l2-merge.py")], tmp_path, _OWNER)
    assert r.returncode == 1 and "No data sources available" in _out(r), _out(r)[-3000:]


def test_merge_with_phone_only_people_does_not_crash(tmp_path):
    _plugin_contacts(
        tmp_path / "data",
        "telegram",
        [{"source": "telegram", "name": "Nora Quinn", "email": "", "phone": "+44 7700 900123"}],
    )
    r = _run([str(CS / "xs-l2-merge.py")], tmp_path, {**_OWNER, "enabled_sources": ["telegram"]})
    assert r.returncode == 0, _out(r)[-3000:]
    assert "IndexError" not in _out(r)


def test_entity_map_cleanup_builds_the_first_map(tmp_path):
    r = _run([str(CS / "xs-l2-entity-map-cleanup.py")], tmp_path, _OWNER)
    assert r.returncode == 0 and "nothing to clean" in _out(r), _out(r)[-3000:]
    cfg = {**_OWNER, "enabled_sources": ["databases"]}
    _plugin_contacts(tmp_path / "data", "databases", _DEMO_PEOPLE)
    r = _run([str(CS / "xs-l2-merge.py")], tmp_path, cfg)
    assert r.returncode == 0, _out(r)[-3000:]
    r = _run([str(CS / "xs-l2-entity-map-cleanup.py")], tmp_path, cfg)
    assert r.returncode == 0, _out(r)[-3000:]
    mappa = json.loads((tmp_path / "data" / "enriched" / "entity-map.json").read_text())
    assert "nora@acme.example" in mappa, sorted(mappa)[:10]


def test_episodes_and_knows_on_a_first_run(tmp_path):
    r = _run([str(CS / "xs-l2-episodes.py"), "--apply"], tmp_path, _OWNER)
    assert r.returncode == 0, _out(r)[-3000:]
    assert "no store tar" not in _out(r)
    assert (tmp_path / "data" / "knowledge" / "episodes").is_dir()
    assert "--copia-del-cervello" not in (CS / "xs-l2-episodes.py").read_text(encoding="utf-8")
    (tmp_path / "data" / "knowledge" / "episodes").rmdir()
    r = _run([str(CS / "xs-l2-knows.py"), "--apply"], tmp_path, _OWNER)
    assert r.returncode == 0, _out(r)[-3000:]
    assert (tmp_path / "data" / "knowledge" / "epistemic" / "knows.parquet").exists()


def test_subject_index_first_run_and_its_protection(tmp_path):
    for _ in range(2):  # the first run writes an empty index, the second keeps working
        r = _run([str(CS / "xs-l3-knows-query.py"), "build-index"], tmp_path, _OWNER)
        assert r.returncode == 0, _out(r)[-3000:]
    _ok(
        _py(
            """
import pyarrow as pa, pyarrow.parquet as pq, sbk_config as c
p = c.DATA_ROOT / "knowledge" / "epistemic" / "subject_index.parquet"
assert pq.read_metadata(p).num_rows == 0
pq.write_table(pa.Table.from_pylist([{"subject_lower": "pilot", "episode_ids": ["ep_1"]}]), p)
print("ok")
""",
            tmp_path,
            _OWNER,
        )
    )
    r = _run([str(CS / "xs-l3-knows-query.py"), "build-index"], tmp_path, _OWNER)
    assert r.returncode == 1 and "refusing to overwrite" in _out(r), _out(r)[-3000:]


def test_attachment_scan_needs_no_slack_index_when_slack_was_never_downloaded(tmp_path):
    _ok(
        _py(
            _load("xs_att_t", "tools/cross-source/xs-l2-attachment-discovery.py")
            + """
assert m.scan_slack(set(), {}, {}) == {}
print("ok")
""",
            tmp_path,
            _OWNER,
        )
    )


def test_person_deep_context_without_a_ranking(tmp_path):
    r = _run([str(CS / "xs-l2-person-deep-context.py")], tmp_path, _OWNER)
    assert r.returncode == 0 and "No people ranking yet" in _out(r), _out(r)[-3000:]
    _ok(
        _py(
            _load("xs_pdc_t", "tools/cross-source/xs-l2-person-deep-context.py")
            + """
import pandas as pd
m.RQ_DIR.mkdir(parents=True, exist_ok=True)
pd.DataFrame({"person_id": ["p_b", "p_a", ""], "score": [1.0, 5.0, 9.0]}).to_parquet(
    m.RQ_DIR / "composite-scores.parquet", index=False
)
assert m._top_from_scores(5) == [{"person_id": "p_a"}, {"person_id": "p_b"}], m._top_from_scores(5)
print("ok")
""",
            tmp_path,
            _OWNER,
        )
    )


def test_rq00_first_run_writes_nothing_and_keeps_its_protection(tmp_path):
    r = _run([str(CS / "rq-00-weight-interactions.py")], tmp_path, _OWNER)
    assert r.returncode == 0 and "nothing to weigh" in _out(r), _out(r)[-3000:]
    weights = tmp_path / "data" / "rq" / "interaction-weights.parquet"
    assert not weights.exists()
    weights.parent.mkdir(parents=True)
    weights.write_bytes(b"an earlier run")
    r = _run([str(CS / "rq-00-weight-interactions.py")], tmp_path, _OWNER)
    assert r.returncode == 1 and "exiting with error" in _out(r), _out(r)[-3000:]


def test_signal_quality_note_names_only_real_earlier_scores(tmp_path):
    for _ in range(2):  # the second run must not read the first run's empty entries as scores
        r = _run([str(CS / "xs-l2-signal-quality.py")], tmp_path, _OWNER)
        assert r.returncode == 0, _out(r)[-3000:]
        meta = json.loads(
            (tmp_path / "data" / "enriched" / "signal-quality-index.json").read_text()
        )
        assert "fonti_mancanti" not in meta["_meta"], meta["_meta"]


def test_inventory_with_no_source_downloaded(tmp_path):
    r = _run([str(CS / "xs-l1-inventario.py")], tmp_path, _OWNER)
    assert r.returncode == 0 and "nothing downloaded yet" in _out(r), _out(r)[-3000:]
    assert not (tmp_path / "data" / "inventory").exists()


# --------------------------------------------------------------------------- L3 stages


def test_calendar_interactions_missing_is_an_empty_frame(tmp_path):
    _ok(
        _py(
            """
from xs_l3_common import SBKData
assert SBKData().calendar_interactions.empty
print("ok")
""",
            tmp_path,
            _OWNER,
        )
    )


def test_fact_index_without_relationship_facts(tmp_path):
    r = _run([str(CS / "xs-l3-fact-index.py"), "--force"], tmp_path, _OWNER)
    assert r.returncode == 0 and "No relationship facts yet" in _out(r), _out(r)[-3000:]


def test_birthday_calendars_are_off_without_a_login(tmp_path):
    r = _run([str(CS / "xs-l3-birthday-calendar.py"), "--applica"], tmp_path, _OWNER)
    assert r.returncode == 0 and "No calendar login saved" in _out(r), _out(r)[-3000:]


def test_search_index_says_why_when_no_model_loads(tmp_path):
    src = (CS / "xs-l3-index.py").read_text(encoding="utf-8")
    i = src.index("model, model_name, dim = load_embedding_model(")
    blocco = src[i - 200 : i + 700]
    assert "except RuntimeError" in blocco and "needs the network once" in blocco


# --------------------------------------------------------------------------- plugins and app


def _linkedin_export(data: Path) -> None:
    d = data / "linkedin" / "raw" / "export-part1"
    d.mkdir(parents=True)
    (d / "Connections.csv").write_text(
        "Notes:\n"
        '"When exporting your connection data, you may notice that some of the email addresses are missing."\n'
        "\n"
        "First Name,Last Name,URL,Email Address,Company,Position,Connected On\n"
        "Leo,Park,https://www.linkedin.com/in/leo-park-demo,leo@globex.example,Globex Demo,CTO,12 Mar 2025\n"
        "Mia,Lane,https://www.linkedin.com/in/mia-lane-demo,,Initech Demo,Designer,20 Sep 2025\n",
        encoding="utf-8",
    )


def test_linkedin_step_from_the_data_export_alone(tmp_path):
    li = ROOT / "tools" / "linkedin"
    r = _run([str(li / "li-l1-enrich.py")], tmp_path, _OWNER)
    assert r.returncode == 0 and "nothing imported yet" in _out(r), _out(r)[-3000:]
    _linkedin_export(tmp_path / "data")
    r = _run([str(li / "li-l0-import-export.py")], tmp_path, _OWNER)
    assert r.returncode == 0, _out(r)[-3000:]
    r = _run([str(li / "li-l1-enrich.py"), "--incremental"], tmp_path, _OWNER)
    assert r.returncode == 0, _out(r)[-3000:]
    assert "Cannot load" not in _out(r) and "not found or invalid" not in _out(r)
    assert (tmp_path / "data" / "linkedin" / "processed" / "contacts-linkedin.parquet").exists()


def test_status_verdict_on_a_fresh_install(tmp_path):
    _ok(
        _py(
            _load("sb_app_t", "tools/secondbrain/sb-app.py")
            + """
assert m.verdetto([], [], [])["titolo"] == "Nothing is connected yet."
fonte = {"gruppo": "a_mano", "scaricata": "2026-11-26T10:00:00+00:00", "salute": "ok"}
v = m.verdetto([fonte], [], [])
assert v["titolo"] == "The knowledge is not built yet." and v["azione"]["arg"] == "ingest", v
print("ok")
""",
            tmp_path,
            _OWNER,
        )
    )


@pytest.mark.parametrize("stage", ["xs-l2-knows.py", "xs-l2-entity-map-cleanup.py"])
def test_first_run_stages_answer_help_without_writing(tmp_path, stage):
    r = _run([str(CS / stage), "--help"], tmp_path, _OWNER)
    assert r.returncode == 0, _out(r)[-3000:]
    assert not (tmp_path / "data").exists() or not any((tmp_path / "data").rglob("*.json"))
