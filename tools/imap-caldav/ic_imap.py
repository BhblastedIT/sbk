"""imap-caldav plugin: IMAP side (TLS only). Reads folders read-only, incremental by UID and,
where the server offers CONDSTORE (RFC 7162), by MODSEQ for flag changes.

Output rows have the same columns as the Gmail downloader (tools/email/em-l0-download.py
parse_message), so tools/email/em-l1-enrich.py reads them unchanged.
"""

from __future__ import annotations

import hashlib
import imaplib
import json
import re
import ssl
from datetime import UTC, date, datetime, timedelta
from email import message_from_bytes, policy
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser

import ic_common as icc

BODY_TEXT_MAX_CHARS = 200_000  # same cap as em-l0-download.py
FETCH_BATCH = 50  # messages per FETCH at most
FETCH_BYTES = 32 * 1024 * 1024  # and at most this many message bytes per FETCH (memory)
SIZE_BATCH = 400  # UIDs per RFC822.SIZE request
CHUNK_ROWS = 500
CHUNK_CHARS = 40_000_000  # body characters held in memory before a chunk is written
FLAG_LABELS = {"UNREAD", "STARRED", "DRAFT"}
SPECIAL_LABEL = {
    "\\sent": "SENT",
    "\\archive": "ARCHIVE",
    "\\drafts": "DRAFT",
    "\\flagged": "STARRED",
}
SKIP_IN_ALL = {"\\noselect", "\\nonexistent", "\\junk", "\\trash", "\\drafts", "\\all", "\\flagged"}
SENT_FALLBACK_NAMES = ("sent", "sent messages", "sent items", "sent mail", "inbox.sent")

MAIL_COLUMNS = [
    "id", "thread_id", "date", "from_addr", "to_addr", "cc", "bcc", "subject", "body_text",
    "body_truncated", "labels", "message_id", "in_reply_to", "snippet", "has_attachments",
    "attachment_count", "attachments_json", "list_unsubscribe", "list_id", "precedence",
    "auto_submitted",
]  # fmt: skip
INTERNAL_COLUMNS = ["_ic_folder", "_ic_uidvalidity", "_ic_uid"]


# --- Connection ----------------------------------------------------------------------------
def _ssl_factory(host: str, port: int):
    return imaplib.IMAP4_SSL(host, port, ssl_context=ssl.create_default_context(), timeout=60)


IMAP_FACTORY = _ssl_factory  # tests replace this


def connect(acc: icc.Account, password: str | None):
    conn = IMAP_FACTORY(acc.imap_host, acc.imap_port)
    try:
        _sign_in(conn, acc, password)
    except BaseException:
        try:
            conn.shutdown()
        except Exception:  # noqa: BLE001
            pass
        raise
    caps = {c.upper() for c in _caps(conn)}
    try:  # many servers list CONDSTORE / ENABLE only after the login, imaplib keeps the first list
        typ, dat = conn.capability()
        if typ == "OK" and dat and dat[-1]:
            line = dat[-1].decode() if isinstance(dat[-1], bytes) else str(dat[-1])
            caps |= {c.upper() for c in line.split()}
            conn.capabilities = tuple(sorted(caps))  # imaplib's enable() checks this list
    except Exception:  # noqa: BLE001
        pass
    if "CONDSTORE" in caps and "ENABLE" in caps:
        try:
            conn.enable("CONDSTORE")
        except Exception:  # noqa: BLE001 - optional; without it we fall back to UIDNEXT
            pass
    return conn, caps


def _sign_in(conn, acc: icc.Account, password: str | None) -> None:
    try:
        if acc.auth == "xoauth2":
            token = icc.ms_refresh_access_token(acc)
            sasl = f"user={acc.username}\x01auth=Bearer {token}\x01\x01".encode()
            conn.authenticate("XOAUTH2", lambda _challenge: sasl)
        else:
            conn.login(acc.username, password or "")
    except UnicodeEncodeError:  # its message would quote a character of the password
        raise icc.SetupError(
            f"{icc.PLUGIN_ID}: '{acc.label}': the mailbox password has non-ASCII characters"
        ) from None
    except imaplib.IMAP4.error as e:
        reason = str(e).replace("\n", " ")[:200]
        how = "--xoauth2" if acc.auth == "xoauth2" else "--imap"
        raise icc.SetupError(
            f"{icc.PLUGIN_ID}: '{acc.label}': {acc.imap_host} refused the login ({reason}); "
            f"check the user name and sign-in (tools/imap-caldav/ic-l0-auth.py --account "
            f"{acc.label} {how})"
        ) from None


def _caps(conn) -> list[str]:
    caps = getattr(conn, "capabilities", ()) or ()
    return [c.decode() if isinstance(c, bytes) else str(c) for c in caps]


# --- Modified UTF-7 (RFC 3501 5.1.3) -------------------------------------------------------
def decode_mutf7(name: str) -> str:
    out, i = [], 0
    while i < len(name):
        ch = name[i]
        if ch == "&":
            j = name.find("-", i)
            if j == -1:
                out.append(name[i:])
                break
            chunk = name[i + 1 : j]
            if chunk == "":
                out.append("&")
            else:
                b64 = chunk.replace(",", "/")
                b64 += "=" * (-len(b64) % 4)
                try:
                    import base64

                    out.append(base64.b64decode(b64).decode("utf-16-be"))
                except Exception:  # noqa: BLE001
                    out.append(name[i : j + 1])
            i = j + 1
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def quote_mailbox(raw: str) -> str:
    return '"' + raw.replace("\\", "\\\\").replace('"', '\\"') + '"'


_LIST_RE = re.compile(r'^\((?P<flags>[^)]*)\)\s+(?P<delim>"(?:[^"\\]|\\.)*"|NIL)\s+(?P<name>.*)$')


def _unquote(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        return re.sub(r"\\(.)", r"\1", s[1:-1])
    return s


def list_folders(conn) -> list[dict]:
    typ, data = conn.list()
    if typ != "OK":
        raise RuntimeError(f"LIST failed: {data!r}")
    out = []
    for item in data or []:
        if item is None:
            continue
        if isinstance(item, tuple):  # literal mailbox name
            head = item[0].decode("utf-8", "replace")
            name = item[1].decode("utf-8", "replace")
            m = _LIST_RE.match(head.rsplit("{", 1)[0].strip() + " X")
            if not m:
                continue
            flags = m.group("flags")
        else:
            line = item.decode("utf-8", "replace") if isinstance(item, bytes) else str(item)
            m = _LIST_RE.match(line)
            if not m:
                continue
            flags, name = m.group("flags"), _unquote(m.group("name"))
        fl = {f.lower() for f in flags.split()}
        out.append({"raw": name, "name": decode_mutf7(name), "flags": fl})
    return out


def folder_label(f: dict) -> str:
    if f["raw"].upper() == "INBOX":
        return "INBOX"
    for flag, label in SPECIAL_LABEL.items():
        if flag in f["flags"]:
            return label
    if f["name"].strip().lower() in SENT_FALLBACK_NAMES:
        return "SENT"
    return f["name"].replace(",", " ")


def choose_folders(folders: list[dict], wanted) -> list[dict]:
    if isinstance(wanted, list):
        names = {str(w).lower() for w in wanted}
        return [f for f in folders if f["name"].lower() in names or f["raw"].lower() in names]
    if str(wanted).lower() == "all":
        return [f for f in folders if not (f["flags"] & SKIP_IN_ALL)]
    # auto: INBOX + the sent folder (SPECIAL-USE \Sent, RFC 6154, else a well-known name)
    chosen = [f for f in folders if f["raw"].upper() == "INBOX"]
    sent = [f for f in folders if "\\sent" in f["flags"]]
    if not sent:
        sent = [f for f in folders if f["name"].strip().lower() in SENT_FALLBACK_NAMES][:1]
    return chosen + [f for f in sent if f not in chosen]


# --- Message parsing -----------------------------------------------------------------------
class _HTMLStripper(HTMLParser):
    _BLOCK = frozenset(("br", "p", "div", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6"))
    _SKIP = frozenset(("style", "script", "head"))

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self.skip += 1
        elif tag in self._BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self._SKIP and self.skip:
            self.skip -= 1
        elif tag in self._BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def strip_html(html: str) -> str:
    s = _HTMLStripper()
    try:
        s.feed(html)
        text = "".join(s.parts)
    except Exception:  # noqa: BLE001
        text = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _header(msg, name: str) -> str:
    try:
        v = msg.get(name)
        return "" if v is None else str(v)
    except Exception:  # noqa: BLE001 - malformed header: decode by hand
        try:
            raw = msg.get_all(name, failobj=[""])[0]
            return str(make_header(decode_header(str(raw))))
        except Exception:  # noqa: BLE001
            return ""


def _part_text(part) -> str:
    try:
        return part.get_content()
    except Exception:  # noqa: BLE001 - unknown charset or broken encoding
        payload = part.get_payload(decode=True) or b""
        return payload.decode(part.get_content_charset() or "utf-8", "replace")


def extract_body(msg) -> str:
    try:
        body = msg.get_body(preferencelist=("plain", "html"))
    except Exception:  # noqa: BLE001
        body = None
    if body is None:
        return ""
    text = _part_text(body)
    if body.get_content_type() == "text/html":
        return strip_html(text)
    return text.strip()


def extract_attachments(msg) -> list[dict]:
    atts = []
    for part in msg.walk():
        if part.is_multipart():
            continue
        try:
            fn = part.get_filename() or ""
            disp = part.get_content_disposition()
        except Exception:  # noqa: BLE001
            continue
        if not fn and disp != "attachment":
            continue
        try:
            size = len(part.get_payload(decode=True) or b"")
        except Exception:  # noqa: BLE001
            size = 0
        atts.append(
            {
                "filename": fn,
                "mime_type": part.get_content_type(),
                "size": size,
                "attachment_id": "",
            }
        )
    return atts


_MSGID_RE = re.compile(r"<[^<>\s]+>")
_MONTHS = {
    m: i
    for i, m in enumerate(
        ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1
    )
}


def parse_internaldate(s: str) -> datetime | None:
    m = re.match(
        r"\s*(\d{1,2})-([A-Za-z]{3})-(\d{4}) (\d{2}):(\d{2}):(\d{2}) ([+-])(\d{2})(\d{2})", s or ""
    )
    if not m:
        return None
    d, mon, y, hh, mm, ss, sign, oh, om = m.groups()
    off = timedelta(hours=int(oh), minutes=int(om)) * (1 if sign == "+" else -1)
    naive = datetime(int(y), _MONTHS.get(mon.title(), 1), int(d), int(hh), int(mm), int(ss))
    return (naive - off).replace(tzinfo=UTC)


def _hash(*parts: str, n: int = 24) -> str:
    return hashlib.sha1("\x00".join(parts).encode("utf-8", "replace")).hexdigest()[:n]


def message_row(
    raw: bytes,
    *,
    account: str,
    folder: dict,
    uidvalidity: int,
    uid: int,
    flags: set[str],
    internaldate: str,
    size: int,
    max_bytes: int,
) -> dict:
    msg = message_from_bytes(raw, policy=policy.default)
    message_id = (_MSGID_RE.findall(_header(msg, "Message-ID")) or [""])[0]
    in_reply_to = (_MSGID_RE.findall(_header(msg, "In-Reply-To")) or [""])[0]
    refs = _MSGID_RE.findall(_header(msg, "References"))
    root = refs[0] if refs else (in_reply_to or message_id)
    if message_id:
        # Message-ID + Date header: the same message copied into two folders keeps one id,
        # while two different messages that reuse a Message-ID (it happens) stay two rows.
        mid = "ic-" + _hash(account, message_id.lower(), _header(msg, "Date").strip())
    else:
        mid = "ic-" + _hash(account, folder["raw"], str(uidvalidity), str(uid))
    thread_id = "ic-t" + _hash(account, (root or mid).lower(), n=20)

    dt = parse_internaldate(internaldate)
    if dt is None:
        try:
            dt = parsedate_to_datetime(_header(msg, "Date"))
            dt = dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
        except Exception:  # noqa: BLE001
            dt = None

    body = extract_body(msg)
    atts = extract_attachments(msg)
    labels = {folder_label(folder)}
    fl = {f.lower() for f in flags}
    if "\\seen" not in fl:
        labels.add("UNREAD")
    if "\\flagged" in fl:
        labels.add("STARRED")
    if "\\draft" in fl:
        labels.add("DRAFT")
    snippet = re.sub(r"\s+", " ", body)[:200]
    return {
        "id": mid,
        "thread_id": thread_id,
        "date": dt,
        "from_addr": _header(msg, "From"),
        "to_addr": _header(msg, "To"),
        "cc": _header(msg, "Cc"),
        "bcc": _header(msg, "Bcc"),
        "subject": _header(msg, "Subject"),
        "body_text": body[:BODY_TEXT_MAX_CHARS],
        "body_truncated": len(body) > BODY_TEXT_MAX_CHARS or size > max_bytes,
        "labels": ",".join(sorted(labels)),
        "message_id": message_id,
        "in_reply_to": in_reply_to,
        "snippet": snippet,
        "has_attachments": len(atts) > 0,
        "attachment_count": len(atts),
        "attachments_json": json.dumps(atts, ensure_ascii=False) if atts else "",
        "list_unsubscribe": _header(msg, "List-Unsubscribe")[:500],
        "list_id": _header(msg, "List-Id")[:300],
        "precedence": _header(msg, "Precedence")[:50],
        "auto_submitted": _header(msg, "Auto-Submitted")[:50],
        "_ic_folder": folder["raw"],
        "_ic_uidvalidity": int(uidvalidity),
        "_ic_uid": int(uid),
    }


# --- FETCH response parsing ----------------------------------------------------------------
_UID_RE = re.compile(rb"\bUID (\d+)")
_FLAGS_RE = re.compile(rb"\bFLAGS \(([^)]*)\)")
_IDATE_RE = re.compile(rb'\bINTERNALDATE "([^"]+)"')
_SIZE_RE = re.compile(rb"\bRFC822\.SIZE (\d+)")
_MODSEQ_RE = re.compile(rb"\bMODSEQ \((\d+)\)")


def parse_fetch(data) -> list[dict]:
    """imaplib FETCH data -> [{uid, flags, internaldate, size, body}] (meta may follow the literal)."""
    items: list[dict] = []
    cur = None
    for part in data or []:
        if isinstance(part, tuple):
            cur = {"meta": part[0], "body": part[1]}
            items.append(cur)
        elif isinstance(part, bytes):
            if cur is not None and part.strip() and not re.match(rb"^\d+ \(", part):
                cur["meta"] += b" " + part
            elif re.match(rb"^\d+ \(", part):
                cur = {"meta": part, "body": None}
                items.append(cur)
    out = []
    for it in items:
        meta = it["meta"]
        m = _UID_RE.search(meta)
        if not m:
            continue
        fl = _FLAGS_RE.search(meta)
        idate = _IDATE_RE.search(meta)
        size = _SIZE_RE.search(meta)
        out.append(
            {
                "uid": int(m.group(1)),
                "flags": set(fl.group(1).decode("ascii", "replace").split()) if fl else set(),
                "internaldate": idate.group(1).decode("ascii", "replace") if idate else "",
                "size": int(size.group(1)) if size else len(it["body"] or b""),
                "body": it["body"],
            }
        )
    return out


def _resp_int(conn, code: str) -> int:
    try:
        typ, dat = conn.response(code)
        vals = [v for v in (dat or []) if v is not None]
        if not vals:
            return 0
        v = vals[-1]
        v = v.decode() if isinstance(v, bytes) else str(v)
        return int(v.split()[0])
    except Exception:  # noqa: BLE001
        return 0


def imap_date(d: str) -> str:
    y, m, dd = (int(x) for x in d.split("-"))
    return date(y, m, dd).strftime("%d-") + list(_MONTHS)[m - 1] + f"-{y}"


def _batches(conn, uids: list[int], max_bytes: int) -> list[list[int]]:
    """UIDs grouped for FETCH: at most FETCH_BATCH messages and about FETCH_BYTES of message data
    per request (sizes asked first with RFC822.SIZE), so a folder of large messages never puts
    hundreds of megabytes in memory at once."""
    sizes: dict[int, int] = {}
    for i in range(0, len(uids), SIZE_BATCH):
        part = uids[i : i + SIZE_BATCH]
        try:
            typ, data = conn.uid("FETCH", ",".join(str(u) for u in part), "(UID RFC822.SIZE)")
        except Exception:  # noqa: BLE001 - sizes only help batching: fall back to counts
            typ, data = "NO", None
        if typ == "OK":
            for it in parse_fetch(data):
                sizes[it["uid"]] = it["size"]
    out: list[list[int]] = []
    cur: list[int] = []
    cur_bytes = 0
    for u in uids:
        b = min(sizes.get(u, 0), max_bytes)
        if cur and (len(cur) >= FETCH_BATCH or cur_bytes + b > FETCH_BYTES):
            out.append(cur)
            cur, cur_bytes = [], 0
        cur.append(u)
        cur_bytes += b
    if cur:
        out.append(cur)
    return out


def sync_folder(
    conn,
    acc: icc.Account,
    folder: dict,
    fstate: dict,
    *,
    since: str,
    force: bool,
    uid_to_id: dict,
    on_rows,
    log,
) -> dict:
    """Fetch new messages of one folder. Calls on_rows(rows, last_uid) per chunk, which must
    persist them and the state. Returns {"new": n, "flag_updates": {id: set(flag labels)}}."""
    typ, _ = conn.select(quote_mailbox(folder["raw"]), readonly=True)
    if typ != "OK":
        raise RuntimeError(f"SELECT {folder['name']} failed")
    uidvalidity = _resp_int(conn, "UIDVALIDITY")
    uidnext = _resp_int(conn, "UIDNEXT")
    modseq = _resp_int(conn, "HIGHESTMODSEQ")
    if fstate.get("uidvalidity") != uidvalidity:
        if fstate.get("uidvalidity"):
            log.warning(f"  {folder['name']}: UIDVALIDITY changed, the folder is read again")
        fstate.clear()
        fstate.update({"uidvalidity": uidvalidity, "last_uid": 0})
    last_uid = int(fstate.get("last_uid", 0))
    result = {"new": 0, "flag_updates": {}, "skipped": False}

    unchanged_new = bool(uidnext) and fstate.get("uidnext") == uidnext
    unchanged_flags = (not modseq) or fstate.get("modseq") == modseq
    if not force and last_uid and unchanged_new and unchanged_flags:
        result["skipped"] = True
        return result

    # Flag changes since the last run (CONDSTORE CHANGEDSINCE, RFC 7162).
    if modseq and fstate.get("modseq") and last_uid and modseq != fstate.get("modseq"):
        typ, data = conn.uid(
            "FETCH", f"1:{last_uid}", "(UID FLAGS)", f"(CHANGEDSINCE {int(fstate['modseq'])})"
        )
        if typ == "OK":
            for it in parse_fetch(data):
                key = (folder["raw"], uidvalidity, it["uid"])
                mid = uid_to_id.get(key)
                if not mid:
                    continue
                fl = {f.lower() for f in it["flags"]}
                labs = set()
                if "\\seen" not in fl:
                    labs.add("UNREAD")
                if "\\flagged" in fl:
                    labs.add("STARRED")
                if "\\draft" in fl:
                    labs.add("DRAFT")
                result["flag_updates"][mid] = labs

    if last_uid:
        typ, data = conn.uid("SEARCH", "UID", f"{last_uid + 1}:*")
    elif since:
        typ, data = conn.uid("SEARCH", "SINCE", imap_date(since))
    else:
        typ, data = conn.uid("SEARCH", "ALL")
    if typ != "OK":
        raise RuntimeError(f"SEARCH {folder['name']} failed")
    uids = sorted({int(x) for x in b" ".join(d for d in data if d).split()} if data else set())
    uids = [u for u in uids if u > last_uid]
    max_bytes = int(acc.max_message_mb * 1024 * 1024)

    batches = _batches(conn, uids, max_bytes)
    rows: list[dict] = []
    chars = 0
    for n, batch in enumerate(batches, 1):
        typ, data = conn.uid(
            "FETCH",
            ",".join(str(u) for u in batch),
            f"(UID FLAGS INTERNALDATE RFC822.SIZE BODY.PEEK[]<0.{max_bytes}>)",
        )
        if typ != "OK":
            raise RuntimeError(f"FETCH {folder['name']} failed")
        for it in parse_fetch(data):
            if it["body"] is None:
                continue
            try:
                row = message_row(
                    it["body"],
                    account=acc.label,
                    folder=folder,
                    uidvalidity=uidvalidity,
                    uid=it["uid"],
                    flags=it["flags"],
                    internaldate=it["internaldate"],
                    size=it["size"],
                    max_bytes=max_bytes,
                )
            except Exception as e:  # noqa: BLE001 - one broken message never stops the folder
                log.warning(f"  {folder['name']} uid {it['uid']}: not parsed ({type(e).__name__})")
                continue
            rows.append(row)
            chars += len(row["body_text"])
        if rows and (len(rows) >= CHUNK_ROWS or chars >= CHUNK_CHARS or n == len(batches)):
            top = max(batch)
            on_rows(rows, top)
            result["new"] += len(rows)
            fstate["last_uid"] = top
            rows, chars = [], 0
    if uids:
        fstate["last_uid"] = max(max(uids), int(fstate.get("last_uid", 0)))
    fstate["uidnext"] = uidnext
    if modseq:
        # Promoted to "modseq" by sync_account only after the flag changes reach the slot.
        fstate["modseq_pending"] = modseq
    return result


# --- Local store: chunks -> messages.parquet (slot) + uid map (plugin state) ------------------
def uidmap_path(account: str):
    return icc.state_dir() / f"{account}-uids.parquet"


def load_uidmap(account: str) -> dict:
    """{(folder, uidvalidity, uid): id} from the plugin's own uid map."""
    import pandas as pd

    p = uidmap_path(account)
    if not p.exists():
        return {}
    df = pd.read_parquet(p)
    keys = zip(df["_ic_folder"], df["_ic_uidvalidity"].astype(int), df["_ic_uid"].astype(int))
    return dict(zip(keys, df["id"]))


def write_chunk(account: str, rows: list[dict], seq: int) -> None:
    import pandas as pd

    d = icc.chunks_dir(account)
    d.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows, columns=MAIL_COLUMNS + INTERNAL_COLUMNS)
    df["date"] = pd.to_datetime(df["date"], utc=True, errors="coerce")
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f")
    icc.cfg.safe_write_parquet(df, d / f"{stamp}-{seq:05d}.parquet", index=False)


def _merge_labels(labels_in_order) -> str:
    """Folder labels: union of every copy. Flag labels: the newest copy only."""
    folder_labels: set[str] = set()
    newest = ""
    for lab in labels_in_order:
        folder_labels |= {x for x in str(lab or "").split(",") if x and x not in FLAG_LABELS}
        newest = str(lab or "")
    flags = {x for x in newest.split(",") if x in FLAG_LABELS}
    return ",".join(sorted(folder_labels | flags))


def merge_into_slot(acc: icc.Account, flag_updates: dict | None = None) -> dict:
    """Fold pending chunks and flag changes into <emails>/<label>/messages.parquet.

    Never drops a message: rows already in the slot stay; a message seen in two folders keeps
    one row with both folder labels. Returns {"messages": n, "added": n, "flag_changes": n}.
    """
    import pandas as pd

    slot = icc.mail_slot(acc.label)
    main = slot / "messages.parquet"
    chunks = sorted(icc.chunks_dir(acc.label).glob("*.parquet"))
    flag_updates = flag_updates or {}
    if not chunks and not flag_updates:
        n = len(pd.read_parquet(main, columns=["id"])) if main.exists() else 0
        return {"messages": n, "added": 0, "flag_changes": 0}

    icc.claim_slot(slot, "messages.parquet")
    parts = []
    before_ids: set = set()
    if main.exists():
        old = pd.read_parquet(main)
        before_ids = set(old["id"].astype(str))
        parts.append(old.assign(_order=0))
    new_parts = [pd.read_parquet(c) for c in chunks]
    for i, df in enumerate(new_parts, start=1):
        parts.append(df.drop(columns=INTERNAL_COLUMNS, errors="ignore").assign(_order=i))
    allrows = pd.concat(parts, ignore_index=True).sort_values("_order", kind="stable")

    dup = allrows["id"].duplicated(keep=False)
    if dup.any():
        seen: dict[str, list] = {}
        for mid, lab in zip(allrows.loc[dup, "id"], allrows.loc[dup, "labels"]):
            seen.setdefault(mid, []).append(lab)  # rows are in _order: oldest first
        merged_labels = {mid: _merge_labels(labs) for mid, labs in seen.items()}
        allrows = allrows.drop_duplicates("id", keep="last").copy()
        has = allrows["id"].isin(merged_labels.keys())
        allrows.loc[has, "labels"] = allrows.loc[has, "id"].map(merged_labels)
    else:
        allrows = allrows.copy()

    changed = 0
    if flag_updates:
        upd = allrows["id"].isin(flag_updates.keys())
        for idx in allrows.index[upd]:
            mid = allrows.at[idx, "id"]
            base = {x for x in str(allrows.at[idx, "labels"] or "").split(",") if x}
            new = (base - FLAG_LABELS) | set(flag_updates[mid])
            if new != base:
                allrows.at[idx, "labels"] = ",".join(sorted(new))
                changed += 1

    out = allrows.drop(columns=["_order"])
    out = out[[c for c in MAIL_COLUMNS if c in out.columns]]
    out["date"] = pd.to_datetime(out["date"], utc=True, errors="coerce")
    out = out.sort_values("date", ascending=False, na_position="last").reset_index(drop=True)
    icc.cfg.safe_write_parquet(out, main, index=False)

    # uid map: old map + the (folder, uidvalidity, uid) of every new copy.
    if new_parts:
        um_new = pd.concat([df[["id"] + INTERNAL_COLUMNS] for df in new_parts], ignore_index=True)
        um_path = uidmap_path(acc.label)
        if um_path.exists():
            um_new = pd.concat([pd.read_parquet(um_path), um_new], ignore_index=True)
        um_new = um_new.drop_duplicates(INTERNAL_COLUMNS, keep="last").reset_index(drop=True)
        icc.cfg.safe_write_parquet(um_new, um_path, index=False)
    # The chunks are this plugin's own temporary files, now folded into the slot.
    for c in chunks:
        c.unlink(missing_ok=True)
    added = len(set(out["id"].astype(str)) - before_ids)
    return {"messages": len(out), "added": added, "flag_changes": changed}


def sync_account(acc: icc.Account, state: dict, *, since: str, force: bool, log) -> dict:
    """Read the chosen folders of one mailbox into its slot. Returns a summary dict."""
    icc.check_label_free(acc)
    icc.claim_slot(icc.mail_slot(acc.label), "messages.parquet")
    # Chunks left by an interrupted run are folded in first.
    merge_into_slot(acc)
    password = None
    if acc.auth == "password":
        password = icc.require_secret("sbk-mailbox", acc, "mailbox password")
    conn, caps = connect(acc, password)
    summary = {"folders": {}, "condstore": "CONDSTORE" in caps, "new": 0, "flag_changes": 0}
    try:
        folders = choose_folders(list_folders(conn), acc.folders)
        if not folders:
            raise icc.SetupError(f"{icc.PLUGIN_ID}: '{acc.label}': none of the folders was found")
        uid_to_id = load_uidmap(acc.label)
        imap_state = state.setdefault("imap", {})
        flag_updates: dict = {}
        seq = [0]
        for f in folders:
            fstate = imap_state.setdefault(f["raw"], {})

            def on_rows(rows, top, _f=f, _fs=fstate):
                seq[0] += 1
                write_chunk(acc.label, rows, seq[0])
                _fs["last_uid"] = top
                icc.save_state(acc.label, state)

            res = sync_folder(
                conn, acc, f, fstate, since=since, force=force, uid_to_id=uid_to_id,
                on_rows=on_rows, log=log,
            )  # fmt: skip
            flag_updates.update(res["flag_updates"])
            summary["folders"][f["name"]] = {
                "new": res["new"], "skipped": res["skipped"],
                "flag_changes": len(res["flag_updates"]),
            }  # fmt: skip
            icc.save_state(acc.label, state)
            log.info(f"  {f['name']}: " + ("unchanged" if res["skipped"] else f"{res['new']} new"))
    finally:
        try:
            conn.logout()
        except Exception:  # noqa: BLE001
            pass
    merged = merge_into_slot(acc, flag_updates)
    for fstate in state.get("imap", {}).values():
        if "modseq_pending" in fstate:
            fstate["modseq"] = fstate.pop("modseq_pending")
    icc.save_state(acc.label, state)
    summary["new"] = merged["added"]
    summary["flag_changes"] = merged["flag_changes"]
    summary["messages"] = merged["messages"]
    return summary
