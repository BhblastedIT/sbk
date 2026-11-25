""









import os
import re
import unicodedata


ITALIAN_PARTICLES = frozenset(
    {
        "di",
        "de",
        "la",
        "lo",
        "del",
        "della",
        "delle",
        "degli",
        "dei",
        "dal",
        "dalla",
    }
)


def strip_accents(s: str) -> str:
    ""
    nfkd = unicodedata.normalize("NFKD", s)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def normalize_name(name: str) -> str:
    ""




    if not name or not isinstance(name, str):
        return ""
    name = strip_accents(name)
    name = re.sub(r"\s+", " ", name.strip().lower())
    return name


def normalize_name_for_match(name: str) -> str:
    ""



    if not name or not isinstance(name, str):
        return ""
    name = name.strip().lower()
    name = strip_accents(name)

    name = re.sub(r"\b(dr|dott|ing|prof|sig|sig\.ra|avv)\b\.?\s*", "", name)

    name = re.sub(r"\bd['''\u2019]", "d'", name)

    name = re.sub(r"[^\w\s']", " ", name)

    return " ".join(name.split())


def normalize_name_case(name: str) -> str:
    ""





    if not name or not isinstance(name, str):
        return name
    name = name.strip()
    if not name:
        return name


    alpha_chars = [c for c in name if c.isalpha()]
    if not alpha_chars:
        return name

    is_all_upper = all(c.isupper() for c in alpha_chars)
    is_all_lower = all(c.islower() for c in alpha_chars)

    if not is_all_upper and not is_all_lower:
        return name


    parts = name.split()
    result = []
    for i, part in enumerate(parts):
        lower_part = part.lower()


        for apo in ["'", "\u2019", "\u2018", "'"]:
            if apo in lower_part and lower_part.startswith("d" + apo):
                after = lower_part[2:]
                result.append("d" + apo + after.capitalize())
                break
        else:

            if lower_part in ITALIAN_PARTICLES and i > 0:
                result.append(lower_part)
            else:
                result.append(part.capitalize())

    return " ".join(result)


def normalize_email(email: str) -> str:
    ""
    if not email or not isinstance(email, str):
        return ""
    return email.strip().lower()


def normalize_phone(phone: str) -> str:
    ""








    if not phone or not isinstance(phone, str):
        return ""

    cleaned = re.sub(r"[^\d+]", "", phone.strip())
    if not cleaned or len(cleaned) < 6:
        return ""

    # Default country code is configurable; unset means no country is assumed.
    _cc = os.environ.get("SBK_PHONE_CC", "").strip().lstrip("+")

    if cleaned.startswith("00"):
        return "+" + cleaned[2:]

    if cleaned.startswith("+"):
        return cleaned

    if _cc and cleaned.startswith(_cc) and len(cleaned) >= len(_cc) + 6:
        return "+" + cleaned

    if _cc and cleaned.isdigit():
        return "+" + _cc + cleaned

    return "+" + cleaned


def normalize_gmail(email: str) -> str:
    ""




    if "@gmail.com" not in email:
        return email
    local, domain = email.split("@", 1)
    local = local.split("+")[0].replace(".", "")
    return f"{local}@{domain}"
