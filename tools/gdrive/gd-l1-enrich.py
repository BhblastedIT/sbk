#!/usr/bin/env python3
""
























from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sqlite3
import sys
import zlib
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))
from sbk_config import DATA_ROOT, OWN_EMAILS, safe_write_parquet



DATA_DIR = DATA_ROOT / "gdrive"
INDEX_FILE = DATA_DIR / "gdrive-index.json"
PROCESSED_DIR = DATA_DIR / "processed"

log = logging.getLogger("gdrive-enrich")


DOC_CATEGORIES = {
    "contratto": [r"contratto", r"contract", r"accordo", r"agreement"],
    "bilancio": [r"bilancio", r"bilanci", r"nota.*integrativa"],
    "fattura": [r"fattur[ae]", r"invoice", r"ricevuta", r"pop_", r"payment"],
    "statuto": [r"statuto", r"atto.*variazione", r"societ[aà].*benefit", r"visura"],
    "finance": [
        r"p&l",
        r"cash.?flow",
        r"budget",
        r"revenue",
        r"pricing",
        r"flussi",
        r"stipendi",
        r"contabilit[aà]",
        r"booking",
        r"bookkeeping",
    ],
    "legal": [
        r"affidavit",
        r"legal",
        r"avvocato",
        r"lettera.*avv",
        r"claim",
        r"dichiarazione",
    ],
    "report": [r"report", r"overview"],
    "compliance": [
        r"compliance",
        r"normativa",
        r"polizza",
        r"catastrofale",
        r"titolare.*effettivo",
    ],
    "hr": [r"forza.*lavoro", r"personio", r"org.*chart"],
    "ops": [
        r"ad.?account",
        r"google",
        r"outreach",
        r"template",
    ],
}


def classify_document(name: str, mime: str) -> str:
    ""
    name_lower = name.lower()
    for category, patterns in DOC_CATEGORIES.items():
        for pat in patterns:
            if re.search(pat, name_lower):
                return category

    if mime == "application/vnd.google-apps.spreadsheet" or name_lower.endswith(
        (".csv", ".xlsx", ".xls")
    ):
        return "spreadsheet"
    if mime == "application/vnd.google-apps.document" or name_lower.endswith(
        (".doc", ".docx", ".md")
    ):
        return "document"
    if name_lower.endswith(".pdf"):
        return "pdf_unclassified"
    return "other"



MAX_CHARS = 100_000






MEMORIA = PROCESSED_DIR / "testi.sqlite"

MEMORIA_PARQUET = PROCESSED_DIR / "testi.parquet"

SCHEDA = (
    "file_id",
    "modified",
    "md5",
    "percorso",
    "stato",
    "tipo",
    "lettore",
    "versione",
    "motivo",
    "letto_il",
    "caratteri",
)

TETTO_MEMORIA = 2_000_000

SCRIVI_OGNI = 200

DI_OGNI = 2000

IN_VOLO_PER_LETTORE = 4

BLOCCO_DOCUMENTI = 2000


def _percorso(local_path: str) -> Path | None:
    ""
    if not local_path:
        return None
    p = Path(local_path)

    return p if p.exists() else None


def extract_text_content(local_path: str, max_chars: int = MAX_CHARS) -> str:
    ""
    from lettura_documenti import leggi

    p = _percorso(local_path)
    return leggi(p, max_chars).testo if p else ""


def apri_memoria(*, sola_lettura: bool = False) -> sqlite3.Connection:
    ""


    if sola_lettura:
        return sqlite3.connect(f"file:{MEMORIA}?mode=ro", uri=True)
    MEMORIA.parent.mkdir(parents=True, exist_ok=True)
    nuovo = not MEMORIA.exists()
    con = sqlite3.connect(MEMORIA)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute(
        "CREATE TABLE IF NOT EXISTS testi (file_id TEXT PRIMARY KEY, modified TEXT, md5 TEXT, percorso TEXT, "
        "stato TEXT, tipo TEXT, lettore TEXT, versione TEXT, motivo TEXT, letto_il TEXT, caratteri INTEGER, "
        "testo BLOB)"
    )
    if nuovo:
        os.chmod(MEMORIA, 0o600)
    _porta_dentro_il_parquet(con)
    return con


def _riga_db(r: dict) -> tuple:
    testo = r.get("testo") or ""
    return (
        r.get("file_id", ""),
        str(r.get("modified") or ""),
        r.get("md5") or "",
        r.get("percorso") or "",
        r.get("stato") or "",
        r.get("tipo") or "",
        r.get("lettore") or "",
        str(r.get("versione") or ""),
        r.get("motivo") or "",
        r.get("letto_il") or "",
        len(testo),
        zlib.compress(testo.encode("utf-8"), 6) if testo else None,
    )


def scrivi_righe(con: sqlite3.Connection, righe: list[dict], *, sostituisci: bool = True) -> None:
    ""
    verbo = "INSERT OR REPLACE" if sostituisci else "INSERT OR IGNORE"
    con.executemany(
        f"{verbo} INTO testi VALUES ({', '.join('?' * 12)})", [_riga_db(r) for r in righe]
    )
    con.commit()


def _porta_dentro_il_parquet(con: sqlite3.Connection) -> None:
    ""

    if not MEMORIA_PARQUET.exists():
        return
    import pyarrow.parquet as pq

    portate = 0
    for blocco in pq.ParquetFile(MEMORIA_PARQUET).iter_batches(batch_size=500):
        righe = blocco.to_pylist()
        scrivi_righe(con, righe, sostituisci=False)
        portate += len(righe)
    MEMORIA_PARQUET.rename(
        MEMORIA_PARQUET.with_name(f"{MEMORIA_PARQUET.name}.portato-{datetime.now():%Y%m%d-%H%M}")
    )
    log.info(f"Text memory: {portate} rows moved from the legacy parquet into the database")


def carica_memoria(con: sqlite3.Connection) -> dict[str, dict]:
    ""
    cur = con.execute(f"SELECT {', '.join(SCHEDA)} FROM testi")
    return {r[0]: dict(zip(SCHEDA, r, strict=True)) for r in cur}


def _testo(blob: bytes | None) -> str:
    return zlib.decompress(blob).decode("utf-8") if blob else ""


def testo_di(con: sqlite3.Connection, file_id: str) -> str:
    ""
    r = con.execute("SELECT testo FROM testi WHERE file_id = ?", (file_id,)).fetchone()
    return _testo(r[0]) if r else ""


def testi_per_id(con: sqlite3.Connection, ids: list[str], max_caratteri: int) -> dict[str, str]:
    ""
    fuori: dict[str, str] = {}
    for i in range(0, len(ids), 500):
        gruppo = ids[i : i + 500]
        cur = con.execute(
            f"SELECT file_id, testo FROM testi WHERE file_id IN ({', '.join('?' * len(gruppo))})",
            gruppo,
        )
        for fid, blob in cur:
            fuori[fid] = _testo(blob)[:max_caratteri]
    return fuori


def _aggiornata(riga: dict | None, voce: dict) -> bool:
    ""

    from lettura_documenti import VERSIONI

    if not riga or str(riga.get("modified")) != str(voce.get("modifiedTime", "")):
        return False

    if riga.get("stato") == "errore":
        return False


    percorso = _percorso(voce.get("local_path", ""))
    if percorso is not None and riga.get("percorso") and str(percorso) != riga.get("percorso"):
        return False
    return riga.get("versione") == VERSIONI.get(riga.get("tipo") or "", "1")


def _leggi_uno(voce: dict, percorso: Path) -> dict:
    ""
    import hashlib

    from lettura_documenti import leggi_bytes

    dati = percorso.read_bytes()
    r = leggi_bytes(voce.get("name") or percorso.name, dati, 0, TETTO_MEMORIA)
    return {
        "file_id": voce.get("id", ""),
        "modified": str(voce.get("modifiedTime", "")),
        "md5": hashlib.md5(dati).hexdigest(),
        "percorso": str(percorso),
        "stato": r.esito,
        "tipo": r.tipo,
        "lettore": r.lettore,
        "versione": r.versione,
        "testo": r.testo,
        "motivo": r.motivo,
        "letto_il": datetime.now(UTC).isoformat(timespec="seconds"),
    }


def _scheda(riga: dict) -> dict:
    ""
    return {
        **{k: riga.get(k) for k in SCHEDA if k != "caratteri"},
        "caratteri": len(riga.get("testo") or ""),
    }


def aggiorna_memoria(
    index: list[dict], memoria: dict[str, dict], con: sqlite3.Connection, lavoratori: int = 1
) -> dict:
    ""






    from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

    try:
        from sbk_resources import pressure
    except ImportError:  # pragma: no cover - outside the repo
        pressure = None

    da_leggere = []
    for voce in index:
        if not voce.get("downloaded") or _aggiornata(memoria.get(voce.get("id", "")), voce):
            continue
        percorso = _percorso(voce.get("local_path", ""))
        if percorso is not None:
            da_leggere.append((voce, percorso))
    conti = {"da_leggere": len(da_leggere), "letti": 0, "fermato": None}
    if not da_leggere:
        return conti
    lavoratori = max(1, lavoratori)
    log.info(f"Reading: {len(da_leggere)} files to read, {lavoratori} at a time")
    coda = iter(da_leggere)
    in_volo: dict = {}
    da_scrivere: list[dict] = []

    def _prendi(futuro, voce: dict) -> None:
        try:
            riga = futuro.result()
        except Exception as e:  # noqa: BLE001 - one file that crashes the reader does not stop the others
            log.warning(f"  {voce.get('name', '?')} cannot be read: {type(e).__name__}: {e}")
            riga = {
                "file_id": voce.get("id", ""),
                "modified": str(voce.get("modifiedTime", "")),
                "percorso": voce.get("local_path", ""),
                "stato": "errore",
                "motivo": type(e).__name__,
                "letto_il": datetime.now(UTC).isoformat(timespec="seconds"),
            }
        da_scrivere.append(riga)
        memoria[riga["file_id"]] = _scheda(riga)
        conti["letti"] += 1

    with ThreadPoolExecutor(max_workers=lavoratori) as pool:
        while True:
            while len(in_volo) < lavoratori * IN_VOLO_PER_LETTORE:
                prossimo = next(coda, None)
                if prossimo is None:
                    break
                in_volo[pool.submit(_leggi_uno, *prossimo)] = prossimo[0]
            if not in_volo:
                break
            finiti, _ = wait(in_volo, return_when=FIRST_COMPLETED)
            for futuro in finiti:
                _prendi(futuro, in_volo.pop(futuro))
                if conti["letti"] % DI_OGNI == 0:
                    log.info(f"  read {conti['letti']}/{len(da_leggere)}")
                    if pressure is not None and pressure().should_abort:
                        conti["fermato"] = "machine memory under pressure"
            if len(da_scrivere) >= SCRIVI_OGNI:
                scrivi_righe(con, da_scrivere)
                da_scrivere.clear()
            if conti["fermato"]:
                for futuro in in_volo:
                    futuro.cancel()
                break

    for futuro, voce in in_volo.items():
        if futuro.done() and not futuro.cancelled():
            _prendi(futuro, voce)
    if da_scrivere:
        scrivi_righe(con, da_scrivere)
    return conti


def load_index() -> list[dict]:
    ""
    if not INDEX_FILE.exists():
        log.error(f"Index not found: {INDEX_FILE}")
        sys.exit(1)
    data = json.loads(INDEX_FILE.read_text())
    log.info(f"Loaded index: {len(data)} files")
    return data


def build_documents(
    index: list[dict], with_text: bool = True, memoria: dict[str, dict] | None = None
) -> pd.DataFrame:
    ""

    memoria = memoria if memoria is not None else {}
    rows = []
    for f in index:
        name = f.get("name", "")
        mime = f.get("mimeType", "")
        owners = f.get("owners", [])
        owner = owners[0] if owners else ""

        category = classify_document(name, mime)

        row = {
            "file_id": f.get("id", ""),
            "name": name,
            "mime_type": mime,
            "size_bytes": f.get("size", 0),
            "created": f.get("createdTime", ""),
            "modified": f.get("modifiedTime", ""),
            "owner_email": owner,
            "folder_path": f.get("folder_path", ""),
            "web_link": f.get("webViewLink", ""),
            "downloaded": f.get("downloaded", False),
            "export_format": f.get("export_format"),
            "local_path": f.get("local_path", ""),
            "skip_reason": f.get("skip_reason", ""),
            "category": category,
        }

        if with_text and f.get("downloaded"):
            riga = memoria.get(f.get("id", ""))


            row["esito_lettura"] = (riga.get("stato") or "") if riga else "non_letto"
            row["lettore"] = (riga.get("lettore") or "") if riga else ""
            row["testo_aggiornato"] = _aggiornata(riga, f)
            row["caratteri"] = min(int(riga.get("caratteri") or 0), MAX_CHARS) if riga else 0

        rows.append(row)

    df = pd.DataFrame(rows)

    for colonna in ("esito_lettura", "lettore"):
        if colonna not in df.columns:
            df[colonna] = ""
        df[colonna] = df[colonna].fillna("")
    if "caratteri" not in df.columns:
        df["caratteri"] = 0
    df["caratteri"] = df["caratteri"].fillna(0).astype(int)
    if "testo_aggiornato" not in df.columns:
        df["testo_aggiornato"] = False
    df["testo_aggiornato"] = df["testo_aggiornato"].fillna(False).astype(bool)


    for col in ["created", "modified"]:
        df[col] = pd.to_datetime(df[col], errors="coerce", utc=True)

    log.info(f"Documents: {len(df)} total, {df['downloaded'].sum()} downloaded")
    log.info(f"Categories: {df['category'].value_counts().to_dict()}")

    return df


def scrivi_documenti(docs_df: pd.DataFrame, con: sqlite3.Connection | None, percorso: Path) -> None:
    ""


    import pyarrow as pa
    import pyarrow.parquet as pq

    from sbk_config import _backup_file

    percorso.parent.mkdir(parents=True, exist_ok=True)
    tmp = percorso.with_name(percorso.name + ".tmp")

    schema = pa.Schema.from_pandas(docs_df.assign(content_text=""), preserve_index=False)
    scrittore = pq.ParquetWriter(tmp, schema, compression="zstd")
    try:
        for inizio in range(0, len(docs_df), BLOCCO_DOCUMENTI):
            blocco = docs_df.iloc[inizio : inizio + BLOCCO_DOCUMENTI].copy()
            ids = blocco.loc[blocco["caratteri"] > 0, "file_id"].tolist() if con is not None else []
            testi = testi_per_id(con, ids, MAX_CHARS) if ids else {}
            blocco["content_text"] = blocco["file_id"].map(testi).fillna("")
            scrittore.write_table(pa.Table.from_pandas(blocco, schema=schema, preserve_index=False))
        scrittore.close()
        scrittore = None
        if percorso.exists():
            _backup_file(percorso, keep=3)
        os.replace(tmp, percorso)
        os.chmod(percorso, 0o600)
    finally:
        if scrittore is not None:
            scrittore.close()
        tmp.unlink(missing_ok=True)


def build_contacts(docs_df: pd.DataFrame) -> pd.DataFrame:
    ""
    if docs_df.empty:
        return pd.DataFrame()

    owner_stats = (
        docs_df.groupby("owner_email")
        .agg(
            doc_count=("file_id", "count"),
            doc_downloaded=("downloaded", "sum"),
            categories=("category", lambda x: list(x.unique())),
            first_doc=("created", "min"),
            last_doc=("modified", "max"),
            total_size=("size_bytes", "sum"),
        )
        .reset_index()
    )

    owner_stats = owner_stats.rename(columns={"owner_email": "email"})
    owner_stats = owner_stats[owner_stats["email"] != ""]
    owner_stats["source"] = "gdrive"


    owner_stats["name"] = owner_stats["email"].apply(
        lambda e: e.split("@")[0].replace(".", " ").replace("-", " ").title() if e else ""
    )

    log.info(f"Contacts: {len(owner_stats)} unique owners")
    return owner_stats


def build_interactions(docs_df: pd.DataFrame) -> pd.DataFrame:
    ""


    # your own mailboxes (sbk.config.json "own_emails"), to skip your own documents
    my_emails = set(OWN_EMAILS)
    my_primary = sorted(my_emails)[0] if my_emails else "owner"

    interactions = defaultdict(lambda: {"doc_count": 0, "categories": set(), "last_date": None})

    for _, row in docs_df.iterrows():
        owner = row["owner_email"]
        if not owner or owner in my_emails:
            continue


        key = (owner, my_primary)
        interactions[key]["doc_count"] += 1
        interactions[key]["categories"].add(row["category"])
        mod = row["modified"]
        if pd.notna(mod):
            current = interactions[key]["last_date"]
            if current is None or mod > current:
                interactions[key]["last_date"] = mod

    rows = []
    for (from_email, to_email), stats in interactions.items():
        rows.append(
            {
                "from_email": from_email,
                "to_email": to_email,
                "doc_count": stats["doc_count"],
                "categories": list(stats["categories"]),
                "last_shared": stats["last_date"],
            }
        )

    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("doc_count", ascending=False)
    log.info(f"Interactions: {len(df)} sharing pairs")
    return df


def build_summary(
    docs_df: pd.DataFrame, contacts_df: pd.DataFrame, interactions_df: pd.DataFrame
) -> dict:
    ""

    text_chars = docs_df["caratteri"]
    has_text = text_chars > 0

    summary = {
        "source": "gdrive",
        "generated": datetime.now(UTC).isoformat(),
        "total_files": len(docs_df),
        "downloaded_files": int(docs_df["downloaded"].sum()),
        "skipped_files": int((~docs_df["downloaded"]).sum()),
        "total_size_mb": round(docs_df["size_bytes"].sum() / 1024 / 1024, 1),
        "unique_owners": len(contacts_df),
        "sharing_pairs": len(interactions_df),
        "categories": docs_df["category"].value_counts().to_dict(),
        "mime_types": docs_df["mime_type"].value_counts().to_dict(),
        "date_range": {
            "earliest": str(docs_df["created"].min()) if docs_df["created"].notna().any() else None,
            "latest": str(docs_df["modified"].max()) if docs_df["modified"].notna().any() else None,
        },
        "text_extraction": {
            "esiti": docs_df["esito_lettura"].value_counts().to_dict(),
            "files_with_text": int(has_text.sum()),
            "total_text_chars": int(text_chars.sum()),
            "avg_text_chars": int(text_chars[has_text].mean()) if has_text.any() else 0,
        },
    }
    return summary


def main():
    parser = argparse.ArgumentParser(description="Google Drive L1 enrichment — SBK")
    parser.add_argument("--dry-run", action="store_true", help="Show stats without writing files")
    parser.add_argument(
        "--no-text", action="store_true", help="Disable text extraction from downloaded files"
    )
    parser.add_argument(
        "--with-text", action="store_true", help="Extract text content (default, kept for compat)"
    )
    parser.add_argument("--incremental", action="store_true", help="Skip if inputs unchanged")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    if args.incremental:
        from sbk_config import check_inputs_changed

        if not check_inputs_changed("gdrive-l1", [INDEX_FILE]):
            log.info("Incremental: inputs unchanged — skipping")
            from sbk_config import mark_last_run

            mark_last_run("gdrive-l1")
            return

    with_text = not args.no_text


    index = load_index()


    if args.dry_run:
        con = apri_memoria(sola_lettura=True) if MEMORIA.exists() else None
    else:
        con = apri_memoria()
    memoria = carica_memoria(con) if con is not None else {}
    giro = {"da_leggere": 0, "letti": 0, "fermato": None}
    if with_text and not args.dry_run:
        try:
            from sbk_resources import cpu_workers

            lavoratori = cpu_workers()
        except ImportError:  # pragma: no cover
            lavoratori = 2
        giro = aggiorna_memoria(index, memoria, con, lavoratori)
        log.info(f"Text memory: {len(memoria)} files, read in this run {giro['letti']}")


    docs_df = build_documents(index, with_text=with_text, memoria=memoria)
    contacts_df = build_contacts(docs_df)
    interactions_df = build_interactions(docs_df)
    summary = build_summary(docs_df, contacts_df, interactions_df)
    summary["memoria"] = {"file": len(memoria), **giro}


    ts = summary["text_extraction"]
    log.info(
        f"Text extraction: {ts['files_with_text']}/{len(docs_df)} files, "
        f"{ts['total_text_chars']:,} total chars, avg {ts['avg_text_chars']:,} chars/file"
    )

    if args.dry_run:
        log.info("DRY RUN — stats only")
        log.info(json.dumps(summary, indent=2, default=str))
        if con is not None:
            con.close()
        return


    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    scrivi_documenti(docs_df, con if with_text else None, PROCESSED_DIR / "documents.parquet")
    log.info(f"Wrote documents.parquet ({len(docs_df)} rows)")
    if con is not None:
        con.close()

    safe_write_parquet(contacts_df, PROCESSED_DIR / "contacts-gdrive.parquet", index=False)
    log.info(f"Wrote contacts-gdrive.parquet ({len(contacts_df)} rows)")

    if not interactions_df.empty:
        safe_write_parquet(
            interactions_df, PROCESSED_DIR / "interactions-gdrive.parquet", index=False
        )
        log.info(f"Wrote interactions-gdrive.parquet ({len(interactions_df)} rows)")

    (PROCESSED_DIR / "_gdrive_summary.json").write_text(json.dumps(summary, indent=2, default=str))
    log.info("Wrote _gdrive_summary.json")

    from sbk_config import mark_last_run, save_input_checkpoint

    if giro["fermato"]:

        log.error(
            f"Reading stopped ({giro['fermato']}): {giro['letti']}/{giro['da_leggere']}, will resume"
        )
        sys.exit(75)
    save_input_checkpoint("gdrive-l1", [INDEX_FILE])
    mark_last_run("gdrive-l1")

    log.info("\nDone. L1 enrichment complete for Google Drive.")
    log.info(f"  {len(docs_df)} documents classified")
    log.info(f"  {len(contacts_df)} unique owners")
    log.info(f"  {len(interactions_df)} sharing interactions")


from pipeline_decorator import pipeline_step


@pipeline_step(name="l1-gdrive-enrich", source="gdrive-l1", stage="l1", mark_run=False)
def _pipeline_run():
    main()


if __name__ == "__main__":
    _pipeline_run()
