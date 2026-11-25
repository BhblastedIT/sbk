""






from __future__ import annotations

import re
from pathlib import Path


def slugify(name: str) -> str:
    slug = name.lower().replace(" ", "-").replace("_", "-")
    slug = re.sub(r"[^a-z0-9\-]", "", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug


def da_trascrivere(cartella: Path, trascrizioni: Path) -> list[Path]:
    ""
    if not cartella.is_dir():
        return []
    return [
        m
        for m in sorted(cartella.glob("*.m4a"))
        if not (trascrizioni / f"{slugify(m.stem)}.json").exists()
    ]
