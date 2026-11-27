"""enabled_sources limits the download plan and the pipeline plan; the brain copy on a new install.

- xs-l0-refresh.py plans only the sources enabled_sources lists, when it is set (also with
  --only); an empty list keeps every source, as before.
- xs-pipeline-run.py reports the L1 phases and the inventory whose sources are not listed as
  "not in enabled_sources" (harmless, not a failed phase) and measures the download age of the
  listed sources only.
- backup_kb treats a missing or empty <data root>/knowledge as nothing to protect, writes its
  tars under the data root and never leaves a .parziale file; the brain-copy precondition does
  not block Knowledge Extract on a new install.

Each check runs in a subprocess with its own SBK_DATA_ROOT, HOME and config, so the
module-level constants of sbk_config never leak between tests. No network, nothing downloaded.
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


def _env(tmp: Path, config: dict | None) -> dict:
    cfg = tmp / "sbk.config.json"
    cfg.write_text(json.dumps(config or {}), encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith("SBK_")}
    (tmp / "home").mkdir(exist_ok=True)
    env.update(
        HOME=str(tmp / "home"),
        SBK_DATA_ROOT=str(tmp / "data"),
        SBK_CONFIG=str(cfg),
        PYTHONPATH=os.pathsep.join([str(ROOT / "tools"), str(ROOT / "tools" / "cross-source")]),
    )
    return env


def _py(code: str, tmp: Path, config: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)],
        cwd=str(ROOT),
        env=_env(tmp, config),
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


def _ok(r: subprocess.CompletedProcess) -> None:
    assert r.returncode == 0 and r.stdout.strip().endswith("ok"), (
        r.stdout[-2000:] + r.stderr[-2000:]
    )


# --------------------------------------------------------------------------- download plan


def test_empty_enabled_sources_keeps_every_download(tmp_path):
    _ok(
        _py(
            _REFRESH
            + """
piano, fuori = m.solo_abilitate(list(m.PIANO))
assert fuori == [] and len(piano) == len(m.PIANO)
print("ok")
""",
            tmp_path,
            {},
        )
    )


def test_set_enabled_sources_plans_only_those(tmp_path):
    _ok(
        _py(
            _REFRESH
            + """
piano, sess = m.solo_se_elencate(list(m.PIANO))
piano, fuori = m.solo_abilitate(piano)
names = {p.sorgente for p in piano}
assert names == {"slack", "hubspot", "imap-caldav"}, sorted(names)
assert "email" in fuori and "gdrive" in fuori and "zoom" in fuori
assert "slack" not in fuori and sess == ["plaud", "tactiq"]
print("ok")
""",
            tmp_path,
            {"enabled_sources": ["slack", "hubspot", "imap_caldav"]},
        )
    )


def _refresh_cli(tmp: Path, config: dict, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(ROOT / "tools/cross-source/xs-l0-refresh.py"), *args],
        cwd=str(ROOT),
        env=_env(tmp, config),
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_dry_run_names_the_sources_left_out(tmp_path):
    r = _refresh_cli(
        tmp_path, {"enabled_sources": ["slack"]}, "--dry-run", "--only", "slack,hubspot"
    )
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
    assert "sl-l0-download.py" in r.stdout
    assert "hs-l0-download.py" not in r.stdout
    assert "(not run) hubspot" in r.stdout and "not in enabled_sources" in r.stdout
    assert not (tmp_path / "data").exists() or not any((tmp_path / "data").rglob("*.tsv"))


# --------------------------------------------------------------------------- brain copy


def test_brain_copy_on_a_new_install_is_nothing_to_protect(tmp_path):
    r = _refresh_cli(tmp_path, {}, "--brain-copy", "--dir", str(tmp_path / "diary"))
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
    assert "nothing to protect" in r.stdout
    assert not list(tmp_path.rglob("*.tar.gz")) and not list(tmp_path.rglob("*.parziale"))
    assert not (tmp_path / "home" / ".sbk-backups").exists()
    assert "nothing to protect" in (tmp_path / "diary" / "esiti.tsv").read_text(encoding="utf-8")


def test_brain_copy_writes_under_the_data_root(tmp_path):
    kb = tmp_path / "data" / "knowledge" / "entities"
    kb.mkdir(parents=True)
    (kb / "p1.json").write_text("{}", encoding="utf-8")
    r = _refresh_cli(tmp_path, {}, "--brain-copy", "--dir", str(tmp_path / "diary"))
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
    tars = list((tmp_path / "data" / "backups-knowledge").glob("knowledge-*-pre-ingest.tar.gz"))
    assert len(tars) == 1
    assert not list(tmp_path.rglob("*.parziale"))
    assert not (tmp_path / "home" / ".sbk-backups").exists()


def test_failed_brain_copy_leaves_no_partial_file(tmp_path):
    kb = tmp_path / "data" / "knowledge"
    kb.mkdir(parents=True)
    (kb / "p1.json").write_text("{}", encoding="utf-8")
    _ok(
        _py(
            _REFRESH
            + f"""
import tarfile
from pathlib import Path
def broken(path, *a, **k):
    Path(path).write_bytes(b"half")   # the half-written copy a failed tar leaves
    raise tarfile.TarError("simulated")
m.tarfile.open = broken
d = Path({str(tmp_path / "diary")!r}); d.mkdir()
assert m.backup_kb(d) is False
assert m.COPIE_KB.is_dir() and not list(m.COPIE_KB.iterdir()), list(m.COPIE_KB.iterdir())
print("ok")
""",
            tmp_path,
        )
    )
    assert not list(tmp_path.rglob("*.parziale"))


def test_kb_repair_reads_the_data_root_copies(tmp_path):
    _ok(
        _py(
            _load("sb_kb_ripara_t", "tools/util/sb-kb-ripara.py")
            + f"""
from pathlib import Path
assert Path({str(tmp_path / "data" / "backups-knowledge")!r}) in m.CARTELLE_TAR
assert not any(".sbk-backups" in str(c) for c in m.CARTELLE_TAR)
print("ok")
""",
            tmp_path,
        )
    )


def test_brain_copy_precondition_passes_without_a_store(tmp_path):
    _ok(
        _py(
            _RUNNER
            + """
blocchi, avvisi = m.precondizioni("ricostruisci")
assert "tar_dello_store" not in blocchi, blocchi
print("ok")
""",
            tmp_path,
        )
    )


def test_brain_copy_precondition_still_guards_an_existing_store(tmp_path):
    kb = tmp_path / "data" / "knowledge"
    kb.mkdir(parents=True)
    (kb / "p1.json").write_text("{}", encoding="utf-8")
    _ok(
        _py(
            _RUNNER
            + """
blocchi, avvisi = m.precondizioni("ricostruisci")
assert "tar_dello_store" in blocchi, blocchi
assert "--brain-copy" in blocchi["tar_dello_store"]
print("ok")
""",
            tmp_path,
        )
    )


# --------------------------------------------------------------------------- pipeline plan


@pytest.mark.parametrize(
    ("config", "expected"),
    [
        ({}, []),
        (
            {"enabled_sources": ["slack"]},
            ["l1_personio", "l1_personio_assenze", "l1_speaker_analysis", "l1_phase2"],
        ),
        ({"enabled_sources": ["plaud"]}, ["l1_personio", "l1_personio_assenze", "l1_phase1"]),
    ],
)
def test_l1_phases_left_out_by_enabled_sources(tmp_path, config, expected):
    _ok(
        _py(
            _RUNNER
            + f"""
import logging
logging.disable(logging.CRITICAL)
r = m.run_l1_pipeline(dry_run=True)
assert sorted(r["fasi_fuori_elenco"]) == sorted({expected!r}), r["fasi_fuori_elenco"]
print("ok")
""",
            tmp_path,
            config,
        )
    )


def test_not_listed_is_a_harmless_skip(tmp_path):
    _ok(
        _py(
            _RUNNER
            + """
s = m.Salto("l1_personio", "non_elencata", "x")
assert s.innocuo
assert m.MOTIVI_EN["non_elencata"] == "not in enabled_sources"
print("ok")
""",
            tmp_path,
        )
    )


@pytest.mark.parametrize(
    ("config", "listed"),
    [({}, None), ({"enabled_sources": ["slack", "hubspot"]}, ["hubspot", "slack"])],
)
def test_download_age_only_for_listed_sources(tmp_path, config, listed):
    _ok(
        _py(
            _RUNNER
            + f"""
ages = m.eta_l0()
if {listed!r} is None:
    assert "email" in ages and "zoom" in ages and "slack" in ages
else:
    assert sorted(ages) == {listed!r}, sorted(ages)
print("ok")
""",
            tmp_path,
            config,
        )
    )


def test_resume_counts_a_not_listed_stage_as_closed():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "sb_ripresa_t", ROOT / "tools/secondbrain/sb_ripresa.py"
    )
    sb_ripresa = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = sb_ripresa  # dataclasses look the module up while it loads
    try:
        spec.loader.exec_module(sb_ripresa)
    finally:
        sys.modules.pop(spec.name, None)

    assert "not in enabled_sources" in sb_ripresa._SALTI_CHIUSI
    riga = (
        "12:00:00 INFO   – L1 Inventory (domains, repos) — SKIPPED (not in enabled_sources): "
        "none of github, gsc, analytics is in enabled_sources (sbk.config.json)"
    )
    m = sb_ripresa._RE_SALTATO.search(riga)
    assert m and m["motivo"] in sb_ripresa._SALTI_CHIUSI


def test_config_example_help_matches_the_plan():
    cfg = json.loads((ROOT / "sbk.config.example.json").read_text(encoding="utf-8"))
    text = cfg["_help_enabled_sources"]
    assert "every source that has data" not in text
    assert "xs-l0-refresh.py" in text and "plans only these" in text
