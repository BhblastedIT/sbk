"""The kit ships no author tools and no author defaults (round 8, D28).

- The author's own tools are not in the repo and nothing points to them: a model benchmark with no
  consent, a release orchestrator, a static-file migration, a brand-name domain checker, a session
  re-reader, swap and disk accounting, a Drive archive, a Downloads harvest, an investor-list import.
- The backup covers ~/Downloads only when you ask for it in sbk.config.json, and has no row for a
  folder nothing in the kit writes.
- sb-who --selftest names nobody from your knowledge base.
- The shipped skills never commit or push on their own.
- The four unused dependencies are gone from pyproject.toml and uv.lock.
- The run diary and the step logs use English markers, and the readers still read older diaries.
- The Plaud speaker page shows English labels for the codes in quadro.json.
- The Microsoft 365 sign-in asks again only for the per-user scopes the kit's own plugins add.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in ("tools", "tools/cross-source", "tools/secondbrain", "tools/microsoft365", "tools/teams"):
    if str(ROOT / _p) not in sys.path:
        sys.path.insert(0, str(ROOT / _p))


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _repo_text_files():
    skip = {".git", ".venv", "lib", "__pycache__", ".build", "node_modules"}
    for p in ROOT.rglob("*"):
        if any(part in skip for part in p.relative_to(ROOT).parts):
            continue
        if p.is_file() and p.suffix in {
            ".py",
            ".md",
            ".json",
            ".toml",
            ".yaml",
            ".yml",
            ".sh",
            ".swift",
            ".html",
        }:
            yield p


# --- the author tools are out --------------------------------------------------------------------

MOVED = [
    "tools/diag/llm-speed-bench.py",
    "tools/diag/net-check.sh",
    "tools/infrastructure/pd-v1-post-launch.py",
    "tools/infrastructure/lkl-migrate-static.py",
    "tools/infrastructure/dl-l0-harvest.py",
    "tools/util/xs-domain-checker.py",
    "tools/util/sb_riavvio_lavori.py",
    "tools/util/sb-disco.py",
    "tools/util/sb-archivio-drive.py",
]


def test_author_tools_are_not_shipped_and_nothing_points_to_them():
    assert [m for m in MOVED if (ROOT / m).exists()] == []
    names = [Path(m).stem for m in MOVED]
    here = Path(__file__).resolve()
    hits = []
    for p in _repo_text_files():
        if p.resolve() == here:
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        hits += [f"{p.relative_to(ROOT)}: {n}" for n in names if n in text]
    assert hits == []


def test_no_pointer_to_the_drive_archive_or_the_downloads_harvest():
    for rel in (
        "tools/gdrive/gd-l0-download.py",
        "tools/infrastructure/sb-backup.py",
        "tools/infrastructure/sb_livelli.py",
    ):
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert "archivio-drive" not in text, rel
        assert "su_drive" not in text, rel
    assert "downloads-harvest" not in (ROOT / "tools/contracts/artifacts.yaml").read_text(
        encoding="utf-8"
    )


def test_no_investor_list_import_in_linkedin_or_in_the_status_table():
    li = (ROOT / "tools/linkedin/li-l1-enrich.py").read_text(encoding="utf-8")
    assert "investor" not in li.lower()
    status = (ROOT / "tools/cross-source/xs-util-pipeline-status.py").read_text(encoding="utf-8")
    assert "Investors enrich" not in status and "LI_INV_RAW" not in status


# --- backup: no author rows, Downloads only on request -----------------------------------------------


def _fuori(tmp_path: Path, config: dict) -> dict:
    cfg = tmp_path / "sbk.config.json"
    cfg.write_text(json.dumps(config), encoding="utf-8")
    code = (
        "import json, sys; sys.path.insert(0, 'tools/infrastructure'); import sb_livelli as lv; "
        "print(json.dumps({f.nome: [str(f.base), f.livello, f.delicato, f.solo_usb] for f in lv.FUORI}))"
    )
    env = {
        **os.environ,
        "SBK_CONFIG": str(cfg),
        "SBK_DATA_ROOT": str(tmp_path / "data"),
        "HOME": str(tmp_path / "home"),
    }
    r = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120
    )
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_backup_has_no_sbk_safety_row_and_leaves_downloads_out_by_default(tmp_path):
    rows = _fuori(tmp_path, {})
    assert "tracciabilita" not in rows
    assert "downloads" not in rows
    assert not any("sbk-safety" in base for base, *_ in rows.values())
    assert "downloads" not in _fuori(tmp_path, {"backup": {"include_downloads": False}})


def test_backup_includes_downloads_only_when_you_ask(tmp_path):
    rows = _fuori(tmp_path, {"backup": {"include_downloads": True}})
    base, livello, delicato, solo_usb = rows["downloads"]
    assert base == str(tmp_path / "home" / "Downloads")
    assert livello == 3 and delicato and solo_usb


def test_config_example_and_skill_describe_the_downloads_switch():
    cfg = json.loads((ROOT / "sbk.config.example.json").read_text(encoding="utf-8"))
    assert cfg["backup"]["include_downloads"] is False
    assert cfg["backup"]["_help_include_downloads"]
    skill = (ROOT / ".claude/skills/backup/SKILL.md").read_text(encoding="utf-8")
    assert "include_downloads" in skill and "off by default" in skill
    assert "backups-knowledge" in skill
    assert "tar-kb" not in skill and "sbk-safety" not in skill


# --- sb-who self-test: nobody from your knowledge base -----------------------------------------------


def test_sb_who_selftest_names_nobody_and_passes_on_a_fresh_knowledge_base(tmp_path):
    data = tmp_path / "data"
    (data / "knowledge" / "entities" / "person").mkdir(parents=True)
    cfg = tmp_path / "sbk.config.json"
    cfg.write_text(json.dumps({"owner": "Alex Demo"}), encoding="utf-8")
    env = {**os.environ, "SBK_CONFIG": str(cfg), "SBK_DATA_ROOT": str(data), "HOME": str(tmp_path)}
    code = (
        "import importlib.util, json, sys; sys.path.insert(0, 'tools'); "
        "s = importlib.util.spec_from_file_location('sb_who_t', 'tools/util/sb-who.py'); "
        "m = importlib.util.module_from_spec(s); s.loader.exec_module(m); "
        "print(json.dumps([n for n, _ in m.GOLDEN]))"
    )
    r = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120
    )
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout.strip().splitlines()[-1]) == ["Alex Demo", "Zxqwerty Nonesiste"]
    r = subprocess.run(
        [sys.executable, "tools/util/sb-who.py", "--selftest"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert "xs-l2-knowledge-extract.py:" not in r.stdout


# --- skills ------------------------------------------------------------------------------------------


def test_phase_skill_never_commits_or_pushes_on_its_own():
    text = (ROOT / ".claude/skills/phase/SKILL.md").read_text(encoding="utf-8")
    assert "Push and report" not in text
    assert "never push on your own" in text
    assert "never commit on your own" in text


def test_infra_memoria_heading_matches_its_text():
    text = (ROOT / ".claude/skills/infra-memoria/SKILL.md").read_text(encoding="utf-8")
    assert "manual by design" not in text
    assert "## What starts on its own and how to switch it off" in text
    assert "cascades are on unless it" in text


# --- dependencies ------------------------------------------------------------------------------------

UNUSED = ("segno", "vtracer", "ezdxf", "simpy")


def test_unused_dependencies_are_gone_from_pyproject_and_the_lock():
    deps = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"][
        "dependencies"
    ]
    names = {
        d.split(">")[0].split("=")[0].split("[")[0].split("<")[0].strip().lower() for d in deps
    }
    assert names.isdisjoint(UNUSED)
    lock = (ROOT / "uv.lock").read_text(encoding="utf-8")
    assert [u for u in UNUSED if f'\nname = "{u}"\n' in lock] == []


# --- run diary markers -------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def moduli():
    vecchio = {k: os.environ.get(k) for k in ("SBK_DATA_ROOT", "SBK_CONFIG")}
    tmp = tempfile.mkdtemp(prefix="sbk-d28-")
    os.environ["SBK_DATA_ROOT"] = str(Path(tmp) / "data")
    os.environ["SBK_CONFIG"] = str(Path(tmp) / "sbk.config.json")
    try:
        app = _load("sb_app_d28", ROOT / "tools" / "secondbrain" / "sb-app.py")
        yield {"app": app, "l0r": app.L0R, "ripresa": app.RIPRESA, "err": app.ERR, "tmp": Path(tmp)}
    finally:
        for k, v in vecchio.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_refresh_writes_english_attempt_markers(moduli, tmp_path):
    l0r = moduli["l0r"]
    (tmp_path / "log").mkdir()
    assert l0r.esegui("demo", [sys.executable, "-c", "pass"], 60, tmp_path)
    log = (tmp_path / "log" / "demo.log").read_text(encoding="utf-8")
    assert log.startswith("── attempt 1 · ")
    righe = [
        r.split("\t") for r in (tmp_path / "esiti.tsv").read_text(encoding="utf-8").splitlines()
    ]
    assert righe[-1][1:4] == ["demo", "attempt.1", "rc=0"]
    src = (ROOT / "tools/cross-source/xs-l0-refresh.py").read_text(encoding="utf-8")
    for old in (
        '_esito(esiti, "INIZIO"',
        '_esito(esiti, "FINE"',
        'else "solo L0"',
        '"poi-ingest" if',
        "── tentativo {",
        'f"tent.{',
    ):
        assert old not in src, old
    assert (l0r.DIARIO_INIZIO, l0r.DIARIO_FINE, l0r.DIARIO_SOLO_L0) == ("START", "END", "L0 only")
    assert l0r.DIARIO_POI_INGEST == "then-ingest"


def _diario(cartella: Path, lingua: str, passo: str) -> Path:
    cartella.mkdir(parents=True, exist_ok=True)
    (cartella / "log").mkdir(exist_ok=True)
    if lingua == "en":
        righe = [
            ["01/02 10:00:00", "START", "1 steps", "L0 only"],
            ["01/02 10:00:05", passo, "attempt.1", "rc=0", "5s", ""],
            ["01/02 10:00:06", "END", "not closed: none"],
        ]
    else:
        righe = [
            ["01/02 10:00:00", "INIZIO", "1 steps", "solo L0"],
            ["01/02 10:00:05", passo, "tent.1", "rc=0", "5s", ""],
            ["01/02 10:00:06", "FINE", "not closed: none"],
        ]
    d = cartella / "esiti.tsv"
    d.write_text("\n".join("\t".join(r) for r in righe) + "\n", encoding="utf-8")
    return d


@pytest.mark.parametrize("lingua", ["en", "it"])
def test_diary_readers_read_english_and_older_italian_diaries(
    moduli, tmp_path, lingua, monkeypatch
):
    app, l0r, ripresa, err = moduli["app"], moduli["l0r"], moduli["ripresa"], moduli["err"]
    p = l0r.PIANO[0]
    cartella = tmp_path / "runs" / f"2026-02-01-{lingua}"
    diario = _diario(cartella, lingua, p.nome)

    g = ripresa.leggi_giro(cartella, [p.nome])
    assert g.trovato and g.modo is None and p.nome in g.chiusi and g.fine is not None

    assert err._ultimo_esito(diario, p.nome)[0] == 0

    assert app._fine_giro(cartella) == "none"
    monkeypatch.setattr(app, "FULLRUN", tmp_path / "runs")
    u = app._ultimo_giro_l0()
    assert u["poi_ingest"] is False and u["fine"] and u["non_chiusi"] == "none"

    giro = app._leggi_giro(cartella, p.sorgente, False)
    passo = next(x for x in giro["passi"] if x["id"] == p.nome)
    assert passo["stato"] == "fatto" and passo["tentativi"] == 1
    assert giro["fine"] == "not closed: none"


def test_full_run_and_lanes_write_the_same_english_markers():
    full = (ROOT / "tools/secondbrain/sb-full.py").read_text(encoding="utf-8")
    corsie = (ROOT / "tools/secondbrain/sb_corsie.py").read_text(encoding="utf-8")
    for text in (full, corsie):
        assert '"INIZIO"' not in text and '"FINE"' not in text
        assert "── tentativo" not in text and '"tent.' not in text and 'f"tent.' not in text
    assert "L0R.DIARIO_INIZIO" in full and "L0R.DIARIO_POI_TUTTO" in full


# --- Plaud speaker page ------------------------------------------------------------------------------


def test_plaud_page_shows_english_labels_for_the_quadro_codes(tmp_path, monkeypatch):
    page = _load("pl_quadro_pagina_d28", ROOT / "tools" / "plaud" / "pl_quadro_pagina.py")
    monkeypatch.setattr(page, "QUADRO", tmp_path)
    (tmp_path / "lotto-verifiche.json").write_text(
        json.dumps(
            {"voci": [{"n": 1, "blocco": "altre persone", "prove": ["testo", "is called by name"]}]}
        ),
        encoding="utf-8",
    )
    q = {
        "solidita": {
            "livelli": {
                "confermato": {"voci": 1, "minuti": 2},
                "senza nome": {"voci": 3, "minuti": 4},
            }
        },
        "per_mese": [],
    }
    d = page.compatta(q)
    assert d["lotto"]["voci"][0]["prove"] == ["text", "is called by name"]
    for code in (
        "confermato",
        "solido",
        "una prova",
        "solo nome",
        "sospetto",
        "smentito",
        "senza nome",
        "il testo la chiama con un altro nome",
        "stesso nome su più speaker",
        "il proprietario su più speaker",
        "nome di più persone nel KB",
        "solo il nome di battesimo",
        "agenti con citazione",
        "voce (Plaud, proprietario)",
        "registratore",
        "audio importato",
        "90% e oltre",
        "sotto il 50%",
        "aspetta te",
    ):
        label = d["etichette"][code]
        assert label and label != code and label.isascii(), code
    js = page.PAGINA
    assert "const EN=k=>(D.etichette||{})[k]??k;" in js
    for raw in ("></i>${k}: ", "'#333'}\">${k}</span>", "`${k} ${n(v)}`", "with confidence ${k}`"):
        assert raw not in js, raw


# --- registry and Microsoft 365 scopes ---------------------------------------------------------------


def test_personio_registry_note_says_it_needs_admin_rights():
    import sorgenti

    note = sorgenti.SORGENTI["personio"].note
    assert "organisation HR source" in note and "admin rights" in note


def test_microsoft365_sign_in_keeps_only_the_kits_own_per_user_scopes():
    auth = _load("ms_l0_auth_d28", ROOT / "tools" / "microsoft365" / "ms-l0-auth.py")
    import ms_graph as mg
    import tm_graph

    rec = {
        "requested_scopes": " ".join(
            [*mg.SCOPES, "Chat.Read", "Directory.ReadWrite.All", "User.ReadWrite.All", "Mail.Send"]
        )
    }
    assert auth.kept_scopes(rec, "organizations") == ("Chat.Read",)
    assert set(auth.dropped_scopes(rec, "organizations")) == {
        "Directory.ReadWrite.All",
        "User.ReadWrite.All",
        "Mail.Send",
    }
    assert auth.kept_scopes(rec, "consumers") == () and auth.dropped_scopes(rec, "consumers") == ()
    own = {s.lower() for s in mg.SCOPES}
    teams_extra = {s.lower() for s in tm_graph.TEAMS_SCOPES} - own
    assert teams_extra <= auth.KEPT_SCOPES_ALLOWED
