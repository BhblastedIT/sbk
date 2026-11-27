"""A first install with ONE source of any kind, and people who come with a phone number only.

Each case imports demo data the way the guide says, runs the source's L1, then the stages after
it that read the merged book (merge, entity map, Knowledge Extract, attachment scan, decay), twice:

- Telegram only, WhatsApp only (iPhone and Android export layouts) and the address book only
  give person entities: people who come with a phone and no email become contacts keyed by
  their normalised phone (a WhatsApp one-to-one chat partner saved by name only, by that name).
- LinkedIn only enriches people and starts nobody: the merge says so and writes no book, and
  the runner treats a missing or 0-row book alike (the stages after the merge have nobody to read).
- databases only still works as before.
- the same phone on an email-keyed person and on a phone-only one is one person, with no
  duplicate across sources or across runs.
- every stage after the merge closes with exit 0 when the book has 0 rows.

Every check runs in a subprocess with its own SBK_DATA_ROOT, HOME and config. Demo data only, no
network, no model key, no Keychain. The real --ingest of each case was run by hand on an empty
data root as well (the line never stops); these tests keep the stages it depends on honest.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import textwrap
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
CS = ROOT / "tools" / "cross-source"
OWNER = {
    "owner": "Casey Demo",
    "own_names": ["casey demo", "casey"],
    "own_emails": ["casey@example.com"],
}


def _env(tmp: Path, config: dict) -> dict:
    cfg = tmp / "sbk.config.json"
    cfg.write_text(json.dumps(config), encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("SBK_", "ANTHROPIC_"))}
    (tmp / "home").mkdir(exist_ok=True)
    env.update(
        HOME=str(tmp / "home"),
        SBK_DATA_ROOT=str(tmp / "data"),
        SBK_CONFIG=str(cfg),
        PYTHON_KEYRING_BACKEND="keyring.backends.fail.Keyring",
        PYTHONPATH=os.pathsep.join([str(ROOT / "tools"), str(CS)]),
    )
    return env


def _run(args: list, tmp: Path, config: dict, timeout: int = 300):
    r = subprocess.run(
        [sys.executable, *[str(a) for a in args]],
        cwd=str(ROOT),
        env=_env(tmp, config),
        capture_output=True,
        text=True,
        timeout=timeout,
        stdin=subprocess.DEVNULL,
    )
    return r


def _out(r) -> str:
    return (r.stdout or "") + (r.stderr or "")


def _ok(r, what: str) -> str:
    assert r.returncode == 0, f"{what}: exit {r.returncode}\n" + _out(r)[-3000:]
    assert "Traceback (most recent" not in _out(r), f"{what}\n" + _out(r)[-3000:]
    return _out(r)


# --------------------------------------------------------------------------- demo inputs


def _telegram(tmp: Path) -> Path:
    from datetime import UTC, datetime

    me, omar, pia = 900001, 900002, 900003

    def m(i, when, frm, fid, text):
        t = datetime.fromisoformat(when).replace(tzinfo=UTC)
        return {
            "id": i,
            "type": "message",
            "date": when,
            "date_unixtime": str(int(t.timestamp())),
            "from": frm,
            "from_id": f"user{fid}",
            "text": text,
            "text_entities": [{"type": "plain", "text": text}],
        }

    export = {
        "personal_information": {"user_id": me, "first_name": "Casey", "last_name": "Demo"},
        "contacts": {
            "list": [
                {
                    "user_id": str(omar),
                    "first_name": "Omar",
                    "last_name": "Reyes",
                    "phone_number": "+1 202 555 0177",
                    "date": "2025-05-01T10:00:00",
                },
                {
                    "user_id": str(pia),
                    "first_name": "Pia",
                    "last_name": "Holt",
                    "phone_number": "+1 202 555 0123",
                    "date": "2025-05-02T10:00:00",
                },
            ]
        },
        "chats": {
            "list": [
                {
                    "name": "Omar Reyes",
                    "type": "personal_chat",
                    "id": omar,
                    "messages": [
                        m(
                            1,
                            "2026-11-19T12:00:00",
                            "Omar Reyes",
                            omar,
                            "Thanks for the call, Casey.",
                        ),
                        m(
                            2,
                            "2026-11-19T12:05:00",
                            "Casey Demo",
                            me,
                            "I'll send you the draft tomorrow.",
                        ),
                    ],
                },
                {
                    "name": "Pia Holt",
                    "type": "personal_chat",
                    "id": pia,
                    "messages": [
                        m(
                            3,
                            "2026-11-22T17:00:00",
                            "Pia Holt",
                            pia,
                            "Are we still on for the workshop?",
                        ),
                    ],
                },
            ]
        },
    }
    d = tmp / "home" / "Downloads" / "Telegram Desktop" / "DataExport_demo"
    d.mkdir(parents=True)
    (d / "result.json").write_text(json.dumps(export), encoding="utf-8")
    return d


_LRM, _LRE, _PDF = "‎", "‪", "‬"


def _whatsapp(tmp: Path, layout: str) -> None:
    raw = tmp / "data" / "whatsapp" / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    if layout == "iphone":
        # [DD/MM/YYYY, HH:MM:SS] Name: text — a contact saved by name, two unsaved numbers
        (raw / "WhatsApp Chat - Omar Reyes.txt").write_text(
            f"{_LRM}[19/11/2026, 12:00:00] Omar Reyes: {_LRM}Messages and calls are end-to-end encrypted.\n"
            "[19/11/2026, 12:00:10] Omar Reyes: Thanks for the call, Casey.\n"
            "[19/11/2026, 12:05:00] Casey Demo: I will send you the draft tomorrow.\n",
            encoding="utf-8",
        )
        (raw / "WhatsApp Chat - +1 202 555 0188.txt").write_text(
            f"[24/11/2026, 10:00:00] {_LRE}+1 202 555 0188{_PDF}: Hi Casey, Rui from the meetup.\n"
            "[24/11/2026, 10:05:00] Casey Demo: Nice to hear from you, Rui.\n",
            encoding="utf-8",
        )
        (raw / "WhatsApp Chat - +1 202 555 0177.txt").write_text(
            f"[25/11/2026, 09:00:00] {_LRE}+1 202 555 0177{_PDF}: Omar here, from my second phone.\n"
            "[25/11/2026, 09:01:00] Casey Demo: Got it.\n",
            encoding="utf-8",
        )
    else:
        # DD/MM/YYYY, HH:MM - Name: text
        (raw / "WhatsApp Chat with Pia Holt.txt").write_text(
            "22/11/2026, 17:00 - Messages and calls are end-to-end encrypted.\n"
            "22/11/2026, 17:00 - Pia Holt: Are we still on for the workshop?\n"
            "22/11/2026, 17:02 - Casey Demo: Yes, I will confirm the room by Friday.\n",
            encoding="utf-8",
        )
        (raw / "WhatsApp Chat with +1 202 555 0166.txt").write_text(
            "25/11/2026, 09:00 - +1 202 555 0166: Hello, Ines here, we met at the fair.\n"
            "25/11/2026, 09:03 - Casey Demo: Hi Ines, good to hear from you.\n",
            encoding="utf-8",
        )


def _vcard(tmp: Path) -> Path:
    f = tmp / "home" / "Downloads" / "contacts.vcf"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(
        "BEGIN:VCARD\nVERSION:3.0\nN:Vance;Tara;;;\nFN:Tara Vance\nORG:Northwind Demo\n"
        "EMAIL;TYPE=INTERNET:tara@northwind.example\nTEL;TYPE=CELL:+1 202 555 0141\nEND:VCARD\n"
        "BEGIN:VCARD\nVERSION:4.0\nFN:Gus Moreno\nN:Moreno;Gus;;;\nEMAIL:gus@tailspin.example\n"
        "TEL;TYPE=cell:+1 202 555 0155\nEND:VCARD\n"
        "BEGIN:VCARD\nVERSION:3.0\nN:Holt;Pia;;;\nFN:Pia Holt\nTEL;TYPE=CELL:+1 202 555 0123\nEND:VCARD\n",
        encoding="utf-8",
    )
    return f


def _linkedin(tmp: Path) -> None:
    d = tmp / "data" / "linkedin" / "raw" / "export-part1"
    d.mkdir(parents=True)
    (d / "Connections.csv").write_text(
        'Notes:\n"Some of the email addresses are missing."\n\n'
        "First Name,Last Name,URL,Email Address,Company,Position,Connected On\n"
        "Lena,Brook,https://www.linkedin.com/in/lena-brook-demo,lena@contoso.example,Contoso Demo,Engineer,14 Feb 2025\n"
        "Ken,Ito,https://www.linkedin.com/in/ken-ito-demo,,Litware Demo,Partner,02 Aug 2024\n",
        encoding="utf-8",
    )


def _database(tmp: Path, config: dict) -> None:
    db = tmp / "home" / "demo-book.sqlite"
    db.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(db)
    c.executescript(
        """
        CREATE TABLE contacts(cid INTEGER PRIMARY KEY, full_name TEXT, mail TEXT, mobile TEXT,
                              org TEXT, changed TEXT);
        INSERT INTO contacts VALUES
         (1,'Tara Vance','tara@northwind.example','+1 202 555 0141','Northwind Demo','2026-11-18 09:00:00'),
         (2,'Omar Reyes','omar@fabrikam.example','+1 202 555 0177','Fabrikam Demo','2026-11-19 09:00:00'),
         (3,'Lena Brook','lena@contoso.example',NULL,'Contoso Demo','2026-11-20 09:00:00');
        """
    )
    c.commit()
    c.close()
    config["databases"] = {
        "connections": {"book": {"engine": "sqlite", "path": str(db)}},
        "sources": [
            {
                "id": "book-people",
                "connection": "book",
                "intake": "contacts",
                "query": "SELECT cid, full_name, mail, mobile, org, changed FROM contacts",
                "columns": {
                    "name": "full_name",
                    "email": "mail",
                    "phone": "mobile",
                    "company": "org",
                    "last_seen": "changed",
                },
                "key": "cid",
            }
        ],
    }


def _import(tmp: Path, config: dict, sources: list[str]) -> None:
    """The L0 of the guide, then the L1 the runner runs for each source."""
    tools = ROOT / "tools"
    if "databases" in sources:
        _ok(_run([tools / "databases" / "db-l0-download.py"], tmp, config), "db L0")
        _ok(_run([tools / "databases" / "db-l1-enrich.py"], tmp, config), "db L1")
    if "telegram" in sources:
        export = _telegram(tmp)
        _ok(_run([tools / "telegram" / "tg-l0-import.py", export], tmp, config), "tg L0")
        _ok(_run([tools / "telegram" / "tg-l1-enrich.py"], tmp, config), "tg L1")
    if "contacts" in sources:
        vcf = _vcard(tmp)
        _ok(
            _run([tools / "contacts" / "ct-l0-import.py", vcf, "--label", "phone"], tmp, config),
            "ct L0",
        )
        _ok(_run([tools / "contacts" / "ct-l1-enrich.py"], tmp, config), "ct L1")
    if "linkedin" in sources:
        _linkedin(tmp)
        _ok(_run([tools / "linkedin" / "li-l0-import-export.py"], tmp, config), "li L0")
        _ok(_run([tools / "linkedin" / "li-l1-enrich.py"], tmp, config), "li L1")
    if "whatsapp" in sources:
        wa = tools / "whatsapp"
        _ok(_run([wa / "wa-l0l3-full.py", "--skip-analysis"], tmp, config), "wa L0")
        _ok(_run([wa / "wa-l1-enrich.py", "--incremental"], tmp, config), "wa L1")


_AFTER_MERGE = [
    ["xs-l2-entity-map-cleanup.py"],
    ["xs-l2-knowledge-extract.py", "--incremental"],
    ["xs-l2-attachment-discovery.py"],
    ["rq-01-decay-engine.py"],
    ["xs-l3-decay.py"],
]


def _chain(tmp: Path, config: dict) -> str:
    out = _ok(_run([CS / "xs-l2-merge.py"], tmp, config), "merge")
    for args in _AFTER_MERGE:
        _ok(_run([CS / args[0], *args[1:]], tmp, config), args[0])
    return out


def _book(tmp: Path) -> pd.DataFrame:
    return pd.read_parquet(tmp / "data" / "enriched" / "contacts-merged.parquet")


def _people(tmp: Path) -> dict[str, dict]:
    d = tmp / "data" / "knowledge" / "entities" / "person"
    out = {}
    for f in sorted(d.glob("*.json")) if d.exists() else []:
        e = json.loads(f.read_text(encoding="utf-8"))
        out[e["entity_id"]] = e
    return out


def _values(entity: dict, attribute: str) -> set[str]:
    return {
        str(f.get("value")) for f in entity.get("facts") or [] if f.get("attribute") == attribute
    }


def _assert_no_duplicates(tmp: Path) -> None:
    book = _book(tmp)
    names = [n for n in book["name"].astype(str) if n]
    assert len(names) == len(set(names)), book[["name", "email", "contact_key"]]
    keys = [k for k in book.get("contact_key", pd.Series(dtype=str)).fillna("").astype(str) if k]
    assert len(keys) == len(set(keys)), keys
    emails = [e for e in book["email"].fillna("").astype(str) if e]
    assert len(emails) == len(set(emails)), emails
    canon = [e.get("canonical_name") for e in _people(tmp).values()]
    assert len(canon) == len(set(canon)), canon


def _first_install(tmp: Path, sources: list[str]) -> dict:
    config = {**OWNER, "enabled_sources": sources}
    if "databases" in sources:
        _database(tmp, config)
    _import(tmp, config, sources)
    _chain(tmp, config)
    first = sorted(_people(tmp))
    _chain(tmp, config)  # the second run on the same input changes nobody
    assert sorted(_people(tmp)) == first
    return config


# --------------------------------------------------------------------------- one source each


def test_telegram_only_gives_people_keyed_by_phone(tmp_path):
    _first_install(tmp_path, ["telegram"])
    book = _book(tmp_path)
    assert set(book["contact_key"]) == {"tel:+12025550177", "tel:+12025550123"}, book
    assert set(book["name"]) == {"Omar Reyes", "Pia Holt"}
    people = {e["canonical_name"]: e for e in _people(tmp_path).values()}
    assert {"Omar Reyes", "Pia Holt"} <= set(people)
    _assert_no_duplicates(tmp_path)


@pytest.mark.parametrize("layout", ["iphone", "android"])
def test_whatsapp_only_gives_people(tmp_path, layout):
    _whatsapp(tmp_path, layout)
    _first_install(tmp_path, ["whatsapp"])
    book = _book(tmp_path).set_index("name")
    people = {e["canonical_name"]: e for e in _people(tmp_path).values()}
    if layout == "iphone":
        # the chat partner saved by name: keyed by that name; the unsaved numbers: by phone
        assert book.loc["Omar Reyes", "contact_key"] == "name:omar reyes"
        assert book.loc["+1 202 555 0188", "contact_key"] == "tel:+12025550188"
        assert book.loc["+1 202 555 0177", "contact_key"] == "tel:+12025550177"
        assert {"Omar Reyes", "+1 202 555 0188"} <= set(people)
        # the knowledge base stores the phone normalised (D38)
        assert "+12025550188" in _values(people["+1 202 555 0188"], "contact.phone")
    else:
        assert book.loc["Pia Holt", "contact_key"] == "name:pia holt"
        assert book.loc["+1 202 555 0166", "contact_key"] == "tel:+12025550166"
        assert {"Pia Holt", "+1 202 555 0166"} <= set(people)
    assert "Casey Demo" not in book.index  # you are never your own contact
    assert book["has_whatsapp"].all()
    _assert_no_duplicates(tmp_path)


def test_address_book_only_gives_people(tmp_path):
    _first_install(tmp_path, ["contacts"])
    book = _book(tmp_path).set_index("name")
    assert book.loc["Pia Holt", "contact_key"] == "tel:+12025550123"
    assert book.loc["Gus Moreno", "email"] == "gus@tailspin.example"
    assert book.loc["Tara Vance", "email"] == "tara@northwind.example"
    assert set(book["started_by"]) == {"iphone"}
    people = {e["canonical_name"]: e for e in _people(tmp_path).values()}
    assert {"Pia Holt", "Gus Moreno", "Tara Vance"} <= set(people)
    assert "gus@tailspin.example" in _values(people["Gus Moreno"], "contact.email")
    _assert_no_duplicates(tmp_path)


def test_linkedin_only_starts_nobody_and_stops_nothing(tmp_path):
    config = {**OWNER, "enabled_sources": ["linkedin"]}
    _import(tmp_path, config, ["linkedin"])
    out = _ok(_run([CS / "xs-l2-merge.py"], tmp_path, config), "merge")
    assert "Nothing to merge yet" in out and "WhatsApp, Telegram, the address book" in out, out
    assert not (tmp_path / "data" / "enriched" / "contacts-merged.parquet").exists()


def test_databases_only_still_works(tmp_path):
    _first_install(tmp_path, ["databases"])
    book = _book(tmp_path)
    assert set(book["email"]) == {
        "tara@northwind.example",
        "omar@fabrikam.example",
        "lena@contoso.example",
    }
    assert not book["contact_key"].fillna("").astype(bool).any()
    assert len(_people(tmp_path)) >= 3
    _assert_no_duplicates(tmp_path)


# --------------------------------------------------------------------------- the same person by phone


def test_same_phone_is_one_person_across_sources_and_runs(tmp_path):
    _whatsapp(tmp_path, "iphone")
    _whatsapp(tmp_path, "android")
    _first_install(tmp_path, ["databases", "telegram", "contacts", "whatsapp"])
    book = _book(tmp_path).set_index("name")
    # Omar: email-keyed in the database, phone-only in Telegram, an unsaved number and a chat
    # saved by name in WhatsApp: one row, keyed by his email
    omar = book.loc["Omar Reyes"]
    assert omar["email"] == "omar@fabrikam.example" and not omar["contact_key"]
    assert "telegram" in omar["plugin_sources"] and bool(omar["has_whatsapp"])
    assert "+1 202 555 0177" not in book.index
    # Pia: phone-only in Telegram and in the address book, saved by name in WhatsApp: one row
    pia = book.loc["Pia Holt"]
    assert pia["contact_key"] == "tel:+12025550123"
    assert (
        bool(pia["has_iphone"])
        and bool(pia["has_whatsapp"])
        and "telegram" in pia["plugin_sources"]
    )
    # Tara: the address-book card carries the database email: the same row
    assert bool(book.loc["Tara Vance", "has_iphone"])
    _assert_no_duplicates(tmp_path)
    people = {e["canonical_name"]: e for e in _people(tmp_path).values()}
    assert {"Omar Reyes", "Pia Holt", "Tara Vance", "Gus Moreno", "Lena Brook"} <= set(people)


def test_phone_country_code_from_the_config(tmp_path):
    code = """
    import importlib.util, os, sys
    import pandas as pd
    spec = importlib.util.spec_from_file_location("merge_cc", sys.argv[1])
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    from collections import defaultdict
    stats = defaultdict(lambda: {"matched": 0, "unmatched": 0, "da_verificare": 0})
    book = m.merge_contacts_phase1(None, None, pd.DataFrame([{
        "email": "ada@fabrikam.example", "name": "Ada Demo", "total_events": 2, "as_organizer": 0,
        "first_seen": "2026-01-01", "last_seen": "2026-02-01"}]), None)
    i = book.index[0]
    book.at[i, "phone_primary"] = "+44 7700 900123"
    noop = lambda get, put: put("has_whatsapp", True)
    os.environ["SBK_PHONE_CC"] = "44"
    out = m.merge_phone_contacts(book.copy(), [m._pendente("whatsapp", m._chiave_telefono("7700 900123"),
                                 "7700 900123", "Ada D", "", noop)], stats)
    assert len(out) == 1 and bool(out.iloc[0]["has_whatsapp"]), out
    os.environ["SBK_PHONE_CC"] = ""
    out = m.merge_phone_contacts(book.copy(), [m._pendente("whatsapp", m._chiave_telefono("7700 900123"),
                                 "7700 900123", "Ada D", "", noop)], stats)
    assert len(out) == 2, out  # without a country code the local number is another phone
    print("ok")
    """
    r = _run(["-c", textwrap.dedent(code), CS / "xs-l2-merge.py"], tmp_path, OWNER)
    assert r.returncode == 0 and r.stdout.strip().endswith("ok"), _out(r)[-3000:]


# --------------------------------------------------------------------------- an empty book


def test_every_stage_after_the_merge_closes_on_an_empty_book(tmp_path):
    enr = tmp_path / "data" / "enriched"
    enr.mkdir(parents=True)
    pd.DataFrame(
        {
            "email": pd.Series(dtype=str),
            "name": pd.Series(dtype=str),
            "person_id": pd.Series(dtype=str),
            "score": pd.Series(dtype=float),
            "source_count": pd.Series(dtype=int),
            "phone_primary": pd.Series(dtype=str),
            "all_emails": pd.Series(dtype=str),
            "is_automated": pd.Series(dtype=bool),
        }
    ).to_parquet(enr / "contacts-merged.parquet", index=False)
    for args in _AFTER_MERGE:
        _ok(_run([CS / args[0], *args[1:]], tmp_path, OWNER), args[0])
    assert json.loads((enr / "person-attachments-index.json").read_text()) == {}
    # asked for one person who is not there: that is still an error
    r = _run([CS / "xs-l2-attachment-discovery.py", "--person", "nobody"], tmp_path, OWNER)
    assert r.returncode == 1 and "Nobody in the merged book matches" in _out(r), _out(r)[-2000:]


def test_runner_treats_a_0_row_book_like_a_missing_one(tmp_path):
    code = """
    import importlib.util, sys
    import pandas as pd
    spec = importlib.util.spec_from_file_location("runner_t", sys.argv[1])
    m = importlib.util.module_from_spec(spec); sys.modules["runner_t"] = m; spec.loader.exec_module(m)
    p = m.ENRICHED_DIR / "contacts-merged.parquet"
    assert not m._rubrica_con_persone()
    p.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"email": pd.Series(dtype=str)}).to_parquet(p, index=False)
    assert not m._rubrica_con_persone()
    pd.DataFrame({"email": ["ada@fabrikam.example"]}).to_parquet(p, index=False)
    assert m._rubrica_con_persone()
    print("ok")
    """
    r = _run(["-c", textwrap.dedent(code), CS / "xs-pipeline-run.py"], tmp_path, OWNER)
    assert r.returncode == 0 and r.stdout.strip().endswith("ok"), _out(r)[-3000:]


def test_the_runner_gate_uses_the_row_count():
    src = (CS / "xs-pipeline-run.py").read_text(encoding="utf-8")
    i = src.index('if not _esegui("l2_merge"')
    assert "if not _rubrica_con_persone():" in src[i : i + 600]
    assert 'not (ENRICHED_DIR / "contacts-merged.parquet").exists()' not in src
