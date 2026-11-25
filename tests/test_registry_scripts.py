"""The source registry and the L0 plan only name scripts that exist, and the code has
no leftover of the removed paths (organisation-wide Google access, Slack admin APIs)."""

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod  # dataclasses need the module registered
    spec.loader.exec_module(mod)
    return mod


def _scripts_in(command: str) -> list[str]:
    return re.findall(r"tools/[\w./-]+\.py", command or "")


def test_registry_names_only_existing_scripts():
    import sorgenti

    missing = []
    for sid, s in sorgenti.SORGENTI.items():
        paths = [s.l1, *(p for _, p in s.stadi_l1), *_scripts_in(s.come_si_aggiorna)]
        missing += [
            f"{sid}: {p}" for p in paths if p and not (ROOT / p).is_file()
        ]
    for stage, sid in sorgenti.STADI_L1.items():
        if sid not in sorgenti.SORGENTI:
            missing.append(f"stage {stage}: unknown source {sid}")
    assert not missing, missing


def test_l0_plan_names_only_existing_scripts_and_covers_the_registry():
    refresh = _load("xs_l0_refresh_under_test", "tools/cross-source/xs-l0-refresh.py")
    missing = [p.args[0] for p in refresh.PIANO if not (ROOT / p.args[0]).is_file()]
    assert not missing, missing
    assert refresh.controlla_copertura() == []


def test_code_has_no_organisation_wide_access_left():
    marker = re.compile(
        # written with [.] and [_] so a plain text search for these words does not hit this test
        r"domain[-]wide|with[_]subject\(|from[_]service[_]account|admin[.]teams|enterprise[ ]grid", re.I
    )
    files = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout.splitlines()
    hits = []
    for f in files:
        if not f.endswith((".py", ".swift", ".json", ".yaml", ".yml", ".toml", ".example")):
            continue
        if f.startswith(("lib/", "tests/test_registry_scripts.py")) or "node_modules" in f:
            continue
        p = ROOT / f
        if not p.is_file():
            continue
        for i, line in enumerate(p.read_text(errors="replace").splitlines(), 1):
            if marker.search(line):
                hits.append(f"{f}:{i}")
    assert not hits, hits
