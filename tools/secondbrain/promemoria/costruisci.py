#!/usr/bin/env python3
"""Builds and switches on "SBK Promemoria", the helper that mirrors the SecondBrain tasks into Apple Reminders.

Usage:
    python3 -I tools/secondbrain/promemoria/costruisci.py build     # compile and sign ~/Applications/SBK Promemoria.app
    python3 -I tools/secondbrain/promemoria/costruisci.py permesso  # open it once, so macOS asks you for Reminders access
    python3 -I tools/secondbrain/promemoria/costruisci.py agente    # write and load the com.sbk.promemoria LaunchAgent
    python3 -I tools/secondbrain/promemoria/costruisci.py stato     # is the agent loaded? last lines of its log
    python3 -I tools/secondbrain/promemoria/costruisci.py spegni    # unload the agent (the plist stays, renamed .spento)

build needs Xcode's command line tools and a "Developer ID Application" signing identity in your keychain. The
agent runs every two minutes at low priority and does something only when the engine and the list differ.
"""





import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

QUI = Path(__file__).resolve().parent
HOME = Path.home()
APP = HOME / "Applications" / "SBK Promemoria.app"
ESEGUIBILE = APP / "Contents" / "MacOS" / "sb-promemoria"
COLLEGAMENTO = HOME / ".local" / "bin" / "sb-promemoria"
ETICHETTA = "com.sbk.promemoria"
PLIST = HOME / "Library" / "LaunchAgents" / f"{ETICHETTA}.plist"
REGISTRO = (
    Path(os.environ.get("SBK_DATA_ROOT") or HOME / ".sbk-data").expanduser()
    / "logs"
    / "promemoria.log"
)
INTERVALLO = 120


def _identita() -> str:
    out = subprocess.run(
        ["security", "find-identity", "-v", "-p", "codesigning"], capture_output=True, text=True
    ).stdout
    for riga in out.splitlines():
        if "Developer ID Application" in riga and '"' in riga:
            return riga.split('"')[1]
    sys.exit("no «Developer ID Application» identity in the Keychain")


def build() -> None:
    ESEGUIBILE.parent.mkdir(parents=True, exist_ok=True)
    nuovo = ESEGUIBILE.with_name(ESEGUIBILE.name + ".nuovo")



    env = {k: v for k, v in os.environ.items() if k not in ("SDKROOT", "DEVELOPER_DIR")}
    sdk = subprocess.run(
        ["xcrun", "--sdk", "macosx", "--show-sdk-path"],
        capture_output=True,
        text=True,
        env=env,
        check=True,
    ).stdout.strip()
    subprocess.run(
        [
            "xcrun",
            "swiftc",
            "-sdk",
            sdk,


            "-target",
            "arm64-apple-macos14.0",
            "-O",

            "-module-name",
            "SBPromemoria",
            str(QUI / "SBPromemoria.swift"),
            "-o",
            str(nuovo),
            "-framework",
            "EventKit",
            "-Xlinker",
            "-sectcreate",
            "-Xlinker",
            "__TEXT",
            "-Xlinker",
            "__info_plist",
            "-Xlinker",
            str(QUI / "Info.plist"),
        ],
        check=True,
        env=env,
    )
    os.replace(nuovo, ESEGUIBILE)
    shutil.copyfile(QUI / "Info.plist", APP / "Contents" / "Info.plist")
    subprocess.run(["codesign", "--force", "--sign", _identita(), str(APP)], check=True)
    subprocess.run(["codesign", "--verify", "--strict", "--deep", str(APP)], check=True)
    COLLEGAMENTO.parent.mkdir(parents=True, exist_ok=True)
    tmp = COLLEGAMENTO.with_name(COLLEGAMENTO.name + ".nuovo")
    if tmp.is_symlink() or tmp.exists():
        os.replace(tmp, COLLEGAMENTO.with_name(COLLEGAMENTO.name + ".vecchio"))
    os.symlink(ESEGUIBILE, tmp)
    os.replace(tmp, COLLEGAMENTO)
    subprocess.run(
        ["/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister",
         "-f", str(APP)],
        capture_output=True,
    )
    print(f"built and signed: {APP}")


def permesso() -> None:
    ""
    REGISTRO.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(["open", "-W", "-g", "-a", str(APP), "--args", "allinea"])
    print(f"permission run finished (open exit code {r.returncode}); log {REGISTRO}")


def agente() -> None:
    if not ESEGUIBILE.exists():
        sys.exit(f"{ESEGUIBILE} is missing: run `build` first")
    REGISTRO.parent.mkdir(parents=True, exist_ok=True)
    PLIST.parent.mkdir(parents=True, exist_ok=True)
    dati = {
        "Label": ETICHETTA,
        "ProgramArguments": [str(ESEGUIBILE), "allinea"],
        "StartInterval": INTERVALLO,
        "RunAtLoad": True,
        "ProcessType": "Background",
        "LowPriorityIO": True,
        "Nice": 10,
        "StandardOutPath": str(REGISTRO),
        "StandardErrorPath": str(REGISTRO),
        # The clone this helper belongs to: SBPromemoria.swift runs tools/secondbrain/sb_promemoria.py from there.
        "EnvironmentVariables": {"SB_RADICE": str(QUI.parents[2])},
    }
    with open(PLIST, "wb") as fh:
        plistlib.dump(dati, fh)
    dominio = f"gui/{os.getuid()}"
    subprocess.run(["launchctl", "bootout", f"{dominio}/{ETICHETTA}"], capture_output=True)
    subprocess.run(["launchctl", "bootstrap", dominio, str(PLIST)], check=True)
    print(f"agent {ETICHETTA} loaded, every {INTERVALLO} s; log {REGISTRO}")


def stato() -> None:
    r = subprocess.run(
        ["launchctl", "print", f"gui/{os.getuid()}/{ETICHETTA}"], capture_output=True, text=True
    )
    vivo = r.returncode == 0
    righe = [
        x.strip()
        for x in r.stdout.splitlines()
        if x.strip().startswith(("state =", "runs =", "last exit code"))
    ]
    print(f"agent {ETICHETTA}: {'loaded' if vivo else 'not loaded'} {' · '.join(righe)}")
    if REGISTRO.exists():
        righe_reg = REGISTRO.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
        print("".join(righe_reg[-8:]), end="")


def spegni() -> None:
    subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}/{ETICHETTA}"], capture_output=True)
    if PLIST.exists():
        os.replace(PLIST, PLIST.with_name(PLIST.name + ".spento"))
    print(f"agent {ETICHETTA} off (plist renamed to .spento)")


if __name__ == "__main__":
    comandi = {
        "build": build,
        "permesso": permesso,
        "agente": agente,
        "stato": stato,
        "spegni": spegni,
    }
    verbo = sys.argv[1] if len(sys.argv) > 1 else ""
    if verbo in ("-h", "--help"):
        print(__doc__)
        sys.exit(0)
    if verbo not in comandi:
        print(__doc__)
        sys.exit(2)
    comandi[verbo]()
