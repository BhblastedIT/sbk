#!/usr/bin/env python3
"""L0 GitHub inventory: the list of your repositories, plus top-level folders and README.

This is the command `tools/sorgenti.py` and `tools/cross-source/xs-l0-refresh.py`
already name for the `github` inventory source. It writes
~/.sbk-data/github/repos.json (read by tools/cross-source/xs-l1-inventario.py)
and, unless --no-trees, ~/.sbk-data/github/alberi/<owner>__<repo>.json.

Incremental on `pushed_at`: a repository nobody pushed to since the last run
keeps its folder list and README without a new call.

Issues, PRs, reviews and collaborators are in gh-l0-download.py.

    uv run python tools/github/gh-l0-inventory.py
    uv run python tools/github/gh-l0-inventory.py --no-trees   # list only, one call per 100 repos
    uv run python tools/github/gh-l0-inventory.py --full       # re-read every tree
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
    ap = argparse.ArgumentParser(description="Inventory of your GitHub repositories (read-only).")
    ap.add_argument("--no-trees", action="store_true", help="skip top-level folders and README")
    ap.add_argument("--full", action="store_true", help="re-read every tree, ignoring pushed_at")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)

    logging.basicConfig(level=logging.WARNING if a.quiet else logging.INFO, format="%(message)s")
    log = logging.getLogger("gh-l0-inventory")

    try:
        from dotenv import load_dotenv

        load_dotenv(REPO / ".env")
    except ImportError:
        pass

    import gh_api

    import sbk_config as cfg

    try:
        token, _where = gh_api.resolve_token()
    except gh_api.NoToken as e:
        print(str(e), file=sys.stderr)
        return 1

    client = gh_api.Client(token)
    stats: dict = {}
    try:
        gh_api.run_inventory(
            client,
            gh_api.GH_DIR,
            trees=not a.no_trees,
            skip_owners=list(cfg.user_cfg("github.skip_owners", []) or []),
            full=a.full,
            stats=stats,
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
    for k, v in stats.items():
        log.info("  %-18s %s", k, v)
    log.info("  api calls          %s", client.calls)
    log.info("  written to %s", gh_api.GH_DIR / gh_api.REPOS_FILE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
