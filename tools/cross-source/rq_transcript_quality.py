"""Classifies transcript content as personal, strategic, operational or transactional, by keywords and duration, so
the relationship scores weigh meetings by substance; --backfill classifies every transcript and caches the result.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("rq.transcript_quality")





CATEGORY_KEYWORDS: dict[str, dict[str, list[str]]] = {
    "personal": {
        "family": [
            "famiglia",
            "moglie",
            "marito",
            "figlio",
            "figlia",
            "padre",
            "madre",
            "fratello",
            "sorella",
            "nonno",
            "nonna",
            "zio",
            "zia",
            "cugino",
            "family",
            "wife",
            "husband",
            "son",
            "daughter",
            "dad",
            "mom",
            "brother",
            "sister",
            "grandpa",
            "grandma",
            "uncle",
            "aunt",
            "cousin",
        ],
        "celebrations": [
            "matrimonio",
            "nozze",
            "battesimo",
            "comunione",
            "cresima",
            "compleanno",
            "natale",
            "pasqua",
            "capodanno",
            "festa",
            "wedding",
            "baptism",
            "communion",
            "birthday",
            "christmas",
            "easter",
            "party",
        ],
        "leisure": [
            "vacanza",
            "vacanze",
            "ferie",
            "weekend",
            "hobby",
            "palestra",
            "calcio",
            "calcetto",
            "leggere",
            "giocare",
            "cucinare",
            "viaggio",
            "vacation",
            "holiday",
            "weekend",
            "hobby",
            "gym",
            "soccer",
            "football",
            "reading",
            "playing",
            "cooking",
            "travel",
        ],
        "wellness": [
            "salute",
            "medico",
            "dottore",
            "terapia",
            "medicina",
            "malattia",
            "health",
            "doctor",
            "medical",
            "therapy",
            "sick",
            "illness",
        ],
        "self_disclosure_patterns": [
            r"\bI feel\b",
            r"\bmy family\b",
            r"\bpersonally\b",
            r"\bto be honest\b",
            r"\bbetween us\b",
            r"\bI'?m worried\b",
            r"\bI'?m excited\b",
            r"\bti dico\b",
            r"\btra noi\b",
            r"\bla mia famiglia\b",
            r"\bpersonalmente\b",
            r"\bmi sento\b",
            r"\bsono preoccupato\b",
            r"\bti confesso\b",
        ],
        "warmth_markers": [
            "come stai",
            "come va",
            "tutto bene",
            "come stanno",
            "buon weekend",
            "come sono andate",
            "how are you",
            "how's it going",
            "hope you're well",
        ],
    },
    "strategic": {
        "business_deals": [
            "acquisizione",
            "equity",
            "partnership",
            "socio",
            "quota",
            "amministratore",
            "CEO",
            "AD",
            "CTO",
            "CFO",
            "COO",
            "fondatore",
            "co-fondatore",
            "holding",
            "controllata",
            "acquisition",
            "partnership",
            "partner",
            "administrator",
            "founder",
            "holding",
            "subsidiary",
        ],
        "vision_direction": [
            "visione",
            "strategia",
            "piano",
            "roadmap",
            "obiettivo",
            "target",
            "crescita",
            "sviluppo",
            "espansione",
            "posizionamento",
            "vision",
            "strategy",
            "plan",
            "roadmap",
            "objective",
            "target",
            "growth",
            "development",
            "expansion",
            "positioning",
        ],
        "investment": [
            "finanziamento",
            "funding",
            "round",
            "investitore",
            "VC",
            "board",
            "investor",
            "financing",
            "capital",
            "raise",
        ],
        "market_competition": [
            "mercato",
            "competitor",
            "concorrente",
            "segmentazione",
            "market",
            "competitor",
            "competition",
            "segmentation",
        ],
        "formal_markers": [
            "egregio",
            "distinti saluti",
            "cordiali saluti",
            "dear",
            "sincerely",
            "regards",
            "professional",
        ],
    },
    "operational": {
        "tasks": [
            "task",
            "azione",
            "action item",
            "TODO",
            "deliverable",
            "deadline",
            "scadenza",
            "fatto",
            "done",
            "completato",
            "finito",
            "in progress",
            "pronto",
            "fatto",
            "action",
            "deliver",
        ],
        "process": [
            "procedura",
            "processo",
            "workflow",
            "step",
            "fase",
            "stage",
            "procedure",
            "process",
            "workflow",
            "step",
            "phase",
            "stage",
        ],
        "schedule": [
            "domani",
            "venerdì",
            "questa settimana",
            "entro",
            "lunedì",
            "martedì",
            "mercoledì",
            "giovedì",
            "sabato",
            "domenica",
            "tomorrow",
            "friday",
            "this week",
            "by",
            "monday",
            "tuesday",
            "wednesday",
            "thursday",
            "saturday",
            "sunday",
        ],
        "technical_functional": [
            "database",
            "API",
            "dashboard",
            "feature",
            "bug",
            "test",
            "deploy",
            "code",
            "server",
            "client",
            "frontend",
            "backend",
            "SQL",
            "database",
            "API",
            "dashboard",
            "feature",
            "bug",
        ],
        "numbers_metrics": [r"\d+%", r"\d+\s*(euro|dollars?|£)", r"KPI", r"metric", r"analytics"],
        "directive_language": [
            "devi fare",
            "occorre",
            "bisogna",
            "avere cura di",
            "importante",
            "must",
            "need to",
            "should",
            "required",
            "important",
            "must do",
        ],
    },
    "transactional": {
        "confirmations": [
            "si",
            "no",
            "ok",
            "d'accordo",
            "perfetto",
            "certo",
            "grazie",
            "grazie mille",
            "capito",
            "esatto",
            "giusto",
            "va bene",
            "yes",
            "no",
            "okay",
            "perfect",
            "sure",
            "thanks",
            "thank you",
            "got it",
            "exactly",
            "right",
            "fine",
        ],
        "logistics": [
            "dove",
            "quando",
            "con chi",
            "zoom link",
            "calendar invite",
            "numero",
            "indirizzo",
            "ora",
            "minuto",
            "where",
            "when",
            "who",
            "zoom",
            "link",
            "invite",
            "address",
            "time",
            "minute",
        ],
        "minimal_elaboration_markers": [r"^ok", r"^yes", r"^no", r"^sure", r"^got it"],
    },
}



DURATION_WEIGHTS: dict[str, tuple[float, float]] = {
    "personal": (30, 60, 1.0),
    "strategic": (45, 90, 1.0),
    "operational": (20, 60, 1.0),
    "transactional": (1, 5, 0.5),
}


@dataclass
class TranscriptClassification:
    ""

    category: str
    score: float
    confidence: float
    signals: list[tuple[str, int]] = field(default_factory=list)
    duration_factor: float = 1.0
    reasoning: str = ""
    language: str = "unknown"
    segment_count: int = 0


class TranscriptContentClassifier:
    ""


    CATEGORY_SCORES = {
        "personal": 0.8,
        "strategic": 0.6,
        "operational": 0.4,
        "transactional": 0.2,
    }

    def __init__(self):
        ""
        self.category_keywords = CATEGORY_KEYWORDS
        self.compiled_patterns: dict[str, dict[str, list]] = self._compile_patterns()
        log.debug("TranscriptContentClassifier initialized")

    def _compile_patterns(self) -> dict[str, dict[str, list]]:
        ""
        compiled = {}
        for category, subcats in self.category_keywords.items():
            compiled[category] = {}
            for subcat, patterns in subcats.items():
                compiled_list = []
                for pattern in patterns:

                    if any(c in pattern for c in r"\^$.*+?[]{}|()"):
                        try:
                            compiled_list.append(("regex", re.compile(pattern, re.IGNORECASE)))
                        except re.error:
                            log.warning(f"Invalid regex pattern: {pattern}")
                            compiled_list.append(("literal", pattern.lower()))
                    else:
                        compiled_list.append(("literal", pattern.lower()))
                compiled[category][subcat] = compiled_list
        return compiled

    def classify_transcript(
        self,
        transcript_text: str,
        duration_minutes: float = 30.0,
        source: str = "tactiq",
        language: str = "it",
        segment_count: int = 1,
    ) -> TranscriptClassification:
        ""











        if not transcript_text or not transcript_text.strip():
            return TranscriptClassification(
                category="transactional",
                score=0.2,
                confidence=0.1,
                reasoning="Empty transcript",
                segment_count=segment_count,
            )

        text_lower = transcript_text.lower()
        text_len = len(transcript_text)


        category_scores: dict[str, tuple[float, list[tuple[str, int]]]] = {}

        for category in self.CATEGORY_SCORES.keys():
            score, signals = self._score_category(text_lower, category, text_len)
            category_scores[category] = (score, signals)


        best_category = max(category_scores.keys(), key=lambda c: category_scores[c][0])
        best_base_score, best_signals = category_scores[best_category]


        duration_factor = self._compute_duration_factor(duration_minutes, best_category)
        final_score = min(0.8, self.CATEGORY_SCORES[best_category] * duration_factor)


        confidence = self._compute_confidence(best_base_score, best_signals, len(category_scores))


        top_signals = sorted(best_signals, key=lambda x: x[1], reverse=True)[:3]
        signal_str = ", ".join([f"{sig[0]}({sig[1]})" for sig in top_signals])
        reasoning = (
            f"Category: {best_category}, signals: {signal_str}, duration: {duration_minutes:.1f}min"
        )

        return TranscriptClassification(
            category=best_category,
            score=round(final_score, 4),
            confidence=round(confidence, 4),
            signals=best_signals,
            duration_factor=round(duration_factor, 4),
            reasoning=reasoning,
            language=language,
            segment_count=segment_count,
        )

    def _score_category(self, text_lower: str, category: str, text_len: int) -> tuple[float, list]:
        ""



        score = 0.0
        signals: dict[str, int] = {}

        if category not in self.compiled_patterns:
            return 0.0, []

        subcats = self.compiled_patterns[category]


        for subcat, patterns in subcats.items():
            for pattern_type, pattern in patterns:
                count = 0
                if pattern_type == "regex":
                    count = len(pattern.findall(text_lower))
                else:

                    count = len(re.findall(rf"\b{re.escape(pattern)}\b", text_lower, re.IGNORECASE))

                if count > 0:
                    signal_name = f"{category}:{subcat}"
                    signals[signal_name] = count

                    score += count * 0.1


        if text_len > 0:
            score = min(1.0, score / (text_len / 100))
        else:
            score = 0.0


        signal_list = sorted(signals.items(), key=lambda x: x[1], reverse=True)

        return score, signal_list

    def _compute_duration_factor(self, duration_minutes: float, category: str) -> float:
        ""



        if category not in DURATION_WEIGHTS:
            return 1.0

        min_sweet, max_sweet, _ = DURATION_WEIGHTS[category]

        if duration_minutes < 5:
            return 0.5
        elif duration_minutes < min_sweet:

            return 0.5 + (duration_minutes - 5) / (min_sweet - 5) * 0.5
        elif duration_minutes <= max_sweet:
            return 1.0
        elif duration_minutes < 180:

            return 1.0 + (duration_minutes - max_sweet) / (180 - max_sweet) * 0.5
        else:
            return 1.5

    def _compute_confidence(self, base_score: float, signals: list, num_categories: int) -> float:
        ""






        confidence = 0.3


        signal_count = len(signals)
        if signal_count == 0:
            return 0.1
        elif signal_count == 1:
            confidence = 0.35
        elif signal_count <= 3:
            confidence = 0.50
        elif signal_count <= 6:
            confidence = 0.70
        else:
            confidence = 0.85


        if base_score > 0.7:
            confidence = min(1.0, confidence + 0.15)
        elif base_score > 0.5:
            confidence = min(1.0, confidence + 0.10)

        return round(confidence, 4)

    def classify_segments(
        self,
        segments: list[dict],
        duration_minutes: float = 30.0,
        source: str = "plaud",
    ) -> list[dict]:
        ""









        if not segments:
            return []

        results = []
        for seg in segments:
            content = seg.get("content", "")
            seg_confidence = seg.get("confidence", 0.8)
            start = seg.get("start_time", 0)
            end = seg.get("end_time", 0)

            classification = self.classify_transcript(
                content,
                duration_minutes,
                source=source,
                segment_count=1,
            )

            results.append(
                {
                    "content": content[:100],
                    "category": classification.category,
                    "score": classification.score,
                    "confidence": classification.confidence,
                    "segment_confidence": seg_confidence,
                    "start_ms": start,
                    "end_ms": end,
                    "reasoning": classification.reasoning,
                }
            )

        return results


def load_classifier() -> TranscriptContentClassifier:
    ""
    return TranscriptContentClassifier()





def backfill_transcript_classifications(
    data_root: Path,
    *,
    force: bool = False,
) -> dict[str, dict]:
    ""




    output_file = data_root / "rq" / "transcript-classifications.json"
    if output_file.exists() and not force:
        return json.loads(output_file.read_text(encoding="utf-8"))

    classifier = load_classifier()
    person_categories: dict[str, dict[str, int]] = {}

    def _add_classification(pid: str, category: str) -> None:
        person_categories.setdefault(
            pid, {"personal": 0, "strategic": 0, "operational": 0, "transactional": 0}
        )
        person_categories[pid][category] += 1


    plaud_results = data_root / "plaud" / "processed" / "_full_results_v2.json"
    if plaud_results.exists():
        try:
            recordings = json.loads(plaud_results.read_text(encoding="utf-8"))
            if isinstance(recordings, list):
                for rec in recordings:
                    segments = rec.get("segments", [])
                    text = " ".join(s.get("content", "") for s in segments if isinstance(s, dict))
                    duration = rec.get("duration_min", 30.0) or 30.0
                    title = rec.get("title", "")
                    if not text or len(text) < 50:
                        continue
                    result = classifier.classify_transcript(text, duration, source="plaud")

                    if title:
                        _add_classification(f"plaud:{title[:60]}", result.category)
                log.info("Plaud: classified %d recordings", len(recordings))
        except (json.JSONDecodeError, OSError) as e:
            log.warning("Failed to load Plaud results: %s", e)


    tactiq_dir = data_root / "tactiq" / "raw"
    if tactiq_dir.exists():
        tq_count = 0
        for f in sorted(tactiq_dir.glob("*.json")):
            if f.name.startswith("_"):
                continue
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    continue
                transcript = data.get("transcript", {})
                if isinstance(transcript, dict):

                    parts = []
                    for val in transcript.values():
                        if isinstance(val, list):
                            for seg in val:
                                if isinstance(seg, dict):
                                    parts.append(seg.get("text", ""))
                                elif isinstance(seg, str):
                                    parts.append(seg)
                        elif isinstance(val, str):
                            parts.append(val)
                    text = " ".join(parts)
                elif isinstance(transcript, list):
                    text = " ".join(s.get("text", "") for s in transcript if isinstance(s, dict))
                else:
                    text = str(transcript)
                duration_raw = data.get("duration", 0)
                duration = (duration_raw / 60) if duration_raw > 300 else duration_raw or 30.0
                meeting_id = data.get("id", f.stem)
                participants = data.get("participants", [])
                if not text or len(text) < 50:
                    continue
                result = classifier.classify_transcript(text, duration, source="tactiq")
                if participants:
                    for p in participants:
                        pid = p if isinstance(p, str) else p.get("person_id", str(p))
                        if pid:
                            _add_classification(pid, result.category)
                else:
                    _add_classification(f"tactiq:{meeting_id}", result.category)
                tq_count += 1
            except (json.JSONDecodeError, OSError):
                continue
        log.info("Tactiq: classified %d meetings", tq_count)


    results: dict[str, dict] = {}
    for pid, cats in person_categories.items():
        total = sum(cats.values())
        if total == 0:
            continue
        dominant = max(cats, key=cats.get)

        cat_scores = {"personal": 0.8, "strategic": 0.6, "operational": 0.4, "transactional": 0.2}
        weighted_score = sum(cats[c] * cat_scores[c] for c in cats) / total
        results[pid] = {
            **cats,
            "total": total,
            "dominant_category": dominant,
            "content_quality_score": round(weighted_score, 4),
        }


    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=2, ensure_ascii=False)
    log.info("Transcript classifications: %d persons, saved to %s", len(results), output_file)

    return results




if __name__ == "__main__":
    import argparse
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from sbk_config import DATA_ROOT

    parser = argparse.ArgumentParser(description="RQV4-04 T2: Transcript Content Classifier")
    parser.add_argument("--backfill", action="store_true", help="Classify all transcripts and save")
    parser.add_argument(
        "--force", action="store_true", help="Force re-classify even if cache exists"
    )
    parser.add_argument("--test", action="store_true", help="Run built-in test examples")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    if args.backfill:
        results = backfill_transcript_classifications(DATA_ROOT, force=args.force)

        cats = {"personal": 0, "strategic": 0, "operational": 0, "transactional": 0}
        for r in results.values():
            cats[r["dominant_category"]] += 1
        log.info("Dominant categories: %s", cats)
        log.info("Total persons classified: %d", len(results))
        sys.exit(0)


    examples = [
        ("personal", "Hi! How are you? How did the family holiday go? I was on vacation.", 45.0),
        (
            "strategic",
            "Acquisition strategy in the fintech market. Three targets identified. The board approved.",
            75.0,
        ),
        ("operational", "Action items: Sam tests the database by Friday, deploy Monday.", 30.0),
        ("transactional", "Yes, perfect. Tomorrow at 3 okay? Ok, see you tomorrow!", 3.0),
    ]

    classifier = load_classifier()
    for expected, text, duration in examples:
        result = classifier.classify_transcript(text, duration)
        match = "OK" if result.category == expected else "FAIL"
        print(
            f"  [{match}] {expected:15s} -> {result.category:15s} (score={result.score:.2f}, conf={result.confidence:.2f})"
        )
