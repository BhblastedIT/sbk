#!/usr/bin/env python3
"""L0 Atlassian: your Jira issues and your Confluence pages, read with your own API token.

GET calls only, nothing is written in Jira or Confluence. What lands in
~/.sbk-data/atlassian/ (or $SBK_DATA_ROOT/atlassian/):

  raw/me.json             your account id, name and the site
  raw/issues.json         Jira issues you created, reported, are assigned to or watch,
                          with status, due date, people and (when more than one) watchers
  raw/pages.json          Confluence pages you created or edited, with creator, last
                          editor and contributors
  state.json              the incremental watermarks
  download-summary.json   what this run did

Incremental: Jira issues updated since the last run (plus one hour), Confluence pages
modified since the day before the last run. The first run looks back
`atlassian.since_days` (365) for Jira and `atlassian.confluence_since_days` (180) for
Confluence. Then run as-l1-enrich.py (or `xs-pipeline-run.py --ingest`).

    uv run python tools/atlassian/as-l0-download.py --dry-run   # checks the token, writes nothing
    uv run python tools/atlassian/as-l0-download.py
    uv run python tools/atlassian/as-l0-download.py --full      # re-reads everything
    uv run python tools/atlassian/as-l0-download.py --only jira
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(REPO / "tools"))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Download your Jira issues and Confluence pages with your own API token (read-only).",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="check the token and print who you are; write nothing",
    )
    ap.add_argument(
        "--full",
        action="store_true",
        help="ignore the watermarks, re-read everything and drop what no longer matches",
    )
    ap.add_argument(
        "--only",
        choices=("jira", "confluence"),
        action="append",
        help="run only this product (repeatable)",
    )
    ap.add_argument(
        "--since-days",
        type=int,
        default=None,
        help="first-run window for Jira in days (default from sbk.config.json, else 365)",
    )
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)

    logging.basicConfig(level=logging.WARNING if a.quiet else logging.INFO, format="%(message)s")
    log = logging.getLogger("as-l0")

    try:
        from dotenv import load_dotenv

        load_dotenv(REPO / ".env")
    except ImportError:
        pass

    import as_api

    import sbk_config as cfg

    try:
        settings = as_api.load_settings(tuple(a.only) if a.only else None)
    except as_api.NotConfigured as e:
        print(str(e), file=sys.stderr)
        return 1

    try:
        if a.dry_run:
            import requests

            session = requests.Session()
            for product in settings.products:
                token, where = settings.tokens[product]
                client = as_api.Client(settings.email, token, settings.site, session=session)
                route, _, me = as_api.resolve_route(product, settings, client, session)
                name = me.get("displayName") or me.get("publicName") or "?"
                log.info("%s: token from %s, route %s, user %s", product, where, route, name)
            log.info("  site %s; nothing written (dry run)", settings.site)
            return 0
        summary = as_api.run_download(
            settings,
            as_api.AS_DIR,
            full=a.full,
            since_days=a.since_days or int(cfg.user_cfg("atlassian.since_days", 365)),
            confluence_since_days=int(cfg.user_cfg("atlassian.confluence_since_days", 180)),
            max_watchers=int(cfg.user_cfg("atlassian.max_watcher_calls_per_run", 200)),
            strict=bool(a.only),
        )
    except as_api.AtlassianError as e:
        if e.status == 401:
            print(
                "atlassian: the token was refused (HTTP 401): check the email, the token, its expiry "
                f"and, for a token with scopes, atlassian.token_kind; {as_api.GUIDE}",
                file=sys.stderr,
            )
        else:
            print(f"atlassian: {e}", file=sys.stderr)
        return 1
    cfg.mark_last_run("atlassian")
    for k, v in summary.items():
        log.info("  %-28s %s", k, v)
    log.info("  written to %s", as_api.AS_DIR)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
