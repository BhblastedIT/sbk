""



















from __future__ import annotations

import logging
import re
from calendar import monthrange
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

log = logging.getLogger("sbk-query-preprocessor")



ACRONYMS: dict[str, str] = {
    "crm": "Attio CRM",
    "m&a": "merger acquisition fusione acquisizione",
    "hr": "risorse umane human resources personio",
    "cfo": "chief financial officer direttore finanziario",
    "ceo": "chief executive officer amministratore delegato",
    "cto": "chief technology officer",
    "coo": "chief operating officer",
    "pnl": "profit and loss conto economico",
    "kpi": "key performance indicator",
    "roi": "return on investment",
    "arr": "annual recurring revenue",
    "mrr": "monthly recurring revenue",
    "nda": "non disclosure agreement riservatezza",
}


def _own_org_acronyms() -> dict[str, str]:
    """Abbreviations of your own organisations ("organisations.aliases" in sbk.config.json)."""
    try:
        from sbk_config import OWN_ORG_ALIASES
    except ImportError:  # imported without tools/ on sys.path
        return {}
    return {k.lower(): v for k, v in OWN_ORG_ALIASES.items() if " " not in k.strip()}


ACRONYMS.update(_own_org_acronyms())


def normalize_query(query: str) -> str:
    ""
    if not query:
        return ""
    return " ".join(query.strip().split())


def expand_acronyms(query: str) -> list[str]:
    ""
    variants = [query]
    words = query.lower().split()
    for word in words:
        if word in ACRONYMS:
            expanded = re.sub(re.escape(word), ACRONYMS[word], query, count=1, flags=re.IGNORECASE)
            if expanded != query:
                variants.append(expanded)
    return list(dict.fromkeys(variants))





def _load_contacts_names() -> tuple[list[str], dict[str, str]]:
    ""



    try:
        import sys

        tools_dir = str(Path(__file__).resolve().parent.parent)
        if tools_dir not in sys.path:
            sys.path.insert(0, tools_dir)
        import pandas as pd

        from sbk_config import ENRICHED_DIR

        path = ENRICHED_DIR / "contacts-merged.parquet"
        if not path.exists():
            log.warning(f"Contacts file not found: {path}")
            return [], {}
        df = pd.read_parquet(path, columns=["name", "email"])
        names = df["name"].dropna().unique().tolist()
        name_to_email = {}
        for _, row in df[["name", "email"]].dropna().iterrows():
            name_to_email[str(row["name"]).lower()] = str(row["email"])
        return names, name_to_email
    except Exception as e:
        log.warning(f"Failed to load contacts: {e}")
        return [], {}


@dataclass
class PersonMatch:
    ""

    original: str
    resolved_name: str
    email: str
    score: int


def fuzzy_match_person(
    query: str, names: list[str], name_to_email: dict[str, str], score_cutoff: int = 75
) -> PersonMatch | None:
    ""





    try:
        from rapidfuzz import fuzz, process
    except ImportError:
        log.debug("rapidfuzz not available, skipping fuzzy entity match")
        return None

    if not names:
        return None


    best = process.extractOne(query, names, scorer=fuzz.token_sort_ratio, score_cutoff=score_cutoff)
    if best:
        name, score, _idx = best

        query_parts = query.strip().split()
        match_parts = name.strip().split()
        if len(query_parts) >= 2 and len(match_parts) >= 2:

            first_name_score = fuzz.ratio(query_parts[0].lower(), match_parts[0].lower())
            if first_name_score < 60:
                best = None
        if best:
            email = name_to_email.get(name.lower(), "")
            return PersonMatch(original=query, resolved_name=name, email=email, score=score)


    _STOP_WORDS = frozenset(
        {
            "cosa",
            "come",
            "quando",
            "dove",
            "perche",
            "stato",
            "fatto",
            "detto",
            "parlato",
            "visto",
            "email",
            "meeting",
            "deal",
            "della",
            "delle",
            "degli",
            "ieri",
            "oggi",
            "questa",
            "quello",
            "molto",
            "tutto",
            "prima",
            "dopo",
            "dimmi",
            "parlami",
            "raccontami",
        }
    )

    _known_lastnames = set()
    for n in names:
        parts = n.strip().split()
        if len(parts) >= 2:
            _known_lastnames.add(parts[-1].lower())

    words = query.split()
    for word in words:
        clean = word.strip("?!.,;:'\"")
        if len(clean) < 4 or clean.lower() in _STOP_WORDS:
            continue

        clean = clean[0].upper() + clean[1:] if len(clean) > 1 else clean.upper()

        candidates = [n for n in names if n.lower().startswith(clean.lower())]
        if candidates:

            query_lastname_words = []
            for w in words:
                wc = w.strip("?!.,;:'\"").lower()
                if len(wc) >= 4 and wc != clean.lower() and wc not in _STOP_WORDS:

                    if any(fuzz.ratio(wc, ln) >= 60 for ln in _known_lastnames):
                        query_lastname_words.append(wc)

            if query_lastname_words:

                filtered = [
                    c
                    for c in candidates
                    if len(c.split()) >= 2
                    and any(
                        fuzz.ratio(c.split()[-1].lower(), lw) >= 60 for lw in query_lastname_words
                    )
                ]
                if filtered:
                    email = name_to_email.get(filtered[0].lower(), "")
                    return PersonMatch(
                        original=clean, resolved_name=filtered[0], email=email, score=95
                    )

                continue

            if len(candidates) == 1:

                email = name_to_email.get(candidates[0].lower(), "")
                return PersonMatch(
                    original=clean, resolved_name=candidates[0], email=email, score=95
                )

            return None

        best = process.extractOne(clean, names, scorer=fuzz.token_sort_ratio, score_cutoff=80)
        if best:
            name, score, _idx = best
            email = name_to_email.get(name.lower(), "")
            return PersonMatch(original=clean, resolved_name=name, email=email, score=score)

    return None




INTENT_PATTERNS: dict[str, list[str]] = {

    "relational_search": [
        r"chi\s+(?:[eè]\s+)?(?:la|il)\s+(?:compagn[oa]|moglie|marito|partner)\s+di\s+",
        r"chi\s+mi\s+ha\s+presentato\s+",
        r"chi\s+conosce\s+",
        r"(?:come|attraverso)\s+(?:chi|quale)\s+(?:arriv[oa]|conosc[oa])\s+",
        r"(?:cosa|di cosa)\s+(?:ha\s+bisogno|serve\s+a|cerca)\s+",
        r"(?:relazioni?|legam[ei]|connession[ei])\s+(?:di|con|tra)\s+",
        r"(?:famiglia|parenti|fratell[oi])\s+di\s+",
        r"warm\s+intro\s+",
        r"chi\s+ha\s+(?:investito|finanziato)\s+",
    ],
    "person_lookup": [
        r"chi\s+[eè]\s+",
        r"profilo\s+di\s+",
        r"cosa\s+sappiamo\s+di\s+",
        r"contatto\s+",
    ],
    "temporal_search": [
        r"quando\s+",
        r"ultima?\s+volta",
        r"la\s+settimana\s+scorsa",
        r"ieri|oggi|domani",
        r"(?:gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|agosto|settembre|ottobre|novembre|dicembre)\s+\d{4}",
    ],
    "action_search": [
        r"cosa\s+(?:devo|dobbiamo)\s+fare",
        r"task|todo|follow\s*up",
        r"pending|scadut[oia]",
    ],
    "decision_search": [
        r"(?:cosa|che)\s+(?:ha|abbiamo|hanno)\s+decis[oa]",
        r"decisione?\s+su\s+",
        r"(?:ha|abbiamo)\s+detto\s+(?:che|di)",
    ],
}

ITALIAN_MONTHS: dict[str, int] = {
    "gennaio": 1,
    "febbraio": 2,
    "marzo": 3,
    "aprile": 4,
    "maggio": 5,
    "giugno": 6,
    "luglio": 7,
    "agosto": 8,
    "settembre": 9,
    "ottobre": 10,
    "novembre": 11,
    "dicembre": 12,
}

ITALIAN_DAYS: dict[str, int] = {
    "lunedì": 0,
    "lunedi": 0,
    "martedì": 1,
    "martedi": 1,
    "mercoledì": 2,
    "mercoledi": 2,
    "giovedì": 3,
    "giovedi": 3,
    "venerdì": 4,
    "venerdi": 4,
    "sabato": 5,
    "domenica": 6,
}

QUARTER_MONTHS: dict[str, tuple[int, int]] = {
    "q1": (1, 3),
    "q2": (4, 6),
    "q3": (7, 9),
    "q4": (10, 12),
}


def classify_intent(query: str) -> str:
    ""
    q = query.lower()
    for intent, patterns in INTENT_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, q):
                return intent
    return "general_search"


def _next_weekday(now: datetime, target_weekday: int) -> datetime:
    ""
    days_ahead = target_weekday - now.weekday()
    if days_ahead <= 0:
        days_ahead += 7
    return now + timedelta(days=days_ahead)


def extract_date_filter(query: str) -> dict | None:
    ""







    q = query.lower()
    now = datetime.now()


    relative_expressions: list[tuple[str, timedelta]] = [
        ("l'altro ieri", timedelta(days=2)),
        ("la settimana scorsa", timedelta(weeks=1)),
        ("il mese scorso", timedelta(days=30)),
        ("questa settimana", timedelta(days=now.weekday())),
        ("ieri", timedelta(days=1)),
        ("oggi", timedelta(days=0)),
        ("dopodomani", timedelta(days=-2)),
        ("domani", timedelta(days=-1)),
    ]
    for expr, delta in relative_expressions:
        if expr in q:
            if delta.days < 0:
                d = now + timedelta(days=-delta.days)
                return {
                    "after": now.strftime("%Y-%m-%d"),
                    "before": d.strftime("%Y-%m-%d"),
                    "label": expr,
                }
            d = now - delta
            return {"after": d.strftime("%Y-%m-%d"), "label": expr}


    m = re.search(r"ultim[io]\s+mese", q)
    if m:
        d = now - timedelta(days=30)
        return {"after": d.strftime("%Y-%m-%d"), "label": "ultimo mese"}

    m = re.search(r"ultim[ie]\s+(\d+)\s+(giorn[oi]|settiman[ae]|mes[ei])", q)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        if "giorn" in unit:
            d = now - timedelta(days=n)
        elif "settiman" in unit:
            d = now - timedelta(weeks=n)
        else:
            d = now - timedelta(days=n * 30)
        return {"after": d.strftime("%Y-%m-%d"), "label": m.group(0)}


    if "anno scorso" in q:
        return {
            "after": f"{now.year - 1}-01-01",
            "before": f"{now.year - 1}-12-31",
            "label": "anno scorso",
        }


    if "quest'anno" in q or "questo anno" in q:
        return {"after": f"{now.year}-01-01", "label": "quest'anno"}


    for day_name, day_num in ITALIAN_DAYS.items():
        m = re.search(rf"(?:scors[oa]\s+{day_name}|{day_name}\s+scors[oa])", q)
        if m:
            days_back = (now.weekday() - day_num) % 7
            if days_back == 0:
                days_back = 7
            target = now - timedelta(days=days_back)
            return {
                "after": target.strftime("%Y-%m-%d"),
                "before": target.strftime("%Y-%m-%d"),
                "label": m.group(0),
            }


    if "last week" in q:
        d = now - timedelta(weeks=1)
        return {"after": d.strftime("%Y-%m-%d"), "label": "last week"}
    if "last month" in q:
        d = now - timedelta(days=30)
        return {"after": d.strftime("%Y-%m-%d"), "label": "last month"}
    if "yesterday" in q:
        d = now - timedelta(days=1)
        return {"after": d.strftime("%Y-%m-%d"), "label": "yesterday"}
    if "last year" in q:
        return {
            "after": f"{now.year - 1}-01-01",
            "before": f"{now.year - 1}-12-31",
            "label": "last year",
        }


    m = re.search(r"da[l]?\s+(\d{4}-\d{2}-\d{2})\s+a[l]?\s+(\d{4}-\d{2}-\d{2})", q)
    if m:
        return {
            "after": m.group(1),
            "before": m.group(2),
            "label": f"da {m.group(1)} a {m.group(2)}",
        }


    for m1_name, m1_num in ITALIAN_MONTHS.items():
        for m2_name, m2_num in ITALIAN_MONTHS.items():
            pattern = rf"da[l]?\s+{m1_name}\s+a[l]?\s+{m2_name}"
            if re.search(pattern, q):
                last_day = monthrange(now.year, m2_num)[1]
                return {
                    "after": f"{now.year}-{m1_num:02d}-01",
                    "before": f"{now.year}-{m2_num:02d}-{last_day:02d}",
                    "label": f"da {m1_name} a {m2_name}",
                }


    m = re.search(r"tra\s+(\d+)\s+(giorn[oi]|settiman[ae]|mes[ei])", q)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        if "giorn" in unit:
            d = now + timedelta(days=n)
        elif "settiman" in unit:
            d = now + timedelta(weeks=n)
        else:
            d = now + timedelta(days=n * 30)
        return {
            "after": now.strftime("%Y-%m-%d"),
            "before": d.strftime("%Y-%m-%d"),
            "label": m.group(0),
        }


    m = re.search(r"prossim[oa]\s+(\w+)", q)
    if m:
        day_name = m.group(1).lower()
        if day_name in ITALIAN_DAYS:
            target = _next_weekday(now, ITALIAN_DAYS[day_name])
            return {
                "after": target.strftime("%Y-%m-%d"),
                "before": target.strftime("%Y-%m-%d"),
                "label": m.group(0),
            }
        if day_name == "settimana":
            monday = _next_weekday(now, 0)
            friday = monday + timedelta(days=4)
            return {
                "after": monday.strftime("%Y-%m-%d"),
                "before": friday.strftime("%Y-%m-%d"),
                "label": "prossima settimana",
            }
        if day_name == "mese":
            next_month = now.month + 1
            year = now.year
            if next_month > 12:
                next_month = 1
                year += 1
            last_day = monthrange(year, next_month)[1]
            return {
                "after": f"{year}-{next_month:02d}-01",
                "before": f"{year}-{next_month:02d}-{last_day:02d}",
                "label": "prossimo mese",
            }


    if "fine mese" in q:
        last_day = monthrange(now.year, now.month)[1]
        return {
            "after": now.strftime("%Y-%m-%d"),
            "before": f"{now.year}-{now.month:02d}-{last_day:02d}",
            "label": "fine mese",
        }

    if "fine settimana" in q:
        days_to_friday = 4 - now.weekday()
        if days_to_friday < 0:
            days_to_friday += 7
        friday = now + timedelta(days=days_to_friday)
        return {
            "after": now.strftime("%Y-%m-%d"),
            "before": friday.strftime("%Y-%m-%d"),
            "label": "fine settimana",
        }


    m = re.search(r"q([1-4])\s*(\d{4})", q)
    if m:
        quarter = int(m.group(1))
        year = int(m.group(2))
        start_month, end_month = QUARTER_MONTHS[f"q{quarter}"]
        last_day = monthrange(year, end_month)[1]
        return {
            "after": f"{year}-{start_month:02d}-01",
            "before": f"{year}-{end_month:02d}-{last_day:02d}",
            "label": f"Q{quarter} {year}",
        }


    for month_name, month_num in ITALIAN_MONTHS.items():
        m = re.search(rf"dopo\s+{month_name}", q)
        if m:
            year = now.year if month_num <= now.month else now.year
            last_day = monthrange(year, month_num)[1]
            return {
                "after": f"{year}-{month_num:02d}-{last_day:02d}",
                "label": f"dopo {month_name}",
            }

        m = re.search(rf"prima\s+di\s+{month_name}", q)
        if m:
            year = now.year if month_num >= now.month else now.year
            return {"before": f"{year}-{month_num:02d}-01", "label": f"prima di {month_name}"}


    for month_name, month_num in ITALIAN_MONTHS.items():
        match = re.search(rf"{month_name}\s+(\d{{4}})", q)
        if match:
            year = int(match.group(1))
            last_day = monthrange(year, month_num)[1]
            return {
                "after": f"{year}-{month_num:02d}-01",
                "before": f"{year}-{month_num:02d}-{last_day:02d}",
                "label": f"{month_name} {year}",
            }


    match = re.search(r"(\d{4}-\d{2}-\d{2})", q)
    if match:
        return {"after": match.group(1), "label": match.group(1)}

    return None





@dataclass
class QueryResult:
    ""

    original: str
    corrected: str
    intent: str = "general_search"
    date_filter: dict | None = None
    person: PersonMatch | None = None
    search_variants: list[str] = field(default_factory=list)
    source_hint: str | None = None


class QueryPipeline:
    ""





    def __init__(self):
        self._names: list[str] = []
        self._name_to_email: dict[str, str] = {}
        self._loaded = False

    def _ensure_loaded(self):
        if not self._loaded:
            self._names, self._name_to_email = _load_contacts_names()
            self._loaded = True
            log.debug(f"QueryPipeline: loaded {len(self._names)} contact names")

    def process(self, raw_query: str, use_llm: bool = False) -> QueryResult:
        ""








        self._ensure_loaded()


        query = normalize_query(raw_query)


        person = fuzzy_match_person(query, self._names, self._name_to_email)


        intent = classify_intent(query)
        date_filter = extract_date_filter(query)


        variants = expand_acronyms(query)


        if person and person.resolved_name.lower() not in query.lower():
            variant_with_name = re.sub(
                re.escape(person.original),
                person.resolved_name,
                query,
                count=1,
                flags=re.IGNORECASE,
            )
            if variant_with_name not in variants:
                variants.append(variant_with_name)


        if use_llm:
            llm_variants = _llm_reformulate(query)
            for v in llm_variants:
                if v not in variants:
                    variants.append(v)

        return QueryResult(
            original=raw_query,
            corrected=query,
            intent=intent,
            date_filter=date_filter,
            person=person,
            search_variants=variants,
        )




_QUERY_UNDERSTANDING_PROMPT = """You are the query preprocessor for SBK, the user's personal information system.

The user wrote a query that may contain:
- Typos (e.g. "Acmee" = "Acme", "fundrazing" = "fundraising")
- Abbreviations (e.g. "CRM" = "Attio", "M&A" = mergers and acquisitions)
- Partial names (e.g. "Sam" = "Sam Taylor")
- Relative dates in Italian (e.g. "ieri", "la settimana scorsa")
- Italian/English mix

Generate 2-3 optimized search variants. For each variant:
1. Fix typos
2. Expand abbreviations and partial names
3. Keep both the Italian and English version of the key terms

Original query: {query}
Today's date: {today}

Respond ONLY with JSON:
{{"search_variants": ["variant1", "variant2"]}}"""


def _llm_reformulate(query: str) -> list[str]:
    ""
    try:
        import json
        import sys

        tools_dir = str(Path(__file__).resolve().parent.parent)
        this_dir = str(Path(__file__).resolve().parent)
        if tools_dir not in sys.path:
            sys.path.insert(0, tools_dir)
        if this_dir not in sys.path:
            sys.path.insert(0, this_dir)
        from xs_l3_common import call_claude

        prompt = _QUERY_UNDERSTANDING_PROMPT.format(
            query=query,
            today=datetime.now().strftime("%Y-%m-%d"),
        )
        response = call_claude(
            prompt=prompt,
            system="You are a query preprocessor. Respond only with valid JSON.",
            model="claude-haiku-4-5-20251001",
            max_tokens=256,
        )
        data = json.loads(response)
        return data.get("search_variants", [])
    except Exception as e:
        log.debug(f"LLM reformulation failed: {e}")
        return []
