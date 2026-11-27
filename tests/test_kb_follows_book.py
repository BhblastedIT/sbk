"""The knowledge base follows the book across runs, the entity map is refreshed on every run, phones are stored
in one form.

- A person the knowledge base coined in an earlier run for a bare number (an unsaved WhatsApp chat) joins the
  person the address book names for that number in a later run: the facts are kept, the number-only entity goes
  to knowledge/archive/merged/ with merged_into, and the merge journal lets xs-l4-disfa-fusione.py undo it. A
  number the book now knows as a company card stops being a person (knowledge/archive/retired/). WhatsApp facts
  follow the person after the book turns a phone row into an email row. Sources that arrive in separate runs give
  the same knowledge base as the same sources in one run.
- The entity map is rebuilt from the book on every run that merges (not only when it is missing), and a changed
  map is applied to the book in the same run: a card with a second email that arrives after a database joins the
  same person, with both emails and the same person_id as one run gives.
- The book and the knowledge base store phones normalised ("+447700900412").
- The shared normaliser reads a national number whose first digits equal the country code as national, and
  understands "00<code> (0)".

Every step runs in a subprocess with its own SBK_DATA_ROOT, HOME and config. Demo data only, phone numbers from
the ranges reserved for fiction (+1 202 555 01xx, +44 7700 900xxx, +44 20 7946 0xxx) or all-zero; no network,
no model key, no Keychain.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
CS = TOOLS / "cross-source"
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(CS))

_ROBIN = {
    "owner": "Robin Demo",
    "own_names": ["robin demo", "robin"],
    "own_emails": ["robin@example.com"],
    "phone_country_code": "44",
}


def _env(tmp: Path, config: dict) -> dict:
    cfg = tmp / "sbk.config.json"
    cfg.write_text(json.dumps(config), encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("SBK_", "ANTHROPIC_"))}
    (tmp / "home").mkdir(parents=True, exist_ok=True)
    env.update(
        HOME=str(tmp / "home"),
        SBK_DATA_ROOT=str(tmp / "data"),
        SBK_CONFIG=str(cfg),
        PYTHON_KEYRING_BACKEND="keyring.backends.fail.Keyring",
        PYTHONPATH=os.pathsep.join([str(TOOLS), str(CS)]),
    )
    return env


def _ok(tmp: Path, config: dict, args: list, what: str) -> str:
    r = subprocess.run(
        [sys.executable, *[str(a) for a in args]],
        cwd=str(ROOT),
        env=_env(tmp, config),
        capture_output=True,
        text=True,
        timeout=600,
        stdin=subprocess.DEVNULL,
    )
    out = (r.stdout or "") + (r.stderr or "")
    assert r.returncode == 0, f"{what}: exit {r.returncode}\n" + out[-4000:]
    assert "Traceback (most recent" not in out, f"{what}\n" + out[-4000:]
    return out


# --------------------------------------------------------------------------- the normaliser


def test_national_numbers_that_begin_with_the_country_code():
    from text_utils import normalize_phone as n

    plus = "+"
    # An Italian mobile written nationally starts with 39 (a 390-393 prefix) and stays national; the
    # same number written in full, with "00" or without "+", is the same number. All-zero numbers.
    it = plus + "39" + "3900000001"
    for raw in ("3900000001", "0039" + "3900000001", "39" + "3900000001", it):
        assert n(raw, "39") == it, (raw, n(raw, "39"))
    assert n("3920000002", "39") == plus + "39" + "3920000002"
    # India: a mobile that starts with 91, nationally and in full
    ind = plus + "91" + "9100000001"
    for raw in ("91000 00001", "91" + "9100000001", "0091 91000 00001", ind):
        assert n(raw, "91") == ind, (raw, n(raw, "91"))
    # UK: in full without "+" (longer than any UK national number) keeps its code
    assert n("447700900631", "44") == "+447700900631"
    # the US trunk 1 is the code itself
    assert n("1 202 555 0147", "1") == n("(202) 555-0147", "1") == "+12025550147"


def test_the_bracketed_trunk_zero_in_every_form():
    from text_utils import normalize_phone as n

    for raw in ("+44 (0)7700 900631", "0044 (0)7700 900631", "44 (0)7700 900631", "07700 900631"):
        assert n(raw, "44") == "+447700900631", (raw, n(raw, "44"))
    assert n("(0)20 7946 0123", "44") == "+442079460123"
    # Italy keeps its 0 after the code, whatever the form
    it = "+" + "390200000000"
    for raw in ("0039 (0)2 0000 0000", "02 0000 0000"):
        assert n(raw, "39") == it, (raw, n(raw, "39"))


def test_a_merge_mark_survives_a_read_and_a_write():
    from knowledge_schema import dict_to_fact, fact_to_dict

    d = {
        "fact_id": "f1",
        "entity_id": "person_demo",
        "entity_type": "person",
        "attribute": "contact.phone",
        "value": "+447700900412",
        "confidence": 0.8,
        "created_at": "2026-11-20T00:00:00+00:00",
        "source": {"source_type": "whatsapp", "source_file": "x", "record_id": "tel:+447700900412"},
        "source_entity_id": "person_number",
    }
    assert fact_to_dict(dict_to_fact(d))["source_entity_id"] == "person_number"
    assert "source_entity_id" not in fact_to_dict(dict_to_fact({**d, "source_entity_id": None}))


# --------------------------------------------------------------------------- end to end, real files

_CARDS = (
    "BEGIN:VCARD\nVERSION:3.0\nN:Varga;Ines;;;\nFN:Ines Varga\nTEL;TYPE=CELL:07700 900305\nEND:VCARD\n"
    "BEGIN:VCARD\nVERSION:3.0\nN:Marsh;Theo;;;\nFN:Theo Marsh\nORG:Dune Demo\n"
    "EMAIL;TYPE=INTERNET:theo@dune.example\nTEL;TYPE=CELL:+44 7700 900412\nEND:VCARD\n"
    "BEGIN:VCARD\nVERSION:3.0\nN:;;;;\nFN:Fern Bakery\nORG:Fern Bakery\n"
    "TEL;TYPE=WORK:020 7946 0000\nX-ABShowAs:COMPANY\nEND:VCARD\n"
)
_CHATS = {
    "WhatsApp Chat with +44 7700 900412.txt": (
        "19/11/2026, 08:00 - +44 7700 900412: Hello Robin, Theo from the fair.\n"
        "19/11/2026, 08:05 - Robin Demo: Hi Theo, good to meet you.\n"
    ),
    "WhatsApp Chat with +44 7700 900305.txt": (
        "20/11/2026, 21:00 - +44 7700 900305: Thanks for the slides!\n"
        "20/11/2026, 21:02 - Robin Demo: Any time.\n"
    ),
    "WhatsApp Chat with +44 20 7946 0000.txt": (
        "21/11/2026, 09:00 - +44 20 7946 0000: Your order is ready.\n"
        "21/11/2026, 09:05 - Robin Demo: Coming at noon.\n"
    ),
    "WhatsApp Chat with +1 202 555 0147.txt": (
        "22/11/2026, 14:00 - +1 202 555 0147: Hi Robin, Sol from the harbour tour.\n"
        "22/11/2026, 14:02 - Robin Demo: Hi Sol!\n"
    ),
    "WhatsApp Chat with +44 7700 900777.txt": (
        "23/11/2026, 18:00 - +44 7700 900777: Mia here, new number.\n"
        "23/11/2026, 18:01 - Robin Demo: Saved, thanks Mia.\n"
    ),
}
# A database person known by email; her number is written nationally there.
_MIA_ROW = [(1, "Mia Cole", "mia@cove.example", "07700 900777", "2026-11-18 09:00:00")]
_MIA_CALL = [(1, "2026-11-18 10:00:00", "Kiln order", "mia@cove.example", "2026-12-03", "open")]


def _whatsapp(tmp: Path, config: dict) -> None:
    raw = tmp / "data" / "whatsapp" / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    for name, text in _CHATS.items():
        (raw / name).write_text(text, encoding="utf-8")
    _ok(tmp, config, [TOOLS / "whatsapp" / "wa-l0l3-full.py", "--skip-analysis"], "wa L0")
    _ok(tmp, config, [TOOLS / "whatsapp" / "wa-l1-enrich.py", "--incremental"], "wa L1")


def _address_book(tmp: Path, config: dict, cards: str) -> None:
    f = tmp / "home" / "Downloads" / "book.vcf"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(cards, encoding="utf-8")
    _ok(tmp, config, [TOOLS / "contacts" / "ct-l0-import.py", f, "--label", "phone"], "ct L0")
    _ok(tmp, config, [TOOLS / "contacts" / "ct-l1-enrich.py"], "ct L1")


def _ingest(tmp: Path, config: dict) -> str:
    """The L2 part of --ingest that this test is about: merge, entity map refresh, Knowledge Extract."""
    out = _ok(tmp, config, [CS / "xs-l2-merge.py"], "merge")
    out += _ok(tmp, config, [CS / "xs-l2-entity-map-cleanup.py"], "entity map")
    out += _ok(
        tmp, config, [CS / "xs-l2-knowledge-extract.py", "--incremental"], "knowledge extract"
    )
    return out


def _persons(tmp: Path) -> dict[str, dict]:
    out = {}
    for f in sorted((tmp / "data" / "knowledge" / "entities" / "person").glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        live = {
            (x["attribute"], str(x["value"]).strip().lower())
            for x in d.get("facts", [])
            if not x.get("valid_to")
            and not x.get("expired_at")
            and x["attribute"] != "identity.classe"
        }
        out[d["entity_id"]] = {"name": d["canonical_name"], "facts": live}
    return out


def _by_name(persons: dict) -> dict[str, set]:
    return {p["name"]: p["facts"] for p in persons.values()}


def test_the_knowledge_base_follows_the_book_across_runs(tmp_path):
    later = tmp_path / "later"
    sources = ["whatsapp", "contacts", "databases"]
    config = {
        **_ROBIN,
        "enabled_sources": sources,
        "databases": _database(later, _MIA_ROW, _MIA_CALL),
    }
    # run 1: only the WhatsApp chats, five unsaved numbers become five persons named by their number
    _whatsapp(later, {**config, "enabled_sources": ["whatsapp"]})
    _ingest(later, {**config, "enabled_sources": ["whatsapp"]})
    assert sorted(p["name"] for p in _persons(later).values()) == [
        "+1 202 555 0147",
        "+44 20 7946 0000",
        "+44 7700 900305",
        "+44 7700 900412",
        "+44 7700 900777",
    ]
    # runs 2 and 3: the address book and the database arrive. Theo (card with email), Ines (card, phone
    # only) and Mia (database, email) are named, the bakery is a company card, Sol stays a number
    _address_book(later, config, _CARDS)
    _db_l0_l1(later, config)
    out = _ingest(later, config) + _ingest(later, config)
    persons = _persons(later)
    names = sorted(p["name"] for p in persons.values())
    assert names == ["+1 202 555 0147", "Ines Varga", "Mia Cole", "Theo Marsh"], (
        names,
        out[-3000:],
    )
    theo = _by_name(persons)["Theo Marsh"]
    assert ("contact.email", "theo@dune.example") in theo
    assert ("contact.phone", "+447700900412") in theo
    # the WhatsApp facts follow the person once the book turned the number into an email row
    for who in ("Theo Marsh", "Mia Cole"):
        assert any(a == "communication.whatsapp_messages" for a, _ in _by_name(persons)[who]), who
    assert ("contact.phone", "+447700900777") in _by_name(persons)["Mia Cole"]
    # the commitment of a meeting she attends lands on her the first time she is named
    assert ("relationship.commitment", "kiln order") in _by_name(persons)["Mia Cole"]
    for p in persons.values():  # one number, one form
        for attr, value in p["facts"]:
            if attr == "contact.phone":
                assert re.fullmatch(r"\+\d+", value), (p["name"], value)

    # the number-only entities are archived, never deleted, and recorded in a merge journal
    arch = later / "data" / "knowledge" / "archive"
    merged = {f.stem: json.loads(f.read_text()) for f in (arch / "merged").glob("*.json")}
    assert sorted(d["canonical_name"] for d in merged.values()) == [
        "+44 7700 900305",
        "+44 7700 900412",
        "+44 7700 900777",
    ]
    assert all(d["merged_into"] in persons for d in merged.values())
    retired = [json.loads(f.read_text()) for f in (arch / "retired").glob("*.json")]
    assert [d["canonical_name"] for d in retired] == ["+44 20 7946 0000"]
    assert "company card" in retired[0]["merge_reason"]
    journals = sorted(
        (later / "data" / "knowledge" / "meta").glob("fusioni-l2-knowledge-extract-book-*.jsonl")
    )
    assert len(journals) == 1, journals  # only the run that had something to do writes one
    righe = [json.loads(x) for x in journals[0].read_text().splitlines()]
    assert sorted(r["fuso"] for r in righe if r["tipo"] == "fusione") == sorted(
        [*merged, retired[0]["entity_id"]]
    )

    # the same sources in one run give the same knowledge base
    once = tmp_path / "once"
    config1 = {**config, "databases": _database(once, _MIA_ROW, _MIA_CALL)}
    _whatsapp(once, config1)
    _address_book(once, config1, _CARDS)
    _db_l0_l1(once, config1)
    _ingest(once, config1)
    _ingest(once, config1)
    assert {k: v for k, v in _persons(once).items()} == persons

    # the merges can be undone like any other merge
    _ok(
        later,
        config,
        [CS / "xs-l4-disfa-fusione.py", "--journal", journals[0].name, "--apply"],
        "undo",
    )
    back = sorted(p["name"] for p in _persons(later).values())
    assert back == [
        "+1 202 555 0147",
        "+44 20 7946 0000",
        "+44 7700 900305",
        "+44 7700 900412",
        "+44 7700 900777",
        "Ines Varga",
        "Mia Cole",
        "Theo Marsh",
    ], back


def _database(tmp: Path, people: list[tuple], calls: list[tuple] = ()) -> dict:
    db = tmp / "home" / "Documents" / "crm.sqlite"
    db.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(db)
    c.execute(
        "CREATE TABLE people(pid INTEGER PRIMARY KEY, name TEXT, email TEXT, phone TEXT, updated TEXT)"
    )
    c.executemany("INSERT INTO people VALUES (?,?,?,?,?)", people)
    c.execute(
        "CREATE TABLE calls(id INTEGER PRIMARY KEY, at TEXT, subject TEXT, attendees TEXT, due TEXT, status TEXT)"
    )
    c.executemany("INSERT INTO calls VALUES (?,?,?,?,?,?)", calls)
    c.commit()
    c.close()
    interazioni = [
        {
            "id": "crm-calls",
            "connection": "crm",
            "intake": "interactions",
            "query": "SELECT id, at, subject, attendees, due, status FROM calls",
            "columns": {
                "ts": "at",
                "title": "subject",
                "participants": "attendees",
                "due": "due",
                "status": "status",
            },
            "kind": "meeting",
            "owner_role": "attendee",
            "key": "id",
        }
    ]
    return {
        "connections": {"crm": {"engine": "sqlite", "path": str(db)}},
        "sources": [
            {
                "id": "crm-people",
                "connection": "crm",
                "intake": "contacts",
                "query": "SELECT pid, name, email, phone, updated FROM people",
                "columns": {
                    "name": "name",
                    "email": "email",
                    "phone": "phone",
                    "last_seen": "updated",
                },
                "key": "pid",
                "cursor": "updated",
            }
        ]
        + (interazioni if calls else []),
    }


def _db_l0_l1(tmp: Path, config: dict) -> None:
    _ok(tmp, config, [TOOLS / "databases" / "db-l0-download.py"], "db L0")
    _ok(tmp, config, [TOOLS / "databases" / "db-l1-enrich.py"], "db L1")


_RAFA_CARD = (
    "BEGIN:VCARD\nVERSION:3.0\nN:Ortiz;Rafa;;;\nFN:Rafa Ortiz\n"
    "EMAIL;TYPE=HOME:rafa.home@mail.example\nTEL;TYPE=CELL:07700 900853\nEND:VCARD\n"
)
_RAFA_ROW = [(1, "Rafa Ortiz", "rafa@quay.example", "+44 (0)7700 900853", "2026-11-19 09:00:00")]


def _rafa(tmp: Path) -> pd.Series:
    book = pd.read_parquet(tmp / "data" / "enriched" / "contacts-merged.parquet")
    rows = book[book["name"] == "Rafa Ortiz"]
    assert len(rows) == 1, book[["name", "email", "person_id"]]
    return rows.iloc[0]


def test_the_entity_map_is_refreshed_on_every_run(tmp_path):
    later = tmp_path / "later"
    config = {
        **_ROBIN,
        "enabled_sources": ["contacts", "databases"],
        "databases": _database(later, _RAFA_ROW),
    }
    # run 1: the database alone (work email, the phone written with "(0)")
    _db_l0_l1(later, config)
    _ingest(later, config)
    assert _rafa(later)["phone_primary"] == "+447700900853"  # stored normalised
    # run 2: the card arrives with a home email and the same number written nationally
    _address_book(later, config, _RAFA_CARD)
    _ingest(later, config)
    rafa = _rafa(later)
    assert sorted(json.loads(rafa["all_emails"])) == [
        "rafa.home@mail.example",
        "rafa@quay.example",
    ], rafa
    pid = rafa["person_id"]
    # run 3, nothing new: the same id
    _ingest(later, config)
    assert _rafa(later)["person_id"] == pid

    # the same sources in one run: the same row and the same id from the first run on
    once = tmp_path / "once"
    config1 = {**config, "databases": _database(once, _RAFA_ROW)}
    _db_l0_l1(once, config1)
    _address_book(once, config1, _RAFA_CARD)
    _ingest(once, config1)
    one = _rafa(once)
    assert one["person_id"] == pid
    assert sorted(json.loads(one["all_emails"])) == ["rafa.home@mail.example", "rafa@quay.example"]
