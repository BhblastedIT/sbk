"""AI history readers (tools/ai-history/ai-l0-*.py) on synthetic fixtures.

The fixtures under tests/fixtures/ai_history/ hold demo text only. Secrets in them are
{{PLACEHOLDERS}}: the tests put fake tokens in their place at run time, built from pieces,
so no token-shaped string sits in the repo.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools" / "ai-history"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "ai_history"
FIELDS = ["source", "session_id", "project", "ts", "text"]

FAKE = {
    "ANTHROPIC_KEY": "sk-" + "ant-" + "api03-" + "Zx9Kq" * 8,
    "OPENAI_KEY": "sk-" + "proj-" + "Q7wE2r" * 8,
    "GITHUB_TOKEN": "gh" + "p_" + "A1b2C3d4" * 5,
    "SLACK_TOKEN": "xo" + "xb-" + "123456789012-123456789012-" + "AbCdEfGhIjKlMnOpQrStUvWx",
    "AWS_KEY": "AK" + "IA" + "QWERTY234567ABCD",
    "PASSWORD": "Tr0ub4dor" + "-x9Q",
}


def _materialise(tmp_path: Path) -> Path:
    """Copy the fixtures to tmp and put the fake tokens in place of the placeholders."""
    dst = tmp_path / "fixtures"
    shutil.copytree(FIXTURES, dst)
    for f in dst.rglob("*"):
        if f.is_file():
            body = f.read_text(encoding="utf-8")
            for name, value in FAKE.items():
                body = body.replace("{{" + name + "}}", value)
            f.write_text(body, encoding="utf-8")
    return dst


def _run(script: str, args: list[str], env_extra: dict[str, str]) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_CONFIG_DIR", "SBK_DATA_ROOT")}
    env.update(env_extra)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    proc = subprocess.run(
        [sys.executable, str(TOOLS / script), *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return proc


def _read(data_root: Path) -> list[dict]:
    path = data_root / "ai-history" / "messages.jsonl"
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def _assert_contract(rows: list[dict]) -> None:
    for r in rows:
        assert list(r.keys()) == FIELDS
        assert all(isinstance(r[f], str) for f in FIELDS)
        assert r["ts"] == "" or re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", r["ts"])
        for secret in FAKE.values():
            assert secret not in r["text"]


@pytest.fixture()
def env(tmp_path):
    fx = _materialise(tmp_path)
    data_root = tmp_path / "data"
    return (
        fx,
        data_root,
        {"CLAUDE_CONFIG_DIR": str(fx / "claude_code"), "SBK_DATA_ROOT": str(data_root)},
    )


# ----------------------------------------------------------------------------- Claude Code
CC_KEPT = {
    "Keep answers short and in plain words. The key is [REDACTED:anthropic-api-key]",
    "Look at this screenshot and tell me what is wrong",
    "Write the summary for demo@example.com and\n\nalways check the numbers twice before you answer.",
    "And add a chart please.",
    "Use the token [REDACTED:github-pat] and password: [REDACTED:generic-api-key]",
    "Rename the function and keep the old name as an alias.",
    "Slack token for the test: [REDACTED:slack-bot-token]",
    "Try a quick experiment with the parser.",
}


def test_claude_code_dry_run_counts_only(env, tmp_path):
    fx, data_root, e = env
    stats_file = tmp_path / "stats.json"
    proc = _run("ai-l0-claude-code.py", ["--dry-run", "--stats-json", str(stats_file)], e)
    stats = json.loads(stats_file.read_text())
    assert stats["kept"] == len(CC_KEPT)
    assert stats["session_files_read"] == 3
    assert stats["subagent_files_skipped"] == 1
    assert stats["user_records"] == 22
    assert stats["sessions_with_text"] == 3
    assert stats["dropped_by_reason"] == {
        "tool_result": 1,
        "meta": 1,
        "compaction_summary": 1,
        "task_notification": 1,
        "teammate_or_cross_session": 1,
        "command": 2,
        "interrupted": 1,
        "injected": 1,
        "suggestion": 1,
        "sdk": 1,
        "empty_after_cleaning": 1,
        "duplicate": 1,
        "subagent": 1,
    }
    assert stats["pasted_blocks_removed"] == 2  # one in a kept message, one in a paste-only message
    assert stats["redactions"] == {
        "anthropic-api-key": 1,
        "github-pat": 1,
        "generic-api-key": 1,
        "slack-bot-token": 1,
    }
    assert not (data_root / "ai-history").exists()
    # a dry run prints counts, never the text
    for word in ("screenshot", "experiment", "alias", "chart", "plain words", "REDACTED"):
        assert word not in proc.stdout


def test_claude_code_writes_only_typed_text(env):
    fx, data_root, e = env
    _run("ai-l0-claude-code.py", [], e)
    rows = _read(data_root)
    _assert_contract(rows)
    assert {r["text"] for r in rows} == CC_KEPT
    assert {r["source"] for r in rows} == {"claude-code"}
    assert {r["project"] for r in rows} == {"demo-app", "old-tool", "scratch"}
    joined = "\n".join(r["text"] for r in rows)
    for gone in (
        "system-reminder",
        "Injected context",
        "pasted",
        "[Image",
        "tool output",
        "parent agent",
        "Sidechain",
        "scheduled job",
        "SDK",
        "teammate",
        "Run the tests",
    ):
        assert gone not in joined
    first = next(r for r in rows if r["text"].startswith("Keep answers"))
    assert first == {
        "source": "claude-code",
        "session_id": "aaaaaaaa-0000-4000-8000-000000000001",
        "project": "demo-app",
        "ts": "2026-03-02T09:00:00Z",
        "text": first["text"],
    }
    # rows are sorted by time
    assert [r["ts"] for r in rows] == sorted(r["ts"] for r in rows)


def test_claude_code_filters_and_email_redaction(env, tmp_path):
    fx, data_root, e = env
    st = tmp_path / "s.json"
    _run("ai-l0-claude-code.py", ["--dry-run", "--since", "2026-01-01", "--stats-json", str(st)], e)
    assert json.loads(st.read_text())["kept"] == len(CC_KEPT) - 1
    _run(
        "ai-l0-claude-code.py",
        ["--dry-run", "--exclude-project", "scratch", "--stats-json", str(st)],
        e,
    )
    assert json.loads(st.read_text())["dropped_by_reason"]["project_filter"] == 1
    _run("ai-l0-claude-code.py", ["--dry-run", "--project", "old-tool", "--stats-json", str(st)], e)
    assert json.loads(st.read_text())["kept"] == 2
    _run("ai-l0-claude-code.py", ["--dry-run", "--include-sdk", "--stats-json", str(st)], e)
    assert json.loads(st.read_text())["kept"] == len(CC_KEPT) + 1
    _run("ai-l0-claude-code.py", ["--redact-emails"], e)
    texts = [r["text"] for r in _read(data_root)]
    assert not any("demo@example.com" in t for t in texts)
    assert any("[REDACTED:email]" in t for t in texts)


def test_claude_code_rerun_replaces_own_lines_and_keeps_others(env):
    fx, data_root, e = env
    out = data_root / "ai-history" / "messages.jsonl"
    out.parent.mkdir(parents=True)
    other = {
        "source": "chatgpt",
        "session_id": "x",
        "project": "",
        "ts": "2026-01-01T00:00:00Z",
        "text": "keep me",
    }
    out.write_text(json.dumps(other) + "\n", encoding="utf-8")
    _run("ai-l0-claude-code.py", [], e)
    _run("ai-l0-claude-code.py", [], e)
    rows = _read(data_root)
    assert other in rows
    assert len(rows) == len(CC_KEPT) + 1
    # a narrowed run adds; excluding a project removes its old lines
    _run("ai-l0-claude-code.py", ["--since", "2026-03-01", "--exclude-project", "scratch"], e)
    rows = _read(data_root)
    assert not any(r["project"] == "scratch" for r in rows)
    assert len(rows) == len(CC_KEPT)


def test_claude_code_missing_logs_is_a_clear_message(tmp_path):
    env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_CONFIG_DIR", "SBK_DATA_ROOT")}
    env.update(
        {"CLAUDE_CONFIG_DIR": str(tmp_path / "nothing"), "SBK_DATA_ROOT": str(tmp_path / "d")}
    )
    proc = subprocess.run(
        [sys.executable, str(TOOLS / "ai-l0-claude-code.py"), "--dry-run"],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    assert proc.returncode == 1
    assert "No Claude Code logs found" in proc.stdout
    assert "Traceback" not in proc.stderr


# ----------------------------------------------------------------------------- exports
def test_import_chatgpt_zip(env, tmp_path):
    fx, data_root, e = env
    z = tmp_path / "chatgpt-export.zip"
    with zipfile.ZipFile(z, "w") as zf:
        for f in (fx / "chatgpt").iterdir():
            zf.write(f, f.name)
        zf.writestr("chat.html", "<html></html>")
    st = tmp_path / "s.json"
    _run("ai-l0-import-export.py", [str(z), "--stats-json", str(st)], e)
    rows = _read(data_root)
    _assert_contract(rows)
    assert {r["source"] for r in rows} == {"chatgpt"}
    assert {r["text"] for r in rows} == {
        "Draft a plan for the demo launch. My key is [REDACTED:openai-api-key]",
        "Draft a shorter plan for the demo launch.",
        "What is in this picture?\n\nand say it out loud",
        "Summarise the notes in three bullets.",
    }
    assert {r["project"] for r in rows} == {"", "g-p-demo123"}
    stats = json.loads(st.read_text())["chatgpt"]
    assert stats["dropped:custom_instructions"] == 1
    assert stats["dropped:hidden"] == 1
    assert stats["dropped:role_assistant"] == 2
    assert json.loads(st.read_text())["_unrecognised_files"] == 0


def test_import_claude_ai_folder(env):
    fx, data_root, e = env
    _run("ai-l0-import-export.py", [str(fx / "claude_ai")], e)
    rows = _read(data_root)
    _assert_contract(rows)
    assert [(r["source"], r["project"], r["text"]) for r in rows] == [
        ("claude-ai", "Website", "Rewrite the pricing page in a friendlier tone."),
        ("claude-ai", "Website", "Use this AWS key in the example: [REDACTED:aws-access-token]"),
    ]
    assert rows[0]["ts"] == "2026-03-04T12:00:10Z"
    assert not any("Attached text" in r["text"] for r in rows)


def test_import_manus_folder(env, tmp_path):
    fx, data_root, e = env
    st = tmp_path / "s.json"
    _run(
        "ai-l0-import-export.py",
        [str(fx / "manus"), "--format", "manus", "--stats-json", str(st)],
        e,
    )
    rows = _read(data_root)
    _assert_contract(rows)
    assert {r["source"] for r in rows} == {"manus"}
    assert {r["text"] for r in rows} == {
        "Find five competitors of a demo note-taking app.\nKeep it to public facts.",
        "Now put them in a table.",
        "Book nothing, just compare three demo flights.",
    }
    assert json.loads(st.read_text())["manus"]["files_without_role_markers"] == 1
    _run(
        "ai-l0-import-export.py",
        [str(fx / "manus"), "--format", "manus", "--whole-file-is-mine"],
        e,
    )
    assert "A note with no turn markers." in {r["text"] for r in _read(data_root)}


def test_import_auto_does_not_guess_unknown_files(env, tmp_path):
    fx, data_root, e = env
    proc = _run("ai-l0-import-export.py", [str(fx / "manus"), "--dry-run"], e)
    assert "not recognised" in proc.stdout
    assert "Book nothing" not in proc.stdout
    assert not (data_root / "ai-history").exists()


def test_all_sources_share_one_file(env):
    fx, data_root, e = env
    _run("ai-l0-claude-code.py", [], e)
    _run("ai-l0-import-export.py", [str(fx / "chatgpt"), str(fx / "claude_ai")], e)
    _run("ai-l0-import-export.py", [str(fx / "manus"), "--format", "manus"], e)
    _run("ai-l0-claude-code.py", [], e)  # a re-run keeps the imported lines
    rows = _read(data_root)
    _assert_contract(rows)
    counts = {s: sum(1 for r in rows if r["source"] == s) for s in {r["source"] for r in rows}}
    assert counts == {"claude-code": len(CC_KEPT), "chatgpt": 4, "claude-ai": 2, "manus": 3}


# ----------------------------------------------------------------------------- redaction
def _redact_module():
    spec = importlib.util.spec_from_file_location("ai_redact", TOOLS / "ai_redact.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize(
    "secret,rule",
    [
        (FAKE["ANTHROPIC_KEY"], "anthropic-api-key"),
        (FAKE["OPENAI_KEY"], "openai-api-key"),
        (FAKE["GITHUB_TOKEN"], "github-pat"),
        (FAKE["SLACK_TOKEN"], "slack-bot-token"),
        (FAKE["AWS_KEY"], "aws-access-token"),
        ("AI" + "za" + "SyA1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q", "gcp-api-key"),
        ("GOC" + "SPX-" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4", "google-oauth-client-secret"),
        ("sk" + "_live_" + "4eC39HqLyjWDarjtT1zdp7dc", "stripe-access-token"),
        ("ey" + "JhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N", "jwt"),
    ],
)
def test_redact_vendor_tokens(secret, rule):
    mod = _redact_module()
    out, hits = mod.redact(f"use {secret} here")
    assert secret not in out
    assert out == f"use [REDACTED:{rule}] here"
    assert hits[rule] == 1


def test_redact_keeps_ordinary_text_and_handles_urls_and_keys():
    mod = _redact_module()
    plain = "The token budget is fine; password reset page; secret sauce."
    assert mod.redact(plain)[0] == plain
    out, hits = mod.redact("db at postgres://demo:" + "S3cr3tPass" + "@db.example:5432/app")
    assert out == "db at postgres://demo:[REDACTED:url-credentials]@db.example:5432/app"
    pem = "-----BEGIN " + "PRIVATE KEY-----\nMIIBVQIBADANBg\n-----END " + "PRIVATE KEY-----"
    out, hits = mod.redact("key:\n" + pem)
    assert out == "key:\n[REDACTED:private-key]"
    out, _ = mod.redact("write to alex@example.com", emails=True)
    assert out == "write to [REDACTED:email]"
    assert mod.redact("write to alex@example.com")[0] == "write to alex@example.com"
