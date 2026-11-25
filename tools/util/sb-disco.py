#!/usr/bin/env python3
"""How much disk there really is, counting the swap that can come back. Read-only, on request."""


















from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time

GIB = 1 << 30
VOLUME = "/System/Volumes/Data"
TELEMETRIA = os.path.expanduser("~/Library/Logs/mem-telemetry.csv")
GIORNI_PICCO = 7
CODA_BYTE = 4 << 20


def _sysctl(nome: str) -> str:
    try:
        return subprocess.run(
            ["sysctl", "-n", nome], capture_output=True, text=True, timeout=5
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def swap_ora() -> float | None:
    ""
    m = re.search(r"total\s*=\s*([\d.]+)([MG])", _sysctl("vm.swapusage"))
    if not m:
        return None
    v = float(m.group(1))
    return v / 1024 if m.group(2) == "M" else v


def picco_swap(
    percorso: str = TELEMETRIA, giorni: int = GIORNI_PICCO, adesso: float | None = None
) -> float | None:
    ""
    try:
        with open(percorso, "rb") as f:
            f.seek(0, os.SEEK_END)
            n = f.tell()
            f.seek(max(0, n - CODA_BYTE))
            righe = f.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return None
    soglia = (adesso or time.time()) - giorni * 86400
    picco = None
    for r in righe:
        c = r.split(",")
        if len(c) < 8 or not c[0][:4].isdigit():
            continue
        try:
            t = time.mktime(time.strptime(c[0], "%Y-%m-%d %H:%M:%S"))
            sf = float(c[7])
        except ValueError:
            continue
        if t >= soglia and (picco is None or sf > picco):
            picco = sf
    return picco


def ram_gib() -> float:
    try:
        return int(_sysctl("hw.memsize")) / GIB
    except ValueError:
        return 16.0


def compressore() -> float | None:
    try:
        return int(_sysctl("vm.compressor.segment.total")) / int(
            _sysctl("vm.compressor.segment.limit")
        )
    except (ValueError, ZeroDivisionError):
        return None


def snapshot_locali() -> int | None:
    try:
        out = subprocess.run(
            ["tmutil", "listlocalsnapshots", VOLUME], capture_output=True, text=True, timeout=10
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    return sum(1 for r in out.splitlines() if "com.apple" in r)


def margine(
    df: float, swap: float | None, picco: float | None, pavimento: float
) -> tuple[float, float, bool]:
    ""
    vero = picco is not None
    p = picco if vero else pavimento
    s = swap if swap is not None else 0.0
    return df - max(0.0, p - s), p, vero


def misura() -> dict:
    st = os.statvfs(VOLUME)
    df = st.f_bavail * st.f_frsize / GIB
    sw = swap_ora()
    pc = picco_swap()
    m, p, vero = margine(df, sw, pc, ram_gib())
    return {
        "ora": time.strftime("%Y-%m-%d %H:%M"),
        "df_gib": round(df, 1),
        "swap_gib": None if sw is None else round(sw, 1),
        "picco_swap_gib": round(p, 1),
        "picco_dalla_telemetria": vero,
        "margine_gib": round(m, 1),
        "compressore": None if compressore() is None else round(compressore(), 2),
        "snapshot_locali": snapshot_locali(),
    }


def riga_breve(d: dict) -> str:
    picco = f"picco {d['picco_swap_gib']:.0f}" + (
        "" if d["picco_dalla_telemetria"] else " stimato, telemetria assente"
    )
    sw = "?" if d["swap_gib"] is None else f"{d['swap_gib']:.0f}"
    comp = "" if d["compressore"] is None else f" · compressore {d['compressore']:.2f}"
    snap = f" · {d['snapshot_locali']} snapshot locali" if d.get("snapshot_locali") else ""
    return f"disco {d['df_gib']:.0f} GiB liberi · swap {sw} ({picco}) · margine {d['margine_gib']:.0f}{comp}{snap}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("misura", help="df, swap, margine, compressore, snapshot (sola lettura)")
    m.add_argument("--breve", action="store_true")
    m.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    d = misura()
    if a.json:
        print(json.dumps(d, ensure_ascii=False))
    elif a.breve:
        print(riga_breve(d))
    else:
        for k, v in d.items():
            print(f"{k:24} {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
