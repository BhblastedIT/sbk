#!/usr/bin/env python3
"""Plaud L1: names the speakers of each transcript in four passes (Plaud's labels, the calendar event that matches
the recording, the context of what is said, then the result applied), telling you from the others.
"""

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))
from sbk_config import (
    OWN_EMAILS,
    OWNER_SPEAKER_LABELS,
    PLAUD_DIR,
    PLAUD_PROCESSED_DIR,
    mark_last_run,
    owner_name_regex,
    safe_write_json,
)

RAW_DIR = PLAUD_DIR
PROC_DIR = PLAUD_PROCESSED_DIR  # Created when the script runs, not at import, so --help writes nothing.


_WATERMARK_FILE = PROC_DIR / "_file_watermarks.json"


def _load_watermarks() -> dict[str, float]:
    ""
    if _WATERMARK_FILE.exists():
        try:
            return json.loads(_WATERMARK_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_watermarks(watermarks: dict[str, float]):
    ""
    safe_write_json(_WATERMARK_FILE, watermarks)


def _risultati_precedenti(percorso: Path) -> dict[str, dict]:
    ""
    try:
        dati = json.loads(percorso.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(dati, list):
        return {}
    return {r["source_file"]: r for r in dati if isinstance(r, dict) and r.get("source_file")}



# Your names and speaker labels, from sbk.config.json (owner, own_names).
OWNER_NAMES = set(OWNER_SPEAKER_LABELS)


# Your email addresses, from sbk.config.json (own_emails).
OWNER_EMAILS: set[str] = set(OWN_EMAILS)


# map a nickname/handle to a display name; load from user config
KNOWN_PEOPLE: dict[str, str] = {}


# map an email address to a display name; load from user config
EMAIL_TO_NAME: dict[str, str] = {}


# Phrases that signal the owner is speaking about their own company, and the
# owner's recurring turns of phrase. Load from user config; empty by default.
OWNER_COMPANY_PHRASES: list[str] = []
OWNER_IDENTITY_PHRASES: list[str] = []


def is_owner(name):
    if not name:
        return False
    return name.lower().strip() in OWNER_NAMES


def is_owner_email(email):
    email = email.lower().strip()

    if "<" in email:
        email = email.split("<")[1].rstrip(">")
    return email in OWNER_EMAILS


def extract_non_owner_attendees(attendees):
    ""
    others = []
    for att in attendees:
        email = att.lower().strip()

        email = re.sub(r"^\(organizer\)\s*", "", email)

        if "<" in email:
            raw_email = email.split("<")[1].rstrip(">")
        else:
            raw_email = email.split()[-1] if email else email

        if raw_email not in OWNER_EMAILS:

            name = EMAIL_TO_NAME.get(raw_email)
            if not name:

                if "<" in att:
                    name = att.split("<")[0].strip()
                else:
                    name = raw_email.split("@")[0]
            others.append({"email": raw_email, "name": name})
    return others


def detect_addressing(content):
    ""
    text = content.lower()

    addressing_patterns = [
        rf"\b{owner_name_regex()}\b",
        r"la tua azienda",
        r"il tuo progetto",
        r"il tuo team",
        r"tu hai detto",
        r"tu vuoi",
        r"tu pensi",
        # English
        r"\byour company\b",
        r"\byour project\b",
        r"\byour team\b",
        r"\byou said\b",
        r"\byou want\b",
        r"\byou think\b",
    ]
    for pat in addressing_patterns:
        if re.search(pat, text):

            if re.search(rf"\b(?:io|mi chiamo|sono|i'm|this is)\s+{owner_name_regex()}\b", text):
                return False
            return True
    return False


def detect_owner_identity(content):
    ""
    text = content.lower()
    score = 0.0
    reasons = []


    if any(p in text for p in OWNER_COMPANY_PHRASES):
        score += 0.7
        reasons.append("refers to own company")

    for phrase in OWNER_IDENTITY_PHRASES:
        if phrase in text:
            score += 0.5
            reasons.append(f"uses phrase: '{phrase}'")
            break

    return score, reasons


def detect_other_identity(content):
    ""
    text = content.lower()
    score = 0.0
    reasons = []

    if any(
        p in text
        for p in [
            "il mio fondo",
            "la mia societa",
            "noi come fondo",
            "i miei partner",
            "la mia agency",
            "my fund",
            "my firm",
            "we as a fund",
            "my partners",
            "my agency",
        ]
    ):
        score += 0.7
        reasons.append("refers to external fund/company")

    if detect_addressing(content):
        score += 0.8
        reasons.append("addresses you by name")

    return score, reasons








PLAUD_LABEL_CONF = 0.55


def pass1_plaud_labels(segments, file_info):
    ""
    speaker_map = {}

    for seg in segments:
        speaker = seg.get("speaker") or ""
        orig = seg.get("original_speaker", speaker)


        if is_owner(speaker):

            if orig and orig.startswith("Speaker "):
                speaker_map[orig] = {
                    "identity": "owner",
                    "confidence": PLAUD_LABEL_CONF,
                    "source": "plaud_label",
                    "unverified": True,
                }

        elif speaker and not speaker.startswith("Speaker ") and speaker != "":

            if orig and orig.startswith("Speaker "):
                speaker_map[orig] = {
                    "identity": speaker,
                    "confidence": PLAUD_LABEL_CONF,
                    "source": "plaud_label",
                    "unverified": True,
                }


    if file_info["category"] == "monologue":
        for seg in segments:
            sp = seg.get("speaker") or seg.get("original_speaker", "")
            if sp:
                speaker_map[sp] = {
                    "identity": "owner",
                    "confidence": 0.95,
                    "source": "monologue",
                }

    return speaker_map


def pass2_calendar(speaker_map, segments, file_info, cal_match):
    ""
    if not cal_match or not cal_match.get("attendees"):
        return speaker_map

    others = extract_non_owner_attendees(cal_match.get("attendees", []))
    if not others:
        return speaker_map


    all_generic = set()
    for seg in segments:
        sp = seg.get("original_speaker") or seg.get("speaker") or ""
        if sp.startswith("Speaker "):
            all_generic.add(sp)

    unmapped_generic = [sp for sp in sorted(all_generic) if sp not in speaker_map]
    owner_ids = [sp for sp, info in speaker_map.items() if info["identity"] == "owner"]


    if not owner_ids and unmapped_generic:

        freq = Counter()
        for seg in segments:
            sp = seg.get("original_speaker") or seg.get("speaker") or ""
            if sp in unmapped_generic:
                freq[sp] += 1


        if freq:
            likely_owner = freq.most_common(1)[0][0]
            speaker_map[likely_owner] = {
                "identity": "owner",
                "confidence": 0.65,
                "source": "calendar_heuristic",
            }
            unmapped_generic.remove(likely_owner)


    if len(others) == 1 and len(unmapped_generic) == 1:
        speaker_map[unmapped_generic[0]] = {
            "identity": others[0]["name"],
            "confidence": 0.75,
            "source": "calendar_match",
        }
    elif len(others) >= 1 and len(unmapped_generic) >= 1:

        for sp in unmapped_generic:
            if sp not in speaker_map:
                speaker_map[sp] = {
                    "identity": "other",
                    "confidence": 0.5,
                    "source": "calendar_pool",
                    "candidates": [o["name"] for o in others],
                }

    return speaker_map


def pass3_contextual(speaker_map, segments, file_info):
    ""



    for seg in segments:
        speaker = seg.get("speaker") or ""
        orig = seg.get("original_speaker", speaker)
        lookup = orig if orig else speaker
        if is_owner(speaker) and lookup not in speaker_map:
            speaker_map[lookup] = {
                "identity": "owner",
                "confidence": PLAUD_LABEL_CONF,
                "source": "named_owner",
                "unverified": True,
            }


    speaker_addresses_owner = set()
    speaker_is_owner_clues = {}

    for seg in segments:
        sp = seg.get("original_speaker") or seg.get("speaker") or ""
        content = seg.get("content", "")

        if not sp or sp in speaker_map:
            continue


        speaker_name = seg.get("speaker") or ""
        if is_owner(speaker_name):
            continue


        if detect_addressing(content):
            speaker_addresses_owner.add(sp)


        owner_score, _ = detect_owner_identity(content)
        if owner_score > 0:
            speaker_is_owner_clues[sp] = speaker_is_owner_clues.get(sp, 0) + owner_score


    for sp in speaker_addresses_owner:
        if sp not in speaker_map:
            speaker_map[sp] = {"identity": "other", "confidence": 0.7, "source": "addressing_rule"}


    for sp, score in speaker_is_owner_clues.items():
        if sp not in speaker_map and score >= 1.0:
            speaker_map[sp] = {
                "identity": "owner",
                "confidence": min(0.7, 0.4 + score * 0.1),
                "source": "content_clues",
            }



    all_speakers = set()
    for seg in segments:
        sp = seg.get("original_speaker") or seg.get("speaker") or ""
        if sp:
            all_speakers.add(sp)

    if len(all_speakers) == 2:
        sp_list = sorted(all_speakers)
        mapped_0 = speaker_map.get(sp_list[0])
        mapped_1 = speaker_map.get(sp_list[1])

        if mapped_0 and mapped_0["identity"] == "owner" and not mapped_1:
            speaker_map[sp_list[1]] = {
                "identity": "other",
                "confidence": 0.7,
                "source": "complement_rule",
            }
        elif mapped_1 and mapped_1["identity"] == "owner" and not mapped_0:
            speaker_map[sp_list[0]] = {
                "identity": "other",
                "confidence": 0.7,
                "source": "complement_rule",
            }
        elif mapped_0 and mapped_0["identity"] == "other" and not mapped_1:

            speaker_map[sp_list[1]] = {
                "identity": "owner",
                "confidence": 0.6,
                "source": "complement_rule",
            }
        elif mapped_1 and mapped_1["identity"] == "other" and not mapped_0:
            speaker_map[sp_list[0]] = {
                "identity": "owner",
                "confidence": 0.6,
                "source": "complement_rule",
            }



    owner_mapped = any(v["identity"] == "owner" for v in speaker_map.values())
    if not owner_mapped:
        freq = Counter()
        for seg in segments:
            sp = seg.get("original_speaker") or seg.get("speaker") or ""
            speaker_name = seg.get("speaker") or ""

            is_generic = not sp or sp.startswith("Speaker ")
            if is_generic and sp and sp not in speaker_map:
                freq[sp] += 1
        if freq:
            likely_owner = freq.most_common(1)[0][0]
            speaker_map[likely_owner] = {
                "identity": "owner",
                "confidence": 0.5,
                "source": "recorder_heuristic",
            }

    return speaker_map


def pass4_apply(segments, speaker_map, file_info):
    ""
    processed = []

    for i, seg in enumerate(segments):
        speaker = seg.get("speaker") or ""
        content = seg.get("content", "")
        orig = seg.get("original_speaker", speaker)


        lookup_id = orig if orig else speaker


        mapped = speaker_map.get(lookup_id)

        if is_owner(speaker):


            attribution = "owner"
            confidence = PLAUD_LABEL_CONF
        elif mapped:
            identity = mapped["identity"]
            if identity == "owner":
                attribution = "owner"
                confidence = mapped["confidence"]
            elif identity == "other":
                attribution = "other"
                confidence = mapped["confidence"]
            else:

                attribution = "other"
                confidence = mapped["confidence"]
        elif speaker and not speaker.startswith("Speaker "):
            attribution = "other"
            confidence = PLAUD_LABEL_CONF
        else:

            owner_score, owner_reasons = detect_owner_identity(content)
            other_score, other_reasons = detect_other_identity(content)

            if owner_score > other_score + 0.3:
                attribution = "owner"
                confidence = min(0.55, 0.3 + owner_score * 0.1)
            elif other_score > owner_score + 0.3:
                attribution = "other"
                confidence = min(0.55, 0.3 + other_score * 0.1)
            else:
                attribution = "uncertain"
                confidence = 0.2


        if file_info["category"] == "monologue":
            attribution = "owner"
            confidence = 0.95

        entry = {
            "index": i,
            "speaker_plaud": speaker,
            "speaker_original": orig,
            "attribution": attribution,
            "confidence": round(confidence, 2),
            "content": content,
            "start_time": seg.get("start_time", 0),
            "end_time": seg.get("end_time", 0),
        }


        if mapped and mapped["identity"] not in ("owner", "other"):
            entry["resolved_name"] = mapped["identity"]
        if mapped and mapped.get("candidates"):
            entry["possible_speakers"] = mapped["candidates"]
        if mapped:
            entry["attribution_source"] = mapped.get("source", "")

        processed.append(entry)

    return processed


def find_calendar_match(filename, file_info, calendar_data):
    ""
    cal_match = None
    clean_title = filename.replace(".json", "")
    file_date = filename[:10]

    for m in calendar_data.get("matches", []):
        plaud_fn = m.get("plaud_filename", "")

        if clean_title[:30] in plaud_fn[:30]:
            cal_match = m
            break

        if file_date == m.get("plaud_date", ""):
            if not cal_match or m.get("match_confidence") == "high":
                cal_match = m

    return cal_match


def process_file(file_info, calendar_data):
    ""
    filename = file_info["filename"]
    json_path = RAW_DIR / filename

    with open(json_path, encoding="utf-8") as f:
        segments = json.load(f)


    cal_match = find_calendar_match(filename, file_info, calendar_data)

    cal_info = {
        "event": cal_match.get("calendar_event", "") if cal_match else None,
        "attendees": cal_match.get("attendees", []) if cal_match else [],
        "confidence": cal_match.get("match_confidence", "") if cal_match else None,
    }


    overrides_file = PROC_DIR / "_speaker_overrides.json"
    try:
        if overrides_file.exists():
            with open(overrides_file, encoding="utf-8") as _ovf:
                _all_overrides = json.load(_ovf)
        else:
            _all_overrides = {}
    except (OSError, json.JSONDecodeError):
        _all_overrides = {}
    file_overrides = _all_overrides.get(filename, {})




    speaker_map = pass1_plaud_labels(segments, file_info)


    speaker_map = pass2_calendar(speaker_map, segments, file_info, cal_match)


    speaker_map = pass3_contextual(speaker_map, segments, file_info)


    for speaker_label, real_name in file_overrides.items():
        if speaker_label in speaker_map:
            speaker_map[speaker_label] = {
                **speaker_map[speaker_label],
                "identity": real_name,
                "confidence": 1.0,
                "source": "manual_override",
            }
        else:
            speaker_map[speaker_label] = {
                "identity": real_name,
                "confidence": 1.0,
                "source": "manual_override",
            }


    processed_segments = pass4_apply(segments, speaker_map, file_info)


    owner_text = []
    other_text = []
    uncertain_text = []

    for s in processed_segments:
        if s["attribution"] == "owner" and s["confidence"] >= 0.6:
            owner_text.append(s["content"])
        elif s["attribution"] == "other" and s["confidence"] >= 0.6:
            other_text.append(s["content"])
        else:
            uncertain_text.append(s["content"])

    attr_counts = Counter(s["attribution"] for s in processed_segments)
    avg_conf = sum(s["confidence"] for s in processed_segments) / max(len(processed_segments), 1)

    result = {
        "source_file": filename,
        "title": filename.replace(".json", ""),
        "category": file_info["category"],
        "duration_min": file_info["duration_min"],
        "total_segments": len(segments),
        "speakers_plaud": file_info["speakers"],
        "named_speakers": file_info.get("named_speakers", []),
        "generic_speakers": file_info.get("generic_speakers", []),
        "speaker_transitions": file_info["speaker_transitions"],
        "calendar_match": cal_info,
        "speaker_map": {
            k: {"identity": v["identity"], "confidence": v["confidence"], "source": v["source"]}
            for k, v in speaker_map.items()
        },
        "segments": processed_segments,
        "stats": {
            "owner_segments": attr_counts.get("owner", 0),
            "other_segments": attr_counts.get("other", 0),
            "uncertain_segments": attr_counts.get("uncertain", 0),
            "avg_confidence": round(avg_conf, 2),
            "owner_chars": sum(len(t) for t in owner_text),
            "other_chars": sum(len(t) for t in other_text),
            "uncertain_chars": sum(len(t) for t in uncertain_text),
            "needs_review": attr_counts.get("uncertain", 0) > len(processed_segments) * 0.3,
        },
        "owner_extract": "\n\n".join(owner_text[:50]),
    }

    return result


def main():
    parser = argparse.ArgumentParser(description="Plaud transcript processor V2")
    parser.add_argument(
        "mode",
        nargs="?",
        default="test",
        choices=["test", "full"],
        help="Processing mode: test (20 files) or full (all)",
    )
    parser.add_argument("--incremental", action="store_true", help="Skip if inputs unchanged")
    parser.add_argument(
        "--dry-run", action="store_true", help="Show what would run without writing"
    )
    args = parser.parse_args()
    PROC_DIR.mkdir(parents=True, exist_ok=True)
    mode = args.mode

    print("=" * 60)
    print(f"PLAUD TRANSCRIPT PROCESSOR V2 — {mode.upper()} mode")
    print("=" * 60)
    print()

    if mode == "full":
        with open(RAW_DIR / "_speaker_analysis.json") as f:
            analysis = json.load(f)
        all_files = analysis["files"]

        test_files = [f for f in all_files if f["segments"] > 0]
    else:
        with open(RAW_DIR / "_test_batch_20.json") as f:
            test_files = json.load(f)





    suffix = "_full" if mode == "full" else "_test_batch"
    output_path = PROC_DIR / f"{suffix}_results_v2.json"
    ordine = [f["filename"] for f in test_files]
    precedenti = _risultati_precedenti(output_path) if args.incremental else {}


    current_wm = {}
    if args.incremental:
        saved_wm = _load_watermarks()
        for f_info in test_files:
            fpath = RAW_DIR / f_info["filename"]
            if fpath.exists():
                current_wm[f_info["filename"]] = fpath.stat().st_mtime
        changed_files = [
            f
            for f in test_files
            if f["filename"] not in saved_wm
            or current_wm.get(f["filename"], 0) > saved_wm.get(f["filename"], 0)
            or f["filename"] not in precedenti
        ]


        spariti = [fn for fn in precedenti if fn not in set(ordine)]
        if not changed_files and not spariti:
            print("Incremental: no new/changed files — skipping")
            mark_last_run("pl-l1")
            return
        if spariti:
            print(
                f"Incremental: {len(spariti)} recordings no longer in the folder leave the results"
            )
        print(f"Incremental: {len(changed_files)}/{len(test_files)} files changed")
        test_files = changed_files

    with open(RAW_DIR / "_calendar_crossref.json") as f:
        calendar_data = json.load(f)

    print(f"Processing {len(test_files)} files...")
    print()

    results = []
    for i, file_info in enumerate(test_files):
        fn = file_info["filename"].replace(".json", "")[:60]
        cat = file_info["category"]
        print(f"  [{i + 1:2}/{len(test_files)}] [{cat:25}] {fn}...", end=" ", flush=True)

        try:
            result = process_file(file_info, calendar_data)
            results.append(result)

            stats = result["stats"]
            sm = result["speaker_map"]
            sm_summary = " ".join(f"{k}={v['identity'][:8]}" for k, v in sm.items())[:40]
            print(
                f"S:{stats['owner_segments']:3} O:{stats['other_segments']:3} "
                f"U:{stats['uncertain_segments']:3} conf:{stats['avg_confidence']:.2f} "
                f"map:[{sm_summary}]" + (" REVIEW" if stats["needs_review"] else " OK")
            )
        except Exception as e:
            print(f"ERROR: {e}")
            import traceback

            traceback.print_exc()

    if args.incremental:


        rifatti = {r["source_file"]: r for r in results}
        results = [
            rifatti.get(fn) or precedenti[fn] for fn in ordine if fn in rifatti or fn in precedenti
        ]
        print(
            f"Incremental: {len(rifatti)} redone, {len(results) - len(rifatti)} kept from the previous results"
        )


    if not args.dry_run:
        safe_write_json(output_path, results)


    print()
    print("=" * 60)
    print("SUMMARY V2 vs V1")
    print("=" * 60)

    total_owner = sum(r["stats"]["owner_segments"] for r in results)
    total_other = sum(r["stats"]["other_segments"] for r in results)
    total_uncertain = sum(r["stats"]["uncertain_segments"] for r in results)
    total_all = total_owner + total_other + total_uncertain
    needs_review = sum(1 for r in results if r["stats"]["needs_review"])

    print(f"  Segments totali: {total_all}")
    print(f"    You:     {total_owner} ({total_owner / total_all * 100:.0f}%)")
    print(f"    Other:      {total_other} ({total_other / total_all * 100:.0f}%)")
    print(f"    Uncertain:  {total_uncertain} ({total_uncertain / total_all * 100:.0f}%)")
    print(f"  Files needing review: {needs_review}/{len(results)}")
    print(f"  Output: {output_path}")
    print()


    cats = {}
    for r in results:
        c = r["category"]
        if c not in cats:
            cats[c] = {"owner": 0, "other": 0, "uncertain": 0, "total": 0, "files": 0, "review": 0}
        cats[c]["owner"] += r["stats"]["owner_segments"]
        cats[c]["other"] += r["stats"]["other_segments"]
        cats[c]["uncertain"] += r["stats"]["uncertain_segments"]
        cats[c]["total"] += r["total_segments"]
        cats[c]["files"] += 1
        if r["stats"]["needs_review"]:
            cats[c]["review"] += 1

    print("  Per-category breakdown:")
    for cat, data in sorted(cats.items()):
        t = data["total"]
        if t > 0:
            pct_resolved = (data["owner"] + data["other"]) / t * 100
        else:
            pct_resolved = 0
        print(
            f"    {cat:25} S:{data['owner']:4} O:{data['other']:4} U:{data['uncertain']:4} "
            f"resolved:{pct_resolved:.0f}% review:{data['review']}/{data['files']}"
        )


    review = []
    for r in results:
        uncertain = [s for s in r["segments"] if s["attribution"] == "uncertain"]
        if uncertain:
            review.append(
                {
                    "file": r["source_file"],
                    "title": r["title"],
                    "category": r["category"],
                    "speaker_map": r["speaker_map"],
                    "uncertain_count": len(uncertain),
                    "total_count": r["total_segments"],
                    "calendar": r["calendar_match"]["event"],
                    "attendees": r["calendar_match"]["attendees"],
                    "sample_uncertain": [
                        {
                            "index": s["index"],
                            "speaker_plaud": s["speaker_plaud"],
                            "speaker_original": s["speaker_original"],
                            "content_preview": s["content"][:200],
                        }
                        for s in uncertain[:10]
                    ],
                }
            )

    review_path = PROC_DIR / f"{suffix}_review_v2.json"
    if not args.dry_run:
        safe_write_json(review_path, review)
    print(f"\n  {'[DRY RUN] Would write' if args.dry_run else 'Review file:'} {review_path}")

    if args.dry_run:
        print("\n[DRY RUN] No files written.")
        return


    if args.incremental and current_wm:

        merged_wm = _load_watermarks()
        merged_wm.update(current_wm)
        _save_watermarks(merged_wm)

    from sbk_config import save_input_checkpoint

    save_input_checkpoint("pl-l1", [RAW_DIR])
    mark_last_run("pl-l1")


from pipeline_decorator import pipeline_step


@pipeline_step(name="l1-plaud-enrich", source="pl-l1", stage="l1", mark_run=False)
def _pipeline_run():
    main()


if __name__ == "__main__":
    _pipeline_run()
