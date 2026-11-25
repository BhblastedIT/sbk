#!/usr/bin/env python3
""













import re




import sys as _sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

_sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sbk_config import ENTITIES_FILE

ENTITIES_PATH = ENTITIES_FILE


IT_STOP_WORDS = {
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
    "col",
    "coi",
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
    "o",
    "ma",
    "se",
    "che",
    "chi",
    "cui",
    "non",
    "ne",
    "ci",
    "vi",
    "si",
    "mi",
    "ti",
    "me",
    "te",
    "lui",
    "lei",
    "noi",
    "voi",
    "loro",
    "questo",
    "quello",
    "questa",
    "quella",
    "questi",
    "quelli",
    "queste",
    "quelle",
    "come",
    "dove",
    "quando",
    "perche",
    "perché",
    "cosa",
    "quale",
    "quali",
    "anche",
    "ancora",
    "sempre",
    "mai",
    "molto",
    "poco",
    "troppo",
    "tutto",
    "tutti",
    "tutta",
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
    "essere",
    "avere",
    "fare",
    "dire",
    "andare",
    "venire",
    "dare",
    "stare",
    "potere",
    "dovere",
    "volere",
    "sapere",
    "sono",
    "sei",
    "è",
    "siamo",
    "siete",
    "ho",
    "hai",
    "ha",
    "abbiamo",
    "avete",
    "hanno",
    "era",
    "ero",
    "eri",
    "eravamo",
    "eravate",
    "erano",
    "fatto",
    "fatta",
    "fatti",
    "fatte",
    "detto",
    "detta",
    "poi",
    "ora",
    "adesso",
    "gia",
    "già",
    "dopo",
    "prima",
    "qui",
    "qua",
    "li",
    "là",
    "sopra",
    "sotto",
    "dentro",
    "fuori",
    "bene",
    "male",
    "meglio",
    "peggio",
    "solo",
    "sola",
    "soli",
    "sole",
    "cosi",
    "così",
    "tanto",
    "quanto",
    "no",
    "sì",
    "ok",
    "va",
    "eh",
    "ah",
    "oh",
    "ecco",
    "allora",
    "quindi",
    "pero",
    "però",
    "oppure",
    "dunque",
    "cioe",
    "cioè",
    "tipo",
    "roba",
    "cose",
    "gente",
}


EN_STOP_WORDS = {
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
    "shall",
    "should",
    "may",
    "might",
    "must",
    "can",
    "could",
    "i",
    "me",
    "my",
    "mine",
    "we",
    "us",
    "our",
    "ours",
    "you",
    "your",
    "yours",
    "he",
    "him",
    "his",
    "she",
    "her",
    "hers",
    "it",
    "its",
    "they",
    "them",
    "their",
    "theirs",
    "this",
    "that",
    "these",
    "those",
    "who",
    "whom",
    "whose",
    "which",
    "what",
    "where",
    "when",
    "why",
    "how",
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
    "not",
    "only",
    "own",
    "same",
    "so",
    "than",
    "too",
    "very",
    "and",
    "but",
    "or",
    "nor",
    "for",
    "yet",
    "as",
    "at",
    "by",
    "from",
    "in",
    "into",
    "of",
    "on",
    "to",
    "up",
    "with",
    "about",
    "above",
    "after",
    "before",
    "between",
    "during",
    "through",
    "under",
    "until",
    "just",
    "also",
    "then",
    "now",
    "here",
    "there",
    "if",
    "because",
    "while",
    "although",
    "though",
    "since",
    "unless",
    "yes",
    "ok",
    "okay",
    "well",
    "right",
    "like",
    "really",
    "actually",
    "basically",
    "thing",
    "things",
    "stuff",
    "way",
    "something",
    "anything",
    "nothing",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
}

ALL_STOP_WORDS = IT_STOP_WORDS | EN_STOP_WORDS


COMMON_WORDS_MISCLASS = {

    "domani",
    "oggi",
    "ieri",
    "mattina",
    "sera",
    "pomeriggio",
    "notte",
    "settimana",
    "mese",
    "anno",
    "giorno",
    "ora",
    "lunedi",
    "lunedì",
    "martedi",
    "martedì",
    "mercoledi",
    "mercoledì",
    "giovedi",
    "giovedì",
    "venerdi",
    "venerdì",
    "sabato",
    "domenica",
    "gennaio",
    "febbraio",
    "marzo",
    "aprile",
    "maggio",
    "giugno",
    "luglio",
    "agosto",
    "settembre",
    "ottobre",
    "novembre",
    "dicembre",
    "lavoro",
    "progetto",
    "piano",
    "budget",
    "team",
    "meeting",
    "riunione",
    "chiamata",
    "mail",
    "messaggio",
    "grazie",
    "prego",
    "scusa",
    "ciao",
    "salve",
    "buongiorno",
    "buonasera",
    "problema",
    "soluzione",
    "proposta",
    "idea",
    "punto",
    "parte",
    "cliente",
    "clienti",
    "azienda",
    "società",
    "ditta",
    "contratto",
    "accordo",
    "fattura",
    "pagamento",
    "conto",
    "numero",
    "percentuale",
    "quota",
    "prezzo",
    "costo",
    "primo",
    "secondo",
    "terzo",
    "quarto",
    "quinto",
    "grande",
    "piccolo",
    "nuovo",
    "vecchio",
    "ultimo",
    "prossimo",
    "capito",
    "esatto",
    "perfetto",
    "chiaro",
    "vero",
    "giusto",
    "ragazzi",
    "gente",
    "persone",
    "persona",
    "uomo",
    "donna",
    "casa",
    "ufficio",
    "sede",
    "negozio",
    "centro",
    "mercato",
    "settore",
    "industria",
    "mondo",
    "paese",
    "prodotto",
    "servizio",
    "piattaforma",
    "sistema",
    "processo",
    "risultato",
    "obiettivo",
    "strategia",
    "modello",
    "struttura",
    "crescita",
    "sviluppo",
    "lancio",
    "investimento",
    "vendita",
    "mila",
    "milioni",
    "miliardi",
    "euro",
    "dollari",
    "sterline",

    "today",
    "tomorrow",
    "yesterday",
    "morning",
    "evening",
    "afternoon",
    "night",
    "week",
    "month",
    "year",
    "day",
    "hour",
    "time",
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
    "work",
    "project",
    "plan",
    "call",
    "email",
    "message",
    "thanks",
    "please",
    "sorry",
    "hello",
    "hi",
    "bye",
    "problem",
    "solution",
    "proposal",
    "point",
    "part",
    "client",
    "clients",
    "company",
    "business",
    "firm",
    "contract",
    "agreement",
    "invoice",
    "payment",
    "account",
    "number",
    "percentage",
    "share",
    "price",
    "cost",
    "first",
    "second",
    "third",
    "fourth",
    "fifth",
    "big",
    "small",
    "new",
    "old",
    "last",
    "next",
    "people",
    "person",
    "man",
    "woman",
    "home",
    "office",
    "store",
    "center",
    "market",
    "sector",
    "industry",
    "world",
    "country",
    "product",
    "service",
    "platform",
    "system",
    "process",
    "result",
    "goal",
    "strategy",
    "model",
    "structure",
    "growth",
    "development",
    "launch",
    "investment",
    "sale",
    "million",
    "billions",
    "thousands",
    "dollars",
    "euros",
    "pounds",
    "percent",
    "thousand",

    "speaker",
    "speaker 1",
    "speaker 2",
    "speaker 3",
    "speaker 4",
    "speaker 5",
    "speaker 6",
    "speaker 7",
    "speaker 8",
    "question",
    "answer",
    "topic",
    "agenda",
    "summary",
    "chapter",
    "section",
    "slide",
    "start",
    "end",
    "beginning",
    "mr",
    "mrs",
    "ms",
    "dr",
    "prof",
    "none",
    "null",
    "n/a",
    "na",
    "tbd",
}


DATE_TIME_PATTERNS = [
    r"^\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4}$",
    r"^\d{4}[/\-.]\d{1,2}[/\-.]\d{1,2}$",
    r"^\d{1,2}:\d{2}(:\d{2})?$",
    r"^\d{1,2}\s*(am|pm)$",
    r"^\d{1,2}:\d{2}\s*(am|pm)$",
    r"^(q[1-4])\s*\d{4}$",
    r"^(h[12])\s*\d{4}$",
    r"^fy\s*\d{4}$",
]


MEASUREMENT_PATTERNS = [
    r"^\d+[\.,]?\d*\s*%$",
    r"^\d+[\.,]?\d*\s*(kg|g|mg|lb|oz)$",
    r"^\d+[\.,]?\d*\s*(km|m|cm|mm|mi|ft|in)$",
    r"^\d+[\.,]?\d*\s*(l|ml|gal)$",
    r"^\d+[\.,]?\d*\s*(k|m|b|mln|mld|bn)$",
    r"^\d+[\.,]?\d*\s*(euro|eur|usd|\$|€|£)$",
    r"^(euro|eur|usd|\$|€|£)\s*\d+[\.,]?\d*$",
    r"^\d+[\.,]?\d*\s*(mila|milioni|miliardi)$",
    r"^\d+[\.,]?\d*\s*(million|billion|thousand)s?$",
]







def main():
    print("=" * 100)
    print("SBK ENTITY AUDIT — Full Misclassification Analysis")
    print("=" * 100)
    print()


    df = pd.read_parquet(ENTITIES_PATH)
    print(f"File: {ENTITIES_PATH}")
    print(f"Total rows: {len(df):,}")
    print(f"Columns: {df.columns.tolist()}")
    print()


    text_col = "entity_text_normalized"
    if text_col not in df.columns or df[text_col].isna().all():
        text_col = "entity_text"


    df["_text_lower"] = df[text_col].fillna("").str.strip().str.lower()
    df["_text_orig"] = df["entity_text"].fillna("").str.strip()




    print("=" * 100)
    print("1. ENTITY TYPE DISTRIBUTION")
    print("=" * 100)
    type_dist = df["entity_type"].value_counts()
    for etype, count in type_dist.items():
        pct = count / len(df) * 100
        print(f"  {etype:<20s} {count:>8,}  ({pct:.1f}%)")
    print(f"  {'TOTAL':<20s} {len(df):>8,}")
    print()




    print("=" * 100)
    print("2. MULTI-TYPE ENTITIES (same text classified as 2+ different types)")
    print("=" * 100)

    entity_types = df.groupby("_text_lower")["entity_type"].apply(set).reset_index()
    entity_types.columns = ["text", "types"]
    entity_types["n_types"] = entity_types["types"].apply(len)
    multi_type = entity_types[entity_types["n_types"] >= 2].sort_values("n_types", ascending=False)


    multi_type_details = []
    for _, row in multi_type.iterrows():
        text = row["text"]
        mask = df["_text_lower"] == text
        type_counts = df[mask]["entity_type"].value_counts().to_dict()
        total = df[mask].shape[0]
        orig = df[mask]["_text_orig"].mode().iloc[0] if not df[mask]["_text_orig"].empty else text
        multi_type_details.append(
            {
                "text": text,
                "original": orig,
                "n_types": row["n_types"],
                "type_counts": type_counts,
                "total_occurrences": total,
            }
        )

    multi_type_details.sort(key=lambda x: (-x["n_types"], -x["total_occurrences"]))

    print(f"\nTotal multi-type entities: {len(multi_type_details):,}")
    print()


    by_ntypes = defaultdict(list)
    for item in multi_type_details:
        by_ntypes[item["n_types"]].append(item)

    for n_types in sorted(by_ntypes.keys(), reverse=True):
        items = by_ntypes[n_types]
        print(f"--- {n_types} types ({len(items)} entities) ---")
        for item in items:
            tc = ", ".join(
                f"{t}={c}" for t, c in sorted(item["type_counts"].items(), key=lambda x: -x[1])
            )
            print(f"  '{item['original']}'  (total={item['total_occurrences']})  [{tc}]")
        print()




    print("=" * 100)
    print("3. SINGLE-CHARACTER ENTITIES")
    print("=" * 100)

    single_char = df[df["_text_lower"].str.len() == 1]
    if len(single_char) > 0:
        sc_grouped = (
            single_char.groupby(["_text_lower", "entity_type"]).size().reset_index(name="count")
        )
        sc_grouped = sc_grouped.sort_values("count", ascending=False)
        print(f"\nTotal single-character entity rows: {len(single_char):,}")
        print(f"Unique single characters: {single_char['_text_lower'].nunique()}")
        print()
        for _, row in sc_grouped.iterrows():
            print(f"  '{row['_text_lower']}'  type={row['entity_type']}  count={row['count']}")
    else:
        print("\n  None found.")
    print()




    print("=" * 100)
    print("4. NUMERIC-ONLY ENTITIES")
    print("=" * 100)

    numeric_mask = df["_text_lower"].str.match(r"^[\d\s,.\-/]+$", na=False)
    numeric = df[numeric_mask]

    if len(numeric) > 0:
        num_grouped = (
            numeric.groupby(["_text_lower", "entity_type"]).size().reset_index(name="count")
        )
        num_grouped = num_grouped.sort_values("count", ascending=False)
        print(f"\nTotal numeric-only entity rows: {len(numeric):,}")
        print(f"Unique numeric entities: {numeric['_text_lower'].nunique()}")
        print()
        for _, row in num_grouped.iterrows():
            print(f"  '{row['_text_lower']}'  type={row['entity_type']}  count={row['count']}")
    else:
        print("\n  None found.")
    print()




    print("=" * 100)
    print("5. DATES, TIMES, MEASUREMENTS MISCLASSIFIED AS OTHER TYPES")
    print("=" * 100)

    all_patterns = DATE_TIME_PATTERNS + MEASUREMENT_PATTERNS
    compiled = [re.compile(p, re.IGNORECASE) for p in all_patterns]

    def matches_pattern(text):
        return any(p.search(text) for p in compiled)

    pattern_mask = df["_text_lower"].apply(matches_pattern)

    wrong_type_mask = pattern_mask & ~df["entity_type"].isin(["date", "money"])
    wrong_pattern = df[wrong_type_mask]

    if len(wrong_pattern) > 0:
        wp_grouped = (
            wrong_pattern.groupby(["_text_orig", "entity_type"]).size().reset_index(name="count")
        )
        wp_grouped = wp_grouped.sort_values("count", ascending=False)
        print(
            f"\nDate/time/measurement patterns classified as NON-date/money: {len(wrong_pattern):,}"
        )
        print()
        for _, row in wp_grouped.iterrows():
            print(f"  '{row['_text_orig']}'  type={row['entity_type']}  count={row['count']}")
    else:
        print("\n  None found.")


    all_pattern_matches = df[pattern_mask]
    if len(all_pattern_matches) > 0:
        print(
            f"\nAll date/time/measurement pattern matches (including correct type): {len(all_pattern_matches):,}"
        )
        ap_grouped = all_pattern_matches.groupby(["entity_type"]).size().reset_index(name="count")
        for _, row in ap_grouped.iterrows():
            print(f"  {row['entity_type']}: {row['count']}")
    print()




    print("=" * 100)
    print("6. STOP WORDS (IT/EN) APPEARING AS ENTITIES")
    print("=" * 100)

    stop_mask = df["_text_lower"].isin(ALL_STOP_WORDS)
    stop_entities = df[stop_mask]

    if len(stop_entities) > 0:
        se_grouped = (
            stop_entities.groupby(["_text_lower", "entity_type"]).size().reset_index(name="count")
        )
        se_grouped = se_grouped.sort_values("count", ascending=False)
        print(f"\nTotal stop word entity rows: {len(stop_entities):,}")
        print(f"Unique stop words found as entities: {stop_entities['_text_lower'].nunique()}")
        print()
        for _, row in se_grouped.iterrows():
            print(f"  '{row['_text_lower']}'  type={row['entity_type']}  count={row['count']}")
    else:
        print("\n  None found.")
    print()




    print("=" * 100)
    print("7. COMMON WORDS MISCLASSIFIED AS ENTITIES")
    print("=" * 100)

    common_mask = df["_text_lower"].isin(COMMON_WORDS_MISCLASS)
    common_entities = df[common_mask]

    if len(common_entities) > 0:
        ce_grouped = (
            common_entities.groupby(["_text_lower", "entity_type"]).size().reset_index(name="count")
        )
        ce_grouped = ce_grouped.sort_values("count", ascending=False)
        print(f"\nTotal common-word entity rows: {len(common_entities):,}")
        print(f"Unique common words found as entities: {common_entities['_text_lower'].nunique()}")
        print()
        for _, row in ce_grouped.iterrows():
            print(f"  '{row['_text_lower']}'  type={row['entity_type']}  count={row['count']}")
    else:
        print("\n  None found.")
    print()




    print("=" * 100)
    print("8. HIGH-FREQUENCY ENTITIES (>50 occurrences) — likely noise")
    print("=" * 100)

    freq = (
        df.groupby("_text_lower")
        .agg(
            count=("_text_lower", "size"),
            types=("entity_type", lambda x: sorted(set(x))),
            original=("_text_orig", lambda x: x.mode().iloc[0] if len(x) > 0 else ""),
        )
        .reset_index()
    )
    high_freq = freq[freq["count"] > 50].sort_values("count", ascending=False)

    print(f"\nEntities with >50 occurrences: {len(high_freq):,}")
    print()
    print(f"  {'Entity':<50s} {'Count':>7s}  Types")
    print(f"  {'-' * 50} {'-' * 7}  {'-' * 40}")
    for _, row in high_freq.iterrows():
        types_str = ", ".join(row["types"])
        name = row["original"] if len(row["original"]) <= 48 else row["original"][:45] + "..."
        print(f"  {name:<50s} {row['count']:>7,}  [{types_str}]")
    print()




    print("=" * 100)
    print("9. TYPE CONFUSION MATRIX")
    print("=" * 100)
    print("  How often the same entity text is classified as type A AND type B")
    print()

    all_types = sorted(df["entity_type"].unique())
    confusion = defaultdict(int)

    for _, row in multi_type.iterrows():
        text = row["text"]
        mask = df["_text_lower"] == text
        types_for_text = df[mask]["entity_type"].value_counts()
        type_list = list(types_for_text.index)
        for i, t1 in enumerate(type_list):
            for t2 in type_list[i + 1 :]:
                pair = tuple(sorted([t1, t2]))
                confusion[pair] += 1

    print(f"  {'Type A':<20s} {'Type B':<20s} {'Entities':>10s}")
    print(f"  {'-' * 20} {'-' * 20} {'-' * 10}")
    for pair, count in sorted(confusion.items(), key=lambda x: -x[1]):
        print(f"  {pair[0]:<20s} {pair[1]:<20s} {count:>10,}")
    print()




    print("=" * 100)
    print("10. LOW-CONFIDENCE ENTITIES (confidence < 0.5)")
    print("=" * 100)

    if "confidence" in df.columns:
        low_conf = df[df["confidence"] < 0.5]
        print(
            f"\nTotal low-confidence rows: {len(low_conf):,} ({len(low_conf) / len(df) * 100:.1f}%)"
        )
        print()
        if len(low_conf) > 0:
            lc_by_type = low_conf["entity_type"].value_counts()
            print("  By type:")
            for t, c in lc_by_type.items():
                total_t = (df["entity_type"] == t).sum()
                print(f"    {t:<20s} {c:>7,} / {total_t:>7,} ({c / total_t * 100:.1f}%)")
            print()


            lc_freq = (
                low_conf.groupby("_text_lower")
                .agg(
                    count=("_text_lower", "size"),
                    avg_conf=("confidence", "mean"),
                    types=("entity_type", lambda x: sorted(set(x))),
                    original=("_text_orig", lambda x: x.mode().iloc[0] if len(x) > 0 else ""),
                )
                .sort_values("count", ascending=False)
                .head(50)
            )
            print("  Top 50 low-confidence entities:")
            print(f"  {'Entity':<45s} {'Count':>6s}  {'Avg Conf':>8s}  Types")
            print(f"  {'-' * 45} {'-' * 6}  {'-' * 8}  {'-' * 30}")
            for _, row in lc_freq.iterrows():
                name = row["original"][:43] if len(row["original"]) > 43 else row["original"]
                types_str = ", ".join(row["types"])
                print(f"  {name:<45s} {row['count']:>6,}  {row['avg_conf']:>8.3f}  [{types_str}]")
    else:
        print("\n  No confidence column found.")
    print()




    print("=" * 100)
    print("11. TOP ANOMALIES — Combined risk scoring")
    print("=" * 100)
    print("  Entities that are anomalous on MULTIPLE dimensions")
    print()


    anomalies = {}
    for text in df["_text_lower"].unique():
        score = 0
        reasons = []


        if text in multi_type["text"].values:
            n = multi_type[multi_type["text"] == text]["n_types"].values[0]
            score += n * 2
            reasons.append(f"multi-type({n})")


        if text in ALL_STOP_WORDS:
            score += 5
            reasons.append("stop_word")


        if text in COMMON_WORDS_MISCLASS:
            score += 4
            reasons.append("common_word")


        if len(text) == 1:
            score += 6
            reasons.append("single_char")


        if re.match(r"^[\d\s,.\-/]+$", text):
            score += 5
            reasons.append("numeric_only")


        if matches_pattern(text):
            mask = df["_text_lower"] == text
            if not df[mask]["entity_type"].isin(["date", "money"]).all():
                score += 3
                reasons.append("date_time_measurement_wrong_type")


        if len(text) == 2:
            score += 2
            reasons.append("very_short")


        count = (df["_text_lower"] == text).sum()
        if count > 100:
            score += 3
            reasons.append(f"high_freq({count})")
        elif count > 50:
            score += 1
            reasons.append(f"freq({count})")


        mask = df["_text_lower"] == text
        avg_conf = df[mask]["confidence"].mean() if "confidence" in df.columns else 1.0
        if avg_conf < 0.5:
            score += 3
            reasons.append(f"low_conf({avg_conf:.2f})")
        elif avg_conf < 0.6:
            score += 1
            reasons.append(f"med_conf({avg_conf:.2f})")

        if score > 0:
            orig_mask = df["_text_lower"] == text
            orig = df[orig_mask]["_text_orig"].mode().iloc[0] if orig_mask.sum() > 0 else text
            types = sorted(df[orig_mask]["entity_type"].unique())
            anomalies[text] = {
                "original": orig,
                "score": score,
                "reasons": reasons,
                "count": count,
                "types": types,
                "avg_confidence": avg_conf,
            }


    top_anomalies = sorted(anomalies.values(), key=lambda x: (-x["score"], -x["count"]))

    print(f"Total anomalous entities: {len(top_anomalies):,}")
    print()
    print(f"  {'Score':>5s}  {'Entity':<45s} {'Count':>6s}  {'Conf':>5s}  {'Types':<30s} Reasons")
    print(f"  {'-' * 5}  {'-' * 45} {'-' * 6}  {'-' * 5}  {'-' * 30} {'-' * 40}")
    for item in top_anomalies[:150]:
        name = item["original"][:43] if len(item["original"]) > 43 else item["original"]
        types_str = ", ".join(item["types"])[:28]
        reasons_str = ", ".join(item["reasons"])
        print(
            f"  {item['score']:>5d}  {name:<45s} {item['count']:>6,}  {item['avg_confidence']:>5.2f}  {types_str:<30s} {reasons_str}"
        )




    print()
    print("=" * 100)
    print("12. SUMMARY")
    print("=" * 100)
    print(f"  Total entity rows:                   {len(df):>10,}")
    print(f"  Unique entity texts:                 {df['_text_lower'].nunique():>10,}")
    print(f"  Entity types:                        {df['entity_type'].nunique():>10}")
    print(f"  Multi-type entities:                 {len(multi_type_details):>10,}")
    print(f"  Single-character entities:            {len(single_char):>10,}")
    print(f"  Numeric-only entities:               {len(numeric):>10,}")
    print(f"  Stop words as entities:              {len(stop_entities):>10,}")
    print(f"  Common words as entities:            {len(common_entities):>10,}")
    print(f"  High-frequency (>50) entities:       {len(high_freq):>10,}")
    if "confidence" in df.columns:
        print(f"  Low-confidence (<0.5) entities:      {len(low_conf):>10,}")
    print(f"  Total anomalous entities:            {len(top_anomalies):>10,}")
    print(
        f"  Top anomaly score:                   {top_anomalies[0]['score'] if top_anomalies else 0:>10d}"
    )
    print()


    noise_texts = set()
    for text in df["_text_lower"].unique():
        if (
            text in ALL_STOP_WORDS
            or text in COMMON_WORDS_MISCLASS
            or len(text) == 1
            or re.match(r"^[\d\s,.\-/]+$", text)
        ):
            noise_texts.add(text)

    noise_rows = df[df["_text_lower"].isin(noise_texts)]
    print(
        f"  Estimated noise rows (stop+common+single+numeric): {len(noise_rows):>10,} ({len(noise_rows) / len(df) * 100:.1f}%)"
    )
    print(
        f"  Estimated clean rows:                              {len(df) - len(noise_rows):>10,} ({(len(df) - len(noise_rows)) / len(df) * 100:.1f}%)"
    )
    print()
    print("=" * 100)
    print("AUDIT COMPLETE")
    print("=" * 100)


if __name__ == "__main__":
    main()
