#!/usr/bin/env python3
"""Download document attachments of every mailbox into <mailbox>/allegati/<year>/ and keep a per-mailbox index (indice.parquet)."""























from __future__ import annotations

import argparse
import base64
import json
import logging
import os
import re
import sys
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

_TOOLS = Path(__file__).resolve().parent.parent
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

import google_oauth  # noqa: E402

from sbk_config import EMAILS_DIR, mark_last_run, safe_write_parquet  # noqa: E402

log = logging.getLogger("em-l0-allegati")

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

DOCUMENT_EXTS = frozenset({
    "pdf", "doc", "docx", "xls", "xlsx", "xlsm", "ppt", "pptx", "csv", "txt", "rtf", "odt", "ods", "odp", "md",
    "eml", "msg", "p7m", "p7s", "xml", "json", "html", "htm", "ics", "numbers", "pages", "key",
})

MAX_BYTES = 25 * 1024 * 1024

SAVE_EVERY = 200
WORKERS = 6

CLOSED_STATES = frozenset({"scaricato", "riusato", "doppione", "troppo_grande", "sparito"})


def extension(nome: str) -> str:
    """Lower-case file extension of a file name (empty if none)."""
    nome = (nome or "").lower().strip()
    return nome.rsplit(".", 1)[-1] if "." in nome else ""


def safe_name(nome: str) -> str:
    pulito = re.sub(r"[^\w.\- ]+", "_", nome or "allegato").strip(" .") or "allegato"
    return pulito[:150]


def make_key(msg_id: str, nome: str, byte: int) -> str:
    return f"{msg_id}|{nome}|{int(byte)}"


def mailbox_documents(folder: Path) -> list[dict]:
    """Document attachments (by extension) referenced by the messages of a mailbox."""
    import pyarrow.parquet as pq

    out = []
    for block in pq.ParquetFile(folder / "messages.parquet").iter_batches(
        batch_size=5000, columns=["id", "date", "attachments_json"]
    ):
        for msg_id, data, aj in zip(*block.to_pydict().values(), strict=True):
            if not aj:
                continue
            try:
                attachments = json.loads(aj)
            except (ValueError, TypeError):
                continue
            seen = set()
            for a in attachments or []:
                nome = a.get("filename") or ""
                byte = int(a.get("size") or 0)
                if extension(nome) not in DOCUMENT_EXTS or (nome, byte) in seen:
                    continue
                seen.add((nome, byte))
                out.append(
                    {
                        "msg_id": str(msg_id),
                        "data": data,
                        "nome": nome,
                        "byte": byte,
                        "mime": a.get("mime_type") or "",
                        "attachment_id": a.get("attachment_id") or "",
                    }
                )
    return out


def legacy_files(folder: Path) -> dict[tuple[str, int], str]:
    """Files already on disk from older runs, keyed by (name, size)."""
    root = folder / "attachments"
    out: dict[tuple[str, int], str] = {}
    if not root.exists():
        return out
    for p in root.rglob("*"):
        if not p.is_file() or p.name == "index.parquet":
            continue
        nome = p.name.split("_", 1)[1] if re.match(r"\d{8}_", p.name) else p.name
        out.setdefault((nome, p.stat().st_size), str(p))
    return out


def read_index(percorso: Path) -> pd.DataFrame:
    if not percorso.exists():
        return pd.DataFrame()
    return pd.read_parquet(percorso)


def _service(label: str):
    """Gmail client of one mailbox, from its own login (Keychain sbk-gmail/<label>)."""
    return google_oauth.gmail_service(label)


def _data(svc, msg_id: str, att_id: str) -> bytes:
    r = svc.users().messages().attachments().get(userId="me", messageId=msg_id, id=att_id).execute()
    payload = r.get("data", "")
    return base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))


def _fresh_id(svc, msg_id: str, nome: str, byte: int) -> str:
    """Re-read the message to get a current attachment id when the stored one has expired."""
    msg = svc.users().messages().get(userId="me", id=msg_id, format="full").execute()
    stack = [msg.get("payload") or {}]
    while stack:
        part = stack.pop()
        stack.extend(part.get("parts") or [])
        body = part.get("body") or {}
        if (
            part.get("filename") == nome
            and int(body.get("size") or 0) == byte
            and body.get("attachmentId")
        ):
            return body["attachmentId"]
    return ""


def _from_source(svc, msg_id: str, nome: str) -> bytes | None:
    """Extract an attachment from the raw RFC 822 message (fallback when no attachment id works)."""
    import email
    from email import policy

    r = svc.users().messages().get(userId="me", id=msg_id, format="raw").execute()
    raw_bytes = base64.urlsafe_b64decode(r["raw"] + "=" * (-len(r["raw"]) % 4))
    for part in email.message_from_bytes(raw_bytes, policy=policy.default).walk():
        if part.get_filename() != nome:
            continue
        if part.get_content_type() == "message/rfc822":
            inner = part.get_payload()
            inner = inner[0] if isinstance(inner, list) else inner
            return (
                inner.as_bytes() if hasattr(inner, "as_bytes") else bytes(str(inner), "utf-8")
            )
        return part.get_payload(decode=True) or b""
    return None


def download_one(svc, row: dict, folder: Path) -> dict:
    """Download one attachment and return its index row (status downloaded/vanished/error)."""

    from googleapiclient.errors import HttpError

    year = str(row["data"])[:4] if row.get("data") is not None else "no-date"
    dest = folder / "allegati" / year / f"{row['msg_id']}__{safe_name(row['nome'])}"
    result = {k: row[k] for k in ("msg_id", "data", "nome", "byte", "mime")}
    result.update(
        chiave=make_key(row["msg_id"], row["nome"], row["byte"]), percorso=str(dest), motivo=""
    )
    for attempt in range(4):
        try:
            if not row.get("attachment_id") or row.get("mime") == "message/rfc822":
                payload = _from_source(svc, row["msg_id"], row["nome"])
            else:
                try:
                    payload = _data(svc, row["msg_id"], row["attachment_id"])
                except HttpError as e:
                    if int(getattr(e.resp, "status", 0) or 0) not in (400, 404):
                        raise
                    fresh = _fresh_id(svc, row["msg_id"], row["nome"], row["byte"])
                    payload = (
                        _data(svc, row["msg_id"], fresh)
                        if fresh
                        else _from_source(svc, row["msg_id"], row["nome"])
                    )
            if payload is None:
                return {**result, "stato": "sparito", "motivo": "attachment no longer in the message"}
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_name(dest.name + ".partial")
            tmp.write_bytes(payload)
            os.replace(tmp, dest)
            os.chmod(dest, 0o600)
            return {**result, "stato": "scaricato"}
        except HttpError as e:
            http_status = int(getattr(e.resp, "status", 0) or 0)
            if http_status == 404:
                return {**result, "stato": "sparito", "motivo": "message no longer on the server"}
            if attempt == 3 or not (http_status == 429 or 500 <= http_status < 600):
                return {**result, "stato": "errore", "motivo": f"Gmail {http_status}"}
            time.sleep(5 * 3**attempt)
        except OSError as e:
            return {**result, "stato": "errore", "motivo": type(e).__name__}
    return {**result, "stato": "errore", "motivo": "retries exhausted"}


def plan_mailbox(folder: Path) -> tuple[list[dict], list[dict]]:
    """Split work into (to download, resolved immediately without a download)."""
    index_df = read_index(folder / "allegati" / "indice.parquet")
    closed_keys = set(index_df.loc[index_df["stato"].isin(CLOSED_STATES), "chiave"]) if not index_df.empty else set()
    already = {}
    if not index_df.empty:
        for r in index_df.loc[index_df["stato"].isin({"scaricato", "riusato"})].itertuples(index=False):
            already.setdefault((r.nome, int(r.byte)), r.percorso)
    legacy = legacy_files(folder)

    queued: set[tuple[str, int]] = set()
    to_do, immediate = [], []
    for r in mailbox_documents(folder):
        k = make_key(r["msg_id"], r["nome"], r["byte"])

        same_key = (r["nome"], r["byte"]) if r["byte"] > 0 else None
        if k in closed_keys or same_key in queued:
            continue
        base = {kk: r[kk] for kk in ("msg_id", "data", "nome", "byte", "mime")}
        when = datetime.now(UTC).isoformat(timespec="seconds")
        if r["byte"] > MAX_BYTES:
            immediate.append(
                {
                    **base,
                    "chiave": k,
                    "percorso": "",
                    "stato": "troppo_grande",
                    "motivo": "",
                    "quando": when,
                }
            )
        elif same_key in already:
            immediate.append(
                {**base, "chiave": k, "percorso": already[same_key], "stato": "doppione", "motivo": "",
                 "quando": when}
            )
        elif same_key in legacy:
            p = legacy[same_key]
            already[same_key] = p
            immediate.append(
                {
                    **base,
                    "chiave": k,
                    "percorso": p,
                    "stato": "riusato",
                    "motivo": "",
                    "quando": when,
                }
            )
        else:
            if same_key:
                queued.add(same_key)
            to_do.append(r)
    return to_do, immediate


def download_mailbox(nome: str, email: str, folder: Path, dry_run: bool) -> dict:
    to_do, immediate = plan_mailbox(folder)
    total_bytes = sum(r["byte"] for r in to_do)
    counts = {
        "da_scaricare": len(to_do),
        "byte_da_scaricare": total_bytes,
        **{
            s: sum(1 for r in immediate if r["stato"] == s)
            for s in ("riusato", "doppione", "troppo_grande")
        },
    }
    log.info(f"[{nome}] to download {len(to_do)} ({total_bytes / 1e9:.2f} GB), {counts}")
    if dry_run:
        return counts
    index_path = folder / "allegati" / "indice.parquet"
    rows = immediate
    lock = threading.Lock()
    local_state = threading.local()

    def save():
        old = read_index(index_path)
        new = pd.DataFrame(rows)
        combined = pd.concat([old, new], ignore_index=True) if not old.empty else new
        combined = combined.drop_duplicates(subset=["chiave"], keep="last")
        safe_write_parquet(combined, index_path, index=False)

    def work(r):
        if getattr(local_state, "svc", None) is None:
            local_state.svc = _service(nome)
        return download_one(local_state.svc, r, folder)

    if rows:
        save()
    rows = []
    done = run_errors = 0
    queue = iter(to_do)
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        in_flight = set()
        while True:
            while len(in_flight) < WORKERS * 4:
                r = next(queue, None)
                if r is None:
                    break
                in_flight.add(pool.submit(work, r))
            if not in_flight:
                break
            finished, in_flight = wait(in_flight, return_when=FIRST_COMPLETED)
            for f in finished:
                row = f.result()
                row["quando"] = datetime.now(UTC).isoformat(timespec="seconds")
                with lock:
                    rows.append(row)
                    done += 1
                    run_errors += row["stato"] == "errore"
            if len(rows) >= SAVE_EVERY:
                save()
                rows = []
                log.info(f"[{nome}] {done}/{len(to_do)}")
    if rows:
        save()
    combined = read_index(index_path)

    counts["errori"] = run_errors
    vanished = int((combined["stato"] == "sparito").sum()) if not combined.empty else 0
    log.info(
        f"[{nome}] done: {done} downloaded or attempted, errors this run {run_errors}, vanished from Gmail {vanished}"
    )
    return counts


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--only", default="", help="comma-separated mailboxes (default: all)")
    ap.add_argument("--dry-run", action="store_true", help="how many and how big, nothing downloaded")
    args = ap.parse_args()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S"
    )

    mailboxes = json.loads((EMAILS_DIR / "accounts.json").read_text(encoding="utf-8"))
    only = {s.strip() for s in args.only.split(",") if s.strip()}
    results = {}
    for nome, payload in mailboxes.items():
        if only and nome not in only:
            continue
        folder = EMAILS_DIR / nome
        email = (payload or {}).get("email", "")
        if not (folder / "messages.parquet").exists() or not email:
            log.warning(f"[{nome}] no mail in L0 or no address: skipping")
            continue
        results[nome] = download_mailbox(nome, email, folder, args.dry_run)
    total = sum(e["byte_da_scaricare"] for e in results.values())
    log.info(
        f"Total to download: {sum(e['da_scaricare'] for e in results.values())} files, {total / 1e9:.2f} GB"
    )
    if args.dry_run:
        return 0
    errors = sum(e.get("errori", 0) for e in results.values())
    mark_last_run("email-allegati")
    return (
        1
        if errors and errors > 0.05 * max(1, sum(e["da_scaricare"] for e in results.values()))
        else 0
    )


if __name__ == "__main__":
    sys.exit(main())
