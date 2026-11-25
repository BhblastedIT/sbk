""










from __future__ import annotations

import re
import tarfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CLASSIFICATION_PATH = (
    Path(__file__).resolve().parent / "registries" / "data-classification.yaml"
)


class ClassificationError(Exception):
    ""


@dataclass(frozen=True)
class DriftFinding:
    member: str
    rule: str
    severity: str


def load_classification(path: str | Path | None = None) -> dict[str, Any]:
    p = Path(path) if path is not None else DEFAULT_CLASSIFICATION_PATH
    if not p.exists():
        raise ClassificationError(f"classificazione assente: {p}")
    doc = yaml.safe_load(p.read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise ClassificationError("classificazione: root non è un mapping")
    for key in ("classes", "backup_policy", "forbidden_in_tar"):
        if key not in doc:
            raise ClassificationError(f"classificazione: sezione mancante: {key}")
    return doc


def _compiled_rules(doc: dict[str, Any]) -> list[tuple[str, re.Pattern[str], str]]:
    rules: list[tuple[str, re.Pattern[str], str]] = []
    for row in doc["forbidden_in_tar"]:
        rules.append((row["name"], re.compile(row["pattern"]), row.get("severity", "high")))
    return rules


def scan_members(members: list[str], path: str | Path | None = None) -> list[DriftFinding]:
    ""
    doc = load_classification(path)
    rules = _compiled_rules(doc)
    findings: list[DriftFinding] = []
    for member in members:
        for name, pat, severity in rules:
            if pat.search(member):
                findings.append(DriftFinding(member=member, rule=name, severity=severity))
    return findings


def scan_tar(tar_path: str | Path, path: str | Path | None = None) -> list[DriftFinding]:
    ""



    tp = Path(tar_path)
    if not tp.exists():
        raise ClassificationError(f"archivio assente: {tp}")
    with tarfile.open(tp, "r:*") as tf:
        names = tf.getnames()
    return scan_members(names, path)


def _main(argv: list[str] | None = None) -> int:
    import argparse
    import json

    parser = argparse.ArgumentParser(
        description="Drift report read-only: segreti/vectordb in un archivio."
    )
    parser.add_argument("tar", nargs="?", help="path dell'archivio tar/tar.gz")
    parser.add_argument("--members-file", help="file con un path per riga (invece del tar)")
    parser.add_argument("--path", default=None, help="path alternativo a data-classification.yaml")
    args = parser.parse_args(argv)

    if args.members_file:
        members = [
            ln.strip()
            for ln in Path(args.members_file).read_text(encoding="utf-8").splitlines()
            if ln.strip()
        ]
        findings = scan_members(members, args.path)
    elif args.tar:
        findings = scan_tar(args.tar, args.path)
    else:
        parser.error("serve un tar oppure --members-file")

    payload = [{"member": f.member, "rule": f.rule, "severity": f.severity} for f in findings]
    print(json.dumps(payload, ensure_ascii=False, indent=2))

    return 2 if any(f.severity == "high" for f in findings) else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
