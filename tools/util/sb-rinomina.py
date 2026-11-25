#!/usr/bin/env python3
""





























from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import sbk_config as cfg  # noqa: E402

PERSON = cfg.DATA_ROOT / "knowledge" / "entities" / "person"
JOURNAL = cfg.DATA_ROOT / "knowledge" / "meta" / "rinomina-journal.jsonl"

_INDIRIZZO = re.compile(r"^[\w.+-]+@[\w.-]+\.\w+$")

_COMPOSITO = re.compile(r"[,&/]|\s(?:e|and)\s|\bteam\b|\bs\.?r\.?l\b|\bs\.p\.a\b", re.I)


def e_indirizzo(s: str) -> bool:
    return bool(_INDIRIZZO.match((s or "").strip()))


def candidato(nome_attuale: str, fatti: list[dict]) -> tuple[str | None, str]:
    ""
    conta: collections.Counter = collections.Counter()
    for f in fatti:
        if str(f.get("attribute") or "") != "identity.name":
            continue
        v = str(f.get("value") or "").strip()
        if not v or e_indirizzo(v) or _COMPOSITO.search(v):
            continue
        pezzi = v.split()
        if len(pezzi) < 2:
            continue






        if any(len(x) < 2 for x in pezzi):
            continue
        if re.match(
            r"^(support|info|team|admin|noreply|no-reply|help|sales|hr|contact)\b", v, re.I
        ):
            continue
        conta[v] += 1
    if not conta:
        return None, "no full name among their identity.name"
    if len(conta) > 1:

        (primo, n1), (_, n2) = conta.most_common(2)
        if n1 <= n2:
            return None, f"{len(conta)} candidate names and none prevails: {list(conta)[:3]}"
        return primo, f"prevails over {len(conta)} candidates ({n1} vs {n2})"
    solo = conta.most_common(1)[0]
    return solo[0], f"only full name, {solo[1]} occurrences"


def scorri():
    for f in sorted(PERSON.glob("*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        nome = (d.get("canonical_name") or "").strip()
        if not e_indirizzo(nome):
            continue
        nuovo, perche = candidato(nome, d.get("facts") or [])
        yield f, d, nome, nuovo, perche


def main() -> int:
    ap = argparse.ArgumentParser(description="Restores the real name to those named like an address")
    ap.add_argument("--esegui", action="store_true")
    a = ap.parse_args()

    fatti_ok = fatti_no = 0
    ok: list[tuple] = []
    no: list[tuple] = []
    journal = []
    for f, d, nome, nuovo, perche in scorri():
        n = len(d.get("facts") or [])
        if nuovo:
            ok.append((n, nome, nuovo, perche))
            fatti_ok += n
            if a.esegui:
                d["canonical_name"] = nuovo
                d.setdefault("facts", []).append(
                    {
                        "fact_id": f"rinomina-{f.stem}",
                        "entity_id": f.stem,
                        "entity_type": "person",
                        "attribute": "identity.name",
                        "value": nuovo,
                        "confidence": 0.9,
                        "valid_from": datetime.now(UTC).date().isoformat(),
                        "created_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "source": {
                            "source_type": "manual_input",
                            "source_file": "rinomina-nome-indirizzo",
                            "record_id": nome,
                            "extracted_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                        },
                    }
                )
                f.write_text(json.dumps(d, ensure_ascii=False, indent=1))
                journal.append(
                    {"op": "rinomina", "eid": f.stem, "da": nome, "a": nuovo, "perche": perche}
                )
        else:
            no.append((n, nome, perche))
            fatti_no += n

    print(f"\nentities named like an address: {len(ok) + len(no)}")
    print(f"   with a real name inside       : {len(ok)}  ({fatti_ok} facts)")
    print(f"   to decide by hand             : {len(no)}  ({fatti_no} facts)")
    print("\nrenamable, the largest:")
    for n, vecchio, nuovo, perche in sorted(ok, reverse=True)[:10]:
        print(f"   {vecchio[:32]:32} {n:5} → «{nuovo[:28]}»  ({perche[:38]})")
    print("\nto decide, the largest:")
    for n, vecchio, perche in sorted(no, reverse=True)[:6]:
        print(f"   {vecchio[:32]:32} {n:5} — {perche[:56]}")

    if a.esegui and journal:
        JOURNAL.parent.mkdir(parents=True, exist_ok=True)
        with JOURNAL.open("a", encoding="utf-8") as fh:
            for x in journal:
                fh.write(json.dumps(x, ensure_ascii=False) + "\n")
        print(f"\n   renamed: {len(journal)}   journal: {JOURNAL}")
    elif not a.esegui:
        print("\n  dry run: nothing was touched. With --esegui it writes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
