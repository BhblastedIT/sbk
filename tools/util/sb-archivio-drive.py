#!/usr/bin/env python3
"""Archives large files of your data root into a private folder of your own Google Drive, and frees the local copy once verified."""






















from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import io
import json
import os
import sys
from pathlib import Path

DATA_ROOT = Path(os.environ.get("SBK_DATA_ROOT", str(Path.home() / ".sbk-data")))
REGISTRO = DATA_ROOT / "archivio-drive" / "registro.json"
# Your own Google login, saved once with `sb-archivio-drive.py login` in the
# Keychain (service "sbk-gdrive-archive", account "default"). The scope is
# drive.file: the archive sees only the files it uploaded itself. The OAuth
# "Desktop app" client is the one of tools/google_oauth.py.
KEYCHAIN_SERVICE = "sbk-gdrive-archive"
SCOPES = ["https://www.googleapis.com/auth/drive.file"]
RADICE = "SBK · Archive"
CARTELLA = "application/vnd.google-apps.folder"


def leggi_registro() -> dict:
    return json.loads(REGISTRO.read_text()) if REGISTRO.exists() else {}


def scrivi_registro(reg: dict) -> None:
    REGISTRO.parent.mkdir(parents=True, exist_ok=True)
    tmp = REGISTRO.with_suffix(".tmp")
    tmp.write_text(json.dumps(dict(sorted(reg.items())), ensure_ascii=False, indent=1))
    tmp.replace(REGISTRO)


def archiviati_per_backup() -> dict[str, int]:
    ""
    try:
        return {k: int(v["byte"]) for k, v in leggi_registro().items()}
    except Exception:
        return {}


def md5(p: Path) -> str:
    h = hashlib.md5()
    with p.open("rb") as f:
        for blocco in iter(lambda: f.read(8 << 20), b""):
            h.update(blocco)
    return h.hexdigest()


def _google_oauth():
    tools = Path(__file__).resolve().parents[1]
    if str(tools) not in sys.path:
        sys.path.insert(0, str(tools))
    import google_oauth

    return google_oauth


def login(args) -> None:
    _google_oauth().browser_login(KEYCHAIN_SERVICE, "default", SCOPES)


def drive():
    from googleapiclient.discovery import build

    c = _google_oauth().stored_credentials(KEYCHAIN_SERVICE, "default")
    if c is None:
        sys.exit("No Drive login for the archive. Run: python3 tools/util/sb-archivio-drive.py login")
    return build("drive", "v3", credentials=c, cache_discovery=False)


def _q(s: str) -> str:
    return s.replace("\\", "\\\\").replace("'", "\\'")


def cartella(d, nome: str, padre: str | None, cache: dict) -> str:
    chiave = (padre, nome)
    if chiave in cache:
        return cache[chiave]
    q = f"name = '{_q(nome)}' and mimeType = '{CARTELLA}' and trashed = false" + (
        f" and '{padre}' in parents" if padre else " and 'root' in parents"
    )
    trovate = d.files().list(q=q, fields="files(id)").execute()["files"]
    fid = (
        trovate[0]["id"]
        if trovate
        else d.files()
        .create(
            body={"name": nome, "mimeType": CARTELLA, "parents": [padre] if padre else []},
            fields="id",
        )
        .execute()["id"]
    )
    cache[chiave] = fid
    return fid


def relativo(p: Path) -> str:
    p = p.expanduser().resolve()
    try:
        return str(p.relative_to(DATA_ROOT.resolve()))
    except ValueError:
        sys.exit(f"outside {DATA_ROOT}: {p}")


def file_sotto(percorsi: list[str], min_byte: int = 0) -> list[Path]:
    out = []
    for s in percorsi:
        p = Path(s).expanduser()
        if p.is_file():
            out.append(p)
        elif p.is_dir():
            out += sorted(
                f
                for f in p.rglob("*")
                if f.is_file()
                and not f.is_symlink()
                and f.stat().st_size >= min_byte
                and f.name != ".DS_Store"
            )
        else:
            sys.exit(f"doesn't exist: {p}")
    return out


def carica(args) -> None:
    from googleapiclient.http import MediaFileUpload

    d, reg, cache = drive(), leggi_registro(), {}
    radice = cartella(d, RADICE, None, cache)
    files = file_sotto(args.percorsi, int(args.min_mb * 1e6))
    print(f"{len(files)} files, {sum(f.stat().st_size for f in files) / 1e9:.2f} GB")
    for f in files:
        rel, peso = relativo(f), f.stat().st_size
        locale = md5(f)
        if rel in reg and reg[rel]["md5"] == locale:
            print(f"  already archived  {rel}")
            continue
        padre = radice
        for parte in Path(rel).parent.parts:
            padre = cartella(d, parte, padre, cache)
        media = MediaFileUpload(str(f), resumable=True, chunksize=64 << 20)
        meta = (
            d.files()
            .create(
                body={"name": f.name, "parents": [padre]},
                media_body=media,
                fields="id,md5Checksum,size,webViewLink",
            )
            .execute()
        )
        if meta.get("md5Checksum") != locale or int(meta.get("size", -1)) != peso:
            print(f"  ✗ md5 differs, NOT registered: {rel}")
            continue
        reg[rel] = {
            "md5": locale,
            "byte": peso,
            "drive_id": meta["id"],
            "link": meta["webViewLink"],
            "caricato": dt.datetime.now().isoformat(timespec="seconds"),
        }
        scrivi_registro(reg)
        print(f"  ✓ {peso / 1e6:8.1f} MB  {rel}")


def selezione(reg: dict, percorsi: list[str]) -> dict:
    if not percorsi:
        return reg
    pref = [relativo(Path(p)) for p in percorsi]
    return {
        k: v
        for k, v in reg.items()
        if any(k == x or k.startswith(x.rstrip("/") + "/") for x in pref)
    }


def stato(args) -> None:
    sel = selezione(leggi_registro(), args.percorsi)
    presenti = [k for k in sel if (DATA_ROOT / k).exists()]
    print(
        f"archived {len(sel)} files, {sum(v['byte'] for v in sel.values()) / 1e9:.2f} GB · still also local {len(presenti)} "
        f"({sum(sel[k]['byte'] for k in presenti) / 1e9:.2f} GB)"
    )


def verifica(args, stampa: bool = True) -> list[str]:
    d, sel, buoni = drive(), selezione(leggi_registro(), args.percorsi), []
    for rel, v in sel.items():
        m = d.files().get(fileId=v["drive_id"], fields="md5Checksum,trashed").execute()
        ok_drive = m.get("md5Checksum") == v["md5"] and not m.get("trashed")
        p = DATA_ROOT / rel
        ok_locale = (not p.exists()) or md5(p) == v["md5"]
        if ok_drive and ok_locale:
            buoni.append(rel)
        elif stampa:
            print(f"  ✗ {'Drive' if not ok_drive else 'local changed'}  {rel}")
    if stampa:
        print(f"verified {len(buoni)} of {len(sel)}")
    return buoni


def libera(args) -> None:
    buoni = [r for r in verifica(args, stampa=True) if (DATA_ROOT / r).exists()]
    peso = sum((DATA_ROOT / r).stat().st_size for r in buoni)
    if not args.si:
        print(
            f"I would remove {len(buoni)} local copies, {peso / 1e9:.2f} GB. Rerun with --si to do it."
        )
        return
    for r in buoni:
        (DATA_ROOT / r).unlink()
    print(
        f"removed {len(buoni)} local copies, {peso / 1e9:.2f} GB freed. Restore them with `riprendi`."
    )


def riprendi(args) -> None:
    from googleapiclient.http import MediaIoBaseDownload

    d = drive()
    for rel, v in selezione(leggi_registro(), args.percorsi).items():
        p = DATA_ROOT / rel
        if p.exists() and md5(p) == v["md5"]:
            continue
        p.parent.mkdir(parents=True, exist_ok=True)
        with io.FileIO(str(p), "wb") as fh:
            dl = MediaIoBaseDownload(
                fh, d.files().get_media(fileId=v["drive_id"]), chunksize=64 << 20
            )
            fatto = False
            while not fatto:
                _, fatto = dl.next_chunk()
        print(("  ✓ " if md5(p) == v["md5"] else "  ✗ md5 differs ") + rel)


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("login", help="saves your Google login for the archive (browser, once)")
    for nome in ("carica", "stato", "verifica", "libera", "riprendi"):
        s = sub.add_parser(nome)
        s.add_argument("percorsi", nargs="*" if nome in ("stato", "verifica") else "+")
        if nome == "carica":
            s.add_argument("--min-mb", type=float, default=0)
        if nome == "libera":
            s.add_argument("--si", action="store_true")
    a = ap.parse_args()
    {
        "carica": carica,
        "stato": stato,
        "verifica": verifica,
        "libera": libera,
        "riprendi": riprendi,
        "login": login,
    }[a.cmd](a)


if __name__ == "__main__":
    main()
