#!/usr/bin/env python3
""










import argparse
import json
import logging
import os
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv



_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

load_dotenv(_TOOLS_DIR.parent / ".env", override=True)

from sbk_config import (  # noqa: E402
    CLINICAL_INCOMING_DIR,
    CLINICAL_PROCESSED_DIR,
    OWNER_SUBJECT,
    mark_last_run,
    safe_write_parquet,
)

log = logging.getLogger("cl-l1")



MARKER_ALIASES = {
    "glicemia": "glucose",
    "glycemia": "glucose",
    "blood sugar": "glucose",
    "glicemia a digiuno": "glucose",
    "colesterolo totale": "cholesterol_total",
    "colesterolo": "cholesterol_total",
    "hdl": "cholesterol_hdl",
    "colesterolo hdl": "cholesterol_hdl",
    "ldl": "cholesterol_ldl",
    "colesterolo ldl": "cholesterol_ldl",
    "trigliceridi": "triglycerides",
    "emoglobina": "hemoglobin",
    "hb": "hemoglobin",
    "emoglobina glicata": "hemoglobin_a1c",
    "hba1c": "hemoglobin_a1c",
    "a1c": "hemoglobin_a1c",
    "ematocrito": "hematocrit",
    "ht": "hematocrit",
    "leucociti": "wbc",
    "globuli bianchi": "wbc",
    "white blood cells": "wbc",
    "eritrociti": "rbc",
    "globuli rossi": "rbc",
    "red blood cells": "rbc",
    "piastrine": "platelets",
    "ferritina": "ferritin",
    "ferro": "iron",
    "sideremia": "iron",
    "vitamina d": "vitamin_d",
    "25-oh-d": "vitamin_d",
    "calcifediolo": "vitamin_d",
    "25(oh)d": "vitamin_d",
    "vit d": "vitamin_d",
    "vitamina d3": "vitamin_d",
    "vitamina b12": "vitamin_b12",
    "cobalamina": "vitamin_b12",
    "acido folico": "folate",
    "folati": "folate",
    "tireotropina": "tsh",
    "t3 libero": "ft3",
    "free t3": "ft3",
    "t4 libero": "ft4",
    "free t4": "ft4",
    "creatinina": "creatinine",
    "creatinina sierica": "creatinine",
    "azotemia": "urea",
    "bun": "urea",
    "acido urico": "uric_acid",
    "gpt": "alt",
    "alanina aminotransferasi": "alt",
    "got": "ast",
    "aspartato aminotransferasi": "ast",
    "gamma gt": "ggt",
    "bilirubina totale": "bilirubin_total",
    "bilirubina diretta": "bilirubin_direct",
    "bilirubina coniugata": "bilirubin_direct",
    "bilirubina indiretta": "bilirubin_indirect",
    "pcr": "crp",
    "proteina c reattiva": "crp",
    "proteina c-reattiva": "crp",
    "hs-crp": "crp_high_sensitivity",
    "pcr ad alta sensibilita'": "crp_high_sensitivity",
    "fosfatasi alcalina": "alp",
    "alp": "alp",
    "ldh": "ldh",
    "lattato deidrogenasi": "ldh",
    "albumina": "albumin",
    "proteine totali": "total_protein",
    "transferrina": "transferrin",
    "insulina": "insulin",
    "omocisteina": "homocysteine",
    "fosforo": "phosphorus",
    "fosforemia": "phosphorus",
    "ves": "esr",
    "velocita' di eritrosedimentazione": "esr",
    "egfr": "egfr",
    "gfr": "egfr",
    "filtrato glomerulare": "egfr",
    "testosterone": "testosterone_total",
    "cortisolo": "cortisol",
    "magnesio": "magnesium",
    "calcio": "calcium",
    "calcemia": "calcium",
    "potassio": "potassium",
    "kaliemia": "potassium",
    "sodio": "sodium",
    "natremia": "sodium",
    "zinco": "zinc",
    "rame": "copper",

    "shbg": "shbg",
    "sex hormone binding globulin": "shbg",
    "igf-1": "igf1",
    "igf1": "igf1",
    "somatomedina c": "igf1",
    "cortisolo mattutino": "cortisol_am",
    "testosterone totale": "testosterone_total",
    "cpk": "cpk",
    "ck": "cpk",
    "creatina chinasi": "cpk",
    "creatine kinase": "cpk",
    "homa-ir": "homa_ir",
    "homa ir": "homa_ir",
    "lp(a)": "lipoprotein_a",
    "lipoproteina(a)": "lipoprotein_a",
    "lipoproteina a": "lipoprotein_a",
    "apolipoproteina a1": "apolipoprotein_a1",
    "apolipoproteina b": "apolipoprotein_b",
    "apo a1": "apolipoprotein_a1",
    "apo b": "apolipoprotein_b",
    "psa totale": "psa_total",
    "psa libero": "psa_free",
    "amilasi": "amylase",
    "lipasi": "lipase",
    "prolattina": "prolactin",
}


VALID_UNITS = {
    "mg/dL",
    "g/dL",
    "ng/mL",
    "pg/mL",
    "ng/dL",
    "µg/dL",
    "µg/L",
    "mIU/L",
    "IU/L",
    "U/L",
    "mU/L",
    "mmol/L",
    "µmol/L",
    "nmol/L",
    "mmHg",
    "%",
    "count/min",
    "bpm",
    "10^3/µL",
    "10^6/µL",
    "K/µL",
    "M/µL",
    "mg/L",
    "mEq/L",
    "fL",
    "pg",
    "sec",
}


UNIT_CANONICAL = {
    "mg/dl": "mg/dL",
    "g/dl": "g/dL",
    "ng/ml": "ng/mL",
    "pg/ml": "pg/mL",
    "ng/dl": "ng/dL",
    "µg/dl": "µg/dL",
    "ug/dl": "µg/dL",
    "µg/l": "µg/L",
    "ug/l": "µg/L",
    "miu/l": "mIU/L",
    "uiu/ml": "mIU/L",
    "iu/l": "IU/L",
    "u/l": "U/L",
    "mu/l": "mU/L",
    "mmol/l": "mmol/L",
    "µmol/l": "µmol/L",
    "umol/l": "µmol/L",
    "nmol/l": "nmol/L",
    "mg/l": "mg/L",
    "meq/l": "mEq/L",
    "uu/ml": "mU/L",
    "g/l": "g/L",
    "k/ul": "K/µL",
    "m/ul": "M/µL",
    "10^3/ul": "10^3/µL",
    "10^6/ul": "10^6/µL",
}


def normalize_unit(raw_unit: str) -> str:
    ""
    if not raw_unit:
        return raw_unit
    lookup = raw_unit.lower().strip()
    return UNIT_CANONICAL.get(lookup, raw_unit)


def parse_italian_float(value_str: str) -> float:
    ""
    if not isinstance(value_str, str):
        return float(value_str)
    s = value_str.strip()

    if re.match(r"^\d{1,3}(\.\d{3})+,\d+$", s):
        s = s.replace(".", "").replace(",", ".")
        return float(s)

    if "," in s and "." not in s:
        s = s.replace(",", ".")
        return float(s)
    return float(s)


BLOOD_TEST_EXTRACTION_PROMPT = """\
You are a medical assistant specialized in blood tests.
Analyze the lab report and extract ALL the values present.

For each value return a JSON object with:
- "marker": parameter name (in the original language of the report, as written)
- "value": numeric value (use the dot as decimal separator, e.g. 1.05 not 1,05)
- "unit": unit of measure
- "ref_min": lower reference limit (null if absent or if the range is like "<200")
- "ref_max": upper reference limit (null if absent)

Rules:
- Convert a decimal comma to a dot: 1,05 -> 1.05
- Range like "<200" -> ref_min=null, ref_max=200
- Range like ">40" -> ref_min=40, ref_max=null
- Ignore H/L/* flags and textual comments
- Do NOT include parameters without a numeric value

Return ONLY a JSON array of objects. No explanation, no markdown.
"""


RETRY_DELAYS = [2, 5, 15]


def call_llm_with_retry(fn, *args, max_retries: int = 3, **kwargs) -> str:
    ""
    for attempt in range(max_retries):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            delay = RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)]
            log.warning(
                "LLM call failed (attempt %d/%d): %s. Retrying in %ds...",
                attempt + 1,
                max_retries,
                e,
                delay,
            )
            time.sleep(delay)
    return ""



PLAUSIBILITY = {
    "glucose": (20, 600),
    "cholesterol_total": (50, 500),
    "cholesterol_hdl": (10, 150),
    "cholesterol_ldl": (10, 400),
    "triglycerides": (20, 5000),
    "hemoglobin": (3, 25),
    "hemoglobin_a1c": (3, 20),
    "hematocrit": (10, 65),
    "wbc": (0.5, 50),
    "rbc": (1, 10),
    "platelets": (10, 1000),
    "tsh": (0.01, 100),
    "ft3": (1, 20),
    "ft4": (0.1, 8),
    "creatinine": (0.1, 20),
    "urea": (5, 300),
    "uric_acid": (1, 20),
    "ferritin": (1, 5000),
    "iron": (10, 500),
    "vitamin_d": (1, 200),
    "vitamin_b12": (100, 2000),
    "folate": (1, 50),
    "alt": (5, 2000),
    "ast": (5, 2000),
    "ggt": (5, 1000),
    "bilirubin_total": (0.1, 30),
    "crp": (0.01, 500),
    "testosterone_total": (10, 2000),
    "cortisol": (1, 100),
    "magnesium": (0.5, 5),
    "calcium": (4, 20),
    "potassium": (1, 10),
    "sodium": (100, 200),
}


def normalize_marker(raw_marker: str) -> str:
    ""
    lower = raw_marker.lower().strip()

    if lower in MARKER_ALIASES:
        return MARKER_ALIASES[lower]

    return lower.replace(" ", "_").replace("-", "_")


def validate_value(
    marker: str, value: float, unit: str, ref_min: float | None, ref_max: float | None
) -> bool:
    ""

    if marker in PLAUSIBILITY:
        pmin, pmax = PLAUSIBILITY[marker]
        if value < pmin or value > pmax:
            log.warning(
                "Value %s=%s outside plausibility range [%s, %s]", marker, value, pmin, pmax
            )
            return False


    if ref_min is not None and ref_max is not None:
        if ref_min >= ref_max:
            log.warning(
                "Invalid reference range for %s: min=%s >= max=%s", marker, ref_min, ref_max
            )
            return False

    return True


def compute_anomaly(value: float, ref_min: float | None, ref_max: float | None) -> bool | None:
    ""
    if ref_min is None and ref_max is None:
        return None
    if ref_min is not None and value < ref_min:
        return True
    if ref_max is not None and value > ref_max:
        return True
    return False


def parse_llm_response(llm_output: str | list) -> list[dict]:
    ""



    if isinstance(llm_output, list):
        return llm_output

    if not isinstance(llm_output, str):
        log.error("Unexpected LLM output type: %s", type(llm_output))
        return []


    text = llm_output.strip()


    if "```json" in text:
        text = text.split("```json")[1].split("```")[0].strip()
    elif "```" in text:
        text = text.split("```")[1].split("```")[0].strip()

    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, dict):
            return [parsed]
    except json.JSONDecodeError:
        log.error("Failed to parse LLM response as JSON")
        return []

    return []


def _call_anthropic_multimodal(raw_text: str, image_b64: str, media_type: str) -> str:
    ""

    _CROSS_SOURCE_DIR = Path(__file__).resolve().parent.parent / "cross-source"
    if str(_CROSS_SOURCE_DIR) not in sys.path:
        sys.path.insert(0, str(_CROSS_SOURCE_DIR))
    from xs_anthropic_client import get_client

    client = get_client()

    content = []
    if image_b64:
        content.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_type or "image/jpeg",
                    "data": image_b64,
                },
            }
        )
    if raw_text:
        content.append({"type": "text", "text": f"Text extracted from the PDF:\n{raw_text[:8000]}"})

    msg = client.messages.create(
        model="claude-sonnet-4-5-20250929",
        max_tokens=4096,
        temperature=0,
        messages=[{"role": "user", "content": content}],
        system=BLOOD_TEST_EXTRACTION_PROMPT,
    )
    return msg.content[0].text


def _call_deepseek_text(raw_text: str) -> str:
    ""
    from openai import OpenAI

    client = OpenAI(
        api_key=os.environ["DEEPSEEK_API_KEY"],
        base_url="https://api.deepseek.com",
    )

    resp = client.chat.completions.create(
        model="deepseek-chat",
        max_tokens=4096,
        temperature=0,
        messages=[
            {"role": "system", "content": BLOOD_TEST_EXTRACTION_PROMPT},
            {"role": "user", "content": raw_text[:8000]},
        ],
    )
    return resp.choices[0].message.content


def call_llm_for_blood_test(
    raw_text: str = "", image_b64: str = "", media_type: str = ""
) -> list[dict]:
    ""





    use_anthropic = bool(image_b64) or len(raw_text) < 100

    if use_anthropic:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError("ANTHROPIC_API_KEY not set — required for image-based extraction")
        raw_response = call_llm_with_retry(
            _call_anthropic_multimodal, raw_text, image_b64, media_type
        )
    else:
        if not os.environ.get("DEEPSEEK_API_KEY"):
            raise RuntimeError("DEEPSEEK_API_KEY not set — required for text-based extraction")
        raw_response = call_llm_with_retry(_call_deepseek_text, raw_text)

    return parse_llm_response(raw_response)


def process_blood_test(meta: dict, llm_caller=None) -> tuple[dict, list[dict]]:
    ""








    caller = llm_caller or call_llm_for_blood_test

    raw_text = meta.get("raw_text", "")
    image_b64 = meta.get("image_b64", "")
    media_type = meta.get("media_type", "")
    subject = meta.get("subject", OWNER_SUBJECT)


    llm_values = caller(raw_text=raw_text, image_b64=image_b64, media_type=media_type)


    record = {
        "record_id": meta["record_id"],
        "date": meta["date"],
        "type": "blood_test",
        "source_file": meta.get("source_file"),
        "source_format": meta.get("source_format", "pdf"),
        "raw_text": raw_text[:10000] if raw_text else None,
        "diagnosis": None,
        "prescriptions": None,
        "notes": None,
        "processed_at": datetime.now(UTC).isoformat(),
    }


    values = []
    valid_count = 0
    total_count = len(llm_values)

    for v in llm_values:
        marker = normalize_marker(v.get("marker", ""))
        try:
            value = parse_italian_float(v.get("value", 0))
        except (ValueError, TypeError):
            continue

        unit = normalize_unit(v.get("unit", ""))
        ref_min = v.get("ref_min")
        ref_max = v.get("ref_max")

        if ref_min is not None:
            try:
                ref_min = float(ref_min)
            except (ValueError, TypeError):
                ref_min = None
        if ref_max is not None:
            try:
                ref_max = float(ref_max)
            except (ValueError, TypeError):
                ref_max = None

        if validate_value(marker, value, unit, ref_min, ref_max):
            valid_count += 1

        is_anomaly = compute_anomaly(value, ref_min, ref_max)

        values.append(
            {
                "record_id": meta["record_id"],
                "date": meta["date"],
                "marker": marker,
                "value": value,
                "unit": unit,
                "ref_min": ref_min,
                "ref_max": ref_max,
                "is_anomaly": is_anomaly,
                "subject": subject,
            }
        )


    if total_count > 0 and valid_count / total_count < 0.7:
        record["notes"] = f"REVIEW: only {valid_count}/{total_count} values passed validation"
        log.warning(
            "Record %s needs review: %d/%d valid", meta["record_id"], valid_count, total_count
        )

    return record, values


def process_visit(meta: dict, llm_caller=None) -> tuple[dict, list[dict]]:
    ""
    record = {
        "record_id": meta["record_id"],
        "date": meta["date"],
        "type": meta["type"],
        "source_file": meta.get("source_file"),
        "source_format": meta.get("source_format", "pdf"),
        "raw_text": (meta.get("raw_text") or "")[:10000] or None,
        "diagnosis": None,
        "prescriptions": None,
        "notes": None,
        "processed_at": datetime.now(UTC).isoformat(),
    }
    return record, []


def process_manual(meta: dict) -> tuple[dict, list[dict]]:
    ""
    manual_data = meta.get("manual_data", {})
    record = {
        "record_id": meta["record_id"],
        "date": meta["date"],
        "type": meta["type"],
        "source_file": None,
        "source_format": "manual",
        "raw_text": None,
        "diagnosis": None,
        "prescriptions": None,
        "notes": json.dumps(manual_data) if manual_data else None,
        "processed_at": datetime.now(UTC).isoformat(),
    }
    return record, []


def process(
    incoming_dir: Path | None = None,
    output_dir: Path | None = None,
    llm_caller=None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    ""









    inc = incoming_dir or CLINICAL_INCOMING_DIR
    out = output_dir or CLINICAL_PROCESSED_DIR
    out.mkdir(parents=True, exist_ok=True)

    all_records = []
    all_values = []


    records_path = out / "records.parquet"
    values_path = out / "values.parquet"

    if records_path.exists():
        existing_records = pd.read_parquet(records_path)
        existing_ids = set(existing_records["record_id"])
    else:
        existing_records = pd.DataFrame()
        existing_ids = set()

    if values_path.exists():
        existing_values = pd.read_parquet(values_path)
    else:
        existing_values = pd.DataFrame()


    pending = sorted(inc.glob("*.json")) if inc.exists() else []
    log.info("Found %d pending records in %s", len(pending), inc)

    for meta_path in pending:
        try:
            meta = json.loads(meta_path.read_text())
        except json.JSONDecodeError:
            log.error("Invalid JSON: %s", meta_path)
            continue

        record_id = meta.get("record_id", "")
        if record_id in existing_ids:
            log.info("Skipping already processed: %s", record_id[:8])
            continue

        record_type = meta.get("type", "")
        log.info("Processing %s (%s)", record_id[:8], record_type)

        try:
            if record_type == "blood_test":
                record, values = process_blood_test(meta, llm_caller)
            elif record_type in {"visit", "ecg", "imaging"}:
                record, values = process_visit(meta, llm_caller)
            elif record_type in {"vaccination", "allergy", "medication"}:
                record, values = process_manual(meta)
            else:
                log.warning("Unknown record type: %s", record_type)
                continue

            all_records.append(record)
            all_values.extend(values)
        except Exception as e:
            log.error("Failed to process %s: %s", record_id[:8], e)

    if not all_records and existing_records.empty:
        log.warning("No records to process")
        empty_records = pd.DataFrame(
            columns=[
                "record_id",
                "date",
                "type",
                "source_file",
                "source_format",
                "raw_text",
                "diagnosis",
                "prescriptions",
                "notes",
                "processed_at",
            ]
        )
        empty_values = pd.DataFrame(
            columns=[
                "record_id",
                "date",
                "marker",
                "value",
                "unit",
                "ref_min",
                "ref_max",
                "is_anomaly",
                "subject",
            ]
        )
        safe_write_parquet(empty_records, records_path)
        safe_write_parquet(empty_values, values_path)
        return empty_records, empty_values


    new_records_df = pd.DataFrame(all_records)
    new_values_df = pd.DataFrame(all_values) if all_values else pd.DataFrame()

    if not existing_records.empty:
        records_df = pd.concat([existing_records, new_records_df], ignore_index=True)
    else:
        records_df = new_records_df

    if not existing_values.empty and not new_values_df.empty:
        values_df = pd.concat([existing_values, new_values_df], ignore_index=True)
    elif not new_values_df.empty:
        values_df = new_values_df
    else:
        values_df = (
            existing_values
            if not existing_values.empty
            else pd.DataFrame(
                columns=[
                    "record_id",
                    "date",
                    "marker",
                    "value",
                    "unit",
                    "ref_min",
                    "ref_max",
                    "is_anomaly",
                    "subject",
                ]
            )
        )


    safe_write_parquet(records_df, records_path)
    safe_write_parquet(values_df, values_path)
    mark_last_run("clinical-l1")

    log.info(
        "Saved records.parquet (%d rows) and values.parquet (%d rows)",
        len(records_df),
        len(values_df),
    )

    return records_df, values_df


def main():
    parser = argparse.ArgumentParser(description="Clinical records parser — SBK")
    parser.add_argument("--file", type=str, help="Specific metadata JSON to process")
    parser.add_argument("--incoming-dir", type=str, help="Override incoming directory")
    parser.add_argument("--output-dir", type=str, help="Override output directory")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

    inc = Path(args.incoming_dir) if args.incoming_dir else None
    out = Path(args.output_dir) if args.output_dir else None

    records_df, values_df = process(incoming_dir=inc, output_dir=out)
    print("\nClinical parsing complete:")
    print(f"  Records: {len(records_df)}")
    print(f"  Values: {len(values_df)}")


if __name__ == "__main__":
    main()
