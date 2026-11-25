#!/usr/bin/env python3
""





















from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from text_utils import normalize_email  # noqa: E402

from sbk_config import (
    ATTIO_DIR,
    ATTIO_SECONDA_CLASSE_PARQUET,
    ATTIO_WORKSPACE_DIRS,
    ENRICHED_DIR,
    ENV_ATTIO_SECONDA_CLASSE,
    OWN_EMAILS,
    acquire_pid_lock,
    attio_seconda_classe_attiva,
    mark_last_run,
    safe_write_parquet,
)



PROCESSED_DIR = ATTIO_DIR / "processed"

log = logging.getLogger("attio-enrich")













ENV_SECONDA_CLASSE = ENV_ATTIO_SECONDA_CLASSE





SECONDA_CLASSE_PARQUET = ATTIO_SECONDA_CLASSE_PARQUET


seconda_classe_attiva = attio_seconda_classe_attiva


def _workspaces_to_read() -> dict[str, Path]:
    ""


    if ATTIO_WORKSPACE_DIRS["acme"] == ATTIO_DIR:
        return dict(ATTIO_WORKSPACE_DIRS)
    return {"acme": ATTIO_DIR}


def _across_workspaces(build, key: str | None) -> pd.DataFrame:
    ""





    global ATTIO_DIR
    original = ATTIO_DIR
    parts = []
    try:
        for ws_name, ws_dir in _workspaces_to_read().items():
            if not ws_dir.exists():
                continue
            ATTIO_DIR = ws_dir
            log.info(f"  Attio workspace: {ws_name} ({ws_dir})")
            df = build()
            if len(df):
                parts.append(df.assign(attio_workspace=ws_name))
    finally:
        ATTIO_DIR = original
    if not parts:
        return pd.DataFrame()
    out = pd.concat(parts, ignore_index=True)
    if key and key in out.columns and len(parts) > 1:


        first = parts[0]
        seen = set(first[key].fillna("").astype(str).str.strip()) - {""}
        kept = [first]
        dropped = 0
        for df in parts[1:]:
            k = df[key].fillna("").astype(str).str.strip()
            dup = k.isin(seen) & (k != "")
            dropped += int(dup.sum())
            kept.append(df[~dup])
            seen |= set(k) - {""}
        out = pd.concat(kept, ignore_index=True)
        if dropped:
            log.info(f"  {dropped} rows with {key} already present in a previous workspace")
    return out


def parse_pipe_separated(val) -> list:
    ""
    if pd.isna(val) or not isinstance(val, str) or not val.strip():
        return []
    return [v.strip() for v in val.split("|||") if v.strip()]


def useful_emails(p) -> list[str]:
    ""





    emails = parse_pipe_separated(p.get("email_addresses", ""))
    emails = [normalize_email(e) for e in emails if "@" in str(e)]
    return [e for e in emails if e and e not in OWN_EMAILS]





def build_contacts():
    ""
    log.info("Phase 1: Building contacts from Attio people...")
    t0 = time.time()

    people_path = ATTIO_DIR / "people.parquet"
    if not people_path.exists():
        log.error(f"Not found: {people_path}")
        return pd.DataFrame()

    people = pd.read_parquet(people_path)
    log.info(f"  Loaded {len(people)} people records")


    company_names = _load_company_lookup()


    notes_count = _count_notes_per_record("people")


    meeting_counts = _count_meetings_per_email()

    rows = []
    for _, p in people.iterrows():

        emails = useful_emails(p)

        if not emails:




            continue


        primary_email = emails[0]


        name = str(p.get("name", "")).strip() if pd.notna(p.get("name")) else ""


        company_uuid = str(p.get("company", "")).strip() if pd.notna(p.get("company")) else ""
        company_name = company_names.get(company_uuid, "")


        job_title = str(p.get("job_title", "")).strip() if pd.notna(p.get("job_title")) else ""


        location = (
            str(p.get("primary_location", "")).strip()
            if pd.notna(p.get("primary_location"))
            else ""
        )


        rel_score = (
            str(p.get("relationship_score", "")).strip()
            if pd.notna(p.get("relationship_score"))
            else ""
        )


        conn_strength = (
            str(p.get("strongest_connection_strength", "")).strip()
            if pd.notna(p.get("strongest_connection_strength"))
            else ""
        )
        conn_strength_num = p.get("strongest_connection_strength_legacy", 0)
        if pd.isna(conn_strength_num):
            conn_strength_num = 0


        sourcing = (
            str(p.get("sourcing_stage", "")).strip() if pd.notna(p.get("sourcing_stage")) else ""
        )


        campaigns = parse_pipe_separated(p.get("outreach_campaign", ""))


        events = parse_pipe_separated(p.get("events", ""))


        linkedin = str(p.get("linkedin", "")).strip() if pd.notna(p.get("linkedin")) else ""


        first_interaction = p.get("first_interaction")
        last_interaction = p.get("last_interaction")
        first_email = p.get("first_email_interaction")
        last_email = p.get("last_email_interaction")
        first_calendar = p.get("first_calendar_interaction")
        last_calendar = p.get("last_calendar_interaction")


        personal_context = (
            str(p.get("personal_context", "")).strip()
            if pd.notna(p.get("personal_context"))
            else ""
        )


        record_id = str(p.get("record_id", "")).strip()



        web_url = str(p.get("web_url", "")).strip() if pd.notna(p.get("web_url")) else ""


        n_notes = notes_count.get(record_id, 0)


        n_meetings = sum(meeting_counts.get(e, 0) for e in emails)


        description = (
            str(p.get("description", "")).strip() if pd.notna(p.get("description")) else ""
        )

        rows.append(
            {
                "email": primary_email,
                "all_emails": "|||".join(emails),
                "name": name,
                "company_name": company_name,
                "job_title": job_title,
                "location": location,
                "linkedin": linkedin,

                "attio_relationship_score": rel_score,
                "attio_connection_strength": conn_strength,
                "attio_connection_strength_num": round(conn_strength_num, 1),
                "attio_sourcing_stage": sourcing,
                "attio_campaigns": "|||".join(campaigns),
                "attio_events": "|||".join(events),
                "attio_personal_context": personal_context[:500],
                "attio_description": description[:500],

                "attio_notes_count": n_notes,
                "attio_meetings_count": n_meetings,

                "attio_first_interaction": first_interaction,
                "attio_last_interaction": last_interaction,
                "attio_first_email": first_email,
                "attio_last_email": last_email,
                "attio_first_calendar": first_calendar,
                "attio_last_calendar": last_calendar,

                "attio_record_id": record_id,
                "attio_web_url": web_url,
            }
        )

    df = pd.DataFrame(rows)


    if len(df) > 0:
        df["_richness"] = (
            df["attio_notes_count"]
            + df["attio_meetings_count"]
            + (df["attio_relationship_score"] != "").astype(int) * 5
            + (df["attio_personal_context"] != "").astype(int) * 3
            + (df["company_name"] != "").astype(int) * 2
        )
        df.sort_values("_richness", ascending=False, inplace=True)
        df.drop_duplicates(subset="email", keep="first", inplace=True)
        df.drop(columns=["_richness"], inplace=True)

    df.sort_values("attio_notes_count", ascending=False, inplace=True)

    elapsed = time.time() - t0
    log.info(f"  Contacts: {len(df)} unique emails in {elapsed:.1f}s")
    return df


def build_contacts_seconda_classe() -> pd.DataFrame:
    ""






































    log.info("Phase 1-bis: second-class lane (Attio people without email)...")
    t0 = time.time()

    people_path = ATTIO_DIR / "people.parquet"
    if not people_path.exists():
        log.error(f"Not found: {people_path}")
        return pd.DataFrame()

    people = pd.read_parquet(people_path)
    company_names = _load_company_lookup()
    notes_count = _count_notes_per_record("people")

    rows_sc = []
    for _, p in people.iterrows():
        if useful_emails(p):
            continue

        person_name = str(p.get("name", "")).strip() if pd.notna(p.get("name")) else ""
        record_id = str(p.get("record_id", "")).strip()
        if not record_id:
            continue

        company_uuid = str(p.get("company", "")).strip() if pd.notna(p.get("company")) else ""
        rows_sc.append(
            {
                "name": person_name,
                "company_name": company_names.get(company_uuid, ""),
                "job_title": str(p.get("job_title", "")).strip()
                if pd.notna(p.get("job_title"))
                else "",
                "linkedin": str(p.get("linkedin", "")).strip()
                if pd.notna(p.get("linkedin"))
                else "",
                "attio_record_id": record_id,
                "attio_web_url": str(p.get("web_url", "")).strip()
                if pd.notna(p.get("web_url"))
                else "",
                "attio_notes_count": notes_count.get(record_id, 0),
                "attio_relationship_score": str(p.get("relationship_score", "")).strip()
                if pd.notna(p.get("relationship_score"))
                else "",
                "attio_sourcing_stage": str(p.get("sourcing_stage", "")).strip()
                if pd.notna(p.get("sourcing_stage"))
                else "",

                "seconda_classe": True,
            }
        )

    df = pd.DataFrame(rows_sc)
    if len(df) > 0:
        df.drop_duplicates(subset="attio_record_id", keep="first", inplace=True)

    with_linkedin = int((df["linkedin"] != "").sum()) if len(df) > 0 else 0
    elapsed = time.time() - t0
    log.info(
        f"  Second class: {len(df)} people without email "
        f"({with_linkedin} with LinkedIn) in {elapsed:.1f}s"
    )
    return df


def _load_company_lookup() -> dict:
    ""
    lookup_path = ATTIO_DIR / "lookups" / "company-names.json"
    if lookup_path.exists():
        with open(lookup_path) as f:
            return json.load(f)


    comp_path = ATTIO_DIR / "companies.parquet"
    if comp_path.exists():
        comp = pd.read_parquet(comp_path)
        return {
            str(row.get("record_id", "")): str(row.get("name", ""))
            for _, row in comp.iterrows()
            if pd.notna(row.get("record_id")) and pd.notna(row.get("name"))
        }
    return {}


def _count_notes_per_record(parent_object: str) -> dict:
    ""
    notes_path = ATTIO_DIR / "notes.parquet"
    if not notes_path.exists():
        return {}

    notes = pd.read_parquet(notes_path)
    filtered = notes[notes["parent_object"] == parent_object]
    counts = filtered.groupby("parent_record_id").size().to_dict()
    log.info(f"  Notes: {len(counts)} {parent_object} with notes ({len(filtered)} total)")
    return counts


def _count_meetings_per_email() -> dict:
    ""
    meetings_path = ATTIO_DIR / "meetings.parquet"
    if not meetings_path.exists():
        return {}

    meetings = pd.read_parquet(meetings_path)
    counts = defaultdict(int)
    for _, m in meetings.iterrows():
        participants = parse_pipe_separated(m.get("participants", ""))
        for p in participants:
            email = normalize_email(p)
            if email and email not in OWN_EMAILS:
                counts[email] += 1

    log.info(f"  Meetings: {len(counts)} unique participants across {len(meetings)} meetings")
    return dict(counts)





def build_companies():
    ""
    log.info("Phase 2: Building companies from Attio...")
    t0 = time.time()

    comp_path = ATTIO_DIR / "companies.parquet"
    if not comp_path.exists():
        log.error(f"Not found: {comp_path}")
        return pd.DataFrame()

    comp = pd.read_parquet(comp_path)
    log.info(f"  Loaded {len(comp)} company records")

    notes_count = _count_notes_per_record("companies")

    rows = []
    for _, c in comp.iterrows():
        name = str(c.get("name", "")).strip() if pd.notna(c.get("name")) else ""
        if not name:
            continue

        domain = str(c.get("domains", "")).strip() if pd.notna(c.get("domains")) else ""
        # Example custom company attributes; adapt these names to your own CRM schema.
        investor_type = (
            str(c.get("investor_type", "")).strip() if pd.notna(c.get("investor_type")) else ""
        )
        thesis_fit = parse_pipe_separated(c.get("thesis_fit", ""))
        stage_fit = parse_pipe_separated(c.get("stage_fit", ""))
        geo_focus = parse_pipe_separated(c.get("geographic_focus", ""))
        tier = str(c.get("tier", "")).strip() if pd.notna(c.get("tier")) else ""
        fund_size = c.get("fund_size_aum", 0)
        if pd.isna(fund_size):
            fund_size = 0
        description = (
            str(c.get("description", "")).strip() if pd.notna(c.get("description")) else ""
        )
        record_id = str(c.get("record_id", "")).strip()

        web_url = str(c.get("web_url", "")).strip() if pd.notna(c.get("web_url")) else ""
        n_notes = notes_count.get(record_id, 0)

        rows.append(
            {
                "company_name": name,
                "domain": domain,
                "investor_type": investor_type,
                "thesis_fit": "|||".join(thesis_fit),
                "stage_fit": "|||".join(stage_fit),
                "geographic_focus": "|||".join(geo_focus),
                "tier": tier,
                "fund_size_aum": fund_size,
                "description": description[:500],
                "attio_notes_count": n_notes,
                "attio_record_id": record_id,
                "attio_web_url": web_url,
            }
        )

    df = pd.DataFrame(rows)
    df.sort_values("fund_size_aum", ascending=False, inplace=True)

    elapsed = time.time() - t0

    has_investor_type = (df["investor_type"] != "").sum() if len(df) > 0 else 0
    has_tier = (df["tier"] != "").sum() if len(df) > 0 else 0
    log.info(
        f"  Companies: {len(df)} ({has_investor_type} with investor_type, {has_tier} with tier)"
    )
    return df





def build_summary(contacts_df, companies_df):
    ""

    merged_path = ENRICHED_DIR / "contacts-merged.parquet"
    overlap = 0
    new_contacts = 0
    if merged_path.exists() and len(contacts_df) > 0:
        merged = pd.read_parquet(merged_path)
        merged_emails = set(merged["email"].str.lower())
        attio_emails = set(contacts_df["email"].str.lower())
        overlap = len(attio_emails & merged_emails)
        new_contacts = len(attio_emails - merged_emails)


    rel_dist = {}
    if len(contacts_df) > 0:
        rel_dist = contacts_df["attio_relationship_score"].value_counts().to_dict()


    conn_dist = {}
    if len(contacts_df) > 0:
        conn_dist = contacts_df["attio_connection_strength"].value_counts().to_dict()


    sourcing_dist = {}
    if len(contacts_df) > 0:
        non_empty = contacts_df[contacts_df["attio_sourcing_stage"] != ""]
        sourcing_dist = non_empty["attio_sourcing_stage"].value_counts().to_dict()


    inv_dist = {}
    if len(companies_df) > 0:
        non_empty = companies_df[companies_df["investor_type"] != ""]
        inv_dist = non_empty["investor_type"].value_counts().to_dict()

    summary = {
        "generated": datetime.now(UTC).isoformat(),
        "pipeline_version": "attio-enrich-v1",
        "contacts": {
            "total": len(contacts_df),
            "with_company": int((contacts_df["company_name"] != "").sum())
            if len(contacts_df) > 0
            else 0,
            "with_notes": int((contacts_df["attio_notes_count"] > 0).sum())
            if len(contacts_df) > 0
            else 0,
            "with_relationship_score": int((contacts_df["attio_relationship_score"] != "").sum())
            if len(contacts_df) > 0
            else 0,
            "with_sourcing_stage": int((contacts_df["attio_sourcing_stage"] != "").sum())
            if len(contacts_df) > 0
            else 0,
            "with_personal_context": int((contacts_df["attio_personal_context"] != "").sum())
            if len(contacts_df) > 0
            else 0,
            "with_linkedin": int((contacts_df["linkedin"] != "").sum())
            if len(contacts_df) > 0
            else 0,
        },
        "cross_reference": {
            "already_in_merged": overlap,
            "new_from_attio": new_contacts,
            "total_attio_emails": len(contacts_df),
        },
        "companies": {
            "total": len(companies_df),
            "with_investor_type": int((companies_df["investor_type"] != "").sum())
            if len(companies_df) > 0
            else 0,
            "with_tier": int((companies_df["tier"] != "").sum()) if len(companies_df) > 0 else 0,
            "with_fund_size": int((companies_df["fund_size_aum"] > 0).sum())
            if len(companies_df) > 0
            else 0,
        },
        "distributions": {
            "relationship_score": rel_dist,
            "connection_strength": conn_dist,
            "sourcing_stage": sourcing_dist,
            "investor_type": inv_dist,
        },
    }
    return summary





def _sha256_file(path: Path) -> str:
    ""
    import hashlib

    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _attio_input_fingerprints() -> dict[str, str]:
    ""
    fingerprints = {}
    for ws, ws_dir in _workspaces_to_read().items():
        prefix = "" if ws == "acme" else f"{ws}/"
        for name in ["people.parquet", "companies.parquet"]:
            path = ws_dir / name
            if path.exists():
                fingerprints[prefix + name] = _sha256_file(path)


        notes_dir = ws_dir / "notes"
        if notes_dir.exists():
            note_hashes = []
            for f in sorted(notes_dir.glob("*.json")):
                note_hashes.append(_sha256_file(f))
            if note_hashes:
                import hashlib

                combined = hashlib.sha256("".join(note_hashes).encode()).hexdigest()
                fingerprints[prefix + "notes"] = combined

    return fingerprints


def _load_attio_input_checkpoint() -> dict[str, str]:
    ""
    from sbk_config import L1_CHECKPOINT_DIR

    ckpt_path = L1_CHECKPOINT_DIR / "attio-input-checkpoint.json"
    if ckpt_path.exists():
        try:
            data = json.loads(ckpt_path.read_text())
            return data.get("fingerprints", {})
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_attio_input_checkpoint(fingerprints: dict[str, str]) -> None:
    ""
    from sbk_config import L1_CHECKPOINT_DIR

    L1_CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
    ckpt_path = L1_CHECKPOINT_DIR / "attio-input-checkpoint.json"
    data = {
        "source": "attio",
        "timestamp": datetime.now(UTC).isoformat(),
        "fingerprints": fingerprints,
    }
    ckpt_path.write_text(json.dumps(data, indent=2))


def _backfill_from_merged(df: pd.DataFrame) -> pd.DataFrame:
    ""
    merged_path = ENRICHED_DIR / "contacts-merged.parquet"
    if not merged_path.exists() or df.empty:
        log.info("  Backfill: contacts-merged not found, skipping")
        return df

    merged = pd.read_parquet(merged_path)
    log.info(f"  Backfill: loaded {len(merged)} merged contacts for cross-reference")


    lookup: dict[str, dict] = {}
    for _, row in merged.iterrows():
        email = str(row.get("email", "")).strip().lower()
        if not email or "@" not in email:
            continue
        lookup[email] = {
            "name": str(row.get("name", "")).strip() if pd.notna(row.get("name")) else "",
            "phone": str(row.get("phone", "")).strip() if pd.notna(row.get("phone")) else "",
            "title": str(row.get("title", row.get("headline", ""))).strip()
            if pd.notna(row.get("title", row.get("headline")))
            else "",
        }

    filled = {"name": 0, "phone": 0, "title": 0}
    for idx, row in df.iterrows():
        email = str(row.get("email", "")).strip().lower()
        info = lookup.get(email)
        if not info:
            continue
        if not row.get("name") and info["name"]:
            df.at[idx, "name"] = info["name"]
            filled["name"] += 1
        if info["phone"]:

            if "phone" not in df.columns:
                df["phone"] = ""
            if not df.at[idx, "phone"]:
                df.at[idx, "phone"] = info["phone"]
                filled["phone"] += 1
        if not row.get("job_title") and info["title"]:
            df.at[idx, "job_title"] = info["title"]
            filled["title"] += 1

    log.info(
        f"  Backfill results: +{filled['name']} names, "
        f"+{filled['phone']} phones, +{filled['title']} titles"
    )
    return df


def main():
    if not acquire_pid_lock("at-l1-enrich", logger=log):


        log.warning("Another instance is running: lock held, exit 75")
        sys.exit(75)

    parser = argparse.ArgumentParser(description="Attio CRM enrichment — SBK L1")
    parser.add_argument("--dry-run", action="store_true", help="Show stats without writing files")
    parser.add_argument(
        "--incremental",
        action="store_true",
        help="Skip if input files unchanged (SHA256 check)",
    )
    parser.add_argument(
        "--contacts-without-email",
        action="store_true",
        dest="seconda_classe",
        help=(
            "Also writes contacts-attio-noemail.parquet, the Attio people "
            "without email. OFF by default (equivalent to SBK_ATTIO_CONTACTS_WITHOUT_EMAIL=1)"
        ),
    )
    # Older Italian name, kept as a hidden alias.
    parser.add_argument(
        "--seconda-classe", action="store_true", dest="seconda_classe", help=argparse.SUPPRESS
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    if not ATTIO_DIR.exists():
        log.error(f"Attio directory not found: {ATTIO_DIR}")
        sys.exit(1)


    if args.incremental and not args.dry_run:
        current_fps = _attio_input_fingerprints()
        saved_fps = _load_attio_input_checkpoint()



        missing_seconda_classe = (
            seconda_classe_attiva(args.seconda_classe)
            and not (PROCESSED_DIR / SECONDA_CLASSE_PARQUET).exists()
        )
        if current_fps and current_fps == saved_fps and not missing_seconda_classe:
            log.info("Incremental: Attio input files unchanged — skipping enrichment")
            try:
                from event_bus import EventBus

                EventBus.emit("attio", "l1", contacts=0, companies=0, output_changed=False)
            except Exception as e:
                log.warning(f"EventBus emit failed: {e}")
            return

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)


    contacts_df = _across_workspaces(build_contacts, "email")


    contacts_df = _backfill_from_merged(contacts_df)


    seconda_classe_df = pd.DataFrame()
    if seconda_classe_attiva(args.seconda_classe):
        seconda_classe_df = _across_workspaces(build_contacts_seconda_classe, None)
    else:
        log.info("Contacts without email: lane OFF (use --contacts-without-email to enable it)")


    companies_df = _across_workspaces(build_companies, "domain")


    summary = build_summary(contacts_df, companies_df)

    if args.dry_run:
        log.info("\n=== DRY RUN ===")
        log.info(json.dumps(summary, indent=2, default=str))
    else:

        if len(contacts_df) > 0:
            out = PROCESSED_DIR / "contacts-attio.parquet"
            safe_write_parquet(contacts_df, out, index=False)
            log.info(f"Saved -> {out}")



        if len(seconda_classe_df) > 0:
            out = PROCESSED_DIR / SECONDA_CLASSE_PARQUET
            safe_write_parquet(seconda_classe_df, out, index=False)
            log.info(f"Saved -> {out}")


        if len(companies_df) > 0:
            out = PROCESSED_DIR / "companies-attio.parquet"
            safe_write_parquet(companies_df, out, index=False)
            log.info(f"Saved -> {out}")


        out = PROCESSED_DIR / "_attio_summary.json"
        out.write_text(json.dumps(summary, indent=2, default=str))
        log.info(f"Saved -> {out}")


    log.info("\n" + "=" * 60)
    log.info("ATTIO ENRICHMENT COMPLETE")
    log.info("=" * 60)
    log.info(f"  Contacts:     {len(contacts_df)}")
    log.info(f"  Second class: {len(seconda_classe_df)}")
    log.info(f"  Companies:    {len(companies_df)}")
    log.info(f"  New emails:   {summary['cross_reference']['new_from_attio']}")
    log.info(f"  Overlap:      {summary['cross_reference']['already_in_merged']}")
    if not args.dry_run:
        log.info(f"\n  Output: {PROCESSED_DIR}")


        _save_attio_input_checkpoint(_attio_input_fingerprints())

        try:
            from event_bus import EventBus
            from l1_checkpoint import L1Checkpoint

            ckpt = L1Checkpoint("attio")
            has_changed = ckpt.has_output_changed()
            ckpt.save()
            EventBus.emit(
                "attio",
                "l1",
                contacts=len(contacts_df),
                companies=len(companies_df),
                output_changed=has_changed,
            )
        except Exception as e:
            log.warning(f"EventBus/checkpoint failed: {e}")

        mark_last_run("attio-l1")


from pipeline_decorator import pipeline_step


def run_transcripts() -> None:
    ""





    if "--dry-run" in sys.argv:
        return
    script = Path(__file__).resolve().parent / "at-util-transcripts.py"
    rc = subprocess.run([sys.executable, str(script)], check=False).returncode
    if rc != 0:
        raise RuntimeError(f"at-util-transcripts.py exited {rc}: Attio transcripts not updated")
    mark_last_run("attio-transcripts-l1")


@pipeline_step(name="l1-attio-enrich", source="attio-l1", stage="l1")
def run():
    main()
    run_transcripts()


if __name__ == "__main__":
    run()
