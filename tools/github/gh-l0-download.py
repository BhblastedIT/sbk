#!/usr/bin/env python3
"""L0 GitHub: your repositories, the people you work with, your issues, PRs and reviews.

Reads with your own personal access token, GET calls only, nothing is written
on GitHub. What lands in ~/.sbk-data/github/ (or $SBK_DATA_ROOT/github/):

  repos.json                 the repositories (same file gh-l0-inventory.py writes,
                             read by tools/cross-source/xs-l1-inventario.py)
  alberi/<owner>__<repo>.json  top-level folders and README (only with --trees)
  raw/me.json                your login
  raw/collaborators/*.json   collaborators of the repos where you can push
  raw/items.json             issues and PRs where you are author or assignee,
                             PRs where your review is requested, PRs you reviewed
  raw/users.json             public profiles of the people found
  state.json                 the incremental watermark
  download-summary.json      what this run did

Incremental: issues and PRs are searched from the last run (minus one day of
overlap); the first run looks back `github.since_days` days (365 by default).
Then run gh-l1-enrich.py (or `xs-pipeline-run.py --ingest`).

    uv run python tools/github/gh-l0-download.py --dry-run   # checks the token, writes nothing
    uv run python tools/github/gh-l0-download.py
    uv run python tools/github/gh-l0-download.py --full      # re-reads everything
    uv run python tools/github/gh-l0-download.py --only work # only issues/PRs/reviews
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
        description="Download your GitHub repositories, collaborators, issues, PRs and reviews (read-only).",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="check the token and print who you are; write nothing",
    )
    ap.add_argument(
        "--full", action="store_true", help="ignore the watermark and re-read everything"
    )
    ap.add_argument(
        "--only",
        choices=("repos", "people", "work"),
        action="append",
        help="run only this step (repeatable): repos, people (collaborators), work (issues/PRs/reviews)",
    )
    ap.add_argument(
        "--trees", action="store_true", help="also read top-level folders and README of each repo"
    )
    ap.add_argument(
        "--since-days",
        type=int,
        default=None,
        help="first-run window in days (default from sbk.config.json, else 365)",
    )
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)

    logging.basicConfig(level=logging.WARNING if a.quiet else logging.INFO, format="%(message)s")
    log = logging.getLogger("gh-l0")

    try:
        from dotenv import load_dotenv

        load_dotenv(REPO / ".env")
    except ImportError:
        pass

    import gh_api

    import sbk_config as cfg

    try:
        token, where = gh_api.resolve_token()
    except gh_api.NoToken as e:
        print(str(e), file=sys.stderr)
        return 1

    client = gh_api.Client(token)
    kind = gh_api.token_kind(token)
    try:
        if a.dry_run:
            me = gh_api.fetch_me(client)
            log.info("github: token from %s (%s), user %s", where, kind, me["login"] or "?")
            if client.scopes is not None:
                log.info("  classic token scopes: %s", client.scopes or "(none)")
            log.info("  rate limit remaining: %s", client.rate_remaining)
            log.info("  nothing written (dry run)")
            return 0
        steps = tuple(a.only) if a.only else ("repos", "people", "work")
        summary = gh_api.run_download(
            client,
            gh_api.GH_DIR,
            steps=steps,
            trees=a.trees or bool(cfg.user_cfg("github.trees", False)),
            full=a.full,
            since_days=a.since_days or int(cfg.user_cfg("github.since_days", 365)),
            affiliation=str(cfg.user_cfg("github.collaborator_affiliation", "direct")),
            skip_owners=list(cfg.user_cfg("github.skip_owners", []) or []),
            max_profiles=int(cfg.user_cfg("github.max_profiles_per_run", 300)),
            max_reviews=int(cfg.user_cfg("github.max_reviews_per_run", 500)),
        )
    except gh_api.GitHubError as e:
        if e.status == 401:
            print(
                "github: the token was refused (HTTP 401), expired or revoked; see docs/CONNECTING.md#github",
                file=sys.stderr,
            )
        else:
            print(f"github: {e}", file=sys.stderr)
        return 1
    summary["token_kind"], summary["token_from"] = kind, where
    cfg.safe_write_json(gh_api.GH_DIR / gh_api.SUMMARY_FILE, summary)
    cfg.mark_last_run("github")
    for k, v in summary.items():
        if k not in ("steps",):
            log.info("  %-28s %s", k, v)
    log.info("  written to %s", gh_api.GH_DIR)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
