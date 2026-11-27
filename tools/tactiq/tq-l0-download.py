#!/usr/bin/env python3
"""Tactiq download: the transcripts of your Tactiq meetings (also those shared with you), through the Tactiq
session of your browser or a refresh token kept in the Keychain (--direct); --verify checks completeness.
"""

import argparse
import json
import logging
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))
from pipeline_decorator import PermanentAPIError  # noqa: E402

from sbk_config import TACTIQ_RAW_DIR, mark_last_run, safe_write_json  # noqa: E402

OUTPUT_DIR = TACTIQ_RAW_DIR  # Created when the script runs, not at import, so --help writes nothing.
INDEX_PATH = OUTPUT_DIR / "_meeting_index.json"
ERRORS_PATH = OUTPUT_DIR / "_errors.json"

GRAPHQL_URL = "https://api2.tactiq.io/api/2/graphql"
PAGE_SIZE = 20
FIREBASE_API_KEY = os.environ.get(
    "TACTIQ_FIREBASE_API_KEY", "YOUR_FIREBASE_API_KEY"
)


_direct_mode = False
_refresh_token_cache = None

log = logging.getLogger("tactiq-dl")


def chrome_js(js_code, timeout=30):
    ""
    escaped = js_code.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")

    applescript = f'''
    tell application "Google Chrome"
        repeat with w in windows
            repeat with t in tabs of w
                if URL of t contains "tactiq.io" then
                    tell t
                        set jsResult to execute javascript "{escaped}"
                    end tell
                    return jsResult
                end if
            end repeat
        end repeat
        return "ERROR_NO_TACTIQ_TAB"
    end tell
    '''

    result = subprocess.run(
        ["osascript", "-e", applescript], capture_output=True, text=True, timeout=timeout
    )

    output = result.stdout.strip()
    if output == "ERROR_NO_TACTIQ_TAB":
        log.error("No Tactiq tab (app.tactiq.io) open in Chrome!")
        log.error("  -> Open https://app.tactiq.io/ and log in, then retry")
        sys.exit(1)
    if result.returncode != 0:
        log.error(f"AppleScript error: {result.stderr[:300]}")
        return None

    return output


def async_chrome(
    js_code, result_key="_sbk_result", status_key="_sbk_status", timeout=30, poll_interval=1
):
    ""

    chrome_js(
        f"localStorage.removeItem('{result_key}'); localStorage.setItem('{status_key}', 'running')"
    )


    chrome_js(js_code, timeout=10)


    for _ in range(timeout):
        time.sleep(poll_interval)
        status = chrome_js(f"localStorage.getItem('{status_key}')", timeout=10)
        if status and ("done" in status or "error" in status):
            break


    raw = chrome_js(f"localStorage.getItem('{result_key}')", timeout=15)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"_raw": raw[:5000]}


def get_firebase_token():
    ""

    js_sdk = r"""
    (function() {
        localStorage.setItem('_sbk_status', 'getting_token');
        try {
            // Try Firebase v9+ modular (getAuth imported by app)
            var tryGetToken = function() {
                // Firebase compat or modular — look for global firebase
                if (typeof firebase !== 'undefined' && firebase.auth) {
                    var user = firebase.auth().currentUser;
                    if (user) {
                        user.getIdToken(true).then(function(token) {
                            localStorage.setItem('_sbk_result', JSON.stringify({token: token, email: user.email, method: 'firebase_sdk'}));
                            localStorage.setItem('_sbk_status', 'done');
                        }).catch(function(err) {
                            localStorage.setItem('_sbk_result', JSON.stringify({error: 'getIdToken failed: ' + err.message}));
                            localStorage.setItem('_sbk_status', 'error');
                        });
                        return true;
                    }
                }
                return false;
            };
            if (!tryGetToken()) {
                // Fallback: try reading from IndexedDB
                var req = indexedDB.open('firebaseLocalStorageDb');
                req.onsuccess = function() {
                    var db = req.result;
                    var tx = db.transaction('firebaseLocalStorage', 'readonly');
                    var store = tx.objectStore('firebaseLocalStorage');
                    var getAll = store.getAll();
                    getAll.onsuccess = function() {
                        db.close();
                        var entries = getAll.result;
                        for (var i = 0; i < entries.length; i++) {
                            var e = entries[i];
                            if (e.value && e.value.stsTokenManager) {
                                var stm = e.value.stsTokenManager;
                                // Check if token is expired (expirationTime is ms timestamp)
                                if (stm.expirationTime && stm.expirationTime > Date.now()) {
                                    localStorage.setItem('_sbk_result', JSON.stringify({token: stm.accessToken, email: e.value.email, method: 'indexeddb_valid'}));
                                    localStorage.setItem('_sbk_status', 'done');
                                    return;
                                }
                                // Token expired — try to refresh using refreshToken
                                if (stm.refreshToken) {
                                    fetch('https://securetoken.googleapis.com/v1/token?key=YOUR_FIREBASE_API_KEY', {
                                        method: 'POST',
                                        headers: {'Content-Type': 'application/x-www-form-urlencoded'},
                                        body: 'grant_type=refresh_token&refresh_token=' + encodeURIComponent(stm.refreshToken)
                                    }).then(function(r) { return r.json(); })
                                    .then(function(data) {
                                        if (data.id_token) {
                                            localStorage.setItem('_sbk_result', JSON.stringify({token: data.id_token, email: e.value.email, method: 'refresh_token'}));
                                            localStorage.setItem('_sbk_status', 'done');
                                        } else {
                                            localStorage.setItem('_sbk_result', JSON.stringify({error: 'refresh failed: ' + JSON.stringify(data)}));
                                            localStorage.setItem('_sbk_status', 'error');
                                        }
                                    }).catch(function(err) {
                                        localStorage.setItem('_sbk_result', JSON.stringify({error: 'refresh fetch error: ' + err.message}));
                                        localStorage.setItem('_sbk_status', 'error');
                                    });
                                    return;
                                }
                                // No refresh token, return stale token anyway
                                localStorage.setItem('_sbk_result', JSON.stringify({token: stm.accessToken, email: e.value.email, method: 'indexeddb_stale'}));
                                localStorage.setItem('_sbk_status', 'done');
                                return;
                            }
                        }
                        localStorage.setItem('_sbk_result', JSON.stringify({error: 'No Firebase entries found'}));
                        localStorage.setItem('_sbk_status', 'error');
                    };
                };
                req.onerror = function() {
                    localStorage.setItem('_sbk_result', JSON.stringify({error: 'Cannot open firebaseLocalStorageDb'}));
                    localStorage.setItem('_sbk_status', 'error');
                };
            }
        } catch(e) {
            localStorage.setItem('_sbk_result', JSON.stringify({error: e.message}));
            localStorage.setItem('_sbk_status', 'error');
        }
        return 'getting_token';
    })()
    """

    js_sdk = js_sdk.replace("YOUR_FIREBASE_API_KEY", FIREBASE_API_KEY)
    result = async_chrome(js_sdk, timeout=20)
    if result and "token" in result:
        method = result.get("method", "unknown")
        log.info(f"Token obtained via {method}")
        return result["token"], result.get("email")
    log.error(f"Token ERROR: {result}")
    return None, None


def _extract_refresh_token_from_chrome():
    ""
    global _refresh_token_cache
    if _refresh_token_cache:


        return _refresh_token_cache

    chrome_base = Path.home() / "Library" / "Application Support" / "Google" / "Chrome"

    candidates = []
    for profile in ["Profile 1", "Default"]:
        idb_dir = chrome_base / profile / "IndexedDB" / "https_app.tactiq.io_0.indexeddb.leveldb"
        if idb_dir.exists():
            candidates.append(idb_dir)

    for idb_dir in candidates:
        raw = b""
        for f in sorted(idb_dir.iterdir()):
            if f.is_file() and f.suffix in (".ldb", ".log"):
                raw += f.read_bytes()
        matches = re.findall(rb"refreshToken.{1,10}?(AMf-[A-Za-z0-9_-]{100,500})", raw)
        if matches:
            token = matches[-1].decode("utf-8", errors="ignore")

            emails = re.findall(rb"([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})", raw)
            email = emails[0].decode() if emails else None
            _refresh_token_cache = (token, email)
            return _refresh_token_cache
    return None, None








PORTACHIAVI_TACTIQ = ("sbk-tactiq", "refresh-token")


def _salva_nel_portachiavi(refresh_token: str) -> None:
    try:
        from secrets_adapter import get_secret, set_secret

        if get_secret(*PORTACHIAVI_TACTIQ) != refresh_token:
            set_secret(*PORTACHIAVI_TACTIQ, refresh_token)
            log.info("Tactiq: access copy updated in the Keychain")
    except Exception as e:  # noqa: BLE001
        log.warning(
            f"Tactiq: cannot write the access copy to the Keychain ({type(e).__name__})"
        )


def _dal_portachiavi() -> str | None:
    try:
        from secrets_adapter import get_secret

        return get_secret(*PORTACHIAVI_TACTIQ)
    except Exception as e:  # noqa: BLE001
        log.warning(f"Tactiq: cannot read the Keychain ({type(e).__name__})")
        return None


def _scambia(refresh_token: str) -> str | None:
    ""
    try:
        return _firebase_refresh_to_access(refresh_token)
    except Exception as e:  # noqa: BLE001
        log.warning(f"Tactiq: access token exchange failed ({type(e).__name__})")
        return None


def _firebase_refresh_to_access(refresh_token):
    ""
    url = f"https://securetoken.googleapis.com/v1/token?key={FIREBASE_API_KEY}"
    data = urllib.parse.urlencode(
        {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }
    ).encode()
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"}
    )
    resp = urllib.request.urlopen(req, timeout=15)
    result = json.loads(resp.read())
    if "id_token" in result:
        return result["id_token"]
    log.error(f"Firebase refresh failed: {result}")
    return None


def get_firebase_token_direct():
    ""
    refresh_token, email = _extract_refresh_token_from_chrome()
    if refresh_token:
        access_token = _scambia(refresh_token)
        if access_token:
            log.info("Token obtained via direct Chrome IndexedDB extraction")
            _salva_nel_portachiavi(refresh_token)
            return access_token, email
        log.warning(
            "Tactiq: the access found in Chrome is no longer valid, trying the Keychain copy"
        )
    else:
        log.warning(
            "Cannot extract the refresh token from Chrome IndexedDB, trying the Keychain copy"
        )
    copia = _dal_portachiavi()
    if copia and copia != refresh_token:
        access_token = _scambia(copia)
        if access_token:
            log.info("Token obtained from the Keychain copy")
            return access_token, email
    log.error("Cannot extract a valid refresh token from either Chrome or the Keychain")
    log.error("  Make sure you are logged in to app.tactiq.io in Chrome")
    return None, None


def graphql_query_direct(token, query, variables=None):
    ""
    payload = json.dumps({"query": query, "variables": variables or {}}).encode()
    req = urllib.request.Request(
        GRAPHQL_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Origin": "https://app.tactiq.io",
            "Referer": "https://app.tactiq.io/",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-site",
            "Sec-Ch-Ua": '"Chromium";v="133", "Not(A:Brand";v="99", "Google Chrome";v="133"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"macOS"',
        },
    )
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:500]
        log.error(f"GraphQL HTTP {e.code}: {body}")
        return {"errors": [{"message": f"HTTP {e.code}: {body[:100]}"}]}
    except Exception as e:
        log.error(f"GraphQL error: {e}")
        return None


def graphql_query(token, query, variables=None):
    ""
    if _direct_mode:
        return graphql_query_direct(token, query, variables)

    vars_json = json.dumps(variables or {})

    query_escaped = query.replace("\\", "\\\\").replace("'", "\\'").replace("\n", " ")
    vars_escaped = vars_json.replace("\\", "\\\\").replace("'", "\\'")

    js = f"""
    (function() {{
        localStorage.setItem('_sbk_status', 'fetching');
        fetch('{GRAPHQL_URL}', {{
            method: 'POST',
            headers: {{
                'Content-Type': 'application/json',
                'Authorization': 'Bearer ' + '{token}'
            }},
            body: JSON.stringify({{
                query: '{query_escaped}',
                variables: JSON.parse('{vars_escaped}')
            }})
        }}).then(function(r) {{ return r.json(); }})
        .then(function(data) {{
            localStorage.setItem('_sbk_result', JSON.stringify(data));
            localStorage.setItem('_sbk_status', 'done');
        }}).catch(function(err) {{
            localStorage.setItem('_sbk_result', JSON.stringify({{error: err.message}}));
            localStorage.setItem('_sbk_status', 'error');
        }});
        return 'fetching';
    }})()
    """
    return async_chrome(js, timeout=30)


def fetch_all_meetings(token, include_shared=False):
    ""
    all_meetings = []
    offset = 0
    meeting_type = "MyMeetings"


    existing_ids = set()
    if INDEX_PATH.exists():
        try:
            with open(INDEX_PATH) as fp:
                for entry in json.load(fp):
                    if "id" in entry:
                        existing_ids.add(entry["id"])
        except Exception:
            pass
    early_stop_threshold = 10

    while True:
        query = f"""query {{
            meetings(type: {meeting_type}, filter: {{}}, offset: {offset}) {{
                hasMore offset
                meetings {{
                    id title platform duration created modified
                    languageCode isDraft hasEnded hadProcessingError
                    participants {{ name color analytics {{ textLength speechDuration }} }}
                    tags {{ count tag {{ name icon }} }}
                    screenshotsCount hasRecordings
                }}
            }}
        }}"""

        result = graphql_query(token, query)
        if not result or "errors" in result:

            raise RuntimeError(f"Tactiq GraphQL error at offset {offset}: {str(result)[:300]}")

        meetings_data = result.get("data", {}).get("meetings", {})
        meetings = meetings_data.get("meetings", [])
        has_more = meetings_data.get("hasMore", False)

        all_meetings.extend(meetings)
        log.info(f"Offset {offset}: +{len(meetings)} meetings (total: {len(all_meetings)})")

        if not has_more or len(meetings) == 0:
            break


        if existing_ids:
            consecutive_existing = 0
            for m in meetings:
                if m.get("id") in existing_ids:
                    consecutive_existing += 1
                    if consecutive_existing >= early_stop_threshold:
                        break
                else:
                    consecutive_existing = 0
            if consecutive_existing >= early_stop_threshold:
                log.info(
                    f"Early stop: {consecutive_existing} consecutive existing meetings "
                    f"found at offset {offset}, stopping listing"
                )
                log.info(
                    f"Early stop: {consecutive_existing} consecutive existing meetings "
                    f"found at offset {offset}, stopping listing"
                )
                break

        offset += len(meetings)
        time.sleep(0.3)


    if include_shared:
        log.info("Downloading SharedWithMe...")
        offset = 0
        while True:
            query = f"""query {{
                meetings(type: SharedWithMe, filter: {{}}, offset: {offset}) {{
                    hasMore offset
                    meetings {{
                        id title platform duration created modified
                        languageCode participants {{ name }}
                    }}
                }}
            }}"""
            result = graphql_query(token, query)
            if not result or "errors" in result:
                raise RuntimeError(
                    f"Tactiq GraphQL error (SharedWithMe) at offset {offset}: {str(result)[:300]}"
                )
            meetings_data = result.get("data", {}).get("meetings", {})
            meetings = meetings_data.get("meetings", [])
            has_more = meetings_data.get("hasMore", False)

            for m in meetings:
                m["_shared"] = True
            all_meetings.extend(meetings)
            log.info(f"SharedWithMe offset {offset}: +{len(meetings)}")

            if not has_more or len(meetings) == 0:
                break
            offset += len(meetings)
            time.sleep(0.3)

    return all_meetings


def fetch_transcript(token, meeting_id):
    ""
    query = """query GetMeeting($meetingId: ID!) {
        meeting(id: $meetingId) {
            id title transcript
        }
    }"""
    variables = {"meetingId": meeting_id}

    result = graphql_query(token, query, variables)
    if not result:
        return None

    if "errors" in result:
        return {"_error": result["errors"][0].get("message", "unknown")}

    meeting = result.get("data", {}).get("meeting", {})
    return meeting.get("transcript")


def format_transcript_text(transcript_data, meeting_info):
    ""
    lines = []
    title = meeting_info.get("title", "Unknown")
    created = meeting_info.get("created", 0)
    duration = meeting_info.get("duration", 0)
    lang = meeting_info.get("languageCode", "?")
    participants = [p.get("name", "?") for p in meeting_info.get("participants", [])]

    date_str = ""
    if created:
        dt = datetime.fromtimestamp(created / 1000, tz=UTC)
        date_str = dt.strftime("%Y-%m-%d %H:%M UTC")

    lines.append(f"# {title}")
    lines.append(f"# Date: {date_str}")
    lines.append(f"# Duration: {duration}s ({duration // 60}min)")
    lines.append(f"# Language: {lang}")
    lines.append(f"# Participants: {', '.join(participants)}")
    lines.append(f"# ID: {meeting_info.get('id', '?')}")
    lines.append("")

    if not transcript_data:
        lines.append("[No transcript data]")
        return "\n".join(lines)

    blocks = transcript_data.get("blocks", [])
    if not blocks:

        if isinstance(transcript_data, str):
            lines.append(transcript_data)
        else:
            lines.append("[Empty transcript]")
        return "\n".join(lines)

    prev_speaker = None
    for block in blocks:
        speaker = block.get("speakerName", "")
        text = block.get("transcript", "")
        if not text or not text.strip():
            continue

        if speaker != prev_speaker:
            if prev_speaker is not None:
                lines.append("")
            lines.append(f"[{speaker}]")
            prev_speaker = speaker

        lines.append(text.strip())

    return "\n".join(lines)


def download_all(include_shared=False, direct=False):
    ""
    log.info("=" * 60)
    log.info("TACTIQ TRANSCRIPT DOWNLOADER v2")
    log.info("=" * 60)
    log.info(f"Output: {OUTPUT_DIR}")
    if direct:
        log.info("Mode: DIRECT (Python HTTP, no AppleScript)")


    log.info("PHASE 1: Authentication...")
    if direct:
        token, email = get_firebase_token_direct()
    else:
        token, email = get_firebase_token()
    if not token:
        log.error("Cannot obtain the Firebase token.")
        log.error("Make sure you are logged in to app.tactiq.io")


        raise PermanentAPIError("tactiq: Firebase token missing or expired (log in at app.tactiq.io)")
    log.info(f"Authenticated as: {email}")


    log.info("PHASE 2: Collecting meeting list...")
    meetings = fetch_all_meetings(token, include_shared=include_shared)
    if not meetings:
        log.warning("No meetings found!")
        return

    log.info(f"Total: {len(meetings)} meetings")


    total_duration = sum(m.get("duration", 0) for m in meetings)
    by_platform = {}
    by_lang = {}
    for m in meetings:
        p = m.get("platform", "?")
        by_platform[p] = by_platform.get(p, 0) + 1
        lang = m.get("languageCode", "?")
        by_lang[lang] = by_lang.get(lang, 0) + 1

    log.info(f"Total duration: {total_duration / 3600:.1f} hours")
    log.info(f"Platforms: {by_platform}")
    log.info(f"Languages: {by_lang}")


    index = []
    for m in meetings:
        created = m.get("created", 0)
        date_str = ""
        if created:
            dt = datetime.fromtimestamp(created / 1000, tz=UTC)
            date_str = dt.strftime("%Y-%m-%d")

        index.append(
            {
                "id": m["id"],
                "title": m.get("title", ""),
                "date": date_str,
                "duration": m.get("duration", 0),
                "platform": m.get("platform", ""),
                "language": m.get("languageCode", ""),
                "participants": [p.get("name", "?") for p in m.get("participants", [])],
                "shared": m.get("_shared", False),
            }
        )




    if INDEX_PATH.exists():
        try:
            with open(INDEX_PATH) as fp:
                precedenti = {e["id"]: e for e in json.load(fp) if "id" in e}
        except Exception as e:
            log.warning(f"Previous index unreadable, rewriting from scratch: {e}")
            precedenti = {}
        precedenti.update({e["id"]: e for e in index})
        index = sorted(precedenti.values(), key=lambda e: e.get("date", ""), reverse=True)

    safe_write_json(INDEX_PATH, index)
    log.info(f"Index saved: {INDEX_PATH} ({len(index)} meetings)")


    log.info("=" * 60)
    log.info(f"PHASE 3: Downloading {len(meetings)} transcripts")
    log.info("=" * 60)

    downloaded = 0
    skipped = 0
    errors = 0
    error_list = []
    total_text = 0
    consecutive_auth_fails = 0
    last_refresh = time.time()

    for i, m in enumerate(meetings):
        mid = m["id"]
        title = m.get("title", "unknown")
        created = m.get("created", 0)


        if time.time() - last_refresh > 2700:
            log.info("Proactive token refresh (45 min)...")
            new_token, _ = get_firebase_token_direct() if _direct_mode else get_firebase_token()
            if new_token:
                token = new_token
                last_refresh = time.time()
                log.info("Token refreshed")


        date_str = ""
        if created:
            dt = datetime.fromtimestamp(created / 1000, tz=UTC)
            date_str = dt.strftime("%Y-%m-%d")

        safe_title = "".join(c if c.isalnum() or c in " -_." else "_" for c in title)[:70]
        short_id = mid[:8]
        out_name = f"{date_str}_{safe_title}_{short_id}" if date_str else f"{mid[:12]}_{safe_title}"

        out_json = OUTPUT_DIR / f"{out_name}.json"
        out_txt = OUTPUT_DIR / f"{out_name}.txt"


        old_name = (
            f"{date_str}_{''.join(c if c.isalnum() or c in ' -_.' else '_' for c in title)[:80]}"
        )
        old_json = OUTPUT_DIR / f"{old_name}.json"
        if old_json.exists() and old_json.stat().st_size > 100 and not out_json.exists():

            old_txt = OUTPUT_DIR / f"{old_name}.txt"
            old_json.rename(out_json)
            if old_txt.exists():
                old_txt.rename(out_txt)


        if out_json.exists() and out_json.stat().st_size > 100:
            downloaded += 1
            if (i + 1) % 20 == 0:
                log.debug(f"[{i + 1}/{len(meetings)}] ... ({downloaded} already downloaded)")
            continue

        log.info(f"[{i + 1}/{len(meetings)}] {out_name[:65]}...")

        try:
            trans = fetch_transcript(token, mid)

            if trans and not (isinstance(trans, dict) and "_error" in trans):

                save_data = {
                    "id": mid,
                    "title": title,
                    "created": created,
                    "duration": m.get("duration", 0),
                    "platform": m.get("platform", ""),
                    "languageCode": m.get("languageCode", ""),
                    "participants": m.get("participants", []),
                    "transcript": trans,
                    "downloaded_at": datetime.now(UTC).isoformat(),
                }
                safe_write_json(out_json, save_data)


                text = format_transcript_text(trans, m)
                with open(out_txt, "w") as fp:
                    fp.write(text)

                blocks_count = len(trans.get("blocks", [])) if isinstance(trans, dict) else 0
                text_len = len(text)
                total_text += text_len
                downloaded += 1
                consecutive_auth_fails = 0
                log.info(f"  OK ({text_len / 1024:.1f}KB, {blocks_count} blocks)")
            else:
                err_msg = (
                    trans.get("_error", "empty") if isinstance(trans, dict) else "null_response"
                )
                log.info(f"  SKIP ({err_msg})")
                skipped += 1
                error_list.append({"id": mid, "title": title, "error": err_msg})


                if "nauthorized" in err_msg or "orbidden" in err_msg or "auth" in err_msg.lower():
                    consecutive_auth_fails += 1
                    if consecutive_auth_fails >= 2:
                        log.warning("Auth failure — refreshing token...")
                        new_token, _ = (
                            get_firebase_token_direct() if _direct_mode else get_firebase_token()
                        )
                        if new_token:
                            token = new_token
                            last_refresh = time.time()
                            consecutive_auth_fails = 0
                            log.info("Token refreshed, retrying...")
                            time.sleep(1)

                            trans2 = fetch_transcript(token, mid)
                            if trans2 and not (isinstance(trans2, dict) and "_error" in trans2):
                                save_data = {
                                    "id": mid,
                                    "title": title,
                                    "created": created,
                                    "duration": m.get("duration", 0),
                                    "platform": m.get("platform", ""),
                                    "languageCode": m.get("languageCode", ""),
                                    "participants": m.get("participants", []),
                                    "transcript": trans2,
                                    "downloaded_at": datetime.now(UTC).isoformat(),
                                }
                                safe_write_json(out_json, save_data)
                                text = format_transcript_text(trans2, m)
                                with open(out_txt, "w") as fp:
                                    fp.write(text)
                                blocks_count = (
                                    len(trans2.get("blocks", [])) if isinstance(trans2, dict) else 0
                                )
                                downloaded += 1
                                skipped -= 1
                                error_list.pop()
                                consecutive_auth_fails = 0
                                log.info(
                                    f"  RETRY OK ({len(text) / 1024:.1f}KB, {blocks_count} blocks)"
                                )
                            else:
                                log.error("RETRY FAILED — still unauthorized")


            time.sleep(0.5)

        except Exception as e:
            errors += 1
            err_msg = str(e)[:100]
            log.error(f"ERR: {err_msg}")
            error_list.append({"id": mid, "title": title, "error": err_msg})

            if "timeout" in str(e).lower():
                log.warning("Pausing 5s after timeout...")
                time.sleep(5)


    if error_list:
        safe_write_json(ERRORS_PATH, error_list)

    log.info("=" * 60)
    log.info("FINAL RESULT")
    log.info(f"Downloaded: {downloaded}")
    log.info(f"Skipped:    {skipped}")
    log.info(f"Errors:     {errors}")
    log.info(f"Total text: {total_text / 1024 / 1024:.1f} MB")
    log.info(f"Output:     {OUTPUT_DIR}")
    log.info("=" * 60)



    if errors:
        log.error("tactiq: %d meetings failed — run NOT complete, exit 1", errors)
        sys.exit(1)
    mark_last_run("tactiq")


def verify():
    ""
    log.info("=" * 60)
    log.info("TACTIQ — COMPLETENESS CHECK")
    log.info("=" * 60)

    if not INDEX_PATH.exists():
        log.warning("No index found. Run the download first.")
        return

    with open(INDEX_PATH) as fp:
        index = json.load(fp)

    json_files = list(OUTPUT_DIR.glob("*.json"))
    json_files = [f for f in json_files if not f.name.startswith("_")]
    txt_files = list(OUTPUT_DIR.glob("*.txt"))

    log.info(f"Meetings in index: {len(index)}")
    log.info(f"JSON files downloaded: {len(json_files)}")
    log.info(f"TXT files downloaded: {len(txt_files)}")


    total_size = 0
    total_blocks = 0
    total_text_chars = 0
    empty_transcripts = []
    small_transcripts = []
    by_language = {}
    by_platform = {}
    speakers_all = {}
    date_range = [None, None]

    for jf in json_files:
        try:
            with open(jf) as fp:
                data = json.load(fp)

            size = jf.stat().st_size
            total_size += size

            trans = data.get("transcript", {})
            blocks = trans.get("blocks", []) if isinstance(trans, dict) else []
            total_blocks += len(blocks)

            if len(blocks) == 0:
                empty_transcripts.append(data.get("title", jf.name))
            elif len(blocks) < 5:
                small_transcripts.append(data.get("title", jf.name))


            for b in blocks:
                text = b.get("transcript", "")
                total_text_chars += len(text)
                spk = b.get("speakerName", "unknown")
                speakers_all[spk] = speakers_all.get(spk, 0) + 1


            lang = data.get("languageCode") or (trans.get("detectedLanguage", {}) or {}).get(
                "shortName", "?"
            )
            by_language[lang] = by_language.get(lang, 0) + 1


            plat = data.get("platform", "?")
            by_platform[plat] = by_platform.get(plat, 0) + 1


            created = data.get("created", 0)
            if created:
                dt = datetime.fromtimestamp(created / 1000, tz=UTC)
                if date_range[0] is None or dt < date_range[0]:
                    date_range[0] = dt
                if date_range[1] is None or dt > date_range[1]:
                    date_range[1] = dt

        except Exception:
            empty_transcripts.append(jf.name)

    log.info(f"Total JSON size: {total_size / 1024 / 1024:.1f} MB")
    log.info(f"Total blocks: {total_blocks:,}")
    log.info(f"Total text: {total_text_chars:,} chars ({total_text_chars / 1024 / 1024:.1f} MB)")

    if date_range[0] and date_range[1]:
        log.info(
            f"Period: {date_range[0].strftime('%Y-%m-%d')} → {date_range[1].strftime('%Y-%m-%d')}"
        )

    log.info(f"Languages: {by_language}")
    log.info(f"Platforms: {by_platform}")


    if speakers_all:
        log.info("Top 15 speakers:")
        for spk, count in sorted(speakers_all.items(), key=lambda x: -x[1])[:15]:
            log.info(f"  {spk}: {count} blocks")

    if empty_transcripts:
        log.warning(f"Empty transcripts ({len(empty_transcripts)}):")
        for t in empty_transcripts[:10]:
            log.warning(f"  - {t[:60]}")
        if len(empty_transcripts) > 10:
            log.warning(f"  ... and {len(empty_transcripts) - 10} more")

    if small_transcripts:
        log.warning(f"Very short transcripts <5 blocks ({len(small_transcripts)}):")
        for t in small_transcripts[:10]:
            log.warning(f"  - {t[:60]}")


    downloaded_ids = set()
    for jf in json_files:
        try:
            with open(jf) as fp:
                data = json.load(fp)
            downloaded_ids.add(data.get("id", ""))
        except Exception:
            pass

    index_ids = {m["id"] for m in index}
    missing = index_ids - downloaded_ids
    if missing:
        log.warning(f"Missing meetings ({len(missing)}):")
        for m in index:
            if m["id"] in missing:
                log.warning(f"  - [{m.get('date', '')}] {m['title'][:50]} (ID: {m['id'][:15]})")
    else:
        log.info("COMPLETE: all meetings in the index have been downloaded!")

    log.info("=" * 60)


def main():
    global _direct_mode
    parser = argparse.ArgumentParser(description="Tactiq Transcript Downloader v2")
    parser.add_argument("--verify", action="store_true", help="Verify completeness")



    parser.add_argument(
        "--shared", action="store_true", default=True, help="Include SharedWithMe (default)"
    )
    parser.add_argument(
        "--no-shared", dest="shared", action="store_false", help="Own meetings only"
    )
    parser.add_argument(
        "--direct",
        action="store_true",
        help="Direct mode: use Python HTTP instead of AppleScript/Chrome (useful when Playwright Chrome interferes)",
    )
    args = parser.parse_args()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    _direct_mode = args.direct

    if args.verify:
        verify()
    else:
        download_all(include_shared=args.shared, direct=args.direct)


from pipeline_decorator import pipeline_step


@pipeline_step(name="l0-tactiq-download", source="tactiq", stage="l0", mark_run=False)
def run():
    main()


if __name__ == "__main__":
    run()
