""






from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml

log = logging.getLogger("sbk-ingestion.manifest")

MANIFESTS_DIR = Path(__file__).resolve().parent / "manifests"

_VALID_TYPES = {
    "official-api",
    "official-cli",
    "sanctioned-export",
    "reverse-eng",
    "manual-export",
    "local",
}
_VALID_TOS = {"safe", "violates"}


@dataclass
class AdapterSpec:
    ""

    name: str
    type: str
    auth: str
    tos: str
    priority: int
    enabled: bool = True
    config: dict = field(default_factory=dict)


@dataclass
class Manifest:
    ""

    source: str
    cadence_hours: float
    adapters: list[AdapterSpec]
    sanity_baseline: dict = field(default_factory=dict)
    probe: str = ""

    @property
    def primary(self) -> AdapterSpec | None:
        active = [a for a in self.adapters if a.enabled]
        return active[0] if active else None


class ManifestError(ValueError):
    ""


def _validate(source: str, raw: dict) -> Manifest:
    if not isinstance(raw, dict):
        raise ManifestError(f"{source}: manifest is not a YAML mapping")
    if raw.get("source") != source:
        raise ManifestError(
            f"{source}: 'source' field ({raw.get('source')!r}) != file name ({source!r})"
        )
    if "cadence_hours" not in raw:
        raise ManifestError(f"{source}: missing 'cadence_hours'")
    adapters_raw = raw.get("adapters") or []
    if not adapters_raw:
        raise ManifestError(f"{source}: no adapter declared")

    specs: list[AdapterSpec] = []
    seen_priorities: set[int] = set()
    for i, a in enumerate(adapters_raw):
        for req in ("name", "type", "auth", "tos", "priority"):
            if req not in a:
                raise ManifestError(f"{source}: adapter #{i} missing '{req}'")
        if a["type"] not in _VALID_TYPES:
            raise ManifestError(f"{source}: adapter {a['name']!r} invalid type: {a['type']!r}")
        if a["tos"] not in _VALID_TOS:
            raise ManifestError(f"{source}: adapter {a['name']!r} invalid tos: {a['tos']!r}")
        prio = int(a["priority"])
        if prio in seen_priorities:
            raise ManifestError(f"{source}: duplicate priority {prio} (must be unique)")
        seen_priorities.add(prio)
        specs.append(
            AdapterSpec(
                name=a["name"],
                type=a["type"],
                auth=a["auth"],
                tos=a["tos"],
                priority=prio,
                enabled=bool(a.get("enabled", True)),
                config=a.get("config", {}) or {},
            )
        )
    specs.sort(key=lambda s: s.priority)
    return Manifest(
        source=source,
        cadence_hours=float(raw["cadence_hours"]),
        adapters=specs,
        sanity_baseline=raw.get("sanity_baseline", {}) or {},
        probe=raw.get("probe", ""),
    )


def load_manifest(source: str, manifests_dir: Path | None = None) -> Manifest:
    ""
    d = manifests_dir or MANIFESTS_DIR
    path = d / f"{source}.yaml"
    if not path.exists():
        raise ManifestError(f"manifest not found: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return _validate(source, raw)


def load_all(manifests_dir: Path | None = None) -> dict[str, Manifest]:
    ""
    d = manifests_dir or MANIFESTS_DIR
    out: dict[str, Manifest] = {}
    for path in sorted(d.glob("*.yaml")):
        source = path.stem
        out[source] = load_manifest(source, manifests_dir=d)
    return out
