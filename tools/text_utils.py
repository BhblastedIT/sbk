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


# Country codes whose national numbers keep their leading 0 after the code (Italy, San
# Marino, Vatican City, Ivory Coast): "02 0000 0000" in Italy is "+39 02 0000 0000". Everywhere
# else a leading 0 is the national trunk prefix and is dropped ("07700 900123" in the UK is
# "+44 7700 900123").
_CC_KEEP_LEADING_ZERO = frozenset({"39", "378", "379", "225"})

# The longest national number (without the country code and without a trunk 0) of a few
# countries; 10 for the others. A number written with neither "+" nor "00" whose digits begin
# with your own country code already carries that code only when it is longer than this:
# "447700900123" is "+44 7700 900123", while an Italian mobile written nationally as
# "3900000001" stays a national number ("+39 390 000 0001").
_NSN_MAX = {
    "1": 10, "7": 10, "20": 10, "27": 9, "30": 10, "31": 9, "32": 9, "33": 9, "34": 9,
    "36": 9, "39": 11, "40": 9, "41": 9, "43": 13, "44": 10, "45": 8, "46": 10, "47": 8,
    "48": 9, "49": 11, "52": 10, "55": 11, "61": 9, "62": 12, "63": 10, "64": 10, "65": 8,
    "81": 10, "82": 10, "86": 11, "90": 10, "91": 10, "225": 10, "351": 9, "353": 9,
    "358": 10, "378": 10, "379": 10, "971": 9, "972": 9,
}


def phone_country_code() -> str:
    """The country calling code of your own phone numbers, digits only.

    SBK_PHONE_CC wins, else "phone_country_code" of sbk.config.json; "" when neither is
    set, and then no country is assumed. Every step that compares phone numbers reads it
    through normalize_phone(), so the address book, WhatsApp, Telegram, the plugins and the
    merge all write the same number the same way.
    """
    cc = os.environ.get("SBK_PHONE_CC", "")
    if not cc.strip():
        try:
            from sbk_config import user_cfg
        except Exception:  # text_utils used on its own, without the tools folder
            return ""
        cc = user_cfg("phone_country_code", "") or ""
    return re.sub(r"\D", "", str(cc))


def normalize_phone(phone: str, country_code: "str | None" = None) -> str:
    """One phone number as "+<country code><number>", "" when it is not a number.

    The one normaliser every step uses. A number written without its country code gets
    `country_code` (default: phone_country_code(), i.e. SBK_PHONE_CC or the
    "phone_country_code" key of sbk.config.json); a national leading 0 is dropped unless
    that country keeps it (Italy and a few others). "00" and "+" mean the code is
    already there; "(0)" after it ("+44 (0)7700 900123", "0044 (0)7700 900123") is dropped.
    A number with neither "+" nor "00" is national, unless its digits begin with your own
    code and it is too long to be a national number of that country ("447700900123").
    Without a country code configured, a number without one is only prefixed with "+".
    """
    if not phone or not isinstance(phone, str):
        return ""

    _cc = phone_country_code() if country_code is None else re.sub(r"\D", "", country_code)

    raw = phone.strip()
    if "(0)" in raw:
        # "+44 (0)7700 ...", "0044 (0)7700 ...", "44 (0)7700 ..." or a national "(0)20 ...":
        # the bracketed 0 is the trunk prefix, kept only where the country keeps it.
        code = re.sub(r"\D", "", raw.split("(0)", 1)[0])
        if code.startswith("00"):
            code = code[2:]
        raw = raw.replace("(0)", "0" if (code or _cc) in _CC_KEEP_LEADING_ZERO else "", 1)
    cleaned = re.sub(r"[^\d+]", "", raw)
    if not cleaned or len(cleaned) < 6:
        return ""

    if cleaned.startswith("00"):
        return "+" + cleaned[2:]

    if cleaned.startswith("+"):
        return "+" + cleaned.replace("+", "")

    if _cc and cleaned.isdigit():
        if cleaned.startswith(_cc) and len(cleaned) > _NSN_MAX.get(_cc, 10):
            return "+" + cleaned  # the code is there, written without "+" or "00"
        if cleaned.startswith("0") and _cc not in _CC_KEEP_LEADING_ZERO:
            cleaned = cleaned[1:]
        return "+" + _cc + cleaned

    return "+" + cleaned


def normalize_gmail(email: str) -> str:
    ""




    if "@gmail.com" not in email:
        return email
    local, domain = email.split("@", 1)
    local = local.split("+")[0].replace(".", "")
    return f"{local}@{domain}"
