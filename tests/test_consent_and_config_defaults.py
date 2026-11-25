"""Model consent in the monitor, and no built-in demo accounts or organisations.

- Every monitor job that sends data to a model is skipped unless SBK_MONITOR_MODEL=1
  (or --with-model), even with an API key, and logs a skip line.
- Mailboxes, calendar accounts and your own organisations come from configuration or data,
  never from names written in the code.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import logging
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DEMO = ("acme", "globex", "initech", "northwind")


@pytest.fixture
def env(monkeypatch, tmp_path):
    data = tmp_path / "data"
    (data / "emails" / "box1").mkdir(parents=True)
    (data / "emails" / "accounts.json").write_text(json.dumps({"box1": {"email": "me@demo.example"}}))
    (data / "emails" / "box2").mkdir(parents=True)
    (data / "emails" / "box2" / "messages.parquet").write_bytes(b"")
    (data / "calendars" / "box1").mkdir(parents=True)
    cfg = tmp_path / "sbk.config.json"
    cfg.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("SBK_DATA_ROOT", str(data))
    monkeypatch.setenv("SBK_CONFIG", str(cfg))
    monkeypatch.delenv("SBK_MONITOR_MODEL", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-real")
    for p in (ROOT / "tools", ROOT / "tools" / "cross-source"):
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))
    import sbk_config

    importlib.reload(sbk_config)
    return data, cfg, sbk_config


def test_no_demo_accounts_or_organisations_by_default(env):
    data, _cfg, c = env
    assert not c.OWN_ORG_NAMES and not c.INTERNAL_DOMAINS and not c.OWN_ORG_ALIASES
    assert c.mail_labels() == ["box1", "box2"]
    assert c.calendar_labels() == ["box1"]


def test_organisations_from_config(env, monkeypatch):
    _data, cfg, c = env
    cfg.write_text(
        json.dumps(
            {"organisations": {"names": ["Demo Co"], "domains": {"Demo Co": ["democo.example"]},
                               "aliases": {"DCO": "Demo Co"}}}
        ),
        encoding="utf-8",
    )
    importlib.reload(c)
    names, domains = c.OWN_ORG_NAMES, c.INTERNAL_DOMAINS
    assert names == {"demo co"}
    assert domains == {"democo.example"}
    assert c.OWN_ORG_DOMAINS == {"Demo Co": ["democo.example"]}
    assert c.is_internal_domain("DemoCo.example")


def _load_monitor(monkeypatch, spawned):
    class _Proc:
        returncode = 0
        pid = 1
        stdout = ""
        stderr = ""

        def poll(self):
            return 0

    def fake(cmd, *a, **k):
        spawned.append(" ".join(str(x) for x in cmd))
        return _Proc()

    monkeypatch.setattr(subprocess, "Popen", fake)
    monkeypatch.setattr(subprocess, "run", fake)
    monkeypatch.syspath_prepend(str(ROOT / "tools" / "monitoring"))
    spec = importlib.util.spec_from_file_location("sbk_monitor_t", ROOT / "tools/monitoring/sbk-monitor.py")
    mon = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mon)
    mon.notify = lambda *a, **k: None
    return mon


def test_monitor_model_jobs_need_consent(env, monkeypatch, caplog):
    data, _cfg, c = env
    spawned: list[str] = []
    mon = _load_monitor(monkeypatch, spawned)
    caplog.set_level(logging.DEBUG, logger="sbk-monitor")

    soon = (datetime.now(UTC) + timedelta(minutes=30)).isoformat()
    c.PLAUD_DIR.mkdir(parents=True, exist_ok=True)
    (c.PLAUD_DIR / "m.txt").write_text("demo transcript")
    monkeypatch.setattr(
        mon.pipeline_dlq,
        "get_pending_retries",
        lambda: [{"script_name": "cross-source/xs-l3-brief.py", "id": "f1", "source": "s"}],
    )
    retried: list = []
    monkeypatch.setattr(mon.pipeline_dlq, "record_retry", lambda *a, **k: retried.append(a))

    def run_all():
        mon.run_digest_cycle()
        mon._schedule_upcoming_briefs([{"id": "e1", "summary": "x", "start": {"dateTime": soon}}])
        mon._check_new_meetings_inner()
        mon._check_dlq_retries_inner()
        return mon.run_intelligence_cycle([{"from": "a@demo.example", "subject": "s"}], {})

    assert run_all() is None
    assert not [s for s in spawned if any(m in s for m in ("xs-l3-digest", "xs-l3-brief", "mt-capture"))]
    assert not retried
    skipped = {r.getMessage().split("(")[1].split(")")[0] for r in caplog.records
               if r.getMessage().startswith("Model call skipped")}
    assert skipped == set(mon.MODEL_JOBS)

    monkeypatch.setenv("SBK_MONITOR_MODEL", "1")
    mon.BRIEFS_DIR.mkdir(parents=True, exist_ok=True)
    spawned.clear()
    mon.run_digest_cycle()
    mon._schedule_upcoming_briefs([{"id": "e2", "summary": "x", "start": {"dateTime": soon}}])
    mon._check_new_meetings_inner()
    assert any("xs-l3-digest" in s for s in spawned)
    assert any("xs-l3-brief.py --hours 1" in s for s in spawned)
    assert any("mt-capture.py" in s for s in spawned)


def test_monitor_calendar_account_from_config(env, monkeypatch):
    spawned: list[str] = []
    mon = _load_monitor(monkeypatch, spawned)
    assert mon.calendar_account() == "box1"
    monkeypatch.setattr(mon, "user_cfg", lambda p, d=None: "cal" if p == "calendar.account" else d)
    assert mon.calendar_account() == "cal"


@pytest.mark.parametrize(
    "rel",
    [
        "tools/monitoring/sbk-monitor.py",
        "tools/cross-source/xs-util-pipeline-status.py",
        "tools/cross-source/xs-l3-email-filter.py",
        "tools/email/em-l1-extract-attachments.py",
        "tools/email/em-l2-extract-attachments.py",
        "dashboard/app/core/cascade_monitor.py",
        "tools/cross-source/xs-l2-network-profiles.py",
        "tools/chatgpt/cg-l1-enrich.py",
        "tools/cross-source/xs_l3_routing.py",
        "tools/cross-source/l4-05-confidence-recal.py",
        "tools/cross-source/l4-06-partial-name-resolve.py",
        "tools/cross-source/xs-l3-shadow-extract.py",
        "tools/cross-source/xs-l2-org-enrich.py",
        "tools/cross-source/xs-l3-graph.py",
    ],
)
def test_no_demo_company_in_code_paths(rel):
    text = (ROOT / rel).read_text(encoding="utf-8").lower()
    assert not [w for w in DEMO if w in text], rel
