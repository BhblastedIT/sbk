"""Sources that run only when enabled_sources names them.

The downloads that read a login session of an app or a browser on this Mac (Plaud desktop
app, Tactiq in Chrome) are planned by xs-l0-refresh.py only when their source is listed in
sbk.config.json enabled_sources; an empty list does not switch them on. The same holds for
the closed chatgpt L1 in xs-pipeline-run.py.

Each check runs in a subprocess with its own empty SBK_DATA_ROOT and config, so the
module-level constants of sbk_config never leak between tests. No network, nothing run.
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


def _py(code: str, tmp: Path, config: dict | None = None) -> subprocess.CompletedProcess:
    cfg = tmp / "sbk.config.json"
    cfg.write_text(json.dumps(config or {}), encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith("SBK_")}
    env.update(
        SBK_DATA_ROOT=str(tmp / "data"),
        SBK_CONFIG=str(cfg),
        PYTHONPATH=os.pathsep.join([str(ROOT / "tools"), str(ROOT / "tools" / "cross-source")]),
    )
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def _load(name: str, rel: str) -> str:
    return f"""
import importlib.util, sys
spec = importlib.util.spec_from_file_location({name!r}, {str(ROOT / rel)!r})
m = importlib.util.module_from_spec(spec)
sys.modules[{name!r}] = m
spec.loader.exec_module(m)
"""


_REFRESH = _load("xs_l0_refresh_t", "tools/cross-source/xs-l0-refresh.py")
_RUNNER = _load("xs_pipeline_run_t", "tools/cross-source/xs-pipeline-run.py")


@pytest.mark.parametrize(
    ("config", "expected_out"),
    [
        ({}, ["plaud", "tactiq"]),
        ({"enabled_sources": ["email", "slack"]}, ["plaud", "tactiq"]),
        ({"enabled_sources": ["plaud"]}, ["tactiq"]),
        ({"enabled_sources": ["plaud", "tactiq"]}, []),
    ],
)
def test_session_downloads_need_enabled_sources(tmp_path, config, expected_out):
    r = _py(
        _REFRESH
        + f"""
piano, fuori = m.solo_se_elencate(list(m.PIANO))
names = {{p.sorgente for p in piano}}
assert fuori == {expected_out!r}, fuori
for sid in ("plaud", "tactiq"):
    assert (sid in names) == (sid not in fuori), (sid, sorted(names))
assert "email" in names and "gdrive" in names
print("ok")
""",
        tmp_path,
        config,
    )
    assert r.returncode == 0 and r.stdout.strip() == "ok", r.stderr[-2000:]


def test_refresh_dry_run_says_what_the_session_downloads_read(tmp_path):
    cfg = tmp_path / "sbk.config.json"
    cfg.write_text("{}", encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith("SBK_")}
    env.update(SBK_DATA_ROOT=str(tmp_path / "data"), SBK_CONFIG=str(cfg))
    r = subprocess.run(
        [sys.executable, str(ROOT / "tools/cross-source/xs-l0-refresh.py"), "--dry-run"],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
    assert "pl-l0-download.py" not in r.stdout and "tq-l0-download.py" not in r.stdout
    assert "(not run) plaud" in r.stdout and "Plaud desktop app" in r.stdout
    assert "(not run) tactiq" in r.stdout and "Chrome" in r.stdout


@pytest.mark.parametrize(
    ("config", "kept"),
    [({}, False), ({"enabled_sources": ["email"]}, False), ({"enabled_sources": ["chatgpt"]}, True)],
)
def test_chatgpt_l1_runs_only_when_listed(tmp_path, config, kept):
    r = _py(
        _RUNNER
        + f"""
saltate = set()
out = m._solo_abilitate(dict(m.L1_SCRIPTS_BASE), saltate)
assert ("chatgpt" in out) is {kept!r}, sorted(out)
assert ("chatgpt" in saltate) is {not kept!r}, saltate
if not {bool(config)!r}:
    assert "email" in out and "slack" in out   # an empty list still keeps the others
print("ok")
""",
        tmp_path,
        config,
    )
    assert r.returncode == 0 and r.stdout.strip() == "ok", r.stderr[-2000:]
