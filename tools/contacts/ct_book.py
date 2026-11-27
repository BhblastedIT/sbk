"""Contacts plugin core: your address book -> the kernel's existing address-book slot.

Inputs (all yours, nothing else):
- a vCard export (.vcf, versions 2.1, 3.0 and 4.0): macOS Contacts, iCloud.com, the iPhone
  Contacts app, Google Contacts, Outlook desktop (one .vcf per contact);
- a CSV export of Google Contacts or Outlook / Outlook.com (they export CSV only);
- Google Contacts read through the People API with your own Google app (ct_google.py).

Output: the rows tagged `contacts:import:<label>` / `contacts:google:<label>` in
<data root>/contacts/contacts.parquet, the slot read by
tools/cross-source/xs-l1-contacts-enrich.py:load_contacts (columns full_name, first_name,
last_name, primary_phone, primary_email, organization, title, all_phones, all_emails). The
same extra columns as the microsoft365 plugin (tools/microsoft365/ms_slots.py) are written:
birthday, last_updated, source, source_id. Rows of every other origin are kept as they are.

Format facts this module relies on (checked 2026-11-25):
- RFC 6350 (vCard 4.0): line folding (CRLF + one space or tab), escaping of \\ , ; and \\n,
  N = family;given;additional;prefixes;suffixes, group.NAME, BDAY like 19960415 or --0415,
  TEL as a tel: URI: https://www.rfc-editor.org/rfc/rfc6350
- RFC 2426 (vCard 3.0): TYPE=work,voice or TYPE=work;TYPE=voice, BDAY:1996-04-15,
  quoted-printable no longer allowed: https://www.rfc-editor.org/rfc/rfc2426
- vCard 2.1 (Outlook desktop, older phones) is not an RFC; its quoted-printable form is read
  the common way (soft line break "=" at the end of a line). Not verifiable on a vendor page.
- Outlook.com and new Outlook export contacts as .csv only:
  https://support.microsoft.com/en-us/outlook/export-contacts-from-outlook-com-or-outlook-on-the-web
  Microsoft and Google show their CSV columns only in pictures, so the header map below is
  built on the usual header names and tested on synthetic files only.
"""

from __future__ import annotations

import calendar
import csv
import hashlib
import io
import json
import os
import quopri
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from text_utils import normalize_phone  # noqa: E402

import sbk_config  # noqa: E402

SOURCE = "contacts"
SOURCE_PREFIX = "contacts:"
# The tag the microsoft365 plugin gives the rows it copies from iphone-contacts.json
# (tools/microsoft365/ms_slots.py SEED_SOURCE): same value, so the two plugins agree.
SEED_SOURCE = "iphone-contacts-json"
OTHER_PLUGIN_PREFIXES = ("microsoft365:",)

SLOT_COLUMNS = [
    "full_name",
    "first_name",
    "last_name",
    "primary_phone",
    "primary_email",
    "organization",
    "title",
    "all_phones",
    "all_emails",
    "birthday",
    "last_updated",
    "source",
    "source_id",
    "kind",
]
# "kind" of a card that is not a person: "org" (a company card, vCard KIND:org or the Apple
# X-ABShowAs:COMPANY flag), "group" or "location" (vCard 4 KIND). Empty for a person. The kernel
# contacts step marks those cards as businesses, and the merge never turns them into people.
NON_PERSON_KINDS = ("org", "group", "location")

LABEL_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
EXPORT_SUFFIXES = (".vcf", ".vcard", ".csv")
# Binary properties: never decoded, never kept (photos can be megabytes each).
_SKIP_PROPS = frozenset({"PHOTO", "LOGO", "SOUND", "KEY"})
_MULTI_SEP = " ::: "  # how Google CSV puts several values in one cell (observed, not documented)


class ContactsError(Exception):
    """A problem worth one clear line to the user (never carries a token)."""


# --------------------------------------------------------------------------- paths


def data_root() -> Path:
    return Path(sbk_config.DATA_ROOT)


def contacts_dir() -> Path:
    """<data root>/contacts: the kernel's address-book folder (sbk_config.CONTACTS_DIR)."""
    return data_root() / "contacts"


def slot_path() -> Path:
    return contacts_dir() / "contacts.parquet"


def raw_dir() -> Path:
    return contacts_dir() / "raw"


def imports_dir(label: str | None = None) -> Path:
    base = raw_dir() / "imports"
    return base / label if label else base


def google_dir(label: str | None = None) -> Path:
    base = raw_dir() / "google"
    return base / label if label else base


def summary_path() -> Path:
    return contacts_dir() / "download-summary.json"


def iphone_json_paths() -> list[Path]:
    """The JSON address book tools/cross-source/xs-l1-contacts-enrich.py reads (data root only)."""
    return [contacts_dir() / "iphone-contacts.json"]


def cfg(key: str, default):
    """A field of the `contacts` section of sbk.config.json."""
    return sbk_config.user_cfg(f"contacts.{key}", default)


def check_label(label: str) -> str:
    label = (label or "").strip().lower()
    if not LABEL_RE.match(label):
        raise ContactsError(
            f"label '{label}' is not valid: lower-case letters, digits, '-' or '_', "
            "at most 40 characters"
        )
    return label


def write_json(path: Path, data) -> None:
    """Atomic write, mode 600 (the files describe people)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def update_summary(key: str, entry: dict) -> dict:
    """<data root>/contacts/download-summary.json keeps one entry per input."""
    data = read_json(summary_path(), {})
    if not isinstance(data, dict):
        data = {}
    inputs = data.get("inputs") if isinstance(data.get("inputs"), dict) else {}
    inputs[key] = entry
    data.update(source=SOURCE, updated_at=datetime.now(UTC).isoformat(), inputs=inputs)
    write_json(summary_path(), data)
    return data


# --------------------------------------------------------------------------- small helpers


def _uniq(values) -> list[str]:
    out: list[str] = []
    for v in values:
        v = (v or "").strip()
        if v and v not in out:
            out.append(v)
    return out


def _clean_email(value: str) -> str:
    v = (value or "").strip()
    if v.lower().startswith("mailto:"):
        v = v[7:]
    v = v.strip().strip("<>").strip()
    return v if "@" in v and " " not in v else ""


def parse_birthday(raw: str, omit_year: str = "") -> str:
    """An ISO date (YYYY-MM-DD), --MM-DD when the year is unknown, or "".

    Accepts the RFC 6350 / RFC 2426 forms (19960415, 1996-04-15, 1996-04-15T..., --0415,
    --04-15). A year equal to Apple's X-APPLE-OMIT-YEAR parameter means "no year" (observed in
    Apple exports, not documented by Apple). Partial dates (only a month, only a day) and
    free text ("circa 1800") give "".
    """
    s = (raw or "").strip()
    if not s:
        return ""
    m = re.fullmatch(r"(\d{4})-?(\d{2})-?(\d{2})(?:T.*)?", s)
    if m:
        y, mo, d = (int(x) for x in m.groups())
        if omit_year and str(y) == str(omit_year).strip():
            y = 0
    else:
        m = re.fullmatch(r"--(\d{2})-?(\d{2})", s)
        if not m:
            return ""
        y, (mo, d) = 0, (int(x) for x in m.groups())
    if not 1 <= mo <= 12:
        return ""
    if not 1 <= d <= calendar.monthrange(y or 2000, mo)[1]:
        return ""
    return f"--{mo:02d}-{d:02d}" if y == 0 else f"{y:04d}-{mo:02d}-{d:02d}"


def contact_row(c: dict, tag: str) -> dict:
    """One slot row from a parsed contact dict."""
    emails = _uniq(_clean_email(e) for e in c.get("emails") or [])
    phones = _uniq(c.get("phones") or [])
    first = (c.get("first_name") or "").strip()
    last = (c.get("last_name") or "").strip()
    org = (c.get("organization") or "").strip()
    full = (c.get("full_name") or "").strip()
    if not full:
        full = " ".join(x for x in (first, (c.get("middle_name") or "").strip(), last) if x)
    if not full and org:
        full = org  # a company card
    if full and not (first or last) and full != org:
        parts = full.split()
        first, last = parts[0], " ".join(parts[1:])
    sid = (c.get("uid") or "").strip()
    if not sid:
        basis = "|".join([full.lower(), *sorted(e.lower() for e in emails), *sorted(phones)])
        sid = "h:" + hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]
    return {
        "full_name": full,
        "first_name": first,
        "last_name": last,
        "primary_phone": phones[0] if phones else "",
        "primary_email": emails[0] if emails else "",
        "organization": org,
        "title": (c.get("title") or "").strip(),
        # "; " because the kernel splits all_phones / all_emails on ";" or ","
        "all_phones": "; ".join(p.replace(";", " ").replace(",", " ") for p in phones),
        "all_emails": "; ".join(emails),
        "birthday": c.get("birthday") or "",
        "last_updated": (c.get("last_updated") or "").strip(),
        "source": tag,
        "source_id": sid,
        "kind": card_kind(c.get("kind")),
    }


def card_kind(kind) -> str:
    """The slot "kind": "org" for a company card, "group" / "location", "" for a person."""
    k = str(kind or "").strip().lower()
    if k in ("org", "organization", "company"):
        return "org"
    return k if k in NON_PERSON_KINDS else ""


# --------------------------------------------------------------------------- vCard


def _logical_lines(fh):
    """Unfolded lines (bytes) of a vCard stream, read line by line.

    RFC 6350 3.2 / RFC 2426: CRLF followed by one space or tab continues the line. A vCard 2.1
    quoted-printable value ending with "=" continues on the next line (soft line break).
    """
    cur: bytes | None = None
    qp = False
    for raw in fh:
        line = raw.rstrip(b"\r\n")
        if cur is not None:
            if qp and cur.endswith(b"="):
                cur = cur[:-1] + line
                continue
            if line[:1] in (b" ", b"\t"):
                cur += line[1:]
                continue
            yield cur
            cur = None
        if not line.strip():
            continue
        cur = line
        head = line.split(b":", 1)[0].upper()
        qp = b"QUOTED-PRINTABLE" in head
    if cur is not None:
        yield cur


def _split_outside_quotes(text: str, sep: str) -> list[str]:
    parts, cur, q = [], [], False
    for ch in text:
        if ch == '"':
            q = not q
        if ch == sep and not q:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    parts.append("".join(cur))
    return parts


def _split_line(line: bytes) -> tuple[bytes, bytes]:
    q = False
    for i, ch in enumerate(line):
        if ch == 0x22:
            q = not q
        elif ch == 0x3A and not q:
            return line[:i], line[i + 1 :]
    return line, b""


def _params(parts: list[str]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if "=" in p:
            k, v = p.split("=", 1)
            k = k.strip().upper()
            vals = [x.strip().strip('"') for x in _split_outside_quotes(v, ",")]
        else:  # vCard 2.1 bare parameter: TEL;CELL;PREF / ;QUOTED-PRINTABLE
            k = (
                "ENCODING"
                if p.upper() in ("QUOTED-PRINTABLE", "BASE64", "8BIT", "7BIT", "B")
                else "TYPE"
            )
            vals = [p]
        out.setdefault(k, []).extend(x for x in vals if x)
    return out


def _decode(value: bytes, params: dict[str, list[str]]) -> str | None:
    enc = (params.get("ENCODING") or [""])[0].upper()
    if enc in ("B", "BASE64"):
        return None
    charset = (params.get("CHARSET") or ["utf-8"])[0]
    data = quopri.decodestring(value) if enc == "QUOTED-PRINTABLE" else value
    for cs in (charset, "utf-8", "cp1252"):
        try:
            return data.decode(cs)
        except (LookupError, UnicodeDecodeError):
            continue
    return data.decode("utf-8", errors="replace")


def _split_escaped(text: str, sep: str = ";") -> list[str]:
    parts, cur, i = [], [], 0
    while i < len(text):
        c = text[i]
        if c == "\\" and i + 1 < len(text):
            cur.append(text[i : i + 2])
            i += 2
            continue
        if c == sep:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(c)
        i += 1
    parts.append("".join(cur))
    return parts


def _unescape(s: str) -> str:
    out, i = [], 0
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s):
            n = s[i + 1]
            out.append("\n" if n in "nN" else n)
            i += 2
            continue
        out.append(c)
        i += 1
    return "".join(out).strip()


def _pref_rank(params: dict[str, list[str]]) -> int:
    for v in params.get("PREF") or []:
        if v.isdigit():
            return int(v)
    types = {t.lower() for t in params.get("TYPE") or []}
    return 1 if "pref" in types else 1000


def _new_card() -> dict:
    return {
        "fn": "",
        "n": [],
        "org": "",
        "title": "",
        "emails": [],
        "phones": [],
        "bday": "",
        "rev": "",
        "uid": "",
        "kind": "",
    }


def _finish(card: dict) -> dict:
    n = card["n"] + [""] * 5
    family, given, additional = n[0], n[1], n[2]
    emails = [v for _, _, v in sorted(card["emails"])]
    phones = [v for _, _, v in sorted(card["phones"])]
    full = card["fn"]
    if not full and card["kind"] in ("org", "company"):
        full = card["org"]
    return {
        "full_name": full,
        "first_name": given,
        "middle_name": additional,
        "last_name": family,
        "organization": card["org"],
        "title": card["title"],
        "emails": emails,
        "phones": phones,
        "birthday": card["bday"],
        "last_updated": card["rev"],
        "uid": card["uid"],
        "kind": card_kind(card["kind"]),
    }


def iter_vcards(fh, stats: dict | None = None):
    """Contacts (dicts) of a vCard stream opened in binary mode; any version, any count."""
    st = stats if stats is not None else {}
    depth = 0
    card = None
    order = 0
    for line in _logical_lines(fh):
        head_b, value_b = _split_line(line)
        head = head_b.decode("utf-8", errors="replace")
        parts = _split_outside_quotes(head, ";")
        name = parts[0].strip().upper()
        if "." in name:
            name = name.split(".", 1)[1]  # item1.EMAIL -> EMAIL
        if name in ("BEGIN", "END"):
            what = value_b.decode("utf-8", errors="replace").strip().upper()
            if what != "VCARD":
                continue
            if name == "BEGIN":
                depth += 1
                if depth == 1:
                    card = _new_card()
            elif depth > 0:
                depth -= 1
                if depth == 0 and card is not None:
                    done = _finish(card)
                    card = None
                    if not (
                        done["full_name"]
                        or done["first_name"]
                        or done["last_name"]
                        or done["organization"]
                        or done["emails"]
                        or done["phones"]
                    ):
                        st["empty_cards"] = st.get("empty_cards", 0) + 1
                        continue
                    st["cards"] = st.get("cards", 0) + 1
                    yield done
            continue
        if depth != 1 or card is None or name in _SKIP_PROPS:
            continue  # outside a card, a nested (AGENT) card, or a binary property
        params = _params(parts[1:])
        text = _decode(value_b, params)
        if text is None:
            continue
        order += 1
        if name == "FN":
            card["fn"] = card["fn"] or _unescape(text)
        elif name == "N":
            card["n"] = [_unescape(x) for x in _split_escaped(text)]
        elif name == "ORG":
            card["org"] = card["org"] or _unescape(_split_escaped(text)[0])
        elif name == "TITLE":
            card["title"] = card["title"] or _unescape(text)
        elif name == "EMAIL":
            email = _clean_email(_unescape(text))
            if email:
                card["emails"].append((_pref_rank(params), order, email))
        elif name == "TEL":
            types = {t.lower() for t in params.get("TYPE") or []}
            if any("fax" in t for t in types):
                continue
            tel = _unescape(text)
            if tel.lower().startswith("tel:"):
                tel = tel[4:].split(";", 1)[0]
            if tel.strip():
                card["phones"].append((_pref_rank(params), order, tel.strip()))
        elif name == "BDAY":
            vtype = (params.get("VALUE") or [""])[0].lower()
            if vtype == "text":
                st["birthdays_unparsed"] = st.get("birthdays_unparsed", 0) + 1
                continue
            omit = (params.get("X-APPLE-OMIT-YEAR") or [""])[0]
            b = parse_birthday(_unescape(text), omit)
            if b:
                card["bday"] = b
            else:
                st["birthdays_unparsed"] = st.get("birthdays_unparsed", 0) + 1
        elif name == "REV":
            card["rev"] = _unescape(text)
        elif name == "UID":
            card["uid"] = _unescape(text)
        elif name == "KIND":
            card["kind"] = _unescape(text).lower()
        elif name == "X-ABSHOWAS" and _unescape(text).upper() == "COMPANY":
            card["kind"] = "company"


def read_vcard_file(path: Path, stats: dict | None = None) -> list[dict]:
    """Contacts of one .vcf file, read line by line (photo-heavy exports stay out of memory).

    A UTF-8 byte-order mark is skipped (otherwise the first BEGIN:VCARD is not seen and the
    first card is lost); a UTF-16 file (byte-order mark FF FE / FE FF) is re-read as text.
    """
    with open(path, "rb") as fh:
        head = fh.read(4)
        if head[:2] in (b"\xff\xfe", b"\xfe\xff"):
            fh.seek(0)
            text = io.TextIOWrapper(fh, encoding="utf-16", errors="replace")
            return list(iter_vcards((line.encode("utf-8") for line in text), stats))
        fh.seek(3 if head[:3] == b"\xef\xbb\xbf" else 0)
        return list(iter_vcards(fh, stats))


# --------------------------------------------------------------------------- CSV


def _norm_header(h: str) -> str:
    return re.sub(r"\s+", " ", (h or "").strip().lower())


_FULL = {"name", "full name", "display name"}
_FIRST = {"first name", "given name"}
_MIDDLE = {"middle name", "additional name"}
_LAST = {"last name", "family name", "surname"}
_ORG = {"company", "company name", "organization", "organization name", "organization 1 - name"}
# Outlook's "Title" column is the honorific (Mr, Dr): only these are the job title.
_TITLE = {"job title", "organization title", "organization 1 - title"}
_BDAY = {"birthday"}


def classify_headers(headers: list[str]) -> dict:
    m: dict = {"full": [], "first": [], "middle": [], "last": [], "org": [], "title": []}
    m.update(emails=[], phones=[], bday=[])
    for h in headers or []:
        n = _norm_header(h)
        if n in _FULL:
            m["full"].append(h)
        elif n in _FIRST:
            m["first"].append(h)
        elif n in _MIDDLE:
            m["middle"].append(h)
        elif n in _LAST:
            m["last"].append(h)
        elif n in _ORG:
            m["org"].append(h)
        elif n in _TITLE:
            m["title"].append(h)
        elif n in _BDAY:
            m["bday"].append(h)
        elif re.fullmatch(r"e-?mail( \d+)?( address)?|e-?mail \d+ address|e-?mail \d+ - value", n):
            m["emails"].append(h)
        # "Phonetic First Name" (Google CSV) contains "phone" but is a name, never a number
        elif ("phone" in n or n == "mobile") and not re.search(r"fax|label|type|phonetic", n):
            m["phones"].append(h)
    return m


def _read_text(path: Path) -> str:
    data = path.read_bytes()
    encodings = ("utf-16",) if data[:2] in (b"\xff\xfe", b"\xfe\xff") else ("utf-8-sig",)
    for enc in encodings:
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("cp1252", errors="replace")


def read_csv_file(path: Path, stats: dict | None = None) -> list[dict]:
    st = stats if stats is not None else {}
    try:
        return _read_csv_rows(path, st)
    except csv.Error as e:  # a NUL byte, a broken quote: one clear line, not a traceback
        raise ContactsError(f"{path.name}: not a readable CSV ({e})") from None


def _read_csv_rows(path: Path, st: dict) -> list[dict]:
    reader = csv.DictReader(io.StringIO(_read_text(path)))
    m = classify_headers(reader.fieldnames or [])
    if not (m["full"] or m["first"] or m["last"]) or not (m["emails"] or m["phones"]):
        raise ContactsError(
            f"{path.name}: not a contacts CSV this plugin knows (it needs a name column and an "
            "e-mail or phone column, as in the Google or Outlook export)"
        )

    def first_of(row, cols):
        for c in cols:
            v = (row.get(c) or "").strip()
            if v:
                return v
        return ""

    def many(row, cols):
        out = []
        for c in cols:
            for v in (row.get(c) or "").split(_MULTI_SEP.strip()):
                if v.strip():
                    out.append(v.strip())
        return out

    out = []
    for row in reader:
        b_raw = first_of(row, m["bday"])
        bday = parse_birthday(b_raw.replace("/", "-")) if b_raw else ""
        if b_raw and not bday:
            st["birthdays_unparsed"] = st.get("birthdays_unparsed", 0) + 1
        c = {
            "full_name": first_of(row, m["full"]),
            "first_name": first_of(row, m["first"]),
            "middle_name": first_of(row, m["middle"]),
            "last_name": first_of(row, m["last"]),
            "organization": first_of(row, m["org"]),
            "title": first_of(row, m["title"]),
            "emails": many(row, m["emails"]),
            "phones": many(row, m["phones"]),
            "birthday": bday,
            "last_updated": "",
            "uid": "",
        }
        if c["full_name"] or c["first_name"] or c["last_name"] or c["emails"] or c["phones"]:
            out.append(c)
    st["cards"] = st.get("cards", 0) + len(out)
    return out


def read_export(path: Path, stats: dict | None = None) -> list[dict]:
    """Contacts of one exported file, chosen by its extension."""
    suffix = path.suffix.lower()
    if suffix in (".vcf", ".vcard"):
        return read_vcard_file(path, stats)
    if suffix == ".csv":
        return read_csv_file(path, stats)
    raise ContactsError(f"{path.name}: not a .vcf or .csv export")


def export_files(paths: list[Path]) -> list[Path]:
    """The .vcf / .csv files named, or found inside the folders named (one level and below)."""
    files: list[Path] = []
    for p in paths:
        p = Path(p).expanduser()
        if p.is_dir():
            files += sorted(
                f
                for f in p.rglob("*")
                if f.is_file()
                and f.suffix.lower() in EXPORT_SUFFIXES
                and not f.name.startswith(".")
            )
        elif p.is_file():
            files.append(p)
        else:
            raise ContactsError(f"{p}: no such file or folder")
    return files


# --------------------------------------------------------------------------- slot


def _as_text(v) -> str:
    """A slot cell as text: "" for a missing value, str(v) otherwise (what the kernel reads)."""
    if isinstance(v, str):
        return v
    if v is None:
        return ""
    missing = pd.isna(v)
    if not hasattr(missing, "__len__") and bool(missing):
        return ""
    return str(v)


def _fill_text(out: pd.DataFrame) -> pd.DataFrame:
    """No NaN in text columns: the kernel reads str(row.get(col)) and would see "nan".

    The slot columns are made text for every row: a parquet you made yourself may hold a
    date or a number in `birthday` or `last_updated`, and mixing it with this plugin's text
    would make the parquet write fail. The kernel reads those cells with str() anyway, so the
    value it sees does not change. Other columns follow tools/microsoft365/ms_slots.py:
    only all-text columns are filled, so a bool or number column of someone else's rows still
    writes.
    """
    for c in out.columns:
        if c in SLOT_COLUMNS:
            out[c] = out[c].map(_as_text).astype(object)
            continue
        values = out[c].dropna()
        if out[c].dtype == object and values.map(lambda v: isinstance(v, str)).all():
            out[c] = out[c].where(out[c].notna(), "")
    return out


def dedupe(rows: list[dict]) -> tuple[list[dict], int]:
    """One row per (source, source_id), then one per (name, primary e-mail, primary phone)."""
    seen_ids: set = set()
    seen_keys: set = set()
    out, dropped = [], 0
    for r in rows:
        if not (r["full_name"] or r["primary_email"] or r["primary_phone"]):
            dropped += 1
            continue
        sid = (r["source"], r["source_id"])
        key = (
            r["full_name"].lower(),
            r["primary_email"].lower(),
            # the shared normaliser: "07700 900123" and "+44 7700 900123" are one number
            normalize_phone(r["primary_phone"]) or re.sub(r"\D", "", r["primary_phone"]),
        )
        if sid in seen_ids or key in seen_keys:
            dropped += 1
            continue
        seen_ids.add(sid)
        seen_keys.add(key)
        out.append(r)
    return out, dropped


def _sources(df: pd.DataFrame) -> pd.Series:
    if "source" not in df.columns:
        return pd.Series([""] * len(df), index=df.index)
    return df["source"].fillna("").astype(str)


def plugin_made(existing: pd.DataFrame | None) -> bool:
    """True when the slot holds only rows written by plugins (this one, microsoft365, or the
    iPhone JSON seed): the parquet exists because of plugins, not because you made it."""
    if existing is None or not len(existing):
        return True
    src = _sources(existing)
    ok = src.str.startswith(SOURCE_PREFIX) | (src == SEED_SOURCE)
    for p in OTHER_PLUGIN_PREFIXES:
        ok |= src.str.startswith(p)
    return bool(ok.all())


def seed_rows(path: Path) -> list[dict]:
    """Rows for the contacts of iphone-contacts.json, tagged SEED_SOURCE.

    tools/cross-source/xs-l1-contacts-enrich.py:load_contacts reads that JSON as the address
    book only while contacts.parquet is missing; once the parquet exists the JSON is only an
    enrichment keyed by name. Creating the parquet without these rows would drop them.
    """
    raw = read_json(path, {})
    items = raw.get("contacts", []) if isinstance(raw, dict) else raw
    rows = []
    for c in items or []:
        if not isinstance(c, dict):
            continue
        row = contact_row(
            {
                "full_name": str(c.get("name") or ""),
                "organization": str(c.get("organization") or ""),
                "emails": [str(e) for e in c.get("emails") or []],
                "phones": [str(p) for p in c.get("phones") or []],
                "birthday": str(c.get("birthday") or ""),
                "last_updated": str(c.get("last_updated") or ""),
            },
            SEED_SOURCE,
        )
        row["source_id"] = ""
        rows.append(row)
    return rows


def merge_slot(existing: pd.DataFrame | None, ours: list[dict]) -> tuple[pd.DataFrame, int]:
    """New slot: every row of other origins kept, every `contacts:` row replaced by `ours`.

    While the slot holds only plugin rows, the iPhone JSON seed is refreshed from the JSON
    (when it exists). Returns (table, seeded rows).
    """
    seeded = 0
    base = existing.copy() if existing is not None and len(existing) else None
    if plugin_made(base):
        for jp in iphone_json_paths():
            if jp.is_file():
                seed = seed_rows(jp)
                if base is not None:
                    base = base[_sources(base) != SEED_SOURCE]
                frames = [
                    f
                    for f in (base, pd.DataFrame(seed, columns=SLOT_COLUMNS))
                    if f is not None and len(f)
                ]
                base = pd.concat(frames, ignore_index=True) if frames else None
                seeded = len(seed)
                break
    new = pd.DataFrame(ours, columns=SLOT_COLUMNS)
    if base is None or not len(base):
        return _fill_text(new.reset_index(drop=True)), seeded
    base = base[~_sources(base).str.startswith(SOURCE_PREFIX)]
    out = pd.concat([f for f in (base, new) if len(f)] or [new], ignore_index=True)
    return _fill_text(out), seeded


def read_slot() -> pd.DataFrame | None:
    p = slot_path()
    if not p.is_file():
        return None
    try:
        return pd.read_parquet(p)
    except Exception as e:  # noqa: BLE001 - an unreadable slot must not be overwritten
        raise ContactsError(f"{p} cannot be read ({type(e).__name__}); fix or move it first") from e


def write_slot(df: pd.DataFrame) -> Path:
    return sbk_config.safe_write_parquet(df, slot_path(), index=False)
