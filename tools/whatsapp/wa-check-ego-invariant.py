#!/usr/bin/env python3
"""Guard for the WhatsApp interactions table: every row must have you on one side (I-WA1), nobody
writes to themselves (I-WA3), and the L1 summary says how many chats did not contain you (I-WA2).

Run it after wa-l1-enrich.py. Exit 1 when a check is red. --esca plants a bad row to prove the
guard turns red. You are recognised through "owner" and "own_names" in sbk.config.json.

    uv run python tools/whatsapp/wa-check-ego-invariant.py
"""





























from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

TOOLS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOLS))

from sbk_config import (  # noqa: E402
    OWN_NAMES_NORMALIZED,
    OWNER_NAME,
    WHATSAPP_DIR,
)









# default threshold; tune for your corpus (configurable)
SOGLIA_CHAT_SENZA_EGO = 650

ESEMPI_DA_MOSTRARE = 5


def _batch_rows() -> int:
    ""
    try:
        import sbk_resources as risorse


        return max(50_000, risorse.budget(share=True).batch_rows(bytes_per_row=120))
    except Exception:
        return 250_000


def _norm(colonna: pa.ChunkedArray | pa.Array) -> pa.Array:
    ""
    return pc.utf8_lower(pc.utf8_trim_whitespace(colonna.cast(pa.string())))


def _ego_mask(colonna: pa.ChunkedArray | pa.Array) -> pa.Array:
    ""





    nomi = {n.strip().lower() for n in OWN_NAMES_NORMALIZED} | {OWNER_NAME.strip().lower()}
    ego = pa.array(sorted(nomi), type=pa.string())
    return pc.is_in(_norm(colonna), value_set=ego)


def verifica_parquet(path: Path, esca: bool = False) -> dict:
    ""
    pf = pq.ParquetFile(path)
    totali = 0
    violazioni = 0
    esempi: list[dict] = []

    self_edge = 0
    esempi_self: list[dict] = []

    for batch in pf.iter_batches(
        batch_size=_batch_rows(), columns=["from_name", "to_name", "chat_name"]
    ):
        totali += batch.num_rows
        tocca = pc.or_(_ego_mask(batch.column("from_name")), _ego_mask(batch.column("to_name")))
        fuori = pc.invert(tocca)
        n = pc.sum(fuori).as_py() or 0
        violazioni += n
        if n and len(esempi) < ESEMPI_DA_MOSTRARE:
            cattive = batch.filter(fuori).slice(0, ESEMPI_DA_MOSTRARE - len(esempi))
            for riga in cattive.to_pylist():
                esempi.append(riga)



        uguali = pc.equal(_norm(batch.column("from_name")), _norm(batch.column("to_name")))
        ns = pc.sum(uguali).as_py() or 0
        self_edge += ns
        if ns and len(esempi_self) < ESEMPI_DA_MOSTRARE:
            cattive = batch.filter(uguali).slice(0, ESEMPI_DA_MOSTRARE - len(esempi_self))
            esempi_self.extend(cattive.to_pylist())

    if esca:


        violazioni += 1
        totali += 1
        esempi.insert(
            0,
            {
                "from_name": "Mia Conti",
                "to_name": "Chris Monroe",
                "chat_name": "Big Group [BAIT]",
            },
        )

    return {
        "righe": totali,
        "violazioni": violazioni,
        "esempi": esempi,
        "self_edge": self_edge,
        "esempi_self": esempi_self,
    }


def verifica_contatore(summary_path: Path) -> dict:
    ""
    if not summary_path.exists():
        return {"stato": "assente", "chat_senza_ego": None}
    dati = json.loads(summary_path.read_text())
    ego = dati.get("ego_invariant")
    if not isinstance(ego, dict) or "chat_senza_ego" not in ego:
        return {"stato": "non_riportato", "chat_senza_ego": None}
    return {"stato": "presente", **ego}


def main() -> int:
    ap = argparse.ArgumentParser(description="Guard for the I-WA invariant (egocentric graph)")
    ap.add_argument("--parquet", type=Path, default=None)
    ap.add_argument("--summary", type=Path, default=None)
    ap.add_argument(
        "--esca",
        action="store_true",
        help="plant a row between third parties: the guard MUST turn red",
    )
    args = ap.parse_args()


    parquet = args.parquet or (WHATSAPP_DIR / "interactions-whatsapp.parquet")
    summary = args.summary or (WHATSAPP_DIR / "_whatsapp_summary.json")

    if not parquet.exists():
        print(f"I-WA: parquet missing, nothing to verify: {parquet}")
        return 0

    rosso = False

    r = verifica_parquet(parquet, esca=args.esca)
    quota = 100.0 * r["violazioni"] / r["righe"] if r["righe"] else 0.0
    print(f"I-WA1  total rows: {r['righe']:,}")
    print(f"I-WA1  rows that do NOT touch the ego: {r['violazioni']:,} ({quota:.2f}%)")
    if r["violazioni"]:
        rosso = True
        print("I-WA1  RED — the graph is not egocentric. Examples:")
        for e in r["esempi"]:
            print(f"         {e['from_name']!r} -> {e['to_name']!r}  in {e['chat_name']!r}")
        print(
            "I-WA1  expected cause: build_interactions() emits the full fan-out "
            "of groups instead of only the edges that touch the ego "
            "(tools/whatsapp/wa-l1-enrich.py)."
        )

    print(f"I-WA3  self-edge (normalized comparison): {r['self_edge']:,}")
    if r["self_edge"]:
        rosso = True
        print("I-WA3  RED — someone talks to themselves. Examples:")
        for e in r["esempi_self"]:
            print(f"         {e['from_name']!r} -> {e['to_name']!r}  in {e['chat_name']!r}")
        print(
            "I-WA3  expected cause: the participant list contains the same person "
            "with two spellings and the sender/participant comparison is not normalized."
        )

    c = verifica_contatore(summary)
    if c["stato"] == "assente":
        print(f"I-WA2  summary missing: {summary} — counter not verifiable")
    elif c["stato"] == "non_riportato":
        rosso = True
        print(
            "I-WA2  RED — the summary does not report 'ego_invariant': the producer "
            "no longer counts what it discards, and a chat can disappear silently."
        )
    else:
        n = c.get("chat_senza_ego") or 0
        print(
            f"I-WA2  chats without ego: {n} (threshold {SOGLIA_CHAT_SENZA_EGO}); "
            f"rows not produced: {c.get('righe_chat_senza_ego', 0):,}; "
            f"rows between third parties suppressed: {c.get('righe_fra_terzi_soppresse', 0):,}"
        )
        if n > SOGLIA_CHAT_SENZA_EGO:
            rosso = True
            print(
                f"I-WA2  RED — {n} chats do not contain the ego. Probably a spelling of "
                "your name is missing from own_names in sbk.config.json: "
                "add it THERE, not in the individual scripts."
            )

    print("I-WA   " + ("RED" if rosso else "green"))
    return 1 if rosso else 0


if __name__ == "__main__":
    sys.exit(main())
