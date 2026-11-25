#!/usr/bin/env python3
""




















from __future__ import annotations

import json
import sys
import time
from pathlib import Path

LKL_PERSON_DIR = Path.home() / ".sbk-data" / "knowledge" / "entities" / "person"
NAME_INDEX_PATH = Path.home() / ".sbk-data" / "clickup-lkl-name-index.json"
NAME_INDEX_TTL_SECS = 86400


def _norm(s: str) -> str:
    return (s or "").strip().lower()


def _is_composite_name(canonical_name: str) -> bool:
    ""







    if not canonical_name:
        return True
    if "," in canonical_name:
        return True
    if " / " in canonical_name or " & " in canonical_name:
        return True
    if "(" in canonical_name and ")" in canonical_name:
        return True
    if "team" in canonical_name.lower() or "group" in canonical_name.lower():
        return True
    return False


def _load_name_index() -> dict | None:
    ""
    if not NAME_INDEX_PATH.exists():
        return None
    age = time.time() - NAME_INDEX_PATH.stat().st_mtime
    if age > NAME_INDEX_TTL_SECS:
        return None
    try:
        return json.loads(NAME_INDEX_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _save_name_index(index: dict) -> None:
    NAME_INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    NAME_INDEX_PATH.write_text(json.dumps(index, indent=2))


def build_name_index() -> dict:
    ""




    cached = _load_name_index()
    if cached is not None:
        return cached

    index: dict = {}
    if not LKL_PERSON_DIR.exists():
        return {"_error": f"LKL person dir not found: {LKL_PERSON_DIR}"}

    for f in LKL_PERSON_DIR.glob("person_*.json"):
        try:
            p = json.loads(f.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        cn = p.get("canonical_name", "")
        if _is_composite_name(cn):
            continue
        eid = p.get("entity_id", "")
        if not eid:
            continue

        index[_norm(cn)] = eid

    _save_name_index(index)
    return index


def _load_person_profile(person_id: str) -> dict | None:
    ""
    path = LKL_PERSON_DIR / f"{person_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def lookup_person(name: str) -> dict | None:
    ""



    index = build_name_index()
    if "_error" in index:
        return None

    name_n = _norm(name)
    if not name_n:
        return None


    if name_n in index:
        return _load_person_profile(index[name_n])


    candidates = [(cn, pid) for cn, pid in index.items() if name_n in cn]
    if not candidates:
        return None


    candidates.sort(key=lambda x: len(x[0]))
    return _load_person_profile(candidates[0][1])


def get_employment_status(name: str) -> dict:
    ""




    profile = lookup_person(name)
    if profile is None:
        return {"found": False, "reason": f"Profile non trovato in LKL per '{name}'"}

    out: dict = {
        "found": True,
        "canonical_name": profile.get("canonical_name", ""),
        "entity_id": profile.get("entity_id", ""),
        "status": None,
        "current_role": None,
        "email": None,
        "expired_at": None,
        "hire_date": None,




        "facts": profile.get("facts", []),
    }


    for fact in profile.get("facts", []):
        attr = fact.get("attribute", "")
        if fact.get("expired_at"):
            continue
        if attr == "employment.status":







            out["status"] = fact.get("value")
        elif attr == "employment.current_role":
            out["current_role"] = fact.get("value")
        elif attr == "contact.email" and out["email"] is None:
            out["email"] = fact.get("value")
        elif attr == "employment.hire_date":
            out["hire_date"] = fact.get("value")

    return out


def is_person_active(name: str) -> bool:
    ""







    info = get_employment_status(name)
    if not info.get("found"):






        return True







    fatti = info.get("facts") or []
    if fatti:
        try:
            import sys as _sys
            from pathlib import Path as _P

            _r = _P(__file__).resolve().parents[1]
            if str(_r) not in _sys.path:
                _sys.path.insert(0, str(_r))
            from knowledge_view import verdetto_stato

            return verdetto_stato(fatti).esito != "CHIUSO"
        except Exception:  # noqa: BLE001 — se il modulo non c'è si prosegue col criterio vecchio
            pass

    status = (info.get("status") or "").lower().strip()
    if status in ("terminated", "inactive", "left", "exit", "former", "resigned", "cessato"):
        return False
    return True


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: lkl_role_query.py '<canonical_name>'", file=sys.stderr)
        return 1
    name = sys.argv[1]
    info = get_employment_status(name)
    info["is_active"] = is_person_active(name)
    print(json.dumps(info, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
