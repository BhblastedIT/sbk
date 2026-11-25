#!/usr/bin/env python3
"""Read-only: extracts the decisions buried in the live-state file into a report (markdown, json or tsv)."""



















from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

_TOOLS = Path(__file__).resolve().parent.parent
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))
import sbk_config as cfg  # noqa: E402

DEFAULT_FILE = cfg.livestate_path()

SB_NOW_START = cfg.SB_NOW_START
SB_NOW_END = cfg.SB_NOW_END


# Your first name in decision-log markers ("attende Alex"), from sbk.config.json
# "owner"; the word "owner" is always recognised too.
OWNER_NAME = re.escape(cfg.OWNER_NAME.split()[0]) if cfg.OWNER_NAME else "owner"

MARKERS: dict[str, str] = {
    "RESTA": r"\bRESTA\b|\bResta\b|\bresta da\b|\brestano\b",
    "ATTESA_OWNER": rf"attesa (?:di )?(?:{OWNER_NAME}|owner)|ATTESA OWNER|attende {OWNER_NAME}|aspetta {OWNER_NAME}",
    "DECISIONE": r"\bDECISION[EI]\b|\bdecisione\b|\bdecidere\b|\bda decidere\b",
    "GATED": r"\bgated\b|\bgate\b|\bblocca(?:to|ta|nte)\b|\bbloccat",
    "WARN": r"⚠️|⚠",
    "DA_CONFERMARE": rf"da confermare|da verificare con {OWNER_NAME}|conferma di {OWNER_NAME}",
    "MANCA": r"\bmanca\b|\bmancano\b|\bmancante\b",
    "OK_OWNER": rf"OK {OWNER_NAME}|ok di {OWNER_NAME}|approvazione (?:esplicita )?(?:di )?{OWNER_NAME}|autorizzazione {OWNER_NAME}",
    "IN_ATTESA": r"in attesa\b",
    "OPEN_LOOP": r"open loop|Open loop",
    "TODO": r"\bTODO\b|\bDA FARE\b|\bda fare\b",
    "PENDENTE": r"\bpendent[ei]\b|\bPENDENTE\b",
}

COMPILED = {name: re.compile(rx) for name, rx in MARKERS.items()}


DATE_RX = re.compile(r"(20\d{2})-(\d{2})-(\d{2})")


@dataclass
class Block:
    ""

    index: int
    header: str
    start_line: int
    end_line: int
    date: str | None
    lines: list[str] = field(default_factory=list)

    @property
    def sha256(self) -> str:
        body = "\n".join(self.lines)
        return hashlib.sha256(body.encode("utf-8")).hexdigest()


@dataclass
class Hit:
    ""

    line_no: int
    block_index: int
    block_header: str
    block_date: str | None
    markers: list[str]
    text: str


def parse_blocks(text: str) -> list[Block]:
    ""
    raw = text.split("\n")


    skip_from = skip_to = None
    for i, line in enumerate(raw):
        if SB_NOW_START in line:
            skip_from = i
        elif SB_NOW_END in line:
            skip_to = i
    protected: set[int] = set()
    if skip_from is not None and skip_to is not None and skip_to >= skip_from:
        protected = set(range(skip_from, skip_to + 1))

    blocks: list[Block] = []
    current: Block | None = None
    for i, line in enumerate(raw):
        if i in protected:
            continue
        if line.startswith("## "):
            if current is not None:
                current.end_line = i
                blocks.append(current)
            m = DATE_RX.search(line)
            current = Block(
                index=len(blocks) + 1,
                header=line[3:].strip(),
                start_line=i + 1,
                end_line=i + 1,
                date=f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None,
                lines=[line],
            )
        elif current is not None:
            current.lines.append(line)
    if current is not None:
        current.end_line = len(raw)
        blocks.append(current)
    return blocks


def infer_date(block: Block) -> str | None:
    ""
    if block.date:
        return block.date
    for line in block.lines[1:]:
        m = DATE_RX.search(line)
        if m:
            return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return None


def scan(blocks: list[Block]) -> list[Hit]:
    ""
    hits: list[Hit] = []
    for block in blocks:
        bdate = infer_date(block)
        for offset, line in enumerate(block.lines):
            stripped = line.strip()
            if not stripped:
                continue
            found = [n for n, rx in COMPILED.items() if rx.search(line)]
            if not found:
                continue
            hits.append(
                Hit(
                    line_no=block.start_line + offset,
                    block_index=block.index,
                    block_header=block.header,
                    block_date=bdate,
                    markers=found,
                    text=stripped,
                )
            )
    return hits


def render_markdown(blocks: list[Block], hits: list[Hit]) -> str:
    ""
    out: list[str] = []
    out.append("# Buried decisions scan — live-state.md")
    out.append("")
    out.append(f"- blocks analyzed (SB-NOW excluded): **{len(blocks)}**")
    out.append(f"- lines with markers: **{len(hits)}**")
    out.append("")
    by_block: dict[int, list[Hit]] = {}
    for h in hits:
        by_block.setdefault(h.block_index, []).append(h)
    ordered = sorted(
        (b for b in blocks if b.index in by_block),
        key=lambda b: infer_date(b) or "0000-00-00",
        reverse=True,
    )
    for b in ordered:
        out.append(f"## [{infer_date(b) or 'no-date'}] L{b.start_line} — {b.header}")
        out.append("")
        for h in by_block[b.index]:
            out.append(f"- **L{h.line_no}** `{'+'.join(h.markers)}` — {h.text}")
        out.append("")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--file", type=Path, default=DEFAULT_FILE)
    ap.add_argument("--format", choices=("markdown", "json", "tsv"), default="markdown")
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="show what it would do (file, blocks, markers) without producing the report",
    )
    args = ap.parse_args(argv)

    path: Path = args.file
    if not path.exists():
        print(f"ERROR: file not found: {path}", file=sys.stderr)
        return 2

    text = path.read_text(encoding="utf-8")
    blocks = parse_blocks(text)
    hits = scan(blocks)

    if args.dry_run:
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        print("DRY-RUN — no writes, no file touched.")
        print(f"  source          : {path}")
        print(f"  sha256          : {digest[:16]}")
        print(f"  lines           : {len(text.splitlines())}")
        print(f"  blocks '## '    : {len(blocks)} (SB-NOW region excluded)")
        print(f"  active markers  : {', '.join(MARKERS)}")
        print(f"  candidate lines : {len(hits)}")
        print(
            "  would produce   : report on stdout, format "
            f"{args.format}. The source is NOT modified."
        )
        return 0

    if args.format == "json":
        print(
            json.dumps(
                {
                    "file": str(path),
                    "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                    "blocks": len(blocks),
                    "hits": [asdict(h) for h in hits],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    elif args.format == "tsv":
        for h in hits:
            print(f"{h.line_no}\t{h.block_date or ''}\t{'+'.join(h.markers)}\t{h.text}")
    else:
        print(render_markdown(blocks, hits))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
