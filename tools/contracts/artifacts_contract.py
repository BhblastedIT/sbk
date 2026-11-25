""










from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

DEFAULT_CONTRACT_PATH = Path(__file__).resolve().parent / "artifacts.yaml"


REQUIRED_SECTIONS = (
    "path",
    "tier",
    "domain",
    "inventory_class",
    "rebuild_class",
    "schema",
    "sanity",
)

_VALID_INVENTORY = {"curated", "derived", "ephemeral"}
_VALID_REBUILD = {"rebuildable", "irreplaceable"}
_REQUIRED_SANITY = ("min_rows", "max_drop_pct")


class ContractError(ValueError):
    ""


@dataclass
class ArtifactContract:
    ""

    artifact_id: str
    path: str
    tier: int
    domain: str
    inventory_class: str
    rebuild_class: str
    schema_columns: dict
    min_rows: int
    max_drop_pct: float
    sentinels: list = field(default_factory=list)
    min_sentinels_present: int = 0
    raw: dict = field(default_factory=dict)


@dataclass
class ValidationResult:
    ""

    artifact_id: str
    ok: bool
    issues: list = field(default_factory=list)
    checks: dict = field(default_factory=dict)

    def add_issue(self, msg: str) -> None:
        self.issues.append(msg)
        self.ok = False


def _validate_entry(artifact_id: str, entry: dict) -> ArtifactContract:
    if not isinstance(entry, dict):
        raise ContractError(f"{artifact_id}: entry is not a mapping")

    for section in REQUIRED_SECTIONS:
        if section not in entry:
            raise ContractError(f"{artifact_id}: missing required section {section!r}")

    inv = entry["inventory_class"]
    if inv not in _VALID_INVENTORY:
        raise ContractError(
            f"{artifact_id}: invalid inventory_class {inv!r} "
            f"(allowed: {', '.join(sorted(_VALID_INVENTORY))})"
        )
    reb = entry["rebuild_class"]
    if reb not in _VALID_REBUILD:
        raise ContractError(
            f"{artifact_id}: invalid rebuild_class {reb!r} "
            f"(allowed: {', '.join(sorted(_VALID_REBUILD))})"
        )

    schema = entry["schema"]
    if not isinstance(schema, dict) or "columns" not in schema:
        raise ContractError(f"{artifact_id}: schema must contain 'columns'")
    columns = schema["columns"]
    if not isinstance(columns, dict) or not columns:
        raise ContractError(f"{artifact_id}: schema.columns empty or invalid")

    sanity = entry["sanity"]
    if not isinstance(sanity, dict):
        raise ContractError(f"{artifact_id}: sanity is not a mapping")
    for key in _REQUIRED_SANITY:
        if key not in sanity:
            raise ContractError(f"{artifact_id}: sanity is missing {key!r}")

    sentinels = sanity.get("sentinels", []) or []
    if not isinstance(sentinels, list):
        raise ContractError(f"{artifact_id}: sanity.sentinels must be a list")
    quota = sanity.get("quota", {}) or {}
    min_present = int(quota.get("min_present", len(sentinels)))

    return ArtifactContract(
        artifact_id=artifact_id,
        path=str(entry["path"]),
        tier=int(entry["tier"]),
        domain=str(entry["domain"]),
        inventory_class=inv,
        rebuild_class=reb,
        schema_columns=dict(columns),
        min_rows=int(sanity["min_rows"]),
        max_drop_pct=float(sanity["max_drop_pct"]),
        sentinels=sentinels,
        min_sentinels_present=min_present,
        raw=entry,
    )


def load_contracts(path: Path | None = None) -> dict[str, ArtifactContract]:
    ""
    p = Path(path) if path is not None else DEFAULT_CONTRACT_PATH
    if not p.exists():
        raise ContractError(f"artifacts.yaml not found: {p}")
    raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or "artifacts" not in raw:
        raise ContractError(f"{p}: missing key 'artifacts'")
    artifacts = raw["artifacts"]
    if not isinstance(artifacts, dict) or not artifacts:
        raise ContractError(f"{p}: 'artifacts' empty or invalid")
    out: dict[str, ArtifactContract] = {}
    for artifact_id, entry in artifacts.items():
        out[artifact_id] = _validate_entry(artifact_id, entry)
    return out


def load_contract(artifact_id: str, path: Path | None = None) -> ArtifactContract:
    ""
    contracts = load_contracts(path)
    if artifact_id not in contracts:
        raise ContractError(f"artifact not present in the contract: {artifact_id!r}")
    return contracts[artifact_id]


def _non_null_pct(df, column: str) -> float:
    total = len(df)
    if total == 0:
        return 0.0
    non_null = int(df[column].notna().sum())
    return non_null / total * 100.0


def validate_dataframe(
    contract: ArtifactContract,
    df,
    *,
    previous_count: int | None = None,
) -> ValidationResult:
    ""







    result = ValidationResult(artifact_id=contract.artifact_id, ok=True)


    missing = [c for c in contract.schema_columns if c not in df.columns]
    result.checks["schema_missing_columns"] = missing
    if missing:
        result.add_issue(f"missing columns: {missing}")


    n = len(df)
    result.checks["rows"] = n
    result.checks["min_rows"] = contract.min_rows
    if n < contract.min_rows:
        result.add_issue(f"rows {n} < min_rows {contract.min_rows}")


    if previous_count is not None and previous_count > 0:
        drop_pct = (previous_count - n) / previous_count * 100.0
        result.checks["drop_pct"] = round(drop_pct, 3)
        if drop_pct > contract.max_drop_pct:
            result.add_issue(
                f"drop {drop_pct:.2f}% > max_drop_pct {contract.max_drop_pct}% "
                f"(prev={previous_count}, cur={n})"
            )


    passed = 0
    sentinel_report = []
    for sent in contract.sentinels:
        col = sent.get("column")
        threshold = float(sent.get("min_non_null_pct", 0.0))
        if col not in df.columns:
            sentinel_report.append({"column": col, "present": False, "pct": None})
            continue
        pct = _non_null_pct(df, col)
        ok = pct >= threshold
        sentinel_report.append(
            {"column": col, "present": True, "pct": round(pct, 2), "threshold": threshold, "ok": ok}
        )
        if ok:
            passed += 1
    result.checks["sentinels"] = sentinel_report
    result.checks["sentinels_passed"] = passed
    result.checks["sentinels_min_present"] = contract.min_sentinels_present
    if passed < contract.min_sentinels_present:
        result.add_issue(
            f"sentinels passed {passed} < min_present {contract.min_sentinels_present}"
        )

    return result
