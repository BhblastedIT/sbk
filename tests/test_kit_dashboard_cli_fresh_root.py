"""The newcomer interfaces on an empty or fresh data root: the web dashboard and the sbk CLI.

- The FastAPI app, started with TestClient on an empty data root, answers every GET route it declares (path
  parameters filled with demo values, with and without demo query parameters) without a 5xx, and the process
  survives: no sys.exit from a tool module may end the server (the bridge turns SystemExit into RuntimeError,
  and a middleware answers 500 for any SystemExit that still reaches a request).
- xs-l3-followup.py load_action_items() returns an empty frame when the paid extract has not run yet.
- The pipeline grid reads the English columns xs-util-pipeline-status.py writes ('Status', 'Source / Stage'...)
  and still accepts a pipeline-status.json with the old Italian ones.
- `sbk lookup`, `sbk brief` and `sbk search` work on a root without email data (no threads.parquet) and on an
  empty root.

Every check runs in a subprocess with its own SBK_DATA_ROOT, HOME and config. Demo data only, outbound network
refused, no model key, no Keychain, the embedding warm-up and the scheduler switched off.
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

_NO_NETWORK = """
import socket, sys
_orig_connect = socket.socket.connect
def _blocked(self, addr):
    if self.family in (socket.AF_INET, socket.AF_INET6):
        host = addr[0] if isinstance(addr, tuple) else str(addr)
        if host not in ("127.0.0.1", "::1", "localhost"):
            raise OSError("network blocked by the test")
    return _orig_connect(self, addr)
socket.socket.connect = _blocked
"""

# Start the app in-process without the embedding warm-up and without the scheduler (both irrelevant to routes).
_APP = (
    _NO_NETWORK
    + f"""
sys.path.insert(0, {str(ROOT / "dashboard")!r})
from app.core import sbk_bridge, scheduler
sbk_bridge.SBKBridge.warmup = lambda self: None
scheduler.AutoScheduler.start = lambda self: None
from app.main import app
from fastapi.testclient import TestClient
from fastapi.routing import APIRoute
"""
)

DEMO_QUERY = {
    "pid": "p_demo01",
    "person_id": "p_demo01",
    "email": "rowan@example.com",
    "emails": "rowan@example.com",
    "name": "Rowan Demo",
    "q": "Rowan",
    "query": "Rowan",
    "a": "p_demo01",
    "b": "p_demo02",
    "target": "Rowan Demo",
    "person": "Rowan Demo",
}


def _env(tmp: Path, config: dict | None) -> dict:
    cfg = tmp / "sbk.config.json"
    cfg.write_text(json.dumps(config or {}), encoding="utf-8")
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("SBK_", "ANTHROPIC_", "OPENAI_", "GEMINI_"))
    }
    (tmp / "home").mkdir(exist_ok=True)
    (tmp / "data").mkdir(exist_ok=True)
    env.update(
        HOME=str(tmp / "home"),
        SBK_DATA_ROOT=str(tmp / "data"),
        SBK_CONFIG=str(cfg),
        PYTHON_KEYRING_BACKEND="keyring.backends.fail.Keyring",
        HF_HOME=str(tmp / "hf"),
        HF_HUB_OFFLINE="1",
        TRANSFORMERS_OFFLINE="1",
        PYTHONDONTWRITEBYTECODE="1",
        PYTHONPATH=os.pathsep.join([str(ROOT / "tools"), str(CS)]),
    )
    return env


def _py(code: str, tmp: Path, config: dict | None = None, timeout: int = 240):
    # A request that ends the app (the bug these tests guard) can leave TestClient waiting: the timeout fails it.
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)],
        cwd=str(ROOT),
        env=_env(tmp, config),
        capture_output=True,
        text=True,
        timeout=timeout,
        stdin=subprocess.DEVNULL,
    )


def _cli(args: list[str], tmp: Path, config: dict | None = None):
    return subprocess.run(
        [sys.executable, str(ROOT / "tools" / "sbk_cli.py"), *args],
        cwd=str(ROOT),
        env=_env(tmp, config),
        capture_output=True,
        text=True,
        timeout=300,
        stdin=subprocess.DEVNULL,
    )


def _result(proc) -> dict:
    line = [x for x in proc.stdout.splitlines() if x.startswith("RESULT ")]
    assert line, (
        f"rc {proc.returncode}\nSTDOUT:\n{proc.stdout[-3000:]}\nSTDERR:\n{proc.stderr[-6000:]}"
    )
    return json.loads(line[-1][len("RESULT ") :])


_OWNER = {"owner": "Casey Demo", "own_emails": ["casey@example.com"], "own_names": ["casey demo"]}


def _seed_people(data: Path) -> None:
    """Three demo people in the merged address book (one with a phone and no email), and no email data at all."""
    import pandas as pd

    enriched = data / "enriched"
    enriched.mkdir(parents=True, exist_ok=True)
    when = pd.Timestamp("2026-11-20T10:00:00Z")
    pd.DataFrame(
        {
            "person_id": ["p_demo01", "p_demo02", "p_demo03"],
            "email": ["rowan@example.com", "sky@example.org", ""],
            "all_emails": ["rowan@example.com", "sky@example.org", ""],
            "name": ["Rowan Demo", "Sky Sample", "Pat Phoneonly"],
            "organization": ["Example Co", "Sample Org", ""],
            "domain": ["example.com", "example.org", ""],
            "phone_primary": ["", "", "+12025550123"],
            "score": [3.5, 1.0, 0.5],
            "source_count": [2, 1, 1],
            "is_internal": [False, False, False],
            "is_automated": [False, False, False],
            "email_total_msgs": [0, 0, 0],
            "cal_events": [0, 0, 0],
            "plaud_meetings": [0, 0, 0],
            "tactiq_meetings": [0, 0, 0],
            "last_contact": [when, when, when],
            "first_contact": [when, when, when],
            "last_contact_source": ["databases", "telegram", "whatsapp"],
            "linkedin_url": ["", "", ""],
            "linkedin_headline": ["", "", ""],
        }
    ).to_parquet(enriched / "contacts-merged.parquet", index=False)
    (enriched / "entity-map.json").write_text(
        json.dumps(
            {
                "rowan@example.com": {
                    "person_id": "p_demo01",
                    "all_emails": ["rowan@example.com"],
                    "primary_email": "rowan@example.com",
                    "canonical_name": "Rowan Demo",
                },
                "sky@example.org": {
                    "person_id": "p_demo02",
                    "all_emails": ["sky@example.org"],
                    "primary_email": "sky@example.org",
                    "canonical_name": "Sky Sample",
                },
            }
        ),
        encoding="utf-8",
    )


def _status_file(data: Path, italian: bool) -> None:
    """A pipeline-status.json with two rows, in the English columns of xs-util-pipeline-status.py or the old ones."""
    en = {
        "Status": "OK",
        "ID": "L0.20",
        "Age h": "2.5",
        "Source / Stage": "Demo databases L0",
        "Type": "Manual",
        "Connection": "SQLite file",
        "Auth": "None",
        "In L3 NLP": "No",
        "In L5 Vector": "Yes",
        "Freq target": "on request",
        "Records": "3",
        "Last run": "2026-11-26 10:00",
        "Action link": "",
        "Script": "db-l0-download.py",
        "Run command": "uv run python3 tools/databases/db-l0-download.py",
        "Cost/run": "0",
        "Size MB": "0.1",
        "Depth": "Full",
        "%": "100%",
        "Gap": "",
    }
    old_names = {
        "Status": "Stato",
        "Source / Stage": "Sorgente / Fase",
        "Age h": "Età h",
        "Type": "Tipo",
        "Connection": "Connessione",
        "Last run": "Ultimo run",
        "Action link": "Link azione",
        "Run command": "Comando run",
        "Cost/run": "Costo/run",
        "Depth": "Profondità",
    }
    rows = [en, {**en, "Status": "Missing", "ID": "L1.20", "Source / Stage": "Demo databases L1"}]
    if italian:
        rows = [{old_names.get(k, k): v for k, v in r.items()} for r in rows]
    data.mkdir(parents=True, exist_ok=True)
    (data / "pipeline-status.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-11-26 10:00",
                "total_rows": len(rows),
                "header": list(rows[0]),
                "data": rows,
            }
        ),
        encoding="utf-8",
    )


# ── Web dashboard ────────────────────────────────────────────────────────────────────────────────────────────


def test_every_get_route_on_an_empty_root_answers_without_5xx_and_the_server_survives(tmp_path):
    code = (
        _APP
        + f"""
import json, re, urllib.parse
DEMO = {DEMO_QUERY!r}
paths = sorted({{r.path for r in app.routes if isinstance(r, APIRoute) and "GET" in r.methods}})
bad, seen = [], 0
with TestClient(app, raise_server_exceptions=False) as c:
    for path in paths:
        if "stream" in path:
            continue  # server-sent events never end
        url = re.sub(r"\\{{[^}}]+\\}}", "demo", path)
        for u in (url, url + "?" + urllib.parse.urlencode(DEMO)):
            r = c.get(u)
            seen += 1
            if r.status_code >= 500:
                bad.append(f"{{r.status_code}} {{u}} {{r.text[:200]}}")
    alive = c.get("/health").status_code
print("RESULT " + json.dumps({{"routes": len(paths), "requests": seen, "bad": bad, "alive": alive}}))
"""
    )
    proc = _py(code, tmp_path, _OWNER)
    res = _result(proc)
    assert res["routes"] > 150, res
    assert res["bad"] == [], "\n".join(res["bad"])
    assert res["alive"] == 200


def test_base_page_fetches_on_an_empty_root(tmp_path):
    """What a browser asks for on the first page: the page, the notifications badge, the home partials."""
    code = (
        _APP
        + """
import json
urls = ["/", "/graph", "/home", "/api/notifications", "/api/notifications/panel", "/api/focus-mode",
        "/api/focus-mode/partial", "/api/briefing/partial", "/api/briefing/preview", "/partials/home_actions",
        "/partials/home_focus", "/partials/home_reachout", "/pipeline", "/partials/pipeline_grid", "/system",
        "/monitor", "/search", "/chat", "/api/chat/status", "/person", "/partials/person_card?q=Rowan"]
out = {}
with TestClient(app, raise_server_exceptions=False) as c:
    for u in urls:
        out[u] = c.get(u).status_code
    out["/health after"] = c.get("/health").status_code
print("RESULT " + json.dumps(out))
"""
    )
    res = _result(_py(code, tmp_path, _OWNER))
    assert all(s < 500 for s in res.values()), res
    assert res["/api/notifications"] == 200
    assert res["/chat"] == 200, "the chat page opens without a model key"
    assert res["/health after"] == 200


def test_every_hx_get_in_the_templates_has_a_get_route(tmp_path):
    """A partial the templates load with hx-get must exist (the thread viewer was linked as /partials/thread_viewer)."""
    code = (
        _APP
        + f"""
import json, pathlib, re
routes = [r for r in app.routes if isinstance(r, APIRoute) and "GET" in r.methods]
missing, checked = [], 0
for f in sorted(pathlib.Path({str(ROOT / "dashboard" / "app" / "templates")!r}).rglob("*.html")):
    for url in re.findall(r'hx-get="([^"]+)"', f.read_text()):
        path = re.sub(r"[{{][{{].*?[}}][}}]", "x", url.split("?")[0])
        if not path.startswith("/") or "{{%" in path:
            continue
        if not any(r.path_regex.match(path) for r in routes):
            missing.append(f"{{f.name}}: {{url}}")
        checked += 1
print("RESULT " + json.dumps({{"missing": missing, "checked": checked}}))
"""
    )
    res = _result(_py(code, tmp_path, _OWNER))
    assert res["missing"] == [] and res["checked"] > 50, res


def test_a_systemexit_inside_a_request_never_ends_the_server(tmp_path):
    code = (
        _APP
        + """
import json, sys
def boom():
    sys.exit(3)
app.add_api_route("/__test_exit", boom, methods=["GET"])
app.middleware_stack = None  # rebuilt on the next request with the new route
with TestClient(app, raise_server_exceptions=False) as c:
    first = c.get("/__test_exit").status_code
    after = c.get("/health").status_code
# The bridge itself turns a tool's sys.exit into RuntimeError.
def calls_exit(self):
    sys.exit(1)
wrapped = sbk_bridge._no_process_exit(calls_exit)
try:
    wrapped(None)
    kind = "nothing"
except RuntimeError:
    kind = "RuntimeError"
except SystemExit:
    kind = "SystemExit"
print("RESULT " + json.dumps({"first": first, "after": after, "bridge": kind}))
"""
    )
    res = _result(_py(code, tmp_path, _OWNER))
    assert res == {"first": 500, "after": 200, "bridge": "RuntimeError"}


def test_followup_load_action_items_returns_empty_without_the_paid_extract(tmp_path):
    code = (
        _NO_NETWORK
        + f"""
import importlib.util, json
spec = importlib.util.spec_from_file_location("xs_l3_followup", {str(CS / "xs-l3-followup.py")!r})
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
df = m.load_action_items()
items = m.filter_actionable(df, lookahead_days=14) + m.filter_actionable(df, lookahead_days=0, overdue_only=True)
print("RESULT " + json.dumps({{"rows": len(df), "items": len(items)}}))
"""
    )
    assert _result(_py(code, tmp_path, _OWNER)) == {"rows": 0, "items": 0}


@pytest.mark.parametrize("italian", [False, True], ids=["english-columns", "old-italian-columns"])
def test_pipeline_grid_reads_the_status_file(tmp_path, italian):
    _status_file(tmp_path / "data", italian)
    code = (
        _APP
        + """
import json
with TestClient(app, raise_server_exceptions=False) as c:
    grid = c.get("/partials/pipeline_grid")
    page = c.get("/pipeline")
    api = c.get("/api/pipeline/grid").json()
rows = [r for s in api.get("pipeline", []) for r in s.get("rows", []) + [x for g in s.get("subgroups", [])
        for x in g.get("rows", [])]]
print("RESULT " + json.dumps({"grid": grid.status_code, "page": page.status_code,
      "shows_stage": "Demo databases L0" in grid.text, "ok_badge": "pg-st-ok" in grid.text,
      "statuses": sorted({r.get("Status", "") for r in rows}),
      "run_scripts": sorted({(r.get("_run_info") or {}).get("script", "") for r in rows})}))
"""
    )
    res = _result(_py(code, tmp_path, _OWNER))
    assert res["grid"] == 200 and res["page"] == 200, res
    assert res["shows_stage"] and res["ok_badge"], res
    assert res["statuses"] == ["Missing", "OK"], res
    assert "databases/db-l0-download.py" in res["run_scripts"], res


def test_person_card_and_lookup_api_without_email_data(tmp_path):
    _seed_people(tmp_path / "data")
    code = (
        _APP
        + """
import json
with TestClient(app, raise_server_exceptions=False) as c:
    card = c.get("/partials/person_card?q=rowan@example.com")
    phone_only = c.get("/partials/person_card?q=Pat Phoneonly")
    by_name = c.get("/partials/person_card?q=Rowan Demo")
    threads = c.get("/api/person/threads?email=rowan@example.com")
print("RESULT " + json.dumps({"card": card.status_code, "name_shown": "Rowan Demo" in card.text,
      "by_name": by_name.status_code, "threads": threads.status_code, "phone_only": phone_only.status_code}))
"""
    )
    res = _result(_py(code, tmp_path, _OWNER))
    assert res["card"] == 200 and res["name_shown"], res
    assert res["by_name"] == 200 and res["threads"] < 500 and res["phone_only"] == 200, res


# ── sbk CLI ──────────────────────────────────────────────────────────────────────────────────────────────────


def test_cli_lookup_brief_search_on_an_empty_root(tmp_path):
    look = _cli(["lookup", "Rowan Demo"], tmp_path, _OWNER)
    assert look.returncode == 1 and "No contact found for: Rowan Demo" in look.stdout, (
        look.stdout + look.stderr
    )
    assert "Traceback" not in look.stderr and "Error:" not in look.stderr + look.stdout
    mail = _cli(["lookup", "rowan@example.com"], tmp_path, _OWNER)
    assert mail.returncode == 1 and "No contact found" in mail.stdout, mail.stdout + mail.stderr
    brief = _cli(["brief"], tmp_path, _OWNER)
    assert brief.returncode == 0, brief.stdout + brief.stderr
    assert "Traceback" not in brief.stderr and "Error:" not in brief.stdout + brief.stderr
    search = _cli(["search", "pricing review"], tmp_path, _OWNER)
    assert search.returncode == 0, search.stdout + search.stderr
    assert "nothing is indexed yet" in search.stdout


def test_cli_lookup_and_brief_without_email_data(tmp_path):
    """People from a non-email source, and no enriched/threads.parquet: lookup by name and by email, and brief."""
    _seed_people(tmp_path / "data")
    for who in ("Rowan Demo", "rowan@example.com"):
        r = _cli(["lookup", who], tmp_path, _OWNER)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "Rowan Demo" in r.stdout and "Example Co" in r.stdout
    phone = _cli(["lookup", "Pat Phoneonly"], tmp_path, _OWNER)
    assert phone.returncode == 0 and "Pat Phoneonly" in phone.stdout, phone.stdout + phone.stderr
    j = _cli(["lookup", "rowan@example.com", "--json"], tmp_path, _OWNER)
    assert j.returncode == 0 and json.loads(j.stdout)["found"] is True, j.stdout + j.stderr
    brief = _cli(["brief"], tmp_path, _OWNER)
    assert brief.returncode == 0, brief.stdout + brief.stderr
    assert "Error:" not in brief.stdout + brief.stderr
