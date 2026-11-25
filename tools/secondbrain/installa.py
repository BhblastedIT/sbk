#!/usr/bin/env python3
"""Build the SBK macOS app (Swift), sign and package it and install it in /Applications; it can also update it in place or roll back to an archived version."""




























from __future__ import annotations

import argparse
import json
import os
import plistlib
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

QUI = Path(__file__).resolve().parent
ROOT = QUI.parents[1]
PACCHETTO = QUI / "app"
sys.path.insert(0, str(QUI))
import sb_versioni  # noqa: E402
from sb_impronta import contenuto_app  # noqa: E402

BUNDLE_ID = "local.sbk.secondbrain"
NOME = "SBK"
VERSIONE = "0.3"
DESTINAZIONE = Path("/Applications") / f"{NOME}.app"


ARCHIVIO = Path.home() / "Library/Application Support/local.sbk.secondbrain/versioni"
RETENTION = 3

TEAM = "XXXXXXXXXX"
XCODE = "/Applications/Xcode.app/Contents/Developer"

SEGNO_AGGIORNAMENTO = Path.home() / "Library" / "Caches" / BUNDLE_ID / "aggiornamento-in-corso"


def _corri(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def compila() -> Path:
    binario = PACCHETTO / ".build" / "release" / NOME
    sorgenti = [*PACCHETTO.glob("Sources/**/*.swift"), PACCHETTO / "Package.swift"]
    for tentativo in (1, 2):
        r = _corri(["swift", "build", "-c", "release"], cwd=PACCHETTO, timeout=1800)
        if r.returncode != 0:
            print(r.stdout[-3000:], r.stderr[-3000:])
            sys.exit("⛔ build failed")
        piu_nuovo = max(sorgenti, key=lambda p: p.stat().st_mtime)
        if piu_nuovo.stat().st_mtime <= binario.stat().st_mtime:
            return binario



        if tentativo == 1:
            binario.unlink(missing_ok=True)
    sys.exit(
        f"⛔ {piu_nuovo.name} is newer than the binary: the build does not contain the new code"
    )


def _commit_app() -> str:
    ""

    commit = _corri(
        ["git", "log", "-1", "--format=%h", "--", "tools/secondbrain/app"], cwd=ROOT, timeout=30
    ).stdout.strip()
    sporco = _corri(
        ["git", "status", "--porcelain", "--", "tools/secondbrain/app"], cwd=ROOT, timeout=30
    ).stdout.strip()
    return commit + ("+" if sporco else "")


def _identita_stabile() -> tuple[str, str] | None:
    ""

    r = _corri(["security", "find-identity", "-v", "-p", "codesigning"], timeout=30)
    for riga in r.stdout.splitlines():
        m = re.search(r'\)\s+([0-9A-F]{40})\s+"(Apple Development: [^"]+)"', riga)
        if not m:
            continue
        impronta, nome = m.groups()
        pem = _corri(["security", "find-certificate", "-c", nome, "-p"], timeout=30).stdout
        soggetto = _corri(["openssl", "x509", "-noout", "-subject"], input=pem, timeout=30).stdout
        if f"OU={TEAM}" in soggetto.replace(" ", ""):
            return impronta, nome
    return None


def firma(bundle: Path) -> str:
    ""
    identita = _identita_stabile()
    if identita:
        impronta, nome = identita
        try:
            r = _corri(
                ["codesign", "--force", "--sign", impronta, "--timestamp=none", str(bundle)],
                timeout=90,
            )
            if r.returncode == 0:
                return f"stable signature ({nome}, team {TEAM})"
            motivo = r.stderr.strip()[-300:]
        except subprocess.TimeoutExpired:
            motivo = "codesign did not respond in 90 s (maybe waiting for the Keychain)"
        print(f"⚠️ stable signature failed, using the ad-hoc signature: {motivo}")
    else:
        print(f"⚠️ no Apple Development identity for team {TEAM}: using the ad-hoc signature")
    r = _corri(["codesign", "--force", "--sign", "-", str(bundle)], timeout=90)
    if r.returncode != 0:
        sys.exit(f"⛔ signature failed: {r.stderr}")
    return "ad-hoc signature (the Mac permissions are lost on every build)"


def impacchetta(binario: Path, versione: str | None = None) -> tuple[Path, str]:
    bundle = PACCHETTO / ".build" / f"{NOME}.app"
    if bundle.exists():
        shutil.rmtree(bundle)
    (bundle / "Contents" / "MacOS").mkdir(parents=True)
    (bundle / "Contents" / "Resources").mkdir()
    shutil.copy2(binario, bundle / "Contents" / "MacOS" / NOME)
    info = {
        "CFBundleName": NOME,
        "CFBundleDisplayName": NOME,
        "CFBundleIdentifier": BUNDLE_ID,
        "CFBundleExecutable": NOME,
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": versione or sb_versioni.corrente(),
        "CFBundleVersion": time.strftime("%Y%m%d%H%M"),

        "LSMinimumSystemVersion": "26.0",

        "CFBundleDevelopmentRegion": "it",
        "CFBundleLocalizations": ["it"],
        "NSHighResolutionCapable": True,
        "NSPrincipalClass": "NSApplication",
        "LSApplicationCategoryType": "public.app-category.productivity",
        "SBCommitApp": _commit_app(),
        # The clone this app is built from: the app runs its engine when no folder was chosen yet.
        "SBRadice": str(ROOT),

        "SBContenutoApp": contenuto_app(PACCHETTO),

        "NSDownloadsFolderUsageDescription": "SBK launches pipeline runs, which read the exports you "
        "download, for example WhatsApp chats.",
        "NSDocumentsFolderUsageDescription": "SBK launches pipeline runs, which read the documents "
        "of the sources you bring.",
        "NSDesktopFolderUsageDescription": "SBK launches pipeline runs, which can read the files "
        "you place on the desktop.",

        "NSMicrophoneUsageDescription": "SBK records your voice replies to Inspiration items. "
        "It transcribes them on the Mac, nothing leaves home.",
    }
    icona_doc = PACCHETTO / f"{NOME}.icon"
    if icona_doc.exists():

        parziale = PACCHETTO / ".build" / "icona-partial.plist"
        r = _corri(
            [
                "xcrun",
                "actool",
                str(icona_doc),
                "--compile",
                str(bundle / "Contents" / "Resources"),
                "--platform",
                "macosx",
                "--minimum-deployment-target",
                info["LSMinimumSystemVersion"],
                "--app-icon",
                NOME,
                "--output-partial-info-plist",
                str(parziale),
                "--output-format",
                "human-readable-text",
                "--notices",
                "--warnings",
                "--errors",
            ],
            timeout=300,
            env=dict(os.environ, DEVELOPER_DIR=XCODE),
        )
        if r.returncode != 0 or not parziale.exists():
            sys.exit(f"⛔ actool did not compile the icon: {r.stdout[-2000:]} {r.stderr[-2000:]}")
        info.update(plistlib.loads(parziale.read_bytes()))
    with (bundle / "Contents" / "Info.plist").open("wb") as f:
        plistlib.dump(info, f)
    come = firma(bundle)
    r = _corri(["codesign", "--verify", "--strict", str(bundle)])
    if r.returncode != 0:
        sys.exit(f"⛔ the signature does not verify: {r.stderr}")
    return bundle, come


def _aperta() -> bool:

    return _corri(["pgrep", "-x", NOME]).returncode == 0


def chiudi(forza_chiusura: bool) -> bool:
    if not _aperta():
        return False
    if not forza_chiusura:
        sys.exit(
            "⛔ SBK is open and I will not close it. Close it yourself (⌘Q) and relaunch, "
            "or relaunch with --chiudi."
        )
    _corri(["osascript", "-e", f'tell application id "{BUNDLE_ID}" to quit'])
    for _ in range(40):
        if not _aperta():
            return True
        time.sleep(0.5)
    sys.exit(
        "⛔ SBK does not close (maybe it is asking what to do with a live run): answer and relaunch"
    )


def _pid_app() -> list[int]:
    ""
    r = _corri(["pgrep", "-x", NOME])
    pid = []
    for riga in r.stdout.split():
        comm = _corri(["ps", "-o", "comm=", "-p", riga]).stdout.strip()
        if comm == str(DESTINAZIONE / "Contents" / "MacOS" / NOME):
            pid.append(int(riga))
    return pid


def _in_sottofondo() -> dict[int, str]:
    ""


    r = _corri([sys.executable, str(QUI / "sb-app.py"), "stato"], cwd=ROOT, timeout=120)
    try:
        stato = json.loads(r.stdout)
    except ValueError:
        return {}
    vivi: dict[int, str] = {}
    marcati = [
        r
        for r in [stato.get("run_app") or {}, *(stato.get("scarichi_soli") or [])]
        if r.get("run_id")
    ]
    marcati = [r for r in marcati if r.get("vivo", True)]
    if marcati:
        import importlib.util

        spec = importlib.util.spec_from_file_location("sb_run_aggiorna", QUI / "sb-run.py")
        custode = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(custode)
        tabella = custode._tabella()
        for run in marcati:
            marca = f"SBK_RUN_ID={run['run_id']}".encode()
            for pid in tabella:
                if custode.marcato(pid, marca):
                    vivi[pid] = f"run dell'app {run.get('nome') or run['run_id']}"
    for pr in (stato.get("da_fuori") or {}).get("processi", []):
        vivi[int(pr["pid"])] = pr.get("script", "pipeline")
    return vivi


def _vivo(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def aggiorna(bundle: Path) -> int:
    ""
    prima = _in_sottofondo()
    print(
        f"in background before: {len(prima)} ({', '.join(f'{p} {n}' for p, n in prima.items()) or 'nothing'})"
    )
    aperta = _pid_app()
    SEGNO_AGGIORNAMENTO.parent.mkdir(parents=True, exist_ok=True)
    SEGNO_AGGIORNAMENTO.write_text(time.strftime("%Y-%m-%dT%H:%M:%S"))
    try:
        if aperta:
            try:
                _corri(
                    ["osascript", "-e", f'tell application id "{BUNDLE_ID}" to quit'], timeout=30
                )
            except subprocess.TimeoutExpired:


                print(
                    "⚠️ the app did not respond to the close request within 30 s, waiting more"
                )
            for _ in range(120):
                if not _pid_app():
                    break
                time.sleep(0.5)
            for pid in _pid_app():

                print(f"⚠️ the app did not close in 60 s, killing process {pid}")
                os.kill(pid, 15)
                time.sleep(5)
                if _vivo(pid):
                    os.kill(pid, 9)
        installa(bundle)
        print(f"✅ installed in {DESTINAZIONE}")
    finally:
        SEGNO_AGGIORNAMENTO.unlink(missing_ok=True)

    _corri(["open", str(DESTINAZIONE)])
    for _ in range(40):
        if _pid_app():
            break
        time.sleep(0.5)
    persi = {p: n for p, n in prima.items() if not _vivo(p)}

    print(f"✅ reopened: {'yes' if _pid_app() else 'NO'}")
    print(
        f"in background after: {len(prima) - len(persi)} of {len(prima)}"
        + (f", no longer alive: {', '.join(f'{p} {n}' for p, n in persi.items())}" if persi else "")
    )
    return 0 if _pid_app() else 1


def _archivia(vecchia: Path) -> None:
    ""



    try:
        with open(vecchia / "Contents" / "Info.plist", "rb") as fh:
            info = plistlib.load(fh)
        ver = str(info.get("CFBundleShortVersionString") or "0")
        build = str(info.get("CFBundleVersion") or "")
        nome = f"{ver}+{build}" if build else ver
        dest = ARCHIVIO / nome / f"{NOME}.app"
        if dest.parent.exists():
            shutil.rmtree(dest.parent)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(vecchia), str(dest))
        tenute = sorted(
            (p for p in ARCHIVIO.iterdir() if p.is_dir()),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for troppo_vecchia in tenute[RETENTION:]:
            shutil.rmtree(troppo_vecchia, ignore_errors=True)
    except Exception:
        shutil.rmtree(vecchia, ignore_errors=True)


def installa(bundle: Path) -> None:
    vecchia = DESTINAZIONE.with_name(f"{NOME}-precedente.app")
    if vecchia.exists():
        shutil.rmtree(vecchia)
    if DESTINAZIONE.exists():
        DESTINAZIONE.rename(vecchia)
    try:
        shutil.copytree(bundle, DESTINAZIONE, symlinks=True)
        r = _corri(["codesign", "--verify", "--strict", str(DESTINAZIONE)])
        if r.returncode != 0:
            raise RuntimeError(r.stderr)
    except Exception as e:  # noqa: BLE001
        if DESTINAZIONE.exists():
            shutil.rmtree(DESTINAZIONE)
        if vecchia.exists():
            vecchia.rename(DESTINAZIONE)
        sys.exit(f"⛔ installazione fallita, rimessa la versione di prima: {e}")
    if vecchia.exists():
        _archivia(vecchia)

    os.utime(DESTINAZIONE)
    _ricorda_radice()


def _ricorda_radice() -> None:
    """Record this clone as the app's repo folder (its "radice" setting), so the app runs the engine it was built with."""
    try:
        r = _corri(["defaults", "write", BUNDLE_ID, "radice", "-string", str(ROOT)], timeout=30)
    except (OSError, subprocess.TimeoutExpired) as e:
        print(f"⚠️ could not record the repo folder in the app settings ({e}): choose it in the app")
        return
    if r.returncode == 0:
        print(f"✅ app settings: repo folder {ROOT}")
    else:
        print(f"⚠️ could not record the repo folder in the app settings ({r.stderr.strip()}): choose it in the app")


def _bundle_archiviato(versione: str) -> Path | None:
    ""
    if not ARCHIVIO.exists():
        return None
    cand = []
    for d in ARCHIVIO.iterdir():
        if not d.is_dir():
            continue
        if d.name.split("+", 1)[0] == versione or d.name == versione:
            app = d / f"{NOME}.app"
            if app.exists():
                cand.append((d.stat().st_mtime, app))
    return max(cand)[1] if cand else None


def torna_a(versione: str) -> int:
    ""



    app = _bundle_archiviato(versione)
    if not app:
        disp = (
            ", ".join(sorted(d.name for d in ARCHIVIO.iterdir() if d.is_dir()))
            if ARCHIVIO.exists()
            else "none"
        )
        sys.exit(
            f"⛔ version {versione} not in the archive (available: {disp}). The fallback is to recompile "
            "from that entry's commit in a detached worktree, the user decides."
        )
    print(f"↩️  reverting to {versione}: {app}")
    return aggiorna(app)


def _registra(rilascio: dict | None, firma: str) -> None:
    ""


    if not rilascio:
        return
    try:
        sb_versioni.aggiungi_rilascio(
            versione=rilascio["prossima"],
            commit=rilascio["commit"],
            contenuto=contenuto_app(PACCHETTO),
            firma=firma,
            canale="swift",
            novita=rilascio["novita"],
        )
        print(f"✅ version {rilascio['prossima']} recorded in versioni.json")
    except Exception as e:  # noqa: BLE001
        print(f"⚠️ version not recorded in the manifest: {e}")


def main() -> int:
    ap = argparse.ArgumentParser(
        description=((__doc__ or "").strip().splitlines() or ["Build and install the SBK macOS app"])[0]
    )
    ap.add_argument("--solo-build", action="store_true")
    ap.add_argument(
        "--chiudi",
        action="store_true",
        help="closes SBK if it is open (only if requested)",
    )
    ap.add_argument("--apri", action="store_true")
    ap.add_argument(
        "--aggiorna",
        action="store_true",
        help="like the terminal: closes the app without questions, replaces it, reopens it; background runs continue",
    )
    ap.add_argument(
        "--torna-a",
        metavar="VERSION",
        help="rollback: reinstalls an archived version, without recompiling",
    )
    args = ap.parse_args()

    if args.torna_a:
        return torna_a(args.torna_a)



    rilascio = None if args.solo_build else sb_versioni.proponi_bump()
    versione = rilascio["prossima"] if rilascio else None
    binario = compila()
    bundle, come = impacchetta(binario, versione)
    print(f"✅ bundle {bundle}" + (f" {versione}" if versione else "") + f", {come}")
    if args.solo_build:
        return 0
    if args.aggiorna:
        esito = aggiorna(bundle)
        if esito == 0:
            _registra(rilascio, come)
        return esito
    era_aperta = chiudi(args.chiudi)
    installa(bundle)
    print(f"✅ installed in {DESTINAZIONE}")
    _registra(rilascio, come)
    if args.apri or era_aperta:

        _corri(["open", str(DESTINAZIONE)])
        print("✅ opened")
    return 0


if __name__ == "__main__":
    sys.exit(main())
