"""`sbk brief` sends nothing to a model unless you ask, plus the small kit items of D36.

- `sbk brief` (tools/sbk_cli.py -> tools/cross-source/xs-l3-digest-v2.py) prints today's stories and sends
  nothing by default, with one line that says how to turn the model summary on and how much it would send.
  The model is asked only with --synthesize or "brief": {"synthesis": true} in sbk.config.json, and only with
  ANTHROPIC_API_KEY; without the key it prints the stories and exits 0. The older xs-l3-digest.py follows the
  same rule. The dashboard's digest refresh never adds --synthesize; the monitor adds it only after its consent.
- `sbk lookup --json` prints what the text output shows, also for a person without e-mail.
- The dashboard run-grid allow-list fails closed: an empty grid runs nothing.
- wa-l1-transcribe-audio.py has no default folder under ~/Downloads.
- li-l0-scraper.js keeps no placeholder URN.
- Demo phone numbers in docs, config example and tests come from fiction ranges only.
- xs-l3-birthday-calendar.py takes --apply (--applica stays as a hidden alias) and the runner uses --apply.
- onomastici-it.json describes itself in English.

Every run of a tool happens in a subprocess with its own SBK_DATA_ROOT, HOME and config. The model client is
replaced by a recorder, outbound network is refused. Demo data only.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
CS = TOOLS / "cross-source"

_NO_NETWORK = """
import socket
_orig_connect = socket.socket.connect
def _blocked(self, addr):
    if self.family in (socket.AF_INET, socket.AF_INET6):
        host = addr[0] if isinstance(addr, tuple) else str(addr)
        if host not in ("127.0.0.1", "::1", "localhost"):
            raise OSError("network blocked by the test")
    return _orig_connect(self, addr)
socket.socket.connect = _blocked
"""

# The model is replaced before any tool module is loaded: call_claude records the prompt size, and building
# an Anthropic client at all counts as a call.
_RECORDER = (
    _NO_NETWORK
    + """
import importlib.util, json, sys
calls = []
import anthropic, xs_anthropic_client, xs_l3_common
def _fake_call(prompt, system="", **kw):
    calls.append(len(prompt))
    return "# Digest demo\\n\\n## TL;DR\\nA demo summary."
def _no_client(*a, **k):
    calls.append("client")
    raise AssertionError("a model client was built")
xs_l3_common.call_claude = _fake_call
xs_l3_common.notify_macos = lambda *a, **k: None  # no desktop notification from a test
xs_anthropic_client.get_client = _no_client
anthropic.Anthropic = _no_client
def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod
def _done(rc):
    print("RESULT " + json.dumps({"rc": rc, "calls": calls}))
"""
)

_OWNER = {"owner": "Casey Demo", "own_emails": ["casey@example.com"], "own_names": ["casey demo"]}
_DATE = ["--date", "2026-11-20", "--no-research"]


def _env(tmp: Path, config: dict | None, key: str | None = None) -> dict:
    cfg = tmp / "sbk.config.json"
    cfg.write_text(json.dumps({**_OWNER, **(config or {})}), encoding="utf-8")
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
        PYTHONPATH=os.pathsep.join([str(TOOLS), str(CS)]),
    )
    if key:
        env["ANTHROPIC_API_KEY"] = key
    return env


def _run(argv: list[str], tmp: Path, config: dict | None = None, key: str | None = None):
    return subprocess.run(
        [sys.executable, *argv],
        cwd=str(ROOT),
        env=_env(tmp, config, key),
        capture_output=True,
        text=True,
        timeout=300,
        stdin=subprocess.DEVNULL,
    )


def _py(code: str, tmp: Path, config: dict | None = None, key: str | None = None):
    return _run(["-c", textwrap.dedent(code)], tmp, config, key)


def _result(proc) -> dict:
    line = [x for x in proc.stdout.splitlines() if x.startswith("RESULT ")]
    assert line, (
        f"rc {proc.returncode}\nSTDOUT:\n{proc.stdout[-3000:]}\nSTDERR:\n{proc.stderr[-6000:]}"
    )
    return json.loads(line[-1][len("RESULT ") :])


def _seed_chat(tmp: Path) -> None:
    """One WhatsApp message from a demo person inside the brief's 24 hours."""
    chats = tmp / "data" / "whatsapp" / "chats"
    chats.mkdir(parents=True, exist_ok=True)
    (chats / "Rowan Demo.json").write_text(
        json.dumps(
            {
                "messages": [
                    {
                        "date": "2026-11-19T15:00:00",
                        "sender": "Rowan Demo",
                        "body": "Can we move the supply review to Friday? The demo numbers are ready.",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )


def _brief(
    args: list[str], tmp: Path, config: dict | None = None, key: str | None = None
) -> tuple[dict, str]:
    _seed_chat(tmp)
    code = (
        _RECORDER
        + f"""
cli = _load("sbk_cli_brief_test", {str(TOOLS / "sbk_cli.py")!r})
try:
    rc = cli.cmd_brief({args!r})
except SystemExit as e:
    rc = e.code
_done(rc)
"""
    )
    proc = _py(code, tmp, config, key)
    return _result(proc), proc.stdout + proc.stderr


def _briefs(tmp: Path) -> list[str]:
    d = tmp / "data" / "briefs"
    return sorted(p.name for p in d.glob("*")) if d.exists() else []


# ── sbk brief (D32) ───────────────────────────────────────────────────────────────────────────────────────────


def test_brief_by_default_prints_the_stories_and_sends_nothing(tmp_path):
    res, out = _brief(_DATE, tmp_path, key="demo-not-a-key")
    assert res["rc"] == 0 and res["calls"] == [], out[-3000:]
    assert "Today's stories" in out and "supply review to Friday" in out, out[-3000:]
    assert "Nothing was sent to a model" in out and "--synthesize" in out, out[-3000:]
    assert re.search(r"sends this story \(\d+ characters", out), out[-3000:]
    assert "ANTHROPIC_API_KEY" in out and "Traceback" not in out
    # the stories file for the dashboard, without a model digest
    assert _briefs(tmp_path) == ["digest-v2-20261120.json"]
    data = json.loads((tmp_path / "data" / "briefs" / "digest-v2-20261120.json").read_text())
    assert data["synthesized"] is False and data["stories"], data


def test_brief_dry_run_writes_nothing(tmp_path):
    res, out = _brief([*_DATE, "--dry-run"], tmp_path, key="demo-not-a-key")
    assert res["rc"] == 0 and res["calls"] == [], out[-3000:]
    assert "supply review to Friday" in out and _briefs(tmp_path) == []


def test_brief_config_on_without_a_key_prints_the_stories_rc_0(tmp_path):
    res, out = _brief(_DATE, tmp_path, config={"brief": {"synthesis": True}})
    assert res["rc"] == 0 and res["calls"] == [], out[-3000:]
    assert "supply review to Friday" in out and "ANTHROPIC_API_KEY is not set" in out, out[-3000:]
    assert "Error:" not in out and "Traceback" not in out


def test_brief_synthesize_with_a_key_announces_and_calls_once(tmp_path):
    res, out = _brief([*_DATE, "--synthesize"], tmp_path, key="demo-not-a-key")
    assert res["rc"] == 0 and len(res["calls"]) == 1 and isinstance(res["calls"][0], int), out[
        -3000:
    ]
    assert "Sending this story" in out and "with your ANTHROPIC_API_KEY" in out, out[-3000:]
    names = _briefs(tmp_path)
    assert "digest-v2-20261120.json" in names and any(n.endswith(".md") for n in names), names
    data = json.loads((tmp_path / "data" / "briefs" / "digest-v2-20261120.json").read_text())
    assert data["synthesized"] is True


def test_brief_config_on_calls_and_no_synthesis_wins(tmp_path):
    on = {"brief": {"synthesis": True}}
    res, out = _brief(_DATE, tmp_path, config=on, key="demo-not-a-key")
    assert res["rc"] == 0 and len(res["calls"]) == 1, out[-3000:]
    res, out = _brief(
        [*_DATE, "--no-synthesis", "--force"], tmp_path, config=on, key="demo-not-a-key"
    )
    assert res["rc"] == 0 and res["calls"] == [], out[-3000:]
    # a stories-only run does not replace the day's model digest file
    data = json.loads((tmp_path / "data" / "briefs" / "digest-v2-20261120.json").read_text())
    assert data["synthesized"] is True
    res, _ = _brief(_DATE, tmp_path, config={"brief": {"synthesis": "yes"}}, key="demo-not-a-key")
    assert res["calls"] == []  # only a real true turns it on


def test_brief_refuses_both_flags_and_help_writes_nothing(tmp_path):
    res, out = _brief(["--synthesize", "--no-synthesis"], tmp_path)
    assert res["rc"] == 2 and res["calls"] == [], out[-2000:]
    before = sorted(str(p) for p in (tmp_path / "data").rglob("*"))
    res, out = _brief(["--help"], tmp_path)
    assert res["rc"] == 0 and "--synthesize" in out and "brief.synthesis" in out, out[-2000:]
    assert "usage: sbk brief" in out
    assert sorted(str(p) for p in (tmp_path / "data").rglob("*")) == before


def test_old_digest_v1_sends_nothing_by_default(tmp_path):
    code = (
        _RECORDER
        + f"""
v1 = _load("xs_l3_digest_v1_test", {str(CS / "xs-l3-digest.py")!r})
item = {{"type": "decay", "title": "Rowan Demo: 40 days without contact", "person": "Rowan Demo"}}
for name in dir(v1):
    if name.startswith("collect_") and name != "collect_deep_fact_deadlines":
        setattr(v1, name, lambda *a, **k: [])
v1.collect_decay_alerts = lambda *a, **k: [dict(item)]
v1.collect_deep_fact_deadlines = lambda *a, **k: ""
v1.score_digest_item = lambda *a, **k: 50
v1.group_by_person = lambda items, data: {{"Rowan Demo": items}}
v1.build_digest_prompt = lambda grouped, d, **k: "demo digest data"
results = []
for argv in (["--date", "2026-11-20"], ["--date", "2026-11-20", "--synthesize"]):
    sys.argv = ["xs-l3-digest.py", *argv]
    v1.main()
    results.append(len(calls))
print("RESULT " + json.dumps({{"rc": 0, "calls": results}}))
"""
    )
    proc = _py(code, tmp_path, key="demo-not-a-key")
    res = _result(proc)
    assert res["calls"] == [0, 1], proc.stdout[-3000:] + proc.stderr[-3000:]
    assert "Nothing was sent to a model" in proc.stdout


def test_dashboard_refresh_never_asks_for_the_model_and_the_monitor_only_after_consent():
    sys.path.insert(0, str(ROOT / "dashboard"))
    try:
        from app.api import pipeline as api
    finally:
        sys.path.remove(str(ROOT / "dashboard"))

    class _Runner:
        def __init__(self):
            self.runs = []

        async def run_script(self, **kw):
            self.runs.append(kw)
            return "job1"

        def get_job(self, job_id):
            return None

    runner = _Runner()
    req = type("R", (), {"app": type("A", (), {"state": type("S", (), {"runner": runner})()})()})()
    asyncio.run(api.refresh_digest(req))
    assert runner.runs[0]["script_path"] == "cross-source/xs-l3-digest-v2.py"
    assert "--synthesize" not in runner.runs[0]["extra_args"]

    src = (TOOLS / "monitoring" / "sbk-monitor.py").read_text(encoding="utf-8")
    body = src[src.index("def run_digest_cycle") :]
    body = body[: body.index("\ndef ", 10)]
    assert body.index('model_gate("morning digest")') < body.index('"--synthesize"')


# ── sbk lookup --json (D36) ──────────────────────────────────────────────────────────────────────────────────


def _seed_people(data: Path) -> None:
    import pandas as pd

    enriched = data / "enriched"
    enriched.mkdir(parents=True, exist_ok=True)
    when = pd.Timestamp("2026-11-20T10:00:00Z")
    pd.DataFrame(
        {
            "person_id": ["p_demo01", "p_demo03"],
            "email": ["rowan@example.com", ""],
            "all_emails": [["rowan@example.com"], []],
            "name": ["Rowan Demo", "Pat Phoneonly"],
            "organization": ["Example Co", "Tailspin Demo"],
            "phone_primary": ["", "+1 202 555 0123"],
            "contact_key": ["rowan@example.com", "tel:+12025550123"],
            "score": [3.5, 0.5],
            "source_count": [2, 1],
            "is_internal": [False, False],
            "is_automated": [False, False],
            "email_total_msgs": [0, 0],
            "cal_events": [0, 0],
            "plaud_meetings": [0, 0],
            "tactiq_meetings": [0, 0],
            "last_contact": [when, when],
            "first_contact": [when, when],
            "last_contact_source": ["databases", "whatsapp"],
            "linkedin_url": ["", ""],
            "linkedin_headline": ["", ""],
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
                }
            }
        ),
        encoding="utf-8",
    )


@pytest.mark.parametrize("who", ["Pat Phoneonly", "Rowan Demo"])
def test_lookup_json_agrees_with_the_text_output(tmp_path, who):
    _seed_people(tmp_path / "data")
    text = _run([str(TOOLS / "sbk_cli.py"), "lookup", who], tmp_path)
    js = _run([str(TOOLS / "sbk_cli.py"), "lookup", who, "--json"], tmp_path)
    assert text.returncode == 0 and js.returncode == 0, (
        text.stdout + text.stderr + js.stdout + js.stderr
    )
    ctx = json.loads(js.stdout)
    assert ctx["found"] is True and ctx["name"] == who, ctx
    for field in ("name", "organization", "person_id"):
        assert str(ctx[field]) and str(ctx[field]) in text.stdout, (field, ctx, text.stdout)
    assert f"Score: {float(ctx['score']):.1f}" in text.stdout
    if who == "Pat Phoneonly":
        assert (
            ctx["phone_primary"] == "+1 202 555 0123"
            and ctx["email"] == ""
            and ctx["all_emails"] == []
        )
        assert "+1 202 555 0123" in text.stdout
    else:
        assert ctx["email"] == "rowan@example.com" and "rowan@example.com" in text.stdout


# ── dashboard run-grid allow-list (D36) ──────────────────────────────────────────────────────────────────────


def _grid_client(grid):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    sys.path.insert(0, str(ROOT / "dashboard"))
    try:
        from app.api import pipeline as api
    finally:
        sys.path.remove(str(ROOT / "dashboard"))

    runs: list[dict] = []

    class _Runner:
        async def run_script(self, **kw):
            runs.append(kw)
            return "job1"

        def get_job(self, job_id):
            return None

    class _Bridge:
        def get_pipeline_grid(self):
            if isinstance(grid, Exception):
                raise grid
            return grid

    app = FastAPI()
    app.include_router(api.router)
    app.state.runner = _Runner()
    app.state.bridge = _Bridge()
    return TestClient(app), runs


def _row(script: str, args: str = "") -> dict:
    return {"_run_info": {"script": script, "args_str": args}}


@pytest.mark.parametrize("grid", [{}, {"pipeline": []}, RuntimeError("no status file")])
def test_run_grid_fails_closed_when_the_grid_lists_nothing(grid):
    client, runs = _grid_client(grid)
    r = client.post(
        "/api/pipeline/run-grid", json={"script": "cross-source/xs-l3-digest-v2.py", "args": ""}
    )
    assert r.status_code == 400 and runs == [], r.text


def test_run_grid_runs_only_listed_scripts_with_their_arguments():
    grid = {
        "pipeline": [
            {
                "rows": [_row("databases/db-l0-download.py", "--dry-run")],
                "subgroups": [{"rows": [_row("telegram/tg-l1-parse.py")]}],
            }
        ]
    }
    client, runs = _grid_client(grid)
    ok = client.post(
        "/api/pipeline/run-grid",
        json={"script": "databases/db-l0-download.py", "args": "--dry-run"},
    )
    plain = client.post(
        "/api/pipeline/run-grid", json={"script": "telegram/tg-l1-parse.py", "args": ""}
    )
    assert ok.status_code == 200 and plain.status_code == 200, ok.text + plain.text
    other = client.post(
        "/api/pipeline/run-grid", json={"script": "cross-source/xs-l3-digest-v2.py"}
    )
    bad_args = client.post(
        "/api/pipeline/run-grid",
        json={"script": "databases/db-l0-download.py", "args": "--synthesize"},
    )
    assert other.status_code == 400 and bad_args.status_code == 400
    assert [r["script_path"] for r in runs] == [
        "databases/db-l0-download.py",
        "telegram/tg-l1-parse.py",
    ]
    assert runs[0]["extra_args"] == ["--dry-run"] and runs[1]["extra_args"] == []


# ── wa-l1-transcribe-audio.py (D36) ──────────────────────────────────────────────────────────────────────────


def test_transcribe_audio_has_no_default_folder_under_downloads(tmp_path):
    script = TOOLS / "whatsapp" / "wa-l1-transcribe-audio.py"
    src = script.read_text(encoding="utf-8")
    assert '"Downloads"' not in src and "whatsapp attachments" not in src
    h = _run([str(script), "--help"], tmp_path)
    assert h.returncode == 0 and "--attachments-dir" in h.stdout and "Downloads" not in h.stdout
    assert not list((tmp_path / "data").rglob("*"))  # --help writes nothing
    # without the folder it stops before reading anything (the pipeline decorator logs the usage error)
    r = _run([str(script), "--dry-run"], tmp_path)
    assert r.returncode == 2 and "--attachments-dir is required" in r.stderr, r.stdout + r.stderr
    assert not (tmp_path / "data" / "whatsapp").exists()
    resume = _run([str(script), "--resume", "--dry-run"], tmp_path)  # --resume needs no folder
    assert resume.returncode == 1 and "No saved plan" in resume.stdout + resume.stderr


# ── li-l0-scraper.js (D36) ───────────────────────────────────────────────────────────────────────────────────


def test_linkedin_scraper_has_no_placeholder_urn():
    src = (TOOLS / "linkedin" / "li-l0-scraper.js").read_text(encoding="utf-8")
    assert "MY_URN" not in src and "PLACEHOLDER" not in src.upper().replace("PLACEHOLDERS", "")


# ── demo phone numbers (D36) ─────────────────────────────────────────────────────────────────────────────────

_PHONE = re.compile(r"\+[0-9]{1,3}[ (.-]*[0-9][0-9 ().-]{6,16}[0-9]")
_LOCAL_LIVE = re.compile(
    r"(?<![\d+])3\d{2} \d{3} \d{4}(?!\d)"
)  # an Italian mobile written without +39


def _fiction(number: str) -> bool:
    d = re.sub(
        r"\D", "", number.replace("(0)", "")
    )  # "+44 (0)7700 ..." writes the trunk 0 in brackets
    return (
        (d.startswith("1202555") and d[7:9] == "01")  # +1 202 555 01xx
        or d.startswith("1555")  # +1 555 01xx and +1 555 555 01xx, never a full live number
        or d.startswith("447700900")  # +44 7700 900xxx (Ofcom drama numbers)
        or d.startswith("442079460")  # +44 20 7946 0xxx (Ofcom drama numbers)
        or d == "44207946"  # the first half of a folded vCard line holding +44 20 7946 0002
        or d.startswith(
            ("7700900", "2079460")
        )  # a UK fiction number that lost its +44 (what a test expects)
    )


def test_demo_phone_numbers_come_from_fiction_ranges():
    files = [ROOT / "sbk.config.example.json", ROOT / ".env.example", ROOT / "README.md"]
    files += list((ROOT / "docs").rglob("*.md")) + list((ROOT / "tests").glob("*.py"))
    files += list(TOOLS.glob("*/README.md"))
    bad = []
    for f in files:
        if not f.exists() or f.resolve() == Path(__file__).resolve():
            continue
        text = f.read_text(encoding="utf-8", errors="replace")
        for n, line in enumerate(text.splitlines(), 1):
            for m in _PHONE.finditer(line):
                if not _fiction(m.group(0)):
                    bad.append(f"{f.relative_to(ROOT)}:{n}: {m.group(0)}")
            bad += [f"{f.relative_to(ROOT)}:{n}: {m.group(0)}" for m in _LOCAL_LIVE.finditer(line)]
    assert not bad, "\n".join(bad)


# ── xs-l3-birthday-calendar.py --apply (D36) ─────────────────────────────────────────────────────────────────


def test_birthday_calendar_apply_in_english_with_the_italian_alias(tmp_path):
    script = CS / "xs-l3-birthday-calendar.py"
    for flag in ("--apply", "--applica"):
        r = _run([str(script), flag], tmp_path)
        assert r.returncode == 0 and "No calendar login saved" in r.stdout + r.stderr, (
            r.stdout + r.stderr
        )
    h = _run([str(script), "--help"], tmp_path)
    assert h.returncode == 0 and "--apply" in h.stdout and "applica" not in h.stdout
    runner = (CS / "xs-pipeline-run.py").read_text(encoding="utf-8")
    assert '_esegui("l3_calendario_ricorrenze", ["--apply"])' in runner
    assert '"--applica"' not in runner


# ── onomastici-it.json (D36) ─────────────────────────────────────────────────────────────────────────────────


def test_name_day_file_describes_itself_in_english(tmp_path):
    data = json.loads((CS / "onomastici-it.json").read_text(encoding="utf-8"))
    meta = {k: v for k, v in data.items() if k.startswith("_") and isinstance(v, str)}
    assert "_cosa" not in data and set(meta) == {"_about"}, meta
    assert "Italian name days" in meta["_about"] and "never from memory" in meta["_about"]
    assert not re.search(r"\b(del|nessun|dato|calendario|allarga|memoria)\b", meta["_about"])
    r = _run([str(CS / "xs-l2-birthdays.py"), "--check"], tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
