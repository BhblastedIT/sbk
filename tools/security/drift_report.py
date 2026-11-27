"""Read-only drift report of a backup archive: lists the members that hold secrets or vector databases according
to the data classification rules.

The rules are built in (DEFAULT_CLASSIFICATION below). Pass --path to use your own YAML file with the same three
sections (classes, backup_policy, forbidden_in_tar).

Usage: uv run python tools/security/drift_report.py <archive.tar[.gz]> | --members-file FILE [--path rules.yaml]
Exit 2 when a high-severity member is found, 0 otherwise.
"""

from __future__ import annotations

import re
import sys
import tarfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

# Built-in rules: what must never sit inside a backup archive. Secrets are high (exit 2); the vector index is
# rebuilt by the pipeline (L3 Index), so it is only flagged.
DEFAULT_CLASSIFICATION: dict[str, Any] = {
    "classes": {
        "secret": "keys, tokens, passwords: they live in .env or the Keychain, never in an archive",
        "vector_db": "the search index under <data root>/l3/vectordb, rebuilt by L3 Index",
    },
    "backup_policy": {"secret": "exclude", "vector_db": "exclude"},
    "forbidden_in_tar": [
        {"name": "env_file", "pattern": r"(^|/)\.env(\.(?!example$)[^/]+)?$", "severity": "high"},
        {"name": "private_key", "pattern": r"\.(pem|key|p12|pfx)$", "severity": "high"},
        {"name": "oauth_client_secret", "pattern": r"(^|/)client_secret[^/]*\.json$", "severity": "high"},
        {"name": "credentials_file", "pattern": r"(^|/)[^/]*credentials[^/]*\.json$", "severity": "high"},
        {"name": "oauth_token_file", "pattern": r"(^|/)token[^/]*\.(json|pickle)$", "severity": "high"},
        {"name": "vector_db", "pattern": r"(^|/)vectordb/", "severity": "medium"},
    ],
}


class ClassificationError(Exception):
    ""


@dataclass(frozen=True)
class DriftFinding:
    member: str
    rule: str
    severity: str


def load_classification(path: str | Path | None = None) -> dict[str, Any]:
    if path is None:
        return DEFAULT_CLASSIFICATION
    p = Path(path)
    if not p.exists():
        raise ClassificationError(f"classification missing: {p}")
    doc = yaml.safe_load(p.read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise ClassificationError("classification: the root is not a mapping")
    for key in ("classes", "backup_policy", "forbidden_in_tar"):
        if key not in doc:
            raise ClassificationError(f"classification: missing section: {key}")
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
        raise ClassificationError(f"archive missing: {tp}")
    with tarfile.open(tp, "r:*") as tf:
        names = tf.getnames()
    return scan_members(names, path)


def _main(argv: list[str] | None = None) -> int:
    import argparse
    import json

    parser = argparse.ArgumentParser(
        description="Read-only drift report: secrets and vector databases inside an archive."
    )
    parser.add_argument("tar", nargs="?", help="path of the tar/tar.gz archive")
    parser.add_argument("--members-file", help="file with one path per line (instead of the tar)")
    parser.add_argument(
        "--path", default=None, help="your own rules YAML (default: the built-in rules)"
    )
    args = parser.parse_args(argv)

    if args.members_file:
        members = [
            ln.strip()
            for ln in Path(args.members_file).read_text(encoding="utf-8").splitlines()
            if ln.strip()
        ]
        findings = scan_members(members, args.path)
    elif args.tar:
        try:
            findings = scan_tar(args.tar, args.path)
        except ClassificationError as exc:
            print(exc, file=sys.stderr)
            return 1
    else:
        parser.error("needs a tar or --members-file")

    payload = [{"member": f.member, "rule": f.rule, "severity": f.severity} for f in findings]
    print(json.dumps(payload, ensure_ascii=False, indent=2))

    return 2 if any(f.severity == "high" for f in findings) else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
