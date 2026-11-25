#!/usr/bin/env python3
""

























import argparse
import json
import random
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path



VOWELS = "aeiou"
CONSONANTS = "bcdfghjklmnprstvwxyz"

START_CLUSTERS = [
    "bl",
    "br",
    "cl",
    "cr",
    "dr",
    "fl",
    "fr",
    "gl",
    "gr",
    "pl",
    "pr",
    "sc",
    "sk",
    "sl",
    "sm",
    "sn",
    "sp",
    "st",
    "str",
    "sw",
    "tr",
    "tw",
    "wr",
    "sh",
    "ch",
    "th",
]

END_CLUSTERS = [
    "ck",
    "ft",
    "ld",
    "lf",
    "lk",
    "lm",
    "lp",
    "lt",
    "mp",
    "nd",
    "nk",
    "nt",
    "pt",
    "rd",
    "rk",
    "rm",
    "rn",
    "rp",
    "rs",
    "rt",
    "sk",
    "sp",
    "st",
    "xt",
]


# Brand-root exclusions. Empty by default; pass exclusions via --exclude.
EXCLUDED_STARTS = []
EXCLUDED_CONTAINS = []
EXCLUDED_NAMES = set()


def is_pronounceable(name: str) -> bool:
    ""
    name = name.lower()

    if not any(c in VOWELS for c in name):
        return False

    consonant_run = 0
    for c in name:
        if c in CONSONANTS:
            consonant_run += 1
            if consonant_run > 3:
                return False
        else:
            consonant_run = 0

    vowel_run = 0
    for c in name:
        if c in VOWELS:
            vowel_run += 1
            if vowel_run > 2:
                return False
        else:
            vowel_run = 0
    return True


def passes_filters(name: str) -> bool:
    ""
    n = name.lower()
    if len(n) < 3 or len(n) > 7:
        return False
    if any(n.startswith(ex) for ex in EXCLUDED_STARTS):
        return False
    if any(ex in n for ex in EXCLUDED_CONTAINS):
        return False
    if n in EXCLUDED_NAMES:
        return False
    if not is_pronounceable(n):
        return False

    for i in range(len(n) - 2):
        if n[i] == n[i + 1] == n[i + 2]:
            return False
    return True


def generate_cvcv(length: int) -> str:
    ""
    name = ""
    for i in range(length):
        if i % 2 == 0:
            name += random.choice(CONSONANTS)
        else:
            name += random.choice(VOWELS)
    return name


def generate_cvccv(length: int) -> str:
    ""
    patterns = {
        4: ["cvcc", "ccvc", "cvcv", "vcvc"],
        5: ["cvcvc", "cvccv", "ccvcv", "cvcev", "cvcvc"],
        6: ["cvccvc", "cvcvcv", "ccvcvc", "cvccve"],
    }
    pat = random.choice(patterns.get(length, ["cvcvc"]))
    name = ""
    for ch in pat:
        if ch == "c":
            name += random.choice(CONSONANTS)
        elif ch == "v":
            name += random.choice(VOWELS)
        elif ch == "e":
            name += random.choice(VOWELS)
    return name[:length]


def generate_name_like(style: str = "abstract", length: int = 5) -> str:
    ""
    if style == "abstract":

        if random.random() < 0.5:
            return generate_cvcv(length)
        else:
            return generate_cvccv(length)
    elif style == "human":

        soft_starts = list("bcdfghjklmnprstvw")
        name = random.choice(soft_starts)
        for i in range(1, length):
            if i % 2 == 1:
                name += random.choice(VOWELS)
            else:
                name += random.choice(CONSONANTS)
        return name
    return generate_cvcv(length)


def generate_candidates(count: int = 200, length: int = 5, pattern: str = None) -> list[str]:
    ""
    candidates = set()
    attempts = 0
    max_attempts = count * 50

    while len(candidates) < count and attempts < max_attempts:
        attempts += 1
        if pattern:
            name = ""
            for ch in pattern:
                if ch == "c":
                    name += random.choice(CONSONANTS)
                elif ch == "v":
                    name += random.choice(VOWELS)
            name = name[:length] if len(name) > length else name
        else:
            style = random.choice(["abstract", "abstract", "human"])
            name = generate_name_like(style, length)

        if passes_filters(name) and name not in candidates:
            candidates.add(name)

    return sorted(candidates)





def check_whois_com(domain: str) -> dict:
    ""
    try:
        result = subprocess.run(
            ["whois", domain],
            capture_output=True,
            text=True,
            timeout=10,
        )
        output = result.stdout.lower()

        if any(
            phrase in output
            for phrase in [
                "no match for",
                "not found",
                "no entries found",
                "domain not found",
                "no data found",
                "status: free",
                "is available",
            ]
        ):
            return {"domain": domain, "available": True, "method": "whois"}

        if any(
            phrase in output
            for phrase in [
                "domain name:",
                "registrar:",
                "creation date:",
                "updated date:",
                "name server:",
            ]
        ):
            return {"domain": domain, "available": False, "method": "whois"}

        return {
            "domain": domain,
            "available": "unknown",
            "method": "whois",
            "note": "ambiguous response",
        }
    except subprocess.TimeoutExpired:
        return {"domain": domain, "available": "timeout", "method": "whois"}
    except Exception as e:
        return {"domain": domain, "available": "error", "method": "whois", "note": str(e)}


def check_whois_ai(domain: str) -> dict:
    ""
    try:
        result = subprocess.run(
            ["whois", "-h", "whois.nic.ai", domain],
            capture_output=True,
            text=True,
            timeout=10,
        )
        output = result.stdout.lower()
        if any(
            phrase in output
            for phrase in [
                "not found",
                "no match",
                "no data found",
                "is available",
                "domain not found",
            ]
        ):
            return {"domain": domain, "available": True, "method": "whois-ai"}
        if any(
            phrase in output
            for phrase in [
                "domain name:",
                "registrar:",
                "creation date:",
                "name server:",
            ]
        ):
            return {"domain": domain, "available": False, "method": "whois-ai"}
        return {
            "domain": domain,
            "available": "unknown",
            "method": "whois-ai",
            "note": output[:200],
        }
    except subprocess.TimeoutExpired:
        return {"domain": domain, "available": "timeout", "method": "whois-ai"}
    except Exception as e:
        return {"domain": domain, "available": "error", "method": "whois-ai", "note": str(e)}


def check_dns(domain: str) -> bool:
    ""
    try:
        result = subprocess.run(
            ["dig", "+short", domain, "A"],
            capture_output=True,
            text=True,
            timeout=5,
        )

        if result.stdout.strip():
            return False
        return True
    except Exception:
        return True


def check_domain_pair(name: str, delay: float = 0.5) -> dict:
    ""
    com_domain = f"{name}.com"
    ai_domain = f"{name}.ai"


    com_result = check_whois_com(com_domain)
    time.sleep(delay)


    ai_result = check_whois_ai(ai_domain)
    time.sleep(delay)


    if com_result["available"] == "unknown":
        com_result["available"] = check_dns(com_domain)
        com_result["method"] += "+dns"
    if ai_result["available"] == "unknown":
        ai_result["available"] = check_dns(ai_domain)
        ai_result["method"] += "+dns"

    return {
        "name": name,
        "com": com_result,
        "ai": ai_result,
        "both_available": com_result["available"] is True and ai_result["available"] is True,
    }


def check_domains_bulk(names: list[str], workers: int = 6, delay: float = 0.8) -> list[dict]:
    ""
    results = []
    total = len(names)

    print(f"\nChecking {total} names (.com + .ai)...\n")



    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {}
        for i, name in enumerate(names):
            future = executor.submit(check_domain_pair, name, delay)
            futures[future] = (i, name)

        for future in as_completed(futures):
            i, name = futures[future]
            try:
                result = future.result()
                results.append(result)


                com_status = (
                    "V"
                    if result["com"]["available"] is True
                    else ("X" if result["com"]["available"] is False else "?")
                )
                ai_status = (
                    "V"
                    if result["ai"]["available"] is True
                    else ("X" if result["ai"]["available"] is False else "?")
                )
                both = " << BOTH AVAILABLE" if result["both_available"] else ""
                print(
                    f"  [{len(results):3d}/{total}] {name:12s}  .com={com_status}  .ai={ai_status}{both}"
                )
            except Exception as e:
                print(f"  [{len(results):3d}/{total}] {name:12s}  ERROR: {e}")

    return results





def print_results(results: list[dict], both_only: bool = False):
    ""
    if both_only:
        results = [r for r in results if r["both_available"]]

    if not results:
        print("\nNo names found with both .com and .ai available.")
        return

    print(f"\n{'=' * 60}")
    if both_only:
        print(f"  BOTH .com AND .ai AVAILABLE ({len(results)} names)")
    else:
        print(f"  DOMAIN CHECK RESULTS ({len(results)} names)")
    print(f"{'=' * 60}")
    print(f"  {'Name':<12s} {'Len':>3s}  {'.com':<8s} {'.ai':<8s} {'Both?':<6s}")
    print(f"  {'-' * 12} {'-' * 3}  {'-' * 8} {'-' * 8} {'-' * 6}")

    for r in sorted(results, key=lambda x: (-x["both_available"], x["name"])):
        name = r["name"]
        com = (
            "FREE"
            if r["com"]["available"] is True
            else ("TAKEN" if r["com"]["available"] is False else "???")
        )
        ai = (
            "FREE"
            if r["ai"]["available"] is True
            else ("TAKEN" if r["ai"]["available"] is False else "???")
        )
        both = "YES" if r["both_available"] else ""
        print(f"  {name:<12s} {len(name):>3d}  {com:<8s} {ai:<8s} {both:<6s}")


    both_count = sum(1 for r in results if r["both_available"])
    com_count = sum(1 for r in results if r["com"]["available"] is True)
    ai_count = sum(1 for r in results if r["ai"]["available"] is True)
    print(f"\n  Summary: {com_count} .com free, {ai_count} .ai free, {both_count} BOTH free")


def save_results(results: list[dict], output_path: str):
    ""
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved to: {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Bulk domain availability checker for brand naming"
    )
    parser.add_argument("--names", type=str, help="Comma-separated list of names to check")
    parser.add_argument("--file", type=str, help="File with one name per line")
    parser.add_argument(
        "--generate", action="store_true", help="Generate random pronounceable names"
    )
    parser.add_argument("--length", type=int, default=5, help="Target name length (default: 5)")
    parser.add_argument(
        "--count", type=int, default=200, help="Number of names to generate (default: 200)"
    )
    parser.add_argument("--pattern", type=str, help="Pattern like 'cvcvc' (c=consonant, v=vowel)")
    parser.add_argument(
        "--both-available",
        action="store_true",
        help="Only show names where both .com and .ai are free",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=3,
        help="Parallel workers (default: 3, keep low to avoid rate limits)",
    )
    parser.add_argument(
        "--delay", type=float, default=1.0, help="Delay between checks in seconds (default: 1.0)"
    )
    parser.add_argument("--output", type=str, help="Save results to JSON file")
    parser.add_argument(
        "--dry-run", action="store_true", help="Only generate names, don't check domains"
    )
    parser.add_argument("--exclude", type=str, help="Comma-separated names to exclude")

    args = parser.parse_args()

    if args.exclude:
        EXCLUDED_NAMES.update(n.strip().lower() for n in args.exclude.split(","))


    names = []

    if args.names:
        names = [n.strip().lower() for n in args.names.split(",") if n.strip()]

    if args.file:
        path = Path(args.file)
        if path.exists():
            names.extend(
                line.strip().lower()
                for line in path.read_text().splitlines()
                if line.strip() and not line.startswith("#")
            )

    if args.generate:
        generated = generate_candidates(
            count=args.count,
            length=args.length,
            pattern=args.pattern,
        )
        print(f"Generated {len(generated)} candidate names (length={args.length}):")
        for i, name in enumerate(generated):
            print(f"  {name}", end="  " if (i + 1) % 8 != 0 else "\n")
        print()
        names.extend(generated)

    if not names:
        parser.print_help()
        sys.exit(1)


    names = sorted(set(names))
    print(f"\nTotal unique names to check: {len(names)}")

    if args.dry_run:
        print("\n(Dry run — no domain checks performed)")
        return


    results = check_domains_bulk(names, workers=args.workers, delay=args.delay)


    print_results(results, both_only=args.both_available)


    if args.output:
        save_results(results, args.output)


if __name__ == "__main__":
    main()
