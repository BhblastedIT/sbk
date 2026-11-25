""











from __future__ import annotations

import json
import logging
import re
from pathlib import Path

import jellyfish
from rapidfuzz import fuzz

log = logging.getLogger("sbk.name-variants")





NAME_VARIANTS: dict[str, list[str]] = {

    "Leopoldo": ["Poldo", "Dino", "Leo"],
    "Giuseppe": ["Beppe", "Peppe", "Pino", "Bepi", "Pinuccio"],
    "Giovanni": ["Gianni", "Nino", "Gianno", "Vanni"],
    "Francesco": ["Franco", "Checco", "Ciccio", "Franz"],
    "Alessandro": ["Ale", "Alex", "Sandro"],
    "Antonio": ["Toni", "Tonino", "Nino", "Totò"],
    "Roberto": ["Roby", "Rob", "Berto"],
    "Marco": ["Marc"],
    "Andrea": ["Andre"],
    "Vincenzo": ["Enzo", "Cenzo", "Vincè"],
    "Lorenzo": ["Enzo", "Renzo", "Lollo"],
    "Domenico": ["Mimmo", "Nico", "Menico"],
    "Raffaele": ["Lello", "Raffa", "Raff"],
    "Pasquale": ["Lino", "Pascale"],
    "Giammarco": ["Gianmarco"],
    "Massimiliano": ["Max", "Massi"],
    "Massimo": ["Max"],
    "Stefano": ["Stefy", "Steve"],
    "Cristiano": ["Cristian", "Chris"],
    "Federico": ["Fede", "Fred", "Rico"],
    "Matteo": ["Matt", "Teo"],
    "Mattia": ["Matt", "Tia"],
    "Luca": ["Luke"],
    "Nicola": ["Nico", "Nick", "Nicky"],
    "Simone": ["Simo"],
    "Riccardo": ["Ricky", "Rick", "Ric"],
    "Davide": ["Dave", "David"],
    "Emanuele": ["Manu", "Manuel", "Lele"],
    "Gabriele": ["Gabri", "Gab", "Gabriel"],
    "Filippo": ["Pippo", "Phil", "Filip"],
    "Leonardo": ["Leo", "Nardo"],
    "Edoardo": ["Edo", "Edward", "Ed"],
    "Giacomo": ["Jack", "James"],
    "Michele": ["Miky", "Mike", "Michel"],
    "Alberto": ["Albi", "Berto", "Al"],
    "Daniele": ["Dani", "Dan", "Daniel"],
    "Claudio": ["Cloud"],
    "Fabio": ["Fab"],
    "Paolo": ["Paul"],
    "Pietro": ["Peter", "Piero"],
    "Luigi": ["Gigi", "Lou", "Louis"],
    "Enrico": ["Rico", "Henry", "Henr"],
    "Carlo": ["Carletto", "Charles"],
    "Giorgio": ["George", "Giò"],
    "Guglielmo": ["William", "Will", "Willy"],
    "Tommaso": ["Tommy", "Tom", "Thomas"],
    "Umberto": ["Berto", "Bert"],
    "Vittorio": ["Vito", "Victor"],
    "Angelo": ["Lino", "Angel"],
    "Sergio": ["Serge"],
    "Carmelo": ["Melo", "Carmè"],
    "Gennaro": ["Rino", "Genny"],
    "Rosario": ["Saro"],
    "Calogero": ["Lillo"],
    "Benedetto": ["Benny", "Ben"],
    "Gioacchino": ["Gioac"],
    "Agostino": ["Ago", "Gus"],
    "Cosimo": ["Cosmo"],
    "Gaetano": ["Tano", "Guy"],
    "Maurizio": ["Mauri", "Maurice"],
    "Eugenio": ["Gene", "Eugene"],
    "Ernesto": ["Ernest", "Ernie"],
    "Sebastiano": ["Seby", "Sebastian", "Bastiano"],
    "Corrado": ["Corry"],
    "Alfredo": ["Alf", "Fred", "Alfred"],
    "Bernardo": ["Bernie", "Bernard"],
    "Donato": ["Dona"],
    "Fernando": ["Ferdi", "Nando"],
    "Gerardo": ["Gerry", "Gerard"],
    "Ignazio": ["Nazio"],
    "Marcello": ["Marc", "Marcel"],
    "Nunzio": ["Nunz"],
    "Orazio": ["Razio"],
    "Renato": ["Rena"],

    "Elisabetta": ["Lisa", "Betta", "Betty", "Elisa", "Beth"],
    "Elena": ["Eleni", "Helen", "Helena", "Lena", "Hella", "Ella"],
    "Francesca": ["Franca", "Fran", "Chicca"],
    "Alessandra": ["Ale", "Alex", "Sandra", "Alessia"],
    "Giovanna": ["Gianna", "Vanna", "Nina"],
    "Maria": ["Mary", "Mariella", "Mariuccia"],
    "Giulia": ["Julia", "Julie"],
    "Valentina": ["Vale", "Tina"],
    "Roberta": ["Roby", "Berta"],
    "Cristina": ["Cris", "Chris", "Tina", "Christina"],
    "Federica": ["Fede", "Rica", "Frederica"],
    "Chiara": ["Clara", "Claire", "Kiara"],
    "Paola": ["Paula"],
    "Laura": ["Lauretta"],
    "Silvia": ["Sylvia"],
    "Daniela": ["Dani", "Dana", "Daniella"],
    "Caterina": ["Kate", "Katia", "Catherine", "Cathy"],
    "Beatrice": ["Bea", "Trice"],
    "Margherita": ["Rita", "Maggie", "Margaret", "Margot"],
    "Teresa": ["Tere", "Theresa"],
    "Rosa": ["Rosetta", "Rose", "Rosina"],
    "Anna": ["Annie", "Anne", "Annetta"],
    "Antonella": ["Nella", "Toni"],
    "Patrizia": ["Patty", "Pat", "Patricia"],
    "Monica": ["Moni", "Monique"],
    "Luisa": ["Louise", "Luisella"],
    "Carla": ["Carlotta", "Charlotte"],
    "Lucia": ["Lucy", "Lucie"],
    "Giuseppina": ["Pina", "Giusy", "Josephine"],
    "Concetta": ["Concy", "Concettina"],

    "Ioannis": ["Yannis", "Giannis", "John", "Giovanni", "Yiannis"],
    "Aikaterini": ["Katerina", "Katia", "Catherine", "Kate"],
    "Konstantinos": ["Kostas", "Constantine", "Costantino", "Gus"],
    "Nikolaos": ["Nikos", "Nicholas", "Nicola"],
    "Dimitrios": ["Dimitris", "Jim", "Demetrio"],
    "Georgios": ["Giorgos", "George", "Giorgio"],
    "Panagiotis": ["Panos", "Takis"],
    "Athanasios": ["Thanasis", "Nassos"],
    "Eleftheria": ["Efthi", "Liberty"],
    "Eleni": ["Elena", "Lena"],

    "Nataliya": ["Natalia", "Natasha", "Nat"],
    "Aleksandr": ["Alexander", "Alex", "Sasha", "Alessandro"],
    "Dmitri": ["Dima", "Dimitri", "Dmitry"],
    "Natalia": ["Natasha", "Natalya", "Natalie"],
    "Ekaterina": ["Katya", "Kate", "Catherine", "Katia"],
    "Mikhail": ["Misha", "Michael", "Michele"],
    "Vladimir": ["Vlad", "Vova", "Volodya"],
    "Sergei": ["Seryozha", "Serge", "Sergio"],
    "Anastasia": ["Nastya", "Ana", "Stasia"],
    "Svetlana": ["Sveta", "Lana"],
    "Tatiana": ["Tanya", "Tania"],
    "Olga": ["Olya"],
    "Ivan": ["Vanya", "John", "Giovanni"],
    "Boris": ["Borya"],
    "Andrei": ["Andrey", "Andrew", "Andrea"],

    "Francisco": ["Paco", "Pancho", "Frank", "Francis", "Franz"],
    "Alejandro": ["Alex", "Alejo", "Alessandro"],
    "José": ["Pepe", "Jose", "Joseph", "Giuseppe"],
    "Carlos": ["Carlo", "Charles"],
    "Guillermo": ["Willy", "William", "Guglielmo"],
    "Rafael": ["Rafa", "Raffaele", "Ralph"],
    "Javier": ["Javi", "Xavier"],
    "Ignacio": ["Nacho", "Ignazio"],
    "Manuel": ["Manu", "Manolo", "Emanuele"],

    "Wilhelmus": ["Wim", "Willy", "William", "Willem"],
    "Johannes": ["Jan", "Hans", "John", "Giovanni"],
    "Friedrich": ["Fritz", "Fred", "Federico"],
    "Heinrich": ["Heinz", "Henry", "Enrico"],
    "Maximilian": ["Max", "Massimiliano"],
}




ITALIAN_COMMON_SUFFIXES = frozenset(
    {
        "ini",
        "ino",
        "ina",
        "elli",
        "ella",
        "ello",
        "etti",
        "etto",
        "etta",
        "ucci",
        "uccio",
        "uccia",
        "acci",
        "accio",
        "accia",
        "one",
        "oni",
        "otti",
        "otto",
        "otta",
    }
)


TOP_SURNAMES = frozenset(
    {
        "rossi",
        "russo",
        "ferrari",
        "esposito",
        "bianchi",
        "romano",
        "colombo",
        "ricci",
        "marino",
        "greco",
        "bruno",
        "gallo",
        "conti",
        "costa",
        "giordano",
        "mancini",
        "rizzo",
        "lombardi",
        "moretti",
        "barbieri",
        "fontana",
        "santoro",
        "mariani",
        "rinaldi",
        "caruso",
        "ferrara",
        "galli",
        "martini",
        "leone",
        "longo",
        "gentile",
        "martinelli",
        "vitale",
        "lombardo",
        "serra",
        "coppola",
        "de luca",
        "damico",
        "marchetti",
        "parisi",
        "villa",
        "conte",
        "ferraro",
        "ferri",
        "fabbri",
        "bianco",
        "marini",
        "grasso",
        "valentini",
        "messina",
        "sala",
        "amato",
        "pellegrini",
        "palumbo",
        "sanna",
        "farina",
        "rizzi",
        "monti",
        "cattaneo",
        "moroni",
        "alberti",
        "guerra",
        "bernardi",
        "fiore",
        "de santis",
        "donati",
        "benedetti",
        "ruggiero",
        "caputo",
        "montanari",
        "neri",
        "grassi",
        "carbone",
        "testa",
        "ferrari",
        "damato",
        "palmieri",
        "sartori",
        "basile",
        "pugliese",
        "sorrentino",
        "dangelo",
        "silvestri",
        "pagano",
        "de rosa",
        "palermo",
        "gatti",
        "cattani",
        "orlando",
        "riva",
    }
)

MIN_NAME_LENGTH_FOR_FUZZY = 5





class NameEquivalenceDB:
    ""

    def __init__(
        self,
        clusters: dict[str, list[str]] | None = None,
        learned_path: Path | None = None,
    ):
        self._clusters: dict[str, list[str]] = dict(clusters or NAME_VARIANTS)
        self._reverse: dict[str, list[str]] = {}
        self._canonical_set: set[str] = set()
        self._learned_path = learned_path
        self._learned_merges: dict[str, list[str]] = {}
        self._learned_rejects: list[tuple[str, str]] = []

        if learned_path:
            self._load_learned(learned_path)

        self._build_reverse_index()

    def _build_reverse_index(self):
        ""
        self._reverse.clear()
        self._canonical_set.clear()


        all_clusters = dict(self._clusters)
        for canon, variants in self._learned_merges.items():
            existing = all_clusters.get(canon, [])
            merged = list(set(existing + variants))
            all_clusters[canon] = merged

        for canonical, variants in all_clusters.items():
            c_lower = canonical.lower()
            self._canonical_set.add(c_lower)

            self._reverse.setdefault(c_lower, []).append(c_lower)
            for v in variants:
                v_lower = v.lower()
                if v_lower not in self._reverse:
                    self._reverse[v_lower] = []
                if c_lower not in self._reverse[v_lower]:
                    self._reverse[v_lower].append(c_lower)

    def _load_learned(self, path: Path):
        ""
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text())
            self._learned_merges = data.get("merges", {})
            self._learned_rejects = [tuple(r) for r in data.get("rejects", [])]
        except Exception as e:
            log.warning("Failed to load learned variants from %s: %s", path, e)

    def _save_learned(self):
        ""
        if not self._learned_path:
            return
        data = {
            "merges": self._learned_merges,
            "rejects": [list(r) for r in self._learned_rejects],
        }
        self._learned_path.parent.mkdir(parents=True, exist_ok=True)
        self._learned_path.write_text(json.dumps(data, indent=2, ensure_ascii=False))

    def get_variants(self, name: str) -> set[str]:
        ""
        n_lower = name.strip().lower()
        canonicals = self._reverse.get(n_lower, [])
        result: set[str] = set()
        for canon in canonicals:

            result.add(canon)

            for c, variants in self._clusters.items():
                if c.lower() == canon:
                    for v in variants:
                        result.add(v.lower())
            for c, variants in self._learned_merges.items():
                if c.lower() == canon:
                    for v in variants:
                        result.add(v.lower())
        result.discard(n_lower)
        return result

    def are_equivalent(self, a: str, b: str) -> bool:
        ""
        a_lower = a.strip().lower()
        b_lower = b.strip().lower()
        if a_lower == b_lower:
            return True


        for r1, r2 in self._learned_rejects:
            if {a_lower, b_lower} == {r1.lower(), r2.lower()}:
                return False

        canonicals_a = set(self._reverse.get(a_lower, []))
        canonicals_b = set(self._reverse.get(b_lower, []))
        return bool(canonicals_a & canonicals_b)

    def get_canonical(self, name: str) -> list[str]:
        ""
        n_lower = name.strip().lower()
        canonicals = self._reverse.get(n_lower, [])
        if not canonicals:
            return [name]
        return [c.title() for c in canonicals]

    def get_variants_for_search(self, name: str) -> set[str]:
        ""
        variants = self.get_variants(name)
        variants.add(name.strip().lower())
        return variants

    def learn_from_merge(self, name_a: str, name_b: str):
        ""
        a_lower = name_a.strip().lower()
        b_lower = name_b.strip().lower()
        if a_lower == b_lower:
            return


        if len(a_lower) >= len(b_lower):
            canon, variant = name_a.strip(), name_b.strip()
        else:
            canon, variant = name_b.strip(), name_a.strip()

        if canon not in self._learned_merges:
            self._learned_merges[canon] = []
        if variant.lower() not in [v.lower() for v in self._learned_merges[canon]]:
            self._learned_merges[canon].append(variant)
            self._build_reverse_index()
            self._save_learned()
            log.info("Learned name variant: %s -> %s", variant, canon)

    def learn_from_reject(self, name_a: str, name_b: str):
        ""
        pair = (name_a.strip().lower(), name_b.strip().lower())
        if pair not in self._learned_rejects and (pair[1], pair[0]) not in self._learned_rejects:
            self._learned_rejects.append(pair)
            self._save_learned()
            log.info("Learned reject: %s != %s", name_a, name_b)





def learn_from_email(display_name: str, email: str) -> tuple[str, str] | None:
    ""



    if not display_name or not email or "@" not in email:
        return None
    local = email.split("@")[0].lower()

    local = re.sub(r"\d+", "", local)
    local = local.replace(".", " ").replace("-", " ").replace("_", " ").strip()
    local_parts = [p for p in local.split() if len(p) >= 2]
    if not local_parts:
        return None

    display_parts = display_name.strip().lower().split()
    if not display_parts:
        return None

    first_display = display_parts[0]
    first_email = local_parts[0]


    if first_display != first_email and len(first_display) >= 2 and len(first_email) >= 3:

        if len(display_parts) >= 2 and len(local_parts) >= 2:
            if display_parts[-1] == local_parts[-1]:
                return (first_display.title(), first_email.title())
        elif len(display_parts) == 1 and len(local_parts) >= 2:

            return (first_display.title(), first_email.title())

    return None





def build_metaphone_index(names: list[str]) -> dict[str, list[str]]:
    ""
    index: dict[str, list[str]] = {}
    for name in names:
        code = jellyfish.metaphone(name.strip())
        if code:
            index.setdefault(code, []).append(name)
    return index


def phonetic_confidence(name_a: str, name_b: str) -> float:
    ""
    code_a = jellyfish.metaphone(name_a.strip())
    code_b = jellyfish.metaphone(name_b.strip())
    if not code_a or not code_b:
        return 0.0
    if code_a != code_b:
        return 0.0

    ed = jellyfish.levenshtein_distance(name_a.strip().lower(), name_b.strip().lower())
    if ed <= 1:
        return 0.85
    elif ed <= 3:
        return 0.72
    return 0.0





def shared_token_guard(name_a: str, name_b: str) -> bool:
    ""
    tokens_a = set(name_a.lower().split())
    tokens_b = set(name_b.lower().split())
    return bool(tokens_a & tokens_b)


def first_name_jw_guard(first_a: str, first_b: str) -> bool:
    ""
    if not first_a or not first_b:
        return False
    jw = jellyfish.jaro_winkler_similarity(first_a.lower(), first_b.lower())
    return jw >= 0.72


def surname_length_guard(surname_a: str, surname_b: str) -> float:
    ""
    if not surname_a or not surname_b:
        return 0.0
    len_a, len_b = len(surname_a), len(surname_b)
    max_len = max(len_a, len_b)
    if max_len == 0:
        return 0.0
    ratio = abs(len_a - len_b) / max_len
    if ratio > 0.15:
        return ratio
    return 0.0


def common_surname_guard(surname: str) -> bool:
    ""
    return surname.lower().strip() in TOP_SURNAMES


def suffix_false_positive_guard(name_a: str, name_b: str) -> bool:
    ""
    a_lower = name_a.lower().strip()
    b_lower = name_b.lower().strip()
    for sfx in ITALIAN_COMMON_SUFFIXES:
        if a_lower.endswith(sfx) and b_lower.endswith(sfx):
            base_a = a_lower[: -len(sfx)]
            base_b = b_lower[: -len(sfx)]
            if base_a and base_b and fuzz.ratio(base_a, base_b) < 60:
                return False
    return True


def short_name_guard(name: str) -> bool:
    ""
    return len(name.strip()) < MIN_NAME_LENGTH_FOR_FUZZY





class NameMatchConfidence:
    KNOWN_VARIANT = 0.95
    FUZZY_HIGH = 0.80
    FUZZY_MED = 0.65
    REVIEW = 0.50
    REJECTED = 0.0


def match_name_v2(
    name_a: str,
    name_b: str,
    lookup_db: NameEquivalenceDB | None = None,
) -> float:
    ""



    a_parts = name_a.strip().lower().split()
    b_parts = name_b.strip().lower().split()

    if not a_parts or not b_parts:
        return NameMatchConfidence.REJECTED

    first_a = a_parts[0]
    first_b = b_parts[0]
    last_a = a_parts[-1] if len(a_parts) >= 2 else ""
    last_b = b_parts[-1] if len(b_parts) >= 2 else ""


    if lookup_db and lookup_db.are_equivalent(first_a, first_b):

        if last_a and last_b:
            jw_last = jellyfish.jaro_winkler_similarity(last_a, last_b)
            if jw_last >= 0.85:
                return NameMatchConfidence.KNOWN_VARIANT
            elif jw_last >= 0.70:
                return NameMatchConfidence.FUZZY_HIGH
        elif not last_a and not last_b:

            return NameMatchConfidence.KNOWN_VARIANT
        return NameMatchConfidence.REVIEW


    if len(a_parts) >= 2 and len(b_parts) >= 2:
        if not shared_token_guard(name_a, name_b):

            pc = phonetic_confidence(first_a, first_b)
            if pc == 0.0:
                return NameMatchConfidence.REJECTED

    if not suffix_false_positive_guard(first_a, first_b):
        return NameMatchConfidence.REJECTED


    if short_name_guard(first_a) or short_name_guard(first_b):
        if first_a != first_b:
            return NameMatchConfidence.REJECTED


    jw_first = jellyfish.jaro_winkler_similarity(first_a, first_b)
    if jw_first < 0.72:
        return NameMatchConfidence.REJECTED

    jw_last = 1.0
    if last_a and last_b:
        jw_last = jellyfish.jaro_winkler_similarity(last_a, last_b)

    composite = 0.40 * jw_first + 0.60 * jw_last


    if composite >= 0.92:
        return NameMatchConfidence.FUZZY_HIGH
    elif composite >= 0.80:
        return NameMatchConfidence.FUZZY_MED
    return NameMatchConfidence.REVIEW
