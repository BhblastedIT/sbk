"""imap-caldav plugin: calendar side.

CalDAV (RFC 4791) with your app password: discovery through current-user-principal (RFC 5397)
and calendar-home-set, falling back to /.well-known/caldav (RFC 6764); a calendar is read again
only when its getctag changed, and inside it only the objects whose ETag changed
(calendar-multiget). Read-only: PROPFIND and REPORT, never PUT or DELETE.

ICS: a private or public calendar link (https or webcal), downloaded with If-None-Match /
If-Modified-Since so an unchanged feed costs one request; a changed feed is stored per event, so
past events that drop out of a feed with a limited past are kept.

Raw objects are kept in <data root>/imap-caldav/raw/<account>/objects.parquet; the calendar slot
<data root>/calendars/<account>/events.parquet is rebuilt from them at every run.
"""

from __future__ import annotations

import hashlib
import os
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import UTC, datetime, timedelta

import ic_common as icc
import ic_ical

NS = {"d": "DAV:", "c": "urn:ietf:params:xml:ns:caldav", "cs": "http://calendarserver.org/ns/"}
MULTIGET_BATCH = 100
RAW_COLUMNS = ["cal_href", "cal_name", "href", "etag", "ics", "fetched_at"]

_PROPFIND_PRINCIPAL = b"""<?xml version="1.0" encoding="utf-8"?>
<d:propfind xmlns:d="DAV:"><d:prop><d:current-user-principal/><d:resourcetype/></d:prop></d:propfind>"""
_PROPFIND_HOME = b"""<?xml version="1.0" encoding="utf-8"?>
<d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">
<d:prop><c:calendar-home-set/></d:prop></d:propfind>"""
_PROPFIND_CALENDARS = b"""<?xml version="1.0" encoding="utf-8"?>
<d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav" xmlns:cs="http://calendarserver.org/ns/">
<d:prop><d:resourcetype/><d:displayname/><cs:getctag/><d:sync-token/>
<c:supported-calendar-component-set/></d:prop></d:propfind>"""
_PROPFIND_ETAGS = b"""<?xml version="1.0" encoding="utf-8"?>
<d:propfind xmlns:d="DAV:"><d:prop><d:getetag/><d:resourcetype/></d:prop></d:propfind>"""


class DavError(Exception):
    pass


def _xml_headers(depth: str) -> dict:
    return {"Depth": depth, "Content-Type": "application/xml; charset=utf-8"}


def _parse_multistatus(data: bytes) -> list[dict]:
    """[{href, props: {"{ns}name": Element}}] for the 200 propstats of a multistatus."""
    try:
        root = ET.fromstring(data)
    except ET.ParseError as e:
        raise DavError(f"unreadable XML answer ({e})") from e
    out = []
    for resp in root.findall("d:response", NS):
        href_el = resp.find("d:href", NS)
        if href_el is None or not (href_el.text or "").strip():
            continue
        props: dict = {}
        for ps in resp.findall("d:propstat", NS):
            st = ps.find("d:status", NS)
            if st is not None and " 200 " not in f" {st.text or ''} ":
                continue
            prop = ps.find("d:prop", NS)
            if prop is None:
                continue
            for child in prop:
                props[child.tag] = child
        out.append({"href": href_el.text.strip(), "props": props})
    return out


def _tag(ns: str, name: str) -> str:
    return "{" + NS[ns] + "}" + name


def _href_in(el) -> str:
    if el is None:
        return ""
    h = el.find("d:href", NS)
    return (h.text or "").strip() if h is not None else ""


class CalDav:
    def __init__(self, base_url: str, username: str, password: str):
        self.base = base_url
        self.auth = (username, password)

    def request(self, method: str, url: str, body: bytes | None = None, depth: str = "0"):
        status, headers, data, final = icc.http_request(
            method, url, _xml_headers(depth), body, auth=self.auth
        )
        if status == 401:
            raise icc.SetupError(
                f"{icc.PLUGIN_ID}: the CalDAV server refused the login (401): check caldav "
                "username and app password"
            )
        return status, headers, data, final

    def propfind(self, url: str, body: bytes, depth: str) -> list[dict]:
        status, _h, data, _final = self.request("PROPFIND", url, body, depth)
        if status != 207:
            raise DavError(f"PROPFIND answered HTTP {status}")
        return _parse_multistatus(data)

    def _abs(self, url: str, href: str) -> str:
        return canon(urllib.parse.urljoin(url, href))

    def discover(self) -> list[dict]:
        """[{href (absolute URL), name, ctag, sync_token}] of the calendars holding events."""
        url = self.base
        principal = ""
        tries = [url]
        parts = urllib.parse.urlsplit(url)
        tries.append(
            urllib.parse.urlunsplit((parts.scheme, parts.netloc, "/.well-known/caldav", "", ""))
        )
        for t in tries:
            try:
                res = self.propfind(t, _PROPFIND_PRINCIPAL, "0")
            except DavError:
                continue
            for r in res:
                rt = r["props"].get(_tag("d", "resourcetype"))
                if rt is not None and rt.find("c:calendar", NS) is not None:
                    # The URL is already one calendar collection.
                    return self._list_calendars(t, depth="0")
                principal = _href_in(r["props"].get(_tag("d", "current-user-principal")))
                if principal:
                    url = t
                    break
            if principal:
                break
        if not principal:
            raise DavError("no current-user-principal at the CalDAV URL or /.well-known/caldav")
        purl = self._abs(url, principal)
        home = ""
        for r in self.propfind(purl, _PROPFIND_HOME, "0"):
            home = _href_in(r["props"].get(_tag("c", "calendar-home-set")))
            if home:
                break
        if not home:
            raise DavError("the principal has no calendar-home-set")
        return self._list_calendars(self._abs(purl, home), depth="1")

    def _list_calendars(self, url: str, depth: str) -> list[dict]:
        cals = []
        for r in self.propfind(url, _PROPFIND_CALENDARS, depth):
            p = r["props"]
            rt = p.get(_tag("d", "resourcetype"))
            if rt is None or rt.find("c:calendar", NS) is None:
                continue
            comps = p.get(_tag("c", "supported-calendar-component-set"))
            if comps is not None:
                names = {c.get("name", "").upper() for c in comps.findall("c:comp", NS)}
                if names and "VEVENT" not in names:
                    continue
            dn = p.get(_tag("d", "displayname"))
            ctag = p.get(_tag("cs", "getctag"))
            st = p.get(_tag("d", "sync-token"))
            cals.append(
                {
                    "href": self._abs(url, r["href"]),
                    "name": (dn.text or "").strip() if dn is not None else "",
                    "ctag": (ctag.text or "").strip() if ctag is not None else "",
                    "sync_token": (st.text or "").strip() if st is not None else "",
                }
            )
        return cals

    def etags(self, cal_url: str) -> dict[str, str]:
        out = {}
        for r in self.propfind(cal_url, _PROPFIND_ETAGS, "1"):
            rt = r["props"].get(_tag("d", "resourcetype"))
            if rt is not None and len(list(rt)):
                continue  # the collection itself
            et = r["props"].get(_tag("d", "getetag"))
            if et is None:
                continue
            out[self._abs(cal_url, r["href"])] = (et.text or "").strip()
        return out

    def multiget(self, cal_url: str, hrefs: list[str]) -> dict[str, tuple[str, str]]:
        """{absolute href: (etag, ics text)}."""
        out: dict[str, tuple[str, str]] = {}
        for i in range(0, len(hrefs), MULTIGET_BATCH):
            batch = hrefs[i : i + MULTIGET_BATCH]
            body = ['<?xml version="1.0" encoding="utf-8"?>',
                    '<c:calendar-multiget xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">',
                    "<d:prop><d:getetag/><c:calendar-data/></d:prop>"]  # fmt: skip
            for h in batch:
                path = urllib.parse.urlsplit(h).path
                body.append(f"<d:href>{_xml_escape(path)}</d:href>")
            body.append("</c:calendar-multiget>")
            status, _h, data, _f = self.request(
                "REPORT", cal_url, "\n".join(body).encode("utf-8"), "1"
            )
            if status != 207:
                raise DavError(f"calendar-multiget answered HTTP {status}")
            for r in _parse_multistatus(data):
                cd = r["props"].get(_tag("c", "calendar-data"))
                et = r["props"].get(_tag("d", "getetag"))
                if cd is None:
                    continue
                out[self._abs(cal_url, r["href"])] = (
                    (et.text or "").strip() if et is not None else "",
                    cd.text or "",
                )
        return out


def _xml_escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


_PATH_SAFE = "/:@!$&'()*+,;=~"


def canon(url: str) -> str:
    """One spelling per resource: servers may answer a PROPFIND with '%40' and a REPORT with '@'
    for the same object; without this the object would look deleted and new at every run."""
    p = urllib.parse.urlsplit(url)
    path = urllib.parse.quote(urllib.parse.unquote(p.path), safe=_PATH_SAFE)
    return urllib.parse.urlunsplit((p.scheme, p.netloc.lower(), path, p.query, ""))


# --- Raw store -------------------------------------------------------------------------------
def raw_path(account: str):
    return icc.raw_dir(account) / "objects.parquet"


def load_raw(account: str):
    import pandas as pd

    p = raw_path(account)
    if p.exists():
        return pd.read_parquet(p)
    return pd.DataFrame(columns=RAW_COLUMNS)


def save_raw(account: str, df) -> None:
    icc.cfg.safe_write_parquet(df.reset_index(drop=True), raw_path(account), index=False)


def set_aside(account: str, removed) -> None:
    """Objects gone from the server are kept aside in removed.parquet, never thrown away."""
    import pandas as pd

    if removed is None or removed.empty:
        return
    p = icc.raw_dir(account) / "removed.parquet"
    if p.exists():
        removed = pd.concat([pd.read_parquet(p), removed], ignore_index=True)
    icc.cfg.safe_write_parquet(removed.reset_index(drop=True), p, index=False)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def sync_caldav(acc: icc.Account, state: dict, *, force: bool, log) -> dict:
    import pandas as pd

    password = icc.require_secret("sbk-caldav", acc, "CalDAV app password")
    user = acc.caldav_username or acc.username or acc.email
    dav = CalDav(acc.caldav_url, user, password)
    try:
        cals = dav.discover()
    except DavError as e:
        raise icc.SetupError(
            f"{icc.PLUGIN_ID}: '{acc.label}': CalDAV discovery failed ({e})"
        ) from e
    inc = {s.lower() for s in acc.calendar_include}
    exc = {s.lower() for s in acc.calendar_exclude}
    cals = [
        c for c in cals
        if (not inc or c["name"].lower() in inc) and c["name"].lower() not in exc
    ]  # fmt: skip
    cstate = state.setdefault("caldav", {})
    raw = load_raw(acc.label)
    summary = {"calendars": {}, "fetched": 0, "removed": 0}
    for cal in cals:
        href, name = cal["href"], cal["name"] or cal["href"].rstrip("/").rsplit("/", 1)[-1]
        prev = cstate.get(href, {})
        if not force and cal["ctag"] and prev.get("ctag") == cal["ctag"]:
            summary["calendars"][name] = {"skipped": True}
            log.info(f"  calendar {name}: unchanged")
            continue
        try:
            server = dav.etags(href)
        except DavError as e:
            log.warning(f"  calendar {name}: listing failed ({e}), kept as it was")
            summary["calendars"][name] = {"error": str(e)}
            continue
        mine = raw[raw["cal_href"] == href]
        known = dict(zip(mine["href"], mine["etag"]))
        changed = [h for h, et in server.items() if force or known.get(h) != et]
        gone = [h for h in known if h not in server]
        try:
            fetched = dav.multiget(href, changed) if changed else {}
        except DavError as e:
            log.warning(f"  calendar {name}: calendar-multiget failed ({e}), kept as it was")
            summary["calendars"][name] = {"error": str(e)}
            continue
        new_rows = pd.DataFrame(
            [
                {
                    "cal_href": href,
                    "cal_name": name,
                    "href": h,
                    "etag": et or server.get(h, ""),
                    "ics": ics,
                    "fetched_at": _now(),
                }
                for h, (et, ics) in fetched.items()
            ],  # fmt: skip
            columns=RAW_COLUMNS,
        )
        drop = raw["cal_href"].eq(href) & raw["href"].isin(set(fetched) | set(gone))
        set_aside(acc.label, raw[raw["cal_href"].eq(href) & raw["href"].isin(gone)])
        raw = pd.concat([raw[~drop], new_rows], ignore_index=True)
        raw.loc[raw["cal_href"] == href, "cal_name"] = name
        save_raw(acc.label, raw)
        missed = [h for h in changed if h not in fetched]
        if missed:
            # Not answered by calendar-multiget: keep the ctag unset, so the next run lists
            # the calendar again and asks for these objects once more.
            log.warning(
                f"  calendar {name}: {len(missed)} changed objects not returned, retried next run"
            )
        cstate[href] = {
            "name": name,
            "ctag": "" if missed else cal["ctag"],
            "objects": len(server),
        }
        icc.save_state(acc.label, state)
        summary["calendars"][name] = {
            "objects": len(server),
            "fetched": len(fetched),
            "removed": len(gone),
            "missed": len(missed),
        }
        summary["fetched"] += len(fetched)
        summary["removed"] += len(gone)
        log.info(f"  calendar {name}: {len(fetched)} fetched, {len(gone)} removed")
    bad = sorted(n for n, v in summary["calendars"].items() if "error" in v)
    if bad:  # the run is reported as failed (no mark_last_run), the other calendars are kept
        summary["error"] = f"{icc.PLUGIN_ID}: '{acc.label}': calendars not read: {', '.join(bad)}"
    return summary


def _sha(s: str, n: int = 16) -> str:
    return hashlib.sha1(s.encode("utf-8", "replace")).hexdigest()[:n]


def split_feed(text: str) -> dict[str, str]:
    """{UID: a small VCALENDAR holding every VEVENT of that UID} (master and overrides together).
    VTIMEZONE blocks are left out: the reader resolves TZID names itself."""
    groups: dict[str, list[str]] = {}
    cur: list[str] | None = None
    depth, uid = 0, ""
    for line in ic_ical.unfold(text):
        up = line.upper()
        if cur is None:
            if up.startswith("BEGIN:VEVENT"):
                cur, depth, uid = [line], 1, ""
            continue
        cur.append(line)
        if up.startswith("BEGIN:"):
            depth += 1
        elif up.startswith("END:"):
            depth -= 1
            if depth == 0:
                groups.setdefault(uid or "nouid-" + _sha("\n".join(cur)), []).extend(cur)
                cur = None
        elif depth == 1 and up.startswith("UID") and up[3:4] in (":", ";"):
            uid = line.split(":", 1)[1].strip()
    return {
        u: "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n" + "\r\n".join(ls) + "\r\nEND:VCALENDAR\r\n"
        for u, ls in groups.items()
    }


def _has_future(ics: str, now: datetime) -> bool:
    """True if the object still has an instance from yesterday on (so leaving the feed means it
    was deleted), False if it is over (it left the feed because the feed shows a limited past)."""
    lo = now - timedelta(days=1)
    rows = ic_ical.rows_from_ics(
        ics, account="", calendar_name="", calendar_id="", own=set(),
        window=(lo, now + timedelta(days=3650)),
    )  # fmt: skip
    for r in rows:
        try:
            if ic_ical._cmp(datetime.fromisoformat(r["start_datetime"])) >= lo:
                return True
        except (TypeError, ValueError):
            return True
    return False


def sync_ics(acc: icc.Account, state: dict, *, force: bool, log) -> dict:
    """One calendar link. The feed is split per event (UID): a changed feed rewrites only the
    events that changed; an event that is over and no longer in the feed (many links publish a
    limited past) is kept; a future event gone from the feed is set aside in removed.parquet."""
    import pandas as pd

    url = icc.require_secret("sbk-ics", acc, "calendar link").strip()
    if url.lower().startswith("webcal://"):
        url = "https://" + url[len("webcal://") :]
    try:
        host = urllib.parse.urlsplit(url).hostname or "?"
    except ValueError:
        host = "?"
    istate = state.setdefault("ics", {})
    headers = {"Accept": "text/calendar"}
    if not force and istate.get("etag"):
        headers["If-None-Match"] = istate["etag"]
    if not force and istate.get("last_modified"):
        headers["If-Modified-Since"] = istate["last_modified"]
    try:
        status, rh, data, _final = icc.http_request("GET", url, headers)
    except icc.SetupError:
        raise
    except Exception as e:  # noqa: BLE001 - the text of these errors can carry the secret link
        raise icc.SetupError(
            f"{icc.PLUGIN_ID}: '{acc.label}': the calendar link could not be read "
            f"({type(e).__name__}, {host})"
        ) from None
    if status == 304:
        log.info(f"  calendar link ({host}): unchanged")
        return {"skipped": True}
    if status != 200:
        raise icc.SetupError(
            f"{icc.PLUGIN_ID}: '{acc.label}': the calendar link answered HTTP {status} ({host})"
        )
    text = data.decode("utf-8", "replace")
    if "BEGIN:VCALENDAR" not in text[:2000].upper():
        raise icc.SetupError(
            f"{icc.PLUGIN_ID}: '{acc.label}': the calendar link did not return iCalendar data ({host})"
        )
    # The feed id does not depend on the link (a secret, and it changes if you reset it).
    feed_id = "ics-" + _sha("feed\x00" + acc.label)
    rdir = icc.raw_dir(acc.label)
    rdir.mkdir(parents=True, exist_ok=True)
    cur_copy, prev_copy = rdir / "feed-current.ics", rdir / "feed-previous.ics"
    if cur_copy.exists():  # one previous copy of the whole feed is kept
        os.replace(cur_copy, prev_copy)
    cur_copy.write_text(text, encoding="utf-8")
    cur_copy.chmod(0o600)

    now = datetime.now(UTC)
    raw = load_raw(acc.label)
    mine = raw[raw["cal_href"] == feed_id]
    known = dict(zip(mine["href"], mine["etag"]))
    objs = {f"{feed_id}#{_sha(uid)}": ics for uid, ics in split_feed(text).items()}
    new_rows = pd.DataFrame(
        [
            {"cal_href": feed_id, "cal_name": acc.label, "href": h, "etag": _sha(ics),
             "ics": ics, "fetched_at": _now()}
            for h, ics in objs.items()
            if force or known.get(h) != _sha(ics)
        ],
        columns=RAW_COLUMNS,
    )  # fmt: skip
    gone = mine[~mine["href"].isin(set(objs))]
    removed = gone[[_has_future(str(x or ""), now) for x in gone["ics"]]] if len(gone) else gone
    set_aside(acc.label, removed)
    drop = raw["cal_href"].eq(feed_id) & raw["href"].isin(
        set(new_rows["href"]) | set(removed["href"])
    )
    raw = pd.concat([raw[~drop], new_rows], ignore_index=True)
    save_raw(acc.label, raw)
    istate.update({"etag": rh.get("etag", ""), "last_modified": rh.get("last-modified", "")})
    icc.save_state(acc.label, state)
    kept = len(gone) - len(removed)
    log.info(
        f"  calendar link ({host}): {len(objs)} events in the feed, {len(new_rows)} new or "
        f"changed, {len(removed)} removed, {kept} past events kept"
    )
    return {
        "skipped": False, "bytes": len(text), "in_feed": len(objs), "fetched": len(new_rows),
        "removed": len(removed), "past_kept": kept,
    }  # fmt: skip


def rebuild_events(acc: icc.Account, log) -> dict:
    """events.parquet of the slot from the raw objects; cancelled events go to cancellati.parquet
    as the Google downloader does."""
    import pandas as pd

    raw = load_raw(acc.label)
    past, future = icc.calendar_window_days()
    now = datetime.now(UTC)
    window = (now - timedelta(days=past), now + timedelta(days=future))
    own = icc.own_addresses(acc)
    rows: list[dict] = []
    for cal_href, cal_name, ics in zip(raw["cal_href"], raw["cal_name"], raw["ics"]):
        rows.extend(
            ic_ical.rows_from_ics(
                ics or "", account=acc.label, calendar_name=cal_name or acc.label,
                calendar_id=cal_href, own=own, window=window,
                warn=lambda m: log.warning(f"  {cal_name}: {m}"),
            )
        )  # fmt: skip
    df = pd.DataFrame(rows, columns=ic_ical.EVENT_COLUMNS).drop_duplicates("id", keep="last")
    slot = icc.calendar_slot(acc.label)
    icc.claim_slot(slot, "events.parquet")
    cancelled = df[df["status"] == "cancelled"]
    if len(cancelled):
        icc.cfg.safe_write_parquet(
            cancelled.reset_index(drop=True), slot / "cancellati.parquet", index=False
        )
    df = df[df["status"] != "cancelled"].sort_values("start_datetime").reset_index(drop=True)
    icc.cfg.safe_write_parquet(df, slot / "events.parquet", index=False)
    return {"events": len(df), "cancelled": len(cancelled)}
