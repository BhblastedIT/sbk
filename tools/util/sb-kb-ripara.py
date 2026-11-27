#!/usr/bin/env python3
"""Restores one unreadable knowledge-base profile from the most recent backup tar that holds it. Dry run by default;
--apply writes, and the damaged file is kept for diagnosis.
"""

from __future__ import annotations

import argparse
import json
import sys
import tarfile
from datetime import datetime, timezone  # noqa: UP017
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))

from sbk_config import DATA_ROOT, KNOWLEDGE_ENTITIES_DIR, safe_write_json  # noqa: E402




# Where the KB tars are: the brain copies of tools/cross-source/xs-l0-refresh.py (backup_kb)
# and the copies made before compaction and re-anchoring, all under the data root.
CARTELLE_TAR = (
    DATA_ROOT / "backups-knowledge",
    DATA_ROOT / "backups-compaction",
    DATA_ROOT / "backups-reanchor",
)


class NonRiparabile(Exception):
    ""


def tar_piu_recente(cartelle=CARTELLE_TAR):
    ""
    candidati = [t for c in cartelle if c.exists() for t in c.glob("*.tar.gz")]
    return max(candidati, key=lambda p: p.stat().st_mtime) if candidati else None


def _dal_tar(tar: Path, entity_id: str) -> tuple[dict, str]:
    ""
    atteso = f"entities/{entity_id}.json"
    with tarfile.open(tar, "r:gz") as t:
        for m in t:
            if not m.isfile() or not m.name.endswith(f"/{entity_id}.json"):
                continue
            if "/entities/" not in m.name and not m.name.endswith(atteso):
                continue
            f = t.extractfile(m)
            if f is None:
                continue
            return json.loads(f.read().decode("utf-8")), m.name
    raise NonRiparabile(f"{entity_id} is not in {tar.name}")


def _riassunto(d: dict) -> dict:
    return {
        "version": d.get("version"),
        "fatti": len(d.get("facts") or []),
        "updated_at": d.get("updated_at"),
        "canonical_name": d.get("canonical_name"),
    }


def ripara(entity_id: str, *, tar=None, entities_dir=None, applica: bool = False) -> dict:
    ""






    tar = Path(tar) if tar else tar_piu_recente()
    if not tar or not Path(tar).exists():
        raise NonRiparabile(f"no tar available in {[str(c) for c in CARTELLE_TAR]}")
    salvato, membro = _dal_tar(Path(tar), entity_id)

    base = Path(entities_dir) if entities_dir else KNOWLEDGE_ENTITIES_DIR
    tipo = salvato.get("entity_type") or membro.split("/")[-2]
    vivo_path = base / tipo / f"{entity_id}.json"
    try:
        vivo = json.loads(vivo_path.read_text(encoding="utf-8"))
        stato_vivo = {"leggibile": True, **_riassunto(vivo)}
    except (OSError, ValueError) as e:
        stato_vivo = {"leggibile": False, "perche": str(e)[:120], "esiste": vivo_path.exists()}

    esito = {
        "entita": entity_id,
        "tar": str(tar),
        "membro": membro,
        "vivo_path": str(vivo_path),
        "dal_tar": _riassunto(salvato),
        "vivo": stato_vivo,
        "applicato": False,
    }
    if not applica:
        return esito

    accantonato = None
    if vivo_path.exists():
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")  # noqa: UP017
        accantonato = vivo_path.with_suffix(f".json.corrupt-{ts}")
        vivo_path.replace(accantonato)
    try:
        safe_write_json(vivo_path, salvato, indent=2, ensure_ascii=True, fsync=True)
    except Exception:
        if accantonato is not None:
            accantonato.replace(vivo_path)
        raise
    esito["applicato"] = True
    esito["accantonato"] = str(accantonato) if accantonato else None
    return esito


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Restores an unreadable KB profile from the tar (dry-run by default)",
        epilog=(
            "LIMITS: the tars are manual actions, ~9 day window. The .jsonl fallback "
            "(knowledge/facts/<tipo>/<id>.jsonl) is NOT a safety net: it covers only a small "
            "part of the entities, a stroke of luck, not a backup."
        ),
    )
    ap.add_argument("--entita", required=True, help="entity_id to restore")
    ap.add_argument("--da", help="specific tar (default: the most recent of the three known ones)")
    ap.add_argument("--apply", action="store_true", help="actually writes (default: dry-run)")
    a = ap.parse_args()

    try:
        esito = ripara(a.entita, tar=a.da, applica=a.apply)
    except NonRiparabile as e:
        print(f"❌ {e}")
        print("   Nothing was touched. The damaged file stays where it is, for diagnosis.")
        return 1

    print(f"entity   {esito['entita']}")
    print(f"tar      {esito['tar']}")
    print(f"from tar {esito['dal_tar']}")
    print(f"live     {esito['vivo']}")
    if not a.apply:
        print("\n(dry-run: nothing written)  to restore: --apply")
        return 0
    print(f"\n✓ restored: {esito['vivo_path']}")
    if esito.get("accantonato"):
        print(f"  the broken one is here, not deleted: {esito['accantonato']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
