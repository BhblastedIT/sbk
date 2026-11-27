#!/usr/bin/env python3
"""Plaud long recordings: split single-voice recordings over three hours into pieces at silences, upload the pieces to Plaud and check their transcription."""



























from __future__ import annotations

import argparse
import datetime as dt
import gzip
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

DATA = Path(
    os.environ.get("SBK_DATA") or os.environ.get("SBK_DATA_ROOT") or Path.home() / ".sbk-data"
).expanduser()
PLAUD = DATA / "plaud"
INDICE = PLAUD / "raw" / "_file_index.json"
DETTAGLI = PLAUD / "dettagli"
CARTELLA = PLAUD / "lunghe"
REGISTRO = CARTELLA / "registro.jsonl"
LAVORO = Path(os.environ.get("SBK_SCRATCH") or (CARTELLA / "_audio"))

PEZZO_MAX_S = 170 * 60
FINESTRA_S = 10 * 60
SOVRAPPOSIZIONE_S = 60
SOGLIA_ORE = 3
PARTE_BYTES = 5 * 1024 * 1024
MAX_BYTES = 500 * 1024 * 1024
ATTESA_TRASCRIZIONE_S = 30 * 60
PASSO_S = 20





def silenzi(stderr: str) -> list[tuple[float, float]]:
    ""
    out, inizio = [], None
    for riga in stderr.splitlines():
        m = re.search(r"silence_start: (-?[\d.]+)", riga)
        if m:
            inizio = max(0.0, float(m.group(1)))
        m = re.search(r"silence_end: ([\d.]+)", riga)
        if m and inizio is not None:
            out.append((inizio, float(m.group(1))))
            inizio = None
    return out


def tagli(durata: float, sil: list[tuple[float, float]]) -> list[float]:
    ""
    n = max(1, math.ceil(durata / PEZZO_MAX_S))
    out = []
    for k in range(1, n):
        ideale = k * durata / n
        vicini = [(b - a, (a + b) / 2) for a, b in sil if abs((a + b) / 2 - ideale) <= FINESTRA_S]
        out.append(round(max(vicini)[1], 2) if vicini else round(ideale, 2))
    return out


def pezzi(durata: float, cut: list[float]) -> list[dict]:
    ""
    bordi = [0.0, *cut, durata]
    out = []
    for k in range(len(bordi) - 1):
        a = max(0.0, bordi[k] - (SOVRAPPOSIZIONE_S if k else 0))
        out.append(
            {"k": k + 1, "n": len(bordi) - 1, "da_s": round(a, 2), "a_s": round(bordi[k + 1], 2)}
        )
    return out


def seriale(sn: str, start_ms: int) -> str:
    ""

    return f"{sn}-{int(start_ms)}"


def chiave(r: dict) -> str:
    return f"{r['orig_id']}:{r['k']}"


def nome_pezzo(titolo: str, k: int, n: int) -> str:
    return f"{titolo} · part {k} of {n}"


def leggi_registro(p: Path = REGISTRO) -> dict[str, dict]:
    ""
    out: dict[str, dict] = {}
    if p.exists():
        for riga in p.read_text().splitlines():
            try:
                r = json.loads(riga)
            except json.JSONDecodeError:
                continue
            out.setdefault(chiave(r), {}).update(r)
    return out


def scrivi_registro(riga: dict, p: Path = REGISTRO) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as f:
        f.write(
            json.dumps(
                {**riga, "quando": dt.datetime.now().isoformat(timespec="seconds")},
                ensure_ascii=False,
            )
            + "\n"
        )
        f.flush()
        os.fsync(f.fileno())





def _contesto() -> tuple[str, str, dict]:
    from tools.plaud.pl_auth_refresh import build_context, load_saved_wt, load_store_py
    from tools.plaud.pl_exec_http import make_request_id
    from tools.plaud.pl_trascrizioni import intestazioni_app

    wt = load_saved_wt()
    if not wt:
        sys.exit("no WT: uv run python tools/plaud/pl_auth_refresh.py --refresh")
    ctx = build_context(load_store_py())
    import plistlib

    with open("/Applications/Plaud.app/Contents/Info.plist", "rb") as fp:
        versione = plistlib.load(fp)["CFBundleShortVersionString"]
    return ctx["api_domain"], wt, intestazioni_app(versione, ctx["device_uuid"], make_request_id())


def _api(metodo: str, path: str, corpo: dict | None = None) -> dict:
    base, wt, app = _contesto()
    from tools.plaud.pl_exec_http import make_request_id

    h = {
        **app,
        "X-Request-Id": make_request_id(),
        "Authorization": f"Bearer {wt}",
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
    }
    data = None
    if corpo is not None:
        data = json.dumps(corpo, ensure_ascii=False).encode()
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(f"{base}{path}", data=data, headers=h, method=metodo)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            raw = r.read()
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code} on {metodo} {path}: {e.read()[:200]!r}") from e
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return json.loads(raw) if raw else {}


def _dati(r: dict) -> dict:
    if isinstance(r, dict) and r.get("status") not in (None, 0):
        raise RuntimeError(f"Plaud responds status {r.get('status')}: {str(r.get('msg'))[:160]}")
    return (r.get("data") if isinstance(r, dict) else None) or r


def scarica_audio(fid: str) -> Path:
    LAVORO.mkdir(parents=True, exist_ok=True)
    dest = LAVORO / f"{fid}.audio"
    if dest.exists() and dest.stat().st_size > 100_000:
        return dest
    url = _dati(_api("GET", f"/file/temp-url/{fid}")).get("temp_url")
    if not url:
        raise RuntimeError(f"temp-url missing for {fid[:8]}")
    subprocess.run(["curl", "-sS", "-f", "-o", str(dest), url], check=True, timeout=3600)
    return dest


def durata_decodificata(p: Path) -> float:
    ""
    r = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(p), "-f", "null", "-"],
        capture_output=True,
        text=True,
        timeout=3600,
    )
    t = re.findall(r"time=(\d+):(\d+):([\d.]+)", r.stderr)
    if not t:
        raise RuntimeError(f"ffmpeg cannot read {p.name}: {r.stderr[-200:]}")
    h, m, s = t[-1]
    return int(h) * 3600 + int(m) * 60 + float(s)


def trova_silenzi(p: Path) -> list[tuple[float, float]]:
    r = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-nostats",
            "-i",
            str(p),
            "-af",
            "silencedetect=noise=-35dB:d=1.5",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        timeout=3600,
    )
    return silenzi(r.stderr)


def codifica(p: Path, da_s: float, a_s: float, out: Path) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-ss",
            f"{da_s:.2f}",
            "-to",
            f"{a_s:.2f}",
            "-i",
            str(p),
            "-c:a",
            "libopus",
            "-ar",
            "16000",
            "-ac",
            "1",
            "-vbr",
            "on",
            "-compression_level",
            "10",
            str(out),
        ],
        check=True,
        timeout=3600,
    )


def carica_file(path: Path, *, filename: str, start_ms: int, scene: int, serial: str) -> str:
    ""
    size = path.stat().st_size
    if size > MAX_BYTES:
        raise RuntimeError(f"{path.name} is {size} bytes, over Plaud's 500 MB limit")
    pre = _dati(
        _api("POST", "/file/get_upload_presigned_url", {"filesize": size, "file_type": "OGG"})
    )
    parti = []
    with path.open("rb") as f:
        for i, url in enumerate(pre["part_urls"], 1):
            blocco = f.read(PARTE_BYTES)
            req = urllib.request.Request(url, data=blocco, method="PUT")
            with urllib.request.urlopen(req, timeout=600) as r:
                parti.append({"Etag": r.headers.get("ETag", "").strip('"'), "PartNumber": i})
    _dati(
        _api(
            "POST",
            "/file/merge_multipart",
            {"upload_id": pre["upload_id"], "object_name": pre["object_name"], "parts": parti},
        )
    )
    from tools.plaud.pl_trascrizioni import ore_utc

    conf = _dati(
        _api(
            "POST",
            "/file/confirm_upload",
            {
                "upload_id": pre["upload_id"],
                "object_name": pre["object_name"],
                "scene": scene,
                "is_tmp": 0,
                "support_mul_summ": True,
                "file_type": "OGG",
                "filename": filename,
                "start_time": start_ms,
                "session_id": start_ms // 1000,
                "serial_number": serial,
                "timezone": ore_utc(),
            },
        )
    )
    fid = conf.get("id") if isinstance(conf, dict) else None
    if not fid:
        raise RuntimeError(f"confirm_upload without id: {str(conf)[:200]}")
    return fid


def chiedi_trascrizione(fid: str) -> dict:
    from tools.plaud.pl_trascrizioni import corpo_richiesta, ore_utc

    return _api("POST", f"/ai/transsumm/{fid}", corpo_richiesta(ore_utc()))


def voci_del_pezzo(fid: str) -> tuple[int | None, int | None]:
    ""
    d = _dati(_api("GET", f"/file/detail/{fid}"))
    diar = None
    for c in d.get("content_list") or []:
        if c.get("data_type") == "transaction" and c.get("data_link"):
            try:
                diar = json.loads((d.get("extra_data") or {}).get("tranConfig") or "{}").get(
                    "diarization"
                )
            except (TypeError, ValueError):
                diar = ((d.get("extra_data") or {}).get("tranConfig") or {}).get("diarization")
            raw = urllib.request.urlopen(c["data_link"], timeout=300).read()
            if raw[:2] == b"\x1f\x8b":
                raw = gzip.decompress(raw)
            segs = json.loads(raw)
            return diar, len({s.get("speaker") for s in segs if isinstance(s, dict)})
    return None, None





def _indice() -> dict[str, dict]:
    return {x["id"]: x for x in json.loads(INDICE.read_text())}


def _dettaglio(fid: str) -> dict:
    p = DETTAGLI / f"{fid}.json"
    return json.loads(p.read_text()) if p.exists() else {}


def _trova(fid: str) -> dict:
    idx = _indice()
    m = [v for k, v in idx.items() if k.startswith(fid)]
    if len(m) != 1:
        sys.exit(f"{fid}: {len(m)} recordings in the index")
    return m[0]


def elenco() -> list[dict]:
    q = json.loads((PLAUD / "quadro" / "quadro.json").read_text())
    out = [
        r
        for r in q["registrazioni"]
        if (r["durata_min"] or 0) >= SOGLIA_ORE * 60 and r["una_voce_sola"]
    ]
    for r in sorted(out, key=lambda r: r["data"]):
        print(r["data"], r["id"][:8], round(r["durata_min"]), (r["titolo"] or "")[:60])
    print(len(out), "recordings,", round(sum(r["durata_min"] for r in out) / 60, 1), "hours")
    return out


def piano(fid: str) -> dict:
    x = _trova(fid)
    audio = scarica_audio(x["id"])
    vera = durata_decodificata(audio)
    if abs(vera - x["duration_sec"]) > 5:
        raise SystemExit(
            f"partial audio: {vera:.0f} s against {x['duration_sec']:.0f} s from the index, stopping"
        )
    cut = tagli(vera, trova_silenzi(audio))
    pz = pezzi(vera, cut)
    sn = _dettaglio(x["id"]).get("serial_number") or "SBK"
    for p in pz:
        p["filename"] = nome_pezzo(x["filename"], p["k"], p["n"])
        p["start_ms"] = int(x["st"] + p["da_s"] * 1000)
        p["serial"] = seriale(sn, p["start_ms"])
    print(
        json.dumps(
            {"id": x["id"], "durata_s": vera, "tagli_s": cut, "pezzi": pz},
            ensure_ascii=False,
            indent=1,
        )
    )
    return {"x": x, "audio": audio, "pezzi": pz}


def carica(fid: str) -> None:
    pl = piano(fid)
    x, audio = pl["x"], pl["audio"]
    prima = _dati(_api("GET", f"/file/detail/{x['id']}")).get("edit_time")
    reg = leggi_registro()
    for p in pl["pezzi"]:
        stato = reg.get(f"{x['id']}:{p['k']}", {})
        if stato.get("file_id"):
            print(f"part {p['k']}: already uploaded, {stato['file_id']}")
            continue
        if stato.get("stato") == "intento":
            sys.exit(
                f"part {p['k']}: there is an interrupted upload ({p['serial']}), check by hand before retrying"
            )
        out = LAVORO / f"{x['id']}-{p['k']}.ogg"
        codifica(audio, p["da_s"], p["a_s"], out)
        sha = hashlib.sha256(out.read_bytes()).hexdigest()
        base = {
            "orig_id": x["id"],
            "serial": p["serial"],
            "k": p["k"],
            "n": p["n"],
            "da_s": p["da_s"],
            "a_s": p["a_s"],
            "sovrapposizione_s": SOVRAPPOSIZIONE_S if p["k"] > 1 else 0,
            "start_ms": p["start_ms"],
            "filename": p["filename"],
            "sha256": sha,
            "bytes": out.stat().st_size,
        }
        scrivi_registro({**base, "stato": "intento"})
        nuovo = carica_file(
            out,
            filename=p["filename"],
            start_ms=p["start_ms"],
            scene=x.get("scene") or 1,
            serial=p["serial"],
        )
        scrivi_registro({**base, "stato": "caricato", "file_id": nuovo})
        r = chiedi_trascrizione(nuovo)
        scrivi_registro(
            {**base, "stato": "trascrizione_chiesta", "file_id": nuovo, "risposta": str(r)[:200]}
        )
        print(f"part {p['k']} of {p['n']}: {nuovo}, transcription requested")
        out.unlink()
    dopo = _dati(_api("GET", f"/file/detail/{x['id']}")).get("edit_time")
    print("original", "identical" if prima == dopo else f"CHANGED {prima} -> {dopo}")


def controlla(fid: str) -> None:
    x = _trova(fid)
    pz = [r for r in leggi_registro().values() if r.get("orig_id") == x["id"] and r.get("file_id")]
    for r in sorted(pz, key=lambda r: r["k"]):
        if r.get("voci"):
            print(f"part {r['k']}: {r['voci']} voices, diarization {r.get('diarization')}")
            continue
        try:
            chiedi_trascrizione(r["file_id"])
        except RuntimeError as e:
            print(f"part {r['k']}: {e}")
        diar, n = voci_del_pezzo(r["file_id"])
        if n is None:
            print(f"part {r['k']}: transcription in progress")
            continue
        scrivi_registro(
            {k: r[k] for k in ("orig_id", "serial", "k", "n", "file_id")}
            | {"stato": "trascritto", "diarization": diar, "voci": n}
        )
        print(f"part {r['k']}: {n} voices, diarization {diar}")



# Recordings already cut live as stato "tagliata" in the registry (registro.jsonl);
# none are hardcoded here.
GIA_TAGLIATE: frozenset[str] = frozenset()



MARGINE_ORE = 10


def minuti_disponibili() -> float:
    d = _dati(_api("GET", "/ai/trans-status"))
    return float(d.get("remain_total") or 0) / 60 - MARGINE_ORE * 60


def caricati_oggi(reg: dict[str, dict] | None = None) -> float:
    oggi = dt.date.today().isoformat()
    return sum(
        (r["a_s"] - r["da_s"]) / 60
        for r in (reg or leggi_registro()).values()
        if r.get("file_id") and str(r.get("quando", "")).startswith(oggi) and "a_s" in r
    )


def tutte(minuti_max: float | None = None) -> None:
    ""

    budget = minuti_disponibili() if minuti_max is None else minuti_max
    usati = 0.0
    reg = leggi_registro()
    fatte = {r["orig_id"] for r in reg.values() if r.get("file_id")}
    tagliate = {
        r["orig_id"][:8]
        for r in reg.values()
        if r.get("stato") == "tagliata" and r.get("orig_id")
    }
    for r in elenco():
        if r["id"][:8] in GIA_TAGLIATE or r["id"][:8] in tagliate or r["id"] in fatte:
            continue
        if usati + r["durata_min"] + 2 > budget:
            print(
                f"Plaud has no room beyond the {MARGINE_ORE} hour margin: resumes when it frees up, from {r['id'][:8]}"
            )
            break
        print(f"== {r['id'][:8]} {round(r['durata_min'])} min")
        try:
            carica(r["id"])
            usati += r["durata_min"] + 2
        except (RuntimeError, SystemExit, subprocess.CalledProcessError) as e:
            print(f"   stopped on {r['id'][:8]}: {e}")
            continue
        finally:
            a = LAVORO / f"{r['id']}.audio"
            if a.exists():
                a.unlink()


def main() -> int:
    ap = argparse.ArgumentParser(
        description=((__doc__ or "").strip().splitlines() or ["Plaud long recordings"])[0]
    )
    # English commands; the older Italian names are accepted too (hidden aliases).
    comandi = {
        "list": "elenco",
        "plan": "piano",
        "upload": "carica",
        "check": "controlla",
        "all": "tutte",
    }

    def comando(s: str) -> str:
        if s in comandi.values():
            return s
        if s in comandi:
            return comandi[s]
        raise argparse.ArgumentTypeError(f"{s!r}: choose from list, plan, upload, check, all")

    ap.add_argument(
        "comando",
        metavar="{list,plan,upload,check,all}",
        type=comando,
        help="list: long recordings · plan/upload/check: one recording (id) · all: upload every one",
    )
    ap.add_argument(
        "--minutes",
        dest="minuti",
        metavar="MINUTES",
        type=float,
        default=None,
        help="with all: manual cap in minutes; without it, what is left on Plaud minus the margin",
    )
    ap.add_argument("id", nargs="?")
    ap.add_argument(
        "--wait",
        dest="aspetta",
        action="store_true",
        help="with check: repeats until the pieces are transcribed",
    )
    # Older Italian names, kept as hidden aliases.
    ap.add_argument("--minuti", dest="minuti", type=float, help=argparse.SUPPRESS)
    ap.add_argument("--aspetta", dest="aspetta", action="store_true", help=argparse.SUPPRESS)
    a = ap.parse_args()
    if a.comando == "elenco":
        elenco()
    elif a.comando == "tutte":
        tutte(a.minuti)
    elif not a.id:
        ap.error("the recording id is required")
    elif a.comando == "piano":
        piano(a.id)
    elif a.comando == "carica":
        carica(a.id)
    else:
        fine = time.time() + (ATTESA_TRASCRIZIONE_S if a.aspetta else 0)
        while True:
            controlla(a.id)
            x = _trova(a.id)
            fatti = [
                r
                for r in leggi_registro().values()
                if r.get("orig_id") == x["id"] and r.get("file_id")
            ]
            if all(r.get("voci") for r in fatti) or time.time() > fine:
                break
            time.sleep(PASSO_S)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
