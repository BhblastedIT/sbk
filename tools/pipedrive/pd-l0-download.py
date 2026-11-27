#!/usr/bin/env python3
"""L0 Pipedrive: the organizations, persons, deals, activities and notes you can see.

Reads with your own personal API token (or the OAuth app you registered yourself),
GET calls only, nothing is written in Pipedrive. What lands in ~/.sbk-data/pipedrive/
(or $SBK_DATA_ROOT/pipedrive/):

  raw/me.json                 your user id, email, company name and domain
  raw/organizations.json      id -> name, owner
  raw/persons.json            id -> name, emails, phones, organization, job title
  raw/deals.json              id -> title, status, value, owner, person, organization
                              (archived deals too, unless pipedrive.include_archived_deals is false)
  raw/activities.json         id -> subject, type, due date, done, participants, attendees, note
  raw/notes.json              id -> text, author, deal / person / organization
  state.json                  one update_time watermark per entity
  download-summary.json       what this run did (requests, estimated API tokens)

Incremental: each entity is asked only for what changed since its last complete pass
(minus one hour). The first run reads everything you can see, or the last
`pipedrive.since_days` days if you set it. Every request counts against your
company's shared daily API budget: `pipedrive.max_requests_per_run` caps one run.
Then run pd-l1-enrich.py (or `xs-pipeline-run.py --ingest`).

    uv run python tools/pipedrive/pd-l0-download.py --dry-run   # checks the credential, writes nothing
    uv run python tools/pipedrive/pd-l0-download.py
    uv run python tools/pipedrive/pd-l0-download.py --full      # re-reads everything, drops what was deleted
    uv run python tools/pipedrive/pd-l0-download.py --only deals --only activities
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(REPO / "tools"))


def _error_line(e) -> str:
    status = getattr(e, "status", 0)
    if status == 401:
        return (
            "pipedrive: the credential was refused (HTTP 401): token changed, revoked or "
            "API access turned off for you; see docs/CONNECTING.md#pipedrive"
        )
    if status == 402:
        return "pipedrive: the company account is not open (HTTP 402: trial expired or payment missing)"
    if status == 403:
        return f"pipedrive: request not allowed (HTTP 403 on {getattr(e, 'where', '?')})"
    if status == 429:
        return (
            "pipedrive: still rate limited after retries; if it lasts, your company's daily API "
            "budget is used up (it resets at midnight, Pipedrive server time). What was read is kept"
        )
    return f"pipedrive: {e}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Download the Pipedrive organizations, persons, deals, activities and notes "
        "you can see (read-only, your own API token or OAuth app).",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="check the credential and print who you are; write nothing",
    )
    ap.add_argument(
        "--full",
        action="store_true",
        help="ignore the watermarks, re-read everything and drop what was deleted in Pipedrive",
    )
    ap.add_argument(
        "--only",
        action="append",
        choices=("organizations", "persons", "deals", "activities", "notes"),
        help="run only this entity (repeatable)",
    )
    ap.add_argument(
        "--since-days",
        type=int,
        default=None,
        help="first-run window in days by last update (default: pipedrive.since_days, else everything)",
    )
    ap.add_argument(
        "--auth",
        choices=("auto", "api_token", "oauth"),
        default=None,
        help="which credential to use (default: pipedrive.auth, else auto = API token first)",
    )
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)

    logging.basicConfig(level=logging.WARNING if a.quiet else logging.INFO, format="%(message)s")
    log = logging.getLogger("pd-l0")

    try:
        from dotenv import load_dotenv

        load_dotenv(REPO / ".env")
    except ImportError:
        pass

    import pd_api

    import sbk_config as cfg

    try:
        auth = pd_api.resolve_auth(a.auth)
    except pd_api.NoCredentials as e:
        print(str(e), file=sys.stderr)
        return 1

    refresher = None
    api_domain = ""
    oauth_error: tuple = ()  # the access token is refreshed mid-run too (every 60 minutes)
    if auth.kind == "oauth":
        import pd_oauth

        oauth_error = (pd_oauth.OAuthError,)
        refresher = pd_oauth.make_refresher(auth)
        try:
            refresher()
        except pd_oauth.OAuthError as e:
            print(f"pipedrive: {e}", file=sys.stderr)
            return 1
        api_domain = auth.oauth.get("api_domain", "")

    cap = int(pd_api.setting("max_requests_per_run", 2000) or 2000)
    client = pd_api.Client(auth, max_requests=cap, refresher=refresher)
    try:
        if a.dry_run:
            me = pd_api.fetch_me(client, api_domain)
            log.info("pipedrive: %s (%s)", auth.kind, auth.where)
            log.info("  user id %s, company %s", me["id"], me["company_name"] or "?")
            log.info("  burst limit per 2 s: %s", client.burst_limit)
            log.info("  nothing written (dry run)")
            return 0
        steps = tuple(a.only) if a.only else pd_api.STEP_CHOICES
        since_days = (
            a.since_days if a.since_days is not None else pd_api.setting("since_days", None)
        )
        summary = pd_api.run_download(
            client,
            pd_api.pd_dir(),
            steps=steps,
            full=a.full,
            since_days=int(since_days) if since_days else None,
            include_archived_deals=bool(pd_api.setting("include_archived_deals", True)),
            api_domain=api_domain,
        )
    except pd_api.PipedriveError as e:
        print(_error_line(e), file=sys.stderr)
        return 1
    except pd_api.RequestCap as e:  # only reachable from the dry run's single call
        print(f"pipedrive: {e}", file=sys.stderr)
        return 1
    except oauth_error as e:  # refresh refused mid-run: what was read is kept
        print(f"pipedrive: {e}", file=sys.stderr)
        return 1
    summary["auth"], summary["auth_from"] = auth.kind, auth.where
    cfg.safe_write_json(pd_api.pd_dir() / pd_api.SUMMARY_FILE, summary)
    cfg.mark_last_run(pd_api.SOURCE_ID)
    for k, v in summary.items():
        if k != "steps":
            log.info("  %-30s %s", k, v)
    if not summary.get("complete"):
        log.warning(
            "  stopped at %s (%s); the next run continues from there",
            summary.get("stopped_at"),
            summary.get("stopped_because"),
        )
    log.info("  written to %s", pd_api.pd_dir())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
