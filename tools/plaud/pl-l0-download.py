#!/usr/bin/env python3
"""Plaud download: the transcripts of your Plaud recordings, through the Plaud desktop app session (--direct, the
default path) or an open plaud.ai tab in Chrome (--chrome); keeps an index, a version ledger and the duplicates
aside, and can ask Plaud to transcribe the recordings that have no transcript yet (--transcribe).
"""

import argparse
import json
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))
from sbk_config import PLAUD_API_BASE, PLAUD_DIR, mark_last_run, safe_write_json

OUTPUT_DIR = PLAUD_DIR  # Created when the script runs, not at import, so --help writes nothing.
INDEX_PATH = OUTPUT_DIR / "_file_index.json"



VERSION_LEDGER_PATH = OUTPUT_DIR / "_version_ledger.json"



COVERAGE_PATH = OUTPUT_DIR / "_coverage.json"


DOPPIONI_DIR = OUTPUT_DIR / "_doppioni"


PAGINA_ELENCO = 9999

FALLITA_SU_PLAUD = "fallita_su_plaud_"


CODA_TRASCRIZIONI_PATH = OUTPUT_DIR / "_trascrizioni.json"
COPIE_DETTAGLI_DIR = OUTPUT_DIR / "_copie-dettagli"

# Region host of your Plaud account: sbk.config.json plaud.api_base or env SBK_PLAUD_API_BASE
# (default the EU host https://api-euc1.plaud.ai).
API_BASE = PLAUD_API_BASE


USER_AGENT_BROWSER = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/138.0.0.0 Safari/537.36"
)
ELECTRON_WRAPPER_DIR = Path(__file__).resolve().parent / "electron-decrypt"


_DIRECT_TOKEN = None


def get_token_direct():
    ""











    try:
        from tools.plaud import pl_auth_refresh as _par
        from tools.plaud.pl_wt_auth import TokenKind, decode_jwt_payload, select_token

        def _exp(tok):
            try:
                return decode_jwt_payload(tok).get("exp", 0)
            except Exception:  # noqa: BLE001
                return 0

        wt = _par.load_saved_wt()
        store_wt = None
        try:
            store_wt = select_token(_par.load_store_py(), TokenKind.WT)
        except Exception:  # noqa: BLE001 - store unreadable: the saved WT remains
            pass
        if store_wt and _exp(store_wt) > _exp(wt or ""):
            wt = store_wt
            _par.save_wt({"WT": store_wt})
        if not wt:
            store = _par.load_store_py()
            ctx = _par.build_context(store)
            result = _par.refresh_wt(ctx)
            _par.save_wt(result["found"])
            wt = result["found"]["WT"]
        if wt:
            return f"Bearer {wt}"
    except Exception as e:  # noqa: BLE001 - the Electron fallback stays as the safety net
        print(f"  pl_auth_refresh unavailable ({e}); Electron wrapper fallback...")

    enc_path = Path.home() / "Library/Application Support/Plaud/encryption.json"
    if not enc_path.exists():
        raise RuntimeError(
            f"encryption.json not found in {enc_path}. "
            "Install Plaud.app desktop and log in at least once."
        )


    try:
        subprocess.run(
            [
                "security",
                "find-generic-password",
                "-s",
                "Plaud Safe Storage",
                "-a",
                "Plaud Key",
                "-w",
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
    except subprocess.CalledProcessError as e:
        raise RuntimeError(
            "Keychain entry 'Plaud Safe Storage / Plaud Key' not found. "
            "Launch Plaud.app desktop at least once to generate it."
        ) from e


    if not ELECTRON_WRAPPER_DIR.exists():
        raise RuntimeError(f"Electron wrapper not found in {ELECTRON_WRAPPER_DIR}")

    electron_bin = ELECTRON_WRAPPER_DIR / "node_modules" / ".bin" / "electron"
    if not electron_bin.exists():

        if not shutil.which("npm"):
            raise RuntimeError("npm not installed. Install Node.js to use --direct.")
        print(f"  Electron not installed. Installing in {ELECTRON_WRAPPER_DIR}...")
        subprocess.run(
            ["npm", "install", "electron", "--no-audit", "--no-fund"],
            cwd=ELECTRON_WRAPPER_DIR,
            check=True,
            timeout=300,
        )
        if not electron_bin.exists():
            raise RuntimeError("npm install electron failed")
        print("  Electron installed.")


    result = subprocess.run(
        [str(electron_bin), "main.js"],
        cwd=str(ELECTRON_WRAPPER_DIR),
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Electron wrapper fail: {result.stderr[:300]}")

    decrypted = json.loads(result.stdout)
    auth_token = decrypted.get("authToken", "")
    if not auth_token or auth_token.startswith("ERR:"):
        raise RuntimeError(f"authToken decryption fail: {auth_token}")
    return auth_token


def api_get_direct(path, timeout=30):
    ""
    return json.loads(_api_get_bytes(path, timeout))


def _api_get_bytes(path, timeout=30):
    ""
    if not _DIRECT_TOKEN:
        raise RuntimeError("Token direct not initialized")
    req = urllib.request.Request(
        f"{API_BASE}{path}",
        headers={
            "Authorization": _DIRECT_TOKEN,
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw_bytes = resp.read()
    if raw_bytes[:2] == b"\x1f\x8b" or resp.headers.get("Content-Encoding") == "gzip":
        import gzip as _gzip

        raw_bytes = _gzip.decompress(raw_bytes)
    return raw_bytes


def _api_post_direct(path, corpo, intestazioni, timeout=30):
    ""
    from tools.plaud.pl_trascrizioni import ErroreHttp

    req = urllib.request.Request(
        f"{API_BASE}{path}",
        data=json.dumps(corpo).encode("utf-8"),
        method="POST",
        headers={
            **intestazioni,
            "Authorization": _DIRECT_TOKEN,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": USER_AGENT_BROWSER,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raise ErroreHttp(e.code, str(e.reason)) from e
    except urllib.error.URLError as e:
        raise ErroreHttp(0, str(e.reason)) from e


def _versione_app_plaud() -> str:
    ""
    import plistlib

    with open("/Applications/Plaud.app/Contents/Info.plist", "rb") as fp:
        return plistlib.load(fp)["CFBundleShortVersionString"]


class _ClientePlaud:
    ""

    def __init__(self):
        from tools.plaud import pl_auth_refresh as _par
        from tools.plaud.pl_exec_http import make_request_id

        self.device = _par.build_context(_par.load_store_py())["device_uuid"]
        self.versione = _versione_app_plaud()
        self._request_id = make_request_id

    def dettaglio(self, file_id):
        from tools.plaud.pl_trascrizioni import ErroreHttp

        try:
            grezzo = _api_get_bytes(f"/file/detail/{file_id}")
        except urllib.error.HTTPError as e:
            raise ErroreHttp(e.code, str(e.reason)) from e
        dati = json.loads(grezzo)
        return (dati.get("data") or dati), grezzo

    def richiesta(self, file_id, corpo):
        from tools.plaud.pl_trascrizioni import intestazioni_app

        return _api_post_direct(
            f"/ai/transsumm/{file_id}",
            corpo,
            intestazioni_app(self.versione, self.device, self._request_id()),
        )


def _rinnova_wt_forzato() -> str:
    ""
    from tools.plaud import pl_auth_refresh as _par

    result = _par.refresh_wt(_par.build_context(_par.load_store_py()))
    _par.save_wt(result["found"])
    print(f"  WT renewed (via {result.get('via')})")
    return f"Bearer {result['found']['WT']}"


def fetch_file_list_direct():
    ""









    global _DIRECT_TOKEN
    visti: dict = {}
    totale = None
    rinnovato = False
    while True:
        path = (
            f"/file/simple/web?skip={len(visti)}&limit={PAGINA_ELENCO}"
            "&is_trash=2&sort_by=start_time&is_desc=true"
        )
        data = api_get_direct(path, timeout=60)
        if data.get("status") == -419 and not rinnovato:
            print("  the server says -419 (workspace token expired): renewing the WT and retrying")
            _DIRECT_TOKEN = _rinnova_wt_forzato()
            rinnovato = True
            data = api_get_direct(path, timeout=60)
        if data.get("status") not in (None, 0) or "data_file_list" not in data:
            raise RuntimeError(
                f"Plaud file list rejected by the server: status={data.get('status')} "
                f"msg={data.get('msg')!r}"
            )
        pagina = data.get("data_file_list") or []
        if data.get("data_file_total") is not None:
            totale = data["data_file_total"]
        nuovi = [f for f in pagina if f.get("id") not in visti]
        if pagina and not nuovi:
            raise RuntimeError(
                f"Plaud list: the page from {len(visti)} repeats already-seen recordings"
            )
        for f in nuovi:
            visti[f.get("id")] = f
        finita = len(visti) >= totale if totale is not None else len(pagina) < PAGINA_ELENCO
        if not pagina or finita:
            break
    if totale is not None and len(visti) != totale:
        raise RuntimeError(
            f"Plaud list incomplete: {len(visti)} recordings of {totale} declared"
        )
    files = list(visti.values())
    return {
        "total": totale if totale is not None else len(files),
        "files": [
            {
                "id": f.get("id"),
                "fn": f.get("filename"),
                "dur": f.get("duration"),
                "st": f.get("start_time"),
                "tr": f.get("is_trans"),
                "sc": f.get("scene"),



                "vms": f.get("version_ms"),
                "et": f.get("edit_time"),
                "ver": f.get("version"),
                "trash": f.get("is_trash"),
            }
            for f in files
        ],
    }


def fetch_transcript_direct(file_id):
    ""
    try:
        detail = api_get_direct(f"/file/detail/{file_id}", timeout=30)
        content_list = (detail.get("data") or detail).get("content_list") or detail.get(
            "content_list", []
        )
        trans_link = None
        stato_compito = None
        for item in content_list:
            if item.get("data_type") == "transaction":
                trans_link = item.get("data_link")
                stato_compito = item.get("task_status")
                break
        if not trans_link:



            if isinstance(stato_compito, int) and stato_compito < 0:
                return {"_error": f"{FALLITA_SU_PLAUD}{stato_compito}"}
            return {"_error": "no_link"}

        req = urllib.request.Request(
            trans_link,
            headers={"User-Agent": "Mozilla/5.0", "Accept-Encoding": "gzip"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw_bytes = resp.read()

        if raw_bytes[:2] == b"\x1f\x8b" or resp.headers.get("Content-Encoding") == "gzip":
            import gzip as _gzip

            raw_bytes = _gzip.decompress(raw_bytes)
        raw = raw_bytes.decode("utf-8", errors="replace")
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"_raw": raw[:5000]}
    except urllib.error.HTTPError as e:
        return {"_error": f"http_{e.code}"}
    except Exception as e:
        return {"_error": str(e)[:80]}


def chrome_js(js_code, timeout=30):
    ""

    escaped = js_code.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")

    applescript = f'''
    tell application "Google Chrome"
        repeat with w in windows
            repeat with t in tabs of w
                if URL of t contains "plaud.ai" then
                    tell t
                        set jsResult to execute javascript "{escaped}"
                    end tell
                    return jsResult
                end if
            end repeat
        end repeat
        return "ERROR_NO_PLAUD_TAB"
    end tell
    '''

    result = subprocess.run(
        ["osascript", "-e", applescript], capture_output=True, text=True, timeout=timeout
    )

    output = result.stdout.strip()
    if output == "ERROR_NO_PLAUD_TAB":
        print("ERROR: No Plaud tab open!")
        sys.exit(1)
    if result.returncode != 0:
        print(f"AppleScript error: {result.stderr[:200]}")
        return None

    return output


def fetch_file_list():
    ""
    js = """
    (function() {
        var tokenStr = localStorage.getItem('tokenstr');
        var xhr = new XMLHttpRequest();
        xhr.open('GET', '__API_BASE__/file/simple/web?skip=0&limit=9999&is_trash=2&sort_by=start_time&is_desc=true', false);
        xhr.setRequestHeader('Authorization', tokenStr);
        xhr.send();
        var data = JSON.parse(xhr.responseText);
        var files = data.data_file_list.map(function(f) {
            return {
                id: f.id,
                fn: f.filename,
                dur: f.duration,
                st: f.start_time,
                tr: f.is_trans,
                sc: f.scene
            };
        });
        return JSON.stringify({total: data.data_file_total, files: files});
    })()
    """
    result = chrome_js(js.replace("__API_BASE__", API_BASE), timeout=60)
    data = json.loads(result)
    return data


def fetch_transcript_from_browser(file_id):
    ""
    js = f"""
    (function() {{
        try {{
            var tokenStr = localStorage.getItem('tokenstr');
            var xhr = new XMLHttpRequest();
            xhr.open('GET', '{API_BASE}/file/detail/{file_id}', false);
            xhr.setRequestHeader('Authorization', tokenStr);
            xhr.send();
            if (xhr.status !== 200) return JSON.stringify({{error: 'detail_' + xhr.status}});

            var detail = JSON.parse(xhr.responseText);
            var contentList = detail.data.content_list || [];
            var transLink = '';
            for (var i = 0; i < contentList.length; i++) {{
                if (contentList[i].data_type === 'transaction') {{
                    transLink = contentList[i].data_link;
                    break;
                }}
            }}

            if (!transLink) return JSON.stringify({{error: 'no_link'}});

            // Download the transcript from S3
            var xhr2 = new XMLHttpRequest();
            xhr2.open('GET', transLink, false);
            xhr2.send();
            if (xhr2.status !== 200) return JSON.stringify({{error: 's3_' + xhr2.status}});

            return xhr2.responseText;
        }} catch(e) {{
            return JSON.stringify({{error: e.message}});
        }}
    }})()
    """
    result = chrome_js(js, timeout=60)
    if not result:
        return None

    try:
        data = json.loads(result)
        if isinstance(data, dict) and "error" in data:
            return {"_error": data["error"]}
        return data
    except json.JSONDecodeError:

        return {"_raw": result[:5000]}


def format_transcript(trans_data):
    ""
    if not trans_data or isinstance(trans_data, str):
        return trans_data or ""

    if isinstance(trans_data, dict):
        if "_error" in trans_data:
            return f"[ERROR: {trans_data['_error']}]"
        if "_raw" in trans_data:
            return trans_data["_raw"]

    lines = []
    segments = trans_data if isinstance(trans_data, list) else []
    if isinstance(trans_data, dict):
        segments = trans_data.get("segments", trans_data.get("results", trans_data.get("data", [])))

    if isinstance(segments, list):
        for seg in segments:
            if isinstance(seg, dict):
                speaker = seg.get("speaker", seg.get("speaker_label", seg.get("spk", "")))
                text = seg.get("text", seg.get("transcript", seg.get("content", "")))
                if isinstance(text, str) and text.strip():
                    if speaker:
                        lines.append(f"[{speaker}] {text.strip()}")
                    else:
                        lines.append(text.strip())
            elif isinstance(seg, str):
                lines.append(seg)

    if not lines and isinstance(trans_data, dict):
        return json.dumps(trans_data, ensure_ascii=False, indent=2)

    return "\n".join(lines)


def _load_version_ledger():
    ""
    if VERSION_LEDGER_PATH.exists():
        try:
            with open(VERSION_LEDGER_PATH) as fp:
                data = json.load(fp)
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _remote_version_key(f_info):
    ""



    vms = f_info.get("version_ms")
    if vms is not None:
        return ("version_ms", vms)
    et = f_info.get("edit_time")
    if et is not None:
        return ("edit_time", et)
    return None


def _needs_download(file_id, remote_key, ledger, file_exists, force_ids):
    ""









    if file_id in force_ids:
        return True, "forced"
    if not file_exists:
        return True, "new"
    if remote_key is None:
        return False, "legacy_exists"
    rec = ledger.get(file_id)
    if not isinstance(rec, dict):
        return False, "backfill_new_record"
    kind, val = remote_key
    prev = rec.get(kind)
    if prev is None:
        return False, "backfill_missing_kind"
    if val > prev:
        return True, "version_newer"
    return False, "unchanged"


def _ledger_record(f_info, out_name):
    ""
    return {
        "version_ms": f_info.get("version_ms"),
        "edit_time": f_info.get("edit_time"),
        "version": f_info.get("version"),
        "out_name": out_name,
    }


def _id_dal_txt(path):
    ""
    try:
        with open(path, encoding="utf-8", errors="replace") as fp:
            for _ in range(6):
                riga = fp.readline()
                if riga.startswith("# ID:"):
                    return riga[5:].strip() or None
    except OSError:
        return None
    return None


def file_per_id(ledger):
    ""







    per_id = {}
    for txt in sorted(OUTPUT_DIR.glob("*.txt")):
        if txt.name.startswith(("_", ".")):
            continue
        fid = _id_dal_txt(txt)
        if fid:
            per_id.setdefault(fid, []).append(txt.stem)
    rivendicati = {n for nomi in per_id.values() for n in nomi}
    for fid, rec in ledger.items():
        nome = rec.get("out_name") if isinstance(rec, dict) else None
        if nome and nome not in rivendicati and (OUTPUT_DIR / f"{nome}.json").exists():
            per_id.setdefault(fid, []).append(nome)
            rivendicati.add(nome)
    return per_id


def metti_da_parte_doppioni(per_id, ledger):
    ""





    spostati = 0
    for fid, nomi in per_id.items():
        if len(nomi) < 2:
            continue
        rec = ledger.get(fid)
        dal_registro = rec.get("out_name") if isinstance(rec, dict) else None
        if dal_registro in nomi:
            tenuto = dal_registro
        else:
            tenuto = max(nomi, key=lambda n: (OUTPUT_DIR / f"{n}.txt").stat().st_mtime)
        DOPPIONI_DIR.mkdir(exist_ok=True)
        for nome in nomi:
            if nome == tenuto:
                continue
            for est in (".json", ".txt"):
                sorgente = OUTPUT_DIR / f"{nome}{est}"
                if sorgente.exists():
                    sorgente.rename(DOPPIONI_DIR / sorgente.name)
                    spostati += 1
            with open(DOPPIONI_DIR / "_spostati.jsonl", "a", encoding="utf-8") as fp:
                riga = {
                    "id": fid,
                    "spostato": nome,
                    "tenuto": tenuto,
                    "il": datetime.now().isoformat(),
                }
                fp.write(json.dumps(riga, ensure_ascii=False) + "\n")
        per_id[fid] = [tenuto]
    return spostati


def doppioni_in_tutto():
    ""
    registro = DOPPIONI_DIR / "_spostati.jsonl"
    if not registro.exists():
        return 0
    return sum(1 for riga in registro.read_text(encoding="utf-8").splitlines() if riga.strip())


def nome_nuovo(date, filename, file_id, occupati):
    ""

    safe_name = "".join(c if c.isalnum() or c in " -_." else "_" for c in filename or "")[:100]
    nome = f"{date}_{safe_name}"
    return f"{nome}__{file_id}" if nome in occupati else nome


def _scarica_e_salva(f_info, out_name, use_direct):
    ""



    file_id = f_info["id"]
    if use_direct:
        trans = fetch_transcript_direct(file_id)
    else:
        trans = fetch_transcript_from_browser(file_id)
    if not trans or (isinstance(trans, dict) and "_error" in trans):
        return (trans.get("_error", "unknown") if isinstance(trans, dict) else "empty"), None
    safe_write_json(OUTPUT_DIR / f"{out_name}.json", trans)
    text = format_transcript(trans)
    with open(OUTPUT_DIR / f"{out_name}.txt", "w") as fp:
        fp.write(f"# {f_info['filename']}\n")
        fp.write(f"# Date: {f_info['date']}\n")
        fp.write(f"# Duration: {f_info['duration_sec']:.0f}s\n")
        fp.write(f"# ID: {file_id}\n\n")
        fp.write(text)
    return None, text


def _indice(files):
    ""
    index = []
    for f in files:
        start_ts = f["st"] / 1000 if f["st"] else 0
        date_str = datetime.fromtimestamp(start_ts).strftime("%Y-%m-%d") if start_ts else "unknown"
        index.append(
            {
                "id": f["id"],
                "filename": f["fn"],
                "date": date_str,



                "st": f.get("st"),
                "duration_sec": f["dur"] / 1000,
                "has_transcript": f["tr"],
                "scene": f["sc"],
                "version_ms": f.get("vms"),
                "edit_time": f.get("et"),
                "version": f.get("ver"),
                "is_trash": f.get("trash"),
            }
        )
    return index


def _impostazioni_plaud():
    ""
    import impostazioni_pipeline

    return impostazioni_pipeline.leggi()["plaud"]


def _chiedi_trascrizioni(index, prova, solo):
    ""
    from tools.plaud import pl_trascrizioni

    imp = _impostazioni_plaud()
    cliente = None if prova else _ClientePlaud()
    return pl_trascrizioni.gestisci(
        cliente,
        index,
        CODA_TRASCRIZIONI_PATH,
        COPIE_DETTAGLI_DIR,
        minuti_giorno=imp["minuti_giorno"],
        soglia_s=imp["soglia_secondi"],
        solo=set(solo) if solo else None,
        prova=prova,
    )


def main(
    use_direct=False,
    no_early_stop=False,
    re_download=None,
    trascrivi=False,
    prova_trascrizioni=False,
    solo_trascrizioni=None,
):
    global _DIRECT_TOKEN
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    force_ids = set(re_download or [])

    print("=" * 60)
    print("PLAUD TRANSCRIPT DOWNLOADER v2")
    if use_direct:
        print("MODE: --direct (Electron safeStorage decryption, no Chrome tab)")
    else:
        print("MODE: AppleScript (Chrome tab plaud.ai required)")
    if no_early_stop:
        print("MODE: --no-early-stop (scan all missing files, no early-stop)")
    print("=" * 60)
    print(f"Output: {OUTPUT_DIR}")
    print()


    if use_direct:
        print("Decrypting bearer JWT via Electron safeStorage...")
        _DIRECT_TOKEN = get_token_direct()
        print("  Token OK")
        print()


    print("Downloading file list...")
    if use_direct:
        data = fetch_file_list_direct()
    else:
        print("  (via Chrome browser)")
        data = fetch_file_list()
    files = data["files"]
    print(f"  {len(files)} files found")

    index = _indice(files)



    trascrizioni = None
    if use_direct and (trascrivi or prova_trascrizioni or solo_trascrizioni):
        try:
            trascrizioni = _chiedi_trascrizioni(index, prova_trascrizioni, solo_trascrizioni)
        except Exception as e:  # noqa: BLE001
            if prova_trascrizioni:
                raise


            print(
                f"  ⚠️ transcription requests stopped, the download continues: {type(e).__name__}: {e}"
            )
            trascrizioni = {"errore": f"{type(e).__name__}: {e}", "pronte": []}
        if prova_trascrizioni:
            print(
                f"  Test: {trascrizioni['candidati']} to request from Plaud, "
                f"{trascrizioni['minuti_candidati']} minutes. No call, nothing downloaded."
            )
            return
        if trascrizioni["pronte"]:
            print(f"  {len(trascrizioni['pronte'])} transcriptions ready: re-reading the list")
            data = fetch_file_list_direct()
            files = data["files"]
            index = _indice(files)

    safe_write_json(INDEX_PATH, index)

    with_trans = sum(1 for f in index if f["has_transcript"])
    total_duration = sum(f["duration_sec"] for f in index)
    print(f"  With transcript: {with_trans}/{len(index)}")
    print(f"  Total duration: {total_duration / 3600:.1f} hours")
    print()


    print("=" * 60)
    print(f"DOWNLOADING {with_trans} TRANSCRIPTS")
    print("=" * 60)
    print()

    downloaded = 0
    skipped = 0
    errors = 0
    error_list = []
    consecutive_existing = 0
    ledger = _load_version_ledger()
    ledger_dirty = False
    refreshed = 0
    nuove = 0
    fermato_presto = False
    da_riprovare = []
    fallite_su_plaud = []

    nomi = file_per_id(ledger)
    spostati = metti_da_parte_doppioni(nomi, ledger)
    if spostati:
        print(f"  Duplicates set aside in {DOPPIONI_DIR.name}/: {spostati} files")
    occupati = {p.stem for p in OUTPUT_DIR.glob("*.json")} | {
        p.stem for p in OUTPUT_DIR.glob("*.txt")
    }

    def _registra_riuscita(f_info, out_name, remote_key, text):
        nonlocal downloaded, nuove, ledger_dirty
        downloaded += 1
        nuove += 1
        if remote_key is not None:
            ledger[f_info["id"]] = _ledger_record(f_info, out_name)
            ledger_dirty = True
        print(f"OK ({len(text) / 1024:.1f}KB)")

    for i, f_info in enumerate(index):
        file_id = f_info["id"]

        if not f_info["has_transcript"]:
            skipped += 1
            continue


        out_name = (nomi.get(file_id) or [None])[0] or nome_nuovo(
            f_info["date"], f_info["filename"], file_id, occupati
        )
        occupati.add(out_name)
        out_txt = OUTPUT_DIR / f"{out_name}.txt"

        file_exists = out_txt.exists() and out_txt.stat().st_size > 100
        remote_key = _remote_version_key(f_info)
        need, reason = _needs_download(file_id, remote_key, ledger, file_exists, force_ids)

        if not need:


            if reason.startswith("backfill") and remote_key is not None:
                ledger[file_id] = _ledger_record(f_info, out_name)
                ledger_dirty = True
            downloaded += 1


            if remote_key is None:
                consecutive_existing += 1
                if not no_early_stop and consecutive_existing >= 10:
                    remaining = len(index) - i - 1
                    print(
                        f"  Early stop: 10 consecutive existing files found, skipping {remaining} remaining files"
                    )
                    fermato_presto = True
                    break
            if (i + 1) % 50 == 0:
                print(f"  [{i + 1}/{len(index)}] ... ({downloaded} present/updated)")
            continue

        consecutive_existing = 0
        if reason in ("version_newer", "forced"):
            refreshed += 1
        tag = f"RE-DOWNLOAD ({reason}) " if reason in ("version_newer", "forced") else ""

        print(f"  [{i + 1}/{len(index)}] {tag}{out_name[:60]}...", end=" ", flush=True)
        try:
            motivo, text = _scarica_e_salva(f_info, out_name, use_direct)
        except Exception as e:  # noqa: BLE001 - retried at the end, then counts as an error
            motivo, text = str(e)[:80], None
            if "timeout" in str(e).lower():
                print("  Pausing 5s for timeout...")
                time.sleep(5)
        if motivo is None:
            _registra_riuscita(f_info, out_name, remote_key, text)
        elif motivo.startswith(FALLITA_SU_PLAUD):
            print(f"FAILED ON PLAUD (task_status {motivo[len(FALLITA_SU_PLAUD) :]})")
            fallite_su_plaud.append(
                {
                    "id": file_id,
                    "task_status": int(motivo[len(FALLITA_SU_PLAUD) :]),
                    "durata_s": f_info["duration_sec"],
                }
            )
        else:


            print(f"ERROR ({motivo}), will retry at the end")
            da_riprovare.append((i, f_info, out_name, remote_key))


        time.sleep(0.3)

    if da_riprovare:
        print(f"\nRetrying {len(da_riprovare)} failed transcriptions...")
        time.sleep(5)
    for i, f_info, out_name, remote_key in da_riprovare:
        print(f"  [{i + 1}/{len(index)}] again {out_name[:60]}...", end=" ", flush=True)
        try:
            motivo, text = _scarica_e_salva(f_info, out_name, use_direct)
        except Exception as e:  # noqa: BLE001
            motivo, text = str(e)[:80], None
        if motivo is None:
            _registra_riuscita(f_info, out_name, remote_key, text)
        else:
            errors += 1
            print(f"ERR: {motivo}")
            error_list.append({"id": f_info["id"], "name": f_info["filename"], "error": motivo})
        time.sleep(0.3)


    if error_list:
        safe_write_json(OUTPUT_DIR / "_errors.json", error_list)


    if ledger_dirty:
        safe_write_json(VERSION_LEDGER_PATH, ledger)


    safe_write_json(
        COVERAGE_PATH,
        {
            "generato": datetime.now().isoformat(timespec="seconds"),
            "nell_elenco": len(index),
            "totale_dichiarato": data.get("total"),
            "con_trascrizione": with_trans,
            "senza_trascrizione": len(index) - with_trans,
            "sul_disco_aggiornate": downloaded,
            "scaricate_in_questo_giro": nuove,
            "riscaricate": refreshed,
            "in_errore": len(error_list),
            "errori": error_list,
            "fallite_su_plaud": len(fallite_su_plaud),
            "fallite_su_plaud_elenco": fallite_su_plaud,
            "doppioni_messi_da_parte": spostati,
            "doppioni_messi_da_parte_in_tutto": doppioni_in_tutto(),
            "giro_completo": not fermato_presto,
            "trascrizioni_chieste": trascrizioni,
        },
    )

    print()
    print("=" * 60)
    print("FINAL RESULT")
    print(f"  Downloaded: {downloaded}")
    print(f"  Refreshed:  {refreshed}  (remote version advanced / forced)")
    print(f"  Skipped:    {skipped}  (no transcription on Plaud)")
    print(f"  Errors:     {errors}")
    print(
        f"  Failed on Plaud: {len(fallite_su_plaud)}  (the transcription on Plaud is missing, see the receipt)"
    )
    print(f"  Output:     {OUTPUT_DIR}")
    print("=" * 60)



    if errors:
        print(f"plaud: {errors} files in error — run NOT complete, exit 1", flush=True)
        sys.exit(1)
    mark_last_run("plaud")


from pipeline_decorator import pipeline_step


def _parse_args():
    p = argparse.ArgumentParser(description="Plaud transcript downloader v2")



    p.add_argument(
        "--direct",
        action="store_true",
        help="The default mode: Plaud API with the Mac app tokens, without Chrome (can be omitted)",
    )
    p.add_argument(
        "--chrome",
        action="store_true",
        help="The old mode, inside a plaud.ai Chrome tab via osascript: only if requested",
    )
    p.add_argument(
        "--no-early-stop",
        action="store_true",
        help="Do not stop at 10 consecutive already-existing files, scan everything",
    )
    p.add_argument(
        "--transcribe",
        action=argparse.BooleanOptionalAction,
        default=None,
        dest="trascrivi",
        help=(
            "Ask Plaud for the missing transcriptions (default: the pipeline setting "
            "plaud.transcribe)"
        ),
    )
    p.add_argument(
        "--dry-transcriptions",
        action="store_true",
        dest="prova_trascrizioni",
        help=(
            "Say how many transcriptions it would request and how many minutes, without "
            "calling Plaud and without downloading"
        ),
    )
    p.add_argument(
        "--only-transcriptions",
        nargs="+",
        metavar="FILE_ID",
        default=None,
        dest="solo_trascrizioni",
        help="Ask for the transcription of only these file_id (for tests)",
    )
    # Older Italian names, kept as hidden aliases so existing scripts keep working.
    p.add_argument(
        "--trascrivi",
        action=argparse.BooleanOptionalAction,
        default=None,
        dest="trascrivi",
        help=argparse.SUPPRESS,
    )
    p.add_argument(
        "--prova-trascrizioni",
        action="store_true",
        dest="prova_trascrizioni",
        help=argparse.SUPPRESS,
    )
    p.add_argument(
        "--solo-trascrizioni",
        nargs="+",
        metavar="FILE_ID",
        default=None,
        dest="solo_trascrizioni",
        help=argparse.SUPPRESS,
    )
    p.add_argument(
        "--re-download",
        nargs="+",
        metavar="FILE_ID",
        default=None,
        help="Force the re-download of one or more file_id (e.g. after a speaker correction on Plaud)",
    )
    return p.parse_args()


@pipeline_step(name="l0-plaud-download", source="plaud", stage="l0", mark_run=False)
def run():
    args = _parse_args()
    trascrivi = args.trascrivi if args.trascrivi is not None else _impostazioni_plaud()["trascrivi"]
    main(
        use_direct=not args.chrome,
        no_early_stop=args.no_early_stop,
        re_download=args.re_download,
        trascrivi=trascrivi,
        prova_trascrizioni=args.prova_trascrizioni,
        solo_trascrizioni=args.solo_trascrizioni,
    )


if __name__ == "__main__":
    run()
