""







from __future__ import annotations

import ast
import json
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "Finding",
    "build_baseline",
    "check_manifest_cli_contract",
    "find_dry_run_guard_bypass",
    "find_parquet_writes",
    "find_subprocess_usage",
    "load_baseline",
    "new_violations",
    "scan_tree",
    "stale_allowances",
]


_ALLOW: dict[str, tuple[str, ...]] = {

    "subprocess": ("registry/launch.py",),

    "parquet_write": ("sbk_config.py",),
}

_PARQUET_WRITE_ATTRS = frozenset({"to_parquet", "write_table", "write_to_dataset", "write_parquet"})
_OS_SPAWN_ATTRS = frozenset({"system", "popen", "execv", "execve", "spawnv", "spawnl"})
_SUBPROCESS_CALLABLES = frozenset(
    {"run", "Popen", "call", "check_call", "check_output", "getoutput", "getstatusoutput"}
)
_DEFAULT_GUARD_NAMES = ("check_write", "guard_zero_suspicious", "mark_if_healthy", "write_receipt")


@dataclass(frozen=True)
class Finding:
    check: str
    file: str
    line: int
    detail: str





def find_subprocess_usage(tree: ast.AST) -> list[tuple[int, str]]:
    ""
    subprocess_names: set[str] = set()
    imported_callables: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "subprocess":
                    subprocess_names.add(alias.asname or "subprocess")
        elif isinstance(node, ast.ImportFrom) and node.module == "subprocess":
            for alias in node.names:
                imported_callables.add(alias.asname or alias.name)

    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute):
            val = func.value
            if isinstance(val, ast.Name):
                if val.id in subprocess_names and func.attr in _SUBPROCESS_CALLABLES:
                    out.append((node.lineno, f"{val.id}.{func.attr}()"))
                elif val.id == "os" and func.attr in _OS_SPAWN_ATTRS:
                    out.append((node.lineno, f"os.{func.attr}()"))
        elif isinstance(func, ast.Name) and func.id in imported_callables:
            out.append((node.lineno, f"{func.id}() (from subprocess)"))
    return out


def find_parquet_writes(tree: ast.AST) -> list[tuple[int, str]]:
    ""
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in _PARQUET_WRITE_ATTRS:
                out.append((node.lineno, f".{node.func.attr}()"))
    return out


def _test_mentions_dry_run(test: ast.AST) -> bool:
    for n in ast.walk(test):
        if isinstance(n, ast.Name) and n.id == "dry_run":
            return True
        if isinstance(n, ast.Attribute) and n.attr == "dry_run":
            return True
    return False


def find_dry_run_guard_bypass(
    tree: ast.AST, guard_names: tuple[str, ...] = _DEFAULT_GUARD_NAMES
) -> list[tuple[int, str]]:
    ""




    out: list[tuple[int, str]] = []
    guard_set = set(guard_names)

    for fn in ast.walk(tree):
        if not isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef):
            continue

        dry_return_line: int | None = None
        for node in ast.walk(fn):
            if isinstance(node, ast.If) and _test_mentions_dry_run(node.test):
                for stmt in node.body:
                    for sub in ast.walk(stmt):
                        if isinstance(sub, ast.Return | ast.Raise):
                            if dry_return_line is None or node.lineno < dry_return_line:
                                dry_return_line = node.lineno
                            break
        if dry_return_line is None:
            continue

        for node in ast.walk(fn):
            if isinstance(node, ast.Call):
                name = None
                if isinstance(node.func, ast.Name):
                    name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    name = node.func.attr
                if name in guard_set and node.lineno > dry_return_line:
                    out.append(
                        (
                            node.lineno,
                            f"guard {name}() dopo early-return dry_run@{dry_return_line} "
                            f"in {fn.name}()",
                        )
                    )
    return out





def _relpath(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _is_allowed(check: str, relpath: str) -> bool:
    return any(relpath.endswith(suf) for suf in _ALLOW.get(check, ()))


def scan_tree(
    root: str | Path,
    *,
    guard_names: tuple[str, ...] = _DEFAULT_GUARD_NAMES,
) -> dict[str, dict[str, int]]:
    ""




    root = Path(root)
    result: dict[str, dict[str, int]] = {
        "subprocess": {},
        "parquet_write": {},
        "dry_run_guard_bypass": {},
    }
    _excluded = {
        "__pycache__",
        ".venv",
        "venv",
        "site-packages",
        "node_modules",
        ".git",
        ".ruff_cache",
        ".mypy_cache",
        ".pytest_cache",
        "build",
        "dist",



        "_deprecated",
    }
    for path in sorted(root.rglob("*.py")):
        if any(part in _excluded for part in path.parts):
            continue
        rel = _relpath(path, root)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (SyntaxError, OSError):
            continue

        sp = find_subprocess_usage(tree)
        if sp and not _is_allowed("subprocess", rel):
            result["subprocess"][rel] = len(sp)

        pq = find_parquet_writes(tree)
        if pq and not _is_allowed("parquet_write", rel):
            result["parquet_write"][rel] = len(pq)

        dr = find_dry_run_guard_bypass(tree, guard_names=guard_names)
        if dr:
            result["dry_run_guard_bypass"][rel] = len(dr)

    return result


def build_baseline(root: str | Path) -> dict[str, dict[str, int]]:
    ""
    return scan_tree(root)


def load_baseline(path: str | Path) -> dict[str, dict[str, int]]:
    p = Path(path)
    if not p.exists():
        return {}
    data = json.loads(p.read_text(encoding="utf-8"))
    return data.get("counts", data) if isinstance(data, dict) else {}


def new_violations(
    current: dict[str, dict[str, int]],
    baseline: dict[str, dict[str, int]],
) -> dict[str, dict[str, dict[str, int]]]:
    ""
    out: dict[str, dict[str, dict[str, int]]] = {}
    for check, files in current.items():
        base = baseline.get(check, {})
        for rel, count in files.items():
            base_count = base.get(rel, 0)
            if count > base_count:
                out.setdefault(check, {})[rel] = {"baseline": base_count, "current": count}
    return out


def stale_allowances(
    current: dict[str, dict[str, int]],
    baseline: dict[str, dict[str, int]],
) -> dict[str, dict[str, dict[str, int]]]:
    ""























    out: dict[str, dict[str, dict[str, int]]] = {}
    for check, files in baseline.items():
        adesso = current.get(check, {})
        for rel, dichiarato in files.items():
            if not isinstance(dichiarato, int) or dichiarato <= 0:
                continue
            vero = adesso.get(rel, 0)
            if vero < dichiarato:
                out.setdefault(check, {})[rel] = {"baseline": dichiarato, "current": vero}
    return out





def check_manifest_cli_contract(manifests_dir: str | Path) -> list[Finding]:
    ""









    import yaml

    d = Path(manifests_dir)
    if not d.exists():
        return []
    findings: list[Finding] = []
    for f in sorted(d.glob("*.yaml")):
        try:
            doc = yaml.safe_load(f.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            findings.append(Finding("manifest_cli", str(f), 1, f"illeggibile: {exc}"))
            continue
        if not isinstance(doc, dict):
            continue

        if "external" in doc:
            continue
        if doc.get("owner") == "other-project" or doc.get("owner_area") == "other-project":
            continue

        exec_block = doc.get("exec", doc)
        if "cmd" not in exec_block:
            findings.append(Finding("manifest_cli", str(f), 1, "campo exec mancante: cmd"))
        args = exec_block.get("args")
        if args is not None and not isinstance(args, list):
            findings.append(
                Finding("manifest_cli", str(f), 1, "campo 'args' deve essere una lista")
            )
    return findings
