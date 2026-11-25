#!/usr/bin/env python3
""


































































from __future__ import annotations

import json
import math
from pathlib import Path




PUNTI_MINIMI = 0.05



SIGMA = 3.0





MARCATORE = "CONIO-ROSSO"


def soglia(quota_stock: float, nate: int) -> float:
    ""





    if nate <= 0:
        return 1.0
    p = min(max(quota_stock, 0.0), 1.0)
    rumore = SIGMA * math.sqrt(p * (1.0 - p) / nate)
    return min(1.0, p + max(PUNTI_MINIMI, rumore))


def fotografia(dir_person: Path, e_composito) -> tuple[int, int]:
    ""







    dir_person = Path(dir_person)
    if not dir_person.is_dir():
        return 0, 0
    compositi = totale = 0
    for f in dir_person.iterdir():
        if f.suffix != ".json":
            continue
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):



            continue
        nome = (d.get("canonical_name") or "").strip()
        totale += 1
        if nome and e_composito(nome):
            compositi += 1
        del d
    return compositi, totale


def verdetto(
    nate: int,
    compositi_nati: int,
    compositi_store: int,
    persone_store: int,
    gia_scritte: bool = True,
) -> dict:
    ""












    esito = {
        "nate": nate,
        "composite": compositi_nati,
        "quota": None,
        "stock_prima": None,
        "stock_prima_su": None,
        "quota_stock": None,
        "soglia": None,
        "rosso": False,
        "perche": "",
    }

    if nate <= 0:
        esito["perche"] = "no entity minted in this run: nothing to judge"
        return esito

    quota = compositi_nati / nate
    esito["quota"] = quota

    compositi_prima = compositi_store - (compositi_nati if gia_scritte else 0)
    persone_prima = persone_store - (nate if gia_scritte else 0)
    esito["stock_prima"] = compositi_prima
    esito["stock_prima_su"] = persone_prima




    if persone_prima <= 0 or compositi_prima < 0:
        esito["rosso"] = compositi_nati > 0
        esito["perche"] = (
            f"no reconstructable base (stock before: {compositi_prima} out of {persone_prima}): "
            f"invariant I1 applies — zero composites in person/, minted {compositi_nati}"
        )
        return esito

    quota_stock = compositi_prima / persone_prima
    s = soglia(quota_stock, nate)
    esito["quota_stock"] = quota_stock
    esito["soglia"] = s
    esito["rosso"] = quota > s
    esito["perche"] = (
        f"minted {compositi_nati}/{nate} = {quota * 100:.2f}% · "
        f"stock before {compositi_prima}/{persone_prima} = {quota_stock * 100:.2f}% · "
        f"threshold {s * 100:.2f}%"
    )
    return esito


def riga_di_log(esito: dict) -> str:
    ""
    if esito.get("rosso"):
        return f"{MARCATORE}: {esito.get('perche', '')}"
    return f"minting: {esito.get('perche', '')}"
