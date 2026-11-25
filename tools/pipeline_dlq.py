#!/usr/bin/env python3
""
















from __future__ import annotations

import fcntl
import json
import logging
import os
import re
import sys
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from sbk_config import DATA_ROOT

log = logging.getLogger("sbk-pipeline-dlq")



FAILURE_QUEUE_FILE = Path(
    os.environ.get("SBK_CODA_FALLITI") or DATA_ROOT / "system" / "failure-queue.json"
)
MAX_RETRIES = 3
BACKOFF_BASE_SECONDS = 3600



_CAMPI_DAL_RUN = (
    ("run", "SBK_CODA_RUN"),
    ("run_app", "SBK_RUN_ID"),
    ("cartella_run", "SBK_RUN_DIR"),
    ("log", "SBK_PASSO_LOG"),
)




_PULIZIA = (
    (re.compile(r"eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]*"), "<jwt>"),
    (re.compile(r"eyJ[A-Za-z0-9_\-\.]{6,}"), "<jwt>"),
    (re.compile(r"(?i)(bearer\s+)[^\s)\"']{6,}"), r"\1<x>"),
    (re.compile(r"xox[abposr]-[A-Za-z0-9\-]+"), "<slack-token>"),
    (re.compile(r"(gh[pousr]_|github_pat_)[A-Za-z0-9_]+"), "<gh-token>"),
    (re.compile(r"sk-[A-Za-z0-9_\-]{10,}"), "<sk-key>"),
    (
        re.compile(
            r"(?i)(token|key|secret|password|cookie|authorization|api[_-]?key)(\s*[=:]\s*)([\"']?)[^\s\"',;}]{8,}"
        ),
        r"\1\2\3<x>",
    ),
    (re.compile(r"\b[A-Za-z0-9_\-]{40,}\b"), "<long>"),
)


def pulisci(testo: str) -> str:
    ""
    for rx, sost in _PULIZIA:
        testo = rx.sub(sost, testo)
    return testo


def ultime_righe(testo: str, quante: int = 5) -> str:
    ""
    righe = [r.strip() for r in (testo or "").splitlines() if r.strip()]
    return " | ".join(pulisci(r)[:300] for r in righe[-quante:])


def coda_del_log(percorso: str | Path, quante: int = 5, byte: int = 64 << 10) -> str:
    ""
    try:
        with open(percorso, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - byte))
            testo = f.read().decode("utf-8", errors="replace")
    except OSError:
        return ""
    return ultime_righe(testo, quante)


def _load_queue() -> list[dict]:
    if FAILURE_QUEUE_FILE.exists():
        try:
            return json.loads(FAILURE_QUEUE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return []


def _save_queue(queue: list[dict]) -> None:

    FAILURE_QUEUE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = FAILURE_QUEUE_FILE.with_name(f"{FAILURE_QUEUE_FILE.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(queue, indent=2, default=str), encoding="utf-8")
    os.replace(tmp, FAILURE_QUEUE_FILE)


@contextmanager
def _coda_bloccata():
    ""
    FAILURE_QUEUE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(FAILURE_QUEUE_FILE.with_name(FAILURE_QUEUE_FILE.name + ".lock"), "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def add_failure(
    script: str,
    source: str,
    stage: str = "",
    error_message: str = "",
    error_type: str = "",
    extra: dict | None = None,
) -> str:
    ""



    with _coda_bloccata():
        return _aggiungi(script, source, stage, error_message, error_type, extra)


def _aggiungi(
    script: str,
    source: str,
    stage: str,
    error_message: str,
    error_type: str,
    extra: dict | None = None,
) -> str:
    queue = _load_queue()
    failure_id = str(uuid.uuid4())[:8]
    now = datetime.now(UTC)
    next_retry = now + timedelta(seconds=BACKOFF_BASE_SECONDS)

    entry = {
        "id": failure_id,
        "script_name": script,
        "source": source,
        "stage": stage,
        "timestamp": now.isoformat(),
        "error_message": pulisci(error_message)[:2000],
        "error_type": error_type,
        "retry_count": 0,
        "max_retries": MAX_RETRIES,
        "next_retry": next_retry.isoformat(),
        "backoff_seconds": BACKOFF_BASE_SECONDS,
        "status": "pending",
    }
    for campo, var in _CAMPI_DAL_RUN:
        if os.environ.get(var):
            entry[campo] = os.environ[var]
    entry["pid"] = os.getpid()
    entry["argv"] = pulisci(" ".join([Path(sys.argv[0]).name, *sys.argv[1:]]))[:300]
    for campo, valore in (extra or {}).items():
        if valore not in (None, ""):
            entry[campo] = valore
    queue.append(entry)
    _save_queue(queue)
    log.info("DLQ: added failure %s for %s (%s)", failure_id, script, error_type)
    return failure_id


def get_pending_retries() -> list[dict]:
    ""
    queue = _load_queue()
    now = datetime.now(UTC)
    pending = []
    for entry in queue:
        if entry.get("status") != "pending":
            continue
        next_retry_str = entry.get("next_retry", "")
        if not next_retry_str:
            continue
        try:
            next_retry = datetime.fromisoformat(next_retry_str)
            if next_retry.tzinfo is None:
                next_retry = next_retry.replace(tzinfo=UTC)
            if next_retry <= now:
                pending.append(entry)
        except (ValueError, TypeError):
            continue
    return pending


def record_retry(failure_id: str, success: bool) -> bool:
    ""








    with _coda_bloccata():
        return _riprova(failure_id, success)


def _riprova(failure_id: str, success: bool) -> bool:
    queue = _load_queue()
    for entry in queue:
        if entry.get("id") != failure_id:
            continue

        if success:
            entry["status"] = "resolved"
            entry["resolved_at"] = datetime.now(UTC).isoformat()
            log.info("DLQ: %s resolved after retry", failure_id)
        else:
            entry["retry_count"] = entry.get("retry_count", 0) + 1
            if entry["retry_count"] >= entry.get("max_retries", MAX_RETRIES):
                entry["status"] = "failed_permanent"
                log.warning(
                    "DLQ: %s permanently failed after %d retries",
                    failure_id,
                    entry["retry_count"],
                )
            else:

                backoff = BACKOFF_BASE_SECONDS * (2 ** entry["retry_count"])
                entry["backoff_seconds"] = backoff
                entry["next_retry"] = (datetime.now(UTC) + timedelta(seconds=backoff)).isoformat()
                entry["status"] = "pending"
                log.info(
                    "DLQ: %s retry %d failed, next in %ds",
                    failure_id,
                    entry["retry_count"],
                    backoff,
                )

        _save_queue(queue)
        return True

    log.warning("DLQ: failure %s not found", failure_id)
    return False


def mark_resolved(failure_id: str, note: str = "") -> bool:
    ""
    with _coda_bloccata():
        queue = _load_queue()
        for entry in queue:
            if entry.get("id") == failure_id:
                _chiudi(entry, note)
                _save_queue(queue)
                log.info("DLQ: %s resolved%s", failure_id, f" ({note})" if note else "")
                return True
    return False


def _chiudi(entry: dict, note: str) -> None:

    entry["stato_prima"] = entry.get("status")
    entry["status"] = "resolved"
    entry["resolved_at"] = datetime.now(UTC).isoformat()
    if note:
        entry["resolution_note"] = note[:500]





NON_SI_CHIUDONO_DA_SOLE = frozenset({"gate_conio"})



_CHIAVE_RIFIUTATA = re.compile(
    r"Authentication failed \(401\)|invalid x-api-key|Permission denied \(403\)"
)


def si_chiude_da_sola(entry: dict) -> bool:
    ""





    if entry.get("solo_a_mano"):
        return False
    return entry.get("error_type") not in NON_SI_CHIUDONO_DA_SOLE and not _CHIAVE_RIFIUTATA.search(
        str(entry.get("error_message") or "")
    )


def chiudi_superate(nomi: set[str] | list[str], nota: str, prima_di: str | None = None) -> int:
    ""






    nomi = set(nomi)
    with _coda_bloccata():
        queue = _load_queue()
        chiuse = 0
        for entry in queue:
            if entry.get("status") == "resolved" or entry.get("script_name") not in nomi:
                continue
            if not si_chiude_da_sola(entry):
                continue
            if prima_di and str(entry.get("timestamp") or "") >= prima_di:
                continue
            _chiudi(entry, nota)
            chiuse += 1
        if chiuse:
            _save_queue(queue)
            log.info("DLQ: %d entries closed for %s (%s)", chiuse, ", ".join(sorted(nomi)), nota)
    return chiuse


def get_failure(failure_id: str) -> dict | None:
    ""
    queue = _load_queue()
    for entry in queue:
        if entry.get("id") == failure_id:
            return entry
    return None


def get_all_failures(include_resolved: bool = False) -> list[dict]:
    ""
    queue = _load_queue()
    if include_resolved:
        return queue
    return [e for e in queue if e.get("status") not in ("resolved",)]


def clear_resolved() -> int:
    ""
    with _coda_bloccata():
        queue = _load_queue()
        before = len(queue)
        queue = [e for e in queue if e.get("status") != "resolved"]
        _save_queue(queue)
    removed = before - len(queue)
    if removed:
        log.info("DLQ: cleared %d resolved entries", removed)
    return removed


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    import argparse

    parser = argparse.ArgumentParser(description="SBK Pipeline DLQ")
    parser.add_argument("--list", action="store_true", help="List all failures")
    parser.add_argument("--list-all", action="store_true", help="List all including resolved")
    parser.add_argument("--pending", action="store_true", help="List pending retries")
    parser.add_argument("--resolve", metavar="ID", help="Manually resolve a failure (with --nota)")
    parser.add_argument("--nota", help="who closes and why: required with --resolve")
    parser.add_argument("--clear", action="store_true", help="Clear resolved entries")
    parser.add_argument("--test-add", action="store_true", help="Add a test failure")
    args = parser.parse_args()

    if args.list or args.list_all:
        failures = get_all_failures(include_resolved=args.list_all)
        if not failures:
            print("No failures in queue.")

        for f in failures:
            print(
                f"  [{f['status']:18s}] {f['id']} | {str(f.get('timestamp', ''))[:19]}Z"
                f" | {f['script_name']} | {f.get('error_type', '')}"
                f" | {str(f.get('error_message', ''))[:120]}"
                + (f" | run {f['run']}" if f.get("run") else "")
                + (f" | closed: {f['resolution_note'][:80]}" if f.get("resolution_note") else "")
            )
    elif args.pending:
        pending = get_pending_retries()
        if not pending:
            print("No pending retries.")
        for f in pending:
            print(f"  {f['id']} | {f['script_name']} | retry={f['retry_count']}/{f['max_retries']}")
    elif args.resolve:
        if not args.nota:
            parser.error("--resolve needs --nota: who closes the entry and why")
        ok = mark_resolved(args.resolve, note=args.nota)
        print(f"Resolved: {ok}")
    elif args.clear:
        n = clear_resolved()
        print(f"Cleared {n} resolved entries.")
    elif args.test_add:
        fid = add_failure("test/test-script.py", "test", "l0", "Test error message", "TestError")
        print(f"Added test failure: {fid}")
    else:
        parser.print_help()
