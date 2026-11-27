"""The ai-history files that hold numbers or a sample of what you typed are readable by you only
(mode 0600): the stats JSON, the --show-payload text and the identity files. No model is called."""

import importlib.util
import json
import stat
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT / "tools" / "ai-history"


def _load(name: str, path: Path):
    if str(HERE) not in sys.path:
        sys.path.insert(0, str(HERE))
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _mode(p: Path) -> int:
    return stat.S_IMODE(p.stat().st_mode)


@pytest.fixture(scope="module")
def hyw():
    return _load("ai_l3_how_you_work_private", HERE / "ai-l3-how-you-work.py")


@pytest.fixture
def env(tmp_path, monkeypatch, hyw):
    monkeypatch.setattr(hyw, "_default_caller", lambda: (_ for _ in ()).throw(AssertionError("model")))
    for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY", "DEEPSEEK_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    root = tmp_path / "data"
    (root / "ai-history").mkdir(parents=True)
    inp = root / "ai-history" / "messages.jsonl"
    t0 = datetime(2026, 1, 5, 9, tzinfo=UTC)
    with inp.open("w", encoding="utf-8") as fh:
        for s in range(5):
            for i, text in enumerate(
                ["Always run the tests after each change.", "Keep the answer short, please."]
            ):
                fh.write(
                    json.dumps(
                        {
                            "source": "claude-code",
                            "session_id": f"s{s}",
                            "project": "demo",
                            "ts": (t0 + timedelta(days=s, minutes=i)).isoformat(),
                            "text": text,
                        }
                    )
                    + "\n"
                )
    monkeypatch.setenv("SBK_DATA_ROOT", str(root))
    return {"root": root, "input": inp, "out": tmp_path / "identity"}


def test_write_private_tightens_an_existing_file(tmp_path):
    common = _load("ai_common_private", HERE / "ai_common.py")
    p = tmp_path / "x.json"
    p.write_text("old", encoding="utf-8")
    p.chmod(0o644)
    common.write_private(p, "new")
    assert p.read_text(encoding="utf-8") == "new" and _mode(p) == 0o600
    q = tmp_path / "y.json"
    common.write_private(str(q), "fresh")
    assert _mode(q) == 0o600


def test_stats_and_payload_are_private(hyw, env):
    args = ["--input", str(env["input"]), "--out-dir", str(env["out"]), "--dry-run", "--show-payload"]
    assert hyw.run(args) == 0
    stats = env["root"] / "ai-history" / "how-you-work-stats.json"
    payload = env["root"] / "ai-history" / "how-you-work-payload.txt"
    assert stats.exists() and payload.exists()
    assert _mode(stats) == 0o600 and _mode(payload) == 0o600
    assert not env["out"].exists()


def test_identity_files_are_private(hyw, env):
    def fake(**kwargs):
        return "# Title\n\nbody\n"

    args = ["--input", str(env["input"]), "--out-dir", str(env["out"]), "--yes", "--only", "profile.md"]
    assert hyw.run(args, caller=fake) == 0
    assert _mode(env["out"] / "profile.md") == 0o600
