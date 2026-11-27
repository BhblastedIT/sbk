"""Pipeline settings (<data root>/system/pipeline-settings.json): Drive limits, the guardian, Plaud, the noise
filter and the other thresholds, with their defaults and English names. Run it to print the settings in force.
"""

from __future__ import annotations

import dataclasses
import json
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sbk_config import DATA_ROOT, scrivi_atomico, user_cfg  # noqa: E402

FILE = DATA_ROOT / "system" / "impostazioni-pipeline.json"
# English file name. A new install reads and writes this one; an install that already has only the
# older Italian file keeps using it.
FILE_EN = DATA_ROOT / "system" / "pipeline-settings.json"

# English names for sections and keys. The file may use either spelling; the code keeps the
# Italian ones internally (leggi() always returns them), so callers do not change.
SEZIONI_EN = {
    "drive": "drive",
    "guardiano": "guardian",
    "plaud": "plaud",
    "rumore": "noise",
    "lettura": "reading",
    "spesa": "spend",
}
CHIAVI_EN = {
    ("drive", "tetto_ore"): "hours_per_attempt",
    ("drive", "giorni"): "days",
    ("drive", "max_mb"): "max_mb",
    ("drive", "max_mb_grandi"): "max_mb_large_folders",
    ("drive", "media"): "media",
    ("guardiano", "solo_pericolo"): "stop_only_for_danger",
    ("guardiano", "memoria_minima"): "min_memory_percent",
    ("plaud", "trascrivi"): "transcribe",
    ("plaud", "soglia_secondi"): "min_seconds",
    ("plaud", "minuti_giorno"): "minutes_per_day",
    ("rumore", "dubbi_contano"): "uncertain_count",
    ("rumore", "massa_conta"): "bulk_counts",
    ("lettura", "ore_attesa"): "hours_waiting",
    ("spesa", "margine_tetto"): "cap_margin_percent",
}


def _percorso() -> Path:
    return FILE if FILE.exists() and not FILE_EN.exists() else FILE_EN


def _da_italiano(sezione: str, chiave: str) -> tuple[str, str]:
    return SEZIONI_EN.get(sezione, sezione), CHIAVI_EN.get((sezione, chiave), chiave)


def _a_italiano(sezione: str, chiave: str) -> tuple[str, str]:
    """Accept a section/key in English or Italian, return the internal Italian pair."""
    sez = next((it for it, en in SEZIONI_EN.items() if sezione in (it, en)), sezione)
    chi = next(
        (it for (s, it), en in CHIAVI_EN.items() if s == sez and chiave in (it, en)), chiave
    )
    return sez, chi


@dataclass(frozen=True)
class Soglia:
    sezione: str
    chiave: str
    nome: str
    unita: str
    partenza: int | bool
    minimo: int | None = None
    massimo: int | None = None
    spiegazione: str = ""


SOGLIE: tuple[Soglia, ...] = (
    Soglia(
        "drive",
        "tetto_ore",
        "Time per attempt",
        "hours",
        8,
        1,
        24,
        "How much Drive can download in one attempt before stopping. There are three attempts, and "
        "the next one resumes from where it left off.",
    ),
    Soglia(
        "drive",
        "giorni",
        "Period",
        "days",
        365,
        0,
        3650,
        "Only files changed in the last few days; those already taken remain. 365, that is 12 months. "
        "Zero means the whole history.",
    ),
    Soglia(
        "drive",
        "max_mb",
        "Files up to",
        "MB",
        15,
        1,
        100,
        "Larger files are not downloaded. Raising it takes more disk space and more time.",
    ),

    Soglia(
        "drive",
        "max_mb_grandi",
        "Files up to, in your large shared drives",
        "MB",
        50,
        1,
        200,
        "Size limit for the shared drives you list in sbk.config.json (gdrive.large_shared_drives), "
        "where files are heavier. Without that list it is not used.",
    ),
    Soglia(
        "drive",
        "media",
        "Photos, video and audio",
        "",
        False,
        spiegazione="Off, Drive photos, video and audio are not downloaded. On, they are downloaded, within "
        "the maximum size.",
    ),



    Soglia(
        "guardiano",
        "solo_pericolo",
        "Stop only for danger",
        "",
        True,
        spiegazione="On, the guardian lets a step run even beyond its budget and stops it only when the "
        "Mac's memory is in danger. Off, it shuts it down as soon as it exceeds one and a half times the "
        "budget, even when the Mac is calm.",
    ),
    Soglia(
        "guardiano",
        "memoria_minima",
        "Pipeline memory when the Mac is calm",
        "%",
        20,
        2,
        60,
        "When the Mac's memory is calm, a pipeline step gets at least this share of the RAM, even if "
        "the other apps hold a lot of it. macOS compresses the idle ones to make room. When the memory heats up, "
        "the normal split returns.",
    ),


    Soglia(
        "plaud",
        "trascrivi",
        "Ask Plaud for the missing transcriptions",
        "",
        True,
        spiegazione="On, on each pass the recordings without a transcription are sent to Plaud for transcription, like when "
        "you click «Auto generation» in the app, and they are downloaded as soon as they are ready. Plaud also provides its title and "
        "summary. Off, they stay without.",
    ),
    Soglia(
        "plaud",
        "soglia_secondi",
        "Minimum duration",
        "seconds",
        40,
        0,
        600,
        "Shorter recordings are not requested. 40 seconds.",
    ),
    Soglia(
        "plaud",
        "minuti_giorno",
        "Minutes requested per day",
        "minutes",
        1200,
        0,
        1440,
        "How many minutes of audio are requested from Plaud in a day. Set it according to your Plaud plan.",
    ),



    Soglia(
        "rumore",
        "dubbi_contano",
        "People who never heard from you count",
        "",
        True,
        spiegazione="On, the scores also count people who write to you without you ever replying, people only in "
        "copy, and the colleagues of your contacts, as before. Off, they do not count until you reply.",
    ),
    Soglia(
        "rumore",
        "massa_conta",
        "Bulk emails from people you know count",
        "",
        True,
        spiegazione="On, a newsletter or a list from someone you have a relationship with counts as one of their emails, "
        "as before. Off, that email does not count and the relationship remains.",
    ),



    Soglia(
        "lettura",
        "ore_attesa",
        "New data waiting",
        "hours",
        24,
        1,
        168,
        "After how many hours new data waiting to be re-read turns orange. Before that it stays grey, labelled "
        "«To re-read».",
    ),



    Soglia(
        "spesa",
        "margine_tetto",
        "Margin on the spending cap",
        "percent",
        25,
        0,
        300,
        "How much a paid batch can exceed the estimate you saw before starting. Beyond that, the batch does not start and "
        "spends nothing. The run's download brings new documents, which is why a bit of margin is needed.",
    ),


)

_PER_CHIAVE = {(s.sezione, s.chiave): s for s in SOGLIE}


def _valida(s: Soglia, v) -> bool:
    if isinstance(s.partenza, bool):
        return isinstance(v, bool)
    if isinstance(v, bool) or not isinstance(v, int):
        return False
    return (s.minimo is None or v >= s.minimo) and (s.massimo is None or v <= s.massimo)


def _scritto() -> dict:
    try:
        d = json.loads(_percorso().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def leggi() -> dict[str, dict]:
    ""
    scritto = _scritto()
    out: dict[str, dict] = {}
    for s in SOGLIE:
        v = _valore_scritto(scritto, s)
        out.setdefault(s.sezione, {})[s.chiave] = v if _valida(s, v) else s.partenza
    return out


def _valore_scritto(scritto: dict, s: Soglia):
    """The value in the file under the English or the Italian name (English wins), else the default."""
    sez_en, chi_en = _da_italiano(s.sezione, s.chiave)
    for sez, chi in ((sez_en, chi_en), (sez_en, s.chiave), (s.sezione, chi_en), (s.sezione, s.chiave)):
        blocco = scritto.get(sez)
        if isinstance(blocco, dict) and chi in blocco:
            return blocco[chi]
    return s.partenza


def imposta(sezione: str, chiave: str, valore) -> tuple[bool, str]:
    ""
    sezione, chiave = _a_italiano(sezione, chiave)
    s = _PER_CHIAVE.get((sezione, chiave))
    if s is None:
        return False, f"Unknown threshold {sezione}.{chiave}."
    if not _valida(s, valore):
        if isinstance(s.partenza, bool):
            return False, f"{s.nome} is on or off."
        return False, f"{s.nome} ranges from {s.minimo} to {s.massimo} {s.unita}.".replace("  ", " ")
    scritto = _scritto()
    # Write under the spelling the file already uses for this setting, English by default for a
    # setting not written yet in the English file.
    sez_en, chi_en = _da_italiano(sezione, chiave)
    dove = (sez_en, chi_en) if _percorso() == FILE_EN else (sezione, chiave)
    for sez, chi in ((sez_en, chi_en), (sez_en, chiave), (sezione, chi_en), (sezione, chiave)):
        if isinstance(scritto.get(sez), dict) and chi in scritto[sez]:
            dove = (sez, chi)
            break
    scritto.setdefault(dove[0], {})[dove[1]] = valore
    scritto["aggiornato"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    scritto["da"] = "SBK"
    percorso = _percorso()
    percorso.parent.mkdir(parents=True, exist_ok=True)
    scrivi_atomico(percorso, json.dumps(scritto, ensure_ascii=False, indent=1))
    return True, ""


def descrivi(sezione: str | None = None) -> list[dict]:
    ""
    vigore = leggi()
    return [
        {
            "sezione": s.sezione,
            "chiave": s.chiave,
            "section": _da_italiano(s.sezione, s.chiave)[0],
            "key": _da_italiano(s.sezione, s.chiave)[1],

            "tipo": "acceso" if isinstance(s.partenza, bool) else "numero",
            "nome": s.nome,
            "unita": s.unita,
            "valore": vigore[s.sezione][s.chiave],
            "partenza": s.partenza,
            "minimo": s.minimo,
            "massimo": s.massimo,
            "spiegazione": s.spiegazione,
            "cambiata": vigore[s.sezione][s.chiave] != s.partenza,
        }
        for s in SOGLIE
        if sezione is None or s.sezione == sezione
    ]


def large_shared_drives() -> list[str]:
    """Names of your shared drives with heavier files (sbk.config.json gdrive.large_shared_drives)."""
    nomi = user_cfg("gdrive.large_shared_drives", [])
    if isinstance(nomi, str):
        nomi = [nomi]
    return [str(n).strip() for n in (nomi or []) if str(n).strip()]


def frase(sezione: str) -> str:
    ""
    v = leggi()[sezione]
    if sezione == "drive":
        if v["giorni"] == 0:
            periodo = "the whole history"
        elif v["giorni"] % 365 == 0:
            periodo = f"the last {v['giorni'] // 365 * 12} months"
        else:
            periodo = f"the last {v['giorni']} days"
        media = "with photos, video and audio" if v["media"] else "without photos, video and audio"
        grandi = large_shared_drives()
        nei_grandi = f" ({v['max_mb_grandi']} in {', '.join(grandi)})" if grandi else ""
        return (
            f"{v['tetto_ore']} hours per attempt, {periodo}, files up to {v['max_mb']} MB"
            f"{nei_grandi}, {media}"
        )
    if sezione == "guardiano":
        modo = (
            "stops a step only for danger"
            if v["solo_pericolo"]
            else "stops a step beyond one and a half times the budget"
        )
        return f"{modo}, at least {v['memoria_minima']}% of the RAM to the pipeline when the Mac is calm"
    if sezione == "rumore":
        dubbi = "count" if v["dubbi_contano"] else "do not count until you reply"
        massa = "counts" if v["massa_conta"] else "does not count"
        return (
            f"noise never weighs, uncertain cases {dubbi}, bulk email from people you know {massa}"
        )
    if sezione == "lettura":
        return f"new data turns orange after {v['ore_attesa']} hours without a re-read"
    if sezione == "plaud":
        if not v["trascrivi"]:
            return "the missing transcriptions are not requested from Plaud"
        return (
            f"the missing transcriptions are requested from Plaud, from {v['soglia_secondi']} seconds up, "
            f"up to {v['minuti_giorno']} minutes a day"
        )
    return ", ".join(f"{k} {x}" for k, x in v.items())


def _argomenti_drive(args: tuple[str, ...], d: dict) -> tuple[str, ...]:
    ""
    out: list[str] = []
    salta = False
    for i, a in enumerate(args):
        if salta:
            salta = False
            continue
        if a in ("--days", "--max-size-mb", "--max-size-mb-large", "--max-size-mb-grandi"):
            salta = i + 1 < len(args)
            continue
        if a == "--include-media":
            continue
        out.append(a)
    out += ["--days", str(d["giorni"]), "--max-size-mb", str(d["max_mb"])]
    out += ["--max-size-mb-large", str(d["max_mb_grandi"])]
    if d["media"]:
        out.append("--include-media")
    return tuple(out)


def applica_al_piano(piano) -> list:
    ""
    d = leggi()["drive"]
    out = []
    for p in piano:
        if getattr(p, "sorgente", None) == "gdrive":
            p = dataclasses.replace(
                p, args=_argomenti_drive(tuple(p.args), d), timeout_s=d["tetto_ore"] * 3600
            )
        out.append(p)
    return out


if __name__ == "__main__":
    import argparse

    argparse.ArgumentParser(
        description=(
            "Print the pipeline settings in force (<data root>/system/pipeline-settings.json, or the "
            "older impostazioni-pipeline.json), with their English names, defaults and older names."
        )
    ).parse_args()
    print(f"Settings file: {_percorso()}")
    for r in descrivi():
        segno = "changed" if r["cambiata"] else "default"
        nome = f"{r['section']}.{r['key']}"
        print(
            f"{nome:<32} {r['valore']!s:>6} {r['unita']:<7} ({segno}, default {r['partenza']})"
            f"  [older name {r['sezione']}.{r['chiave']}]"
        )
