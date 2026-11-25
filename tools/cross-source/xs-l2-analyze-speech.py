#!/usr/bin/env python3
""
















import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))
_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

from xs_l3_common import get_excluded_attio_meeting_ids, get_excluded_tactiq_meeting_ids

from sbk_config import (
    ATTIO_TRANSCRIPTS_DIR,
    ENRICHED_DIR,
    PLAUD_PROCESSED_DIR,
    TACTIQ_DIR,
    attio_transcript_files,
    is_owner_speaker,
    mark_last_run,
    safe_write_json,
)



PLAUD_CORPUS_PATH = PLAUD_PROCESSED_DIR / "owner-speech-corpus.json"
TACTIQ_CORPUS_PATH = TACTIQ_DIR / "owner-speech-corpus-tactiq.json"
ATTIO_TRANSCRIPTS_PATH = ATTIO_TRANSCRIPTS_DIR
CORPUS_PATH = PLAUD_CORPUS_PATH
OUTPUT_PATH = ENRICHED_DIR / "speech-analysis.json"




CATEGORY_PRIORITY = {
    "monologue": 0,
    "clean_multi": 1,
    "owner_only_multi": 2,
    "partial_id": 3,
    "attio_call": 1,
    "tactiq_meeting": 1,
    "no_id": 4,
}

MIN_CONFIDENCE = 0.6


IT_STOPWORDS = {
    "il",
    "lo",
    "la",
    "i",
    "gli",
    "le",
    "un",
    "uno",
    "una",
    "di",
    "del",
    "dello",
    "della",
    "dei",
    "degli",
    "delle",
    "a",
    "al",
    "allo",
    "alla",
    "ai",
    "agli",
    "alle",
    "da",
    "dal",
    "dallo",
    "dalla",
    "dai",
    "dagli",
    "dalle",
    "in",
    "nel",
    "nello",
    "nella",
    "nei",
    "negli",
    "nelle",
    "con",
    "su",
    "sul",
    "sullo",
    "sulla",
    "sui",
    "sugli",
    "sulle",
    "per",
    "tra",
    "fra",
    "e",
    "ed",
    "o",
    "od",
    "ma",
    "se",
    "che",
    "chi",
    "cui",
    "non",
    "ne",
    "ni",
    "ci",
    "vi",
    "si",
    "mi",
    "ti",
    "questo",
    "quello",
    "questa",
    "quella",
    "questi",
    "quelli",
    "queste",
    "quelle",
    "io",
    "tu",
    "lui",
    "lei",
    "noi",
    "voi",
    "loro",
    "esso",
    "essa",
    "me",
    "te",
    "mio",
    "mia",
    "miei",
    "mie",
    "tuo",
    "tua",
    "tuoi",
    "tue",
    "suo",
    "sua",
    "suoi",
    "sue",
    "nostro",
    "nostra",
    "nostri",
    "nostre",
    "vostro",
    "vostra",
    "vostri",
    "vostre",
    "essere",
    "avere",
    "fare",
    "dire",
    "andare",
    "potere",
    "volere",
    "dovere",
    "ho",
    "ha",
    "hai",
    "hanno",
    "abbiamo",
    "avete",
    "sono",
    "sei",
    "siamo",
    "siete",
    "era",
    "ero",
    "eri",
    "erano",
    "eravamo",
    "eravate",
    "fatto",
    "detto",
    "stato",
    "stata",
    "stati",
    "state",
    "fa",
    "fai",
    "fanno",
    "facciamo",
    "fate",
    "va",
    "vai",
    "vanno",
    "andiamo",
    "andate",
    "posso",
    "puoi",
    "puo",
    "può",
    "possiamo",
    "potete",
    "possono",
    "voglio",
    "vuoi",
    "vuole",
    "vogliamo",
    "volete",
    "vogliono",
    "devo",
    "devi",
    "deve",
    "dobbiamo",
    "dovete",
    "devono",
    "cosa",
    "come",
    "dove",
    "quando",
    "quanto",
    "quanta",
    "quanti",
    "quante",
    "molto",
    "molta",
    "molti",
    "molte",
    "poco",
    "poca",
    "pochi",
    "poche",
    "tutto",
    "tutta",
    "tutti",
    "tutte",
    "ogni",
    "altro",
    "altra",
    "altri",
    "altre",
    "stesso",
    "stessa",
    "stessi",
    "stesse",
    "primo",
    "prima",
    "secondo",
    "seconda",
    "anche",
    "ancora",
    "gia",
    "già",
    "mai",
    "sempre",
    "solo",
    "proprio",
    "piu",
    "più",
    "meno",
    "tanto",
    "poi",
    "qui",
    "qua",
    "li",
    "lì",
    "là",
    "cosi",
    "così",
    "ora",
    "adesso",
    "dopo",
    "pero",
    "però",
    "cioe",
    "cioè",
    "quindi",
    "perche",
    "perché",
    "stare",
    "sto",
    "stai",
    "sta",
    "stiamo",
    "stanno",
    "c'è",
    "ce",
    "c'e",
    "no",
    "sì",
    "eh",
    "ok",
    "beh",
    "ah",
    "oh",
    "anno",
    "parte",
    "modo",
    "senso",

    "do",
    "dice",
    "vede",
    "viene",
    "mette",
    "prende",
    "tiene",
    "visto",
    "preso",
    "messo",
}


EN_STOPWORDS = {
    "the",
    "a",
    "an",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "being",
    "have",
    "has",
    "had",
    "do",
    "does",
    "did",
    "will",
    "would",
    "could",
    "should",
    "may",
    "might",
    "shall",
    "can",
    "i",
    "you",
    "he",
    "she",
    "it",
    "we",
    "they",
    "me",
    "him",
    "her",
    "us",
    "them",
    "my",
    "your",
    "his",
    "its",
    "our",
    "their",
    "this",
    "that",
    "these",
    "those",
    "of",
    "in",
    "to",
    "for",
    "with",
    "on",
    "at",
    "from",
    "by",
    "about",
    "as",
    "into",
    "through",
    "during",
    "before",
    "after",
    "and",
    "but",
    "or",
    "not",
    "so",
    "if",
    "than",
    "what",
    "which",
    "who",
    "whom",
    "when",
    "where",
    "how",
    "why",
    "all",
    "each",
    "every",
    "both",
    "few",
    "more",
    "most",
    "other",
    "some",
    "such",
    "no",
    "only",
    "same",
    "just",
    "very",
    "also",
}

ALL_STOPWORDS = IT_STOPWORDS | EN_STOPWORDS


IT_FILLERS = [
    "cioè",
    "cioe",
    "praticamente",
    "diciamo",
    "tipo",
    "allora",
    "insomma",
    "comunque",
    "ecco",
    "vabbè",
    "vabbe",
    "vabbeh",
    "niente",
    "boh",
    "mah",
    "oddio",
    "capito",
    "senti",
    "guarda",
    "dai",
    "fondamentalmente",
    "sostanzialmente",
    "effettivamente",
    "magari",
    "figurati",
    "appunto",
]


EN_FILLERS = [
    "like",
    "basically",
    "actually",
    "you know",
    "i mean",
    "literally",
    "right",
    "so",
    "well",
    "anyway",
    "kind of",
    "sort of",
]


EN_BUSINESS_TERMS = [
    "business",
    "marketing",
    "performance",
    "team",
    "meeting",
    "deal",
    "company",
    "startup",
    "founder",
    "investor",
    "fundraising",
    "pitch",
    "revenue",
    "budget",
    "target",
    "pipeline",
    "platform",
    "dashboard",
    "feedback",
    "skill",
    "leader",
    "manager",
    "board",
    "exit",
    "cash",
    "cashflow",
    "cash flow",
    "account",
    "client",
    "campaign",
    "tool",
    "tech",
    "technology",
    "software",
    "AI",
    "data",
    "brand",
    "branding",
    "growth",
    "scaling",
    "scale",
    "acquisition",
    "merge",
    "holding",
    "equity",
    "valuation",
    "advisory",
    "consulting",
    "partner",
    "partnership",
    "best practice",
    "roadmap",
    "sprint",
    "OKR",
    "KPI",
    "bootstrap",
    "break even",
    "breakeven",
    "call",
    "follow up",
    "follow-up",
    "onboarding",
    "offboarding",
    "network",
    "networking",
    "mindset",
    "challenge",
    "opportunity",
    "bottom line",
    "top line",
    "run rate",
    "burn rate",
    "cap table",
    "term sheet",
    "due diligence",
    "smart",
    "cool",
    "ok",
    "nice",
    "crazy",
    "storytelling",
    "content",
]


DECISION_PATTERNS = [
    r"facciamo cos[iì]",
    r"andiamo con",
    r"la mia idea [eè]",
    r"io (?:penso|credo) che",
    r"secondo me",
    r"la (?:cosa|strada) (?:giusta|migliore)",
    r"dobbiamo (?:fare|andare|prendere|decidere)",
    r"(?:decidiamo|procediamo|chiudiamo)",
    r"il piano [eè]",
    r"la strategia [eè]",
    r"(?:si|no),?\s*procediamo",
    r"io (?:voglio|vorrei) che",
    r"(?:punto|focus|priorit[aà])\s+(?:[eè]|numero uno|principale)",
    r"la direzione [eè]",
    r"(?:confermiamo|confermo|confermato)",
    r"(?:accetto|rifiuto|non accetto)",
    r"(?:il mio|nostro) obiettivo",
]


TEACHING_PATTERNS = [
    r"tu devi",
    r"il punto [eè]",
    r"la chiave [eè]",
    r"(?:devi|bisogna|serve) capire",
    r"ti spiego",
    r"(?:ricorda|ricordati) che",
    r"(?:il problema|l'errore) [eè]",
    r"non (?:devi|puoi|bisogna)",
    r"(?:la regola|il principio) [eè]",
    r"(?:fai|fate) attenzione",
    r"(?:sai cosa|sai che cosa)",
    r"(?:vedi|guarda),?\s*(?:il punto|quando|se)",
    r"(?:pensa|pensaci|ragiona)",
    r"(?:la lezione|l'insegnamento|il takeaway) [eè]",
    r"non dare per scontato",
    r"prima (?:di tutto|cosa|devi)",
    r"il segreto [eè]",
    r"in pratica (?:significa|vuol dire)",
]





def tokenize(text):
    ""
    return re.findall(r"[a-zà-ú']+", text.lower())


def split_sentences(text):
    ""

    sents = re.split(r"[.!?]+\s*", text)
    return [s.strip() for s in sents if s.strip() and len(s.strip()) > 3]


def is_question(sentence):
    ""
    s = sentence.strip()
    if s.endswith("?"):
        return True

    q_starters = [
        "come",
        "cosa",
        "dove",
        "quando",
        "quanto",
        "quanti",
        "chi",
        "perché",
        "perche",
        "quale",
        "quali",
        "che cosa",
    ]
    lower = s.lower()
    for q in q_starters:
        if lower.startswith(q + " "):
            return True
    return False


def is_imperative(sentence):
    ""
    lower = sentence.strip().lower()
    imp_starters = [
        "fai",
        "fate",
        "fammi",
        "facciamo",
        "dimmi",
        "digli",
        "dille",
        "andiamo",
        "andate",
        "vai",
        "procediamo",
        "ricorda",
        "ricordati",
        "pensa",
        "pensaci",
        "guarda",
        "senti",
        "prendi",
        "prova",
        "provate",
        "manda",
        "mandami",
        "mandagli",
        "scrivi",
        "scrivimi",
        "chiama",
        "chiamami",
        "organizza",
        "prepara",
        "controlla",
        "verifica",
    ]
    for imp in imp_starters:
        if lower.startswith(imp + " ") or lower.startswith(imp + ",") or lower == imp:
            return True
    return False


def detect_language(text):
    ""
    words = tokenize(text)
    if not words:
        return "unknown"


    it_markers = {
        "perché",
        "perche",
        "anche",
        "questo",
        "questa",
        "quello",
        "quella",
        "dove",
        "quando",
        "siamo",
        "hanno",
        "abbiamo",
        "possiamo",
        "diciamo",
        "stiamo",
        "facciamo",
        "dobbiamo",
        "noi",
        "loro",
        "cioè",
        "cioe",
        "però",
        "pero",
        "quindi",
        "adesso",
        "sempre",
        "ancora",
    }


    en_markers = {
        "the",
        "is",
        "are",
        "was",
        "were",
        "have",
        "has",
        "been",
        "will",
        "would",
        "could",
        "should",
        "they",
        "them",
        "their",
        "what",
        "which",
        "where",
        "when",
        "because",
        "about",
        "with",
        "from",
        "into",
        "through",
        "before",
        "after",
    }

    it_count = sum(1 for w in words if w in it_markers)
    en_count = sum(1 for w in words if w in en_markers)

    total = it_count + en_count
    if total == 0:
        return "unknown"
    if en_count == 0:
        return "it"
    if it_count == 0:
        return "en"
    en_ratio = en_count / total
    if en_ratio > 0.7:
        return "en"
    if en_ratio > 0.2:
        return "mixed"
    return "it"


def extract_en_terms_in_context(text):
    ""
    found = []
    lower = text.lower()
    for term in EN_BUSINESS_TERMS:

        pattern = r"\b" + re.escape(term) + r"\b"
        matches = re.findall(pattern, lower)
        if matches:
            found.append((term, len(matches)))
    return found


def extract_golden_phrases(segments, min_words=8, max_words=40):
    ""
    candidates = []


    golden_indicators = [

        r"[eè] come (?:quando|se|un)",
        r"in un mondo di",
        r"(?:la|il) (?:chiave|segreto|punto|problema) [eè]",

        r"io (?:credo|penso|sono convinto) che",
        r"(?:non|mai) (?:bisogna|devi|puoi)",
        r"se (?:vuoi|volete) (?:fare|essere|avere)",

        r"(?:chi|quando|dove) .{10,} [eè] .{5,}",

        r"(?:noi|io) (?:facciamo|andiamo)",

        r"(\w{4,})\W+\1",

        r"(?:sai|capisci|vedi) (?:cosa|che|perché|come)",
    ]

    for seg in segments:
        content = seg["content"]
        sentences = split_sentences(content)
        for sent in sentences:
            words = sent.split()
            if len(words) < min_words or len(words) > max_words:
                continue

            score = 0
            lower = sent.lower()


            for pattern in golden_indicators:
                if re.search(pattern, lower):
                    score += 2


            if "!" in sent:
                score += 1


            strong_verbs: list[str] = []  # load from user config
            for v in strong_verbs:
                if v in lower:
                    score += 1


            filler_count = sum(1 for f in IT_FILLERS if f in lower)
            if filler_count > 2:
                score -= 2

            if score >= 2:
                candidates.append(
                    {
                        "phrase": sent,
                        "score": score,
                        "word_count": len(words),
                    }
                )


    for seg in segments:
        content = seg["content"]
        sentences = split_sentences(content)
        for sent in sentences:
            words = sent.split()
            wc = len(words)
            if 5 <= wc <= 15:
                lower = sent.lower()

                if any(
                    lower.startswith(s)
                    for s in [
                        "il punto è",
                        "la chiave è",
                        "il segreto è",
                        "fammi",
                        "io voglio",
                        "noi dobbiamo",
                    ]
                ):
                    candidates.append(
                        {
                            "phrase": sent,
                            "score": 3,
                            "word_count": wc,
                        }
                    )


    seen = set()
    unique = []
    for c in candidates:
        normalized = c["phrase"].lower().strip()
        if normalized not in seen:
            seen.add(normalized)
            unique.append(c)

    unique.sort(key=lambda x: x["score"], reverse=True)
    return unique[:100]


def find_pattern_matches(text, patterns):
    ""
    matches = []
    for pattern in patterns:
        for m in re.finditer(pattern, text.lower()):
            start = max(0, m.start() - 60)
            end = min(len(text), m.end() + 60)
            context = text[start:end].strip()
            matches.append(
                {
                    "pattern": pattern,
                    "match": m.group(),
                    "context": context,
                }
            )
    return matches





def load_plaud_corpus(path):
    ""
    with open(path) as f:
        return json.load(f)


def load_tactiq_corpus(path):
    ""









    with open(path) as f:
        raw = json.load(f)

    meetings = raw.get("meetings", [])
    normalized = []

    for m in meetings:
        segs = []
        for s in m.get("segments", []):
            segs.append(
                {
                    "content": s["text"],
                    "confidence": 1.0,
                    "start_time": s.get("timestamp", 0),
                    "end_time": s.get("timestamp", 0),
                }
            )

        normalized.append(
            {
                "source_file": m.get("meeting_id", ""),
                "title": m.get("title", ""),
                "category": "tactiq_meeting",
                "duration_min": m.get("duration_min", 0),
                "calendar_event": m.get("title", ""),
                "segments_count": len(segs),
                "segments": segs,
            }
        )

    return normalized


def load_attio_transcripts(transcripts_dir):
    ""










    files = attio_transcript_files(Path(transcripts_dir))
    normalized = []

    for f in files:
        data = json.loads(f.read_text(encoding="utf-8"))
        segments = data.get("segments", [])
        if not segments:
            continue


        merged_segs = []
        current_text_parts = []
        current_start = None

        for seg in segments:
            speaker = seg.get("speaker", "")
            if isinstance(speaker, dict):
                speaker = speaker.get("name") or speaker.get("displayName") or ""
            if not isinstance(speaker, str):
                speaker = str(speaker) if speaker else ""
            if is_owner_speaker(speaker):
                if current_start is None:
                    current_start = seg.get("start", 0)
                current_text_parts.append(seg.get("text", ""))
            else:

                if current_text_parts:
                    merged_text = " ".join(current_text_parts)
                    if len(merged_text.strip()) > 10:
                        merged_segs.append(
                            {
                                "content": merged_text,
                                "confidence": 0.85,
                                "start_time": current_start,
                                "end_time": seg.get("start", 0),
                            }
                        )
                    current_text_parts = []
                    current_start = None


        if current_text_parts:
            merged_text = " ".join(current_text_parts)
            if len(merged_text.strip()) > 10:
                merged_segs.append(
                    {
                        "content": merged_text,
                        "confidence": 0.85,
                        "start_time": current_start,
                        "end_time": segments[-1].get("end", 0),
                    }
                )

        if merged_segs:
            normalized.append(
                {
                    "source_file": data.get("meeting_id", f.stem),
                    "title": data.get("meeting_title", ""),
                    "category": "attio_call",
                    "duration_min": round(
                        (segments[-1].get("end", 0) - segments[0].get("start", 0)) / 60, 1
                    )
                    if segments
                    else 0,
                    "calendar_event": data.get("meeting_title", ""),
                    "segments_count": len(merged_segs),
                    "segments": merged_segs,
                }
            )

    return normalized





def analyze_corpus(corpus, verbose=False, source_label=None):
    ""






    label = f" [{source_label}]" if source_label else ""


    priority_categories = [
        "monologue",
        "clean_multi",
        "owner_only_multi",
        "partial_id",
        "tactiq_meeting",
        "attio_call",
    ]
    entries = [e for e in corpus if e.get("category", "no_id") in priority_categories]
    entries.sort(key=lambda e: CATEGORY_PRIORITY.get(e.get("category", "no_id"), 5))

    if verbose:
        print(f"Total entries{label}: {len(corpus)}")
        print(f"Filtered entries (excl no_id){label}: {len(entries)}")


    all_segments = []
    all_text_parts = []
    segments_by_category = defaultdict(list)

    for entry in entries:
        cat = entry.get("category", "unknown")
        for seg in entry.get("segments", []):
            if seg.get("confidence", 1.0) >= MIN_CONFIDENCE:
                all_segments.append(
                    {
                        **seg,
                        "category": cat,
                        "source_file": entry.get("source_file", ""),
                        "title": entry.get("title", ""),
                        "calendar_event": entry.get("calendar_event"),
                    }
                )
                all_text_parts.append(seg["content"])
                segments_by_category[cat].append(seg)

    full_text = " ".join(all_text_parts)
    all_words = tokenize(full_text)

    if verbose:
        print(f"Total segments (conf >= {MIN_CONFIDENCE}): {len(all_segments)}")
        print(f"Total words: {len(all_words)}")
        print(f"Segments by category: {dict((k, len(v)) for k, v in segments_by_category.items())}")
        print()



    word_freq = Counter(all_words)
    content_words = {w: c for w, c in word_freq.items() if w not in ALL_STOPWORDS and len(w) > 2}
    content_freq = Counter(content_words)

    total_words = len(all_words)
    unique_words = len(word_freq)
    vocabulary_richness = unique_words / total_words if total_words > 0 else 0


    hapax = [w for w, c in word_freq.items() if c == 1]

    vocab_analysis = {
        "total_words": total_words,
        "unique_words": unique_words,
        "vocabulary_richness": round(vocabulary_richness, 4),
        "hapax_legomena_count": len(hapax),
        "hapax_ratio": round(len(hapax) / unique_words, 4) if unique_words else 0,
        "top_100_content_words": content_freq.most_common(100),
        "top_50_all_words": word_freq.most_common(50),
    }

    if verbose:
        print("=== VOCABULARY ===")
        print(f"Total words: {total_words:,}")
        print(f"Unique words: {unique_words:,}")
        print(f"Richness (TTR): {vocabulary_richness:.4f}")
        print(f"Top 20 content words: {content_freq.most_common(20)}")
        print()



    filler_counts = {}
    for filler in IT_FILLERS + EN_FILLERS:
        pattern = r"\b" + re.escape(filler) + r"\b"
        count = len(re.findall(pattern, full_text.lower()))
        if count > 0:
            filler_counts[filler] = count


    filler_sorted = sorted(filler_counts.items(), key=lambda x: x[1], reverse=True)
    total_fillers = sum(filler_counts.values())
    filler_rate = total_fillers / total_words * 1000 if total_words else 0

    filler_analysis = {
        "total_filler_occurrences": total_fillers,
        "filler_rate_per_1000_words": round(filler_rate, 2),
        "fillers_ranked": filler_sorted,
        "italian_fillers_total": sum(c for f, c in filler_sorted if f in IT_FILLERS),
        "english_fillers_total": sum(c for f, c in filler_sorted if f in EN_FILLERS),
    }

    if verbose:
        print("=== FILLER WORDS ===")
        print(f"Total filler occurrences: {total_fillers}")
        print(f"Filler rate: {filler_rate:.1f} per 1000 words")
        print(f"Top fillers: {filler_sorted[:15]}")
        print()



    all_sentences = []
    questions = []
    imperatives = []

    for text_part in all_text_parts:
        sents = split_sentences(text_part)
        for s in sents:
            all_sentences.append(s)
            if is_question(s):
                questions.append(s)
            if is_imperative(s):
                imperatives.append(s)

    sentence_lengths = [len(s.split()) for s in all_sentences]
    avg_sentence_length = sum(sentence_lengths) / len(sentence_lengths) if sentence_lengths else 0


    starters = Counter()
    for s in all_sentences:
        words = s.split()
        if len(words) >= 2:
            starters[" ".join(words[:2]).lower()] += 1

    sentence_analysis = {
        "total_sentences": len(all_sentences),
        "avg_sentence_length_words": round(avg_sentence_length, 1),
        "median_sentence_length": sorted(sentence_lengths)[len(sentence_lengths) // 2]
        if sentence_lengths
        else 0,
        "questions_count": len(questions),
        "questions_pct": round(len(questions) / len(all_sentences) * 100, 1)
        if all_sentences
        else 0,
        "imperatives_count": len(imperatives),
        "imperatives_pct": round(len(imperatives) / len(all_sentences) * 100, 1)
        if all_sentences
        else 0,
        "top_sentence_starters": starters.most_common(30),
        "sample_questions": questions[:30],
        "sample_imperatives": imperatives[:30],
    }

    if verbose:
        print("=== SENTENCE PATTERNS ===")
        print(f"Total sentences: {len(all_sentences)}")
        print(f"Avg length: {avg_sentence_length:.1f} words")
        print(f"Questions: {len(questions)} ({len(questions) / len(all_sentences) * 100:.1f}%)")
        print(
            f"Imperatives: {len(imperatives)} ({len(imperatives) / len(all_sentences) * 100:.1f}%)"
        )
        print(f"Top starters: {starters.most_common(15)}")
        print()




    lang_counts = Counter()
    mixed_segments = []
    en_segments = []

    for seg in all_segments:
        lang = detect_language(seg["content"])
        lang_counts[lang] += 1
        if lang == "mixed":
            mixed_segments.append(
                {
                    "content": seg["content"][:300],
                    "source": seg.get("title", ""),
                    "calendar": seg.get("calendar_event", ""),
                }
            )
        elif lang == "en":
            en_segments.append(
                {
                    "content": seg["content"][:300],
                    "source": seg.get("title", ""),
                    "calendar": seg.get("calendar_event", ""),
                }
            )


    en_terms_in_it = Counter()
    for text_part in all_text_parts:
        terms = extract_en_terms_in_context(text_part)
        for term, count in terms:
            en_terms_in_it[term] += count

    code_switch_analysis = {
        "language_distribution": dict(lang_counts),
        "mixed_segments_count": len(mixed_segments),
        "english_segments_count": len(en_segments),
        "top_english_terms_in_italian": en_terms_in_it.most_common(50),
        "sample_mixed_segments": mixed_segments[:20],
        "sample_english_segments": en_segments[:20],
    }

    if verbose:
        print("=== LANGUAGE MIXING ===")
        print(f"Language distribution: {dict(lang_counts)}")
        print(f"Top EN terms in IT context: {en_terms_in_it.most_common(20)}")
        print()




    event_topics = defaultdict(lambda: {"count": 0, "total_words": 0, "segments": 0})
    for seg in all_segments:
        event = seg.get("calendar_event") or "No calendar event"
        words = tokenize(seg["content"])
        event_topics[event]["count"] += 1
        event_topics[event]["total_words"] += len(words)
        event_topics[event]["segments"] += 1


    # Generic business topic taxonomy. Replace or extend these keyword lists to
    # match the vocabulary of your own meetings; the counting logic below is
    # domain-agnostic.
    topic_keywords = {
        "sales": [
            "sales",
            "pipeline",
            "deal",
            "lead",
            "prospect",
            "quota",
            "revenue",
            "customer",
            "account",
            "renewal",
        ],
        "product": [
            "product",
            "feature",
            "roadmap",
            "release",
            "backlog",
            "design",
            "spec",
            "launch",
            "prototype",
        ],
        "engineering": [
            "platform",
            "software",
            "tool",
            "tech",
            "automation",
            "dashboard",
            "API",
            "infrastructure",
            "bug",
            "deployment",
        ],
        "hr": [
            "team",
            "people",
            "hiring",
            "onboarding",
            "performance",
            "culture",
            "role",
            "headcount",
            "review",
        ],
        "legal": [
            "legal",
            "contract",
            "agreement",
            "compliance",
            "terms",
            "policy",
            "dispute",
            "counsel",
        ],
        "finance": [
            "budget",
            "revenue",
            "cost",
            "margin",
            "cash",
            "forecast",
            "invoice",
            "pricing",
        ],
        "strategy": [
            "strategy",
            "vision",
            "plan",
            "roadmap",
            "goal",
            "target",
            "growth",
            "priority",
        ],
        "marketing": [
            "marketing",
            "campaign",
            "brand",
            "content",
            "advertising",
            "ads",
            "audience",
            "channel",
        ],
        "operations": [
            "operations",
            "process",
            "workflow",
            "logistics",
            "supplier",
            "vendor",
            "schedule",
        ],
        "partnerships": [
            "partner",
            "partnership",
            "integration",
            "alliance",
            "reseller",
            "collaboration",
        ],
    }

    topic_counts = {}
    topic_samples = {}
    for topic, keywords in topic_keywords.items():
        count = 0
        samples = []
        for seg in all_segments:
            lower = seg["content"].lower()
            if any(kw.lower() in lower for kw in keywords):
                count += 1
                if len(samples) < 5:
                    samples.append(seg["content"][:200])
        topic_counts[topic] = count
        topic_samples[topic] = samples

    topic_analysis = {
        "calendar_events": {
            k: v
            for k, v in sorted(event_topics.items(), key=lambda x: x[1]["segments"], reverse=True)[
                :30
            ]
        },
        "keyword_topics": dict(sorted(topic_counts.items(), key=lambda x: x[1], reverse=True)),
        "topic_samples": topic_samples,
    }

    if verbose:
        print("=== TOPICS ===")
        print("By calendar event (top 10):")
        for k, v in sorted(event_topics.items(), key=lambda x: x[1]["segments"], reverse=True)[:10]:
            print(f"  {k}: {v['segments']} segments, {v['total_words']} words")
        sorted_topics = dict(sorted(topic_counts.items(), key=lambda x: x[1], reverse=True))
        print(f"By keyword topics: {sorted_topics}")
        print()



    golden_raw = extract_golden_phrases(all_segments)


    short_expressions = Counter()
    for text_part in all_text_parts:

        words = text_part.lower().split()
        for n in range(3, 7):
            for i in range(len(words) - n):
                phrase = " ".join(words[i : i + n])

                content_count = sum(1 for w in words[i : i + n] if w not in ALL_STOPWORDS)
                if content_count >= 2:
                    short_expressions[phrase] += 1


    repeated_expressions = {k: v for k, v in short_expressions.items() if v >= 3}
    repeated_sorted = sorted(repeated_expressions.items(), key=lambda x: x[1], reverse=True)[:50]

    golden_analysis = {
        "golden_phrases": golden_raw[:60],
        "repeated_expressions": repeated_sorted,
    }

    if verbose:
        print("=== KEY PHRASES ===")
        print(f"Found {len(golden_raw)} candidate key phrases")
        for g in golden_raw[:10]:
            print(f"  [score={g['score']}] {g['phrase'][:100]}")
        print(f"Repeated expressions: {repeated_sorted[:15]}")
        print()



    decision_matches = []
    for seg in all_segments:
        matches = find_pattern_matches(seg["content"], DECISION_PATTERNS)
        for m in matches:
            m["source"] = seg.get("title", "")
            m["calendar"] = seg.get("calendar_event", "")
            decision_matches.append(m)


    decision_pattern_freq = Counter(m["pattern"] for m in decision_matches)

    decision_analysis = {
        "total_decision_markers": len(decision_matches),
        "pattern_frequency": decision_pattern_freq.most_common(),
        "sample_matches": decision_matches[:40],
    }

    if verbose:
        print("=== DECISION LANGUAGE ===")
        print(f"Total decision markers: {len(decision_matches)}")
        print(f"Pattern freq: {decision_pattern_freq.most_common(10)}")
        for m in decision_matches[:5]:
            print(f"  [{m['pattern']}] ...{m['context']}...")
        print()



    teaching_matches = []
    for seg in all_segments:
        matches = find_pattern_matches(seg["content"], TEACHING_PATTERNS)
        for m in matches:
            m["source"] = seg.get("title", "")
            m["calendar"] = seg.get("calendar_event", "")
            teaching_matches.append(m)

    teaching_pattern_freq = Counter(m["pattern"] for m in teaching_matches)

    teaching_analysis = {
        "total_teaching_markers": len(teaching_matches),
        "pattern_frequency": teaching_pattern_freq.most_common(),
        "sample_matches": teaching_matches[:40],
    }

    if verbose:
        print("=== TEACHING LANGUAGE ===")
        print(f"Total teaching markers: {len(teaching_matches)}")
        print(f"Pattern freq: {teaching_pattern_freq.most_common(10)}")
        for m in teaching_matches[:5]:
            print(f"  [{m['pattern']}] ...{m['context']}...")
        print()



    results = {
        "meta": {
            "source": source_label or "unknown",
            "corpus_entries": len(corpus),
            "analyzed_entries": len(entries),
            "analyzed_segments": len(all_segments),
            "total_chars": sum(len(t) for t in all_text_parts),
            "total_words": total_words,
            "min_confidence": MIN_CONFIDENCE,
            "categories_included": priority_categories,
            "skipped_categories": ["no_id"],
            "generated_at": __import__("datetime").datetime.now().isoformat(),
        },
        "vocabulary": vocab_analysis,
        "filler_words": filler_analysis,
        "sentence_patterns": sentence_analysis,
        "code_switching": code_switch_analysis,
        "topic_clusters": topic_analysis,
        "golden_phrases": golden_analysis,
        "decision_language": decision_analysis,
        "teaching_language": teaching_analysis,
    }

    return results


def print_summary(results, label=""):
    ""
    prefix = f"  [{label}] " if label else "  "
    print(f"{prefix}Segments analyzed: {results['meta']['analyzed_segments']}")
    print(f"{prefix}Total chars: {results['meta']['total_chars']:,}")
    print(f"{prefix}Total words: {results['meta']['total_words']:,}")
    print(f"{prefix}Unique words: {results['vocabulary']['unique_words']:,}")
    print(f"{prefix}Vocabulary richness: {results['vocabulary']['vocabulary_richness']}")
    print(
        f"{prefix}Filler rate: {results['filler_words']['filler_rate_per_1000_words']} per 1000 words"
    )
    print(f"{prefix}Questions: {results['sentence_patterns']['questions_pct']}%")
    print(f"{prefix}Imperatives: {results['sentence_patterns']['imperatives_pct']}%")
    print(f"{prefix}Decision markers: {results['decision_language']['total_decision_markers']}")
    print(f"{prefix}Teaching markers: {results['teaching_language']['total_teaching_markers']}")
    print(f"{prefix}Golden phrases found: {len(results['golden_phrases']['golden_phrases'])}")
    print(
        f"{prefix}Top EN terms in IT: {results['code_switching']['top_english_terms_in_italian'][:5]}"
    )





def main():
    parser = argparse.ArgumentParser(
        description="Analyze your speech corpus (Plaud + Tactiq)"
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Detailed output")
    parser.add_argument(
        "--plaud-corpus", type=str, default=str(PLAUD_CORPUS_PATH), help="Path to Plaud corpus JSON"
    )
    parser.add_argument(
        "--tactiq-corpus",
        type=str,
        default=str(TACTIQ_CORPUS_PATH),
        help="Path to Tactiq corpus JSON",
    )
    parser.add_argument(
        "--attio-transcripts",
        type=str,
        default=str(ATTIO_TRANSCRIPTS_PATH),
        help="Path to Attio transcripts directory",
    )
    parser.add_argument(
        "--corpus",
        type=str,
        default=None,
        help="(Legacy) Path to single corpus JSON — runs single-source mode",
    )
    parser.add_argument("--output", type=str, default=str(OUTPUT_PATH), help="Output path")
    parser.add_argument(
        "--dry-run", action="store_true", help="Show what would run without writing"
    )
    args = parser.parse_args()

    output_path = Path(args.output)


    if args.corpus:
        corpus_path = Path(args.corpus)
        if not corpus_path.exists():
            print(f"ERROR: Corpus not found at {corpus_path}")
            sys.exit(1)
        print(f"[legacy] Loading single corpus from {corpus_path}...")
        with open(corpus_path) as f:
            corpus = json.load(f)
        print(f"Loaded {len(corpus)} entries")
        print("Analyzing...")
        results = analyze_corpus(corpus, verbose=args.verbose, source_label="legacy")
        safe_write_json(output_path, results)
        print(f"Done! Analysis saved to {output_path}")
        print_summary(results)
        return


    plaud_path = Path(args.plaud_corpus)
    tactiq_path = Path(args.tactiq_corpus)
    attio_path = Path(args.attio_transcripts)

    plaud_corpus = []
    tactiq_corpus = []
    attio_corpus = []

    if plaud_path.exists():
        print(f"Loading Plaud corpus from {plaud_path}...")
        plaud_corpus = load_plaud_corpus(plaud_path)
        print(f"  Plaud: {len(plaud_corpus)} entries")
    else:
        print(f"WARNING: Plaud corpus not found at {plaud_path}, skipping")

    if tactiq_path.exists():
        print(f"Loading Tactiq corpus from {tactiq_path}...")
        tactiq_corpus = load_tactiq_corpus(tactiq_path)
        print(f"  Tactiq: {len(tactiq_corpus)} entries (meetings)")
    else:
        print(f"WARNING: Tactiq corpus not found at {tactiq_path}, skipping")

    if attio_path.exists() and attio_path.is_dir():
        print(f"Loading Attio transcripts from {attio_path}...")
        attio_corpus = load_attio_transcripts(attio_path)
        attio_segs = sum(e["segments_count"] for e in attio_corpus)
        print(f"  Attio: {len(attio_corpus)} calls, {attio_segs} of your utterances")
    else:
        print(f"WARNING: Attio transcripts not found at {attio_path}, skipping")


    if tactiq_corpus:
        excluded_tactiq = get_excluded_tactiq_meeting_ids()
        if excluded_tactiq:
            before = len(tactiq_corpus)
            tactiq_corpus = [
                t for t in tactiq_corpus if t.get("source_file") not in excluded_tactiq
            ]
            filtered = before - len(tactiq_corpus)
            if filtered:
                print(
                    f"  Tactiq dedup: filtered {filtered} meetings (Attio won), {len(tactiq_corpus)} remaining"
                )

    if attio_corpus:
        excluded_attio = get_excluded_attio_meeting_ids()
        if excluded_attio:
            before = len(attio_corpus)
            attio_corpus = [a for a in attio_corpus if a.get("source_file") not in excluded_attio]
            filtered = before - len(attio_corpus)
            if filtered:
                print(
                    f"  Attio dedup: filtered {filtered} meetings (Tactiq won), {len(attio_corpus)} remaining"
                )

    if not plaud_corpus and not tactiq_corpus and not attio_corpus:
        print("ERROR: No corpus data found. Provide at least one source.")
        sys.exit(1)


    combined_corpus = plaud_corpus + tactiq_corpus + attio_corpus


    print("\n" + "=" * 60)
    print("Analyzing COMBINED corpus...")
    print("=" * 60)
    combined_results = analyze_corpus(
        combined_corpus, verbose=args.verbose, source_label="combined"
    )

    plaud_results = None
    if plaud_corpus:
        print("\n" + "=" * 60)
        print("Analyzing PLAUD corpus...")
        print("=" * 60)
        plaud_results = analyze_corpus(plaud_corpus, verbose=args.verbose, source_label="plaud")

    tactiq_results = None
    if tactiq_corpus:
        print("\n" + "=" * 60)
        print("Analyzing TACTIQ corpus...")
        print("=" * 60)
        tactiq_results = analyze_corpus(tactiq_corpus, verbose=args.verbose, source_label="tactiq")

    attio_results = None
    if attio_corpus:
        print("\n" + "=" * 60)
        print("Analyzing ATTIO corpus...")
        print("=" * 60)
        attio_results = analyze_corpus(attio_corpus, verbose=args.verbose, source_label="attio")


    final_output = {
        "meta": {
            "sources": [],
            "combined_segments": combined_results["meta"]["analyzed_segments"],
            "combined_chars": combined_results["meta"]["total_chars"],
            "combined_words": combined_results["meta"]["total_words"],
            "generated_at": __import__("datetime").datetime.now().isoformat(),
        },
        "combined": combined_results,
    }

    if plaud_results:
        final_output["plaud"] = plaud_results
        final_output["meta"]["sources"].append(
            {
                "name": "plaud",
                "path": str(plaud_path),
                "entries": plaud_results["meta"]["corpus_entries"],
                "segments": plaud_results["meta"]["analyzed_segments"],
                "chars": plaud_results["meta"]["total_chars"],
                "words": plaud_results["meta"]["total_words"],
            }
        )

    if tactiq_results:
        final_output["tactiq"] = tactiq_results
        final_output["meta"]["sources"].append(
            {
                "name": "tactiq",
                "path": str(tactiq_path),
                "entries": tactiq_results["meta"]["corpus_entries"],
                "segments": tactiq_results["meta"]["analyzed_segments"],
                "chars": tactiq_results["meta"]["total_chars"],
                "words": tactiq_results["meta"]["total_words"],
            }
        )

    if attio_results:
        final_output["attio"] = attio_results
        final_output["meta"]["sources"].append(
            {
                "name": "attio",
                "path": str(attio_path),
                "entries": attio_results["meta"]["corpus_entries"],
                "segments": attio_results["meta"]["analyzed_segments"],
                "chars": attio_results["meta"]["total_chars"],
                "words": attio_results["meta"]["total_words"],
            }
        )


    if args.dry_run:
        print(f"\n[DRY RUN] Would write results to {output_path}")
        print(
            f"[DRY RUN] Sources: {len(final_output['meta']['sources'])}, "
            f"combined segments: {final_output['meta']['combined_segments']}"
        )
    else:
        print(f"\nWriting results to {output_path}...")
        safe_write_json(output_path, final_output)

        mark_last_run("speech-analysis")
        print(f"Done! Analysis saved to {output_path}")

    print(f"\n{'=' * 60}")
    print("SUMMARY")
    print(f"{'=' * 60}")

    print("\nCOMBINED:")
    print_summary(combined_results, "combined")

    if plaud_results:
        print("\nPLAUD:")
        print_summary(plaud_results, "plaud")

    if tactiq_results:
        print("\nTACTIQ:")
        print_summary(tactiq_results, "tactiq")

    if attio_results:
        print("\nATTIO:")
        print_summary(attio_results, "attio")


from pipeline_decorator import pipeline_step


@pipeline_step(name="l2-analyze-speech", source="speech-analysis", stage="l2", mark_run=False)
def _pipeline_run():
    main()


if __name__ == "__main__":
    _pipeline_run()
