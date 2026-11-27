#!/usr/bin/env python3
"""Read the text of downloaded mail attachments (L1) into a text memory and write a per-attachment output parquet."""














from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

_TOOLS = Path(__file__).resolve().parent.parent
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

import memoria_testi as M  # noqa: E402

from sbk_config import EMAILS_DIR, mark_last_run  # noqa: E402

log = logging.getLogger("em-l1-allegati")

MEMORY_DB = EMAILS_DIR / "processed" / "allegati-testi.sqlite"

OUTPUT = EMAILS_DIR / "processed" / "allegati-posta.parquet"

MEMORY_CAP = 2_000_000
MAX_CHARS = 100_000
WRITE_EVERY = 200
IN_FLIGHT_PER_READER = 4
BLOCK_ROWS = 2000
READABLE_STATES = frozenset({"scaricato", "riusato", "doppione"})


def index_paths() -> list[Path]:
    accounts = EMAILS_DIR / "accounts.json"
    if not accounts.is_file():
        return []
    mailboxes = json.loads(accounts.read_text(encoding="utf-8"))
    return [
        EMAILS_DIR / c / "allegati" / "indice.parquet"
        for c in mailboxes
        if (EMAILS_DIR / c / "allegati" / "indice.parquet").exists()
    ]


def attachments() -> pd.DataFrame:
    """All readable attachments of all mailboxes joined with their message headers."""
    frames = []
    for p in index_paths():
        mailbox = p.parent.parent.name
        df = pd.read_parquet(p)
        df = df[df["stato"].isin(READABLE_STATES) & (df["percorso"].fillna("") != "")].copy()
        if df.empty:
            continue
        df["casella"] = mailbox
        mail = pd.read_parquet(
            EMAILS_DIR / mailbox / "messages.parquet", columns=["id", "from_addr", "subject"]
        ).rename(columns={"id": "msg_id"})
        frames.append(df.merge(mail.drop_duplicates("msg_id"), on="msg_id", how="left"))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def signature(p: Path) -> str:
    """Cheap change signature of a file (size + mtime)."""
    st = p.stat()
    return f"{st.st_size}:{st.st_mtime_ns}"


def _read_one(path: str) -> dict:
    from lettura_documenti import leggi_bytes

    p = Path(path)
    payload = p.read_bytes()
    r = leggi_bytes(p.name, payload, 0, MEMORY_CAP)
    return {
        "chiave": path,
        "modified": signature(p),
        "md5": hashlib.md5(payload).hexdigest(),
        "percorso": path,
        "stato": r.esito,
        "tipo": r.tipo,
        "lettore": r.lettore,
        "versione": r.versione,
        "testo": r.testo,
        "motivo": r.motivo,
        "letto_il": datetime.now(UTC).isoformat(timespec="seconds"),
    }


def to_read(paths: list[str], schede: dict[str, dict]) -> list[str]:
    """Paths that are new, failed before, changed on disk or read with an outdated reader version."""
    from lettura_documenti import VERSIONI

    out = []
    for p in paths:
        if not os.path.exists(p):
            continue
        s = schede.get(p)
        if (
            s is None
            or s.get("stato") == "errore"
            or s.get("modified") != signature(Path(p))
            or s.get("versione") != VERSIONI.get(s.get("tipo") or "", "1")
        ):
            out.append(p)
    return out


def update_memory(con, paths: list[str], schede: dict[str, dict], workers: int) -> int:
    """Read the given files in parallel and store the results in the text memory."""
    queue = iter(paths)
    in_flight: dict = {}
    rows: list[dict] = []
    read_count = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        while True:
            while len(in_flight) < workers * IN_FLIGHT_PER_READER:
                p = next(queue, None)
                if p is None:
                    break
                in_flight[pool.submit(_read_one, p)] = p
            if not in_flight:
                break
            finished, _ = wait(in_flight, return_when=FIRST_COMPLETED)
            for f in finished:
                p = in_flight.pop(f)
                try:
                    row = f.result()
                except Exception as e:  # noqa: BLE001 - one file crashing the reader must not stop the others
                    row = {
                        "chiave": p,
                        "percorso": p,
                        "stato": "errore",
                        "motivo": type(e).__name__,
                    }
                rows.append(row)
                schede[p] = M.scheda(row)
                read_count += 1
            if len(rows) >= WRITE_EVERY:
                M.scrivi(con, rows)
                rows = []
                log.info(f"  read {read_count}/{len(paths)}")
    if rows:
        M.scrivi(con, rows)
    return read_count


def write_output(df: pd.DataFrame, con, schede: dict[str, dict], path: Path) -> int:
    """Write the output parquet (attachment metadata + extracted text); return rows with text."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    df = df.copy()
    df["esito_lettura"] = df["percorso"].map(
        lambda p: (schede.get(p) or {}).get("stato") or "non_letto"
    )
    df["lettore"] = df["percorso"].map(lambda p: (schede.get(p) or {}).get("lettore") or "")
    df["caratteri"] = df["percorso"].map(
        lambda p: min(int((schede.get(p) or {}).get("caratteri") or 0), MAX_CHARS)
    )
    columns = [
        "casella", "msg_id", "data", "nome", "byte", "mime", "percorso", "from_addr", "subject",
        "esito_lettura", "lettore", "caratteri",
    ]
    df = df[[c for c in columns if c in df.columns]]
    schema = pa.Schema.from_pandas(df.assign(content_text=""), preserve_index=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    writer = pq.ParquetWriter(tmp, schema, compression="zstd")
    try:
        for i in range(0, len(df), BLOCK_ROWS):
            block = df.iloc[i : i + BLOCK_ROWS].copy()
            chiavi = sorted(set(block.loc[block["caratteri"] > 0, "percorso"]))
            texts = M.testi_per_chiave(con, chiavi, MAX_CHARS)
            block["content_text"] = block["percorso"].map(texts).fillna("")
            writer.write_table(pa.Table.from_pandas(block, schema=schema, preserve_index=False))
        writer.close()
        writer = None
        os.replace(tmp, path)
        os.chmod(path, 0o600)
    finally:
        if writer is not None:
            writer.close()
        tmp.unlink(missing_ok=True)
    return int((df["caratteri"] > 0).sum())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--incremental",
        action="store_true",
        help="skip if no mailbox index has changed",
    )
    args = ap.parse_args()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S"
    )

    if args.incremental:
        from sbk_config import check_inputs_changed

        if not check_inputs_changed("email-allegati-l1", index_paths()):
            log.info("Incremental: no attachment index changed, skipping")
            mark_last_run("email-allegati-l1")
            return 0

    df = attachments()
    if df.empty:
        log.info("No attachment downloaded yet: nothing to read")
        return 0
    con = M.apri(MEMORY_DB)
    schede = M.schede(con)
    paths = sorted(set(df["percorso"]))
    new_paths = to_read(paths, schede)
    try:
        from sbk_resources import cpu_workers

        workers = cpu_workers()
    except ImportError:  # pragma: no cover
        workers = 2
    log.info(
        f"Attachments: {len(df)} in {len(paths)} files, to read {len(new_paths)}, {workers} at a time"
    )
    update_memory(con, new_paths, schede, max(1, workers))
    with_text = write_output(df, con, schede, OUTPUT)
    con.close()
    log.info(f"Written {OUTPUT.name}: {len(df)} attachments, {with_text} with text")

    from sbk_config import save_input_checkpoint

    save_input_checkpoint("email-allegati-l1", index_paths())
    mark_last_run("email-allegati-l1")
    return 0


from pipeline_decorator import pipeline_step  # noqa: E402


@pipeline_step(name="l1-email-allegati", source="email-allegati-l1", stage="l1")
def run():

    code = main()
    if code:
        sys.exit(code)


if __name__ == "__main__":
    run()
