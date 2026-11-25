"""AI history plugin (tools/ai-history/), end to end.

What this file proves:
  1. the Claude Code reader keeps only what the person typed (every kind of non-typed
     content in a session log is dropped, and counted by reason);
  2. secrets are redacted before anything is written, and again before anything could be sent;
  3. each export importer (ChatGPT, Claude.ai, Manus, generic) works on the fixtures;
  4. step 1 of "how you work" is local and deterministic;
  5. --dry-run never reaches a model: the model call path is mocked and the network is cut;
  6. the plugin is registered as an on-request source, outside the automatic run, and the
     identity files it writes are git-ignored.

No test calls a model or the network. All text is demo text. Token-shaped strings are built
from pieces at run time, so no secret-looking literal sits in the repo.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import socket
import subprocess
import sys
import zipfile
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools" / "ai-history"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "ai_history"
FIELDS = ["source", "session_id", "project", "ts", "text"]

FAKE = {
    "ANTHROPIC_KEY": "sk-" + "ant-" + "api03-" + "Pq7Lm" * 8,
    "OPENAI_KEY": "sk-" + "proj-" + "Hy6Tg4" * 8,
    "GITHUB_TOKEN": "gh" + "p_" + "Z9y8X7w6" * 5,
    "SLACK_TOKEN": "xo" + "xb-" + "210987654321-210987654321-" + "QwErTyUiOpAsDfGhJkLzXcVb",
    "AWS_KEY": "AK" + "IA" + "ZXCVBN234567QWER",
    "PASSWORD": "Gr4ss" + "hopper-7Kz",
}

MODEL_MODULES = ("anthropic", "openai", "xs_l3_common")


# ----------------------------------------------------------------------------- helpers
def _load(name: str, path: Path):
    if str(TOOLS) not in sys.path:
        sys.path.insert(0, str(TOOLS))
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def cc():
    return _load("ai_l0_claude_code_it", TOOLS / "ai-l0-claude-code.py")


@pytest.fixture(scope="module")
def imp():
    return _load("ai_l0_import_export_it", TOOLS / "ai-l0-import-export.py")


@pytest.fixture(scope="module")
def red():
    return _load("ai_redact_it", TOOLS / "ai_redact.py")


@pytest.fixture(scope="module")
def hyw():
    return _load("ai_l3_how_you_work_it", TOOLS / "ai-l3-how-you-work.py")


def _env(**extra: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_CONFIG_DIR", "SBK_DATA_ROOT")}
    for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY", "DEEPSEEK_API_KEY"):
        env.pop(var, None)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.update(extra)
    return env


def _run(script: str, args: list[str], env: dict[str, str], rc: int = 0):
    proc = subprocess.run(
        [sys.executable, str(TOOLS / script), *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )
    assert proc.returncode == rc, proc.stdout + proc.stderr
    return proc


def _rows(data_root: Path) -> list[dict]:
    path = data_root / "ai-history" / "messages.jsonl"
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def _no_secret(text: str) -> None:
    for value in FAKE.values():
        assert value not in text


def _materialise(tmp_path: Path) -> Path:
    """Copy the shared fixtures and put fake tokens in place of their {{PLACEHOLDERS}}."""
    dst = tmp_path / "fixtures"
    shutil.copytree(FIXTURES, dst)
    for f in dst.rglob("*"):
        if f.is_file():
            body = f.read_text(encoding="utf-8")
            for name, value in FAKE.items():
                body = body.replace("{{" + name + "}}", value)
            f.write_text(body, encoding="utf-8")
    return dst


@pytest.fixture()
def no_network(monkeypatch):
    """Any attempt to open a connection fails the test."""

    def refuse(*args, **kwargs):
        raise AssertionError(f"a network connection was attempted: {args!r}")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


# ----------------------------------------------------------------------------- 1. Claude Code
SID = "dddddddd-0000-4000-8000-000000000004"
LEGACY_SID = "eeeeeeee-0000-4000-8000-000000000005"
NEW = "2.1.30"


def _rec(n: int, content, **fields) -> dict:
    rec = {
        "parentUuid": None,
        "isSidechain": False,
        "userType": "external",
        "cwd": "/home/demo/projects/demo-site",
        "sessionId": SID,
        "version": NEW,
        "type": "user",
        "message": {"role": "user", "content": content},
        "uuid": f"u{n:02d}",
        "timestamp": f"2026-04-01T10:{n:02d}:00.000Z",
        "entrypoint": "cli",
    }
    rec.update(fields)
    return rec


TYPED = {"origin": {"kind": "human"}, "promptSource": "typed"}


def _session_lines() -> list[dict]:
    """One record per case. The comment says what the reader must do with it."""
    return [
        # kept, once cleaned: the reminder, the paste and the image marker are not typed text
        _rec(
            1,
            "Please keep the changelog in plain English. [Image #1]\n"
            "<pasted_content>ERROR 42 at line 7 of the demo log</pasted_content>\n"
            "<system-reminder>Injected context for the model.</system-reminder>",
            **TYPED,
        ),
        # kept, with the secret redacted
        _rec(2, "Deploy the demo with key " + FAKE["ANTHROPIC_KEY"], **TYPED),
        # kept: a list of text parts typed at the prompt
        _rec(3, [{"type": "text", "text": "Then open a draft pull request."}], **TYPED),
        # tool_result: tool output fed back to the model
        _rec(
            4,
            [{"type": "tool_result", "tool_use_id": "t1", "content": "demo tool output"}],
        ),
        # meta: context Claude Code injects
        _rec(5, "Caveat: demo injected caveat", isMeta=True, **TYPED),
        # compaction_summary
        _rec(
            6,
            "This session is being continued from a previous demo conversation.",
            isCompactSummary=True,
        ),
        # task_notification
        _rec(
            7,
            "<task-notification>demo task finished</task-notification>",
            origin={"kind": "task-notification"},
        ),
        # teammate_or_cross_session
        _rec(
            8,
            '<teammate-message from="demo">hello from a teammate</teammate-message>',
            origin={"kind": "teammate"},
        ),
        # sdk: a script sent it through `claude -p`
        _rec(
            9,
            "Summarise the demo log from a script.",
            entrypoint="sdk-cli",
            promptSource="sdk",
            origin={"kind": "human"},
        ),
        # command: slash-command wrapper
        _rec(10, "<command-name>/model</command-name>", **TYPED),
        # interrupted marker
        _rec(11, "[Request interrupted by user]", **TYPED),
        # injected: no typed marks in a session whose version writes them
        _rec(12, "A scheduled demo prompt placed by another program."),
        # suggestion: accepted with one key
        _rec(
            13, "Run the demo tests", origin={"kind": "human"}, promptSource="suggestion_accepted"
        ),
        # automatic: a workflow harness task
        _rec(14, "[Workflow harness] demo computed task text", **TYPED),
        # empty_after_cleaning: only pasted material
        _rec(15, "<pasted_content>only pasted demo text</pasted_content>", **TYPED),
        # duplicate: the same record seen again (a resumed session)
        _rec(1, "Please keep the changelog in plain English.", **TYPED),
        # not a user record at all: the assistant's answer is never read as yours
        {
            "type": "assistant",
            "sessionId": SID,
            "uuid": "a01",
            "message": {"role": "assistant", "content": [{"type": "text", "text": "Demo answer."}]},
            "timestamp": "2026-04-01T10:20:00.000Z",
        },
    ]


CC_KEPT = {
    "Please keep the changelog in plain English.",
    "Deploy the demo with key [REDACTED:anthropic-api-key]",
    "Then open a draft pull request.",
    # the legacy session (older version, no typed marks): its plain prompt is kept
    "Write the release notes for the demo.",
}
CC_DROPPED = {
    "tool_result": 1,
    "meta": 1,
    "compaction_summary": 1,
    "task_notification": 1,
    "teammate_or_cross_session": 1,
    "sdk": 1,
    "command": 1,
    "interrupted": 1,
    "injected": 1,
    "suggestion": 1,
    "automatic": 1,
    "empty_after_cleaning": 1,
    "duplicate": 1,
}


@pytest.fixture()
def claude_home(tmp_path) -> Path:
    home = tmp_path / "claude"
    proj = home / "projects" / "-home-demo-projects-demo-site"
    proj.mkdir(parents=True)
    with (proj / f"{SID}.jsonl").open("w", encoding="utf-8") as fh:
        for rec in _session_lines():
            fh.write(json.dumps(rec) + "\n")
        fh.write("{ not json\n")
    legacy = {
        **_rec(1, "Write the release notes for the demo."),
        "sessionId": LEGACY_SID,
        "version": "1.0.40",
        "uuid": "L01",
        "timestamp": "2026-02-01T09:00:00.000Z",
    }
    (proj / f"{LEGACY_SID}.jsonl").write_text(json.dumps(legacy) + "\n", encoding="utf-8")
    sub = proj / SID / "subagents"
    sub.mkdir(parents=True)
    (sub / "agent-demo.jsonl").write_text(
        json.dumps(_rec(30, "Prompt written by a parent agent, not by you.", **TYPED)) + "\n",
        encoding="utf-8",
    )
    return home


def test_claude_code_drops_everything_not_typed(claude_home, tmp_path):
    data = tmp_path / "data"
    env = _env(CLAUDE_CONFIG_DIR=str(claude_home), SBK_DATA_ROOT=str(data))
    stats_file = tmp_path / "stats.json"
    proc = _run("ai-l0-claude-code.py", ["--dry-run", "--stats-json", str(stats_file)], env)
    stats = json.loads(stats_file.read_text())
    assert stats["kept"] == len(CC_KEPT)
    assert stats["dropped_by_reason"] == CC_DROPPED
    assert stats["session_files_read"] == 2
    assert stats["subagent_files_skipped"] == 1
    assert stats["pasted_blocks_removed"] == 2
    assert stats["redactions"] == {"anthropic-api-key": 1}
    # a dry run writes nothing and prints counts, never your text
    assert not (data / "ai-history").exists()
    for word in ("changelog", "pull request", "release notes", "REDACTED"):
        assert word not in proc.stdout

    _run("ai-l0-claude-code.py", [], env)
    rows = _rows(data)
    assert {r["text"] for r in rows} == CC_KEPT
    assert all(list(r) == FIELDS for r in rows)
    assert {r["source"] for r in rows} == {"claude-code"}
    assert {r["project"] for r in rows} == {"demo-site"}
    joined = "\n".join(r["text"] for r in rows)
    for gone in (
        "ERROR 42",
        "Injected context",
        "[Image",
        "demo tool output",
        "injected caveat",
        "continued from",
        "task finished",
        "teammate",
        "from a script",
        "/model",
        "interrupted",
        "scheduled demo prompt",
        "Run the demo tests",
        "computed task",
        "only pasted",
        "Demo answer",
        "parent agent",
    ):
        assert gone not in joined
    _no_secret(joined)
    assert (data / "ai-history" / "messages.jsonl").stat().st_mode & 0o077 == 0


def test_claude_code_classify_unit(cc):
    """The same rules, record by record, without files."""
    reasons = {}
    for rec in _session_lines():
        if rec.get("type") != "user":
            continue
        reason, _ = cc.classify(rec, include_sdk=False, marked_session=True)
        reasons.setdefault(reason, 0)
        reasons[reason] += 1
    # record by record, the 3 kept prompts, the duplicate (a file-level decision) and the
    # paste-only prompt (emptied later by clean_text) all pass classify
    assert reasons.pop(None) == 5
    expected = {
        k: v for k, v in CC_DROPPED.items() if k not in ("duplicate", "empty_after_cleaning")
    }
    assert reasons == expected
    # --include-sdk keeps the script prompt
    sdk = next(r for r in _session_lines() if r.get("entrypoint") == "sdk-cli")
    assert cc.classify(sdk, include_sdk=True, marked_session=True)[0] is None
    # an unmarked prompt is yours when the session predates the marks
    plain = _rec(1, "Write the release notes for the demo.")
    assert cc.classify(plain, include_sdk=False, marked_session=False)[0] is None
    assert cc.classify(plain, include_sdk=False, marked_session=True)[0] == "injected"
    text, pasted = cc.clean_text(
        "Fix it. [Pasted text #2 +40 lines]\n<pasted_content>x</pasted_content>"
        "<system-reminder>r</system-reminder>"
    )
    assert (text, pasted) == ("Fix it.", 1)


def test_claude_code_honours_claude_config_dir(tmp_path):
    env = _env(CLAUDE_CONFIG_DIR=str(tmp_path / "elsewhere"), SBK_DATA_ROOT=str(tmp_path / "d"))
    proc = _run("ai-l0-claude-code.py", ["--dry-run"], env, rc=1)
    assert str(tmp_path / "elsewhere" / "projects") in proc.stdout
    assert "Traceback" not in proc.stderr


# ----------------------------------------------------------------------------- 2. redaction
@pytest.mark.parametrize(
    "secret,rule",
    [
        (FAKE["ANTHROPIC_KEY"], "anthropic-api-key"),
        (FAKE["OPENAI_KEY"], "openai-api-key"),
        (FAKE["GITHUB_TOKEN"], "github-pat"),
        (FAKE["SLACK_TOKEN"], "slack-bot-token"),
        (FAKE["AWS_KEY"], "aws-access-token"),
    ],
)
def test_reader_redaction_names_the_rule(red, secret, rule):
    out, hits = red.redact(f"the value {secret} is here")
    assert out == f"the value [REDACTED:{rule}] is here"
    assert dict(hits) == {rule: 1}


def test_reader_redaction_keeps_the_sentence(red):
    out, hits = red.redact("my password: " + FAKE["PASSWORD"] + " and the token budget is fine")
    assert out == "my password: [REDACTED:generic-api-key] and the token budget is fine"
    out, _ = red.redact("mysql://demo:" + "Hunter2" + "pass@db.example/app")
    assert out == "mysql://demo:[REDACTED:url-credentials]@db.example/app"
    assert red.redact("mail alex@demo.example")[0] == "mail alex@demo.example"
    assert red.redact("mail alex@demo.example", emails=True)[0] == "mail [REDACTED:email]"


def test_second_pass_before_sending(hyw):
    """How-you-work redacts again, with the readers' rules plus contacts, before anything
    could be sent: a secret that reached messages.jsonl unredacted is still caught."""
    text, n = hyw.redact(
        "use " + FAKE["SLACK_TOKEN"] + ", write to alex@demo.example, call +1 202 555 0147,"
        " on 2026-04-01"
    )
    _no_secret(text)
    assert "alex@demo.example" not in text and "[phone]" in text and "2026-04-01" in text
    assert n >= 3
    # the first pass is the readers' module, named by rule
    assert "[REDACTED:slack-bot-token]" in text


# ----------------------------------------------------------------------------- 3. export importers
@pytest.fixture()
def fx(tmp_path):
    return _materialise(tmp_path)


def _import(fx_path: Path, args: list[str], data: Path, tmp_path: Path) -> dict:
    st = tmp_path / "import-stats.json"
    env = _env(SBK_DATA_ROOT=str(data))
    _run("ai-l0-import-export.py", [*args, "--stats-json", str(st)], env)
    return json.loads(st.read_text())


def test_import_chatgpt_export(fx, tmp_path):
    data = tmp_path / "data"
    stats = _import(fx, [str(fx / "chatgpt" / "conversations.json")], data, tmp_path)
    rows = _rows(data)
    assert {r["source"] for r in rows} == {"chatgpt"}
    texts = {r["text"] for r in rows}
    assert texts == {
        "Draft a plan for the demo launch. My key is [REDACTED:openai-api-key]",
        "Draft a shorter plan for the demo launch.",
        "What is in this picture?\n\nand say it out loud",
        "Summarise the notes in three bullets.",
    }
    assert "Here is a plan." not in "\n".join(texts)
    assert stats["chatgpt"]["dropped:role_assistant"] == 2
    _no_secret("\n".join(texts))


def test_import_claude_ai_export_zip(fx, tmp_path):
    z = tmp_path / "claude-export.zip"
    with zipfile.ZipFile(z, "w") as zf:
        for f in (fx / "claude_ai").iterdir():
            zf.write(f, f.name)
    data = tmp_path / "data"
    _import(fx, [str(z)], data, tmp_path)
    rows = _rows(data)
    assert [(r["source"], r["project"], r["text"]) for r in rows] == [
        ("claude-ai", "Website", "Rewrite the pricing page in a friendlier tone."),
        ("claude-ai", "Website", "Use this AWS key in the example: [REDACTED:aws-access-token]"),
    ]
    _no_secret(json.dumps(rows))


def test_import_manus_folder(fx, tmp_path):
    data = tmp_path / "data"
    stats = _import(fx, [str(fx / "manus"), "--format", "manus"], data, tmp_path)
    rows = _rows(data)
    assert {r["source"] for r in rows} == {"manus"}
    assert {r["text"] for r in rows} == {
        "Find five competitors of a demo note-taking app.\nKeep it to public facts.",
        "Now put them in a table.",
        "Book nothing, just compare three demo flights.",
    }
    assert not any(t in r["text"] for r in rows for t in ("Here are five", "Done.", "Comparison"))
    assert stats["manus"]["files_without_role_markers"] == 1


def test_import_generic_folder_with_own_source_name(fx, tmp_path):
    data = tmp_path / "data"
    _import(fx, [str(fx / "manus"), "--format", "generic", "--source", "demo-tool"], data, tmp_path)
    rows = _rows(data)
    assert {r["source"] for r in rows} == {"demo-tool"}
    assert len(rows) == 3


def test_import_dry_run_writes_nothing(fx, tmp_path):
    data = tmp_path / "data"
    env = _env(SBK_DATA_ROOT=str(data))
    proc = _run("ai-l0-import-export.py", [str(fx / "chatgpt"), "--dry-run"], env)
    assert not (data / "ai-history").exists()
    assert "Draft a plan" not in proc.stdout


# ----------------------------------------------------------------------------- 4. how you work, step 1
@pytest.fixture()
def history(fx, tmp_path, monkeypatch):
    """messages.jsonl built by the real readers from the fixtures."""
    data = tmp_path / "data"
    env = _env(CLAUDE_CONFIG_DIR=str(fx / "claude_code"), SBK_DATA_ROOT=str(data))
    _run("ai-l0-claude-code.py", [], env)
    _run("ai-l0-import-export.py", [str(fx / "chatgpt"), str(fx / "claude_ai")], env)
    _run("ai-l0-import-export.py", [str(fx / "manus"), "--format", "manus"], env)
    monkeypatch.setenv("SBK_DATA_ROOT", str(data))
    return data


def _strip_clock(stats: dict) -> dict:
    return {k: v for k, v in stats.items() if k != "generated_at"}


def test_step1_is_local_and_deterministic(hyw, history, tmp_path, monkeypatch, no_network):
    caller = mock.Mock(side_effect=AssertionError("step 1 must not call a model"))
    monkeypatch.setattr(hyw, "_default_caller", lambda: caller)
    stats_path = history / "ai-history" / "how-you-work-stats.json"
    out_dir = tmp_path / "identity"

    assert hyw.run(["--stats-only", "--out-dir", str(out_dir)], caller=caller) == 0
    first = json.loads(stats_path.read_text(encoding="utf-8"))
    assert hyw.run(["--stats-only", "--out-dir", str(out_dir)], caller=caller) == 0
    second = json.loads(stats_path.read_text(encoding="utf-8"))

    assert _strip_clock(first) == _strip_clock(second)
    caller.assert_not_called()
    assert not out_dir.exists()
    rows = _rows(history)
    assert first["totals"]["messages"] == len(rows)
    assert first["totals"]["sessions"] == len({r["session_id"] for r in rows})
    # the stats hold counts and short instructions, never a secret
    _no_secret(stats_path.read_text(encoding="utf-8"))

    # the evidence that step 2 would send is the same on every run
    loaded = hyw.load_messages(history / "ai-history" / "messages.jsonl")
    ev1, info1 = hyw.build_evidence(loaded.messages, first, 4000)
    ev2, info2 = hyw.build_evidence(loaded.messages, second, 4000)
    assert ev1 == ev2 and info1 == info2
    assert len(ev1) <= 4000


def test_step1_finds_an_instruction_repeated_across_sessions(hyw, tmp_path):
    path = tmp_path / "messages.jsonl"
    with path.open("w", encoding="utf-8") as fh:
        for s in range(4):
            for i, text in enumerate(
                (
                    "Always answer in short paragraphs, no tables.",
                    f"Look at the demo report number {s} and tell me what changed.",
                )
            ):
                fh.write(
                    json.dumps(
                        {
                            "source": "claude-code",
                            "session_id": f"s{s}",
                            "project": "demo",
                            "ts": f"2026-05-0{s + 1}T09:0{i}:00Z",
                            "text": text,
                        }
                    )
                    + "\n"
                )
    msgs = hyw.load_messages(path).messages
    a = hyw.compute_stats(msgs, min_sessions=2)
    b = hyw.compute_stats(msgs, min_sessions=2)
    assert _strip_clock(a) == _strip_clock(b)
    found = {r["text"]: r["sessions"] for r in a["recurring_instructions"]}
    assert found.get("Always answer in short paragraphs, no tables.") == 4


# ----------------------------------------------------------------------------- 5. --dry-run sends nothing
def test_dry_run_never_reaches_the_model(hyw, history, tmp_path, monkeypatch, no_network, capsys):
    import xs_l3_common

    real_path = mock.Mock(side_effect=AssertionError("call_claude was reached"))
    monkeypatch.setattr(xs_l3_common, "call_claude", real_path)
    default_caller = mock.Mock(side_effect=AssertionError("the model caller was loaded"))
    monkeypatch.setattr(hyw, "_default_caller", default_caller)
    out_dir = tmp_path / "identity"

    # even with the consent flag, --dry-run sends nothing and writes no identity file
    rc = hyw.run(["--dry-run", "--yes", "--show-payload", "--out-dir", str(out_dir)])
    assert rc == 0
    default_caller.assert_not_called()
    real_path.assert_not_called()
    assert not out_dir.exists()
    out = capsys.readouterr().out
    assert "what would be sent" in out and "nothing was sent" in out.lower()
    payload = (history / "ai-history" / "how-you-work-payload.txt").read_text(encoding="utf-8")
    _no_secret(payload)
    # without --yes nothing is sent either
    assert hyw.run(["--out-dir", str(out_dir)]) == 2
    default_caller.assert_not_called()
    real_path.assert_not_called()


def test_consent_flag_is_the_only_way_to_the_model(hyw, history, tmp_path, monkeypatch, no_network):
    """The positive control for the test above: with --yes (and no --dry-run) the mocked
    caller is used once per file, and what it receives is redacted."""
    fake = mock.Mock(return_value="# Working rules\n\n- Demo rule.")
    out_dir = tmp_path / "identity"
    assert (
        hyw.run(["--yes", "--only", "working-rules.md", "--out-dir", str(out_dir)], caller=fake)
        == 0
    )
    assert fake.call_count == 1
    sent = fake.call_args.kwargs
    _no_secret(sent["system"] + sent["prompt"])
    assert (
        (out_dir / "working-rules.md").read_text(encoding="utf-8").startswith("<!-- Generated by")
    )


def test_readers_dry_run_load_no_model_code(cc, imp, fx, tmp_path, monkeypatch, no_network, capsys):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(fx / "claude_code"))
    monkeypatch.setenv("SBK_DATA_ROOT", str(tmp_path / "data"))
    before = {m for m in MODEL_MODULES if m in sys.modules}
    assert cc.main(["--dry-run"]) == 0
    assert imp.main([str(fx / "chatgpt"), "--dry-run"]) == 0
    after = {m for m in MODEL_MODULES if m in sys.modules}
    assert after == before
    assert not (tmp_path / "data" / "ai-history").exists()
    for src in (TOOLS / "ai-l0-claude-code.py", TOOLS / "ai-l0-import-export.py"):
        body = src.read_text(encoding="utf-8")
        assert "call_claude" not in body and "import anthropic" not in body
    capsys.readouterr()


# ----------------------------------------------------------------------------- 6. integration
def test_registered_on_request_and_outside_the_automatic_run():
    import sorgenti

    s = sorgenti.SORGENTI["ai-history"]
    assert s.natura == "a_richiesta"
    assert "ai-l0-claude-code.py" in s.come_si_aggiorna
    assert "ai-l0-import-export.py" in s.come_si_aggiorna
    assert s.l1 == "tools/ai-history/ai-l3-how-you-work.py"
    assert (ROOT / s.l1).is_file()
    assert s.dato_in == ("messages.jsonl",)

    spec = importlib.util.spec_from_file_location(
        "xs_l0_refresh_ai_history", ROOT / "tools" / "cross-source" / "xs-l0-refresh.py"
    )
    refresh = importlib.util.module_from_spec(spec)
    sys.modules["xs_l0_refresh_ai_history"] = refresh
    spec.loader.exec_module(refresh)
    assert "ai-history" in refresh.MANUALI
    assert "ai-history" not in {p.sorgente for p in refresh.PIANO}
    assert not any("ai-history" in " ".join(p.args) for p in refresh.PIANO)
    assert "ai-history" not in refresh.controlla_copertura()
    # the pipeline runner never launches these scripts
    runner = (ROOT / "tools" / "cross-source" / "xs-pipeline-run.py").read_text(encoding="utf-8")
    assert "tools/ai-history" not in runner and "how-you-work" not in runner


def test_identity_and_history_files_are_git_ignored():
    if not (ROOT / ".git").exists() or shutil.which("git") is None:
        pytest.skip("not a git checkout")

    def ignored(path: str) -> bool:
        return (
            subprocess.run(
                ["git", "check-ignore", "-q", "--no-index", path], cwd=ROOT, check=False
            ).returncode
            == 0
        )

    for path in (
        "sbk/identity/profile.md",
        "sbk/identity/working-rules.md",
        "sbk/identity/style-guide.new.md",
        "ai-history/messages.jsonl",
        "data/ai-history/how-you-work-payload.txt",
    ):
        assert ignored(path), path
    for path in (
        "tools/ai-history/ai-l3-how-you-work.py",
        "tests/fixtures/ai_history/manus/task-001.md",
    ):
        assert not ignored(path), path


def test_no_old_prefix_left():
    """ah- belongs to apple-health; the AI history plugin uses ai-."""
    assert not list(TOOLS.glob("ah-*")) and not list(TOOLS.glob("ah_*"))
    assert not (ROOT / "tests" / "test_ah_how_you_work.py").exists()
