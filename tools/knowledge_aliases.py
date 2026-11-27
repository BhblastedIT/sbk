#!/usr/bin/env python3
"""Curated aliases (nickname -> full name, optional entity id) in knowledge/aliases.json, used to match people
written by nickname. --list, --check <name>, --add <nickname> --canonical <name>.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import unicodedata
from datetime import UTC, datetime
from pathlib import Path

ALIASES_PATH = (
    Path(os.environ.get("SBK_DATA_ROOT") or Path.home() / ".sbk-data").expanduser()
    / "knowledge"
    / "aliases.json"
)


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(s.lower().split())


def _load() -> dict:
    if ALIASES_PATH.exists():
        try:
            return json.loads(ALIASES_PATH.read_text())
        except Exception:
            pass
    return {"_schema": 1, "aliases": {}}


def _save(data: dict) -> None:
    ALIASES_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = ALIASES_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True))
    tmp.rename(ALIASES_PATH)


def canonical(raw: str) -> dict | None:
    ""

    entry = _load()["aliases"].get(_norm(raw))
    if not entry:
        return None
    return {
        "name": entry["canonical"],
        "entity_id": entry.get("entity_id", ""),
        "via": "alias-store",
    }


def display(raw: str) -> str:
    hit = canonical(raw)
    return f"{hit['name']} (alias: {raw})" if hit else raw


def add(alias: str, canonical_name: str, entity_id: str = "", fonte: str = "") -> None:
    data = _load()
    data["aliases"][_norm(alias)] = {
        "canonical": canonical_name,
        "entity_id": entity_id,
        "fonte": fonte,
        "verificato": datetime.now(tz=UTC).strftime("%Y-%m-%d"),
    }
    _save(data)


def main() -> int:
    ap = argparse.ArgumentParser(description="Curated alias store, nickname -> canonical name")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--check")
    ap.add_argument("--add")
    ap.add_argument("--canonical")
    ap.add_argument("--entity", default="")
    ap.add_argument("--fonte", default="")
    args = ap.parse_args()

    if args.add:
        if not args.canonical:
            print("--add needs --canonical")
            return 2
        add(args.add, args.canonical, args.entity, args.fonte)
        print(f"added: «{args.add}» -> {args.canonical} ({args.entity or 'no id'})")
        return 0
    if args.check:
        hit = canonical(args.check)
        print(json.dumps(hit, ensure_ascii=False) if hit else f"no alias for «{args.check}»")
        return 0
    data = _load()
    print(f"{len(data['aliases'])} alias in {ALIASES_PATH}:")
    for k, v in sorted(data["aliases"].items()):
        print(
            f"  «{k}» -> {v['canonical']}  [{v.get('entity_id', '')}] ({v.get('fonte', '')}, {v.get('verificato', '')})"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
