"""Model calls only on opt-in in the manual CLIs, `sbk brief` names people from the book, and small kit items.

- tools/cross-source/xs-temporal-analysis.py: the analysis is local by default and sends nothing. --ai (or
  "insights": {"synthesis": true} in sbk.config.json) sends the week summary to Claude, and the log says what
  and how much first. --no-ai is still accepted, --dry-run never sends, --ai with --no-ai is refused.
- tools/monitoring/signal-detector.py --scan: a local one-line summary by default. --synthesize (or
  "signals": {"synthesis": true}) sends each new signal to Claude, announced with its size. --no-synthesize is
  still accepted, --dry-run never sends.
- tools/monitoring/commitment-tracker.py --verify announces each commitment it sends; --dry-run sends nothing.
- `sbk brief` (xs-l3-digest-v2.py) names a WhatsApp sender who wrote from an unsaved number with the name the
  merged address book gives that number.
- The pipeline runner tags its memory lines '[resources]'; the dashboard home has English placeholders; the
  text_utils comment uses a zero-padded number; .gitignore keeps tokens, sessions and exports out of git.

Each tool runs in a subprocess with its own SBK_DATA_ROOT, HOME and config; the model client is a recorder and
outbound network is refused. Demo data only.
"""

from __future__ import annotations

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
MON = TOOLS / "monitoring"

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

# The Anthropic client is a recorder: every messages.create is one call (the prompt length is kept), and
# call_claude counts too. Building a real client is impossible (anthropic.Anthropic raises).
_RECORDER = (
    _NO_NETWORK
    + """
import importlib.util, json, logging, runpy, sys, types
calls = []
REPLY = "[]"
import anthropic, xs_anthropic_client, xs_l3_common
class _Messages:
    def create(self, **kw):
        calls.append(sum(len(m.get("content", "")) for m in kw.get("messages", [])))
        return types.SimpleNamespace(content=[types.SimpleNamespace(text=REPLY)])
class _Client:
    messages = _Messages()
def _real_client(*a, **k):
    raise AssertionError("a real Anthropic client was built")
def _fake_call(prompt, system="", **kw):
    calls.append(len(prompt))
    return REPLY
xs_anthropic_client.get_client = lambda *a, **k: _Client()
anthropic.Anthropic = _real_client
xs_l3_common.call_claude = _fake_call
xs_l3_common.notify_macos = lambda *a, **k: None
def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod
def _main(path, argv):
    sys.argv = [str(path), *argv]
    try:
        runpy.run_path(str(path), run_name="__main__")
        return 0
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
def _done(rc):
    print("RESULT " + json.dumps({"rc": rc, "calls": calls}))
"""
)

_OWNER = {"owner": "Casey Demo", "own_emails": ["casey@example.com"], "own_names": ["casey demo"]}


def _env(tmp: Path, config: dict | None, key: str | None) -> dict:
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


def _py(code: str, tmp: Path, config: dict | None = None, key: str | None = None):
    proc = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)],
        cwd=str(ROOT),
        env=_env(tmp, config, key),
        capture_output=True,
        text=True,
        timeout=300,
        stdin=subprocess.DEVNULL,
    )
    lines = [x for x in proc.stdout.splitlines() if x.startswith("RESULT ")]
    assert lines, (
        f"rc {proc.returncode}\nSTDOUT:\n{proc.stdout[-3000:]}\nSTDERR:\n{proc.stderr[-6000:]}"
    )
    return json.loads(lines[-1][len("RESULT ") :]), proc.stdout + proc.stderr


# ── xs-temporal-analysis.py (D39) ────────────────────────────────────────────────────────────────────────────


def _seed_emails(tmp: Path) -> None:
    """Twelve demo e-mails of the last days between you and two demo contacts."""
    from datetime import UTC, datetime, timedelta

    import pandas as pd

    now = datetime.now(UTC)
    rows = []
    for i in range(12):
        mine = i % 2 == 0
        rows.append(
            {
                "date": (now - timedelta(days=i % 6, hours=i)).isoformat(),
                "from_addr": "Casey Demo <casey@example.com>"
                if mine
                else "Tara Vance <tara@northwind.example>",
                "to_addr": "tara@northwind.example" if mine else "casey@example.com",
                "subject": f"Demo thread {i}",
                "thread_id": f"t{i % 3}",
            }
        )
    d = tmp / "data" / "emails" / "demo"
    d.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(d / "messages.parquet")


def _temporal(
    tmp: Path, argv: list[str], config: dict | None = None, key: str | None = "demo-not-a-key"
):
    _seed_emails(tmp)
    code = (
        _RECORDER
        + f"""
REPLY = json.dumps([{{"id": "ins_001", "type": "relational", "severity": "info", "title": "Demo",
                     "content": "A demo insight."}}])
_done(_main({str(CS / "xs-temporal-analysis.py")!r}, {argv!r}))
"""
    )
    return _py(code, tmp, config, key)


def _weekly(tmp: Path) -> list[dict]:
    files = sorted((tmp / "data" / "insights").glob("weekly-*.json"))
    return [json.loads(f.read_text()) for f in files]


def test_temporal_by_default_is_local_and_sends_nothing(tmp_path):
    res, out = _temporal(tmp_path, [])
    assert res["rc"] == 0 and res["calls"] == [], out[-3000:]
    assert "Nothing was sent to a model" in out and "--ai" in out, out[-3000:]
    assert re.search(r"sends the week summary \(\d+ characters", out), out[-3000:]
    weekly = _weekly(tmp_path)
    assert (
        len(weekly) == 1 and weekly[0]["insights"] == [] and weekly[0]["stats"]["emails_sent"] == 6
    )


def test_temporal_old_no_ai_is_accepted_and_sends_nothing(tmp_path):
    res, out = _temporal(tmp_path, ["--no-ai"])
    assert res["rc"] == 0 and res["calls"] == [], out[-3000:]


def test_temporal_ai_announces_then_calls_once(tmp_path):
    res, out = _temporal(tmp_path, ["--ai"])
    assert res["rc"] == 0 and len(res["calls"]) == 1, out[-3000:]
    m = re.search(
        r"Sending the week summary \((\d+) characters: .*e-mail addresses.*ANTHROPIC_API_KEY", out
    )
    assert m, out[-3000:]
    assert out.index("Sending the week summary") < out.index("Generated 1 insights"), out[-3000:]
    assert _weekly(tmp_path)[0]["insights"][0]["id"] == "ins_001"


def test_temporal_config_turns_it_on_and_no_ai_still_wins(tmp_path):
    on = {"insights": {"synthesis": True}}
    res, out = _temporal(tmp_path, [], config=on)
    assert res["rc"] == 0 and len(res["calls"]) == 1, out[-3000:]
    res, out = _temporal(tmp_path, ["--no-ai"], config=on)
    assert res["rc"] == 0 and res["calls"] == [], out[-3000:]


def test_temporal_ai_without_key_or_on_dry_run_sends_nothing(tmp_path):
    res, out = _temporal(tmp_path, ["--ai"], key=None)
    assert res["rc"] == 0 and res["calls"] == [] and "ANTHROPIC_API_KEY is not set" in out, out[
        -3000:
    ]
    res, out = _temporal(tmp_path, ["--ai", "--dry-run"])
    assert res["rc"] == 0 and res["calls"] == [], out[-3000:]


def test_temporal_ai_and_no_ai_together_are_refused(tmp_path):
    res, out = _temporal(tmp_path, ["--ai", "--no-ai"])
    assert res["rc"] == 2 and res["calls"] == [], out[-3000:]


# ── signal-detector.py --scan (D39) ──────────────────────────────────────────────────────────────────────────

_CLUSTER = {
    "theme": "Northwind Demo",
    "entities": ["Northwind Demo"],
    "sources": ["email:demo-1", "slack:demo-2"],
    "source_types": ["email", "slack"],
    "first_seen": "2026-11-20",
    "last_seen": "2026-11-21",
    "relevance_score": 0.9,
    "urgency_score": 0.9,
    "combined_score": 0.9,
    "fact_count": 2,
    "contexts": [
        "Tara Vance said the Northwind demo order moves to Friday",
        "Demo kiln slot confirmed",
    ],
}


def _scan(
    tmp: Path, argv: list[str], config: dict | None = None, key: str | None = "demo-not-a-key"
):
    code = (
        _RECORDER
        + f"""
REPLY = "WHAT: a demo signal."
sd = _load("signal_detector_test", {str(MON / "signal-detector.py")!r})
sd.scan_batch_responses = lambda days_back=7: [{{"entity": "Northwind Demo", "topic": "", "source": "email"}}]
sd.scan_deep_responses = lambda days_back=7: []
sd.cluster_cross_source = lambda index, **kw: [dict({_CLUSTER!r})]
sd.score_clusters = lambda clusters, config: clusters
sd.notify_signal = lambda signal, dry_run=False: False
logging.basicConfig(level=logging.INFO)
sys.argv = ["signal-detector.py", *{argv!r}]
try:
    sd.main(); rc = 0
except SystemExit as e:
    rc = e.code
log = sd.SIGNALS_LOG_FILE
saved = json.loads(log.read_text()) if log.exists() else []
print("SUMMARY " + json.dumps([s.get("summary", "") for s in saved]))
_done(rc)
"""
    )
    return _py(code, tmp, config, key)


def test_signal_scan_by_default_sends_nothing(tmp_path):
    res, out = _scan(tmp_path, ["--scan"])
    assert res["rc"] in (0, None) and res["calls"] == [], out[-3000:]
    assert "Nothing was sent to a model" in out and "--synthesize" in out, out[-3000:]
    assert "Cross-source signal: 'Northwind Demo'" in out, out[-3000:]


def test_signal_scan_old_no_synthesize_is_accepted(tmp_path):
    res, out = _scan(tmp_path, ["--scan", "--no-synthesize"])
    assert res["rc"] in (0, None) and res["calls"] == [], out[-3000:]


def test_signal_scan_synthesize_announces_then_calls(tmp_path):
    res, out = _scan(tmp_path, ["--scan", "--synthesize"])
    assert res["rc"] in (0, None) and len(res["calls"]) == 1, out[-3000:]
    assert re.search(
        r"Sending signal 'Northwind Demo' \(\d+ characters: .*ANTHROPIC_API_KEY", out
    ), out[-3000:]
    assert "WHAT: a demo signal." in out


def test_signal_scan_config_on_no_synthesize_wins_dry_run_and_no_key_send_nothing(tmp_path):
    on = {"signals": {"synthesis": True}}
    res, out = _scan(tmp_path, ["--scan"], config=on)
    assert len(res["calls"]) == 1, out[-3000:]
    res, out = _scan(tmp_path, ["--scan", "--no-synthesize"], config=on)
    assert res["calls"] == [], out[-3000:]
    res, out = _scan(tmp_path, ["--scan", "--synthesize", "--dry-run"])
    assert res["calls"] == [], out[-3000:]
    res, out = _scan(tmp_path, ["--scan", "--synthesize"], key=None)
    assert res["calls"] == [] and "ANTHROPIC_API_KEY is not set" in out, out[-3000:]


def test_signal_scan_function_default_sends_nothing():
    text = (MON / "signal-detector.py").read_text(encoding="utf-8")
    assert re.search(r"def run_signal_scan\([^)]*synthesize: bool = False", text, re.S)


# ── commitment-tracker.py --verify ───────────────────────────────────────────────────────────────────────────


def _verify(tmp: Path, argv: list[str]):
    code = (
        _RECORDER
        + f"""
REPLY = '{{"verdict": "KEPT", "confidence": 0.9, "evidence": "demo"}}'
ct = _load("commitment_tracker_test", {str(MON / "commitment-tracker.py")!r})
ct.load_commitments = lambda: [{{"commitment_id": "c-demo-1", "status": "BROKEN", "who": "Tara Vance",
    "what": "send the demo order", "source_type": "email", "source_date": "2026-11-01"}}]
ct.save_commitments = lambda c: None
ct._find_subsequent_facts = lambda **kw: ["[email] Tara Vance sent the demo order"]
logging.basicConfig(level=logging.INFO)
sys.argv = ["commitment-tracker.py", *{argv!r}]
try:
    ct.main(); rc = 0
except SystemExit as e:
    rc = e.code
_done(rc)
"""
    )
    return _py(code, tmp, None, "demo-not-a-key")


def test_commitment_verify_announces_and_dry_run_sends_nothing(tmp_path):
    res, out = _verify(tmp_path, ["--verify", "--dry-run"])
    assert res["calls"] == [] and "Nothing was sent to a model" in out, out[-3000:]
    res, out = _verify(tmp_path, ["--verify"])
    assert len(res["calls"]) == 1, out[-3000:]
    assert re.search(r"Sending commitment c-demo-1 \(\d+ characters", out), out[-3000:]


# ── cl-l1-parse.py: says which provider gets the document before sending ────────────────────────────────────


def test_clinical_parse_announces_provider_and_size(tmp_path):
    code = (
        _RECORDER
        + f"""
cl = _load("cl_l1_parse_test", {str(TOOLS / "clinical" / "cl-l1-parse.py")!r})
def _fake_text(raw_text):
    calls.append(len(raw_text)); return "[]"
def _fake_image(raw_text, image_b64, media_type):
    calls.append("image"); return "[]"
cl._call_deepseek_text = _fake_text
cl._call_anthropic_multimodal = _fake_image
logging.basicConfig(level=logging.INFO)
os = __import__("os"); os.environ["DEEPSEEK_API_KEY"] = "demo-not-a-key"
cl.call_llm_for_blood_test(raw_text="Demo lab report. Glucose 92 mg/dl (60-110). " * 5)
cl.call_llm_for_blood_test(raw_text="", image_b64="ZGVtbw==", media_type="image/png")
_done(0)
"""
    )
    res, out = _py(code, tmp_path, None, "demo-not-a-key")
    assert len(res["calls"]) == 2, out[-3000:]
    assert re.search(r"Sending this document \(\d+ characters of text\) to DeepSeek", out), out[
        -3000:
    ]
    assert re.search(r"Sending this document \(0 characters of text, 1 image\) to Claude", out), (
        out[-3000:]
    )


# ── sbk brief names people from the book (D38) ───────────────────────────────────────────────────────────────


def _seed_book_and_chat(tmp: Path) -> None:
    import pandas as pd

    enriched = tmp / "data" / "enriched"
    enriched.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {  # e-mail-keyed row: the number written as the database had it
                "person_id": "p_demo0001",
                "name": "Pia Brandt",
                "email": "pia@hollow.example",
                "phone_primary": "+44 (0)7700 900631",
                "contact_key": "",
                "has_whatsapp": True,
            },
            {  # an unsaved number: the book has no name for it
                "person_id": "p_demo0002",
                "name": "+1 202 555 0147",
                "email": "",
                "phone_primary": "+1 202 555 0147",
                "contact_key": "tel:+12025550147",
                "has_whatsapp": True,
            },
        ]
    ).to_parquet(enriched / "contacts-merged.parquet")
    chats = tmp / "data" / "whatsapp" / "chats"
    chats.mkdir(parents=True, exist_ok=True)
    # seven hours apart, so the two chats stay two stories
    for stem, sender, when, body in (
        (
            "+44-7700-900631",
            "+44 7700 900631",
            "2026-11-19T15:00:00",
            "The kiln is delayed to Friday.",
        ),
        (
            "+1-202-555-0147",
            "+1 202 555 0147",
            "2026-11-19T08:00:00",
            "Hello, is the pottery class on?",
        ),
    ):
        (chats / f"{stem}.json").write_text(
            json.dumps({"messages": [{"date": when, "sender": sender, "body": body}]}),
            encoding="utf-8",
        )


def test_brief_names_an_unsaved_whatsapp_number_from_the_book(tmp_path):
    _seed_book_and_chat(tmp_path)
    code = (
        _RECORDER
        + f"""
cli = _load("sbk_cli_brief_names", {str(TOOLS / "sbk_cli.py")!r})
try:
    rc = cli.cmd_brief(["--date", "2026-11-20", "--no-research"])
except SystemExit as e:
    rc = e.code
_done(rc)
"""
    )
    res, out = _py(code, tmp_path, {"phone_country_code": "44"}, None)
    assert res["rc"] == 0 and res["calls"] == [], out[-3000:]
    assert "WhatsApp from Pia Brandt" in out and "Persons: Pia Brandt" in out, out[-3000:]
    assert "WhatsApp from +44 7700 900631" not in out, out[-3000:]
    # a number the book does not name stays a number
    assert "+1 202 555 0147" in out, out[-3000:]
    data = json.loads((tmp_path / "data" / "briefs" / "digest-v2-20261120.json").read_text())
    titles = [s["title"] for s in data["stories"]]
    assert any(t.startswith("WhatsApp from Pia Brandt") for t in titles), titles


# ── small items (D40) ────────────────────────────────────────────────────────────────────────────────────────


def test_pipeline_runner_tags_memory_lines_in_english():
    text = (CS / "xs-pipeline-run.py").read_text(encoding="utf-8")
    assert "[risorse]" not in text and text.count("[resources]") >= 5
    # the app still reads old logs and the new tag
    app = (TOOLS / "secondbrain" / "sb-app.py").read_text(encoding="utf-8")
    assert r"\[(?:resources|risorse)\]" in app


def test_dashboard_home_placeholders_are_english():
    html = (ROOT / "dashboard" / "app" / "templates" / "home.html").read_text(encoding="utf-8")
    assert "User ID or channel ID (e.g. U0123456789)" in html
    assert "Thread timestamp (e.g. 1700000000.000100)" in html
    assert not re.search(r"placeholder=\"[^\"]*\b(es\.|o Channel)", html)


def test_text_utils_comment_uses_a_zero_padded_number():
    text = (TOOLS / "text_utils.py").read_text(encoding="utf-8")
    assert "1234 5678" not in text and '"02 0000 0000" in Italy is' in text


@pytest.mark.parametrize(
    "path",
    [
        "token.json",
        "google-token.json",
        "tools/email/token.json",
        "cookies.txt",
        "linkedin-session.json",
        "plaud-wt.json",
        "conversations.json",
        "messages.jsonl",
        "session.jsonl",
        "backup.tar.gz",
        "backup.enc",
        "export.zip",
        "contacts.vcf",
        "WhatsApp Chat with Demo.txt",
        "ChatStorage.sqlite",
    ],
)
def test_gitignore_keeps_tokens_sessions_and_exports_out(path):
    rc = subprocess.run(
        ["git", "check-ignore", "-q", "--no-index", path], cwd=str(ROOT), capture_output=True
    ).returncode
    assert rc == 0, f"{path} is not ignored"


def test_gitignore_keeps_the_demo_fixtures():
    for path in (
        "tests/fixtures/ai_history/chatgpt/conversations.json",
        "tests/fixtures/ai_history/claude_code/projects/-home-demo-projects-demo-app/"
        "aaaaaaaa-0000-4000-8000-000000000001.jsonl",
    ):
        rc = subprocess.run(
            ["git", "check-ignore", "-q", "--no-index", path], cwd=str(ROOT), capture_output=True
        ).returncode
        assert rc == 1, f"{path} would be ignored"
