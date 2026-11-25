"""imap-caldav plugin (tools/imap-caldav/): mocked network only, no real account, no Keychain.

Checks: account config and presets, IMAP folder parsing (modified UTF-7, SPECIAL-USE), message
rows with the Gmail downloader's columns, the incremental IMAP sync (UID, UIDVALIDITY, CONDSTORE
flag changes, a message in two folders), read-only use of the server, the mail slot read by
tools/email/em-l1-enrich.py, the iCalendar reader (all-day, TZID, recurrence, overrides,
cancelled), CalDAV discovery + ctag/ETag incremental + set-aside of removed objects, the ICS link
with ETag, the calendar slot read by tools/calendar/ca-l1-extract.py, HTTP safety (https only, no
credentials to another site), the Outlook.com device code flow and refresh-token rotation, and
the scripts' --help and one-line errors without configuration or credentials.
"""

from __future__ import annotations

import imaplib
import importlib.util
import json
import os
import py_compile
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "tools" / "imap-caldav"
for p in (PLUGIN, ROOT / "tools"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import ic_caldav  # noqa: E402
import ic_common as icc  # noqa: E402
import ic_ical  # noqa: E402
import ic_imap  # noqa: E402

import sbk_config  # noqa: E402

ME = "demo.owner@mail.example"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


L0 = _load("ic_l0_download", PLUGIN / "ic-l0-download.py")
AUTH = _load("ic_l0_auth", PLUGIN / "ic-l0-auth.py")


class _Log:
    def __init__(self):
        self.lines = []

    def info(self, m):
        self.lines.append(("info", m))

    def warning(self, m):
        self.lines.append(("warning", m))

    def error(self, m):
        self.lines.append(("error", m))


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Isolated data root and config; secrets come from a dict, never the Keychain."""
    root = tmp_path / "data"
    monkeypatch.setattr(sbk_config, "DATA_ROOT", root)
    monkeypatch.setattr(sbk_config, "EMAILS_DIR", root / "emails")
    monkeypatch.setattr(sbk_config, "CALENDARS_DIR", root / "calendars")
    monkeypatch.setattr(sbk_config, "LAST_RUNS_FILE", root / "last-runs.json")
    monkeypatch.setattr(sbk_config, "OWN_EMAILS", {ME})
    conf = {
        "imap_caldav": {
            "accounts": {
                "demo": {
                    "preset": "fastmail",
                    "email": ME,
                    "folders": "auto",
                    "calendar": "caldav",
                }
            }
        }
    }
    monkeypatch.setattr(sbk_config, "_USER_CFG", conf)
    secrets: dict = {}
    monkeypatch.setattr(icc, "get_secret", lambda s, a: secrets.get((s, a)))
    monkeypatch.setattr(icc, "set_secret", lambda s, a, v: secrets.__setitem__((s, a), v))
    return {"root": root, "conf": conf, "secrets": secrets}


# --------------------------------------------------------------------------- config


def test_presets_and_account_config(env):
    env["conf"]["imap_caldav"]["accounts"]["icl"] = {
        "preset": "icloud",
        "email": "demo@icloud.example",
    }
    accs = {a.label: a for a in icc.load_accounts()}
    assert accs["demo"].imap_host == "imap.fastmail.com" and accs["demo"].imap_port == 993
    assert accs["demo"].caldav_url == "https://caldav.fastmail.com/"
    assert accs["demo"].username == ME
    assert accs["icl"].imap_host == "imap.mail.me.com"
    assert accs["icl"].username == "demo"  # Apple: the name part of the address
    assert accs["icl"].calendar == "none"
    for p in icc.PRESETS.values():  # every preset cites official pages
        assert p["docs"] and all(u.startswith("https://") for u in p["docs"])


@pytest.mark.parametrize(
    "acc,needle",
    [
        ({"preset": "nope", "email": ME}, "unknown preset"),
        ({"email": ME}, "imap_host missing"),
        (
            {"imap_host": "imap.mail.example", "email": ME, "calendar": "caldav"},
            "caldav_url is empty",
        ),
        ({"preset": "outlook", "email": ME}, "oauth_client_id"),
        (
            {
                "imap_host": "imap.mail.example",
                "email": ME,
                "calendar": "caldav",
                "caldav_url": "http://dav.mail.example/",
            },
            "https://",
        ),  # fmt: skip
        ({"imap_host": "imap.mail.example", "email": ME, "mail_since": "01/02/2026"}, "YYYY-MM-DD"),
    ],
)
def test_account_config_errors(env, acc, needle):
    env["conf"]["imap_caldav"]["accounts"] = {"bad": acc}
    with pytest.raises(icc.SetupError) as e:
        icc.load_accounts()
    assert needle in str(e.value) and "\n" not in str(e.value)


def test_bad_label_and_empty_config(env):
    env["conf"]["imap_caldav"]["accounts"] = {"Bad-Label": {"preset": "fastmail", "email": ME}}
    with pytest.raises(icc.SetupError):
        icc.load_accounts()
    env["conf"].clear()
    with pytest.raises(icc.SetupError, match="no account"):
        icc.load_accounts()


# --------------------------------------------------------------------------- IMAP pieces


def test_mutf7_and_list_parsing():
    assert ic_imap.decode_mutf7("Entw&APw-rfe") == "Entwürfe"
    assert ic_imap.decode_mutf7("A&-B") == "A&B"
    data = [
        b'(\\HasNoChildren) "/" "INBOX"',
        b'(\\HasNoChildren \\Sent) "/" "Sent Items"',
        b'(\\HasNoChildren \\Trash) "/" "Trash"',
        b'(\\HasNoChildren \\Junk) "/" "Spam"',
        b'(\\HasNoChildren) "/" "Entw&APw-rfe"',
        b'(\\Noselect \\HasChildren) "/" "Archive"',
    ]

    class C:
        def list(self):
            return "OK", data

    folders = ic_imap.list_folders(C())
    names = [f["name"] for f in folders]
    assert "Entwürfe" in names
    auto = [f["name"] for f in ic_imap.choose_folders(folders, "auto")]
    assert auto == ["INBOX", "Sent Items"]
    allf = [f["name"] for f in ic_imap.choose_folders(folders, "all")]
    assert "Trash" not in allf and "Spam" not in allf and "Archive" not in allf
    assert "Entwürfe" in allf
    assert [f["name"] for f in ic_imap.choose_folders(folders, ["entwürfe"])] == ["Entwürfe"]


def _mail(uid, subject, frm="Ada Demo <ada@acme.example>", to=ME, html=False, msgid=None,
          reply_to=None, attach=False):  # fmt: skip
    m = EmailMessage()
    m["From"] = frm
    m["To"] = to
    m["Cc"] = "=?utf-8?q?B=C3=A9a_Demo?= <bea@acme.example>"
    m["Subject"] = subject
    m["Date"] = "Mon, 02 Nov 2026 10:00:00 +0100"
    m["Message-ID"] = msgid or f"<m{uid}@acme.example>"
    if reply_to:
        m["In-Reply-To"] = reply_to
        m["References"] = reply_to
    m.set_content(f"Plain body {uid}")
    if html:
        m.add_alternative(f"<html><body><p>Html body {uid}</p><script>x()</script></body></html>",
                          subtype="html")  # fmt: skip
    if attach:
        m.add_attachment(
            b"%PDF-1.4 demo", maintype="application", subtype="pdf", filename="offer.pdf"
        )
    return m.as_bytes()


def test_message_row_columns_and_values():
    raw = _mail(7, "Hello", html=True, attach=True)
    folder = {"raw": "INBOX", "name": "INBOX", "flags": set()}
    row = ic_imap.message_row(
        raw, account="demo", folder=folder, uidvalidity=11, uid=7, flags={"\\Flagged"},
        internaldate="02-Nov-2026 10:00:05 +0100", size=len(raw), max_bytes=10**7,
    )  # fmt: skip
    assert set(ic_imap.MAIL_COLUMNS) <= set(row)
    assert row["date"] == datetime(2026, 11, 2, 9, 0, 5, tzinfo=UTC)
    assert row["subject"] == "Hello" and "Béa Demo" in row["cc"]
    assert row["body_text"].startswith("Plain body 7")
    assert set(row["labels"].split(",")) == {"INBOX", "UNREAD", "STARRED"}
    assert row["message_id"] == "<m7@acme.example>"
    assert (
        row["has_attachments"] and json.loads(row["attachments_json"])[0]["filename"] == "offer.pdf"
    )
    again = ic_imap.message_row(
        raw, account="demo", folder={"raw": "Sent", "name": "Sent", "flags": {"\\sent"}},
        uidvalidity=99, uid=1, flags={"\\Seen"}, internaldate="", size=0, max_bytes=10**7,
    )  # fmt: skip
    assert again["id"] == row["id"]  # same Message-ID -> same id in every folder
    assert again["labels"] == "SENT"
    reply = ic_imap.message_row(
        _mail(8, "Re: Hello", reply_to="<m7@acme.example>"), account="demo", folder=folder,
        uidvalidity=11, uid=8, flags=set(), internaldate="", size=0, max_bytes=10**7,
    )  # fmt: skip
    assert reply["thread_id"] == row["thread_id"] and reply["in_reply_to"] == "<m7@acme.example>"


def test_html_only_body_is_stripped():
    m = EmailMessage()
    m["From"] = "x@acme.example"
    m["Subject"] = "h"
    m.set_content("<p>Line one</p><style>p{}</style><p>Line &amp; two</p>", subtype="html")
    assert ic_imap.extract_body(m) == "Line one\n\nLine & two"


# --------------------------------------------------------------------------- fake IMAP server


class FakeIMAP:
    """Just enough of imaplib.IMAP4_SSL; records every command."""

    def __init__(self, boxes, caps=("IMAP4REV1", "CONDSTORE", "ENABLE")):
        self.boxes = boxes
        self.capabilities = tuple(caps)
        self.calls = []
        self.selected = None
        self._untagged = {}

    def login(self, user, pw):
        self.calls.append(("LOGIN", user))
        if pw != "app-pass":
            raise imaplib.IMAP4.error("[AUTHENTICATIONFAILED] Authentication failed.")
        return "OK", [b"ok"]

    def authenticate(self, mech, cb):
        self.calls.append(("AUTHENTICATE", mech, cb(b"")))
        return "OK", [b"ok"]

    def enable(self, cap):
        self.calls.append(("ENABLE", cap))
        return "OK", [b""]

    def list(self):
        self.calls.append(("LIST",))
        return "OK", [f'({b["flags"]}) "/" "{name}"'.encode() for name, b in self.boxes.items()]

    def select(self, mailbox, readonly=False):
        self.calls.append(("SELECT", mailbox, readonly))
        name = mailbox.strip('"')
        b = self.boxes[name]
        self.selected = b
        uids = sorted(b["msgs"])
        self._untagged = {
            "UIDVALIDITY": [str(b["uidvalidity"]).encode()],
            "UIDNEXT": [str((uids[-1] + 1) if uids else 1).encode()],
        }
        if "CONDSTORE" in self.capabilities:
            hm = max([m["modseq"] for m in b["msgs"].values()] or [1])
            self._untagged["HIGHESTMODSEQ"] = [str(hm).encode()]
        return "OK", [str(len(uids)).encode()]

    def response(self, code):
        return code, self._untagged.pop(code, [None])

    def uid(self, cmd, *args):
        self.calls.append(("UID", cmd) + args)
        b = self.selected
        uids = sorted(b["msgs"])
        if cmd == "SEARCH":
            if args[0] == "UID":
                lo = int(args[1].split(":")[0])
                hit = [u for u in uids if u >= lo] or uids[-1:]
            else:
                hit = uids
            return "OK", [" ".join(str(u) for u in hit).encode()]
        if cmd == "FETCH":
            spec, items = args[0], args[1]
            if ":" in spec:
                lo, hi = (int(x) for x in spec.split(":"))
                want = [u for u in uids if lo <= u <= hi]
            else:
                want = [int(x) for x in spec.split(",")]
            changed = int(args[2].split()[1].rstrip(")")) if len(args) > 2 else None
            out = []
            for n, u in enumerate(want, 1):
                m = b["msgs"][u]
                if changed is not None and m["modseq"] <= changed:
                    continue
                fl = " ".join(sorted(m["flags"]))
                if "BODY.PEEK" in items:
                    head = (f'{n} (UID {u} FLAGS ({fl}) INTERNALDATE "02-Nov-2026 10:00:00 +0000" '
                            f"RFC822.SIZE {len(m['raw'])} BODY[]<0> {{{len(m['raw'])}}}")  # fmt: skip
                    out += [(head.encode(), m["raw"]), b")"]
                elif "RFC822.SIZE" in items:
                    out.append(f"{n} (UID {u} RFC822.SIZE {len(m['raw'])})".encode())
                else:
                    out.append(f"{n} (UID {u} FLAGS ({fl}) MODSEQ ({m['modseq']}))".encode())
            return "OK", out
        raise AssertionError(f"unexpected UID {cmd}")

    def logout(self):
        self.calls.append(("LOGOUT",))
        return "BYE", [b""]


def _boxes():
    return {
        "INBOX": {"flags": "\\HasNoChildren", "uidvalidity": 5, "msgs": {
            1: {"flags": {"\\Seen"}, "modseq": 10, "raw": _mail(1, "One")},
            2: {"flags": set(), "modseq": 11, "raw": _mail(2, "Two", html=True)},
        }},
        "Sent": {"flags": "\\HasNoChildren \\Sent", "uidvalidity": 7, "msgs": {
            1: {"flags": {"\\Seen"}, "modseq": 3,
                "raw": _mail(3, "Re: One", frm=f"Demo Owner <{ME}>", to="ada@acme.example",
                             reply_to="<m1@acme.example>")},
        }},
        "Trash": {"flags": "\\HasNoChildren \\Trash", "uidvalidity": 9, "msgs": {
            1: {"flags": set(), "modseq": 1, "raw": _mail(9, "Deleted")},
        }},
    }  # fmt: skip


def _sync(env, server, monkeypatch, **kw):
    env["secrets"][("sbk-mailbox", "demo")] = "app-pass"
    monkeypatch.setattr(ic_imap, "IMAP_FACTORY", lambda host, port: server)
    acc = icc.load_accounts()[0]
    state = icc.load_state("demo")
    return ic_imap.sync_account(acc, state, since="", force=kw.get("force", False), log=_Log())


def test_imap_first_run_incremental_flags_and_read_only(env, monkeypatch):
    boxes = _boxes()
    server = FakeIMAP(boxes)
    s1 = _sync(env, server, monkeypatch)
    slot = env["root"] / "emails" / "demo" / "messages.parquet"
    df = pd.read_parquet(slot)
    assert len(df) == 3 and s1["new"] == 3 and s1["condstore"]
    assert set(ic_imap.MAIL_COLUMNS) == set(df.columns)
    assert str(df["date"].dtype).startswith("datetime64") and "UTC" in str(df["date"].dtype)
    assert not any("Deleted" in s for s in df["subject"])  # Trash is not read in auto
    two = df[df["subject"] == "Two"].iloc[0]
    assert set(two["labels"].split(",")) == {"INBOX", "UNREAD"}
    # read-only: EXAMINE (readonly=True), BODY.PEEK, never STORE/EXPUNGE/COPY
    assert all(c[2] is True for c in server.calls if c[0] == "SELECT")
    assert not any(
        c[0] == "UID" and c[1] in ("STORE", "COPY", "MOVE", "EXPUNGE") for c in server.calls
    )
    assert (env["root"] / "emails" / "demo" / ".imap-caldav").exists()

    # unchanged mailbox: no FETCH at all
    server.calls.clear()
    s2 = _sync(env, server, monkeypatch)
    assert s2["new"] == 0 and not any(c[:2] == ("UID", "FETCH") for c in server.calls)
    assert all(v["skipped"] for v in s2["folders"].values())

    # a new message + a flag change (Two read, CONDSTORE)
    boxes["INBOX"]["msgs"][3] = {"flags": set(), "modseq": 20, "raw": _mail(4, "Three")}
    boxes["INBOX"]["msgs"][2]["flags"] = {"\\Seen", "\\Flagged"}
    boxes["INBOX"]["msgs"][2]["modseq"] = 21
    server.calls.clear()
    s3 = _sync(env, server, monkeypatch)
    fetched = [c for c in server.calls if c[:2] == ("UID", "FETCH") and "BODY.PEEK" in c[3]]
    assert [c[2] for c in fetched] == ["3"]  # only the new UID is downloaded
    assert any("CHANGEDSINCE 11" in c[-1] for c in server.calls if c[:2] == ("UID", "FETCH"))
    df = pd.read_parquet(slot)
    assert len(df) == 4 and s3["new"] == 1 and s3["flag_changes"] == 1
    two = df[df["subject"] == "Two"].iloc[0]
    assert set(two["labels"].split(",")) == {"INBOX", "STARRED"}
    assert not list(icc.chunks_dir("demo").glob("*.parquet"))


def test_imap_message_in_two_folders_and_uidvalidity_change(env, monkeypatch):
    boxes = _boxes()
    boxes["Sent"]["msgs"][2] = {"flags": {"\\Seen"}, "modseq": 4, "raw": _mail(1, "One")}
    server = FakeIMAP(boxes, caps=("IMAP4REV1",))  # no CONDSTORE
    _sync(env, server, monkeypatch)
    df = pd.read_parquet(env["root"] / "emails" / "demo" / "messages.parquet")
    one = df[df["message_id"] == "<m1@acme.example>"]
    assert len(one) == 1 and set(one.iloc[0]["labels"].split(",")) == {"INBOX", "SENT"}
    boxes["INBOX"]["uidvalidity"] = 6  # server renumbered the folder
    server.calls.clear()
    _sync(env, server, monkeypatch)
    assert any(c[:3] == ("UID", "SEARCH", "ALL") for c in server.calls)
    df2 = pd.read_parquet(env["root"] / "emails" / "demo" / "messages.parquet")
    assert len(df2) == len(df)  # re-read, no duplicates


def test_imap_wrong_password_and_gmail_label_clash(env, monkeypatch):
    server = FakeIMAP(_boxes())
    env["secrets"][("sbk-mailbox", "demo")] = "wrong"
    monkeypatch.setattr(ic_imap, "IMAP_FACTORY", lambda h, p: server)
    acc = icc.load_accounts()[0]
    with pytest.raises(icc.SetupError) as e:
        ic_imap.sync_account(acc, icc.load_state("demo"), since="", force=False, log=_Log())
    assert "refused the login" in str(e.value) and "wrong" not in str(e.value)
    assert "\n" not in str(e.value)
    (env["root"] / "emails").mkdir(parents=True, exist_ok=True)
    (env["root"] / "emails" / "accounts.json").write_text(json.dumps({"demo": {}}))
    with pytest.raises(icc.SetupError, match="Gmail mailbox"):
        ic_imap.sync_account(acc, icc.load_state("demo"), since="", force=False, log=_Log())


def test_slot_owned_by_another_downloader_is_refused(env):
    d = env["root"] / "emails" / "demo"
    d.mkdir(parents=True)
    pd.DataFrame({"id": ["x"]}).to_parquet(d / "messages.parquet")
    with pytest.raises(icc.SetupError, match="another downloader"):
        icc.claim_slot(d, "messages.parquet")


def test_xoauth2_login_uses_sasl_string(env, monkeypatch):
    env["conf"]["imap_caldav"]["accounts"] = {
        "ol": {"preset": "outlook", "email": "demo@outlook.example", "oauth_client_id": "cid-demo"}
    }
    env["secrets"][("sbk-imap-oauth", "ol")] = "refresh-1"
    seen = []

    def send(method, url, headers, body):
        seen.append((method, url, parse_qs(body.decode())))
        return 200, {}, json.dumps({"access_token": "at-1", "refresh_token": "refresh-2"}).encode()

    monkeypatch.setattr(icc, "HTTP_SEND", send)
    server = FakeIMAP(_boxes())
    monkeypatch.setattr(ic_imap, "IMAP_FACTORY", lambda h, p: server)
    acc = icc.load_accounts()[0]
    ic_imap.connect(acc, None)
    auth = [c for c in server.calls if c[0] == "AUTHENTICATE"][0]
    assert auth[1] == "XOAUTH2"
    assert auth[2] == b"user=demo@outlook.example\x01auth=Bearer at-1\x01\x01"
    assert seen[0][1] == "https://login.microsoftonline.com/consumers/oauth2/v2.0/token"
    assert seen[0][2]["scope"] == [icc.MS_IMAP_SCOPE]
    assert env["secrets"][("sbk-imap-oauth", "ol")] == "refresh-2"  # rotated


def test_em_l1_enrich_reads_the_mail_slot(env, monkeypatch):
    _sync(env, FakeIMAP(_boxes()), monkeypatch)
    em = _load("em_l1_enrich_for_test", ROOT / "tools" / "email" / "em-l1-enrich.py")
    monkeypatch.setattr(em, "DATA_DIR", env["root"] / "emails")
    msgs = em.load_all_messages()
    assert set(msgs["account"]) == {"demo"}
    contacts = em.build_contacts(msgs)
    assert {"ada@acme.example", "bea@acme.example"} <= set(contacts["email"])
    assert contacts.set_index("email").loc["bea@acme.example", "name"] == "Béa Demo"


# --------------------------------------------------------------------------- iCalendar


def _d(days, hour=10):
    t = datetime.now(UTC).replace(hour=hour, minute=0, second=0, microsecond=0) + timedelta(
        days=days
    )
    return t


def _fmt(t: datetime) -> str:
    return t.strftime("%Y%m%dT%H%M%S")


def _window():
    n = datetime.now(UTC)
    return n - timedelta(days=60), n + timedelta(days=60)


def _ics(*vevents):
    return (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//demo//EN\r\n"
        + "".join(vevents)
        + "END:VCALENDAR\r\n"
    )


def _vevent(uid, start, *, extra="", tz="Europe/Rome", summary="Demo meeting"):
    return (
        "BEGIN:VEVENT\r\n"
        f"UID:{uid}\r\n"
        f"DTSTART;TZID={tz}:{_fmt(start)}\r\n"
        f"DTEND;TZID={tz}:{_fmt(start + timedelta(hours=1))}\r\n"
        f"SUMMARY:{summary}\r\n"
        f"ORGANIZER;CN=Ada Demo:mailto:ada@acme.example\r\n"
        f'ATTENDEE;CN="Demo, Owner";PARTSTAT=ACCEPTED:mailto:{ME}\r\n'
        "ATTENDEE;CN=Bea Demo;PARTSTAT=TENTATIVE:mailto:bea@acme.example\r\n"
        "DESCRIPTION:Agenda\\, notes\\nJoin https://meet.google.com/abc-defg-hij \r\n"
        " now\r\n"
        "LAST-MODIFIED:20261101T080000Z\r\n"
        f"{extra}END:VEVENT\r\n"
    )


def test_ical_single_event_row():
    start = _d(3)
    rows = ic_ical.rows_from_ics(
        _ics(_vevent("u1@demo", start)), account="demo", calendar_name="Work",
        calendar_id="cal-1", own={ME}, window=_window(),
    )  # fmt: skip
    assert len(rows) == 1
    r = rows[0]
    assert set(r) == set(ic_ical.EVENT_COLUMNS)
    assert r["start_datetime"].startswith(start.strftime("%Y-%m-%dT10:00:00"))
    assert r["start_timezone"] == "Europe/Rome"
    assert r["organizer_email"] == "ada@acme.example" and r["organizer_self"] == ""
    att = json.loads(r["attendees"])
    assert [a["email"] for a in att] == [ME, "bea@acme.example"]
    assert att[0]["name"] == "Demo, Owner" and att[1]["status"] == "tentative"
    assert r["self_status"] == "accepted" and r["status"] == "confirmed"
    assert r["description"] == "Agenda, notes\nJoin https://meet.google.com/abc-defg-hij now"
    assert r["conference_url"] == "https://meet.google.com/abc-defg-hij"
    assert r["updated"] == "2026-11-01T08:00:00+00:00"


def test_ical_all_day_floating_and_unknown_zone():
    text = _ics(
        "BEGIN:VEVENT\r\nUID:a@demo\r\nDTSTART;VALUE=DATE:20261224\r\nSUMMARY:Holiday\r\nEND:VEVENT\r\n",
        "BEGIN:VEVENT\r\nUID:b@demo\r\nDTSTART;TZID=W. Europe Standard Time:20261110T090000\r\n"
        "DURATION:PT30M\r\nSUMMARY:Windows zone\r\nEND:VEVENT\r\n",
    )
    rows = {r["summary"]: r for r in ic_ical.rows_from_ics(
        text, account="demo", calendar_name="c", calendar_id="c", own=set(), window=_window())}  # fmt: skip
    assert rows["Holiday"]["start_datetime"] == "2026-12-24"
    assert rows["Holiday"]["end_datetime"] == "2026-12-25"
    w = rows["Windows zone"]
    assert (
        w["start_datetime"] == "2026-11-10T09:00:00" and w["end_datetime"] == "2026-11-10T09:30:00"
    )
    assert w["start_timezone"] == "W. Europe Standard Time"


def test_ical_recurrence_exdate_override_and_cancelled():
    start = _d(-14)
    ex = start + timedelta(days=7)
    moved = start + timedelta(days=14)
    gone = start + timedelta(days=21)
    master = _vevent(
        "r@demo", start, summary="Weekly",
        extra=f"RRULE:FREQ=WEEKLY;COUNT=6\r\nEXDATE;TZID=Europe/Rome:{_fmt(ex)}\r\n",
    )  # fmt: skip
    override = _vevent(
        "r@demo", moved + timedelta(hours=2), summary="Weekly (moved)",
        extra=f"RECURRENCE-ID;TZID=Europe/Rome:{_fmt(moved)}\r\n",
    )  # fmt: skip
    cancelled = _vevent(
        "r@demo", gone, summary="Weekly",
        extra=f"RECURRENCE-ID;TZID=Europe/Rome:{_fmt(gone)}\r\nSTATUS:CANCELLED\r\n",
    )  # fmt: skip
    rows = ic_ical.rows_from_ics(
        _ics(master, override, cancelled), account="demo", calendar_name="c", calendar_id="c",
        own={ME}, window=_window(),
    )  # fmt: skip
    assert len(rows) == 5  # 6 occurrences - 1 EXDATE
    base = {r["recurring_event_id"] for r in rows}
    assert len(base) == 1 and all(r["id"].startswith(next(iter(base)) + "_") for r in rows)
    by_summary = [r["summary"] for r in rows]
    assert by_summary.count("Weekly (moved)") == 1
    assert sum(r["status"] == "cancelled" for r in rows) == 1
    assert not any(r["start_datetime"].startswith(ex.strftime("%Y-%m-%d")) for r in rows)
    assert len({r["id"] for r in rows}) == 5


def test_ical_broken_rrule_keeps_first_instance():
    warns = []
    text = _ics(_vevent("x@demo", _d(1), extra="RRULE:FREQ=NEVER\r\n"))
    rows = ic_ical.rows_from_ics(text, account="d", calendar_name="c", calendar_id="c", own=set(),
                                 window=_window(), warn=warns.append)  # fmt: skip
    assert len(rows) == 1 and warns


# --------------------------------------------------------------------------- fake CalDAV server

BASE = "https://dav.mail.example"


class FakeDav:
    def __init__(self, objects):
        self.objects = objects  # {path: (etag, ics)}
        self.ctag = "ctag-1"
        self.calls = []

    def __call__(self, method, url, headers, body):
        u = urlsplit(url)
        self.calls.append((method, u.path, headers.get("Authorization", ""), body))
        assert u.scheme == "https"
        if method == "PROPFIND" and u.path == "/":
            return 404, {}, b""
        if method == "PROPFIND" and u.path == "/.well-known/caldav":
            return 301, {"location": "/dav/"}, b""
        if method == "PROPFIND" and u.path == "/dav/":
            return (
                207,
                {},
                self._ms(
                    [
                        (
                            "/dav/",
                            "<d:current-user-principal><d:href>/dav/principals/demo/</d:href></d:current-user-principal>",
                        )
                    ]
                ),
            )
        if method == "PROPFIND" and u.path == "/dav/principals/demo/":
            return (
                207,
                {},
                self._ms(
                    [
                        (
                            "/dav/principals/demo/",
                            "<c:calendar-home-set><d:href>/dav/cal/demo/</d:href></c:calendar-home-set>",
                        )
                    ]
                ),
            )
        if method == "PROPFIND" and u.path == "/dav/cal/demo/" and b"getctag" in body:
            return 207, {}, self._ms([
                ("/dav/cal/demo/", "<d:resourcetype><d:collection/></d:resourcetype>"),
                ("/dav/cal/demo/work/", "<d:resourcetype><d:collection/><c:calendar/></d:resourcetype>"
                 f"<d:displayname>Work</d:displayname><cs:getctag>{self.ctag}</cs:getctag>"
                 '<c:supported-calendar-component-set><c:comp name="VEVENT"/></c:supported-calendar-component-set>'),
                ("/dav/cal/demo/tasks/", "<d:resourcetype><d:collection/><c:calendar/></d:resourcetype>"
                 "<d:displayname>Tasks</d:displayname><cs:getctag>t1</cs:getctag>"
                 '<c:supported-calendar-component-set><c:comp name="VTODO"/></c:supported-calendar-component-set>'),
            ])  # fmt: skip
        if method == "PROPFIND" and u.path == "/dav/cal/demo/work/":
            items = [
                (
                    "/dav/cal/demo/work/",
                    "<d:resourcetype><d:collection/><c:calendar/></d:resourcetype>",
                )
            ]
            items += [
                (p, f"<d:resourcetype/><d:getetag>{et}</d:getetag>")
                for p, (et, _i) in self.objects.items()
            ]
            return 207, {}, self._ms(items)
        if method == "REPORT" and u.path == "/dav/cal/demo/work/":
            import re

            wanted = re.findall(rb"<d:href>([^<]+)</d:href>", body)
            items = []
            for w in wanted:
                et, ics = self.objects[w.decode()]
                items.append(
                    (
                        w.decode(),
                        f"<d:getetag>{et}</d:getetag><c:calendar-data>{ics}</c:calendar-data>",
                    )
                )
            return 207, {}, self._ms(items)
        return 405, {}, b""

    @staticmethod
    def _ms(items):
        parts = ['<?xml version="1.0"?><d:multistatus xmlns:d="DAV:" '
                 'xmlns:c="urn:ietf:params:xml:ns:caldav" xmlns:cs="http://calendarserver.org/ns/">']  # fmt: skip
        for href, props in items:
            parts.append(f"<d:response><d:href>{href}</d:href><d:propstat><d:prop>{props}</d:prop>"
                         "<d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>")  # fmt: skip
        parts.append("</d:multistatus>")
        return "".join(parts).encode()


def _cal_env(env, monkeypatch, dav):
    env["conf"]["imap_caldav"]["accounts"]["demo"]["caldav_url"] = BASE + "/"
    env["conf"]["imap_caldav"]["calendar_past_days"] = 60
    env["conf"]["imap_caldav"]["calendar_future_days"] = 60
    env["secrets"][("sbk-caldav", "demo")] = "dav-pass"
    monkeypatch.setattr(icc, "HTTP_SEND", dav)
    return icc.load_accounts()[0]


def test_caldav_discovery_incremental_and_set_aside(env, monkeypatch):
    objs = {
        "/dav/cal/demo/work/a.ics": ('"e1"', _ics(_vevent("a@demo", _d(2), summary="Alpha"))),
        "/dav/cal/demo/work/b.ics": ('"e2"', _ics(_vevent("b@demo", _d(5), summary="Beta"))),
    }
    dav = FakeDav(objs)
    acc = _cal_env(env, monkeypatch, dav)
    log = _Log()
    state = icc.load_state("demo")
    s1 = ic_caldav.sync_caldav(acc, state, force=False, log=log)
    r1 = ic_caldav.rebuild_events(acc, log)
    assert s1["fetched"] == 2 and r1["events"] == 2 and "Tasks" not in s1["calendars"]
    # Basic credentials go only to the same site, through the well-known redirect
    assert all(c[2].startswith("Basic ") for c in dav.calls)
    ev = pd.read_parquet(env["root"] / "calendars" / "demo" / "events.parquet")
    assert set(ic_ical.EVENT_COLUMNS) == set(ev.columns)
    assert set(ev["calendar_name"]) == {"Work"} and set(ev["summary"]) == {"Alpha", "Beta"}

    # same ctag: no object listing
    dav.calls.clear()
    s2 = ic_caldav.sync_caldav(acc, icc.load_state("demo"), force=False, log=log)
    assert s2["calendars"]["Work"] == {"skipped": True}
    assert not any(c[1] == "/dav/cal/demo/work/" for c in dav.calls)

    # one changed, one deleted, one new
    objs["/dav/cal/demo/work/a.ics"] = ('"e1b"', _ics(_vevent("a@demo", _d(2), summary="Alpha v2")))
    del objs["/dav/cal/demo/work/b.ics"]
    objs["/dav/cal/demo/work/c.ics"] = ('"e3"', _ics(_vevent("c@demo", _d(9), summary="Gamma")))
    dav.ctag = "ctag-2"
    dav.calls.clear()
    s3 = ic_caldav.sync_caldav(acc, icc.load_state("demo"), force=False, log=log)
    ic_caldav.rebuild_events(acc, log)
    rep = [c for c in dav.calls if c[0] == "REPORT"]
    assert len(rep) == 1 and b"a.ics" in rep[0][3] and b"c.ics" in rep[0][3]
    assert s3["fetched"] == 2 and s3["removed"] == 1
    ev = pd.read_parquet(env["root"] / "calendars" / "demo" / "events.parquet")
    assert set(ev["summary"]) == {"Alpha v2", "Gamma"}
    removed = pd.read_parquet(icc.raw_dir("demo") / "removed.parquet")
    assert list(removed["href"]) == [BASE + "/dav/cal/demo/work/b.ics"]


def test_ca_l1_extract_reads_the_calendar_slot(env, monkeypatch):
    objs = {"/dav/cal/demo/work/a.ics": ('"e1"', _ics(_vevent("a@demo", _d(2))))}
    acc = _cal_env(env, monkeypatch, FakeDav(objs))
    ic_caldav.sync_caldav(acc, icc.load_state("demo"), force=False, log=_Log())
    ic_caldav.rebuild_events(acc, _Log())
    ca = _load("ca_l1_extract_for_test", ROOT / "tools" / "calendar" / "ca-l1-extract.py")
    monkeypatch.setattr(ca, "CALENDARS_DIR", env["root"] / "calendars")
    monkeypatch.setattr(ca, "EMAILS_DIR", env["root"] / "emails")
    files = ca.discover_parquet_files()
    assert [a for a, _p in files] == ["demo"]
    ((_acc, df),) = ca.eventi_senza_doppioni(files)
    row = df.iloc[0]
    assert ca.get_event_date(row) == _d(2).strftime("%Y-%m-%d")
    assert ca.parse_attendees(row["attendees"]) == [ME, "bea@acme.example"]
    assert row["organizer_email"] == "ada@acme.example"


def test_caldav_bad_password_is_one_line(env, monkeypatch):
    acc = _cal_env(env, monkeypatch, lambda m, u, h, b: (401, {}, b""))
    with pytest.raises(icc.SetupError) as e:
        ic_caldav.sync_caldav(acc, icc.load_state("demo"), force=False, log=_Log())
    assert "401" in str(e.value) and "\n" not in str(e.value)


def test_ics_link_etag_and_webcal(env, monkeypatch):
    env["conf"]["imap_caldav"]["accounts"] = {
        "feed": {"imap_host": "imap.mail.example", "email": ME, "mail": False, "calendar": "ics"}
    }
    env["secrets"][("sbk-ics", "feed")] = "webcal://cal.mail.example/private/secret-token/basic.ics"
    calls = []

    def send(method, url, headers, body):
        calls.append((url, dict(headers)))
        if headers.get("If-None-Match") == '"v1"':
            return 304, {}, b""
        return 200, {"etag": '"v1"'}, _ics(_vevent("f@demo", _d(1), summary="Feed")).encode()

    monkeypatch.setattr(icc, "HTTP_SEND", send)
    acc = icc.load_accounts()[0]
    log = _Log()
    r1 = ic_caldav.sync_ics(acc, icc.load_state("feed"), force=False, log=log)
    ic_caldav.rebuild_events(acc, log)
    r2 = ic_caldav.sync_ics(acc, icc.load_state("feed"), force=False, log=log)
    assert r1["skipped"] is False and r2 == {"skipped": True}
    assert calls[0][0].startswith("https://cal.mail.example/")
    assert "Authorization" not in calls[0][1]
    assert not any("secret-token" in str(m) for _lvl, m in log.lines)  # the link is a secret
    state = json.loads((icc.state_dir() / "feed.json").read_text())
    assert "secret-token" not in json.dumps(state)
    ev = pd.read_parquet(env["root"] / "calendars" / "feed" / "events.parquet")
    assert list(ev["summary"]) == ["Feed"] and not ev["calendar_id"].str.contains("secret").any()


# --------------------------------------------------------------------------- HTTP safety + OAuth


def test_http_refuses_plain_http_and_cross_site_credentials(monkeypatch):
    seen = []

    def send(method, url, headers, body):
        seen.append((url, headers.get("Authorization")))
        if "dav.mail.example" in url:
            return 302, {"location": "https://evil.other.example/steal"}, b""
        return 200, {}, b"ok"

    monkeypatch.setattr(icc, "HTTP_SEND", send)
    with pytest.raises(icc.SetupError, match="non-https"):
        icc.http_request("GET", "http://dav.mail.example/")
    status, _h, _b, final = icc.http_request(
        "PROPFIND", "https://dav.mail.example/", auth=("u", "p")
    )
    assert status == 200 and final == "https://evil.other.example/steal"
    assert seen[0][1].startswith("Basic ") and seen[1][1] is None


def test_device_code_flow(env, monkeypatch):
    env["conf"]["imap_caldav"]["accounts"] = {
        "ol": {"preset": "outlook", "email": "demo@outlook.example", "oauth_client_id": "cid-demo"}
    }
    answers = [
        (
            200,
            {
                "device_code": "dc-1",
                "user_code": "ABCD",
                "verification_uri": "https://microsoft.com/devicelogin",
                "interval": 1,
                "expires_in": 60,
                "message": "go",
            },
        ),  # fmt: skip
        (400, {"error": "authorization_pending"}),
        (400, {"error": "slow_down"}),
        (200, {"access_token": "a", "refresh_token": "r-1"}),
    ]
    posts = []

    def send(method, url, headers, body):
        posts.append((url, parse_qs(body.decode())))
        st, js = answers.pop(0)
        return st, {}, json.dumps(js).encode()

    monkeypatch.setattr(icc, "HTTP_SEND", send)
    sleeps = []
    acc = icc.load_accounts()[0]
    tok = AUTH.device_code_login(acc, sleep=sleeps.append, echo=lambda m: None)
    assert tok == "r-1"
    assert posts[0][0].endswith("/consumers/oauth2/v2.0/devicecode")
    assert posts[1][1]["grant_type"] == ["urn:ietf:params:oauth:grant-type:device_code"]
    assert sleeps == [1, 1, 6]


# --------------------------------------------------------------------------- scripts


def _run(args, tmp_path, config=None):
    envv = dict(os.environ)
    envv.update(
        {
            "SBK_DATA_ROOT": str(tmp_path / "d"),
            "SBK_CONFIG": str(tmp_path / "sbk.config.json"),
            "SBK_CONTAINERIZED": "1",  # no Keychain lookups from tests
        }
    )
    for k in list(envv):
        if k.startswith(("SBK_MAILBOX_", "SBK_CALDAV_", "SBK_ICS_", "SBK_IMAP_OAUTH_")):
            envv.pop(k)
    # Empty, not absent: a .env file loaded by the script (override=False) cannot fill them,
    # so the no-credentials runs can never reach a real server.
    for k in ("SBK_MAILBOX_PASSWORD_DEMO", "SBK_CALDAV_PASSWORD_DEMO", "SBK_ICS_URL_DEMO",
              "SBK_IMAP_OAUTH_REFRESH_DEMO"):  # fmt: skip
        envv[k] = ""
    # The owner fields are always set, so the kernel's "no owner" warning stays out of the
    # one-line error checks; the imap_caldav section comes only from `config`.
    owner = {"owner": "Alex Demo", "own_emails": ["alex@personal.example"]}
    (tmp_path / "sbk.config.json").write_text(json.dumps({**owner, **(config or {})}))
    return subprocess.run(
        [sys.executable, *args], cwd=ROOT, env=envv, capture_output=True, text=True, timeout=120
    )


def test_scripts_compile_and_help(tmp_path):
    for f in PLUGIN.glob("*.py"):
        py_compile.compile(str(f), doraise=True)
    for script in ("ic-l0-download.py", "ic-l0-auth.py"):
        r = _run([str(PLUGIN / script), "--help"], tmp_path)
        assert r.returncode == 0 and "usage" in r.stdout.lower() and "Traceback" not in r.stderr


def test_no_config_and_no_credentials_give_one_line(tmp_path):
    r = _run([str(PLUGIN / "ic-l0-download.py")], tmp_path)
    assert r.returncode == 2 and "Traceback" not in r.stderr
    assert len(r.stderr.strip().splitlines()) == 1 and "no account" in r.stderr
    conf = {"imap_caldav": {"accounts": {"demo": {"preset": "fastmail", "email": ME}}}}
    r = _run([str(PLUGIN / "ic-l0-download.py")], tmp_path, conf)
    assert r.returncode == 2 and "Traceback" not in r.stderr
    lines = r.stderr.strip().splitlines()
    assert (
        len(lines) == 1 and "SBK_MAILBOX_PASSWORD_DEMO" in lines[0] and "ic-l0-auth.py" in lines[0]
    )
    assert not (tmp_path / "d" / "emails").exists()  # nothing written


def test_download_main_end_to_end(env, monkeypatch):
    server = FakeIMAP(_boxes())
    objs = {"/dav/cal/demo/work/a.ics": ('"e1"', _ics(_vevent("a@demo", _d(2))))}
    _cal_env(env, monkeypatch, FakeDav(objs))
    env["secrets"][("sbk-mailbox", "demo")] = "app-pass"
    monkeypatch.setattr(ic_imap, "IMAP_FACTORY", lambda h, p: server)
    assert L0.main([]) == 0
    summary = json.loads(icc.summary_path().read_text())
    assert summary["failed"] == [] and summary["accounts"]["demo"]["mail"]["messages"] == 3
    assert summary["accounts"]["demo"]["calendar"]["events"] == 1
    assert "demo" not in json.dumps(summary["missing_credentials"])
    runs = json.loads((env["root"] / "last-runs.json").read_text())
    assert icc.PLUGIN_ID in json.dumps(runs)


# --------------------------------------------------------------------------- review regressions


def test_ical_mixed_value_kinds_do_not_stop_the_calendar():
    d = _d(2).strftime("%Y%m%d")
    mixed = (
        f"BEGIN:VEVENT\r\nUID:m1@demo\r\nDTSTART;VALUE=DATE:{d}\r\nDTEND:{d}T110000Z\r\n"
        "SUMMARY:Date start, time end\r\nEND:VEVENT\r\n"
        f"BEGIN:VEVENT\r\nUID:m2@demo\r\nDTSTART:{d}T100000Z\r\n"
        f"DTEND;TZID=Nowhere/Zone:{d}T110000\r\nRRULE:FREQ=DAILY;COUNT=2\r\n"
        "SUMMARY:Aware start, naive end\r\nEND:VEVENT\r\n"
    )
    warns = []
    rows = ic_ical.rows_from_ics(
        _ics(_vevent("ok@demo", _d(3), summary="Fine"), mixed), account="d",
        calendar_name="c", calendar_id="c", own=set(), window=_window(), warn=warns.append,
    )  # fmt: skip
    names = [r["summary"] for r in rows]
    assert "Fine" in names and "Date start, time end" in names
    assert names.count("Aware start, naive end") == 2


def test_one_unreadable_event_is_skipped_not_fatal(monkeypatch):
    real = ic_ical._rows_of_series

    def boom(uid, slot, **kw):
        if uid == "bad@demo":
            raise ValueError("broken")
        return real(uid, slot, **kw)

    monkeypatch.setattr(ic_ical, "_rows_of_series", boom)
    warns = []
    rows = ic_ical.rows_from_ics(
        _ics(_vevent("bad@demo", _d(1)), _vevent("ok@demo", _d(2), summary="Fine")),
        account="d", calendar_name="c", calendar_id="c", own=set(), window=_window(),
        warn=warns.append,
    )  # fmt: skip
    assert [r["summary"] for r in rows] == ["Fine"] and warns


def test_ics_link_error_text_never_carries_the_link(env, monkeypatch):
    import http.client

    env["conf"]["imap_caldav"]["accounts"] = {
        "feed": {"imap_host": "imap.mail.example", "email": ME, "mail": False, "calendar": "ics"}
    }
    env["secrets"][("sbk-ics", "feed")] = "https://cal.mail.example/private/SECRET-TOKEN/basic .ics"

    def send(method, url, headers, body):
        raise http.client.InvalidURL(f"URL can't contain control characters. {url!r}")

    monkeypatch.setattr(icc, "HTTP_SEND", send)
    acc = icc.load_accounts()[0]
    with pytest.raises(icc.SetupError) as e:
        ic_caldav.sync_ics(acc, icc.load_state("feed"), force=False, log=_Log())
    assert "SECRET-TOKEN" not in str(e.value) and "InvalidURL" in str(e.value)


def test_ics_feed_keeps_past_events_and_sets_aside_deleted_future_ones(env, monkeypatch):
    env["conf"]["imap_caldav"]["accounts"] = {
        "feed": {"imap_host": "imap.mail.example", "email": ME, "mail": False, "calendar": "ics"}
    }
    env["secrets"][("sbk-ics", "feed")] = "https://cal.mail.example/private/tok/basic.ics"
    feeds = {
        '"v1"': _ics(
            _vevent("past@demo", _d(-10), summary="Past"),
            _vevent("soon@demo", _d(5), summary="Soon"),
            _vevent("later@demo", _d(7), summary="Later"),
        ),
        '"v2"': _ics(_vevent("soon@demo", _d(5), summary="Soon v2")),  # limited past, one deleted
    }
    current = ['"v1"']

    def send(method, url, headers, body):
        if headers.get("If-None-Match") == current[0]:
            return 304, {}, b""
        return 200, {"etag": current[0]}, feeds[current[0]].encode()

    monkeypatch.setattr(icc, "HTTP_SEND", send)
    acc = icc.load_accounts()[0]
    r1 = ic_caldav.sync_ics(acc, icc.load_state("feed"), force=False, log=_Log())
    ic_caldav.rebuild_events(acc, _Log())
    assert r1["in_feed"] == 3 and r1["fetched"] == 3
    current[0] = '"v2"'
    r2 = ic_caldav.sync_ics(acc, icc.load_state("feed"), force=False, log=_Log())
    ic_caldav.rebuild_events(acc, _Log())
    assert r2["fetched"] == 1 and r2["removed"] == 1 and r2["past_kept"] == 1
    ev = pd.read_parquet(env["root"] / "calendars" / "feed" / "events.parquet")
    assert set(ev["summary"]) == {"Past", "Soon v2"}
    removed = pd.read_parquet(icc.raw_dir("feed") / "removed.parquet")
    assert len(removed) == 1 and "Later" in removed.iloc[0]["ics"]
    assert (icc.raw_dir("feed") / "feed-previous.ics").exists()


class _PartialDav(FakeDav):
    """REPORT answers only the first object asked for; hrefs come back spelled with '@'."""

    def __call__(self, method, url, headers, body):
        if method == "REPORT":
            from urllib.parse import unquote

            asked = [
                unquote(w.decode())
                for w in __import__("re").findall(rb"<d:href>([^<]+)</d:href>", body)
            ]
            by_plain = {unquote(k): v for k, v in self.objects.items()}
            items = []
            for w in asked[: self.answer]:
                et, ics = by_plain[w]
                items.append(
                    (w, f"<d:getetag>{et}</d:getetag><c:calendar-data>{ics}</c:calendar-data>")
                )
            self.calls.append((method, urlsplit(url).path, headers.get("Authorization", ""), body))
            return 207, {}, self._ms(items)
        return super().__call__(method, url, headers, body)


def test_caldav_partial_multiget_is_retried_and_href_spelling_is_one(env, monkeypatch):
    objs = {
        "/dav/cal/demo/work/a%40demo.ics": ('"e1"', _ics(_vevent("a@demo", _d(2), summary="A"))),
        "/dav/cal/demo/work/b%40demo.ics": ('"e2"', _ics(_vevent("b@demo", _d(3), summary="B"))),
    }
    dav = _PartialDav(objs)
    dav.answer = 1
    acc = _cal_env(env, monkeypatch, dav)
    s1 = ic_caldav.sync_caldav(acc, icc.load_state("demo"), force=False, log=_Log())
    assert s1["fetched"] == 1 and s1["calendars"]["Work"]["missed"] == 1
    state = icc.load_state("demo")
    assert all(v["ctag"] == "" for v in state["caldav"].values())  # not trusted yet
    dav.answer = 10
    s2 = ic_caldav.sync_caldav(acc, state, force=False, log=_Log())  # same ctag on the server
    assert s2["fetched"] == 1 and s2["removed"] == 0  # only the missed one, nothing "deleted"
    ic_caldav.rebuild_events(acc, _Log())
    ev = pd.read_parquet(env["root"] / "calendars" / "demo" / "events.parquet")
    assert set(ev["summary"]) == {"A", "B"}
    dav.ctag = "ctag-2"
    s3 = ic_caldav.sync_caldav(acc, icc.load_state("demo"), force=False, log=_Log())
    assert s3["fetched"] == 0 and s3["removed"] == 0
    assert not (icc.raw_dir("demo") / "removed.parquet").exists()


def test_reused_message_id_with_another_date_stays_two_messages():
    folder = {"raw": "INBOX", "name": "INBOX", "flags": set()}
    a = EmailMessage()
    a["Message-ID"] = "<same@acme.example>"
    a["Date"] = "Mon, 02 Nov 2026 10:00:00 +0100"
    a["Subject"] = "one"
    a.set_content("x")
    b = EmailMessage()
    b["Message-ID"] = "<same@acme.example>"
    b["Date"] = "Tue, 03 Nov 2026 10:00:00 +0100"
    b["Subject"] = "two"
    b.set_content("y")
    kw = {
        "account": "demo", "folder": folder, "uidvalidity": 1, "flags": set(),
        "internaldate": "", "size": 0, "max_bytes": 10**7,
    }  # fmt: skip
    assert (
        ic_imap.message_row(a.as_bytes(), uid=1, **kw)["id"]
        != ic_imap.message_row(b.as_bytes(), uid=2, **kw)["id"]
    )


def test_fetch_batches_are_capped_by_bytes(monkeypatch):
    class C:
        def uid(self, cmd, spec, items):
            assert cmd == "FETCH" and items == "(UID RFC822.SIZE)"
            return "OK", [f"{n} (UID {u} RFC822.SIZE {20 * 1024 * 1024})".encode()
                          for n, u in enumerate(spec.split(","), 1)]  # fmt: skip

    batches = ic_imap._batches(C(), list(range(1, 8)), max_bytes=10 * 1024 * 1024)
    # each message counts at most max_bytes (10 MB): 3 per 32 MB request
    assert batches == [[1, 2, 3], [4, 5, 6], [7]]
    many = ic_imap._batches(C(), list(range(1, 120)), max_bytes=100)
    assert max(len(b) for b in many) == ic_imap.FETCH_BATCH


def test_capabilities_after_login_enable_condstore(env, monkeypatch):
    class LateCaps(FakeIMAP):
        def capability(self):
            return "OK", [b"IMAP4rev1 CONDSTORE ENABLE"]

    server = LateCaps(_boxes(), caps=("IMAP4REV1",))
    env["secrets"][("sbk-mailbox", "demo")] = "app-pass"
    monkeypatch.setattr(ic_imap, "IMAP_FACTORY", lambda h, p: server)
    _conn, caps = ic_imap.connect(icc.load_accounts()[0], "app-pass")
    assert "CONDSTORE" in caps and ("ENABLE", "CONDSTORE") in server.calls
