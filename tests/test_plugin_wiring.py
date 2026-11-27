"""How the plugins on the generic intake and on the mail/calendar slots are wired into
the kernel: the runner's L1 lists and change detection, enabled_sources, the fact
taxonomy, the pid lock on a fresh data root and the dashboard's step names.

Each check runs in a subprocess with its own empty SBK_DATA_ROOT and config, so the
module-level constants of sbk_config never leak between tests. No network.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _py(code: str, tmp: Path, config: dict | None = None) -> subprocess.CompletedProcess:
    cfg = tmp / "sbk.config.json"
    owner = {"owner": "Alex Demo", "own_emails": ["alex@personal.example"]}
    cfg.write_text(json.dumps({**owner, **(config or {})}), encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith("SBK_")}
    env.update(
        SBK_DATA_ROOT=str(tmp / "data"),
        SBK_CONFIG=str(cfg),
        SBK_CONTAINERIZED="1",
        PYTHONPATH=os.pathsep.join(
            [
                str(ROOT / "tools"),
                str(ROOT / "tools" / "cross-source"),
                str(ROOT / "tools" / "secondbrain"),
            ]
        ),
    )
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


_LOAD_RUNNER = """
import importlib.util, sys
spec = importlib.util.spec_from_file_location(
    "xs_pipeline_run_under_test", "tools/cross-source/xs-pipeline-run.py")
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)
"""


def test_runner_lists_the_plugin_l1_scripts(tmp_path):
    r = _py(
        _LOAD_RUNNER
        + """
for k in ("zoom", "github_intake", "databases"):
    assert k in m.L1_SCRIPTS_BASE and m.L1_SCRIPTS_BASE[k].is_file(), k
import sorgenti
assert sorgenti.sorgente_di("github_intake") == "github"
assert m._FONTE_DELLO_STADIO["github_intake"] == "github"
print("ok")
""",
        tmp_path,
    )
    assert r.returncode == 0 and r.stdout.strip() == "ok", r.stderr[-2000:]


def test_plugin_intake_files_mark_merge_and_knowledge_to_redo(tmp_path):
    r = _py(
        _LOAD_RUNNER
        + """
import os, pandas as pd
w = m.WATCHED_FILES["plugin_intake"]
assert not w.exists()
assert m.WATCHED_CONSUMERS["plugin_intake"] == ("l2_merge", "l2_knowledge_extract")
d = m.DATA_ROOT / "demo-plugin" / "processed"
d.mkdir(parents=True)
pd.DataFrame({"name": ["Ada Demo"], "email": ["ada@fabrikam.example"]}).to_parquet(
    d / "plugin-contacts.parquet")
pd.DataFrame({"ts": ["2026-01-01"], "kind": ["issue"], "title": ["x"], "participants": [""]}
    ).to_parquet(d / "plugin-interactions.parquet")
os.utime(d / "plugin-contacts.parquet", (1000, 1000))
os.utime(d / "plugin-interactions.parquet", (2000, 2000))
assert w.exists() and w.stat().st_mtime == 2000
changes = m.detect_changes()
assert changes["plugin_intake"] is True
redo = m.stadi_da_rifare(changes)
assert redo.get("l2_merge") and redo.get("l2_knowledge_extract"), redo
print("ok")
""",
        tmp_path,
    )
    assert r.returncode == 0 and r.stdout.strip() == "ok", r.stderr[-2000:]


def test_enabled_microsoft365_keeps_the_email_and_calendar_stages(tmp_path):
    r = _py(
        _LOAD_RUNNER
        + """
saltate = set()
kept = m._solo_abilitate(dict(m.L1_SCRIPTS_BASE), saltate)
assert set(kept) == {"email", "calendar"}, sorted(kept)
assert "email_allegati" not in kept and "email" in m.L1_SCRIPTS_BASE
print("ok")
""",
        tmp_path,
        {"enabled_sources": ["microsoft365"]},
    )
    assert r.returncode == 0 and r.stdout.strip() == "ok", r.stderr[-2000:]


def test_enabled_github_keeps_its_intake_stage(tmp_path):
    r = _py(
        _LOAD_RUNNER
        + """
kept = m._solo_abilitate(dict(m.L1_SCRIPTS_BASE), set())
assert set(kept) == {"github_intake"}, sorted(kept)
print("ok")
""",
        tmp_path,
        {"enabled_sources": ["github"]},
    )
    assert r.returncode == 0 and r.stdout.strip() == "ok", r.stderr[-2000:]


def test_plugin_communication_facts_are_aggregates(tmp_path):
    r = _py(
        """
import knowledge_taxonomy as t
for a in ("communication.zoom_interactions", "communication.github_first_contact",
          "communication.demo_tracker_last_contact"):
    assert t.classe_temporale(a) == t.AGGREGATO, a
assert t.classe_temporale("communication.email_total") == t.AGGREGATO
assert t.classe_temporale("communication.meeting_topic") == t.EVENTO
print("ok")
""",
        tmp_path,
    )
    assert r.returncode == 0 and r.stdout.strip() == "ok", r.stderr[-2000:]


def test_pid_lock_on_a_data_root_that_does_not_exist_yet(tmp_path):
    r = _py(
        """
import sbk_config
assert not sbk_config.DATA_ROOT.exists()
assert sbk_config.acquire_pid_lock("wiring-test")
assert (sbk_config.DATA_ROOT / "wiring-test.pid").is_file()
sbk_config.release_pid_lock("wiring-test")
print("ok")
""",
        tmp_path,
    )
    assert r.returncode == 0 and r.stdout.strip() == "ok", r.stderr[-2000:]


def test_dashboard_step_names_of_the_new_sources(tmp_path):
    r = _py(
        """
import sb_errori as e
assert e.sorgente_del_passo("imap-caldav") == "imap-caldav"
assert e.sorgente_del_passo("microsoft365") == "microsoft365"
assert e.sorgente_del_passo("inv-github") == "github"
assert e.sorgente_del_passo("email-allegati") == "email"
for p in ("microsoft365", "imap-caldav", "zoom", "inv-github"):
    assert e.famiglia_del_passo(p) == "giro", p
print("ok")
""",
        tmp_path,
    )
    assert r.returncode == 0 and r.stdout.strip() == "ok", r.stderr[-2000:]


def test_l0_plan_step_names_match_the_dashboard(tmp_path):
    r = _py(
        """
import importlib.util, sys
spec = importlib.util.spec_from_file_location("l0r", "tools/cross-source/xs-l0-refresh.py")
m = importlib.util.module_from_spec(spec); sys.modules["l0r"] = m; spec.loader.exec_module(m)
import sb_errori as e
names = [p.nome for p in m.PIANO]
assert set(names) <= set(e.PASSI_GIRO), sorted(set(names) - set(e.PASSI_GIRO))
for p in m.PIANO:
    assert e.sorgente_del_passo(p.nome) == p.sorgente, (p.nome, p.sorgente)
assert "databases" in m.MANUALI
print("ok")
""",
        tmp_path,
    )
    assert r.returncode == 0 and r.stdout.strip() == "ok", r.stderr[-2000:]


_NEW_PLUGINS = (
    "hubspot",
    "pipedrive",
    "fireflies",
    "fathom",
    "granola",
    "telegram",
    "teams",
    "atlassian",
    "linear",
    "contacts",
)


def test_batch_two_and_three_plugins_are_wired(tmp_path):
    r = _py(
        _LOAD_RUNNER
        + f"""
import sorgenti, json, secrets_adapter
new = {_NEW_PLUGINS!r}
for k in new:
    s = sorgenti.SORGENTI[k]
    assert k in m.L1_SCRIPTS_BASE and m.L1_SCRIPTS_BASE[k].is_file(), k
    assert m.L1_SCRIPTS_BASE[k].as_posix().endswith(s.l1), (k, s.l1)
    assert s.dato_in and not any(p.startswith("processed/") for p in s.dato_in), k
cfg = json.load(open("sbk.config.example.json"))
for k in new:
    assert k in cfg and cfg[k].get("_help"), k
env = open(".env.example").read()
for v in ("HUBSPOT_CLIENT_ID", "PIPEDRIVE_API_TOKEN", "FIREFLIES_API_KEY", "FATHOM_API_KEY",
          "GRANOLA_API_KEY", "ATLASSIAN_API_TOKEN", "LINEAR_API_KEY", "SBK_GCONTACTS_TOKEN_"):
    assert v in env, v
mapped = set(secrets_adapter._ENV_MAP)
assert ("sbk-hubspot", "default") not in mapped and ("sbk-pipedrive", "refresh-token") not in mapped
assert m.WATCHED_CONSUMERS["contacts_iphone"] == ("l2_merge",)
assert str(m.WATCHED_FILES["contacts_iphone"]).endswith("contacts/processed/contacts-iphone.parquet")
saltate = set()
assert set(m._solo_abilitate(dict(m.L1_SCRIPTS_BASE), saltate)) == {{"telegram", "contacts"}}
print("ok")
""",
        tmp_path,
        {"enabled_sources": ["telegram", "contacts"]},
    )
    assert r.returncode == 0 and r.stdout.strip() == "ok", r.stderr[-2000:]


def test_batch_two_and_three_downloads_are_planned(tmp_path):
    r = _py(
        f"""
import importlib.util, sys
spec = importlib.util.spec_from_file_location("l0r", "tools/cross-source/xs-l0-refresh.py")
m = importlib.util.module_from_spec(spec); sys.modules["l0r"] = m; spec.loader.exec_module(m)
import sb_errori as e
planned = {{p.sorgente for p in m.PIANO}}
for k in {_NEW_PLUGINS!r}:
    assert (k in planned) != (k in m.MANUALI), k
assert "telegram" in m.MANUALI and "telegram" not in planned
step = {{p.nome: p for p in m.PIANO}}["contacts-google"]
assert step.sorgente == "contacts" and e.sorgente_del_passo("contacts-google") == "contacts"
assert m.controlla_copertura() == []
print("ok")
""",
        tmp_path,
    )
    assert r.returncode == 0 and r.stdout.strip() == "ok", r.stderr[-2000:]
