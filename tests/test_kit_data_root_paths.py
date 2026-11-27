"""No personal data is written inside the repo tree, and every data path follows SBK_DATA_ROOT.

Each module is loaded in a fresh Python process with SBK_DATA_ROOT and HOME pointing at a temporary
folder, so the paths are computed the way a person with a custom data root gets them. The LinkedIn
check runs the documented path (import the data export, then the L1 step) on a demo export.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"

# module file -> attributes that must resolve under the data root
WRITERS = {
    "tools/sbk_config.py": ["CALENDAR_RAW_DIR", "NETWORK_DIR", "NOTES_DIR", "LINKEDIN_RAW_DIR"],
    "tools/calendar/ca-l0-download.py": ["RAW_CALENDAR_DIR"],
    "tools/linkedin/li-l1-enrich.py": [
        "RAW_LINKEDIN_DIR",
        "RAW_CONVERSATIONS_FULL",
        "PROCESSED_DIR",
    ],
    "tools/linkedin/li_safety.py": ["DATA_DIR", "KILLSWITCH_LOCK"],
    "tools/knowledge_aliases.py": ["ALIASES_PATH"],
    "tools/cross-source/xs-l3-schema-migrate.py": ["AUDIT_LOG"],
    "tools/cross-source/xs-l2-network-profiles.py": ["NETWORK_DIR", "INDEX_FILE", "RAW_DIR"],
    "tools/cross-source/xs-l1-contacts-enrich.py": ["CONTACTS_JSON", "CONTACTS_JSON_ALT"],
    "tools/cross-source/xs-util-consolidate-extractions.py": ["OUTPUT_DIR"],
    "tools/plaud/pl_auth_refresh.py": ["WT_OUT"],
    "tools/plaud/pl_quadro.py": ["DATA"],
    "tools/plaud/pl_voice_cluster.py": ["RAW_DIR", "EMB_PATH", "OUT_PATH"],
    "tools/notion/no-l0-download.py": ["INDEX_PATH", "OUTPUT_DIR"],
    "tools/voice-memos/vm-l1-enrich.py": ["AT_DIR"],
    "tools/docusign/ds-l0-api.py": ["KEY_FILE"],
    "tools/util/sb-rango.py": ["ENTITA"],
}

PROBE = r"""
import importlib.util, json, sys
from pathlib import Path
sys.path[:0] = [sys.argv[1] + "/tools", sys.argv[1] + "/tools/cross-source"]
out = {}
for rel, attrs in json.loads(sys.argv[2]).items():
    name = "probe_" + rel.replace("/", "_").replace("-", "_").replace(".", "_")
    spec = importlib.util.spec_from_file_location(name, Path(sys.argv[1]) / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    out[rel] = {a: str(getattr(mod, a)) for a in attrs}
print("PROBE=" + json.dumps(out))
"""


def _env(tmp_path: Path) -> dict:
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("SBK_", "DOCUSIGN_", "SB_")) and k != "HOME"
    }
    env.update(
        HOME=str(tmp_path / "home"),
        SBK_DATA_ROOT=str(tmp_path / "data"),
        SBK_CONFIG=str(ROOT / "sbk.config.example.json"),
        PYTHONDONTWRITEBYTECODE="1",
        PYTHON_KEYRING_BACKEND="keyring.backends.fail.Keyring",
    )
    (tmp_path / "home").mkdir(exist_ok=True)
    return env


def _repo_sbk_files() -> set[str]:
    base = ROOT / "sbk"
    if not base.exists():
        return set()
    return {str(p) for p in base.rglob("*") if p.is_file() and "identity" not in p.parts}


def test_main_writers_resolve_under_the_data_root(tmp_path):
    r = subprocess.run(
        [sys.executable, "-c", PROBE, str(ROOT), json.dumps(WRITERS)],
        env=_env(tmp_path),
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert r.returncode == 0, r.stderr[-2000:]
    line = next(x for x in r.stdout.splitlines() if x.startswith("PROBE="))
    got = json.loads(line.removeprefix("PROBE="))
    data = (tmp_path / "data").resolve()
    for rel, attrs in got.items():
        for attr, value in attrs.items():
            p = Path(value).expanduser().resolve()
            assert p.is_relative_to(data), f"{rel} {attr} = {value} is outside SBK_DATA_ROOT"
            assert not p.is_relative_to(ROOT), f"{rel} {attr} = {value} is inside the repo"


# Files that still carry the old default while another session owns them (decision D16).
_D16 = {
    "tools/plaud/regole/giudizio.py",
    "tools/plaud/pl_eval_set.py",
    "tools/plaud/pl_calibrate.py",
}
_HOME_DEFAULT = re.compile(
    r"""(Path\.home\(\)|\bHOME)\s*/\s*["']\.sbk-data|(Path|expanduser)\(\s*f?["']~/\.sbk-data"""
)
_REPO_DATA = re.compile(
    r"""["']sbk["']\s*[/,]\s*["'](raw|network|companies)["']|["']sbk/(raw|network|companies)|["']scratchpad["']|["']\./data/"""
)


def _code_files():
    for base in (TOOLS, ROOT / "dashboard"):
        for p in base.rglob("*"):
            if p.suffix in {".py", ".js"} and "node_modules" not in p.parts:
                yield p


def test_no_code_path_ignores_sbk_data_root():
    bad = []
    for p in _code_files():
        rel = str(p.relative_to(ROOT))
        if rel in _D16:
            continue
        for n, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            s = line.strip()
            if s.startswith(("#", "//", "*")) or "help=" in s:
                continue
            if _HOME_DEFAULT.search(line) and "SBK_DATA_ROOT" not in line:
                bad.append(f"{rel}:{n}: {s[:120]}")
    assert not bad, "hard-coded ~/.sbk-data that ignores SBK_DATA_ROOT:\n" + "\n".join(bad)


def test_no_code_writes_data_inside_the_repo_tree():
    bad = []
    for p in _code_files():
        rel = str(p.relative_to(ROOT))
        for n, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if _REPO_DATA.search(line):
                bad.append(f"{rel}:{n}: {line.strip()[:120]}")
    assert not bad, "data paths inside the repo tree:\n" + "\n".join(bad)


def test_gitignore_keeps_old_repo_data_folders_out_of_git():
    lines = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    for entry in ("/sbk/raw/", "/sbk/network/", "/scratchpad/", "/sbk/identity/"):
        assert entry in lines, entry


@pytest.fixture
def demo_linkedin_export(tmp_path):
    src = tmp_path / "data" / "linkedin" / "raw" / "export-part1"
    src.mkdir(parents=True)
    (src / "Connections.csv").write_text(
        "Notes:\n"
        '"When exporting your connection data, you may notice that some of the email addresses are missing."\n'
        "\n"
        "First Name,Last Name,URL,Email Address,Company,Position,Connected On\n"
        "Sam,Demo,https://www.linkedin.com/in/sam-demo,sam@demo.example,Acme Demo,CTO,01 Jan 2025\n"
        "Robin,Sample,https://www.linkedin.com/in/robin-sample,,Globex Demo,Designer,15 Mar 2024\n",
        encoding="utf-8",
    )
    return tmp_path


def _run(script: str, tmp_path: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(TOOLS / script), *args],
        env=_env(tmp_path),
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=300,
    )


def test_linkedin_import_then_l1_on_a_demo_export(demo_linkedin_export):
    import pandas as pd

    tmp_path = demo_linkedin_export
    before = _repo_sbk_files()
    imp = _run("linkedin/li-l0-import-export.py", tmp_path)
    assert imp.returncode == 0, imp.stderr[-2000:]
    raw = tmp_path / "data" / "linkedin" / "raw" / "export-connections.parquet"
    assert raw.is_file()

    l1 = _run("linkedin/li-l1-enrich.py", tmp_path)
    assert l1.returncode == 0, (l1.stdout + l1.stderr)[-3000:]
    out = tmp_path / "data" / "linkedin" / "processed" / "contacts-linkedin.parquet"
    assert out.is_file(), (l1.stdout + l1.stderr)[-3000:]
    df = pd.read_parquet(out)
    assert len(df) == 2
    assert "Traceback" not in l1.stderr
    assert "raw directory not found" not in (l1.stdout + l1.stderr)
    assert _repo_sbk_files() == before, "the LinkedIn steps wrote into <repo>/sbk"


def test_linkedin_l1_with_nothing_imported_is_nothing_to_do(tmp_path):
    l1 = _run("linkedin/li-l1-enrich.py", tmp_path)
    assert l1.returncode == 0, (l1.stdout + l1.stderr)[-3000:]
    assert "nothing to do" in (l1.stdout + l1.stderr)
    assert not (tmp_path / "data" / "linkedin" / "processed").exists()


def test_calendar_json_copy_goes_under_the_data_root(tmp_path):
    probe = (
        "import importlib.util, sys; from pathlib import Path\n"
        f"sys.path[:0] = [{str(TOOLS)!r}]\n"
        f"spec = importlib.util.spec_from_file_location('ca_probe', {str(TOOLS / 'calendar' / 'ca-l0-download.py')!r})\n"
        "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
        "p = m.RAW_CALENDAR_DIR / 'cal-demo.json'\n"
        "m.events_to_json([{'id': 'e1', 'summary': 'Demo call', 'attendees': [{'email': 'sam@demo.example'}]}], p)\n"
        "print('WROTE=' + str(p))\n"
    )
    before = _repo_sbk_files()
    r = subprocess.run(
        [sys.executable, "-c", probe],
        env=_env(tmp_path),
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert r.returncode == 0, r.stderr[-2000:]
    wrote = Path(
        next(x for x in r.stdout.splitlines() if x.startswith("WROTE=")).removeprefix("WROTE=")
    )
    assert wrote.is_file()
    assert wrote.resolve().is_relative_to((tmp_path / "data" / "calendars").resolve())
    assert _repo_sbk_files() == before
