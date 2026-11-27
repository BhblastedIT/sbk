"""Tests for tools/ai-history/ai-l3-how-you-work.py. No test calls a model: the model call
path is replaced by a fake, and the real one is made to fail if anything reaches it."""

import importlib.util
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "ai-history" / "ai-l3-how-you-work.py"


@pytest.fixture(scope="module")
def hyw():
    spec = importlib.util.spec_from_file_location("ai_l3_how_you_work", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["ai_l3_how_you_work"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(autouse=True)
def no_model(monkeypatch, hyw):
    def boom():
        raise AssertionError("a test reached the real model call path")

    monkeypatch.setattr(hyw, "_default_caller", boom)
    for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY", "DEEPSEEK_API_KEY"):
        monkeypatch.delenv(var, raising=False)


def _rows():
    t0 = datetime(2026, 1, 5, 9, tzinfo=UTC)
    rows = []
    for s in range(6):
        sid = f"s{s}"
        proj = "demo-shop" if s % 2 else "demo-blog"
        t = t0 + timedelta(days=s)
        texts = [
            "Never use em dashes in anything you write for me.",
            "Can you check why the product page is slow on mobile?",
            "Scrivi una bozza breve per la newsletter di dicembre, tono gentile.",
        ]
        if s < 3:
            texts.append("Sempre i test dopo ogni modifica, ricordati.")
        if s in (1, 4):
            texts.append("No, I told you to keep the old file as it was.")
        if s == 2:
            texts.append('Traceback (most recent call last):\n  File "x.py", line 1\nValueError: x')
            texts.append("my key is sk-ant-abcdefghijklmnopqrstuvwxyz0123 mail alex@demo.example")
        for i, tx in enumerate(texts):
            rows.append(
                {
                    "source": "claude-code" if s < 4 else "chatgpt",
                    "session_id": sid,
                    "project": proj,
                    "ts": (t + timedelta(minutes=i)).isoformat(),
                    "text": tx,
                }
            )
    return rows


@pytest.fixture
def env(tmp_path, monkeypatch):
    root = tmp_path / "data"
    (root / "ai-history").mkdir(parents=True)
    path = root / "ai-history" / "messages.jsonl"
    with path.open("w", encoding="utf-8") as fh:
        for r in _rows():
            fh.write(json.dumps(r) + "\n")
        fh.write("{broken\n")
    monkeypatch.setenv("SBK_DATA_ROOT", str(root))
    out = tmp_path / "identity"
    return {"root": root, "input": path, "out": out}


class FakeCaller:
    def __init__(self):
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return "```markdown\n# Title\n\nbody for " + kwargs["prompt"].split("\n", 1)[0] + "\n```"


def test_load_skips_bad_lines_and_flags(hyw, env):
    res = hyw.load_messages(env["input"])
    assert res.bad_lines == 1
    assert any(m.paste for m in res.messages)
    assert sum(m.correction for m in res.messages) == 2
    assert {m.lang for m in res.messages} >= {"en", "it"}


def test_step1_finds_recurring_instructions(hyw, env):
    res = hyw.load_messages(env["input"])
    stats = hyw.compute_stats(res.messages, min_sessions=2)
    texts = {r["text"]: r["sessions"] for r in stats["recurring_instructions"]}
    assert texts.get("Never use em dashes in anything you write for me.") == 6
    assert any("ricordati" in t.lower() and n == 3 for t, n in texts.items())
    assert stats["totals"]["sessions"] == 6 and stats["totals"]["pasted_messages"] == 1
    assert stats["recurring_corrections"][0]["sessions"] == 2
    assert {t["project"] for t in stats["topics_by_project"]} == {"demo-shop", "demo-blog"}
    assert set(stats["languages_pct"]) >= {"en", "it"}
    # a phrase already inside a recurring instruction is not repeated as a phrase
    assert not any("em dashes" in p["phrase"] for p in stats["recurring_phrases"])


def test_near_duplicate_sentences_group(hyw):
    m1 = hyw.Message("x", "a", "p", None, "t", idx=0)
    m2 = hyw.Message("x", "b", "p", None, "t", idx=1)
    groups = hyw.group_sentences(
        [
            ("Always run the full tests after every change.", m1),
            ("always run the tests after every single change", m2),
        ]
    )
    assert len(groups) == 1 and len(groups[0].sessions) == 2


def test_redaction(hyw):
    text, n = hyw.redact(
        "key sk-ant-abcdefghijklmnopqrstuvwxyz0123, token: abc123, mail alex@demo.example,"
        " call +44 7700 900123, date 2026-11-25, path /Users/demo/projects/some-long-folder-name/x"
    )
    assert "sk-ant" not in text and "abc123" not in text and "alex@demo.example" not in text
    assert "[phone]" in text and "2026-11-25" in text and "/Users/demo/projects" in text
    assert n >= 4


def test_without_yes_nothing_is_sent(hyw, env, capsys):
    fake = FakeCaller()
    rc = hyw.run(["--input", str(env["input"]), "--out-dir", str(env["out"])], caller=fake)
    assert rc == 2 and fake.calls == []
    assert not env["out"].exists()
    out = capsys.readouterr().out
    assert "what would be sent" in out and "api.anthropic.com" in out and "Nothing was sent" in out


def test_dry_run_sends_nothing_even_with_yes(hyw, env, capsys):
    fake = FakeCaller()
    rc = hyw.run(
        [
            "--input",
            str(env["input"]),
            "--out-dir",
            str(env["out"]),
            "--dry-run",
            "--yes",
            "--show-payload",
            "--max-chars",
            "3000",
        ],
        caller=fake,
    )
    assert rc == 0 and fake.calls == []
    assert not env["out"].exists()
    payload = (env["root"] / "ai-history" / "how-you-work-payload.txt").read_text(encoding="utf-8")
    assert len(payload) <= 3000
    assert "sk-ant" not in payload and "alex@demo.example" not in payload


def test_stats_only(hyw, env):
    rc = hyw.run(["--input", str(env["input"]), "--stats-only"])
    assert rc == 0
    stats = json.loads((env["root"] / "ai-history" / "how-you-work-stats.json").read_text())
    assert stats["totals"]["messages"] == len(_rows())


def test_yes_writes_five_files_then_new_md_then_force(hyw, env):
    fake = FakeCaller()
    args = ["--input", str(env["input"]), "--out-dir", str(env["out"]), "--yes"]
    assert hyw.run(args, caller=fake) == 0
    assert len(fake.calls) == 5
    assert {c["provider"] for c in fake.calls} == {"anthropic"}
    assert all(c["cache_system"] for c in fake.calls)
    assert all("sk-ant" not in c["system"] for c in fake.calls)
    names = sorted(p.name for p in env["out"].iterdir())
    assert names == sorted(hyw.IDENTITY_FILES)
    body = (env["out"] / "profile.md").read_text()
    assert body.startswith("<!-- Generated by") and "```" not in body

    (env["out"] / "profile.md").write_text("my own edits\n")
    assert hyw.run(args + ["--only", "profile.md"], caller=fake) == 0
    assert (env["out"] / "profile.md").read_text() == "my own edits\n"
    assert (env["out"] / "profile.new.md").exists()

    assert hyw.run(args + ["--only", "profile.md", "--force"], caller=fake) == 0
    assert (env["out"] / "profile.md").read_text().startswith("<!-- Generated by")


def test_playbook_prompt_uses_draft_headers(hyw):
    headers = hyw._playbook_headers()
    prompt = hyw.file_prompt("communication-playbook.md", "English")
    assert headers and all(h in prompt for h in headers)


def test_default_model_matches_call_path(hyw):
    assert hyw.default_model("anthropic").startswith("claude-")


def test_model_failure_is_reported(hyw, env):
    def failing(**kwargs):
        raise RuntimeError("no key")

    rc = hyw.run(
        [
            "--input",
            str(env["input"]),
            "--out-dir",
            str(env["out"]),
            "--yes",
            "--only",
            "style-guide.md",
        ],
        caller=failing,
    )
    assert rc == 1
    assert not (env["out"] / "style-guide.md").exists()


def test_identity_folder_is_git_ignored():
    lines = [ln.strip() for ln in (ROOT / ".gitignore").read_text().splitlines()]
    assert any(ln.rstrip("/") in ("sbk/identity", "/sbk/identity") for ln in lines)


def test_playbook_headers_are_the_neutral_segments(hyw):
    headers = hyw._playbook_headers()
    assert headers == hyw.DEFAULT_PLAYBOOK_HEADERS
    assert headers == [
        "#### Investors",
        "#### Clients",
        "#### Partners",
        "#### Team",
        "#### Family / friends",
        "#### Other",
    ]


def _draft_module():
    pytest.importorskip("pandas")
    path = ROOT / "tools" / "cross-source" / "xs-l3-draft.py"
    for p in (str(ROOT / "tools"), str(path.parent)):
        if p not in sys.path:
            sys.path.insert(0, p)
    spec = importlib.util.spec_from_file_location("xs_l3_draft_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except ImportError as e:  # an optional dependency of the draft writer is missing
        pytest.skip(f"xs-l3-draft.py not importable here: {e}")
    return mod


def test_draft_finds_every_section_the_playbook_prompt_asks_for(hyw):
    draft = _draft_module()
    playbook = "# Communication playbook\n\n## General\nBe brief.\n\n" + "".join(
        f"{h}\nRules for {seg}.\n\n" for seg, h in draft.SEGMENT_SYSTEM_SECTIONS.items()
    )
    for seg in ("investors", "clients", "partners", "team", "family", "other"):
        section = draft._extract_playbook_section(playbook, seg)
        assert section.startswith(draft.SEGMENT_SYSTEM_SECTIONS[seg])
        assert section.endswith(f"Rules for {seg}.")
    # a header that only starts the same way is not taken for another one
    assert draft._extract_playbook_section("#### Teams\nx\n", "team") == ""
    assert draft._extract_playbook_section(playbook, "unknown") == ""


def test_redaction_markers_are_not_topic_words(hyw):
    t0 = datetime(2026, 1, 5, 9, tzinfo=UTC)
    texts = [
        "Deploy the demo shop with key [REDACTED:anthropic-api-key] tonight",
        "Use the token [REDACTED:github-pat] for the demo shop pipeline",
        "Mail [REDACTED:email] about the demo shop launch, password: [REDACTED]",
        "Check the demo shop checkout, my key is [REDACTED key] and [email] [phone]",
    ]
    msgs = [
        hyw.Message("claude-code", f"s{i}", "demo-shop", t0 + timedelta(days=i), tx, idx=i)
        for i, tx in enumerate(texts)
    ]
    stats = hyw.compute_stats(msgs, min_sessions=2)
    words = set(stats["topics_by_project"][0]["keywords"]) | set(stats["vocabulary"]["top_words"])
    assert "shop" in words
    for marker_word in ("redacted", "anthropic-api-key", "github-pat", "email", "phone"):
        assert marker_word not in words


def test_plan_reports_redactions_of_readers_and_this_pass(hyw, env, capsys):
    with env["input"].open("a", encoding="utf-8") as fh:
        for i in range(2):
            fh.write(
                json.dumps(
                    {
                        "source": "claude-code",
                        "session_id": f"r{i}",
                        "project": "demo-blog",
                        "ts": f"2026-02-0{i + 1}T10:00:00+00:00",
                        "text": "Publish the post with key [REDACTED:openai-api-key] please today",
                    }
                )
                + "\n"
            )
    loaded = hyw.load_messages(env["input"])
    stats = hyw.compute_stats(loaded.messages)
    _, info = hyw.build_evidence(loaded.messages, stats, 60_000)
    assert info["redactions_by_readers"] >= 2
    assert info["redactions_this_pass"] >= 2  # the sk-ant key and the e-mail of the fixture
    assert info["redactions_in_sample"] == (
        info["redactions_by_readers"] + info["redactions_this_pass"]
    )
    rc = hyw.run(["--input", str(env["input"]), "--out-dir", str(env["out"]), "--dry-run"])
    assert rc == 0
    out = capsys.readouterr().out
    assert f"redacted in what would be sent: {info['redactions_in_sample']} in total" in out
    assert f"{info['redactions_by_readers']} by the readers" in out


def _function_strings(path: Path, func: str) -> set[str]:
    import ast

    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == func:
            return {
                n.value
                for n in ast.walk(node)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)
            }
    return set()


def test_every_identity_file_is_read_by_drafts_and_dashboard(hyw):
    loader = _function_strings(
        ROOT / "tools" / "cross-source" / "xs_l3_common.py", "load_identity_files"
    )
    dashboard = hyw._read_constant(
        ROOT / "dashboard" / "app" / "core" / "chat_tools.py", "_IDENTITY_FILES"
    )
    for name in hyw.IDENTITY_FILES:
        assert name in loader, f"load_identity_files() does not read {name}"
        assert name in dashboard, f"the dashboard chat does not read {name}"
