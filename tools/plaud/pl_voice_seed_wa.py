#!/usr/bin/env python3
"""Seeds a clean voice registry from the voice notes in your WhatsApp exports: clips of each 1:1 contact and of you,
matched to the knowledge base.

It reads the exports under <data root>/whatsapp only. To read exports kept somewhere else (for example an unzipped
export in ~/Downloads), name that folder: --folder PATH (repeatable). No other folder is ever walked.

Usage: uv run python tools/plaud/pl_voice_seed_wa.py {scan,build,show} [--folder PATH ...]
"""

from __future__ import annotations

import json
import os
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

try:
    from tools.plaud import pl_voice_encoder as enc
except ImportError:  # pragma: no cover
    import pl_voice_encoder as enc  # type: ignore[no-redef]

_HOME = Path.home()
# Only the data root by default; other folders are read only when you pass them (--folder).
WA_ROOTS = [
    Path(os.environ.get("SBK_DATA_ROOT") or _HOME / ".sbk-data").expanduser() / "whatsapp",
]
CLEAN_REGISTRY_PATH = (
    Path(os.environ.get("SBK_DATA_ROOT") or _HOME / ".sbk-data").expanduser()
    / "plaud"
    / "_voice_registry_clean.json"
)


_ATTACH_RE = re.compile(r"\]\s+([^:]{2,40}?):\s*‎?<attached:\s*([^>]+\.opus)>")

_SENDER_RE = re.compile(r"\]\s+([^:]{2,40}?):\s")
# You as a sender in your WhatsApp exports (sbk.config.json owner / own_names).
try:
    from sbk_config import OWNER_LABEL, owner_name_regex
except ImportError:  # pragma: no cover
    from tools.sbk_config import OWNER_LABEL, owner_name_regex  # type: ignore[no-redef]
_SELF_RE = re.compile(rf"\b{owner_name_regex()}\b", re.IGNORECASE)

_NUM_RE = re.compile(r"^~?\+?[\d\s]+$")


def _norm_key(name: str) -> str:
    s = unicodedata.normalize("NFKD", name)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(s.lower().replace("-", " ").split())


def find_chat_files(roots: list[Path] | None = None) -> list[Path]:
    ""
    roots = roots or WA_ROOTS
    seen: set[str] = set()
    out: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        for chatf in root.glob("**/_chat.txt"):
            d = str(chatf.parent)
            if d in seen:
                continue
            seen.add(d)
            out.append(chatf)
    return out


def parse_chat(chatf: Path) -> dict[str, Any]:
    ""


    txt = chatf.read_text(encoding="utf-8", errors="ignore")
    senders: dict[str, int] = {}
    for m in _SENDER_RE.finditer(txt):
        s = m.group(1).strip()
        senders[s] = senders.get(s, 0) + 1
    audio: dict[str, list[str]] = {}
    for m in _ATTACH_RE.finditer(txt):
        s = m.group(1).strip()
        f = m.group(2).strip()
        p = chatf.parent / f
        if p.exists():
            audio.setdefault(s, []).append(str(p))
    others = [s for s in senders if not _SELF_RE.search(s)]
    counterpart = others[0] if len(others) == 1 else None
    return {
        "senders": senders,
        "audio": audio,
        "is_1to1": len(senders) == 2,
        "counterpart": counterpart,
    }


def collect_person_clips(
    roots: list[Path] | None = None,
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    ""




    people: dict[str, dict[str, Any]] = {}
    self_clips: list[str] = []
    for chatf in find_chat_files(roots):
        info = parse_chat(chatf)

        for sender, clips in info["audio"].items():
            if _SELF_RE.search(sender):
                self_clips.extend(clips)
        if not info["is_1to1"]:
            continue
        cp = info["counterpart"]
        if not cp or _NUM_RE.match(cp):
            continue
        clips = info["audio"].get(cp, [])
        if not clips:
            continue
        key = _norm_key(cp)
        entry = people.setdefault(key, {"name": cp, "clips": [], "chats": []})
        entry["clips"].extend(clips)
        entry["chats"].append(chatf.parent.name)
    return people, self_clips


def _resolve_entity(name: str) -> str | None:
    ""
    try:
        from tools.plaud.pl_name_index import load_or_build

        idx = load_or_build()
        ids = idx.lookup(name) if hasattr(idx, "lookup") else idx.get(_norm_key(name))
        if ids:
            return list(ids)[0] if not isinstance(ids, str) else ids
    except Exception:  # noqa: BLE001
        pass
    return None


def build_clean_registry(
    *,
    roots: list[Path] | None = None,
    max_clips: int = 15,
    min_clips: int = 2,
    encoder: Any = None,
    resolve_kb: bool = True,
) -> dict[str, Any]:
    ""
    import numpy as np  # noqa: F401

    people, self_clips = collect_person_clips(roots)
    entries: list[dict[str, Any]] = []

    def _add(name: str, clips: list[str], chats: list[str]) -> None:
        clips = clips[:max_clips]
        if len(clips) < min_clips:
            return
        try:
            vec = enc.embed_files_mean(clips, encoder=encoder)
        except enc.VoiceEncoderError:
            return
        entries.append(
            {
                "name": name,
                "key": _norm_key(name),
                "entity_id": _resolve_entity(name) if resolve_kb else None,
                "vec": [round(float(x), 6) for x in vec],
                "n_clips": len(clips),
                "source": "whatsapp",
                "chats": sorted(set(chats)),
            }
        )

    for entry in people.values():
        _add(entry["name"], entry["clips"], entry["chats"])
    if self_clips:
        _add(OWNER_LABEL, self_clips, ["<self>"])

    return {
        "version": 1,
        "n_people": len(entries),
        "max_clips": max_clips,
        "entries": entries,
    }


def seed_incremental(
    *,
    roots: list[Path] | None = None,
    max_clips: int = 15,
    min_clips: int = 2,
    encoder: Any = None,
    resolve_kb: bool = True,
    resume: bool = True,
    path: Path | None = None,
    on_progress: Any = None,
) -> dict[str, Any]:
    ""



    dest = path or CLEAN_REGISTRY_PATH
    reg = load_clean_registry(dest) if resume else {}
    entries: list[dict[str, Any]] = list(reg.get("entries", [])) if reg else []
    done_keys = {e.get("key") for e in entries}

    def _persist() -> None:
        save_clean_registry(
            {"version": 1, "n_people": len(entries), "max_clips": max_clips, "entries": entries},
            dest,
        )

    def _add(name: str, clips: list[str], chats: list[str]) -> None:
        key = _norm_key(name)
        if key in done_keys:
            return
        clips = clips[:max_clips]
        if len(clips) < min_clips:
            return
        try:
            vec = enc.embed_files_mean(clips, encoder=encoder)
        except enc.VoiceEncoderError:
            return
        entries.append(
            {
                "name": name,
                "key": key,
                "entity_id": _resolve_entity(name) if resolve_kb else None,
                "vec": [round(float(x), 6) for x in vec],
                "n_clips": len(clips),
                "source": "whatsapp",
                "chats": sorted(set(chats)),
            }
        )
        done_keys.add(key)
        _persist()
        if on_progress:
            on_progress(name, len(clips))

    people, self_clips = collect_person_clips(roots)
    for entry in people.values():
        _add(entry["name"], entry["clips"], entry["chats"])
    if self_clips:
        _add(OWNER_LABEL, self_clips, ["<self>"])

    return {"version": 1, "n_people": len(entries), "max_clips": max_clips, "entries": entries}


def save_clean_registry(registry: dict[str, Any], path: Path | None = None) -> Path:
    dest = path or CLEAN_REGISTRY_PATH
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    tmp.write_text(json.dumps(registry, ensure_ascii=False), encoding="utf-8")
    tmp.replace(dest)
    return dest


def load_clean_registry(path: Path | None = None) -> dict[str, Any]:
    dest = path or CLEAN_REGISTRY_PATH
    if not dest.exists():
        return {}
    return json.loads(dest.read_text(encoding="utf-8"))


def _main() -> int:
    import argparse

    ap = argparse.ArgumentParser(
        description="Seed a clean voice registry from the voice notes of your WhatsApp exports "
        "(<data root>/whatsapp; other folders only with --folder)"
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    cartella = argparse.ArgumentParser(add_help=False)
    cartella.add_argument(
        "--folder",
        action="append",
        type=Path,
        default=[],
        metavar="PATH",
        help="also read the WhatsApp exports in this folder (repeatable); nothing else is walked",
    )
    sub.add_parser("scan", parents=[cartella])
    pb = sub.add_parser("build", parents=[cartella])
    pb.add_argument("--max-clips", type=int, default=15)
    sub.add_parser("show")
    args = ap.parse_args()
    roots = [*WA_ROOTS, *(p.expanduser() for p in getattr(args, "folder", []))]

    if args.cmd == "scan":
        people, self_clips = collect_person_clips(roots)
        print(f"People (1:1 contacts with voice notes): {len(people)}")
        for k, e in sorted(people.items(), key=lambda x: -len(x[1]["clips"])):
            print(f"  {e['name']:30} {len(e['clips']):>4} voice notes  chats={e['chats']}")
        print(f"Your voice notes (self): {len(self_clips)}")
    elif args.cmd == "build":

        def _prog(name, n):
            print(f"  [ok] {name:30} {n:>3} clip  (saved)", flush=True)

        print("Incremental build (resume on, saves after each person)...", flush=True)
        reg = seed_incremental(
            roots=roots, max_clips=args.max_clips, resume=True, on_progress=_prog
        )
        print(f"Clean registry: {CLEAN_REGISTRY_PATH}  ({reg['n_people']} people)")
    elif args.cmd == "show":
        reg = load_clean_registry()
        if not reg:
            print("No clean registry. Run 'build'.")
            return 1
        print(f"People: {reg['n_people']}")
        for e in reg["entries"]:
            print(f"  {e['name']:30} {e['n_clips']:>3} clip  entity={e['entity_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
