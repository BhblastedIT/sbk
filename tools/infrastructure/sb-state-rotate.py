#!/usr/bin/env python3
"""Rotates old sessions from the live-state file into the session log without losing a byte (dry run unless --apply)."""
























































from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import hashlib
import re
import shutil
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


if str(REPO / "tools") not in sys.path:
    sys.path.insert(0, str(REPO / "tools"))
import sbk_config as cfg  # noqa: E402

LIVESTATE_MAX_LINES = cfg.LIVESTATE_MAX_LINES
LIVESTATE_MAX_BYTES = cfg.LIVESTATE_MAX_BYTES

DEFAULT_LIVE = cfg.livestate_path()
DEFAULT_LOG = cfg.sessionlog_path()

SB_NOW_END = cfg.SB_NOW_END






SB_WAIT_START = cfg.SB_WAIT_START
SB_WAIT_END = cfg.SB_WAIT_END
DATE_RE = re.compile(r"20\d{2}-\d{2}-\d{2}")
UNKNOWN_DATE = "0000-00-00"






STUB_MARK = cfg.SB_STUB_MARK
STUB_RE = re.compile(r"^<!-- SB-STUB sha256=([0-9a-f]{64}) -->$")

EXIT_OK = 0
EXIT_CHECK_FAIL = 1
EXIT_GATE_FAIL = 2
EXIT_RACE = 3


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class Block:
    raw: str
    index: int

    @property
    def header(self) -> str:
        return self.raw.split("\n", 1)[0]

    @property
    def body(self) -> str:
        parts = self.raw.split("\n", 1)
        return parts[1] if len(parts) == 2 else ""

    @property
    def header_text(self) -> str:
        return self.header.lstrip("#").strip()

    @property
    def canon(self) -> str:
        return self.header_text + "\n" + self.body.rstrip("\n")

    @property
    def canon_sha(self) -> str:
        return sha256(self.canon)

    @property
    def date(self) -> str | None:
        m = DATE_RE.search(self.header)
        return m.group(0) if m else None

    @property
    def is_session(self) -> bool:
        ""








        t = self.header_text.lstrip("#").strip()

        t = re.sub(r"^[^\w\d]+", "", t)
        return bool(re.match(r"Sessione\b", t) or DATE_RE.match(t))

    @property
    def stub_of(self) -> str | None:
        ""






        for ln in self.body.split("\n"):
            if not ln.strip():
                continue
            m = STUB_RE.match(ln.strip())
            return m.group(1) if m else None
        return None


def assert_lf(text: str, path: str) -> None:
    ""






    if "\r\n" in text:
        raise SystemExit(
            f"ABORT: {path} has CRLF line endings. Convert it first:\n"
            f"  python3 -c \"from pathlib import Path; p=Path('{path}'); "
            f'p.write_text(p.read_text().replace(chr(13)+chr(10), chr(10)))"'
        )


def sb_wait_regione(text: str) -> str | None:
    ""




    if text.count(SB_WAIT_START) != 1 or text.count(SB_WAIT_END) != 1:
        return None
    a = text.index(SB_WAIT_START)
    b = text.index(SB_WAIT_END)
    if b < a:
        return None
    return text[a : b + len(SB_WAIT_END)]


def _estendi_a_sb_wait(lines: list[str], end_idx: int, header_re: re.Pattern) -> int:
    ""







    try:
        i_start = next(i for i, ln in enumerate(lines) if SB_WAIT_START in ln)
        i_end = next(i for i, ln in enumerate(lines) if SB_WAIT_END in ln)
    except StopIteration:
        return end_idx
    if i_end < i_start or i_start <= end_idx:
        return end_idx
    if any(header_re.match(ln.rstrip("\r")) for ln in lines[end_idx + 1 : i_start]):
        return end_idx
    return i_end


def split_blocks(text: str, marker: str) -> tuple[str, list[Block]]:
    ""














    lines = text.split("\n")
    header_re = re.compile(rf"^{re.escape(marker)} (?!#)")
    end_idx = -1
    for i, line in enumerate(lines):
        if SB_NOW_END in line:
            end_idx = i
            break
    end_idx = _estendi_a_sb_wait(lines, end_idx, header_re)
    in_fence = False
    in_html_comment = False
    header_lines: list[int] = []
    for i, line in enumerate(lines):



        clean = line.rstrip("\r")
        if clean.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue



        if in_html_comment:
            if "-->" in clean:
                in_html_comment = False
            continue
        if "<!--" in clean and "-->" not in clean:
            in_html_comment = True
            continue
        if header_re.match(clean) and i > end_idx:
            header_lines.append(i)
    if not header_lines:
        return text, []
    prefix = "\n".join(lines[: header_lines[0]]) + "\n"
    blocks: list[Block] = []
    for n, start in enumerate(header_lines):
        end = header_lines[n + 1] if n + 1 < len(header_lines) else len(lines)
        raw = "\n".join(lines[start:end])
        if end < len(lines):
            raw += "\n"
        blocks.append(Block(raw=raw, index=n))
    rebuilt = prefix + "".join(b.raw for b in blocks)
    if rebuilt != text:
        raise AssertionError("parser does not reconstruct the file byte-identical: abort")
    return prefix, blocks


def classify(
    blocks: list[Block],
    age_days: int,
    today: dt.date,
    force_headers: set[str],
    force_res: tuple[re.Pattern, ...] = (),
    stub_recent: bool = False,
    log_text: str = "",
) -> dict[str, list[Block]]:
    ""










    cutoff = today - dt.timedelta(days=age_days)
    out: dict[str, list[Block]] = {"move": [], "stub": [], "keep": [], "drop": []}
    datati_non_sessione: list[str] = []
    orfani: list[str] = []
    stub_scritti: list[str] = []

    def block_date(b: Block) -> dt.date | None:
        if b.date is None:
            return None
        try:
            return dt.date.fromisoformat(b.date)
        except ValueError:

            return None

    coda_tenuta: list[str] = []
    for b in blocks:



        if SB_WAIT_START in b.raw or SB_WAIT_END in b.raw:
            coda_tenuta.append(b.header)
            out["keep"].append(b)
            continue


        ref = b.stub_of
        if ref is not None:
            d = block_date(b)
            if d is not None and d < cutoff:
                if f"{ROTATED_MARK} sha256={ref} -->" in log_text:






                    if _stub_e_intatto(b):
                        out["drop"].append(b)
                    else:
                        stub_scritti.append(b.header)
                        out["keep"].append(b)
                else:



                    orfani.append(b.header)
                    out["keep"].append(b)
            else:
                out["keep"].append(b)
            continue


        forced = b.header in force_headers or any(rx.search(b.header) for rx in force_res)





        eligible = forced or b.is_session
        if not eligible:
            if b.date is not None:
                datati_non_sessione.append(b.header)
            out["keep"].append(b)
            continue
        d = block_date(b)
        if d is None:


            out["move" if forced else "keep"].append(b)
            continue
        if forced or d < cutoff:
            out["move"].append(b)
        elif stub_recent:
            out["stub"].append(b)
        else:
            out["keep"].append(b)

    for h in coda_tenuta:
        print(f"  [kept] contains the SB-WAIT queue, never archivable: {h[:70]}", file=sys.stderr)
    for h in datati_non_sessione:
        print(
            f"  [kept] dated header but not a session, NOT archived: {h[:70]}", file=sys.stderr
        )
    for h in orfani:
        print(
            f"  [kept] expired stub but original NOT found in archive: {h[:70]}",
            file=sys.stderr,
        )
    return out


def sort_for_log(archive: list[Block]) -> list[Block]:
    ""

    return sorted(archive, key=lambda b: (b.date or UNKNOWN_DATE, -b.index))


ROTATED_MARK = "<!-- SB-ROTATED"
ROTATED_RE = re.compile(r"^<!-- SB-ROTATED sha256=([0-9a-f]{64}) -->$")
ROTATED_END = "<!-- SB-ROTATED-END -->"


def build_log_appendix(archive: list[Block], now: str) -> str:
    ""


    banner = (
        "\n---\n\n"
        f"> ↓ Blocks rotated out of `live-state.md` on {now} with "
        "`tools/infrastructure/sb-state-rotate.py`.\n"
        "> Content VERBATIM (only the header changed from `##` to `###`).\n"
        "> Sorted by date: they may chronologically precede the historical entries "
        "above.\n"
    )
    parts = [banner]
    for b in sort_for_log(archive):
        parts.append(
            f"\n<!-- SB-ROTATED sha256={b.canon_sha} -->\n"
            "### " + b.header_text + "\n" + b.body.rstrip("\n") + "\n"
        )


    parts.append("\n" + ROTATED_END + "\n")
    return "".join(parts)


def parse_appendix(appendix: str) -> tuple[list[str], list[str]]:
    ""

    problems: list[str] = []
    shas: list[str] = []
    lines = appendix.split("\n")
    marks = [i for i, ln in enumerate(lines) if ln.startswith(ROTATED_MARK)]
    for n, start in enumerate(marks):
        if lines[start] == ROTATED_END:
            continue
        m = ROTATED_RE.match(lines[start])
        if not m:
            problems.append(f"malformed marker: {lines[start][:60]}")
            continue
        declared = m.group(1)
        end = marks[n + 1] if n + 1 < len(marks) else len(lines)
        chunk = lines[start + 1 : end]
        if not chunk or not chunk[0].startswith("### "):
            problems.append(f"block without ### header after the marker {declared[:16]}")
            continue
        canon = chunk[0].lstrip("#").strip() + "\n" + "\n".join(chunk[1:]).rstrip("\n")
        actual = sha256(canon)
        if actual != declared:
            problems.append(
                f"declared sha {declared[:16]} ≠ content {actual[:16]} ({chunk[0][:60]})"
            )
        shas.append(actual)
    return shas, problems


POINTER_MARK = "⤷ testo integrale in"


def _stub_e_intatto(b: Block, max_lines: int = 3) -> bool:
    ""











    righe = [ln for ln in b.body.split("\n") if ln.strip()]
    if not righe:
        return False
    puntatore = [i for i, ln in enumerate(righe) if POINTER_MARK in ln]
    if not puntatore:
        return False
    i = puntatore[-1]
    if i != len(righe) - 1:
        return False
    corpo = [ln for ln in righe[:i] if not ln.strip().startswith(STUB_MARK)]
    return len(corpo) <= max_lines


def build_stub(b: Block, max_lines: int, max_cols: int, log_rel: str) -> Block:
    ""







    body_lines: list[str] = []
    for ln in b.body.split("\n"):
        if not ln.strip():
            if body_lines:
                break
            continue
        if ln.strip().startswith("<!--"):
            continue
        s = ln.rstrip()
        if len(s) > max_cols:
            cut = s[:max_cols].rsplit(" ", 1)[0]
            s = (cut or s[:max_cols]) + " […]"
        body_lines.append(s)
        if len(body_lines) >= max_lines:
            break
    sha = b.canon_sha
    raw = (
        b.header
        + "\n"
        + f"<!-- SB-STUB sha256={sha} -->\n"
        + ("\n".join(body_lines) + "\n" if body_lines else "")
        + f"⤷ testo integrale in `{log_rel}` — cerca `sha256={sha[:16]}`\n\n"
    )
    return Block(raw=raw, index=b.index)




SCAFFOLD = (
    "\n## Active sessions / handoff (≤48h)\n\n"
    "> Only live work with an explicit deadline. The rest drops into the archive on its own.\n\n"
    "## Decisions awaiting the owner\n\n"
    "> What is waiting for the owner's reply. PENDING ≠ EXPIRED: if they still have to "
    "reply, it stays here.\n"
)


def build_new_live(prefix: str, body_blocks: list[Block], init_structure: bool) -> str:
    parts = [prefix]
    if init_structure:
        parts.append(SCAFFOLD)
        parts.append("\n## Latest sessions (≤7 days)\n\n")
        parts.append(
            "> Summary + sha256. Full text in "
            "`sbk/context/sessions/SESSION-LOG.md`; they expire on their own.\n\n"
        )
    parts.extend(b.raw for b in body_blocks)
    return "".join(parts)


def gate(
    orig_blocks: list[Block],
    plan: dict[str, list[Block]],
    new_live: str,
    old_log: str,
    new_log: str,
    old_live: str = "",
) -> list[str]:
    ""
    keep, moved, stubbed, dropped = plan["keep"], plan["move"], plan["stub"], plan["drop"]
    problems: list[str] = []
    if not new_log.startswith(old_log):
        problems.append("SESSION-LOG is not append-only: historical content would change")



    if old_live:
        prima = sb_wait_regione(old_live)
        dopo = sb_wait_regione(new_live)
        if prima is not None and dopo is None:
            problems.append(
                "the SB-WAIT queue was there before and is gone after: rotation would "
                "carry it away. The wait queue must not be moved by rotation"
            )
        elif prima is not None and dopo != prima:
            problems.append("the SB-WAIT queue changed: this script must not touch it")

    try:
        _, live_blocks = split_blocks(new_live, "##")
    except AssertionError as exc:
        return [f"new live-state not parsable: {exc}"]
    appendix = new_log[len(old_log) :]
    log_shas, appendix_problems = parse_appendix(appendix)
    problems.extend(appendix_problems)
    archived = moved + stubbed
    if len(log_shas) != len(archived):
        problems.append(f"appendix: expected {len(archived)} blocks, found {len(log_shas)}")
    log_sha_set = set(log_shas)


    for b in stubbed:
        if b.canon_sha not in log_sha_set:
            problems.append(f"STUB without original in archive: {b.header[:70]}")

    for b in live_blocks:
        if b.stub_of is not None and b.canon_sha in log_sha_set:
            problems.append(f"a STUB was appended to the archive: {b.header[:70]}")

    for b in live_blocks:
        ref = b.stub_of
        if ref is not None and ref not in log_sha_set and f"sha256={ref} -->" not in new_log:
            problems.append(f"STUB pointing at nothing (sha {ref[:16]}): {b.header[:70]}")




    found = Counter(b.canon_sha for b in live_blocks)
    found += Counter(log_shas)
    allowed_gone = Counter(b.canon_sha for b in dropped)
    for b in dropped:
        ref = b.stub_of
        if ref is None or f"{ROTATED_MARK} sha256={ref} -->" not in old_log:
            problems.append(f"deletion not proven, rejected: {b.header[:70]}")
    missing = Counter(b.canon_sha for b in orig_blocks) - found - allowed_gone
    if missing:
        by_sha = {b.canon_sha: b for b in orig_blocks}
        for h, n in missing.items():
            problems.append(f"LOST ({n}x): sha {h[:16]} — {by_sha[h].header[:80]}")

    keep_found = Counter(b.raw for b in live_blocks)
    keep_missing = Counter(b.raw for b in keep) - keep_found
    for raw, n in keep_missing.items():
        problems.append(f"kept block altered ({n}x): {raw.splitlines()[0][:80]}")
    return problems


def atomic_write(path: Path, content: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".tmp-")
    with open(fd, "w", encoding="utf-8") as f:
        f.write(content)
    Path(tmp).replace(path)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--apply", action="store_true", help="actually writes (default: dry-run)")
    ap.add_argument("--dry-run", action="store_true", help="explicit: plan only")
    ap.add_argument("--check", action="store_true", help="exit 1 if rotation is needed")



    ap.add_argument("--age-days", type=int, default=cfg.LIVESTATE_ROTATE_AGE_DAYS)
    ap.add_argument("--max-lines", type=int, default=LIVESTATE_MAX_LINES, help="--check threshold")
    ap.add_argument(
        "--max-kb", type=int, default=LIVESTATE_MAX_BYTES // 1024, help="--check threshold"
    )
    ap.add_argument("--init-structure", action="store_true")
    ap.add_argument("--force-archive", action="append", default=[], metavar="HEADER")
    ap.add_argument(
        "--force-archive-re",
        action="append",
        default=[],
        metavar="REGEX",
        help="like --force-archive but on a regex of the header (repeatable). "
        "Matches show in the dry-run BEFORE writing.",
    )
    ap.add_argument(
        "--stub-recent",
        action="store_true",
        help="recent sessions go to the archive anyway, and in live-state "
        "stay reduced to a few lines + pointer",
    )
    ap.add_argument("--stub-lines", type=int, default=3, help="summary lines per stub")
    ap.add_argument("--stub-cols", type=int, default=150, help="max width of a stub line")
    ap.add_argument("--live", type=Path, default=DEFAULT_LIVE)
    ap.add_argument("--log", type=Path, default=DEFAULT_LOG)
    args = ap.parse_args()
    if args.dry_run:
        args.apply = False

    lock_ctx = None
    if args.apply:
        lock_path = args.live.parent / ".sb-state-rotate.lock"
        lock_ctx = open(lock_path, "w")  # noqa: SIM115 — kept open for the flock
        try:
            fcntl.flock(lock_ctx, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("ABORT: another rotation is in progress (lock held)")
            return EXIT_RACE






    assert_lf(args.live.read_bytes().decode("utf-8", "replace"), str(args.live))
    assert_lf(args.log.read_bytes().decode("utf-8", "replace"), str(args.log))
    live_text = args.live.read_text(encoding="utf-8")
    log_text = args.log.read_text(encoding="utf-8")

    prefix, blocks = split_blocks(live_text, "##")
    today = dt.date.today()
    try:
        force_res = tuple(re.compile(r) for r in args.force_archive_re)
    except re.error as exc:
        raise SystemExit(f"ABORT: --force-archive-re invalid: {exc}") from exc
    plan = classify(
        blocks,
        args.age_days,
        today,
        set(args.force_archive),
        force_res,
        args.stub_recent,
        log_text,
    )
    archive = plan["move"] + plan["stub"]
    keep = plan["keep"]

    if args.check:
        errs = []
        if archive:
            errs.append(f"{len(archive)} blocks to rotate (older than {args.age_days}d)")
        if plan["drop"]:
            errs.append(f"{len(plan['drop'])} expired stubs to remove")


        n_lines = len(live_text.splitlines())
        n_kb = len(live_text.encode()) / 1024
        if n_lines > args.max_lines:
            errs.append(f"live-state {n_lines} lines > {args.max_lines}")
        if n_kb > args.max_kb:
            errs.append(f"live-state {n_kb:.0f} KB > {args.max_kb}")
        if errs:
            print("sb-state-rotate --check: " + " · ".join(errs))
            print(f"  fix: uv run python {Path(__file__).relative_to(REPO)} --apply")
            return EXIT_CHECK_FAIL
        print("sb-state-rotate --check: OK")
        return EXIT_OK

    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    appendix = build_log_appendix(archive, now) if archive else ""
    new_log = log_text + appendix
    try:
        log_rel = str(args.log.resolve().relative_to(REPO))
    except ValueError:
        log_rel = args.log.name
    stub_by_index = {
        b.index: build_stub(b, args.stub_lines, args.stub_cols, log_rel) for b in plan["stub"]
    }
    gone_idx = {b.index for b in plan["drop"]} | {b.index for b in plan["move"]}
    stub_idx = set(stub_by_index)
    body_blocks = [stub_by_index.get(b.index, b) for b in blocks if b.index not in gone_idx]
    new_live = build_new_live(prefix, body_blocks, args.init_structure)


    print(
        f"live-state: {len(blocks)} blocks · archive: {len(archive)} "
        f"(whole {len(plan['move'])} + reduced to stub {len(plan['stub'])}) · "
        f"{len(keep)} remain · expired stubs removed {len(plan['drop'])}"
    )
    for b in sort_for_log(archive):
        tag = b.date or "NO-DATE(force)"
        verb = "STUB    " if b.index in stub_idx else "ARCHIVE "
        print(f"  {verb} {tag}  {len(b.raw):>6}B  {b.canon_sha[:16]}  {b.header[:70]}")
    for b in plan["drop"]:
        print(f"  REMOVE   expired stub (original proven in archive)  {b.header[:70]}")
    for b in keep:
        print(f"  STAYS    {b.date or '—':<10}  {len(b.raw):>6}B  {b.header[:70]}")
    print(
        f"live-state: {live_text.count(chr(10))} → {new_live.count(chr(10))} lines · "
        f"{len(live_text.encode())} → {len(new_live.encode())} bytes"
    )
    print(
        f"SESSION-LOG: {log_text.count(chr(10))} → {new_log.count(chr(10))} lines "
        f"(+{len(appendix.encode())} bytes, append only)"
    )

    if not archive and not plan["drop"]:
        print("Nothing to rotate.")
        return EXIT_OK

    problems = gate(blocks, plan, new_live, log_text, new_log, old_live=live_text)
    if problems:
        print("\n❌ GATE FAILED — ZERO WRITES:")
        for p in problems:
            print("   " + p)
        return EXIT_GATE_FAIL
    print(
        "✅ GATE OK: every original block still exists (sha256 verified), "
        "SESSION-LOG history intact, kept blocks byte-identical."
    )

    if not args.apply:
        print("(dry-run: no writes; use --apply to run)")
        return EXIT_OK


    if args.live.read_text(encoding="utf-8") != live_text or (
        args.log.read_text(encoding="utf-8") != log_text
    ):
        print("ABORT: a file changed during computation (concurrent sessions). Re-run.")
        return EXIT_RACE

    ts = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    for p in (args.live, args.log):
        shutil.copy2(p, p.with_name(p.name + f".bak-rotate-{ts}"))

    atomic_write(args.log, new_log)
    atomic_write(args.live, new_live)
    print(f"Written. Backup: *.bak-rotate-{ts} next to the original files.")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
