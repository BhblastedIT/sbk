""



























from __future__ import annotations

import json
import logging
import re
import sys
import time
import unicodedata
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from sbk_config import (
    ENRICHED_DIR,
    KNOWLEDGE_ENTITIES_DIR,
    OWNER_NAME,
    RQ_DIR,
)

log = logging.getLogger("rq.entity_bridge")



ENTITY_MAP_PATH = ENRICHED_DIR / "entity-map.json"
CONTACTS_MERGED_PATH = ENRICHED_DIR / "contacts-merged.parquet"
KNOWLEDGE_PERSON_DIR = KNOWLEDGE_ENTITIES_DIR / "person"
PEOPLE_UNIVERSE_PATH = ENRICHED_DIR / "people-universe.parquet"
ENTITY_OVERRIDES_PATH = RQ_DIR / "entity-overrides.json"
NON_PERSON_BLOCKLIST_PATH = RQ_DIR / "non-person-blocklist.json"
BRIDGE_OUTPUT_PATH = RQ_DIR / "entity-bridge.json"




_GROUP_KEYWORDS = frozenset(
    {
        "team",
        "group",
        "company",
        "srl",
        "s.r.l.",
        "spa",
        "s.p.a.",
        "ltd",
        "llc",
        "inc",
        "corp",
        "gmbh",
        "sarl",
        "colleagues",
        "department",
        "division",
        "committee",
    }
)


_MULTI_PERSON_RE = re.compile(
    r"^[A-Z][a-z]+\s+[A-Z][a-z]+\s*,\s*[A-Z][a-z]+",
    re.UNICODE,
)


def is_group_entity(canonical_name: str) -> bool:
    ""








    if not canonical_name or not canonical_name.strip():
        return True

    name = canonical_name.strip()


    name_lower = name.lower()
    for kw in _GROUP_KEYWORDS:

        if re.search(rf"\b{re.escape(kw)}\b", name_lower):
            return True


    if "," in name:
        parts = [p.strip() for p in name.split(",") if p.strip()]

        person_like_parts = 0
        for part in parts:
            words = part.split()
            if len(words) >= 2 and all(w[0].isupper() for w in words if w):
                person_like_parts += 1

        if person_like_parts >= 2:
            return True


    if _MULTI_PERSON_RE.match(name):
        return True

    return False





def _normalize_name(name: str) -> str:
    ""
    if not name:
        return ""
    name = name.strip().lower()

    nfkd = unicodedata.normalize("NFKD", name)
    name = "".join(c for c in nfkd if not unicodedata.combining(c))

    name = " ".join(name.split())
    return name


def _normalize_email(email: str) -> str:
    ""
    if not email:
        return ""
    return email.strip().lower()


def _name_parts(name: str) -> set[str]:
    ""
    return set(name.split())





def build_entity_bridge(
    entity_map_path: str | Path | None = None,
    contacts_merged_path: str | Path | None = None,
    knowledge_dir: str | Path | None = None,
    people_universe_path: str | Path | None = None,
    overrides_path: str | Path | None = None,
    blocklist_path: str | Path | None = None,
) -> dict[str, str]:
    ""












    em_path = Path(entity_map_path) if entity_map_path else ENTITY_MAP_PATH
    cm_path = Path(contacts_merged_path) if contacts_merged_path else CONTACTS_MERGED_PATH
    k_dir = Path(knowledge_dir) if knowledge_dir else KNOWLEDGE_PERSON_DIR
    pu_path = Path(people_universe_path) if people_universe_path else PEOPLE_UNIVERSE_PATH
    ov_path = Path(overrides_path) if overrides_path else ENTITY_OVERRIDES_PATH
    bl_path = Path(blocklist_path) if blocklist_path else NON_PERSON_BLOCKLIST_PATH

    bridge: dict[str, str] = {}
    stats = {
        "overrides": 0,
        "entity_map_emails": 0,
        "contacts_merged_names": 0,
        "contacts_merged_emails": 0,
        "knowledge_email_linked": 0,
        "knowledge_name_linked": 0,
        "knowledge_unlinked": 0,
        "knowledge_group_skipped": 0,
        "people_universe_linked": 0,
        "people_universe_unlinked": 0,
        "people_universe_group_skipped": 0,
        "blocklist_removed": 0,
    }

    t0 = time.monotonic()


    if ov_path.exists():
        try:
            raw = json.loads(ov_path.read_text(encoding="utf-8"))

            override_data = raw.get("overrides", raw) if isinstance(raw, dict) else {}
            for src_id, target_pid in override_data.items():
                if not isinstance(target_pid, str):
                    continue
                bridge[src_id.lower().strip()] = target_pid
                stats["overrides"] += 1
            log.info("Loaded %d entity overrides from %s", stats["overrides"], ov_path)
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("Failed to load overrides from %s: %s", ov_path, exc)
    else:
        log.debug("No entity overrides file at %s", ov_path)



    email_to_pid: dict[str, str] = {}

    if em_path.exists():
        try:
            entity_map = json.loads(em_path.read_text(encoding="utf-8"))
            for email_key, entry in entity_map.items():
                pid = entry.get("person_id", "")
                if not pid:
                    continue

                email_norm = _normalize_email(email_key)
                if email_norm:
                    if email_norm not in bridge:
                        bridge[email_norm] = pid
                    email_to_pid[email_norm] = pid
                    stats["entity_map_emails"] += 1


                for alt_email in entry.get("all_emails", []):
                    alt_norm = _normalize_email(alt_email)
                    if alt_norm and alt_norm not in bridge:
                        bridge[alt_norm] = pid
                        email_to_pid[alt_norm] = pid
                        stats["entity_map_emails"] += 1


                cn = entry.get("canonical_name", "")
                if cn:
                    cn_norm = _normalize_name(cn)
                    if cn_norm and cn_norm not in bridge:
                        bridge[cn_norm] = pid

            log.info(
                "Loaded entity-map: %d email mappings from %s",
                stats["entity_map_emails"],
                em_path,
            )
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("Failed to load entity-map from %s: %s", em_path, exc)
    else:
        log.warning("Entity-map not found at %s", em_path)


    name_to_pid: dict[str, str] = {}

    if cm_path.exists():
        try:
            import pandas as pd

            cm = pd.read_parquet(
                cm_path,
                columns=["person_id", "name", "email", "all_emails"],
            )

            for _, row in cm.iterrows():
                pid = str(row.get("person_id", ""))
                if not pid or not pid.startswith("p_"):
                    continue


                if pid not in bridge:
                    bridge[pid] = pid


                name = str(row.get("name", "")) if pd.notna(row.get("name")) else ""
                if name:
                    name_norm = _normalize_name(name)
                    if name_norm and name_norm not in bridge:
                        bridge[name_norm] = pid
                        stats["contacts_merged_names"] += 1

                    if name_norm:
                        name_to_pid[name_norm] = pid


                email = str(row.get("email", "")) if pd.notna(row.get("email")) else ""
                if email:
                    email_norm = _normalize_email(email)
                    if email_norm and email_norm not in bridge:
                        bridge[email_norm] = pid
                        email_to_pid[email_norm] = pid
                        stats["contacts_merged_emails"] += 1


                all_emails_raw = row.get("all_emails")
                if pd.notna(all_emails_raw):
                    if isinstance(all_emails_raw, str):
                        try:
                            all_emails_list = json.loads(all_emails_raw)
                        except (json.JSONDecodeError, TypeError):
                            all_emails_list = [all_emails_raw]
                    elif isinstance(all_emails_raw, list):
                        all_emails_list = all_emails_raw
                    else:
                        all_emails_list = []

                    for alt_email in all_emails_list:
                        alt_norm = _normalize_email(str(alt_email))
                        if alt_norm and alt_norm not in bridge:
                            bridge[alt_norm] = pid
                            email_to_pid[alt_norm] = pid
                            stats["contacts_merged_emails"] += 1

            log.info(
                "Loaded contacts-merged: %d names, %d emails from %s",
                stats["contacts_merged_names"],
                stats["contacts_merged_emails"],
                cm_path,
            )
        except Exception as exc:
            log.warning("Failed to load contacts-merged from %s: %s", cm_path, exc)
    else:
        log.warning("Contacts-merged not found at %s", cm_path)


    if k_dir.exists() and k_dir.is_dir():
        knowledge_files = list(k_dir.glob("*.json"))
        log.info("Processing %d knowledge entity files from %s", len(knowledge_files), k_dir)

        for kf in knowledge_files:
            try:
                data = json.loads(kf.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue

            entity_id = data.get("entity_id", "")
            canonical_name = data.get("canonical_name", "")

            if not entity_id:
                continue


            if is_group_entity(canonical_name):
                stats["knowledge_group_skipped"] += 1
                continue


            if entity_id in bridge:
                continue


            email_facts = [
                f for f in data.get("facts", []) if f.get("attribute") == "contact.email"
            ]
            linked_pid = None
            for ef in email_facts:
                email_val = _normalize_email(str(ef.get("value", "")))
                if email_val and email_val in email_to_pid:
                    linked_pid = email_to_pid[email_val]
                    break

            if linked_pid:
                bridge[entity_id] = linked_pid
                stats["knowledge_email_linked"] += 1
            else:

                cn_norm = _normalize_name(canonical_name)
                if cn_norm and cn_norm in name_to_pid:
                    bridge[entity_id] = name_to_pid[cn_norm]
                    stats["knowledge_name_linked"] += 1
                else:

                    bridge[entity_id] = entity_id
                    stats["knowledge_unlinked"] += 1


            if canonical_name:
                cn_norm = _normalize_name(canonical_name)
                if cn_norm and cn_norm not in bridge:
                    bridge[cn_norm] = bridge.get(entity_id, entity_id)

    else:
        log.warning("Knowledge person dir not found at %s", k_dir)


    if pu_path.exists():
        try:
            import pandas as pd

            pu = pd.read_parquet(pu_path, columns=["person_id", "canonical_name", "emails"])

            for _, row in pu.iterrows():
                pu_id = str(row.get("person_id", ""))
                if not pu_id or not pu_id.startswith("pu_"):
                    continue

                cn = (
                    str(row.get("canonical_name", ""))
                    if pd.notna(row.get("canonical_name"))
                    else ""
                )


                if is_group_entity(cn):
                    stats["people_universe_group_skipped"] += 1
                    continue


                if pu_id in bridge:
                    continue


                emails_raw = row.get("emails")
                linked_pid = None
                if pd.notna(emails_raw):
                    if isinstance(emails_raw, str):
                        try:
                            emails_list = json.loads(emails_raw)
                        except (json.JSONDecodeError, TypeError):
                            emails_list = [emails_raw] if emails_raw else []
                    elif isinstance(emails_raw, list):
                        emails_list = emails_raw
                    else:
                        emails_list = []

                    for em in emails_list:
                        em_norm = _normalize_email(str(em))
                        if em_norm and em_norm in email_to_pid:
                            linked_pid = email_to_pid[em_norm]
                            break

                if linked_pid:
                    bridge[pu_id] = linked_pid
                    stats["people_universe_linked"] += 1
                else:

                    cn_norm = _normalize_name(cn)
                    if cn_norm and cn_norm in name_to_pid:
                        bridge[pu_id] = name_to_pid[cn_norm]
                        stats["people_universe_linked"] += 1
                    else:

                        bridge[pu_id] = pu_id
                        stats["people_universe_unlinked"] += 1

            log.info(
                "Loaded people-universe: %d linked, %d unlinked, %d group-skipped",
                stats["people_universe_linked"],
                stats["people_universe_unlinked"],
                stats["people_universe_group_skipped"],
            )
        except Exception as exc:
            log.warning("Failed to load people-universe from %s: %s", pu_path, exc)
    else:
        log.debug("People-universe not found at %s", pu_path)


    if bl_path.exists():
        try:
            blocklist = json.loads(bl_path.read_text(encoding="utf-8"))
            blocked_ids = set()
            if isinstance(blocklist, list):
                blocked_ids = {b.strip().lower() for b in blocklist if isinstance(b, str)}
            elif isinstance(blocklist, dict):
                blocked_ids = {k.strip().lower() for k in blocklist}

            to_remove = []
            for key, val in bridge.items():
                val_str = val if isinstance(val, str) else str(val)
                if key.lower() in blocked_ids or val_str.lower() in blocked_ids:
                    to_remove.append(key)

            for key in to_remove:
                del bridge[key]
                stats["blocklist_removed"] += 1

            log.info("Blocklist removed %d entries", stats["blocklist_removed"])
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("Failed to load blocklist from %s: %s", bl_path, exc)
    else:
        log.debug("No blocklist file at %s", bl_path)

    elapsed = time.monotonic() - t0
    log.info("Entity bridge built in %.1fs: %d total mappings", elapsed, len(bridge))
    log.info("Bridge stats: %s", json.dumps(stats, indent=2))




    changed = True
    max_iterations = 5
    iteration = 0
    while changed and iteration < max_iterations:
        changed = False
        iteration += 1
        for key in list(bridge.keys()):
            if key.startswith("__"):
                continue
            val = bridge[key]
            if isinstance(val, str) and val in bridge and bridge[val] != val:
                next_val = bridge[val]
                if isinstance(next_val, str) and next_val != val:
                    bridge[key] = next_val
                    changed = True
    if iteration > 1:
        log.info("Chain resolution: %d iterations", iteration)


    bridge["__stats__"] = json.dumps(stats)
    bridge["__built_at__"] = time.strftime("%Y-%m-%dT%H:%M:%S")

    return bridge





def resolve(bridge: dict[str, str], identifier: str) -> str | None:
    ""











    if not identifier or not identifier.strip():
        return None

    identifier = identifier.strip()


    if identifier.startswith("__"):
        return None


    if identifier in bridge:
        return bridge[identifier]


    lower = identifier.lower()
    if lower in bridge:
        return bridge[lower]


    if "@" in identifier:
        email_norm = _normalize_email(identifier)
        if email_norm in bridge:
            return bridge[email_norm]
        return None


    name_norm = _normalize_name(identifier)
    if name_norm in bridge:
        return bridge[name_norm]



    id_parts = _name_parts(name_norm)
    if len(id_parts) >= 2:
        candidates = []
        for key, pid in bridge.items():
            if key.startswith("__"):
                continue

            if (
                "@" in key
                or key.startswith("p_")
                or key.startswith("person_")
                or key.startswith("pu_")
            ):
                continue
            key_parts = _name_parts(key)
            if len(key_parts) < 2:
                continue

            if id_parts.issubset(key_parts) or key_parts.issubset(id_parts):
                candidates.append((key, pid))


        unique_pids = {pid for _, pid in candidates}
        if len(unique_pids) == 1:
            return candidates[0][1]

    return None





def save_bridge(bridge: dict[str, str], path: str | Path | None = None) -> Path:
    ""








    out = Path(path) if path else BRIDGE_OUTPUT_PATH
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(bridge, indent=2, ensure_ascii=False), encoding="utf-8")
    log.info("Bridge saved to %s (%d entries)", out, len(bridge))
    return out


def load_bridge(path: str | Path | None = None) -> dict[str, str]:
    ""







    p = Path(path) if path else BRIDGE_OUTPUT_PATH
    if not p.exists():
        log.warning("Bridge file not found at %s", p)
        return {}
    try:
        bridge = json.loads(p.read_text(encoding="utf-8"))
        log.info("Loaded bridge from %s: %d entries", p, len(bridge))
        return bridge
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("Failed to load bridge from %s: %s", p, exc)
        return {}





def _print_stats(bridge: dict[str, str]) -> None:
    ""
    stats_raw = bridge.get("__stats__")
    built_at = bridge.get("__built_at__", "unknown")

    total = sum(1 for k in bridge if not k.startswith("__"))


    targets = [v for k, v in bridge.items() if not k.startswith("__") and isinstance(v, str)]
    p_targets = sum(1 for t in targets if t.startswith("p_"))
    person_targets = sum(1 for t in targets if t.startswith("person_"))
    pu_targets = sum(1 for t in targets if t.startswith("pu_"))


    keys = [k for k in bridge if not k.startswith("__")]
    email_keys = sum(1 for k in keys if "@" in k)
    p_keys = sum(1 for k in keys if k.startswith("p_"))
    person_keys = sum(1 for k in keys if k.startswith("person_"))
    pu_keys = sum(1 for k in keys if k.startswith("pu_"))
    name_keys = total - email_keys - p_keys - person_keys - pu_keys


    unique_pids = set(targets)

    log.info("=" * 60)
    log.info("  SBK Entity Bridge")
    log.info("  Built at: %s", built_at)
    log.info("=" * 60)
    log.info("  Total mappings:  %s", f"{total:,}")
    log.info("  Unique targets:  %s", f"{len(unique_pids):,}")
    log.info("  Mappings by key type:")
    log.info("    Email keys:       %s", f"{email_keys:,}")
    log.info("    Name keys:        %s", f"{name_keys:,}")
    log.info("    p_XXXX keys:      %s", f"{p_keys:,}")
    log.info("    person_XXXX keys: %s", f"{person_keys:,}")
    log.info("    pu_ keys:         %s", f"{pu_keys:,}")
    log.info("  Targets by prefix:")
    log.info("    -> p_XXXX:        %s", f"{p_targets:,}")
    log.info("    -> person_XXXX:   %s", f"{person_targets:,}")
    log.info("    -> pu_:           %s", f"{pu_targets:,}")

    if stats_raw:
        try:
            stats = json.loads(stats_raw)
            log.info("  Build stats:")
            for k, v in stats.items():
                log.info("    %s: %s", k, f"{v:,}")
        except json.JSONDecodeError:
            pass

    log.info("=" * 60)


def main():
    ""
    import argparse

    parser = argparse.ArgumentParser(
        description="Build SBK entity bridge (unified ID resolution)",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=str,
        default=None,
        help=f"Output path for bridge JSON (default: {BRIDGE_OUTPUT_PATH})",
    )
    parser.add_argument(
        "--test",
        "-t",
        nargs="*",
        help="Test resolution for given identifiers",
    )
    parser.add_argument(
        "--load",
        action="store_true",
        help="Load existing bridge instead of rebuilding",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    if args.load:
        bridge = load_bridge(args.output)
        if not bridge:
            log.error("No bridge file found. Run without --load to build.")
            sys.exit(1)
    else:
        bridge = build_entity_bridge()
        out_path = save_bridge(bridge, args.output)
        log.info("Bridge saved to: %s", out_path)

    _print_stats(bridge)


    if args.test is not None:
        identifiers = (
            args.test
            if args.test
            else [
                *([OWNER_NAME] if OWNER_NAME else []),
                "person_00000000",
                "not-a-real-person@nowhere.example",
            ]
        )
        log.info("  Resolution tests:")
        log.info("  %s", "-" * 50)
        for ident in identifiers:
            result = resolve(bridge, ident)
            log.info("    %s -> %s", f"{ident!r:45s}", result)


if __name__ == "__main__":
    main()
