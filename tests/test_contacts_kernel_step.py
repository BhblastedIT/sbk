"""The kernel's address-book step (tools/cross-source/xs-l1-contacts-enrich.py) on a slot
where no row has a name: it used to crash sorting a frame with no columns.

Each run is a subprocess on its own temporary data root and config. No network, no Keychain.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
STEP = ROOT / "tools" / "cross-source" / "xs-l1-contacts-enrich.py"
CT = ROOT / "tools" / "contacts"

COLUMNS = {
    "name",
    "organization",
    "phone_numbers",
    "email",
    "phone_primary",
    "name_normalized",
    "first_name",
    "last_name",
    "last_updated",
    "birthday",
    "is_business",
    "kind",  # "org" / "group" / "location" for a card that is not a person, "" otherwise
}


def _env(tmp: Path) -> dict:
    e = {k: v for k, v in os.environ.items() if not k.startswith(("SBK_", "GOOGLE_OAUTH"))}
    cfg = tmp / "owner-only.json"
    cfg.write_text(
        json.dumps({"owner": "Alex Demo", "own_emails": ["alex@personal.example"]}),
        encoding="utf-8",
    )
    e.update(
        SBK_DATA_ROOT=str(tmp),
        SBK_CONTAINERIZED="1",
        SBK_CONFIG=str(cfg),
        HOME=str(tmp / "home"),
        PYTHONPATH=os.pathsep.join([str(ROOT / "tools"), str(ROOT / "tools" / "cross-source")]),
    )
    return e


def _run(cmd: list[str], tmp: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, env=_env(tmp), capture_output=True, text=True, timeout=120, cwd=str(ROOT)
    )


def _slot(tmp: Path, rows: list[dict]) -> None:
    (tmp / "contacts").mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(tmp / "contacts" / "contacts.parquet")


def _out(tmp: Path) -> pd.DataFrame:
    return pd.read_parquet(tmp / "contacts" / "processed" / "contacts-iphone.parquet")


def test_slot_with_no_names_writes_an_empty_file_with_its_columns(tmp_path):
    _slot(
        tmp_path,
        [
            {"full_name": "", "primary_email": "ana@fabrikam.example", "source": "contacts:x"},
            {"full_name": "", "primary_phone": "+1 555 0100", "source": "contacts:x"},
        ],
    )
    r = _run([sys.executable, str(STEP)], tmp_path)
    assert r.returncode == 0, r.stderr[-2000:]
    assert "Traceback" not in r.stderr
    out = _out(tmp_path)
    assert len(out) == 0 and set(out.columns) == COLUMNS
    summary = json.loads(
        (tmp_path / "contacts" / "processed" / "_contacts_summary.json").read_text()
    )
    assert summary["totals"]["contacts"] == 0 and summary["coverage"]["phone_rate"] == 0


def test_rows_without_a_name_are_left_out_and_the_others_kept(tmp_path):
    _slot(
        tmp_path,
        [
            {"full_name": "", "primary_email": "ana@fabrikam.example", "source": "contacts:x"},
            {
                "full_name": "Lee Park",
                "primary_email": "lee@contoso.example",
                "primary_phone": "+1 555 0142",
                "source": "contacts:x",
            },
        ],
    )
    r = _run([sys.executable, str(STEP)], tmp_path)
    assert r.returncode == 0, r.stderr[-2000:]
    out = _out(tmp_path)
    assert list(out["name"]) == ["Lee Park"] and set(out.columns) == COLUMNS
    assert out.iloc[0]["email"] == "lee@contoso.example"


def test_contacts_plugin_with_an_email_only_card_ends_cleanly(tmp_path):
    """The two commands a user types: import an export whose only card has no name, then L1."""
    vcf = tmp_path / "only-email.vcf"
    vcf.write_text(
        "BEGIN:VCARD\nVERSION:3.0\nFN:\nEMAIL:ana@fabrikam.example\nEND:VCARD\n",
        encoding="utf-8",
    )
    r = _run([sys.executable, str(CT / "ct-l0-import.py"), str(vcf), "--label", "phone"], tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr[-2000:]
    r = _run([sys.executable, str(CT / "ct-l1-enrich.py")], tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr[-2000:]
    assert "Traceback" not in r.stderr
    assert len(_out(tmp_path)) == 0
