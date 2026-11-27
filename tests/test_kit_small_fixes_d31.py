"""The small items left after the first-run work (round 9, D31), one regression check per command touched.

- sbk.config.example.json: the enabled_sources help says what --ingest really does with an empty list.
- gen-dossier-pdf.py writes under <data root>/dossiers/, never in the current folder; *.pdf is git-ignored.
- the author's unreferenced audits left the kit; drift_report.py carries its own rules.
- sb-cerca.py masks the known key formats by itself, in English, with --self-test (--prova kept).
- xs-l3-schema-migrate.py looks for the archives sb-backup really writes (or --backup-dir).
- LinkedIn 'Connected On' ('14 Feb 2025') becomes an ISO date in the knowledge base.
- li-l0-import-export.py --dry-run writes nothing.
- the app's verdict tells a failed stage, and "Nothing is connected yet" only when no source has data.
- the run diary and the runner log write English status words; the readers accept the older Italian ones.
- a setup failure (exit 78, e.g. no embedding model offline) is not retried and not called a line stop.
- pl_voice_seed_wa.py never walks ~/Downloads unless --folder names it.
- the LinkedIn browser scripts read your own member id from config, env or LinkedIn: no placeholder.

Every check runs in a subprocess with its own SBK_DATA_ROOT, HOME and config. Demo data only, no network.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CS = ROOT / "tools" / "cross-source"
_OWNER = {"owner": "Alex Demo", "own_names": ["Alex Demo"], "own_emails": ["alex@example.com"]}


def _env(tmp: Path, config: dict | None, extra: dict | None = None) -> dict:
    cfg = tmp / "sbk.config.json"
    cfg.write_text(json.dumps(config or {}), encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("SBK_", "ANTHROPIC_"))}
    (tmp / "home").mkdir(exist_ok=True)
    env.update(
        HOME=str(tmp / "home"),
        SBK_DATA_ROOT=str(tmp / "data"),
        SBK_CONFIG=str(cfg),
        PYTHON_KEYRING_BACKEND="keyring.backends.fail.Keyring",
        PYTHONPATH=os.pathsep.join(
            [str(ROOT / "tools"), str(CS), str(ROOT / "tools" / "secondbrain")]
        ),
    )
    env.update(extra or {})
    return env


def _run(args, tmp: Path, config=None, extra=None, cwd=None, timeout: int = 180):
    return subprocess.run(
        [sys.executable, *args],
        cwd=str(cwd or ROOT),
        env=_env(tmp, config, extra),
        capture_output=True,
        text=True,
        timeout=timeout,
        stdin=subprocess.DEVNULL,
    )


def _py(code: str, tmp: Path, config=None, extra=None):
    return _run(["-c", textwrap.dedent(code)], tmp, config, extra)


def _load(name: str, rel: str, var: str = "m") -> str:
    return f"""
import importlib.util, sys
spec = importlib.util.spec_from_file_location({name!r}, {str(ROOT / rel)!r})
{var} = importlib.util.module_from_spec(spec)
sys.modules[{name!r}] = {var}
spec.loader.exec_module({var})
"""


def _out(r) -> str:
    return (r.stdout or "") + (r.stderr or "")


def _ok(r) -> None:
    assert r.returncode == 0 and "ok" in r.stdout, _out(r)[-4000:]


def _files(root: Path) -> set[str]:
    return (
        {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}
        if root.exists()
        else set()
    )


# --- sbk.config.example.json ---------------------------------------------------------------------


def test_enabled_sources_help_matches_what_ingest_does():
    cfg = json.loads((ROOT / "sbk.config.example.json").read_text(encoding="utf-8"))
    aiuto = cfg["_help_enabled_sources"]
    assert "stops with an error" not in aiuto
    assert "not downloaded yet" in aiuto and "no retry" in aiuto
    assert "own_urn" in cfg["linkedin"] and cfg["linkedin"]["own_urn"] == ""


# --- gen-dossier-pdf.py --------------------------------------------------------------------------

_REPORTLAB_STUB = """
class _Qualsiasi:
    def __init__(self, *a, **k):
        self.a, self.k = a, k
    def __getattr__(self, nome):
        return _Qualsiasi()
    def __call__(self, *a, **k):
        return _Qualsiasi()
"""


def _stub_reportlab(base: Path) -> Path:
    """A stand-in reportlab (the real one is optional): build() writes the file it was given."""
    pkg = base / "stub" / "reportlab"
    for sub in ("lib", "platypus"):
        (pkg / sub).mkdir(parents=True, exist_ok=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "lib" / "__init__.py").write_text("", encoding="utf-8")
    for mod, names in (
        ("colors", "HexColor"),
        ("enums", "TA_CENTER TA_JUSTIFY TA_LEFT"),
        ("styles", "ParagraphStyle"),
    ):
        righe = [_REPORTLAB_STUB] + [f"{n} = _Qualsiasi" for n in names.split()]
        (pkg / "lib" / f"{mod}.py").write_text("\n".join(righe), encoding="utf-8")
    (pkg / "lib" / "pagesizes.py").write_text("A4 = (595.0, 842.0)\n", encoding="utf-8")
    (pkg / "platypus" / "__init__.py").write_text(
        _REPORTLAB_STUB
        + "HRFlowable = Paragraph = Spacer = Table = TableStyle = _Qualsiasi\n"
        + "class SimpleDocTemplate:\n"
        + "    def __init__(self, path, **k):\n"
        + "        self.path = path\n"
        + "    def build(self, *a, **k):\n"
        + "        open(self.path, 'wb').write(b'%PDF-stub')\n",
        encoding="utf-8",
    )
    return base / "stub"


def test_dossier_pdf_goes_under_the_data_root(tmp_path):
    md = tmp_path / "work" / "sam-demo.md"
    md.parent.mkdir()
    md.write_text("# Sam Demo\n\nA demo dossier.\n\n- one\n- two\n", encoding="utf-8")
    stub = _stub_reportlab(tmp_path)
    env_pp = os.pathsep.join([str(stub), str(ROOT / "tools")])
    r = _run(
        [str(ROOT / "tools" / "util" / "gen-dossier-pdf.py"), str(md)],
        tmp_path,
        _OWNER,
        extra={"PYTHONPATH": env_pp},
        cwd=tmp_path / "work",
    )
    assert r.returncode == 0, _out(r)[-3000:]
    assert (tmp_path / "data" / "dossiers" / "sam-demo.pdf").is_file(), _out(r)
    assert not (tmp_path / "work" / "dossier.pdf").exists()
    assert sorted(p.name for p in (tmp_path / "work").iterdir()) == ["sam-demo.md"]
    assert "*.pdf" in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()


def test_dossier_pdf_help_writes_nothing(tmp_path):
    r = _run([str(ROOT / "tools" / "util" / "gen-dossier-pdf.py"), "--help"], tmp_path, _OWNER)
    assert r.returncode == 0 and "data root" in r.stdout, _out(r)
    assert not (tmp_path / "data").exists()


# --- author audits out, drift_report self-contained ---------------------------------------------

_FUORI = (
    "tools/audit_cross_source.py",
    "tools/verify_data_quality.py",
    "tools/audit_contacts_quality.py",
    "tools/util/check-memory-index.py",
    "tools/linkedin/li-util-adapter.py",
)


def test_author_audits_left_the_kit():
    for rel in _FUORI:
        assert not (ROOT / rel).exists(), rel
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "li-util-adapter" not in pyproject
    nomi = [Path(rel).stem for rel in _FUORI]
    for base in ("tools", "dashboard", "docs", ".claude"):
        for f in (ROOT / base).rglob("*"):
            if f.is_file() and f.suffix in {".py", ".md", ".json", ".sh", ".toml", ".js"}:
                testo = f.read_text(encoding="utf-8", errors="ignore")
                for n in nomi:
                    assert n not in testo, (f, n)


def test_drift_report_uses_its_built_in_rules(tmp_path):
    membri = tmp_path / "members.txt"
    membri.write_text(
        "data/.env\ndata/.env.example\nsecrets/client_secret_123.json\nl3/vectordb/chunks.lance\n"
        "knowledge/entities/person/p_sam.json\n",
        encoding="utf-8",
    )
    script = str(ROOT / "tools" / "security" / "drift_report.py")
    r = _run([script, "--members-file", str(membri)], tmp_path, _OWNER)
    assert r.returncode == 2, _out(r)
    trovati = {(x["member"], x["severity"]) for x in json.loads(r.stdout)}
    assert ("data/.env", "high") in trovati
    assert ("secrets/client_secret_123.json", "high") in trovati
    assert ("l3/vectordb/chunks.lance", "medium") in trovati
    assert not any(
        m in ("data/.env.example", "knowledge/entities/person/p_sam.json") for m, _ in trovati
    )
    pulito = tmp_path / "clean.txt"
    pulito.write_text("knowledge/entities/person/p_sam.json\n", encoding="utf-8")
    r = _run([script, "--members-file", str(pulito)], tmp_path, _OWNER)
    assert r.returncode == 0 and json.loads(r.stdout) == [], _out(r)
    assert _run([script, "--help"], tmp_path).returncode == 0


# --- sb-cerca.py --------------------------------------------------------------------------------


@pytest.mark.parametrize("flag", ["--self-test", "--prova"])
def test_sb_cerca_self_test_passes_in_english(tmp_path, flag):
    r = _run([str(ROOT / "tools" / "util" / "sb-cerca.py"), flag], tmp_path, _OWNER)
    assert r.returncode == 0, _out(r)
    assert "self-test: 10 of 10 passed" in r.stdout and "OSCURATO" not in r.stdout
    assert "prova:" not in r.stdout and "NO  " not in r.stdout


def test_sb_cerca_masks_bare_known_tokens(tmp_path):
    _ok(
        _py(
            _load("sb_cerca_t", "tools/util/sb-cerca.py")
            + """
casi = [
    "sk-ant-api03-" + "Ab1" * 12,
    "xoxp-1234567890-1234567890-1234567890-" + "a1" * 12,
    "ghp_" + "Z9y8" * 9,
    "AKIA" + "QWERTYUIOPASDFGH",
    "AIza" + "B" * 35,
    ".".join(["eyJ" + "demoHeader01", "eyJ" + "demoPayload02", "demoSignature03"]),
]
for c in casi:
    out = m.oscura("token in a mail: " + c + " end")
    assert c not in out and m.MASK in out, (c, out)
assert m.oscura("a plain sentence about the handover") == "a plain sentence about the handover"
assert "credentials_loader" not in open(m.__file__).read()
print("ok")
""",
            tmp_path,
            _OWNER,
        )
    )


# --- xs-l3-schema-migrate.py --------------------------------------------------------------------


def test_schema_migrate_reads_what_sb_backup_writes(tmp_path):
    _ok(
        _py(
            _load("schema_migrate_t", "tools/cross-source/xs-l3-schema-migrate.py")
            + f"""
from pathlib import Path
b = Path({str(tmp_path / "backups")!r})
ok, msg = m._check_backup(b)
assert not ok and "--backup-dir" in msg, msg
b.mkdir()
(b / "sbk-config-20261126-100000.tar.gz").write_bytes(b"x")
(b / "sbk-l1-20261126-100000.tar.gz.enc.parziale").write_bytes(b"x")
ok, msg = m._check_backup(b)
assert not ok and "no sb-backup archive" in msg, msg
(b / "sbk-l1-20261126-110000.tar.gz.enc").write_bytes(b"x")
ok, msg = m._check_backup(b)
assert ok and "sbk-l1-20261126-110000.tar.gz.enc" in msg, msg
(b / "sbk-full-20261126-120000.tar.gz").write_bytes(b"x")
assert m._check_backup(b)[0]
assert m.BACKUP_DIR_DEFAULT == Path.home() / "Backups" / "sbk"
print("ok")
""",
            tmp_path,
            _OWNER,
        )
    )
    r = _run([str(CS / "xs-l3-schema-migrate.py"), "--help"], tmp_path, _OWNER)
    assert r.returncode == 0 and "--backup-dir" in r.stdout, _out(r)


# --- LinkedIn 'Connected On' --------------------------------------------------------------------


def test_linkedin_connected_on_becomes_an_iso_date(tmp_path):
    _ok(
        _py(
            _load("ke_t", "tools/cross-source/xs-l2-knowledge-extract.py")
            + """
d = m._data_linkedin
assert d("14 Feb 2025") == "2025-02-14"
assert d("3 Sept 2024") == "2024-09-03"
assert d("Feb 14, 2025") == "2025-02-14"
assert d("2/14/25") == "2025-02-14"
assert d("2025-02-14T09:30:00Z") == "2025-02-14"
assert d("31 Feb 2025") is None and d("someday") is None and d("") is None and d(None) is None
src = open(m.__file__).read()
assert 'quando[:10]' not in src
print("ok")
""",
            tmp_path,
            _OWNER,
        )
    )


# --- li-l0-import-export.py --dry-run -----------------------------------------------------------


def _linkedin_export(data: Path) -> None:
    d = data / "linkedin" / "raw" / "export-part1"
    d.mkdir(parents=True)
    (d / "Connections.csv").write_text(
        "Notes:\n"
        '"When exporting your connection data, you may notice that some of the email addresses are missing."\n'
        "\n"
        "First Name,Last Name,URL,Email Address,Company,Position,Connected On\n"
        "Leo,Park,https://www.linkedin.com/in/leo-park-demo,leo@globex.example,Globex Demo,CTO,12 Mar 2025\n",
        encoding="utf-8",
    )


def test_linkedin_import_dry_run_writes_nothing(tmp_path):
    data = tmp_path / "data"
    _linkedin_export(data)
    prima = _files(data)
    script = str(ROOT / "tools" / "linkedin" / "li-l0-import-export.py")
    r = _run([script, "--dry-run"], tmp_path, _OWNER)
    assert r.returncode == 0 and "Connections.csv: 1 connections" in _out(r), _out(r)[-3000:]
    assert "Dry run: nothing written." in _out(r)
    assert _files(data) == prima, _files(data) - prima
    r = _run([script], tmp_path, _OWNER)
    assert r.returncode == 0, _out(r)[-3000:]
    dopo = _files(data) - prima
    assert "linkedin/raw/export-connections.parquet" in dopo, dopo
    assert "last-runs.json" in dopo, dopo


# --- the app's verdict --------------------------------------------------------------------------


def test_verdict_tells_a_failed_stage_and_an_imported_source(tmp_path):
    _ok(
        _py(
            _load("sb_app_t", "tools/secondbrain/sb-app.py")
            + """
assert m.verdetto([], [], [])["titolo"] == "Nothing is connected yet."
wa = {"id": "whatsapp", "nome": "WhatsApp", "gruppo": "a_mano", "salute": "ok",
      "scaricata": None, "dato_del": "2026-11-20T10:00:00", "lettura": "2026-11-26T10:00:00"}
v = m.verdetto([wa], [], [])
assert v["titolo"] == "The knowledge is not built yet.", v
stadio = {"id": "l2_attachment_discovery", "nome": "Attachments of the main people",
          "salute": "errore", "ultimo": {"quando": "2026-11-26T10:00:00+00:00", "esito": "errore"},
          "da_solo": {"azione": None}}
v = m.verdetto([wa], [stadio], [])
assert v["livello"] == "errore" and v["titolo"] == "Attachments of the main people failed in the last run.", v
assert v["oggetto"] == {"tipo": "stadio", "id": "l2_attachment_discovery"}
print("ok")
""",
            tmp_path,
            _OWNER,
        )
    )


# --- run diary and runner log in English --------------------------------------------------------


def test_diary_writers_use_english_status_words():
    l0r = (CS / "xs-l0-refresh.py").read_text(encoding="utf-8")
    for parola in ('"STOPPED"', '"INTERRUPTED"', '"NOT STARTED"', '"not started"', '"resumed"'):
        assert parola in l0r, parola
    scrive = re.compile(
        r"_esito(?:_sicuro)?\(\s*esiti,[^)]*?\"(FERMATO|INTERROTTO|NON PARTITO|non partita|ripreso)\"",
        re.S,
    )
    for rel in ("sb-full.py", "sb_corsie.py", "sb_ripresa.py"):
        testo = (ROOT / "tools" / "secondbrain" / rel).read_text(encoding="utf-8")
        assert not scrive.findall(testo), (rel, scrive.findall(testo))
        assert "L0R.DIARIO_" in testo, rel


def test_diary_readers_accept_both_words(tmp_path):
    cartella = tmp_path / "giro"
    (cartella / "log").mkdir(parents=True)
    _ok(
        _py(
            _load("sb_ripresa_t", "tools/secondbrain/sb_ripresa.py", "r")
            + _load("sb_errori_t", "tools/secondbrain/sb_errori.py", "e")
            + f"""
from pathlib import Path
c = Path({str(cartella)!r})
for fine, ripreso, interrotto in (("STOPPED", "resumed", "INTERRUPTED"), ("FERMATO", "ripreso", "INTERROTTO")):
    (c / "esiti.tsv").write_text(
        "26/11 10:00:00\\tSTART\\t2 steps\\tthen-ingest\\n"
        f"26/11 10:00:01\\tgmail\\t{{ripreso}}\\tclosed in run x\\n"
        f"26/11 10:00:02\\tslack\\tattempt.1\\t{{interrotto}}\\t5s\\n"
        f"26/11 10:00:03\\tEND\\t{{fine}}\\tnot closed: slack\\n",
        encoding="utf-8",
    )
    g = r.leggi_giro(c, ["gmail", "slack"])
    assert "gmail" in g.chiusi and "slack" not in g.chiusi, (fine, g.chiusi)
    assert g.fermato, fine
    assert e._ultimo_esito(c / "esiti.tsv", "slack")[0] == -15, interrotto
print("ok")
""",
            tmp_path,
            _OWNER,
        )
    )


def test_runner_prints_labels_and_does_not_retry_a_setup_failure(tmp_path):
    _ok(
        _py(
            _load("xs_pipeline_run_t", "tools/cross-source/xs-pipeline-run.py")
            + """
import logging, subprocess
from pathlib import Path
assert str(m.Salto("l1_personio", "non_elencata", "x")) == "l1_personio (not in enabled_sources) — x"
assert str(m.Salto("l3_x", "niente_da_leggere")) == "l3_x (nothing to read yet)"
assert m.CLASSI_EN["fallito"] == "failed" and m._FERMATA_TENTATIVI["configurazione"] == 1

righe = []
class Raccolta(logging.Handler):
    def emit(self, rec):
        righe.append(rec.getMessage())
m.log.addHandler(Raccolta())
attese = []
m.time.sleep = lambda s: attese.append(s)
m._wait_and_budget = lambda name: None
m._registra_nel_budget = lambda name, budget: None
m._timeout_step = lambda name: 60
m._dlq_add_failure = lambda *a, **k: None
m._log_metrics = lambda *a, **k: None
codici = []
def finto(cmd, *, timeout, budget, name):
    codici.append(rc)
    cp = subprocess.CompletedProcess(cmd, rc, "", "no embedding model")
    cp.guard_kill = None
    cp.picco = 0
    return cp
m._run_guarded = finto
script = Path(m.__file__)

rc = 78
assert m.run_script("L3 Index", script) is False
assert codici == [78] and attese == [], (codici, attese)
testo = "\\n".join(righe)
assert "setup missing, not retried" in testo and "line stop" not in testo, testo

codici.clear(); righe.clear(); rc = 1
assert m.run_script("L2 Demo", script) is False
assert codici == [1, 1] and attese == [30], (codici, attese)
testo = "\\n".join(righe)
assert "🔁 retry: 'L2 Demo' died (failed)" in testo and "(class: failed)" in testo, testo
assert "fallito" not in testo and "line stop" not in testo, testo
print("ok")
""",
            tmp_path,
            _OWNER,
        )
    )


def test_app_reads_the_new_and_old_retry_lines(tmp_path):
    _ok(
        _py(
            _load("sb_app_t2", "tools/secondbrain/sb-app.py")
            + """
for riga in (
    "10:00:00 WARNING   🔁 retry: 'L3 Index' died (setup missing, not retried) — attempt 2/2 in 30 s",
    "10:00:00 WARNING   🔁 line stop: 'L3 Index' died (fallito) — attempt 2/2 in 30 s",
):
    mm = m._RE_RIPROVA.match(riga)
    assert mm and mm["nome"] == "L3 Index" and mm["t"] == "2", riga
print("ok")
""",
            tmp_path,
            _OWNER,
        )
    )


def test_index_exits_78_without_a_model():
    src = (CS / "xs-l3-index.py").read_text(encoding="utf-8")
    i = src.index("model, model_name, dim = load_embedding_model(")
    blocco = src[i : i + 900]
    assert "sys.exit(78)" in blocco and "sys.exit(1)" not in blocco


def test_knowledge_coverage_warning_is_english(tmp_path):
    _ok(
        _py(
            _load("ke_t2", "tools/cross-source/xs-l2-knowledge-extract.py")
            + """
s = m._deriva_in_parole({"rete": ["person_a", "person_b", "commitment_c", "commitment_d", "x"]})
assert s == "network (entities linked to nothing yet): 5 (person_a, person_b, commitment_c, ... +2)", s
assert "rete" not in s
print("ok")
""",
            tmp_path,
            _OWNER,
        )
    )


# --- pl_voice_seed_wa.py ------------------------------------------------------------------------


def _chat(cartella: Path) -> None:
    cartella.mkdir(parents=True)
    (cartella / "_chat.txt").write_text(
        "[19/11/2026, 12:00:00] Omar Demo: hello\n[19/11/2026, 12:00:10] Alex Demo: hi\n",
        encoding="utf-8",
    )


def test_voice_seed_never_walks_downloads_unless_asked(tmp_path):
    _chat(tmp_path / "home" / "Downloads" / "WhatsApp Chat - Omar Demo")
    _chat(tmp_path / "data" / "whatsapp" / "WhatsApp Chat - Pia Demo")
    _ok(
        _py(
            _load("voice_seed_t", "tools/plaud/pl_voice_seed_wa.py")
            + f"""
from pathlib import Path
assert all("Downloads" not in str(p) for p in m.WA_ROOTS), m.WA_ROOTS
trovati = m.find_chat_files()
assert [p.parent.name for p in trovati] == ["WhatsApp Chat - Pia Demo"], trovati
altro = Path({str(tmp_path / "home" / "Downloads")!r})
assert len(m.find_chat_files([*m.WA_ROOTS, altro])) == 2
print("ok")
""",
            tmp_path,
            _OWNER,
        )
    )
    r = _run([str(ROOT / "tools" / "plaud" / "pl_voice_seed_wa.py"), "scan", "--help"], tmp_path)
    assert r.returncode == 0 and "--folder" in r.stdout, _out(r)


# --- LinkedIn browser scripts -------------------------------------------------------------------

_NODE = shutil.which("node")


def test_linkedin_scripts_have_no_placeholder_id():
    for f in (ROOT / "tools" / "linkedin" / "scripts").glob("*.js"):
        testo = f.read_text(encoding="utf-8")
        assert "PLACEHOLDER" not in testo, f.name
        if "MY_URN" in testo:
            assert "require('./li-own-urn.js')" in testo, f.name


@pytest.mark.skipif(_NODE is None, reason="node is not installed")
def test_linkedin_own_urn_from_config_env_and_me(tmp_path):
    cfg = tmp_path / "sbk.config.json"
    cfg.write_text(json.dumps({"linkedin": {"own_urn": "urn:li:fsd_profile:ACoAADemoConfig123"}}))
    modulo = str(ROOT / "tools" / "linkedin" / "scripts" / "li-own-urn.js")
    codice = f"""
const u = require({json.dumps(modulo)});
const out = {{
  cfg: u.ownUrnFromConfig(),
  me: u.ownUrnFromMe({{included: [{{'$type': 'com.linkedin.voyager.identity.shared.MiniProfile',
                                    entityUrn: 'urn:li:fs_miniProfile:ACoAADemoFromMe456'}}]}}),
  none: u.ownUrnFromMe({{included: []}}),
}};
console.log(JSON.stringify(out));
"""
    base = {k: v for k, v in os.environ.items() if not k.startswith("SBK_")}
    env = {
        **base,
        "SBK_CONFIG": str(cfg),
        "SBK_DATA_ROOT": str(tmp_path / "data"),
        "HOME": str(tmp_path),
    }
    r = subprocess.run([_NODE, "-e", codice], env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == {
        "cfg": "ACoAADemoConfig123",
        "me": "ACoAADemoFromMe456",
        "none": "",
    }
    env["SBK_LINKEDIN_OWN_URN"] = "ACoAADemoEnv789xyz"
    r = subprocess.run([_NODE, "-e", codice], env=env, capture_output=True, text=True, timeout=60)
    assert json.loads(r.stdout)["cfg"] == "ACoAADemoEnv789xyz"
    for f in (ROOT / "tools" / "linkedin" / "scripts").glob("*.js"):
        chk = subprocess.run([_NODE, "--check", str(f)], capture_output=True, text=True, timeout=60)
        assert chk.returncode == 0, (f.name, chk.stderr)
