#!/usr/bin/env python3
"""Receipts (L1): extract payment receipts from email (vendor, amount, currency, category), gated by a write guard."""

















from __future__ import annotations

import argparse
import logging
import re
import sys
from pathlib import Path

import pandas as pd

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from contracts.write_guard import check_write  # noqa: E402
from truth.receipt import Mode, Outcome, Receipt, write_receipt  # noqa: E402

import sbk_config  # noqa: E402

log = logging.getLogger("em-l1-receipts")

ARTIFACT_ID = "receipts-email"
JOB_ID = "email-l1-receipts"


RECEIPT_DOMAINS: frozenset[str] = frozenset(
    {
        "stripe.com",
        "growth.stripe.com",
        "paypal.it",
        "paypal.com",
        "e.paypal.it",
        "receipts.stripe.com",
    }
)


# Multilingual (EN/IT) subject keywords that mark a payment receipt.
_SUBJECT_HINTS = (
    "receipt",
    "ricevuta",
    "payment received",
    "payment confirmation",
    "your payment",
    "invoice paid",
    "fattura pagata",
    "order confirmation",
    "conferma ordine",
    "thanks for your payment",
    "pagamento ricevuto",
    "pagamento effettuato",
)

OUTPUT_COLUMNS: tuple[str, ...] = (
    "message_id",
    "account",
    "date",
    "vendor",
    "amount",
    "currency",
    "category",
    "subject",
    "source_domain",
)

_CURRENCY_SYMBOLS = {"€": "EUR", "$": "USD", "£": "GBP"}


_CATEGORY_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("subscription", ("subscription", "abbonamento", "renewal", "rinnovo", "monthly plan")),
    ("saas", ("stripe", "openai", "anthropic", "github", "vercel", "notion", "figma")),
    ("marketplace", ("amazon", "order", "ordine", "shipping", "spedizione")),
    ("transfer", ("paypal", "transfer", "trasferimento")),
)


def _emails_dir(root: Path | None = None) -> Path:
    base = Path(root) if root is not None else sbk_config.DATA_ROOT
    return base / "emails"


def _output_path(root: Path | None = None) -> Path:
    base = Path(root) if root is not None else sbk_config.DATA_ROOT
    return base / "finance" / "receipts.parquet"


def _addr(raw: object) -> str:
    if not isinstance(raw, str) or not raw:
        return ""
    m = re.search(r"<([^>]+)>", raw)
    return (m.group(1) if m else raw).strip().lower()


def _domain(raw: object) -> str:
    addr = _addr(raw)
    return addr.split("@")[-1] if "@" in addr else ""


def _display_name(raw: object) -> str:
    if not isinstance(raw, str) or not raw:
        return ""
    if "<" in raw:
        return raw[: raw.index("<")].strip().strip('"').strip("'")
    return ""


def _vendor(from_addr: object) -> str:
    """Vendor name: the sender display name, else the second-level domain."""
    name = _display_name(from_addr)
    if name:
        return name
    dom = _domain(from_addr)
    if dom:

        parts = dom.split(".")
        return parts[-2] if len(parts) >= 2 else dom
    return ""


def _normalize_number(tok: str) -> float | None:
    tok = tok.strip()
    if "," in tok and "." in tok:
        if tok.rfind(",") > tok.rfind("."):
            tok = tok.replace(".", "").replace(",", ".")
        else:
            tok = tok.replace(",", "")
    elif "," in tok:
        if re.search(r",\d{2}$", tok):
            tok = tok.replace(",", ".")
        else:
            tok = tok.replace(",", "")
    elif re.search(r"\.\d{3}$", tok) and not re.search(r"^\d+\.\d{1,2}$", tok):
        tok = tok.replace(".", "")
    try:
        return round(float(tok), 2)
    except ValueError:
        return None


def _parse_amount(*texts: str) -> tuple[float | None, str | None]:
    pattern = re.compile(
        r"(?P<pre>€|\$|£|EUR|USD|GBP)?\s*"
        r"(?P<num>\d{1,3}(?:[.,]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?)"
        r"\s*(?P<post>€|\$|£|EUR|USD|GBP)?",
        re.IGNORECASE,
    )
    for text in texts:
        if not isinstance(text, str) or not text:
            continue
        for m in pattern.finditer(text):
            cur = None
            for g in (m.group("pre"), m.group("post")):
                if not g:
                    continue
                cur = _CURRENCY_SYMBOLS.get(g) or (
                    g.upper() if g.upper() in _CURRENCY_SYMBOLS.values() else None
                )
                if cur:
                    break
            val = _normalize_number(m.group("num"))
            if val is not None and (cur is not None or m.group("pre") or m.group("post")):
                return val, cur
    return None, None


def _category(*texts: str) -> str:
    blob = " ".join(t for t in texts if isinstance(t, str)).lower()
    for label, kws in _CATEGORY_RULES:
        if any(k in blob for k in kws):
            return label
    return "other"


def _is_receipt(from_addr: object, subject: object) -> bool:
    dom = _domain(from_addr)
    if dom in RECEIPT_DOMAINS:
        return True
    subj = (subject or "").lower() if isinstance(subject, str) else ""
    return any(h in subj for h in _SUBJECT_HINTS)


def load_receipt_emails(
    root: Path | None = None, accounts: list[str] | None = None
) -> pd.DataFrame:
    """Load the messages that look like receipts, across the selected accounts."""
    edir = _emails_dir(root)
    frames: list[pd.DataFrame] = []
    if not edir.exists():
        return pd.DataFrame()
    acc_dirs = (
        [edir / a for a in accounts] if accounts else [d for d in edir.iterdir() if d.is_dir()]
    )
    for adir in acc_dirs:
        pq = adir / "messages.parquet"
        if not pq.exists():
            continue
        cols = ["id", "date", "from_addr", "subject", "body_text", "snippet"]
        try:
            df = pd.read_parquet(pq)
        except Exception as exc:  # noqa: BLE001
            log.warning("account %s unreadable: %s", adir.name, exc)
            continue
        for c in cols:
            if c not in df.columns:
                df[c] = None
        df = df[cols].copy()
        df["account"] = adir.name
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    allm = pd.concat(frames, ignore_index=True)
    allm["source_domain"] = allm["from_addr"].apply(_domain)
    mask = allm.apply(lambda r: _is_receipt(r["from_addr"], r["subject"]), axis=1)
    return allm[mask].reset_index(drop=True)


def build_receipts(msgs: pd.DataFrame) -> pd.DataFrame:
    """Turn receipt-like messages into the receipts table."""
    if msgs is None or len(msgs) == 0:
        return pd.DataFrame(columns=list(OUTPUT_COLUMNS))
    rows = []
    for _, row in msgs.iterrows():
        subject = row.get("subject") or ""
        body = row.get("body_text") or ""
        snippet = row.get("snippet") or ""
        amount, currency = _parse_amount(subject, snippet, body)
        rows.append(
            {
                "message_id": str(row.get("id") or ""),
                "account": row.get("account") or "",
                "date": row.get("date"),
                "vendor": _vendor(row.get("from_addr")),
                "amount": amount,
                "currency": currency,
                "category": _category(subject, snippet, body),
                "subject": subject,
                "source_domain": row.get("source_domain") or "",
            }
        )
    out = pd.DataFrame(rows, columns=list(OUTPUT_COLUMNS))
    out["date"] = pd.to_datetime(out["date"], utc=True, errors="coerce")
    out.sort_values("date", inplace=True, na_position="last")
    return out.reset_index(drop=True)


def build(
    root: Path | None = None,
    *,
    accounts: list[str] | None = None,
    contract_path: Path | None = None,
    dry_run: bool = False,
    emit_receipt: bool = False,
    caller: str = "cli",
) -> Receipt:
    """Build the receipts table end to end and return the job Receipt."""
    mode = Mode.DRY_RUN if dry_run else Mode.NORMAL
    src = load_receipt_emails(root, accounts)
    receipts = build_receipts(src)
    seen = len(src)

    if len(receipts) == 0:
        return Receipt(
            job_id=JOB_ID,
            caller=caller,
            status=Outcome.EMPTY_CONFIRMED,
            mode=mode,
            records_seen=seen,
            records_written=0,
            detail="no receipt email found",
        )

    out_path = _output_path(root)
    prev = out_path if out_path.exists() else None
    verdict = check_write(
        receipts, ARTIFACT_ID, previous_path=prev, contract_path=contract_path, dry_run=dry_run
    )
    if not verdict.ok:
        return Receipt(
            job_id=JOB_ID,
            caller=caller,
            status=Outcome.BROKEN,
            mode=mode,
            records_seen=seen,
            records_written=0,
            detail="write-guard ABORT: " + "; ".join(verdict.reasons),
        )

    if not dry_run:
        sbk_config.safe_write_parquet(receipts, out_path, index=False)

    receipt = Receipt(
        job_id=JOB_ID,
        caller=caller,
        status=Outcome.OK,
        mode=mode,
        records_seen=seen,
        records_written=len(receipts),
        detail=f"{'[dry-run] ' if dry_run else ''}{out_path}",
    )
    if emit_receipt and not dry_run:
        write_receipt(receipt, root=root)
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Receipt/payment emails -> receipts (L1, gated)."
    )
    parser.add_argument("--account", default=None, help="Only one account (default: all).")
    parser.add_argument("--dry-run", action="store_true", help="Do not write (the guard still runs).")
    parser.add_argument(
        "--emit-receipt", action="store_true", help="Write the Receipt under system/receipts."
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    accounts = [args.account] if args.account else None
    receipt = build(
        accounts=accounts, dry_run=args.dry_run, emit_receipt=args.emit_receipt, caller="cli"
    )
    log.info(
        "status=%s seen=%d written=%d %s",
        receipt.status.value,
        receipt.records_seen,
        receipt.records_written,
        receipt.detail,
    )
    return 0 if receipt.status in (Outcome.OK, Outcome.EMPTY_CONFIRMED) else 1


if __name__ == "__main__":
    raise SystemExit(main())
