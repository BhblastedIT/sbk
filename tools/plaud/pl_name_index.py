#!/usr/bin/env python3
""
































from __future__ import annotations

import json
import re
import time
import unicodedata
from collections.abc import Iterable
from pathlib import Path
from typing import Any





try:
    from sbk_config import KNOWLEDGE_ENTITIES_DIR, PLAUD_DIR

    _PERSON_DIR = KNOWLEDGE_ENTITIES_DIR / "person"
    _DEFAULT_CACHE = PLAUD_DIR.parent / "pl-name-index.json"
except Exception:  # pragma: no cover - fallback when sbk_config is not on path
    _PERSON_DIR = Path.home() / ".sbk-data" / "knowledge" / "entities" / "person"
    _DEFAULT_CACHE = Path.home() / ".sbk-data" / "plaud" / "pl-name-index.json"

CACHE_TTL_SECS = 86400


_NAME_ATTRS = frozenset(
    {
        "identity.name",
        "identity.alias",
        "identity.full_name",
        "identity.nickname",
        "relationship.nickname",
    }
)






_COMPOSITE_RE = re.compile(
    r"""
    ,                    |  # comma: "Sam, Mia" / "Clutch, Agency Partner"
    \s+/\s+              |  # slash: "Mario / Dana"
    \s+&\s+             |  # spaced ampersand: "Sam & Mia"
    \band\b(?=\s+\w)    |  # English "and" followed by a word
    \s+\be\b\s+            # isolated Italian "e" between two words
    """,
    re.VERBOSE | re.IGNORECASE,
)


_AGGREGATE_TOKENS = frozenset({"team", "group", "gruppo", "staff", "dept", "department"})



_ALLOWED_NAME_RE = re.compile(r"^[a-z][a-z .'\-]*$")


def strip_accents(s: str) -> str:
    ""
    nfkd = unicodedata.normalize("NFKD", s)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def norm_name(s: str | None) -> str:
    ""


    if not s:
        return ""
    out = strip_accents(str(s)).lower().strip()
    out = re.sub(r"\s+", " ", out)
    return out


def is_composite_name(name: str | None) -> bool:
    ""







    if not name or not name.strip():
        return True

    raw = name.strip()


    if "(" in raw or ")" in raw:
        return True


    if _COMPOSITE_RE.search(raw):
        return True

    low = strip_accents(raw).lower()


    if _AGGREGATE_TOKENS & set(re.findall(r"[a-z]+", low)):
        return True


    if not _ALLOWED_NAME_RE.match(low):
        return True


    alpha = [c for c in low if c.isalpha()]
    if len(alpha) < 2:
        return True

    return False







def iter_profile_names(profile: dict[str, Any]) -> set[str]:
    ""



    names: set[str] = set()
    cn = profile.get("canonical_name")
    if cn:
        names.add(str(cn).strip())
    for fact in profile.get("facts", []) or []:
        if not isinstance(fact, dict):
            continue
        if fact.get("attribute") in _NAME_ATTRS:
            val = fact.get("value")
            if val and isinstance(val, str):
                names.add(val.strip())
    return names







class NameIndex:
    ""








    def __init__(self) -> None:
        self.full: dict[str, set[str]] = {}
        self.first: dict[str, set[str]] = {}
        self.alias: dict[str, set[str]] = {}



    def _add(self, bucket: dict[str, set[str]], key: str, entity_id: str) -> None:
        if not key or not entity_id:
            return
        bucket.setdefault(key, set()).add(entity_id)

    def add_profile(self, profile: dict[str, Any]) -> bool:
        ""


        if profile.get("merged_into"):
            return False
        entity_id = profile.get("entity_id")
        if not entity_id:
            return False

        canonical_raw = profile.get("canonical_name")
        canonical_norm = norm_name(canonical_raw)

        added = False
        for raw in iter_profile_names(profile):
            if is_composite_name(raw):
                continue
            key = norm_name(raw)
            if not key:
                continue
            self._add(self.full, key, entity_id)
            first = key.split(" ", 1)[0]
            self._add(self.first, first, entity_id)
            if key != canonical_norm:
                self._add(self.alias, key, entity_id)
            added = True
        return added



    def lookup(self, name: str) -> set[str]:
        ""



        return set(self.full.get(norm_name(name), set()))

    def lookup_first(self, first_name: str) -> set[str]:
        ""


        return set(self.first.get(norm_name(first_name), set()))

    def resolve(self, mention: str) -> set[str]:
        ""


        exact = self.lookup(mention)
        if exact:
            return exact
        norm = norm_name(mention)
        if norm and " " not in norm:
            return self.lookup_first(norm)
        return set()



    def __len__(self) -> int:
        ""
        return len(self.full)

    def entity_ids(self) -> set[str]:
        ""
        out: set[str] = set()
        for ids in self.full.values():
            out |= ids
        return out



    def to_dict(self) -> dict[str, Any]:
        ""

        def dump(bucket: dict[str, set[str]]) -> dict[str, list[str]]:
            return {k: sorted(v) for k, v in bucket.items()}

        return {
            "_schema": 1,
            "full": dump(self.full),
            "first": dump(self.first),
            "alias": dump(self.alias),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> NameIndex:
        idx = cls()

        def load(bucket: dict[str, list[str]]) -> dict[str, set[str]]:
            return {k: set(v) for k, v in (bucket or {}).items()}

        idx.full = load(d.get("full", {}))
        idx.first = load(d.get("first", {}))
        idx.alias = load(d.get("alias", {}))
        return idx







def build_index(profiles: Iterable[dict[str, Any]]) -> NameIndex:
    ""
    idx = NameIndex()
    for profile in profiles:
        if isinstance(profile, dict):
            idx.add_profile(profile)
    return idx


def _iter_profiles_from_dir(person_dir: Path) -> Iterable[dict[str, Any]]:
    ""
    if not person_dir.exists():
        return
    for f in sorted(person_dir.glob("person_*.json")):
        try:
            yield json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            continue


def build_index_from_dir(person_dir: Path | None = None) -> NameIndex:
    ""
    person_dir = person_dir or _PERSON_DIR
    return build_index(_iter_profiles_from_dir(person_dir))


def _cache_fresh(cache_path: Path, ttl: int) -> bool:
    if not cache_path.exists():
        return False
    return (time.time() - cache_path.stat().st_mtime) <= ttl


def load_or_build(
    person_dir: Path | None = None,
    cache_path: Path | None = None,
    ttl: int = CACHE_TTL_SECS,
    force_rebuild: bool = False,
) -> NameIndex:
    ""


    person_dir = person_dir or _PERSON_DIR
    cache_path = cache_path or _DEFAULT_CACHE

    if not force_rebuild and _cache_fresh(cache_path, ttl):
        try:
            return NameIndex.from_dict(json.loads(cache_path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError, KeyError):
            pass

    idx = build_index_from_dir(person_dir)
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = cache_path.with_name(cache_path.name + ".tmp")
        tmp.write_text(json.dumps(idx.to_dict(), ensure_ascii=False), encoding="utf-8")
        tmp.rename(cache_path)
    except OSError:
        pass
    return idx







def _main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Lookup name -> entity_id in the Knowledge Layer")
    ap.add_argument("name", help="name or first-name to look up")
    ap.add_argument("--rebuild", action="store_true", help="force rebuild ignoring the cache")
    args = ap.parse_args()

    idx = load_or_build(force_rebuild=args.rebuild)
    exact = sorted(idx.lookup(args.name))
    first = sorted(idx.lookup_first(args.name.split()[0] if args.name else ""))
    print(
        json.dumps(
            {
                "query": args.name,
                "indexed_names": len(idx),
                "exact_match": exact,
                "first_name_match": first,
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
