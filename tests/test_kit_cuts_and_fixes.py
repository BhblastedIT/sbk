"""What left the kit stays out, and the small fixes hold on an empty data root.

- The dashboard has no fundraising page, investor momentum or investor funnel, and no FUNDRAISING_DIR.
- The knowledge-extract stage no longer runs a metrics tool that wrote into the repo.
- Inspiration is off until inspiration.archive_dir is set; its folder follows SBK_DATA_ROOT.
- sbk-monitor loads signal-detector.py by path; internal callers pass --propagate.
- Freshness and the email L1 steps run on an empty data root without a traceback.
- xs-l1-match-vcf takes your CSV with --csv (required) and writes its report under the data root.

Checks that import a module run in a child process with a temporary HOME, data root and config,
because the modules read their paths and sbk.config.json when they are imported.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "tools" / "secondbrain"


@pytest.fixture
def clean(tmp_path):
    home = tmp_path / "home"
    data = tmp_path / "data"
    home.mkdir()
    data.mkdir()
    cfg = tmp_path / "sbk.config.json"
    cfg.write_text("{}", encoding="utf-8")
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(home),
        "TMPDIR": str(tmp_path),
        "SBK_DATA_ROOT": str(data),
        "SBK_CONFIG": str(cfg),
        "SB_FINTO_LEASE": "1",
        "PYTHON_KEYRING_BACKEND": "keyring.backends.fail.Keyring",
    }
    return tmp_path, cfg, env


def _run(env: dict, code: str, timeout: int = 120) -> dict:
    """Run `code` with tools/ and tools/secondbrain importable; it must print one JSON line last."""
    prelude = f"import sys, json\nsys.path[:0] = [{str(APP)!r}, {str(ROOT / 'tools')!r}]\n"
    r = subprocess.run(
        [sys.executable, "-c", prelude + textwrap.dedent(code)],
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(env["TMPDIR"]),
    )
    assert r.returncode == 0, r.stderr[-2000:]
    return json.loads(r.stdout.strip().splitlines()[-1])


def _text(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


# --- moved out --------------------------------------------------------------------------


def test_fundraising_page_is_gone():
    for rel in (
        "dashboard/app/api/fundraising.py",
        "dashboard/app/templates/fundraising.html",
        "dashboard/app/templates/partials/fundraising_pipeline.html",
    ):
        assert not (ROOT / rel).exists(), rel
    for rel in (
        "dashboard/app/main.py",
        "dashboard/app/core/sbk_bridge.py",
        "dashboard/app/api/flow.py",
        "dashboard/app/templates/flow.html",
        "dashboard/app/templates/partials/person_card.html",
        "tools/sbk_config.py",
        "tools/cross-source/xs-l3-index.py",
    ):
        text = _text(rel)
        for gone in (
            "fundraising_router",
            "get_fundraising_pipeline",
            "get_investor_momentum",
            "get_investor_sankey",
            "FUNDRAISING_DIR",
            "Investor Funnel",
            "Investor Momentum",
        ):
            assert gone not in text, f"{gone} in {rel}"


def test_author_metrics_tools_are_gone():
    for rel in (
        "tools/util/sb-ratchet.py",
        "tools/util/sb-sei-numeri.py",
        "tools/email/EM-PIPELINE.md",
    ):
        assert not (ROOT / rel).exists(), rel
    for rel in (
        "tools/cross-source/xs-l2-knowledge-extract.py",
        "tools/util/sb-kb-ripara.py",
        ".gitignore",
    ):
        text = _text(rel)
        assert "sb-ratchet" not in text and "sb-sei-numeri" not in text, rel


# --- Inspiration off unless configured ----------------------------------------------------


def test_inspiration_is_off_without_archive_dir(clean):
    tmp, _cfg, env = clean
    out = _run(
        env,
        """
        import sb_inspiration_root as R, sb_inspiration as S, sb_inspiration_azioni as A
        print(json.dumps({"on": R.is_on(), "root": str(R.root()), "stato": S.per_app(),
                          "esegui": A.esegui(["importa"])}))
        """,
    )
    assert out["on"] is False
    assert out["root"] == str(tmp / "data" / "inspiration")
    for k in ("stato", "esegui"):
        assert out[k]["ok"] is False and out[k]["spenta"] is True
        assert "inspiration.archive_dir" in out[k]["messaggio"]
    assert not (tmp / "data" / "inspiration").exists()


def test_inspiration_archive_dir_relative_to_data_root(clean):
    tmp, cfg, env = clean
    cfg.write_text(json.dumps({"inspiration": {"archive_dir": "my-ideas"}}), encoding="utf-8")
    out = _run(
        env,
        """
        import sb_inspiration_root as R, sb_inspiration_azioni as A
        print(json.dumps({"on": R.is_on(), "root": str(R.root()), "radice": str(A.RADICE)}))
        """,
    )
    assert out["on"] is True
    assert out["root"] == out["radice"] == str(tmp / "data" / "my-ideas")


def test_inspiration_missing_archive_script_says_so(clean):
    tmp, cfg, env = clean
    (tmp / "ideas" / "archivio").mkdir(parents=True)
    cfg.write_text(
        json.dumps({"inspiration": {"archive_dir": str(tmp / "ideas")}}), encoding="utf-8"
    )
    out = _run(env, 'import sb_inspiration_azioni as A\nprint(json.dumps(A.esegui(["rileggi"])))')
    assert out["ok"] is False
    assert "leggi-dm.py" in out["messaggio"] and "SBK does not ship" in out["messaggio"]


# --- monitor, callers, empty data root ----------------------------------------------------


def test_monitor_loads_signal_detector_by_path():
    text = _text("tools/monitoring/sbk-monitor.py")
    assert "monitoring.signal_detector" not in text
    assert '"signal-detector.py"' in text
    assert (ROOT / "tools/monitoring/signal-detector.py").is_file()


def test_internal_callers_pass_propagate():
    for rel in (
        "tools/monitoring/sbk-monitor.py",
        "dashboard/app/core/cascade_monitor.py",
        "dashboard/app/api/pipeline.py",
        "tools/secondbrain/sb-app.py",
    ):
        # A command list or append that passes the Italian alias (sb-app's flag table may map it).
        assert not re.search(r'(append\(|\[|, )"--propaga"[\])]', _text(rel)), rel


def test_signal_detector_scan_on_empty_root(clean):
    _tmp, _cfg, env = clean
    out = _run(
        env,
        f"""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "signal_detector", {str(ROOT / "tools/monitoring/signal-detector.py")!r})
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        print(json.dumps({{"has_scan": callable(getattr(mod, "run_signal_scan", None))}}))
        """,
    )
    assert out["has_scan"] is True


def test_freshness_on_empty_data_root(clean):
    _tmp, _cfg, env = clean
    r = subprocess.run(
        [sys.executable, str(ROOT / "tools/cross-source/xs-util-freshness.py")],
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
        cwd=str(env["TMPDIR"]),
    )
    assert "Traceback" not in r.stderr, r.stderr[-2000:]
    assert r.returncode == 0, r.stderr[-2000:]


@pytest.mark.parametrize(
    ("script", "args"),
    [
        ("tools/email/em-l1-enrich.py", ["--incremental"]),
        ("tools/email/em-l1-allegati.py", ["--incremental"]),
        ("tools/cross-source/xs-l2-calendar-episodes.py", []),
        ("tools/cross-source/xs-l2-email-participants.py", []),
        ("tools/cross-source/xs-l2-attachment-discovery.py", []),
        ("tools/cross-source/rq-05-backfill-events.py", []),
        ("tools/cross-source/rq-backfill-content-quality.py", []),
        ("tools/cross-source/xs-l3-graph.py", []),
        ("tools/cross-source/xs-l3-decay.py", []),
    ],
)
def test_stage_on_empty_data_root(clean, script, args):
    """No traceback on an empty data root: a clear message (and exit 0 or 1) instead."""
    _tmp, _cfg, env = clean
    r = subprocess.run(
        [sys.executable, str(ROOT / script), *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
        cwd=str(env["TMPDIR"]),
    )
    assert "Traceback" not in r.stderr + r.stdout, (r.stderr + r.stdout)[-2000:]


def test_match_vcf_needs_csv_and_writes_to_data_root(clean):
    _tmp, _cfg, env = clean
    script = str(ROOT / "tools/cross-source/xs-l1-match-vcf.py")
    h = subprocess.run([sys.executable, script, "--help"], env=env, capture_output=True, text=True)
    assert h.returncode == 0 and "--csv" in h.stdout
    r = subprocess.run([sys.executable, script], env=env, capture_output=True, text=True)
    assert r.returncode == 2 and "--csv" in r.stderr
    text = _text("tools/cross-source/xs-l1-match-vcf.py")
    assert "contatti-vari-import.csv" not in text
    assert 'OUTPUT_PATH = DATA_ROOT / "contacts"' in text


# --- neutral texts --------------------------------------------------------------------------


def test_dashboard_chat_examples_are_neutral():
    assert "sam-taylor" not in _text("dashboard/app/core/chat_tools.py")
    assert "Who is Sam" not in _text("dashboard/app/templates/chat.html")


def test_version_file_is_english():
    text = _text("VERSION")
    assert "author:" in text and "autore" not in text and "versione" not in text
