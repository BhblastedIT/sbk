"""One person, whatever order the sources come in: email over phone, one phone normaliser,
company cards out, person ids without an entity map.

- An email-keyed identity always wins over a phone-keyed one. A card with email and phone that
  meets a row started by a WhatsApp number or a Telegram contact becomes one email-keyed row that
  keeps the phone, the card's name, the organisation and every source. Every order and every
  combination of WhatsApp, Telegram, the address book and a database on the same person gives
  one row.
- An unsaved WhatsApp number named by the address book takes the book's name.
- One phone normaliser (tools/text_utils.normalize_phone) applies phone_country_code of
  sbk.config.json (or SBK_PHONE_CC) in the kernel contacts step, the merge and the plugins, so a
  national number on a card and the same number written in full elsewhere are one person.
- Address-book company cards (KIND:org, X-ABShowAs:COMPANY) carry their kind into
  contacts.parquet and never become persons.
- The p_ + hash(contact_key) person id is given even when no entity-map row resolves.

Every check runs in a subprocess with its own SBK_DATA_ROOT, HOME and config. Demo data only,
phone numbers from the ranges reserved for fiction (+1 202 555 01xx, +44 7700 900xxx,
+44 20 7946 0xxx), no network, no model key, no Keychain.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
CS = TOOLS / "cross-source"
OWNER = {
    "owner": "Casey Demo",
    "own_names": ["casey demo", "casey"],
    "own_emails": ["casey@example.com"],
}


def _env(tmp: Path, config: dict, extra: dict | None = None) -> dict:
    cfg = tmp / "sbk.config.json"
    cfg.write_text(json.dumps(config), encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("SBK_", "ANTHROPIC_"))}
    (tmp / "home").mkdir(exist_ok=True)
    env.update(
        HOME=str(tmp / "home"),
        SBK_DATA_ROOT=str(tmp / "data"),
        SBK_CONFIG=str(cfg),
        PYTHON_KEYRING_BACKEND="keyring.backends.fail.Keyring",
        PYTHONPATH=os.pathsep.join([str(TOOLS), str(CS)]),
    )
    env.update(extra or {})
    return env


def _run(args: list, tmp: Path, config: dict, extra: dict | None = None, timeout: int = 300):
    return subprocess.run(
        [sys.executable, *[str(a) for a in args]],
        cwd=str(ROOT),
        env=_env(tmp, config, extra),
        capture_output=True,
        text=True,
        timeout=timeout,
        stdin=subprocess.DEVNULL,
    )


def _out(r) -> str:
    return (r.stdout or "") + (r.stderr or "")


def _ok(r, what: str) -> str:
    assert r.returncode == 0, f"{what}: exit {r.returncode}\n" + _out(r)[-3000:]
    assert "Traceback (most recent" not in _out(r), f"{what}\n" + _out(r)[-3000:]
    return _out(r)


def _code(tmp: Path, config: dict, code: str, extra: dict | None = None) -> str:
    r = _run(["-c", textwrap.dedent(code), CS / "xs-l2-merge.py"], tmp, config, extra)
    assert r.returncode == 0 and r.stdout.strip().endswith("ok"), _out(r)[-4000:]
    return _out(r)


# --------------------------------------------------------------------------- the normaliser


def test_one_normaliser_reads_the_config_key(tmp_path):
    code = """
    from text_utils import normalize_phone, phone_country_code
    assert phone_country_code() == "44", phone_country_code()
    # national forms get the code; the UK trunk 0 and the "(0)" go
    for raw in ("7700 900123", "07700 900123", "+44 (0)7700 900123", "0044 7700 900123",
                "+44 7700 900123", "447700900123"):
        assert normalize_phone(raw) == "+447700900123", (raw, normalize_phone(raw))
    # a number in full keeps its own code; an explicit code wins over the configured one
    assert normalize_phone("+1 (202) 555-0177") == "+12025550177"
    assert normalize_phone("(202) 555-0177", "1") == "+12025550177"
    # Italy keeps its leading 0 (landlines), with the code given or written (an all-zero
    # number, written so no real one appears here)
    it = "+" + "390200000000"
    assert normalize_phone("02 0000 0000", "39") == it
    assert normalize_phone("+" + "39 (0)2 0000 0000") == it
    assert normalize_phone("123") == "" and normalize_phone("") == "" and normalize_phone(None) == ""
    print("ok")
    """
    _code(tmp_path, {**OWNER, "phone_country_code": "44"}, code)


def test_the_environment_wins_and_no_code_assumes_none(tmp_path):
    code = """
    import os
    from text_utils import normalize_phone, phone_country_code
    assert phone_country_code() == "1"
    assert normalize_phone("(202) 555-0177") == "+12025550177"
    os.environ["SBK_PHONE_CC"] = ""
    assert phone_country_code() == "44"  # back to the config key
    print("ok")
    """
    _code(tmp_path, {**OWNER, "phone_country_code": "44"}, code, {"SBK_PHONE_CC": "+1"})
    code = """
    from text_utils import normalize_phone, phone_country_code
    assert phone_country_code() == ""
    assert normalize_phone("7700 900123") == "+7700900123"  # compared as written
    print("ok")
    """
    _code(tmp_path, OWNER, code)


def test_plugins_and_the_merge_share_the_normaliser(tmp_path):
    code = """
    import importlib.util, sys
    sys.path.insert(0, sys.argv[1].rsplit("/cross-source/", 1)[0] + "/contacts")
    sys.path.insert(0, sys.argv[1].rsplit("/cross-source/", 1)[0] + "/telegram")
    sys.path.insert(0, sys.argv[1].rsplit("/cross-source/", 1)[0] + "/databases")
    import ct_book, tg_export, db_reader
    spec = importlib.util.spec_from_file_location("merge_n", sys.argv[1])
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    assert tg_export.phone_digits("07700 900305") == tg_export.phone_digits("+44 7700 900305")
    assert db_reader._contact_key("", "07700 900305", "x") == db_reader._contact_key("", "+447700900305", "y")
    rows = [dict(full_name="Ines Varga", primary_email="", primary_phone=p, source="t", source_id=str(i))
            for i, p in enumerate(("07700 900305", "+44 7700 900305"))]
    kept, dropped = ct_book.dedupe(rows)
    assert len(kept) == 1 and dropped == 1, kept
    assert m._chiave_telefono("07700 900305") == "+447700900305"
    print("ok")
    """
    _code(tmp_path, {**OWNER, "phone_country_code": "44"}, code)


# --------------------------------------------------------------------------- one person, any order

_HARNESS = """
import importlib.util, itertools, sys
from collections import defaultdict
import pandas as pd
spec = importlib.util.spec_from_file_location("merge_p", sys.argv[1])
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

def stats():
    return defaultdict(lambda: {"matched": 0, "unmatched": 0, "ambiguous": 0,
                                "da_verificare": 0, "verificati": 0})

def wa(name, phone, n=3):
    return {"name": name, "phone": phone, "message_count": n, "is_1to1_participant": True,
            "last_message": "2026-11-25T09:00:00", "first_message": "2026-11-20T09:00:00"}

def card(name, phone, email="", org="", kind=""):
    from text_utils import normalize_phone
    p = normalize_phone(phone)
    return {"name": name, "organization": org, "phone_numbers": [p] if p else [], "email": email,
            "phone_primary": p, "name_normalized": m.normalize_name_for_match(name),
            "first_name": name.split()[0], "last_name": " ".join(name.split()[1:]),
            "last_updated": "", "birthday": "", "is_business": bool(kind), "kind": kind}

def plug(source, name, email, phone, company=""):
    return {"source": source, "name": name, "email": email, "phone": phone, "company": company,
            "title": "", "url": "", "first_seen": "2026-11-01T09:00:00",
            "last_seen": "2026-11-19T09:00:00", "interactions": 2,
            "plugin": source.split(":")[0], "from_participants": False}

def phase2(wa_rows, cards, plugin_rows):
    merged = m.merge_contacts_phase1(None, None, None, None, None, None, None)
    w = pd.DataFrame(wa_rows) if wa_rows else None
    c = pd.DataFrame(cards) if cards else None
    p = pd.DataFrame(plugin_rows) if plugin_rows else None
    out, _ = m.merge_contacts_phase2(merged, None, None, w, None, c, None, None,
                                     da_verificare=[], verifiche={}, plugin_df=p)
    return out
"""


def test_every_order_and_mix_of_sources_gives_one_person(tmp_path):
    code = _HARNESS + textwrap.dedent(
        """
    EMAIL, TEL = "omar@fabrikam.example", "+12025550177"
    SOURCES = {
        "whatsapp": ("wa", wa("+1 202 555 0177", "+1 202 555 0177")),
        "telegram": ("plug", plug("telegram", "Omar Reyes", "", "+1 202 555 0177")),
        "vcard": ("card", card("Omar Reyes", "(202) 555-0177", EMAIL, "Fabrikam Demo")),
        "databases": ("plug", plug("databases:book", "Omar Reyes", EMAIL, "+1 (202) 555-0177",
                                   "Fabrikam Demo")),
    }
    checked = 0
    for k in range(1, 5):
        for combo in itertools.permutations(SOURCES, k):
            rows = {"wa": [], "card": [], "plug": []}
            for s in combo:
                lane, row = SOURCES[s]
                rows[lane].append(row)
            book = phase2(rows["wa"], rows["card"], rows["plug"])
            assert len(book) == 1, (combo, book[["name", "email", "contact_key", "started_by"]])
            r = book.iloc[0]
            with_email = "vcard" in combo or "databases" in combo
            assert (r["email"] == EMAIL) == with_email, (combo, r["email"])
            assert bool(r["contact_key"]) != with_email, (combo, r["contact_key"])
            if combo != ("whatsapp",):
                assert r["name"] == "Omar Reyes", (combo, r["name"])
            assert m.normalize_phone(str(r["phone_primary"])) == TEL, (combo, r["phone_primary"])
            assert bool(r["has_whatsapp"]) == ("whatsapp" in combo), combo
            assert bool(r["has_iphone"]) == ("vcard" in combo), combo
            srcs = str(r.get("plugin_sources") or "")
            assert ("telegram" in srcs) == ("telegram" in combo), (combo, srcs)
            assert ("databases" in srcs) == ("databases" in combo), (combo, srcs)
            if with_email:
                assert r["organization"] == "Fabrikam Demo", (combo, r["organization"])
            checked += 1
    assert checked == 64, checked
    print(checked, "ok")
    """
    )
    _code(tmp_path, {**OWNER, "phone_country_code": "1"}, code)


def test_the_leftovers_in_any_order_give_the_same_book(tmp_path):
    code = _HARNESS + textwrap.dedent(
        """
    import itertools
    EMAIL = "theo@dune.example"

    def leftovers():
        w = wa("+44 7700 900412", "+44 7700 900412")
        t = plug("telegram", "Theo Marsh", "", "+44 7700 900412")
        c = card("Theo Marsh", "07700 900412", EMAIL, "Dune Demo")
        d = plug("databases:crm", "Theo Marsh", EMAIL, "+44 7700 900412", "Dune Demo")
        tel = m._chiave_telefono("+44 7700 900412")
        return [
            m._pendente("whatsapp", tel, w["phone"], w["name"], "", m._applica_whatsapp(w)),
            m._pendente("telegram", tel, t["phone"], t["name"], "",
                        lambda get, put, _r=pd.DataFrame([t]).itertuples(index=False).__next__():
                            m._riempi_da_plugin(get, put, _r)),
            m._pendente("iphone", tel, c["phone_primary"], c["name"], EMAIL, m._applica_iphone(c)),
            m._pendente("databases:crm", tel, d["phone"], d["name"], EMAIL,
                        lambda get, put, _r=pd.DataFrame([d]).itertuples(index=False).__next__():
                            m._riempi_da_plugin(get, put, _r)),
        ]

    base = m.merge_contacts_phase1(None, None, None, None, None, None, None)
    for col, default in m.PLUGIN_COLUMNS_DEFAULTS.items():
        base[col] = default
    seen = set()
    for order in itertools.permutations(range(4)):
        items = leftovers()
        out = m.merge_phone_contacts(base.copy(), [items[i] for i in order], stats())
        assert len(out) == 1, (order, out[["name", "email", "contact_key"]])
        r = out.iloc[0]
        assert r["email"] == EMAIL and not r["contact_key"] and r["name"] == "Theo Marsh", (order, r)
        assert bool(r["has_whatsapp"]) and bool(r["has_iphone"]), order
        assert {"telegram", "databases:crm"} <= set(str(r["plugin_sources"]).split("|||")), order
        assert r["organization"] == "Dune Demo" and m.normalize_phone(r["phone_primary"]) == "+447700900412"
        seen.add((r["name"], r["email"], r["started_by"]))
    assert len(seen) == 1, seen  # the same row whatever the order
    print("ok")
    """
    )
    _code(tmp_path, {**OWNER, "phone_country_code": "44"}, code)


def test_a_card_upgrades_an_earlier_phone_row(tmp_path):
    code = _HARNESS + textwrap.dedent(
        """
    base = m.merge_contacts_phase1(None, None, None, None, None, None, None)
    w = wa("+44 7700 900412", "+44 7700 900412")
    c = card("Theo Marsh", "+44 7700 900412", "theo@dune.example", "Dune Demo")
    tel = m._chiave_telefono("+44 7700 900412")
    # the WhatsApp number first: a tel row named by the number
    book = m.merge_phone_contacts(base.copy(), [
        m._pendente("whatsapp", tel, w["phone"], w["name"], "", m._applica_whatsapp(w))], stats())
    assert book.iloc[0]["contact_key"] == "tel:+447700900412"
    assert book.iloc[0]["name"] == "+44 7700 900412"
    # then the card, matched by phone onto that row in the same pass
    s = stats()
    pend = [m._pendente("whatsapp", tel, w["phone"], w["name"], "", m._applica_whatsapp(w)),
            m._pendente("iphone", tel, c["phone_primary"], c["name"], "theo@dune.example",
                        m._applica_iphone(c))]
    # force the old order (the number first) through the upgrade path
    m_sort = m._ordine_pendente
    m._ordine_pendente = lambda p: 0
    try:
        book = m.merge_phone_contacts(base.copy(), pend, s)
    finally:
        m._ordine_pendente = m_sort
    assert len(book) == 1, book
    r = book.iloc[0]
    assert r["email"] == "theo@dune.example" and r["contact_key"] == "" and r["name"] == "Theo Marsh"
    assert r["domain"] == "dune.example" and r["organization"] == "Dune Demo"
    assert bool(r["has_whatsapp"]) and bool(r["has_iphone"]) and r["started_by"] == "whatsapp"
    print("ok")
    """
    )
    _code(tmp_path, OWNER, code)


def test_an_unsaved_number_takes_the_address_book_name(tmp_path):
    code = _HARNESS + textwrap.dedent(
        """
    # Zed: only a phone on the card, and an unsaved WhatsApp chat from that phone
    book = phase2([wa("+44 20 7946 0958", "+44 20 7946 0958")], [card("Zed Quill", "+44 20 7946 0958")], [])
    assert len(book) == 1 and book.iloc[0]["name"] == "Zed Quill", book[["name", "contact_key"]]
    assert book.iloc[0]["contact_key"] == "tel:+442079460958"
    # the same two leftovers in both orders: the card's name either way
    w = wa("+44 20 7946 0958", "+44 20 7946 0958")
    c = card("Zed Quill", "+44 20 7946 0958")
    tel = m._chiave_telefono(w["phone"])
    base = m.merge_contacts_phase1(None, None, None, None, None, None, None)
    for pend in (
        [m._pendente("whatsapp", tel, w["phone"], w["name"], "", m._applica_whatsapp(w)),
         m._pendente("iphone", tel, c["phone_primary"], c["name"], "", m._applica_iphone(c))],
        [m._pendente("iphone", tel, c["phone_primary"], c["name"], "", m._applica_iphone(c)),
         m._pendente("whatsapp", tel, w["phone"], w["name"], "", m._applica_whatsapp(w))],
    ):
        m_sort = m._ordine_pendente
        m._ordine_pendente = lambda p: 0  # keep the order given, to reach the renaming path
        try:
            out = m.merge_phone_contacts(base.copy(), pend, stats())
        finally:
            m._ordine_pendente = m_sort
        assert len(out) == 1 and out.iloc[0]["name"] == "Zed Quill", out[["name", "contact_key"]]
    # a Telegram contact names a WhatsApp number the same way
    book = phase2([wa("+44 7700 900520", "+44 7700 900520")], [],
                  [plug("telegram", "Zoe Quill", "", "+44 7700 900520")])
    assert len(book) == 1 and book.iloc[0]["name"] == "Zoe Quill", book[["name"]]
    print("ok")
    """
    )
    _code(tmp_path, OWNER, code)


def test_company_cards_never_become_persons(tmp_path):
    code = _HARNESS + textwrap.dedent(
        """
    cards = [card("Fern Bakery", "+44 20 7946 0000", "", "Fern Bakery", kind="org"),
             card("Ada Lund", "+44 7700 900333", "ada@elm.example")]
    w = [wa("+44 20 7946 0000", "+44 20 7946 0000"),       # the bakery's number, unsaved
         wa("Fern Bakery", "+44 20 7946 0000")]             # or saved under the card's name
    book = phase2(w, cards, [])
    assert set(book["name"]) == {"Ada Lund"}, book[["name", "contact_key", "started_by"]]
    print("ok")
    """
    )
    _code(tmp_path, OWNER, code)


# --------------------------------------------------------------------------- end to end, real files


_LRE, _PDF = "‪", "‬"


def _address_book(tmp: Path, cards: str) -> Path:
    f = tmp / "home" / "Downloads" / "book.vcf"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(cards, encoding="utf-8")
    return f


def _contacts_l0_l1(tmp: Path, config: dict, vcf: Path) -> None:
    _ok(
        _run([TOOLS / "contacts" / "ct-l0-import.py", vcf, "--label", "phone"], tmp, config),
        "ct L0",
    )
    _ok(_run([TOOLS / "contacts" / "ct-l1-enrich.py"], tmp, config), "ct L1")


def _whatsapp_l0_l1(tmp: Path, config: dict, chats: dict[str, str]) -> None:
    raw = tmp / "data" / "whatsapp" / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    for name, text in chats.items():
        (raw / name).write_text(text, encoding="utf-8")
    wa = TOOLS / "whatsapp"
    _ok(_run([wa / "wa-l0l3-full.py", "--skip-analysis"], tmp, config), "wa L0")
    _ok(_run([wa / "wa-l1-enrich.py", "--incremental"], tmp, config), "wa L1")


def _book(tmp: Path) -> pd.DataFrame:
    return pd.read_parquet(tmp / "data" / "enriched" / "contacts-merged.parquet")


_CARDS = (
    "BEGIN:VCARD\nVERSION:3.0\nN:Varga;Ines;;;\nFN:Ines Varga\nTEL;TYPE=CELL:07700 900305\nEND:VCARD\n"
    "BEGIN:VCARD\nVERSION:3.0\nN:Marsh;Theo;;;\nFN:Theo Marsh\nORG:Dune Demo\n"
    "EMAIL;TYPE=INTERNET:theo@dune.example\nTEL;TYPE=CELL:+44 7700 900412\nEND:VCARD\n"
    "BEGIN:VCARD\nVERSION:3.0\nN:;;;;\nFN:Fern Bakery\nORG:Fern Bakery\n"
    "TEL;TYPE=WORK:+44 20 7946 0000\nX-ABShowAs:COMPANY\nEND:VCARD\n"
    "BEGIN:VCARD\nVERSION:4.0\nKIND:org\nFN:Gale Studio\nORG:Gale Studio\n"
    "TEL:+44 20 7946 0001\nEND:VCARD\n"
)
_CHATS = {
    "WhatsApp Chat with +44 7700 900412.txt": (
        "19/11/2026, 08:00 - +44 7700 900412: Hello Robin, Theo from the fair.\n"
        "19/11/2026, 08:05 - Robin Demo: Hi Theo, good to meet you.\n"
    ),
    "WhatsApp Chat with +44 7700 900305.txt": (
        "20/11/2026, 21:00 - +44 7700 900305: Thanks for the slides!\n"
        "20/11/2026, 21:02 - Robin Demo: Any time.\n"
    ),
}
_ROBIN = {
    "owner": "Robin Demo",
    "own_names": ["robin demo", "robin"],
    "own_emails": ["robin@example.com"],
    "phone_country_code": "44",
}


def test_whatsapp_then_address_book_end_to_end(tmp_path):
    config = {**_ROBIN, "enabled_sources": ["whatsapp", "contacts"]}
    # first the WhatsApp chats alone: two people keyed by phone
    _whatsapp_l0_l1(tmp_path, {**config, "enabled_sources": ["whatsapp"]}, _CHATS)
    _ok(_run([CS / "xs-l2-merge.py"], tmp_path, config), "merge 1")
    first = _book(tmp_path)
    assert sorted(first["contact_key"]) == ["tel:+447700900305", "tel:+447700900412"], first
    # then the address book arrives (a national number, a company card): the same two people,
    # Theo now keyed by his email with the card's name, Ines named by the card
    _contacts_l0_l1(tmp_path, config, _address_book(tmp_path, _CARDS))
    slot = pd.read_parquet(tmp_path / "data" / "contacts" / "contacts.parquet")
    assert dict(zip(slot["full_name"], slot["kind"], strict=True))["Fern Bakery"] == "org"
    assert dict(zip(slot["full_name"], slot["kind"], strict=True))["Gale Studio"] == "org"
    iph = pd.read_parquet(tmp_path / "data" / "contacts" / "processed" / "contacts-iphone.parquet")
    by = iph.set_index("name")
    assert by.loc["Ines Varga", "phone_primary"] == "+447700900305"  # the config key applied
    assert bool(by.loc["Fern Bakery", "is_business"]) and by.loc["Fern Bakery", "kind"] == "org"
    for run in (1, 2):
        out = _ok(_run([CS / "xs-l2-merge.py"], tmp_path, config), f"merge with the book {run}")
        book = _book(tmp_path).set_index("name")
        assert sorted(book.index) == ["Ines Varga", "Theo Marsh"], (out[-2000:], book)
        theo = book.loc["Theo Marsh"]
        assert theo["email"] == "theo@dune.example" and not theo["contact_key"]
        assert bool(theo["has_whatsapp"]) and bool(theo["has_iphone"])
        assert theo["organization"] == "Dune Demo" and theo["person_id"].startswith("p_")
        ines = book.loc["Ines Varga"]
        assert ines["contact_key"] == "tel:+447700900305" and bool(ines["has_iphone"])
        assert bool(ines["has_whatsapp"]) and ines["person_id"].startswith("p_")


def test_person_ids_without_any_email(tmp_path):
    config = {**_ROBIN, "enabled_sources": ["whatsapp"]}
    _whatsapp_l0_l1(tmp_path, config, _CHATS)
    ids = []
    for run in range(3):
        if run == 2:  # an entity map with no row for these people
            (tmp_path / "data" / "enriched" / "entity-map.json").write_text("{}", encoding="utf-8")
        _ok(_run([CS / "xs-l2-merge.py"], tmp_path, config), f"merge {run}")
        book = _book(tmp_path)
        assert book["person_id"].astype(str).str.startswith("p_").all(), book[["name", "person_id"]]
        ids.append(sorted(book["person_id"]))
    assert ids[0] == ids[1] == ids[2], ids
