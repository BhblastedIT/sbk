#!/usr/bin/env python3
"""L0 Linear: your issues (assigned, created, subscribed) and their comments.

Reads with your own personal API key, GraphQL queries only, nothing is written
in Linear. What lands in ~/.sbk-data/linear/ (or $SBK_DATA_ROOT/linear/):

  raw/me.json                you and the workspace name
  raw/issues.json            the issues you are assigned to, created, or are
                             subscribed to: status, team, project, priority,
                             labels, due date, assignee, creator, subscribers
  raw/comments.json          the comments on those issues, with their author
  state.json                 the incremental watermark
  download-summary.json      what this run did

Incremental: issues and comments updated since the last run (minus
`linear.overlap_hours`, 24 by default) are read again; the first run looks back
`linear.history_days` days (365 by default, 0 = everything). Open issues already
on disk that no longer match (you were unassigned) are read again by id. An
issue that became yours since the last run gets all its older comments once.
Turning `include_subscribed` or `comments` on later reads the first-run window again.
Then run ln-l1-enrich.py.

    uv run python tools/linear/ln-l0-download.py --dry-run   # checks the key, writes nothing
    uv run python tools/linear/ln-l0-download.py
    uv run python tools/linear/ln-l0-download.py --full      # forgets the saved state, reads everything
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
        description="Download your Linear issues (assigned, created, subscribed) and their comments (read-only).",
    )
    ap.add_argument(
        "--dry-run", action="store_true", help="check the key and print who you are; write nothing"
    )
    ap.add_argument(
        "--full",
        action="store_true",
        help="forget the saved state and files and read your whole history again "
        "(history_days and --since-days are not applied)",
    )
    ap.add_argument(
        "--since-days",
        type=int,
        default=None,
        help="first-run window in days, 0 = everything (default from sbk.config.json, else 365)",
    )
    ap.add_argument(
        "--no-subscribed",
        action="store_true",
        help="leave out issues you are only subscribed to (assigned and created stay)",
    )
    ap.add_argument("--no-comments", action="store_true", help="do not read comments")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)

    logging.basicConfig(level=logging.WARNING if a.quiet else logging.INFO, format="%(message)s")
    log = logging.getLogger("ln-l0")

    try:
        from dotenv import load_dotenv

        load_dotenv(REPO / ".env")
    except ImportError:
        pass

    import ln_api

    import sbk_config as cfg

    try:
        key, where = ln_api.resolve_key()
    except ln_api.NoKey as e:
        print(str(e), file=sys.stderr)
        return 1

    client = ln_api.Client(key)
    try:
        if a.dry_run:
            me = ln_api.fetch_me(client)
            log.info(
                "linear: key from %s, user %s, workspace %s",
                where,
                me.get("name") or "?",
                me["organization"]["name"] or "?",
            )
            log.info("  requests left this hour: %s", client.requests_remaining)
            log.info("  nothing written (dry run)")
            return 0
        try:
            history = (
                a.since_days
                if a.since_days is not None
                else int(cfg.user_cfg("linear.history_days", 365))
            )
            overlap = int(cfg.user_cfg("linear.overlap_hours", 24))
        except (TypeError, ValueError):
            print(
                "linear: linear.history_days and linear.overlap_hours in sbk.config.json "
                "must be whole numbers",
                file=sys.stderr,
            )
            return 1
        summary = ln_api.run_download(
            client,
            ln_api.LN_DIR,
            full=a.full,
            history_days=history,
            overlap_hours=overlap,
            include_subscribed=not a.no_subscribed
            and bool(cfg.user_cfg("linear.include_subscribed", True)),
            comments=not a.no_comments and bool(cfg.user_cfg("linear.comments", True)),
        )
    except ln_api.KeyRefused:
        print(ln_api.REFUSED_MSG, file=sys.stderr)
        return 1
    except ln_api.LinearError as e:
        print(f"linear: {e}", file=sys.stderr)
        return 1
    summary["key_from"] = where
    cfg.safe_write_json(ln_api.LN_DIR / ln_api.SUMMARY_FILE, summary)
    cfg.mark_last_run("linear")
    for k, v in summary.items():
        log.info("  %-24s %s", k, v)
    log.info("  written to %s", ln_api.LN_DIR)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
