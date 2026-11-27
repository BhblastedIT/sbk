"""Contacts plugin: synthetic exports and a mocked People API only.

No real account, no real network (urllib's urlopen is replaced by a function that fails),
no real Keychain. The kernel step that reads the address-book slot
(tools/cross-source/xs-l1-contacts-enrich.py) runs in a subprocess on a temporary data root.
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import subprocess
import sys
import urllib.request
from email.message import Message
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
CT = ROOT / "tools" / "contacts"
sys.path.insert(0, str(CT))

import ct_book  # noqa: E402
import ct_google  # noqa: E402
import google_oauth  # noqa: E402

import sbk_config  # noqa: E402


def _load(name: str, file: str):
    spec = importlib.util.spec_from_file_location(name, CT / file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


IMPORT = _load("ct_l0_import", "ct-l0-import.py")
DOWNLOAD = _load("ct_l0_download", "ct-l0-download.py")
AUTH = _load("ct_l0_auth", "ct-l0-auth.py")
L1 = _load("ct_l1_enrich", "ct-l1-enrich.py")

# --------------------------------------------------------------------------- sample exports

VCF_30_APPLE = (
    "BEGIN:VCARD\r\n"
    "VERSION:3.0\r\n"
    "PRODID:-//Apple Inc.//macOS//EN\r\n"
    "N:Conti;Mia;Rosa;;\r\n"
    "FN:Mia Conti\r\n"
    "ORG:Fabrikam\\, Inc.;Sales\r\n"
    "TITLE:Head of Sales\r\n"
    "EMAIL;type=INTERNET;type=WORK:mia@fabrikam.example\r\n"
    "item1.EMAIL;type=INTERNET;type=pref:mia.conti@personal.example\r\n"
    "item1.X-ABLabel:_$!<Other>!$_\r\n"
    "TEL;type=CELL;type=VOICE;type=pref:+44 7700 900001\r\n"
    "TEL;type=WORK;type=VOICE:+44 20 7946\r\n"
    " 0002\r\n"
    "TEL;type=WORK;type=FAX:+44 20 7946 0009\r\n"
    "BDAY;X-APPLE-OMIT-YEAR=1604:1604-04-15\r\n"
    "PHOTO;ENCODING=b;TYPE=JPEG:/9j/4AAQSkZJRgABAQAAAQABAAD\r\n"
    " /2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDA\r\n"
    "NOTE:Met at a fair\\nsecond line\r\n"
    "REV:2026-10-01T10:00:00Z\r\n"
    "UID:apple-uid-1\r\n"
    "END:VCARD\r\n"
    "BEGIN:VCARD\r\n"
    "VERSION:3.0\r\n"
    "N:;;;;\r\n"
    "FN:Northwind Traders\r\n"
    "ORG:Northwind Traders;\r\n"
    "TEL;type=MAIN:+1 555 0100\r\n"
    "X-ABShowAs:COMPANY\r\n"
    "END:VCARD\r\n"
)

VCF_40 = (
    "BEGIN:VCARD\n"
    "VERSION:4.0\n"
    "FN:Lee Park\n"
    "N:Park;Lee;;;\n"
    "EMAIL;TYPE=home:lee@home.example\n"
    "EMAIL;PREF=1;TYPE=work:lee@contoso.example\n"
    'TEL;VALUE=uri;TYPE="voice,cell":tel:+1-555-555-0142;ext=12\n'
    "BDAY:--0229\n"
    "UID:urn:uuid:4fbe8971-0bc3-424c-9c26-36c3e1eff6b1\n"
    "END:VCARD\n"
    "BEGIN:VCARD\n"
    "VERSION:4.0\n"
    "FN:Ana Ruiz\n"
    "BDAY:19850412\n"
    "TEL:+44 7700 900003\n"
    "BDAY;VALUE=text:circa 1800\n"
    "END:VCARD\n"
)

# vCard 2.1 as Outlook desktop writes it: quoted-printable with a soft line break.
VCF_21_OUTLOOK = (
    b"BEGIN:VCARD\r\n"
    b"VERSION:2.1\r\n"
    b"N;CHARSET=utf-8;ENCODING=QUOTED-PRINTABLE:M=C3=BCller;J=C3=B6rg\r\n"
    b"FN;CHARSET=utf-8;ENCODING=QUOTED-PRINTABLE:J=C3=B6rg M=C3=BC=\r\n"
    b"ller\r\n"
    b"ORG:Contoso Ltd\r\n"
    b"TEL;CELL;PREF:+44 7700 900004\r\n"
    b"TEL;WORK;VOICE:+44 20 7946 0005\r\n"
    b"EMAIL;PREF;INTERNET:joerg@contoso.example\r\n"
    b"BDAY:1979-02-31\r\n"
    b"END:VCARD\r\n"
)

CSV_GOOGLE = (
    "First Name,Middle Name,Last Name,Organization Name,Organization Title,Birthday,"
    "E-mail 1 - Label,E-mail 1 - Value,E-mail 2 - Value,Phone 1 - Label,Phone 1 - Value\n"
    "Sam,,Demo,Tailspin,CTO,1990-07-01,* Work,sam@tailspin.example ::: sam2@tailspin.example,,"
    "Mobile,+44 7700 900001\n"
    "Kim,,Example,,,--12-24,,kim@example.example,,,\n"
)

CSV_OUTLOOK = (
    "﻿First Name,Middle Name,Last Name,Title,Suffix,Company,Job Title,Business Phone,"
    "Business Fax,Mobile Phone,E-mail Address,E-mail Display Name,E-mail 2 Address,Birthday\n"
    "Robin,,Sample,Dr.,,Woodgrove,Analyst,+1 555 0111,+1 555 0199,+1 555 0112,"
    "robin@woodgrove.example,Robin Sample (robin@woodgrove.example),,4/15/1985\n"
)


# --------------------------------------------------------------------------- fixtures


def _no_network(*a, **k):
    raise AssertionError("real network used in a test")


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen", _no_network)
    # ct_google did `from urllib.request import urlopen`: its own name must be patched too
    monkeypatch.setattr(ct_google, "urlopen", _no_network)
    monkeypatch.setattr(sbk_config, "DATA_ROOT", tmp_path)
    monkeypatch.setattr(sbk_config, "_USER_CFG", {})
    monkeypatch.setattr(
        ct_book, "iphone_json_paths", lambda: [tmp_path / "contacts" / "iphone-contacts.json"]
    )
    monkeypatch.setattr(sbk_config, "mark_last_run", lambda s: None)
    vault: dict = {}
    monkeypatch.setattr(ct_google, "get_secret", lambda s, a: vault.get((s, a)))
    monkeypatch.setattr(ct_google, "set_secret", lambda s, a, v: vault.__setitem__((s, a), v))
    monkeypatch.setattr(google_oauth, "client_id_secret", lambda: ("cid.example", "csec-x"))
    monkeypatch.delenv("SBK_GCONTACTS_TOKEN_PERSONAL", raising=False)
    vault[(ct_google.KEYCHAIN_SERVICE, "personal")] = "RT_START"
    return tmp_path, vault


def _write(tmp: Path, name: str, data) -> Path:
    p = tmp / "exports" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, bytes):
        p.write_bytes(data)
    else:
        p.write_text(data, encoding="utf-8", newline="")
    return p


# --------------------------------------------------------------------------- vCard / CSV parsing


def _by_name(contacts):
    return {c["full_name"]: c for c in contacts}


def test_vcard_30_apple_export():
    st: dict = {}
    got = _by_name(ct_book.iter_vcards(io.BytesIO(VCF_30_APPLE.encode()), st))
    assert st["cards"] == 2
    mia = got["Mia Conti"]
    assert (mia["first_name"], mia["middle_name"], mia["last_name"]) == ("Mia", "Rosa", "Conti")
    assert mia["organization"] == "Fabrikam, Inc." and mia["title"] == "Head of Sales"
    # TYPE=pref first, then file order; the folded line is joined; fax left out
    assert mia["emails"] == ["mia.conti@personal.example", "mia@fabrikam.example"]
    assert mia["phones"] == ["+44 7700 900001", "+44 20 79460002"]
    assert mia["birthday"] == "--04-15"  # X-APPLE-OMIT-YEAR: year unknown
    assert mia["uid"] == "apple-uid-1" and mia["last_updated"] == "2026-10-01T10:00:00Z"
    company = got["Northwind Traders"]
    assert company["organization"] == "Northwind Traders" and company["phones"] == ["+1 555 0100"]


def test_vcard_40_pref_uri_and_birthdays():
    st: dict = {}
    got = _by_name(ct_book.iter_vcards(io.BytesIO(VCF_40.encode()), st))
    lee = got["Lee Park"]
    assert lee["emails"] == ["lee@contoso.example", "lee@home.example"]  # PREF=1 first
    assert lee["phones"] == ["+1-555-555-0142"]  # tel: URI, extension dropped
    assert lee["birthday"] == "--02-29"
    assert got["Ana Ruiz"]["birthday"] == "1985-04-12"
    assert st["birthdays_unparsed"] == 1  # VALUE=text


def test_vcard_21_quoted_printable():
    st: dict = {}
    (c,) = list(ct_book.iter_vcards(io.BytesIO(VCF_21_OUTLOOK), st))
    assert c["full_name"] == "Jörg Müller" and c["last_name"] == "Müller"
    assert c["phones"] == ["+44 7700 900004", "+44 20 7946 0005"]
    assert c["emails"] == ["joerg@contoso.example"]
    assert c["birthday"] == "" and st["birthdays_unparsed"] == 1  # 31 February


def test_birthday_forms():
    assert ct_book.parse_birthday("1996-04-15") == "1996-04-15"
    assert ct_book.parse_birthday("19531015T231000Z") == "1953-10-15"
    assert ct_book.parse_birthday("--0415") == "--04-15"
    assert ct_book.parse_birthday("---15") == ""
    assert ct_book.parse_birthday("2023-02-29") == ""


def test_csv_google_and_outlook(tmp_path):
    g = ct_book.read_csv_file(_write(tmp_path, "google.csv", CSV_GOOGLE))
    sam = _by_name(ct_book.contact_row(c, "t") for c in g)["Sam Demo"]
    assert sam["organization"] == "Tailspin" and sam["title"] == "CTO"
    assert sam["all_emails"] == "sam@tailspin.example; sam2@tailspin.example"
    assert sam["primary_phone"] == "+44 7700 900001" and sam["birthday"] == "1990-07-01"
    st: dict = {}
    o = ct_book.read_csv_file(_write(tmp_path, "outlook.csv", CSV_OUTLOOK), st)
    r = ct_book.contact_row(o[0], "t")
    assert r["full_name"] == "Robin Sample" and r["title"] == "Analyst"  # not "Dr."
    assert r["all_phones"] == "+1 555 0111; +1 555 0112"  # fax and display name left out
    assert r["primary_email"] == "robin@woodgrove.example"
    assert r["birthday"] == "" and st["birthdays_unparsed"] == 1  # locale-dependent date


def test_csv_without_contact_columns_is_refused(tmp_path):
    with pytest.raises(ct_book.ContactsError, match="not a contacts CSV"):
        ct_book.read_csv_file(_write(tmp_path, "x.csv", "a,b\n1,2\n"))


# --------------------------------------------------------------------------- import (L0)


def test_import_copies_keeps_previous_and_skips_identical(env):
    tmp, _ = env
    vcf = _write(tmp, "contacts.vcf", VCF_30_APPLE)
    s = IMPORT.run_import([vcf], "phone")
    assert s["contacts_parsed"] == 2 and not s["unchanged"]
    dest = tmp / "contacts" / "raw" / "imports" / "phone"
    assert (dest / "contacts.vcf").is_file()
    assert oct((dest / "contacts.vcf").stat().st_mode & 0o777) == "0o600"
    assert IMPORT.run_import([vcf], "phone")["unchanged"] is True
    vcf.write_text(VCF_40, encoding="utf-8")
    IMPORT.run_import([vcf], "phone")
    assert (
        (dest / "previous" / "contacts.vcf").read_bytes().startswith(b"BEGIN:VCARD\r\nVERSION:3.0")
    )
    assert (dest / "contacts.vcf").read_bytes().startswith(b"BEGIN:VCARD\nVERSION:4.0")
    summary = json.loads((tmp / "contacts" / "download-summary.json").read_text())
    assert summary["inputs"]["import:phone"]["contacts_parsed"] == 2


def test_import_with_no_contacts_replaces_nothing(env):
    tmp, _ = env
    IMPORT.run_import([_write(tmp, "a.vcf", VCF_40)], "phone")
    with pytest.raises(ct_book.ContactsError, match="no contact found"):
        IMPORT.run_import([_write(tmp, "b.vcf", "BEGIN:VCARD\nEND:VCARD\n")], "phone")
    assert (tmp / "contacts" / "raw" / "imports" / "phone" / "a.vcf").is_file()


def test_import_folder_of_outlook_vcards(env):
    tmp, _ = env
    _write(tmp, "outlook/one.vcf", VCF_21_OUTLOOK)
    _write(tmp, "outlook/two.vcf", VCF_40)
    s = IMPORT.run_import([tmp / "exports" / "outlook"], "outlook")
    assert s["files"] == 2 and s["contacts_parsed"] == 3


# --------------------------------------------------------------------------- People API (mocked)


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def _http_error(url, code, body, headers=None):
    msg = Message()
    for k, v in (headers or {}).items():
        msg[k] = v
    return HTTPError(url, code, "err", msg, io.BytesIO(json.dumps(body).encode()))


def _person(rn, name, email="", phone="", deleted=False, prev=None, **extra):
    p = {
        "resourceName": rn,
        "metadata": {
            "sources": [{"type": "CONTACT", "id": rn[7:], "updateTime": "2026-11-01T00:00:00Z"}],
        },
        "names": [
            {"displayName": name, "givenName": name.split()[0], "familyName": name.split()[-1]}
        ],
    }
    if email:
        p["emailAddresses"] = [{"value": email, "metadata": {"primary": True}}]
    if phone:
        p["phoneNumbers"] = [{"value": phone, "canonicalForm": phone.replace(" ", "")}]
    if deleted:
        p["metadata"]["deleted"] = True
    if prev:
        p["metadata"]["previousResourceNames"] = prev
    p.update(extra)
    return p


class FakeGoogle:
    """Answers oauth2.googleapis.com/token and people.googleapis.com connections."""

    def __init__(self):
        self.calls: list[dict] = []
        self.token_forms: list[dict] = []
        self.round = 1
        self.expired_once = False
        self.throttle_once = False
        self.disabled = False
        self.invalid_grant = False

    def __call__(self, req, timeout):
        url = req.full_url
        if url == ct_google.TOKEN_URL:
            form = {k: v[0] for k, v in parse_qs(req.data.decode()).items()}
            self.token_forms.append(form)
            if self.invalid_grant:
                raise _http_error(url, 400, {"error": "invalid_grant"})
            return _Resp(
                json.dumps(
                    {"access_token": "AT1", "expires_in": 3599, "scope": ct_google.SCOPES[0]}
                ).encode()
            )
        assert url.startswith(ct_google.API_URL), url
        q = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
        self.calls.append({"q": q, "auth": req.get_header("Authorization")})
        if self.disabled:
            raise _http_error(
                url,
                403,
                {
                    "error": {
                        "code": 403,
                        "status": "PERMISSION_DENIED",
                        "details": [{"reason": "SERVICE_DISABLED"}],
                    }
                },
            )
        if self.throttle_once:
            self.throttle_once = False
            raise _http_error(
                url, 429, {"error": {"status": "RESOURCE_EXHAUSTED"}}, {"Retry-After": "3"}
            )
        if "syncToken" in q and self.expired_once:
            self.expired_once = False
            raise _http_error(
                url,
                400,
                {
                    "error": {
                        "status": "FAILED_PRECONDITION",
                        "details": [{"reason": "EXPIRED_SYNC_TOKEN"}],
                    }
                },
            )
        if "syncToken" in q:  # round 2: one changed (and renamed), one deleted, one new
            body = {
                "connections": [
                    _person("people/c9", "Mia Conti", "mia@new.example", prev=["people/c1"]),
                    _person("people/c2", "Lee Park", deleted=True),
                    _person("people/c4", "Kai Demo", phone="+1 555 0104"),
                ],
                "nextSyncToken": "SYNC2",
                "totalItems": 3,
            }
        elif q.get("pageToken") == "P2":
            body = {
                "connections": [
                    _person(
                        "people/c3",
                        "Ana Ruiz",
                        "ana@ruiz.example",
                        birthdays=[{"date": {"year": 0, "month": 4, "day": 12}}],
                        organizations=[{"name": "Litware", "title": "CFO"}],
                    )
                ],
                "nextSyncToken": "SYNC1",
                "totalItems": 3,
            }
        else:
            body = {
                "connections": [
                    _person("people/c1", "Mia Conti", "mia@fabrikam.example", "+44 7700 900001"),
                    _person("people/c2", "Lee Park", "lee@contoso.example"),
                ],
                "nextPageToken": "P2",
                "totalItems": 3,
            }
        return _Resp(json.dumps(body).encode())


def _sleeps():
    waits: list[float] = []
    return waits, waits.append


def test_scope_is_read_only_contacts():
    assert ct_google.SCOPES == ["https://www.googleapis.com/auth/contacts.readonly"]
    assert ct_google.READ_SOURCES == "READ_SOURCE_TYPE_CONTACT"


def test_full_then_incremental_download(env):
    tmp, vault = env
    fake = FakeGoogle()
    waits, sleep = _sleeps()
    s = DOWNLOAD.run_one("personal", opener=fake, sleep=sleep)
    assert s["mode"] == "full" and s["contacts_stored"] == 3 and s["sync_token_saved"]
    first = fake.calls[0]
    assert first["auth"] == "Bearer AT1"
    assert first["q"]["personFields"] == ct_google.PERSON_FIELDS
    assert first["q"]["sources"] == "READ_SOURCE_TYPE_CONTACT"
    assert first["q"]["requestSyncToken"] == "true" and first["q"]["pageSize"] == "1000"
    assert fake.token_forms[0]["refresh_token"] == "RT_START"
    assert fake.token_forms[0]["client_id"] == "cid.example"
    gdir = tmp / "contacts" / "raw" / "google" / "personal"
    assert json.loads((gdir / "state.json").read_text())["sync_token"] == "SYNC1"

    s2 = DOWNLOAD.run_one("personal", opener=fake, sleep=sleep)
    assert s2["mode"] == "incremental"
    # c1 renamed to c9 counts as changed, c4 is new, c2 deleted
    assert (s2["added"], s2["changed"], s2["deleted"]) == (1, 1, 1)
    people = json.loads((gdir / "people.json").read_text())
    assert set(people) == {"people/c3", "people/c4", "people/c9"}  # c1 renamed to c9, c2 gone
    sync_calls = [c for c in fake.calls if "syncToken" in c["q"]]
    assert sync_calls[0]["q"]["syncToken"] == "SYNC1"
    # same parameters as the first call, as Google requires
    assert sync_calls[0]["q"]["personFields"] == first["q"]["personFields"]
    blob = (gdir / "state.json").read_text() + (
        tmp / "contacts" / "download-summary.json"
    ).read_text()
    assert "RT_START" not in blob and "AT1" not in blob


def test_expired_sync_token_falls_back_to_full(env):
    tmp, _ = env
    fake = FakeGoogle()
    DOWNLOAD.run_one("personal", opener=fake, sleep=lambda s: None)
    fake.expired_once = True
    s = DOWNLOAD.run_one("personal", opener=fake, sleep=lambda s: None)
    assert s["mode"] == "full (sync token expired)" and s["contacts_stored"] == 3


def test_429_waits_retry_after(env):
    fake = FakeGoogle()
    fake.throttle_once = True
    waits, sleep = _sleeps()
    s = DOWNLOAD.run_one("personal", opener=fake, sleep=sleep)
    assert s["retries"] == 1 and 3.0 in waits


def test_disabled_api_and_revoked_login_give_one_clear_error(env):
    fake = FakeGoogle()
    fake.disabled = True
    with pytest.raises(ct_book.ContactsError, match="People API is not enabled"):
        DOWNLOAD.run_one("personal", opener=fake, sleep=lambda s: None)
    fake = FakeGoogle()
    fake.invalid_grant = True
    with pytest.raises(ct_book.ContactsError, match="invalid_grant"):
        DOWNLOAD.run_one("personal", opener=fake, sleep=lambda s: None)


def test_login_from_env_when_no_keychain(env, monkeypatch):
    _tmp, vault = env
    vault.clear()
    with pytest.raises(ct_book.ContactsError, match="SBK_GCONTACTS_TOKEN_PERSONAL"):
        ct_google.load_login("personal")
    monkeypatch.setenv("SBK_GCONTACTS_TOKEN_PERSONAL", json.dumps({"refresh_token": "RT_ENV"}))
    assert ct_google.load_login("personal")[0] == "RT_ENV"


def test_person_mapping():
    c = ct_google.person_to_contact(
        _person(
            "people/c3",
            "Ana Ruiz",
            "ana@ruiz.example",
            "+44 7700 900003",
            birthdays=[{"date": {"year": 0, "month": 4, "day": 12}}],
            organizations=[{"name": "Litware", "title": "CFO"}],
        )
    )
    r = ct_book.contact_row(c, "contacts:google:personal")
    assert r["primary_phone"] == "+447700900003"  # canonicalForm (E.164)
    assert (r["organization"], r["title"], r["birthday"]) == ("Litware", "CFO", "--04-12")
    assert r["source_id"] == "people/c3" and r["last_updated"] == "2026-11-01T00:00:00Z"


def test_auth_check_and_login_store(env, capsys):
    _tmp, vault = env
    fake = FakeGoogle()
    called = []
    assert AUTH.cli(["--account", "personal"], opener=fake, login=lambda: called.append(1)) == 0
    assert called == [1]
    assert "3 contacts readable" in capsys.readouterr().out
    assert fake.calls[-1]["q"]["pageSize"] == "1"


# --------------------------------------------------------------------------- L1 and the slot


def _kernel_env(tmp: Path) -> dict:
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


def test_l1_keeps_other_rows_dedupes_and_seeds_iphone_json(env, monkeypatch, capsys):
    tmp, _ = env
    IMPORT.run_import([_write(tmp, "contacts.vcf", VCF_30_APPLE)], "phone")
    IMPORT.run_import([_write(tmp, "again.vcf", VCF_30_APPLE)], "copy")  # same people twice
    DOWNLOAD.run_one("personal", opener=FakeGoogle(), sleep=lambda s: None)
    jp = tmp / "contacts" / "iphone-contacts.json"
    jp.write_text(json.dumps({"contacts": [{"name": "Pat Seed", "phones": ["+1 555 0177"]}]}))
    ms = pd.DataFrame(
        [
            {
                "full_name": "Bo Outlook",
                "primary_email": "bo@example.example",
                "source": "microsoft365:x",
            }
        ]
    )
    (tmp / "contacts").mkdir(exist_ok=True)
    ms.to_parquet(tmp / "contacts" / "contacts.parquet")

    assert L1.cli(["--no-kernel"]) == 0
    ct = pd.read_parquet(tmp / "contacts" / "contacts.parquet")
    assert not ct.isna().any().any()
    src = dict(zip(ct["full_name"] + "|" + ct["source"], ct["source"], strict=False))
    assert "Bo Outlook|microsoft365:x" in src and "Pat Seed|iphone-contacts-json" in src
    mine = ct[ct["source"].str.startswith("contacts:")]
    # the second import of the same file adds nothing; Google's Mia has another e-mail, so stays
    assert sorted(mine["full_name"]) == [
        "Ana Ruiz",
        "Lee Park",
        "Mia Conti",
        "Mia Conti",
        "Northwind Traders",
    ]
    imported = ct[ct["source"].str.startswith("contacts:import:")]
    # one of the two identical imports is kept (labels are read in name order: copy, phone)
    assert set(imported["source"]) == {"contacts:import:copy"}
    mia = imported[imported["full_name"] == "Mia Conti"].iloc[0]
    assert mia["all_phones"] == "+44 7700 900001; +44 20 79460002"
    assert mia["birthday"] == "--04-15" and mia["organization"] == "Fabrikam, Inc."

    # a second run replaces only this plugin's rows
    assert L1.cli(["--no-kernel"]) == 0
    assert len(pd.read_parquet(tmp / "contacts" / "contacts.parquet")) == len(ct)


def test_slot_made_by_you_is_not_seeded(env):
    tmp, _ = env
    (tmp / "contacts").mkdir()
    pd.DataFrame([{"full_name": "Own Row", "primary_phone": "+1 555 0101"}]).to_parquet(
        tmp / "contacts" / "contacts.parquet"
    )
    (tmp / "contacts" / "iphone-contacts.json").write_text(
        json.dumps({"contacts": [{"name": "X Y"}]})
    )
    IMPORT.run_import([_write(tmp, "a.vcf", VCF_40)], "phone")
    assert L1.cli(["--no-kernel"]) == 0
    ct = pd.read_parquet(tmp / "contacts" / "contacts.parquet")
    assert "Own Row" in set(ct["full_name"]) and "X Y" not in set(ct["full_name"])


def test_kernel_contacts_step_reads_the_slot(env):
    tmp, _ = env
    IMPORT.run_import([_write(tmp, "contacts.vcf", VCF_30_APPLE)], "phone")
    IMPORT.run_import([_write(tmp, "o.vcf", VCF_21_OUTLOOK)], "outlook")
    assert L1.cli(["--no-kernel"]) == 0
    r = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "cross-source" / "xs-l1-contacts-enrich.py")],
        env=_kernel_env(tmp),
        capture_output=True,
        text=True,
        timeout=120,
        cwd=str(ROOT),
    )
    assert r.returncode == 0, r.stderr[-2000:]
    out = pd.read_parquet(tmp / "contacts" / "processed" / "contacts-iphone.parquet")
    by = out.set_index("name")
    assert set(by.index) == {"Mia Conti", "Northwind Traders", "Jörg Müller"}
    assert by.loc["Mia Conti", "email"] == "mia.conti@personal.example"
    assert by.loc["Mia Conti", "organization"] == "Fabrikam, Inc."
    assert len(by.loc["Mia Conti", "phone_numbers"]) == 2
    assert by.loc["Jörg Müller", "phone_primary"]


def test_import_then_l1_cli_runs_the_kernel_step(tmp_path):
    """The two commands a user types, as subprocesses: import, then L1 with the kernel step."""
    env = _kernel_env(tmp_path)
    vcf = _write(tmp_path, "contacts.vcf", VCF_40)
    r = subprocess.run(
        [sys.executable, str(CT / "ct-l0-import.py"), str(vcf), "--label", "phone"],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r.returncode == 0, r.stderr[-2000:]
    assert "2 contacts" in r.stdout
    r = subprocess.run(
        [sys.executable, str(CT / "ct-l1-enrich.py")],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        cwd=str(ROOT),
    )
    assert r.returncode == 0, r.stderr[-2000:]
    out = pd.read_parquet(tmp_path / "contacts" / "processed" / "contacts-iphone.parquet")
    assert set(out["name"]) == {"Lee Park", "Ana Ruiz"}
    assert set(out.set_index("name").loc["Lee Park", "phone_numbers"]) and (
        out.set_index("name").loc["Lee Park", "email"] == "lee@contoso.example"
    )


# --------------------------------------------------------------------------- CLI


@pytest.mark.parametrize(
    "script", ["ct-l0-import.py", "ct-l0-auth.py", "ct-l0-download.py", "ct-l1-enrich.py"]
)
def test_cli_help_and_no_credentials(tmp_path, script):
    env = _kernel_env(tmp_path)
    r = subprocess.run(
        [sys.executable, str(CT / script), "--help"],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r.returncode == 0 and "Traceback" not in r.stderr and "usage" in r.stdout
    argv = {
        "ct-l0-import.py": [],
        "ct-l0-auth.py": ["--check", "--account", "personal"],
        "ct-l0-download.py": ["--account", "personal"],
        "ct-l1-enrich.py": [],
    }[script]
    r = subprocess.run(
        [sys.executable, str(CT / script), *argv],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r.returncode in (1, 2) and "Traceback" not in r.stderr
    lines = [ln for ln in r.stderr.strip().splitlines() if ln]
    assert len(lines) == 1 and lines[0].startswith("contacts:"), r.stderr
    if script != "ct-l1-enrich.py" and script != "ct-l0-import.py":
        assert "SBK_GCONTACTS_TOKEN_PERSONAL" in lines[0]


def test_download_all_with_no_accounts_is_a_quiet_no_op(env, capsys):
    assert DOWNLOAD.cli(["--all"]) == 0
    assert "nothing to download" in capsys.readouterr().out


# --------------------------------------------------------------------------- reviewer cases


def test_network_guard_reaches_ct_google(env):
    """Without an injected opener, ct_google must hit the test's no-network guard."""
    with pytest.raises(AssertionError, match="real network"):
        ct_google._default_opener(urllib.request.Request(ct_google.API_URL), 1)


def test_phonetic_name_column_is_not_a_phone(tmp_path):
    csv_text = (
        "First Name,Phonetic First Name,Last Name,E-mail 1 - Value,Phone 1 - Value\n"
        "Yui,Yu-i,Demo,yui@demo.example,+44 7700 900006\n"
    )
    (c,) = ct_book.read_csv_file(_write(tmp_path, "g.csv", csv_text))
    assert c["phones"] == ["+44 7700 900006"]


def test_csv_the_csv_module_rejects_is_one_clear_error(tmp_path):
    # a field over csv.field_size_limit() (131072 characters by default) raises csv.Error
    big = '"' + "x" * 200_000 + '"'
    p = _write(tmp_path, "bad.csv", f"First Name,E-mail Address\n{big},a@b.example\n")
    with pytest.raises(ct_book.ContactsError, match="not a readable CSV"):
        ct_book.read_csv_file(p)


def test_vcard_with_byte_order_marks(tmp_path):
    one = "BEGIN:VCARD\r\nVERSION:3.0\r\nFN:Ana Demo\r\nTEL:+1 555 0100\r\nEND:VCARD\r\n"
    two = one + one.replace("Ana Demo", "Ben Demo")
    assert (
        len(ct_book.read_vcard_file(_write(tmp_path, "bom8.vcf", b"\xef\xbb\xbf" + two.encode())))
        == 2
    )
    got = ct_book.read_vcard_file(_write(tmp_path, "u16.vcf", two.encode("utf-16")))
    assert [c["full_name"] for c in got] == ["Ana Demo", "Ben Demo"]


def test_missing_people_store_forces_a_full_read(env):
    tmp, _ = env
    fake = FakeGoogle()
    DOWNLOAD.run_one("personal", opener=fake, sleep=lambda s: None)
    gdir = tmp / "contacts" / "raw" / "google" / "personal"
    (gdir / "people.json").unlink()
    s = DOWNLOAD.run_one("personal", opener=fake, sleep=lambda s: None)
    assert s["mode"] == "full (stored contacts missing)" and s["contacts_stored"] == 3
    assert "syncToken" not in fake.calls[-1]["q"]


def test_changed_request_fields_force_a_full_read(env):
    tmp, _ = env
    fake = FakeGoogle()
    DOWNLOAD.run_one("personal", opener=fake, sleep=lambda s: None)
    sp = tmp / "contacts" / "raw" / "google" / "personal" / "state.json"
    st = json.loads(sp.read_text())
    st["person_fields"] = "names"
    sp.write_text(json.dumps(st))
    s = DOWNLOAD.run_one("personal", opener=fake, sleep=lambda s: None)
    assert s["mode"] == "full (request fields changed)" and s["contacts_stored"] == 3


def test_reimport_after_the_copy_was_removed_copies_again(env):
    tmp, _ = env
    vcf = _write(tmp, "contacts.vcf", VCF_40)
    IMPORT.run_import([vcf], "phone")
    copy = tmp / "contacts" / "raw" / "imports" / "phone" / "contacts.vcf"
    copy.unlink()
    assert IMPORT.run_import([vcf], "phone")["unchanged"] is False
    assert copy.is_file()


def test_slot_you_made_with_date_columns_still_writes(env):
    tmp, _ = env
    (tmp / "contacts").mkdir()
    pd.DataFrame(
        [
            {
                "full_name": "Own Row",
                "birthday": pd.Timestamp("1990-01-02"),
                "last_updated": pd.Timestamp("2026-01-01"),
                "score": 3,
            }
        ]
    ).to_parquet(tmp / "contacts" / "contacts.parquet")
    IMPORT.run_import([_write(tmp, "a.vcf", VCF_40)], "phone")
    assert L1.cli(["--no-kernel"]) == 0
    ct = pd.read_parquet(tmp / "contacts" / "contacts.parquet")
    own = ct[ct["full_name"] == "Own Row"].iloc[0]
    assert own["birthday"].startswith("1990-01-02") and int(own["score"]) == 3
    assert not ct[list(ct_book.SLOT_COLUMNS)].isna().any().any()


def test_auth_login_in_container_mode_is_one_clear_line(tmp_path):
    r = subprocess.run(
        [sys.executable, str(CT / "ct-l0-auth.py"), "--account", "personal"],
        env=_kernel_env(tmp_path),
        capture_output=True,
        text=True,
        timeout=60,
    )
    lines = [ln for ln in r.stderr.strip().splitlines() if ln]
    assert r.returncode == 2 and len(lines) == 1, r.stderr
    assert "outside the container" in lines[0] and "SBK_GCONTACTS_TOKEN_PERSONAL" in lines[0]
