#!/usr/bin/env python3
"""WhatsApp extra: classify the photos sent in your chats, read the text in screenshots (OCR).

Status: extra step, NOT SET UP OR TESTED BY THE AUTHOR. The WhatsApp path the author uses is
the chat export plus the import (wa-l0l3-full.py, wa-l0-import-history.py, then
wa-l1-enrich.py). Live reading of WhatsApp is not set up.

Input: <data root>/whatsapp/attachments-index.json, written only by
wa-l0-import-history.py --attachments-dir, plus the chat files for context.
Output: <data root>/whatsapp/photos/.

The pipeline runs it only when you ask (xs-pipeline-run.py --ingest --whatsapp-extras), with no
options and after the WhatsApp L1: local classification and OCR only (tesseract if installed),
nothing leaves your machine. With --vision it SENDS PHOTOS TO THE
ANTHROPIC API for a description; it needs ANTHROPIC_API_KEY and only runs when you add the flag.

    uv run python tools/whatsapp/wa-l1-extract-photos.py --dry-run
    uv run python tools/whatsapp/wa-l1-extract-photos.py                 # local only
    uv run python tools/whatsapp/wa-l1-extract-photos.py --vision        # sends photos to the API
"""




























from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    print("ERROR: PIL required. Install with: uv add pillow")
    sys.exit(1)





_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from sbk_config import DATA_ROOT  # noqa: E402





WHATSAPP_DATA_DIR = DATA_ROOT / "whatsapp"
CHATS_DIR = WHATSAPP_DATA_DIR / "chats"
CHATS_INDEX_FILE = CHATS_DIR / "chats-index.json"
ATTACHMENTS_INDEX_FILE = WHATSAPP_DATA_DIR / "attachments-index.json"
PHOTOS_DIR = WHATSAPP_DATA_DIR / "photos"
CLASSIFICATION_FILE = PHOTOS_DIR / "_photo-classification.json"
SUMMARY_FILE = PHOTOS_DIR / "_extraction_summary.json"

IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "heic"}


STICKER_MAX_BYTES = 20_000
LOW_PRIORITY_MAX_BYTES = 100_000



SCREENSHOT_MIN_RATIO = 1.8
SCREENSHOT_MIN_WIDTH = 300


BUSINESS_KEYWORDS = {
    # Default business/document keywords; load from user config.
    "contratto",
    "progetto",
    "sito",
    "render",
    "ufficio",
    "piano",
    "documento",
    "fattura",
    "preventivo",
    "offerta",
    "proposta",
    "budget",
    "revenue",
    "forecast",
    "report",
    "dashboard",
    "deal",
    "acquisizione",
    "merger",
    "fundraising",
    "investor",
    "term sheet",
    "round",
    "valuation",
    "cap table",
    "screenshot",
    "schermata",
    "screen",
    "firma",
    "firmato",
    "signed",
    "contract",
    "mockup",
    "wireframe",
    "design",
    "layout",
    "codice",
    "code",
    "error",
    "bug",
    "deploy",
}


RE_STICKER = re.compile(r"STK-", re.IGNORECASE)
RE_CAMERA_PHOTO = re.compile(r"IMG-", re.IGNORECASE)
RE_ATTACHED_REF = re.compile(r"<attached:\s*([\w\-\.]+)>")



DEFAULT_TOP = 0

DEFAULT_WORKERS = None

log = logging.getLogger("wa-photo-extract")







def slugify(name: str) -> str:
    ""
    slug = name.lower().strip()
    slug = re.sub(r"[^\w\s\-]", "", slug)
    slug = re.sub(r"[\s\-]+", "-", slug).strip("-")
    return slug or "unknown"


def get_context_messages(messages: list[dict], timestamp: str, window: int = 3) -> list[dict]:
    ""



    context = []
    target_idx = None

    for i, msg in enumerate(messages):
        if msg.get("timestamp", "") == timestamp:
            target_idx = i
            break

    if target_idx is None:

        ts_base = timestamp[:19]
        for i, msg in enumerate(messages):
            if msg.get("timestamp", "")[:19] == ts_base:
                target_idx = i
                break

    if target_idx is None:
        return []

    start = max(0, target_idx - window)
    end = min(len(messages), target_idx + window + 1)

    for i in range(start, end):
        msg = messages[i]
        context.append(
            {
                "timestamp": msg.get("timestamp", ""),
                "sender": msg.get("sender", ""),
                "text": msg.get("text", "")[:300],
            }
        )

    return context


def detect_business_context(
    messages: list[dict], timestamp: str, window: int = 5
) -> tuple[bool, str]:
    ""



    context = get_context_messages(messages, timestamp, window=window)
    if not context:
        return False, ""

    combined_text = " ".join(m.get("text", "") for m in context).lower()

    found_keywords = []
    for kw in BUSINESS_KEYWORDS:
        if kw in combined_text:
            found_keywords.append(kw)

    if found_keywords:
        return True, ", ".join(found_keywords[:3])

    return False, ""







def classify_single_photo(
    photo_info: dict,
    messages: list[dict] | None = None,
) -> dict:
    ""








    file_path = Path(photo_info["path"])
    size_bytes = photo_info.get("size_bytes", 0)
    size_kb = round(size_bytes / 1024, 1)
    filename = file_path.name
    timestamp = photo_info.get("timestamp", "")
    sender = photo_info.get("sender", "")

    result = {
        "file": str(file_path),
        "filename": filename,
        "size_kb": size_kb,
        "sender": sender,
        "timestamp": timestamp,
        "class": "unknown",
        "priority": "medium",
        "context_hint": "",
        "width": 0,
        "height": 0,
        "aspect_ratio": 0.0,
        "is_screenshot": False,
    }


    if RE_STICKER.search(filename):
        result["class"] = "sticker"
        result["priority"] = "skip"
        return result


    if size_bytes < STICKER_MAX_BYTES:
        result["class"] = "sticker"
        result["priority"] = "skip"
        return result

    if size_bytes < LOW_PRIORITY_MAX_BYTES:
        result["class"] = "thumbnail"
        result["priority"] = "low"




    try:
        if file_path.exists():
            with Image.open(file_path) as img:
                w, h = img.size
                result["width"] = w
                result["height"] = h

                if w > 0 and h > 0:

                    ratio = max(w, h) / min(w, h)
                    result["aspect_ratio"] = round(ratio, 2)


                    if ratio >= SCREENSHOT_MIN_RATIO and max(w, h) >= SCREENSHOT_MIN_WIDTH:
                        result["class"] = "screenshot"
                        result["is_screenshot"] = True
                        result["priority"] = "high"
                    elif result["class"] == "unknown":
                        result["class"] = "photo"
    except Exception as e:
        log.debug("Cannot read image dimensions for %s: %s", filename, e)
        if result["class"] == "unknown":
            result["class"] = "photo"


    if messages:
        is_biz, hint = detect_business_context(messages, timestamp)
        if is_biz:
            result["context_hint"] = hint
            if result["priority"] != "skip":
                result["priority"] = "high"


    if result["class"] == "unknown":
        result["class"] = "photo"

    return result


def classify_chat_photos(
    slug: str,
    attachments: list[dict],
    messages: list[dict] | None = None,
) -> list[dict]:
    ""









    images = [a for a in attachments if a.get("ext", "").lower() in IMAGE_EXTENSIONS]

    if not images:
        return []

    results = []
    for img in images:
        result = classify_single_photo(img, messages=messages)
        results.append(result)

    return results







def _check_tesseract() -> bool:
    ""
    import shutil

    return shutil.which("tesseract") is not None


def _ocr_with_tesseract(image_path: str) -> str:
    ""
    try:
        import pytesseract

        img = Image.open(image_path)
        text = pytesseract.image_to_string(img, lang="eng+ita")
        return text.strip()
    except ImportError:
        log.debug("pytesseract not installed, falling back to PIL basic")
        return ""
    except Exception as e:
        log.debug("Tesseract OCR failed for %s: %s", image_path, e)
        return ""


def _ocr_with_pil_basic(image_path: str) -> str:
    ""





    try:
        img = Image.open(image_path)

        gray = img.convert("L")
        w, h = gray.size


        pixels = list(gray.getdata())
        if not pixels:
            return ""


        histogram = gray.histogram()
        total_pixels = sum(histogram)
        if total_pixels == 0:
            return ""


        dark = sum(histogram[:64])
        light = sum(histogram[192:])
        bimodal_ratio = (dark + light) / total_pixels


        if bimodal_ratio > 0.7:
            return "[TEXT_DETECTED:PIL_HEURISTIC — install tesseract for actual OCR]"

        return ""
    except Exception as e:
        log.debug("PIL basic analysis failed for %s: %s", image_path, e)
        return ""


def ocr_single_photo(photo_path: str, use_tesseract: bool = True) -> str:
    ""



    if use_tesseract:
        text = _ocr_with_tesseract(photo_path)
        if text:
            return text


    return _ocr_with_pil_basic(photo_path)


def _ocr_worker(args: tuple) -> tuple[str, str, str]:
    ""




    photo_path, chat_slug, photo_stem = args
    use_tesseract = _check_tesseract()

    try:
        text = ocr_single_photo(photo_path, use_tesseract=use_tesseract)
        return chat_slug, photo_stem, text
    except Exception as e:
        return chat_slug, photo_stem, f"[OCR_ERROR: {e}]"







def describe_with_vision(
    photo_path: str,
    context_hint: str = "",
    chat_name: str = "",
) -> str:
    ""



    try:
        import base64

        import anthropic  # noqa: F401 — probe installation; actual client via factory
    except ImportError:
        log.warning("anthropic package not installed, skipping vision")
        return ""

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        log.warning("ANTHROPIC_API_KEY not set, skipping vision")
        return ""

    try:

        path = Path(photo_path)
        if not path.exists():
            return ""


        ext = path.suffix.lower()
        media_types = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp",
        }
        media_type = media_types.get(ext, "image/jpeg")

        image_data = base64.b64encode(path.read_bytes()).decode("utf-8")


        context_str = ""
        if context_hint:
            context_str = f" The conversation context mentions: {context_hint}."
        if chat_name:
            context_str += f" This is from a WhatsApp chat with {chat_name}."

        prompt = (
            f"Describe this image concisely in 1-3 sentences.{context_str} "
            "Focus on: what it shows, any text visible, and why someone might "
            "have shared it in a business conversation. "
            "If it's a screenshot, extract the key information. "
            "If it's a document photo, describe what document it is. "
            "If it's a casual photo (selfie, food, meme), just say 'casual photo' briefly."
        )

        _CROSS_SOURCE_DIR = Path(__file__).resolve().parent.parent / "cross-source"
        if str(_CROSS_SOURCE_DIR) not in sys.path:
            sys.path.insert(0, str(_CROSS_SOURCE_DIR))
        from xs_anthropic_client import get_client

        client = get_client()
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=300,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": image_data,
                            },
                        },
                        {
                            "type": "text",
                            "text": prompt,
                        },
                    ],
                }
            ],
        )
        return response.content[0].text.strip()
    except Exception as e:
        log.warning("Vision API failed for %s: %s", photo_path, e)
        return f"[VISION_ERROR: {e}]"







def load_top_chat_slugs(top_n: int) -> list[str]:
    ""
    if not CHATS_INDEX_FILE.exists():
        log.error("Chats index not found: %s", CHATS_INDEX_FILE)
        return []

    idx = json.loads(CHATS_INDEX_FILE.read_text(encoding="utf-8"))
    chats = idx.get("chats", [])


    try:
        import rumore

        rumorosi = rumore.gruppi_rumore()
    except ImportError:  # pragma: no cover - fuori dal repo
        rumorosi = set()
    chats = [c for c in chats if f"{c.get('sanitized_name', '')}.json" not in rumorosi]
    chats.sort(key=lambda c: c.get("message_count", 0), reverse=True)
    return [c["sanitized_name"] for c in (chats[:top_n] if top_n > 0 else chats)]


def load_chat_messages(slug: str) -> list[dict]:
    ""
    json_path = CHATS_DIR / f"{slug}.json"
    if not json_path.exists():
        return []
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
        return data.get("messages", [])
    except (json.JSONDecodeError, OSError):
        return []


def get_chat_name(slug: str) -> str:
    ""
    json_path = CHATS_DIR / f"{slug}.json"
    if json_path.exists():
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
            return data.get("chat_name", slug)
        except (json.JSONDecodeError, OSError):
            pass
    return slug


def load_existing_classification() -> dict:
    ""
    if CLASSIFICATION_FILE.exists():
        try:
            return json.loads(CLASSIFICATION_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def get_processed_photos(slug: str) -> set[str]:
    ""
    chat_photos_dir = PHOTOS_DIR / slug
    if not chat_photos_dir.exists():
        return set()
    return {f.stem for f in chat_photos_dir.glob("*.json") if not f.name.startswith("_")}


def _quanti_processi(chiesti: int | None) -> int:
    ""




    if chiesti:
        return chiesti
    try:
        from sbk_resources import cpu_workers

        return cpu_workers()
    except ImportError:  # pragma: no cover
        return 2


def run_pipeline(
    top_n: int = DEFAULT_TOP,
    person_filter: str | None = None,
    workers: int | None = DEFAULT_WORKERS,
    dry_run: bool = False,
    enable_vision: bool = False,
    skip_ocr: bool = False,
    resume: bool = False,
) -> dict:
    ""



    t0 = time.time()
    has_tesseract = _check_tesseract()


    if not ATTACHMENTS_INDEX_FILE.exists():
        log.error("Attachments index not found: %s", ATTACHMENTS_INDEX_FILE)
        log.error("Run wa-l0-import-history.py --attachments-dir first")
        return {"error": "No attachments index"}

    att_index = json.loads(ATTACHMENTS_INDEX_FILE.read_text(encoding="utf-8"))
    log.info("Loaded attachments index: %d chats", len(att_index))


    if person_filter:

        target_slug = slugify(person_filter)
        matching_slugs = [
            slug for slug in att_index.keys() if target_slug in slug or slug in target_slug
        ]
        if not matching_slugs:

            filter_words = set(person_filter.lower().split())
            matching_slugs = [
                slug
                for slug in att_index.keys()
                if any(w in slug for w in filter_words if len(w) > 2)
            ]
        if not matching_slugs:
            log.error("No chats found matching '%s'", person_filter)
            return {"error": f"No match for '{person_filter}'"}
        target_slugs = matching_slugs
        log.info(
            "Matched person filter '%s' to %d chats: %s",
            person_filter,
            len(matching_slugs),
            matching_slugs[:5],
        )
    else:
        top_slugs = load_top_chat_slugs(top_n)

        target_slugs = [s for s in top_slugs if s in att_index]
        log.info("Top %d chats: %d have attachments", top_n, len(target_slugs))


    existing_classification = load_existing_classification() if resume else {}




    log.info("=" * 60)
    log.info("PHASE 1: Classifying photos (%d chats)", len(target_slugs))
    log.info("=" * 60)

    classification: dict[str, list[dict]] = {}
    stats = Counter()

    for i, slug in enumerate(target_slugs, 1):
        attachments = att_index.get(slug, [])
        images = [a for a in attachments if a.get("ext", "").lower() in IMAGE_EXTENSIONS]

        if not images:
            continue


        if resume and slug in existing_classification:
            existing_count = len(existing_classification[slug])
            if existing_count >= len(images):
                classification[slug] = existing_classification[slug]
                stats["photos_skipped_resume"] += existing_count
                log.debug("Resume: skipping %s (%d already classified)", slug, existing_count)
                continue


        messages = load_chat_messages(slug)


        results = classify_chat_photos(slug, attachments, messages=messages)

        if results:
            classification[slug] = results
            for r in results:
                stats[f"class_{r['class']}"] += 1
                stats[f"priority_{r['priority']}"] += 1

        if i % 50 == 0:
            log.info("  Classified %d / %d chats...", i, len(target_slugs))

    total_photos = sum(len(v) for v in classification.values())
    log.info(
        "Phase 1 complete: %d photos classified across %d chats", total_photos, len(classification)
    )
    log.info(
        "  Classes: sticker=%d, thumbnail=%d, screenshot=%d, photo=%d",
        stats.get("class_sticker", 0),
        stats.get("class_thumbnail", 0),
        stats.get("class_screenshot", 0),
        stats.get("class_photo", 0),
    )
    log.info(
        "  Priority: skip=%d, low=%d, medium=%d, high=%d",
        stats.get("priority_skip", 0),
        stats.get("priority_low", 0),
        stats.get("priority_medium", 0),
        stats.get("priority_high", 0),
    )


    if not dry_run:
        PHOTOS_DIR.mkdir(parents=True, exist_ok=True)
        CLASSIFICATION_FILE.write_text(
            json.dumps(classification, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        log.info("Classification written: %s", CLASSIFICATION_FILE)




    if skip_ocr:
        log.info("Skipping Phase 2 (OCR) — --skip-ocr flag")
    else:
        log.info("=" * 60)
        log.info(
            "PHASE 2: OCR extraction (tesseract=%s)",
            "YES" if has_tesseract else "NO (PIL fallback)",
        )
        log.info("=" * 60)


        ocr_tasks: list[tuple[str, str, str]] = []

        for slug, photos in classification.items():
            already_done = get_processed_photos(slug) if resume else set()

            for photo in photos:
                if photo.get("class") not in ("screenshot",) and photo.get("priority") != "high":
                    continue

                path = photo["file"]
                stem = Path(path).stem


                if resume and stem in already_done:
                    stats["ocr_skipped_resume"] += 1
                    continue

                if not Path(path).exists():
                    stats["ocr_file_missing"] += 1
                    continue

                ocr_tasks.append((path, slug, stem))

        log.info("OCR tasks: %d photos to process", len(ocr_tasks))

        if ocr_tasks and not dry_run:
            ocr_results: dict[str, dict[str, str]] = defaultdict(dict)
            ocr_count = 0

            effective_workers = min(_quanti_processi(workers), len(ocr_tasks))
            log.info("Processi per l'OCR: %d", effective_workers)

            if effective_workers > 1:
                with ProcessPoolExecutor(max_workers=effective_workers) as executor:
                    futures = {executor.submit(_ocr_worker, task): task for task in ocr_tasks}
                    for future in as_completed(futures):
                        try:
                            chat_slug, photo_stem, text = future.result(timeout=60)
                            ocr_results[chat_slug][photo_stem] = text
                            ocr_count += 1
                            if ocr_count % 100 == 0:
                                log.info("  OCR progress: %d / %d", ocr_count, len(ocr_tasks))
                        except Exception as e:
                            task = futures[future]
                            log.warning("OCR worker failed for %s: %s", task[0], e)
            else:
                for task in ocr_tasks:
                    try:
                        _, chat_slug, photo_stem = _ocr_worker(task)
                        ocr_results[chat_slug][photo_stem] = photo_stem

                        chat_slug, photo_stem, text = _ocr_worker(task)
                        ocr_results[chat_slug][photo_stem] = text
                        ocr_count += 1
                    except Exception as e:
                        log.warning("OCR failed for %s: %s", task[0], e)

            stats["ocr_processed"] = ocr_count
            stats["ocr_with_text"] = sum(
                1
                for slug_results in ocr_results.values()
                for text in slug_results.values()
                if text and not text.startswith("[")
            )
            log.info(
                "Phase 2 complete: %d processed, %d with text",
                stats["ocr_processed"],
                stats["ocr_with_text"],
            )


            for slug, results in ocr_results.items():
                if slug in classification:
                    for photo in classification[slug]:
                        stem = Path(photo["file"]).stem
                        if stem in results:
                            photo["ocr_text"] = results[stem]
        elif dry_run:
            log.info("[DRY RUN] Would OCR %d photos", len(ocr_tasks))




    if enable_vision:
        log.info("=" * 60)
        log.info("PHASE 3: Vision description (Claude API)")
        log.info("=" * 60)

        vision_count = 0
        vision_tasks = []

        for slug, photos in classification.items():
            for photo in photos:
                if photo.get("priority") != "high":
                    continue
                if photo.get("class") == "screenshot":

                    continue
                if photo.get("vision_description"):

                    continue
                if not Path(photo["file"]).exists():
                    continue

                vision_tasks.append((slug, photo))

        log.info("Vision tasks: %d HIGH_PRIORITY photos", len(vision_tasks))

        if vision_tasks and not dry_run:
            for slug, photo in vision_tasks:
                chat_name = get_chat_name(slug)
                description = describe_with_vision(
                    photo["file"],
                    context_hint=photo.get("context_hint", ""),
                    chat_name=chat_name,
                )
                if description:
                    photo["vision_description"] = description
                    vision_count += 1


                time.sleep(1.0)

                if vision_count % 10 == 0:
                    log.info("  Vision progress: %d / %d", vision_count, len(vision_tasks))

            stats["vision_processed"] = vision_count
            log.info("Phase 3 complete: %d descriptions generated", vision_count)
        elif dry_run:
            log.info("[DRY RUN] Would describe %d photos with Vision API", len(vision_tasks))
    else:
        log.info("Skipping Phase 3 (Vision) — use --vision to enable")




    if not dry_run:
        log.info("=" * 60)
        log.info("Writing per-photo output files")
        log.info("=" * 60)

        files_written = 0
        for slug, photos in classification.items():
            chat_name = get_chat_name(slug)
            messages = load_chat_messages(slug)
            chat_dir = PHOTOS_DIR / slug

            for photo in photos:

                if photo.get("priority") == "skip":
                    continue

                stem = Path(photo["file"]).stem
                out_path = chat_dir / f"{stem}.json"


                if resume and out_path.exists():
                    continue


                context = []
                if messages and photo.get("timestamp"):
                    context = get_context_messages(messages, photo["timestamp"])

                output = {
                    "source_file": photo["file"],
                    "chat": chat_name,
                    "chat_slug": slug,
                    "sender": photo.get("sender", ""),
                    "timestamp": photo.get("timestamp", ""),
                    "classification": photo.get("class", "unknown"),
                    "priority": photo.get("priority", "medium"),
                    "size_kb": photo.get("size_kb", 0),
                    "width": photo.get("width", 0),
                    "height": photo.get("height", 0),
                    "aspect_ratio": photo.get("aspect_ratio", 0),
                    "is_screenshot": photo.get("is_screenshot", False),
                    "ocr_text": photo.get("ocr_text", ""),
                    "vision_description": photo.get("vision_description", ""),
                    "context_hint": photo.get("context_hint", ""),
                    "conversation_context": context,
                    "processed_at": datetime.now().isoformat(),
                }

                chat_dir.mkdir(parents=True, exist_ok=True)
                out_path.write_text(
                    json.dumps(output, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                files_written += 1

        stats["files_written"] = files_written
        log.info("Wrote %d per-photo JSON files", files_written)


        CLASSIFICATION_FILE.write_text(
            json.dumps(classification, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )




    elapsed = time.time() - t0
    summary = {
        "run_at": datetime.now().isoformat(),
        "elapsed_seconds": round(elapsed, 1),
        "chats_processed": len(classification),
        "total_photos": total_photos,
        "classification": {
            "sticker": stats.get("class_sticker", 0),
            "thumbnail": stats.get("class_thumbnail", 0),
            "screenshot": stats.get("class_screenshot", 0),
            "photo": stats.get("class_photo", 0),
        },
        "priority": {
            "skip": stats.get("priority_skip", 0),
            "low": stats.get("priority_low", 0),
            "medium": stats.get("priority_medium", 0),
            "high": stats.get("priority_high", 0),
        },
        "ocr": {
            "processed": stats.get("ocr_processed", 0),
            "with_text": stats.get("ocr_with_text", 0),
            "skipped_resume": stats.get("ocr_skipped_resume", 0),
            "file_missing": stats.get("ocr_file_missing", 0),
        },
        "vision": {
            "processed": stats.get("vision_processed", 0),
        },
        "files_written": stats.get("files_written", 0),
        "tesseract_available": has_tesseract,
        "dry_run": dry_run,
    }

    if not dry_run:
        SUMMARY_FILE.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    log.info("=" * 60)
    log.info("PHOTO EXTRACTION COMPLETE")
    log.info("=" * 60)
    log.info("  Chats processed:    %d", summary["chats_processed"])
    log.info("  Total photos:       %d", summary["total_photos"])
    log.info("  Screenshots:        %d", summary["classification"]["screenshot"])
    log.info("  High priority:      %d", summary["priority"]["high"])
    log.info(
        "  OCR processed:      %d (with text: %d)",
        summary["ocr"]["processed"],
        summary["ocr"]["with_text"],
    )
    log.info("  Vision processed:   %d", summary["vision"]["processed"])
    log.info("  Files written:      %d", summary["files_written"])
    log.info("  Tesseract:          %s", "YES" if has_tesseract else "NO")
    log.info("  Time:               %.1fs", elapsed)
    if dry_run:
        log.info("  *** DRY RUN — no files written ***")

    return summary







def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Classify and extract text from WhatsApp photos")
    p.add_argument(
        "--top",
        type=int,
        default=DEFAULT_TOP,
        help=f"Process top N chats by message count (default: {DEFAULT_TOP})",
    )
    p.add_argument(
        "--person",
        type=str,
        default=None,
        help="Process only chats matching this person name",
    )
    p.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        help="Parallel OCR workers (default: from the machine budget, sbk_resources.cpu_workers)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Show plan without writing files",
    )
    p.add_argument(
        "--vision",
        action="store_true",
        help="Enable Claude Vision API for HIGH_PRIORITY photo descriptions",
    )
    p.add_argument(
        "--skip-ocr",
        action="store_true",
        help="Skip OCR phase, only classify",
    )
    p.add_argument(
        "--resume",
        action="store_true",
        help="Skip already-processed photos",
    )
    p.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable debug logging",
    )
    return p.parse_args()


def main():
    args = parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s  %(message)s",
        datefmt="%H:%M:%S",
    )

    summary = run_pipeline(
        top_n=args.top,
        person_filter=args.person,
        workers=args.workers,
        dry_run=args.dry_run,
        enable_vision=args.vision,
        skip_ocr=args.skip_ocr,
        resume=args.resume,
    )

    if "error" in summary:
        sys.exit(1)






try:
    from pipeline_decorator import pipeline_step

    main = pipeline_step(
        name="l1-whatsapp-extract-photos",
        source="whatsapp",
        stage="l1",
        mark_run=False,
    )(main)
except ImportError:
    pass

if __name__ == "__main__":
    main()
