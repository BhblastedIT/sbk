#!/usr/bin/env python3
"""The sbk command line: search, brief, decay, lookup, pipeline, monitor, tasks and draft, each calling the
matching tool.

Usage: uv run python tools/sbk_cli.py <command> [options]   (--help lists the commands)
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


_CLI_DIR = Path(__file__).resolve().parent
_CROSS_SOURCE_DIR = _CLI_DIR / "cross-source"
_MONITORING_DIR = _CLI_DIR / "monitoring"

for p in [str(_CLI_DIR), str(_CROSS_SOURCE_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)


def _load_module(name: str, path: Path):
    ""
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        print(f"Error: could not load {path}", file=sys.stderr)
        sys.exit(1)
    mod = importlib.util.module_from_spec(spec)








    sys.modules.setdefault(name, mod)
    spec.loader.exec_module(mod)
    return mod





def cmd_search(args: list[str]) -> int:
    ""
    import argparse

    parser = argparse.ArgumentParser(
        prog="sbk search",
        description="Semantic search. Raw results by default, nothing is sent to a model; "
        "--synthesize also asks Claude (your own claude login) for an answer.",
    )
    parser.add_argument("query", help="Search query")
    parser.add_argument(
        "--source", metavar="TYPE", help="Filter by source (email, plaud, slack...)"
    )
    parser.add_argument("--after", metavar="DATE", help="Filter after date (YYYY-MM-DD)")
    parser.add_argument("--person", metavar="NAME", help="Filter by participant name")
    parser.add_argument(
        "--top", type=int, default=10, metavar="N", help="Number of results (default: 10)"
    )
    sintesi = parser.add_mutually_exclusive_group()
    sintesi.add_argument(
        "--synthesize",
        action="store_true",
        help="Also send the question and the results to Claude with your own claude login "
        "(claude -p) and print its answer. Off by default; search.synthesis true in "
        "sbk.config.json turns it on for every search",
    )
    sintesi.add_argument(
        "--no-synthesis",
        action="store_true",
        help="Raw results only (the default); overrides search.synthesis true in sbk.config.json",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Debug logging")
    opts = parser.parse_args(args)

    mod = _load_module("xs_l3_search", _CROSS_SOURCE_DIR / "xs-l3-search.py")
    mod.setup_logging(verbose=opts.verbose, name="sbk-search")

    try:
        table = mod.open_lancedb()
    except RuntimeError as e:
        if str(e).startswith("No LanceDB table found"):
            # Fresh data root: nothing to search yet, not an error.
            print(
                "No results: nothing is indexed yet. The L3 Index stage of "
                "`uv run python tools/cross-source/xs-pipeline-run.py --ingest` builds the search index."
            )
            return 0
        print(f"Error: {e}", file=sys.stderr)
        return 1

    query_vector = list(mod.embed_query(opts.query))
    results = mod.hybrid_search(
        table=table,
        query=opts.query,
        query_vector=query_vector,
        top_k=opts.top,
        source_filter=opts.source,
        after_date=opts.after,
        person_filter=opts.person,
    )

    if not results:
        print("No results found.")
        return 0

    mod.stampa_risultati(
        opts.query,
        results,
        grezzo=not mod.synthesis_wanted(opts.synthesize, opts.no_synthesis),
    )
    return 0





def cmd_brief(args: list[str]) -> int:
    """Today's stories. The model summary only with --synthesize or brief.synthesis true in sbk.config.json."""
    mod = _load_module("xs_l3_digest_v2", _CROSS_SOURCE_DIR / "xs-l3-digest-v2.py")
    return mod.main(args, prog="sbk brief") or 0





def cmd_decay(args: list[str]) -> int:
    ""
    import argparse

    parser = argparse.ArgumentParser(prog="sbk decay", description="Decay tracker")
    parser.add_argument("--dry-run", action="store_true", help="Compute without writing state")
    parser.add_argument("--full-report", action="store_true", help="Show all tracked people")
    parser.add_argument("--budget", type=int, default=5, help="Max alerts per day (default: 5)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Debug logging")
    opts = parser.parse_args(args)

    mod = _load_module("xs_l3_decay", _CROSS_SOURCE_DIR / "xs-l3-decay.py")
    mod.setup_logging(verbose=opts.verbose, name="sbk-decay")

    from xs_l3_common import SBKData

    data = SBKData()
    alerts = mod.run_decay_analysis(
        data=data,
        budget=opts.budget,
        dry_run=opts.dry_run,
        full_report=opts.full_report,
    )
    return 0 if alerts is not None else 1





def cmd_lookup(args: list[str]) -> int:
    ""
    import argparse
    import json

    parser = argparse.ArgumentParser(prog="sbk lookup", description="Person lookup")
    parser.add_argument("name", help="Person name or email to look up")
    parser.add_argument("--json", action="store_true", dest="json_out", help="Output as JSON")
    parser.add_argument("--verbose", "-v", action="store_true", help="Debug logging")
    opts = parser.parse_args(args)

    from xs_l3_common import SBKData

    data = SBKData()


    person = data.resolve_person(opts.name)

    if not person:

        pid = data.resolve_person_by_name(opts.name)
        if pid:

            matches = data.contacts[data.contacts["person_id"] == pid]
            if not matches.empty:
                row = matches.iloc[0]
                email = row.get("email", "")
                # A contact without e-mail (WhatsApp, Telegram, an address-book card) is the row itself.
                person = data.resolve_person(email) if email else row.to_dict()

    if not person:
        print(f"No contact found for: {opts.name}")
        return 1

    ctx = _lookup_context(data, person)

    if opts.json_out:
        print(json.dumps(ctx, indent=2, ensure_ascii=False, default=str))
    else:
        _print_person_summary(person, ctx)

    return 0


def _plain(value):
    """A JSON-friendly value: numpy scalars as Python numbers, NaN/NaT as None, dates as text."""
    import math

    if hasattr(value, "item") and not isinstance(value, (str, bytes)):
        try:
            value = value.item()
        except (ValueError, TypeError):
            pass
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    if type(value).__name__ in ("NaTType", "NAType"):
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if hasattr(value, "tolist"):
        return _plain(value.tolist())
    return str(value)


def _lookup_context(data, person: dict) -> dict:
    """What `sbk lookup` knows about the person: the text output and --json read this same dict.

    A person with an e-mail gets the full context (threads, meetings, facts); a contact that came
    without e-mail (WhatsApp, Telegram, an address-book card) gets the fields of its address-book row.
    """
    import json as _json

    email = str(person.get("email") or "")
    ctx = data.get_person_context(email) if email else {"found": False}
    if not ctx.get("found"):
        ctx = {
            "email": email,
            "found": True,
            "name": person.get("name", ""),
            "person_id": person.get("person_id", ""),
            "organization": person.get("organization") or person.get("attio_company") or "",
            "job_title": person.get("attio_job_title") or person.get("linkedin_headline") or "",
            "score": person.get("score", 0),
            "source_count": person.get("source_count", 0),
            "is_internal": person.get("is_internal", False),
            "last_contact": str(person.get("last_contact", "") or ""),
            "last_contact_source": str(person.get("last_contact_source", "") or ""),
        }
    for key in ("phone_primary", "contact_key", "started_by"):
        if person.get(key) and key not in ctx:
            ctx[key] = person[key]
    all_emails = person.get("all_emails", [])
    if isinstance(all_emails, str):
        try:
            all_emails = _json.loads(all_emails)
        except (ValueError, TypeError):
            all_emails = []
    ctx["all_emails"] = list(all_emails) if all_emails is not None else []
    return {k: _plain(v) for k, v in ctx.items()}


def _print_person_summary(person: dict, ctx: dict) -> None:
    ""
    # Read from ctx (the same dict --json prints), the address-book row only as a fallback.
    name = ctx.get("name") or person.get("name") or "Unknown"
    email = ctx.get("email") or person.get("email") or ""
    org = ctx.get("organization") or person.get("organization") or ""
    score = ctx.get("score") or person.get("score") or 0
    pid = ctx.get("person_id") or person.get("person_id") or ""
    phone = ctx.get("phone_primary") or ""

    print(f"\n{'=' * 60}")
    print(f"  {name}")
    if org:
        print(f"  {org}")
    if email:
        print(f"  {email}")
    if phone and phone != name:
        print(f"  {phone}")
    print(f"  Score: {float(score):.1f}  |  ID: {pid}")
    print(f"{'=' * 60}")

    if ctx.get("found"):
        if ctx.get("last_contact"):
            print(f"\n  Last contact: {ctx['last_contact']}")
        if ctx.get("email_count"):
            print(f"  Email: {ctx['email_count']} threads")
        if ctx.get("meeting_count"):
            print(f"  Meetings: {ctx['meeting_count']} events")
        if ctx.get("attio_notes"):
            print(f"  Attio notes: {len(ctx['attio_notes'])}")


    all_emails = ctx.get("all_emails") or []
    if len(all_emails) > 1:
        print(f"\n  Email aliases: {', '.join(all_emails)}")

    print()





def cmd_pipeline(args: list[str]) -> int:
    ""
    import argparse

    parser = argparse.ArgumentParser(prog="sbk pipeline", description="Pipeline orchestrator")






    parser.add_argument(
        "--propagate",
        dest="propaga",
        action="store_true",
        help="L2+L3 incremental (does NOT read the sources). The default",
    )
    parser.add_argument(
        "--rebuild", dest="ricostruisci", action="store_true", help="L2+L3 with all stages forced"
    )
    # Older Italian names, kept as hidden aliases.
    parser.add_argument("--propaga", dest="propaga", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument(
        "--ricostruisci", dest="ricostruisci", action="store_true", help=argparse.SUPPRESS
    )
    parser.add_argument("--auto", action="store_true", help="DEPRECATED since 0.1: --propagate")
    parser.add_argument("--full", action="store_true", help="DEPRECATED since 0.1: --rebuild")
    parser.add_argument("--dry-run", action="store_true", help="Show what would run")
    parser.add_argument("--verbose", "-v", action="store_true", help="Debug logging")
    opts = parser.parse_args(args)

    mod = _load_module("xs_pipeline_run", _CROSS_SOURCE_DIR / "xs-pipeline-run.py")

    import logging

    logging.basicConfig(
        level=logging.DEBUG if opts.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    if opts.auto or opts.full:
        print(
            f"⚠️  --{'full' if opts.full else 'auto'} is deprecated since 0.1: use "
            f"--{'rebuild' if opts.full else 'propagate'}. "
            "Removal in a future release."
        )
    mode = "ricostruisci" if (opts.ricostruisci or opts.full) else "propaga"
    result = mod.run_pipeline(mode=mode, dry_run=opts.dry_run)
    print(f"\n{result.get('intestazione', '')}")

    print(f"\nPipeline completed in {result.get('elapsed', 0):.1f}s")
    if result.get("stages_run"):
        print(f"  Stages run: {', '.join(result['stages_run'])}")
    if result.get("stages_skipped"):
        print(f"  Stages skipped: {', '.join(result['stages_skipped'])}")
    if result.get("errors"):
        print(f"  Errors: {', '.join(result['errors'])}")




    return int(result.get("exit_code", 1 if result.get("errors") else 0))





def cmd_monitor(args: list[str]) -> int:
    ""

    sys.argv = ["sbk-monitor.py"] + args
    mod = _load_module("sbk_monitor", _MONITORING_DIR / "sbk-monitor.py")
    mod.main()
    return 0





def cmd_tasks(args: list[str]) -> int:
    ""
    sys.argv = ["xs-l3-tasks.py"] + args
    mod = _load_module("xs_l3_tasks", _CROSS_SOURCE_DIR / "xs-l3-tasks.py")
    mod.main()
    return 0





def cmd_draft(args: list[str]) -> int:
    ""
    sys.argv = ["xs-l3-draft.py"] + args
    mod = _load_module("xs_l3_draft", _CROSS_SOURCE_DIR / "xs-l3-draft.py")
    mod.main()
    return 0




COMMANDS = {
    "search": (cmd_search, "Semantic search across all indexed data"),
    "brief": (cmd_brief, "Today's stories; a model summary only with --synthesize"),
    "decay": (cmd_decay, "Relationship decay analysis and alerts"),
    "lookup": (cmd_lookup, "Person lookup with cross-source context"),
    "pipeline": (cmd_pipeline, "Smart pipeline orchestrator"),
    "monitor": (cmd_monitor, "Monitor daemon control and status"),
    "tasks": (cmd_tasks, "Daily task board"),
    "draft": (cmd_draft, "Communication draft generator"),
}


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print("sbk — SBK unified CLI\n")
        print("Usage: sbk <command> [options]\n")
        print("Commands:")
        max_len = max(len(c) for c in COMMANDS)
        for name, (_, desc) in COMMANDS.items():
            print(f"  {name:<{max_len + 2}} {desc}")
        print("\nRun 'sbk <command> --help' for command-specific options.")
        return 0

    cmd_name = sys.argv[1]

    if cmd_name not in COMMANDS:
        print(f"Unknown command: {cmd_name}", file=sys.stderr)
        print(f"Available commands: {', '.join(COMMANDS)}", file=sys.stderr)
        return 1

    handler, _ = COMMANDS[cmd_name]


    remaining_args = sys.argv[2:]

    try:
        return handler(remaining_args) or 0
    except KeyboardInterrupt:
        print("\nInterrupted.")
        return 130
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
