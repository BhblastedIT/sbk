#!/usr/bin/env python3
""
















from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

try:
    from sbk_config import PLAUD_DIR as _RAW_DIR
except Exception:  # pragma: no cover
    _RAW_DIR = Path.home() / ".sbk-data" / "plaud" / "raw"


REGISTRY_PATH = _RAW_DIR.parent / "_speaker_registry.json"


def extract_speakers(response: Any) -> list[dict[str, Any]]:
    ""
    data = response.get("data") if isinstance(response, dict) else None
    src = data if isinstance(data, dict) else response
    if isinstance(src, dict):
        sp = src.get("speakers")
    elif isinstance(src, list):
        sp = src
    else:
        sp = None
    return [s for s in (sp or []) if isinstance(s, dict)]


def _norm(s: Any) -> str:
    return " ".join(str(s or "").lower().split())


def match_to_kb(speakers: list[dict[str, Any]], name_index: Any | None) -> list[dict[str, Any]]:
    ""



    out: list[dict[str, Any]] = []
    for s in speakers:
        name = s.get("speaker_name") or s.get("name") or ""
        eids: set[str] = set()
        if name_index is not None and name:
            try:
                eids = set(name_index.lookup(name)) or set(name_index.resolve(name))
            except Exception:  # noqa: BLE001 - best-effort, il name_index puo' variare
                eids = set()
        emb = s.get("embeddings") or {}
        vec = emb.get("auto") if isinstance(emb, dict) else None
        out.append(
            {
                "speaker_id": s.get("speaker_id") or s.get("id"),
                "name": name,
                "entity_ids": sorted(eids),
                "has_embedding": bool(vec),
                "n_dims": len(vec) if isinstance(vec, list) else 0,
            }
        )
    return out


def save_registry(speakers: list[dict[str, Any]], path: Path | None = None) -> Path:
    ""
    try:
        from tools.plaud.pl_name_index import load_or_build
    except Exception:  # pragma: no cover
        try:
            from pl_name_index import load_or_build  # type: ignore[no-redef]
        except Exception:  # noqa: BLE001
            load_or_build = None  # type: ignore[assignment]
    name_index = None
    if load_or_build is not None:
        try:
            name_index = load_or_build()
        except Exception:  # noqa: BLE001
            name_index = None
    matched = match_to_kb(speakers, name_index)
    dest = path or REGISTRY_PATH
    dest.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "n_speakers": len(speakers),
        "n_matched": sum(1 for m in matched if m["entity_ids"]),
        "index": matched,
        "speakers": speakers,
    }
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp.replace(dest)
    return dest


def load_registry(path: Path | None = None) -> dict[str, Any]:
    ""
    dest = path or REGISTRY_PATH
    if not dest.exists():
        return {}
    return json.loads(dest.read_text(encoding="utf-8"))


def fetch_registry() -> list[dict[str, Any]]:
    ""
    try:
        from tools.plaud.pl_write import _http, get_auth
    except Exception:  # pragma: no cover
        from pl_write import _http, get_auth  # type: ignore[no-redef]
    wt, api = get_auth()
    resp = _http("GET", api, "/speaker/list", wt)
    return extract_speakers(resp)


def _main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Registro voci Plaud (voiceprint)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("fetch")
    sub.add_parser("show")
    args = ap.parse_args()

    if args.cmd == "fetch":
        speakers = fetch_registry()
        dest = save_registry(speakers)
        reg = load_registry(dest)
        print(f"Registro salvato: {dest}")
        print(f"  speaker: {reg['n_speakers']}, matchati al KB: {reg['n_matched']}")
    elif args.cmd == "show":
        reg = load_registry()
        if not reg:
            print("Nessun registro salvato. Esegui 'fetch' (serve WT valido).")
            return 1
        print(f"speaker: {reg['n_speakers']}, matchati al KB: {reg['n_matched']}")
        for m in reg["index"][:15]:
            eid = m["entity_ids"][0] if m["entity_ids"] else "(no-match)"
            print(f"  {m['name']!r} -> {eid}  emb={m['n_dims']}d")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
