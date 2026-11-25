#!/usr/bin/env python3
"""Checks that the knowledge-layer migration is complete: archive headers, CLAUDE.md references, knowledge folders."""












from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from sbk_config import KNOWLEDGE_DIR  # noqa: E402

ARCHIVE_MARKER = "**ARCHIVIO**"

checks_passed = 0
checks_failed = 0


def check(name: str, condition: bool, detail: str = ""):
    global checks_passed, checks_failed
    if condition:
        checks_passed += 1
        print(f"  PASS: {name}")
    else:
        checks_failed += 1
        print(f"  FAIL: {name}{' -- ' + detail if detail else ''}")


def main():
    print("=== LKL-06 Migration Verification ===\n")


    print("1. Archive headers on static files")
    network_dir = PROJECT_ROOT / "sbk" / "network"
    network_files = sorted(network_dir.rglob("*.md")) if network_dir.exists() else []
    companies_dir = PROJECT_ROOT / "sbk" / "companies"
    state_files = sorted(companies_dir.rglob("state.md")) if companies_dir.exists() else []

    total_static = len(network_files) + len(state_files)
    missing_header = 0
    for f in network_files + state_files:
        content = f.read_text(encoding="utf-8")[:500]
        if ARCHIVE_MARKER not in content:
            missing_header += 1
            rel = f.relative_to(PROJECT_ROOT)
            print(f"    MISSING: {rel}")

    check(
        f"All {total_static} static files have header",
        missing_header == 0,
        f"{missing_header} files missing header",
    )


    print("\n2. CLAUDE.md references")
    claude_md = PROJECT_ROOT / "CLAUDE.md"
    claude_content = claude_md.read_text(encoding="utf-8")
    check(
        "CLAUDE.md mentions Living Knowledge Layer",
        "Living Knowledge Layer" in claude_content,
    )
    check(
        "CLAUDE.md mentions get_entity_profile",
        "get_entity_profile" in claude_content,
    )
    check(
        "CLAUDE.md mentions knowledge store path",
        "~/.sbk-data/knowledge/" in claude_content,
    )


    print("\n3. Agent file references")
    agents_dir = PROJECT_ROOT / ".claude" / "agents"
    agent_files = sorted(agents_dir.glob("*.md")) if agents_dir.exists() else []
    if not agent_files:
        check("agent files exist", False, "no .md files in .claude/agents")
    for agent_file in agent_files:
        content = agent_file.read_text(encoding="utf-8")
        check(
            f"{agent_file.name} mentions knowledge store",
            "get_entity_profile" in content
            or "get_company_team" in content
            or "Knowledge Store" in content,
        )


    print("\n4. Knowledge store data")
    check("Knowledge directory exists", KNOWLEDGE_DIR.exists())
    entities_dir = KNOWLEDGE_DIR / "entities"
    check(
        "Entities directory exists",
        entities_dir.exists() if KNOWLEDGE_DIR.exists() else False,
    )

    if entities_dir and entities_dir.exists():

        for subdir_name in ["person", "organization"]:
            subdir = entities_dir / subdir_name
            if subdir.exists():
                count = len(list(subdir.glob("*.json")))
                check(f"entities/{subdir_name}/ has data ({count} files)", count > 0)
            else:
                check(f"entities/{subdir_name}/ exists", False)


    print(f"\n=== Results: {checks_passed} passed, {checks_failed} failed ===")
    return 0 if checks_failed == 0 else 1


if __name__ == "__main__":
    if {"-h", "--help"} & set(sys.argv[1:]):
        print(__doc__)
        sys.exit(0)
    sys.exit(main())
