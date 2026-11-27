#!/usr/bin/env python3
"""L1 inventory: joins the Search Console, Analytics and GitHub data into the tables under <data root>/inventory."""










































from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))

import sbk_config as cfg  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("xs-l1-inventario")

DEST = cfg.DATA_ROOT / "inventory"

GSC_PROPERTY = cfg.DATA_ROOT / "gsc" / "property.json"
GSC_PERF = cfg.DATA_ROOT / "gsc" / "performance"
ANALYTICS = cfg.DATA_ROOT / "analytics" / "property.json"
GITHUB = cfg.DATA_ROOT / "github" / "repos.json"


def _leggi(p: Path) -> dict:
    ""
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def normalizza(dominio: str) -> str:
    ""





    d = str(dominio or "").strip().lower()
    d = re.sub(r"^sc-domain:", "", d)
    d = re.sub(r"^https?://", "", d)
    d = d.split("/")[0]
    return re.sub(r"^www\.", "", d).strip()






def costruisci_domini() -> list[dict]:
    per_dominio: dict[str, dict] = {}

    def voce(nome: str) -> dict:
        k = normalizza(nome)
        if not k:
            return {}
        return per_dominio.setdefault(
            k,
            {
                "dominio": k,
                "search_console": False,
                "clic_28gg": None,
                "impressioni_28gg": None,
                "fonti": [],
            },
        )

    for p in _leggi(GSC_PROPERTY).get("property", []):
        v = voce(p.get("property", ""))
        if not v:
            continue
        v["search_console"] = True
        v["fonti"].append("gsc")
    if GSC_PERF.exists():
        for f in GSC_PERF.glob("*.json"):
            d = _leggi(f)
            v = voce(d.get("property", ""))
            if not v:
                continue



            v["clic_28gg"] = (v["clic_28gg"] or 0) + int(d.get("clic") or 0)
            v["impressioni_28gg"] = (v["impressioni_28gg"] or 0) + int(d.get("impressioni") or 0)

    for v in per_dominio.values():
        v["fonti"] = " ".join(dict.fromkeys(v["fonti"]))
        v["n_fonti"] = len(v["fonti"].split()) if v["fonti"] else 0
    return sorted(per_dominio.values(), key=lambda x: (-x["n_fonti"], x["dominio"]))


def costruisci_repo() -> list[dict]:
    ora = datetime.now(UTC)
    fuori = []
    for r in _leggi(GITHUB).get("repo", []):
        spinto = str(r.get("pushedAt") or "")
        giorni = None
        if spinto:
            try:
                giorni = (ora - datetime.fromisoformat(spinto.replace("Z", "+00:00"))).days
            except ValueError:
                giorni = None
        fuori.append(
            {
                "owner": r.get("owner", ""),
                "nome": r.get("name", ""),
                "descrizione": r.get("descrizione", ""),
                "privata": bool(r.get("privata")),
                "archiviata": bool(r.get("archiviata")),
                "fork": bool(r.get("fork")),
                "linguaggio": r.get("linguaggio", ""),
                "kb": int(r.get("kb") or 0),
                "ultimo_push": spinto[:10],
                "giorni_dall_ultimo_push": giorni,
                "url": r.get("url", ""),
            }
        )
    return sorted(
        fuori,
        key=lambda x: (x["giorni_dall_ultimo_push"] is None, x["giorni_dall_ultimo_push"] or 0),
    )


def rileggi() -> dict:
    import pandas as pd

    DEST.mkdir(parents=True, exist_ok=True)
    domini, repo = costruisci_domini(), costruisci_repo()

    if not (domini or repo):
        log.error(
            "none of the inventory sources left readable data, "
            "first run the L0 collectors (tools/{gsc,analytics,github}/*-l0-*.py)"
        )
        return {}

    for nome, righe in (("domini", domini), ("repo", repo)):
        if righe:
            cfg.safe_write_parquet(pd.DataFrame(righe), DEST / f"{nome}.parquet")

    incrociati = sum(1 for d in domini if d["n_fonti"] > 1)
    return {
        "domini": len(domini),
        "domini_in_piu_fonti": incrociati,
        "domini_in_una_sola": len(domini) - incrociati,
        "con_traffico": sum(1 for d in domini if (d["clic_28gg"] or 0) > 0),
        "repo": len(repo),
        "repo_attive_90gg": sum(
            1
            for r in repo
            if r["giorni_dall_ultimo_push"] is not None and r["giorni_dall_ultimo_push"] <= 90
        ),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()
    if not any((cfg.DATA_ROOT / s).exists() for s in ("gsc", "analytics", "github")):
        # None of the three inventory sources was ever downloaded: nothing to reread, not an error.
        log.info("Inventory: nothing downloaded yet for gsc, analytics or github, nothing to do")
        return 0
    e = rileggi()
    if not e:
        return 1
    if not a.quiet:
        for k, v in e.items():
            log.info("  %-24s %s", k, f"{v:,}")
        log.info("  written to %s", DEST)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
