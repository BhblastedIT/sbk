#!/usr/bin/env python3
"""Checks a data file against its contract in artifacts.yaml (columns, types, tier), read-only, and prints a JSON
report; --list shows the artifacts in the contract.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

import sbk_config  # noqa: E402

try:
    from .artifacts_contract import (
        ContractError,
        load_contract,
        load_contracts,
        validate_dataframe,
    )
except ImportError:
    from artifacts_contract import (  # type: ignore[no-redef]
        ContractError,
        load_contract,
        load_contracts,
        validate_dataframe,
    )


def _resolve_parquet(contract_path: str, override: str | None) -> Path:
    if override:
        return Path(override)
    return sbk_config.DATA_ROOT / contract_path


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate an artifact against artifacts.yaml (read-only)"
    )
    parser.add_argument("artifact_id", nargs="?", help="artifact id in the contract")
    parser.add_argument("--contract", help="path to artifacts.yaml (default: the one shipped with the package)")
    parser.add_argument("--parquet", help="override the parquet path (default: DATA_ROOT/<path>)")
    parser.add_argument("--out", help="write the JSON report here (default: stdout)")
    parser.add_argument("--list", action="store_true", help="list the artifacts in the contract")
    args = parser.parse_args(argv)

    contract_path = Path(args.contract) if args.contract else None

    if args.list:
        contracts = load_contracts(contract_path)
        for aid, c in contracts.items():
            print(f"{aid}\ttier={c.tier}\tdomain={c.domain}\tpath={c.path}")
        return 0

    if not args.artifact_id:
        parser.error("specify artifact_id or --list")

    try:
        contract = load_contract(args.artifact_id, contract_path)
    except ContractError as exc:
        print(f"CONTRACT ERROR: {exc}", file=sys.stderr)
        return 2

    parquet_path = _resolve_parquet(contract.path, args.parquet)
    report: dict = {
        "artifact_id": contract.artifact_id,
        "parquet": str(parquet_path),
        "contract": asdict(contract),
    }

    if not parquet_path.exists():
        report["ok"] = False
        report["issues"] = [f"parquet not found: {parquet_path}"]
        report["read_only"] = True
        _emit(report, args.out)
        return 1

    import pandas as pd

    df = pd.read_parquet(parquet_path)
    result = validate_dataframe(contract, df)
    report["ok"] = result.ok
    report["issues"] = result.issues
    report["checks"] = result.checks
    report["read_only"] = True

    _emit(report, args.out)
    return 0 if result.ok else 1


def _emit(report: dict, out: str | None) -> None:
    text = json.dumps(report, ensure_ascii=False, indent=2, default=str)
    if out:

        Path(out).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)


if __name__ == "__main__":
    raise SystemExit(run())
