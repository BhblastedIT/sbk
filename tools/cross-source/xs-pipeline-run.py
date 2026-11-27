#!/usr/bin/env python3
"""Pipeline runner: runs the L1, L2 and L3 stages in order with checkpoints, change detection, a failure queue and
metrics. --ingest rereads the sources on disk up to the knowledge base without paid stages, --propagate and
--rebuild run L2+L3 only, --all runs the whole chain and asks before any paid stage (--allow-spend or
SBK_ALLOW_SPEND gives consent up front). --dry-run prints the plan.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))
_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

from sbk_config import (
    DATA_ROOT,
    ENABLED_SOURCES,
    ENRICHED_DIR,
    KB_SILENZIO_GIORNI,
    KNOWLEDGE_LAST_EXTRACTION_FILE,
    acquire_pid_lock,
    kb_giorni_di_silenzio,
    release_pid_lock,
    safe_write_json,
    source_enabled,
    source_listed,
)

log = logging.getLogger("sbk-pipeline")


# L1 stages that belong to a source with another name (for enabled_sources).
_FONTE_DELLO_STADIO = {
    "personio_assenze": "personio",
    "email_allegati": "email",
    "docusign_pdf": "docusign",
    "wa_extract_docs": "whatsapp",
    "wa_extract_photos": "whatsapp",
    "l1_speaker_analysis": "plaud",
    "plaud_speakers": "plaud",
    "github_intake": "github",
}

# Plugins that write into the kernel's mail and calendar slots: listing one of them in
# enabled_sources also keeps the email and calendar stages (these two only, not
# email_allegati, which reads Gmail mailboxes) that read their files.
_ANCHE_PER = {
    "email": ("microsoft365", "imap-caldav"),
    "calendar": ("microsoft365", "imap-caldav"),
}


# Sources whose L1 runs only when enabled_sources names them: an empty list does not switch
# them on. chatgpt is closed in the registry (replaced by the ai-history source); its L1 stays
# for whoever imported a ChatGPT export and lists "chatgpt".
_SOLO_SE_ELENCATE = frozenset({"chatgpt"})


def _solo_abilitate(scripts: dict, saltate: set[str]) -> dict:
    """Keep the L1 stages of the sources in sbk.config.json enabled_sources.

    Empty or missing enabled_sources = every stage (the behaviour before the
    field was read), except the sources in _SOLO_SE_ELENCATE, which need to be
    listed. The names left out go into `saltate`, for the log.
    """
    tenute = {}
    for k, v in scripts.items():
        fonte = _FONTE_DELLO_STADIO.get(k, k)
        if fonte in _SOLO_SE_ELENCATE:
            tenuta = source_listed(fonte)
        else:
            tenuta = source_enabled(fonte) or any(
                source_enabled(p) for p in _ANCHE_PER.get(k, ())
            )
        if tenuta:
            tenute[k] = v
        else:
            saltate.add(_FONTE_DELLO_STADIO.get(k, k))
    return tenute


def _fasi_fuori_elenco(
    prima: dict[str, set[str]], pre: dict, base: dict, dep: dict, wa: dict
) -> list[str]:
    """The L1 phase ids that had scripts but kept none because of enabled_sources."""
    fuori: list[str] = []
    for chiave, fase in (("personio", "l1_personio"), ("personio_assenze", "l1_personio_assenze")):
        if chiave in prima["pre"] and chiave not in pre:
            fuori.append(fase)
    if prima["base"] and not base:
        fuori.append("l1_phase1")
    if "plaud" in prima["dep"] and "plaud" not in dep:
        fuori.append("l1_speaker_analysis")
    if prima["dep"] and not dep:
        fuori.append("l1_phase2")
    if prima.get("wa") and not wa:
        fuori.append("l1_phase3_wa_deep")
    return fuori


def _non_ancora_scaricata(stadio: str) -> bool:
    """True when the source of this L1 stage has no folder under the data root yet."""
    return not _l0_dir(_FONTE_DELLO_STADIO.get(stadio, stadio)).exists()


def _togli_mai_scaricate(scripts: dict) -> tuple[dict, list[str]]:
    """Split off the L1 stages whose source was never downloaded or imported (no folder)."""
    via = sorted(k for k in scripts if _non_ancora_scaricata(k))
    return {k: v for k, v in scripts.items() if k not in via}, via


def _rubrica_con_persone() -> bool:
    """True when contacts-merged.parquet exists and has at least one row.

    A book with 0 rows (a first install whose sources only enrich people, LinkedIn alone for
    example) counts as no book: the stages after the merge have nobody to read.
    """
    path = ENRICHED_DIR / "contacts-merged.parquet"
    if not path.exists():
        return False
    try:
        import pyarrow.parquet as pq

        return pq.ParquetFile(path).metadata.num_rows > 0
    except Exception:  # noqa: BLE001 — unreadable: the stages after the merge say why
        return True



SCRIPTS = {
    "l2_merge": _THIS_DIR / "xs-l2-merge.py",
    "l2_entity_map_cleanup": _THIS_DIR / "xs-l2-entity-map-cleanup.py",
    "l2_entity_resolve": _THIS_DIR / "xs-l2-entity-resolve.py",
    "l2_entity_boost": _THIS_DIR / "xs-l2-entity-boost.py",
    "l2_duckdb": _THIS_DIR / "xs-l2-duckdb-setup.py",
    "l2_sqi": _THIS_DIR / "xs-l2-signal-quality.py",
    "l2_attachment_discovery": _THIS_DIR / "xs-l2-attachment-discovery.py",
    "l2_person_deep_context": _THIS_DIR / "xs-l2-person-deep-context.py",


    "l1_inventario": _THIS_DIR / "xs-l1-inventario.py",
    "l2_knowledge_extract": _THIS_DIR / "xs-l2-knowledge-extract.py",


    "l2_ricorrenze": _THIS_DIR / "xs-l2-birthdays.py",
    "l3_calendario_ricorrenze": _THIS_DIR / "xs-l3-birthday-calendar.py",




    "l2_episodes": _THIS_DIR / "xs-l2-episodes.py",
    "l2_calendar_episodes": _THIS_DIR / "xs-l2-calendar-episodes.py",
    "l2_email_participants": _THIS_DIR / "xs-l2-email-participants.py",
    "l2_knows": _THIS_DIR / "xs-l2-knows.py",
    "l3_subject_index": _THIS_DIR / "xs-l3-knows-query.py",
    "l3_extract": _THIS_DIR / "xs-l3-extract.py",
    "l3_extract_rel": _THIS_DIR / "xs-l3-extract-relationships.py",
    "l3_shadow": _THIS_DIR / "xs-l3-shadow-extract.py",
    "l3_graph": _THIS_DIR / "xs-l3-graph.py",
    "l3_fact_index": _THIS_DIR / "xs-l3-fact-index.py",
    "l3_index": _THIS_DIR / "xs-l3-index.py",
    "l3_decay": _THIS_DIR / "xs-l3-decay.py",
    "l3_deep_extract": _THIS_DIR / "xs-l3-deep-extract.py",
    "freshness": _THIS_DIR / "xs-util-freshness.py",
    "pipeline_status": _THIS_DIR / "xs-util-pipeline-status.py",

    "rq_00_weights": _THIS_DIR / "rq-00-weight-interactions.py",


    "l1_speaker_analysis": _TOOLS_DIR / "plaud" / "pl-analyze-speakers.py",

    "l1_personio": _TOOLS_DIR / "personio" / "pe-l1-enrich.py",
    "l1_personio_assenze": _TOOLS_DIR / "personio" / "pe-l2-absences-daily.py",





    "rq_01_decay": _THIS_DIR / "rq-01-decay-engine.py",
    "rq_02b_signals": _THIS_DIR / "rq-02b-extract-signals.py",
    "rq_03_types": _THIS_DIR / "rq-03-type-detection.py",
    "rq_02_scoring": _THIS_DIR / "rq-02-scoring.py",

    "rqv4_bridge": _THIS_DIR / "rq_entity_bridge.py",
    "rqv4_backfill": _THIS_DIR / "rq-05-backfill-events.py",
    "rqv4_content_quality": _THIS_DIR / "rq-backfill-content-quality.py",
    "rqv4_snapshot": _THIS_DIR / "rq-daily-snapshot.py",
}



























L1_SCRIPTS_PRE = {
    "personio": _TOOLS_DIR / "personio" / "pe-l1-enrich.py",
    "personio_assenze": _TOOLS_DIR / "personio" / "pe-l2-absences-daily.py",
}


L1_SCRIPTS_BASE = {
    "email": _TOOLS_DIR / "email" / "em-l1-enrich.py",

    "email_allegati": _TOOLS_DIR / "email" / "em-l1-allegati.py",

    "calendar": _TOOLS_DIR / "calendar" / "ca-l1-extract.py",
    "attio": _TOOLS_DIR / "attio" / "at-l1-enrich.py",



    "clickup": _TOOLS_DIR / "clickup" / "cu-l1-enrich.py",




    "whoop": _TOOLS_DIR / "whoop" / "wp-l1-process.py",
    "slack": _TOOLS_DIR / "slack" / "sl-l1-enrich.py",
    "notion": _TOOLS_DIR / "notion" / "no-l1-enrich.py",
    "gdrive": _TOOLS_DIR / "gdrive" / "gd-l1-enrich.py",
    "linkedin": _TOOLS_DIR / "linkedin" / "li-l1-enrich.py",
    "docusign": _TOOLS_DIR / "docusign" / "ds-l1-enrich.py",

    "docusign_pdf": _TOOLS_DIR / "docusign" / "ds-l1-pdf.py",
    "chatgpt": _TOOLS_DIR / "chatgpt" / "cg-l1-enrich.py",
    "whatsapp": _TOOLS_DIR / "whatsapp" / "wa-l1-enrich.py",
    "voicememos": _TOOLS_DIR / "voice-memos" / "vm-l1-enrich.py",
    # plugins that write the generic intake (<data root>/<plugin>/processed/plugin-*.parquet,
    # read by plugin_intake.py in l2_merge and l2_knowledge_extract)
    "zoom": _TOOLS_DIR / "zoom" / "zm-l1-enrich.py",
    "github_intake": _TOOLS_DIR / "github" / "gh-l1-enrich.py",
    "databases": _TOOLS_DIR / "databases" / "db-l1-enrich.py",
    "hubspot": _TOOLS_DIR / "hubspot" / "hs-l1-enrich.py",
    "pipedrive": _TOOLS_DIR / "pipedrive" / "pd-l1-enrich.py",
    "fireflies": _TOOLS_DIR / "fireflies" / "ff-l1-enrich.py",
    "fathom": _TOOLS_DIR / "fathom" / "fa-l1-enrich.py",
    "granola": _TOOLS_DIR / "granola" / "gr-l1-enrich.py",
    "telegram": _TOOLS_DIR / "telegram" / "tg-l1-enrich.py",
    "teams": _TOOLS_DIR / "teams" / "tm-l1-enrich.py",
    "atlassian": _TOOLS_DIR / "atlassian" / "as-l1-enrich.py",
    "linear": _TOOLS_DIR / "linear" / "ln-l1-enrich.py",
    # the address-book plugin writes the kernel's slot contacts/contacts.parquet and then runs
    # the kernel step xs-l1-contacts-enrich.py itself (contacts-iphone.parquet, read by l2_merge)
    "contacts": _TOOLS_DIR / "contacts" / "ct-l1-enrich.py",
}




L1_SCRIPTS_DEPENDENT = {
    "tactiq": _TOOLS_DIR / "tactiq" / "tq-l1-enrich.py",
    "plaud": _TOOLS_DIR / "plaud" / "pl-l1-enrich.py",
}


# WhatsApp extras: documents and photos pulled out of the exported chats. Not set up or tested by
# the author, so they never run in a default --ingest or --all: only with --whatsapp-extras.
L1_SCRIPTS_WA_DEEP = {
    "wa_extract_docs": _TOOLS_DIR / "whatsapp" / "wa-l1-extract-docs.py",
    "wa_extract_photos": _TOOLS_DIR / "whatsapp" / "wa-l1-extract-photos.py",
}

# Stages of tipo "a_richiesta" that this run switched on (filled by main() from the flags).
STADI_A_RICHIESTA_ACCESI: set[str] = set()






L1_SCRIPTS_SPEAKERS = {
    "plaud_speakers": _TOOLS_DIR / "plaud" / "pl-analyze-speakers.py",
}







L1_INCREMENTAL = {
    "email",
    "email_allegati",
    "docusign_pdf",
    "calendar",
    "slack",
    "gdrive",
    "linkedin",
    "plaud",
    "whatsapp",
}


def argomenti_l1(name: str) -> list[str]:
    ""

    extra = ["--incremental"] if name in L1_INCREMENTAL else []
    if name == "plaud":
        extra.insert(0, "full")
    return extra



















STEP_DURATA_MISURATA_S: dict[str, tuple[int, str]] = {
    "L2 Knowledge Extract": (2000, "sample run"),












    "L3 Graph": (681, "ingest"),
}

STEP_TIMEOUT_MARGINE = 3

STEP_TIMEOUT_DEFAULT_S = 30 * 60

L3_INDEX_TIMEOUT_S = 4 * 3600









STEP_TIMEOUT_OVERRIDE_S: dict[str, int] = {
    "L3 Extract": 26 * 3600,
    "L3 Extract Relationships": 26 * 3600,
    "L3 Deep Extract": 26 * 3600,



    "L3 Index": 16 * 3600,

}
















L1_PHASE_TIMEOUT_S = 3600






L1_TIMEOUT_OVERRIDE_S: dict[str, int] = {
    "gdrive": 3 * 3600,
}


def _timeout_step(name: str) -> int:
    ""
    override = STEP_TIMEOUT_OVERRIDE_S.get(name)
    if override is not None:
        return override
    misura = STEP_DURATA_MISURATA_S.get(name)
    if misura is None:
        return STEP_TIMEOUT_DEFAULT_S
    return max(STEP_TIMEOUT_DEFAULT_S, misura[0] * STEP_TIMEOUT_MARGINE)



PIPELINE_CHECKPOINT = DATA_ROOT / "l3" / "pipeline-checkpoint.json"





L1_ESITO_FILE = DATA_ROOT / "system" / "l1-ultimo-esito.json"



CANCELLO_SPESA_FILE = DATA_ROOT / "system" / "cancello-spesa.json"




L1_FINGERPRINT_OWNER = "orchestrator"

L1_FINGERPRINT_SOURCES = ("email", "slack", "attio")


class _IntakePiuRecente:
    """The newest plugin intake file (<data root>/*/processed/plugin-*.parquet).

    WATCHED_FILES holds one path per channel, while the generic intake is one pair of
    files per plugin: this stands in for a Path (exists, stat) and looks at the files
    each time it is asked, so a plugin that rewrites its intake files marks l2_merge and
    l2_knowledge_extract to redo in a --propagate run.
    """

    def _piu_recente(self) -> Path | None:
        import plugin_intake

        files = plugin_intake.contact_files(DATA_ROOT) + plugin_intake.interaction_files(
            DATA_ROOT
        )
        tempi = []
        for f in files:
            try:
                tempi.append((f.stat().st_mtime, f))
            except OSError:
                continue
        return max(tempi)[1] if tempi else None

    def exists(self) -> bool:
        return self._piu_recente() is not None

    def stat(self):
        f = self._piu_recente()
        if f is None:
            raise FileNotFoundError(str(DATA_ROOT / "*" / "processed" / "plugin-*.parquet"))
        return f.stat()

    def __str__(self) -> str:
        return str(DATA_ROOT / "*" / "processed" / "plugin-*.parquet")


WATCHED_FILES = {
    "contacts_merged": ENRICHED_DIR / "contacts-merged.parquet",
    "entity_map": ENRICHED_DIR / "entity-map.json",
    "interactions": ENRICHED_DIR / "interactions.parquet",
    "relationship_facts": DATA_ROOT / "l3" / "nlp" / "relationship-facts.parquet",
    "plugin_intake": _IntakePiuRecente(),
    # the address book the kernel step xs-l1-contacts-enrich.py writes (run by the contacts
    # plugin's L1, or by hand after microsoft365 filled the slot)
    "contacts_iphone": DATA_ROOT / "contacts" / "processed" / "contacts-iphone.parquet",
}





















WATCHED_CONSUMERS: dict[str, tuple[str, ...]] = {
    "contacts_merged": ("l3_graph", "l3_index", "l2_knowledge_extract"),
    "entity_map": ("l2_merge",),
    "interactions": ("l2_merge",),
    "relationship_facts": ("l3_fact_index",),
    "plugin_intake": ("l2_merge", "l2_knowledge_extract"),
    "contacts_iphone": ("l2_merge",),
}




CANALI_EXTRA_CONSUMERS: dict[str, tuple[str, ...]] = {
    "l1_fingerprints": ("l2_merge",),
}


def canali_consumatori() -> dict[str, tuple[str, ...]]:
    ""
    return {**WATCHED_CONSUMERS, **CANALI_EXTRA_CONSUMERS}


def stadi_da_rifare(changes: dict[str, bool]) -> dict[str, bool]:
    ""
















    rifare: dict[str, bool] = {}
    for canale, consumatori in canali_consumatori().items():
        if changes.get(canale):
            for stadio in consumatori:
                rifare[stadio] = True
    return rifare





















MODI = ("propaga", "ricostruisci", "ingest", "tutto")

# The English flag of each command. The internal names above stay; the Italian --<modo> is kept
# as a hidden alias so older scripts, the app and the monitor keep working.
FLAG_MODO = {
    "propaga": "--propagate",
    "ricostruisci": "--rebuild",
    "ingest": "--ingest",
    "tutto": "--all",
}
MODO_DA_FLAG = {**{v: k for k, v in FLAG_MODO.items()}, **{f"--{k}": k for k in FLAG_MODO}}

# English labels for the skip reasons and the preconditions, for what the run prints. The codes
# themselves stay (they are read back from the logs).
MOTIVI_EN = {
    "invariato": "unchanged",
    "ripreso": "resumed",
    "fuori_dal_singolo": "outside this single run",
    "non_scelto": "not chosen",
    "precondizione": "precondition",
    "cancello_spesa": "spending gate",
    "fermata_di_linea": "line stop",
    "a_monte": "upstream failed",
    "non_elencata": "not in enabled_sources",
    "niente_da_leggere": "nothing to read yet",
    "motivo_non_dichiarato": "no reason declared",
}
PRECONDIZIONI_EN = {
    "chiave_api": "model API key",
    "consenso_spesa": "spending consent",
    "tar_dello_store": "brain copy",
    "parquet_relazioni_sano": "relationship facts file intact",
    "pressione_memoria": "memory pressure",
    "contacts_merged_del_run_precedente": "contacts of the previous run",
    "eta_l0": "age of the downloads",
}


def _sentinella(valore: str) -> str:
    """--sentinels block|shadow (older Italian values blocco|ombra are accepted)."""
    return {"block": "blocco", "shadow": "ombra"}.get(valore, valore)



_AIUTO_MODI = {
    "propaga": (
        "L2+L3 incremental: propagates the snapshot already on disk. "
        "Does NOT read the sources (neither L0 nor L1): if L1 is idle, it brings no new fact"
    ),
    "ricostruisci": (
        "L2+L3 with all stages forced. Like --propagate: never L1, never L0, never paid stages"
    ),
    "ingest": (
        "L1+L2+L3 FREE: rereads the sources already on disk and carries them up to the KB. "
        "The paid stages stay out and the plan NAMES them as excluded"
    ),
    "tutto": (
        "The WHOLE chain in data order, paid stages included. "
        "Asks for spending consent; never spends on its own, never skips silently"
    ),
}



ALIAS_DEPRECATI = {
    "--auto": "--propagate",
    "--full": "--rebuild",
    "--full-pipeline": "--ingest",
}
ALIAS_RIMOZIONE_NON_PRIMA_DEL = "a future release"
ALIAS_DEPRECATI_DAL = "0.1"





MODI_LEGACY = {
    "auto": "propaga",
    "full": "ricostruisci",
    "full_pipeline": "ingest",
    "full-pipeline": "ingest",
}


def normalizza_modo(mode: str) -> str | None:
    ""
    m = str(mode or "").strip().lower()
    m = MODI_LEGACY.get(m, m)
    return m if m in MODI else None



















# "non_elencata": an L1 phase whose sources enabled_sources does not list (nothing to read).
# "niente_da_leggere": the stage's input was never produced because there is nothing yet (a first
# install: RQ-00 found no interactions, so it wrote no weights for the stages after it).
MOTIVI_SALTO_INNOCUI = (
    "invariato",
    "ripreso",
    "fuori_dal_singolo",
    "non_elencata",
    "niente_da_leggere",
)


@dataclass(frozen=True)
class Salto:
    ""






    id: str
    motivo: str
    dettaglio: str = ""

    @property
    def innocuo(self) -> bool:
        return self.motivo in MOTIVI_SALTO_INNOCUI

    def __str__(self) -> str:
        coda = f" — {self.dettaglio}" if self.dettaglio else ""
        return f"{self.id} ({MOTIVI_EN.get(self.motivo, self.motivo)}){coda}"


@dataclass(frozen=True)
class Passo:
    ""

    id: str
    nome: str
    strato: str
    tipo: str = "ricorrente"
    consuma: tuple[str, ...] = ()
    produce: tuple[str, ...] = ()

    perche_fuori: str = ""

    precondizioni: tuple[str, ...] = field(default_factory=tuple)

    def nel_perimetro(self, modo: str) -> bool:
        ""




        if self.tipo == "fuori_ciclo":
            return False
        if self.tipo == "a_richiesta":
            return modo in ("ingest", "tutto") and self.id in STADI_A_RICHIESTA_ACCESI
        if self.tipo == "pagato":
            return modo == "tutto"
        if self.strato == "L1":
            return modo in ("ingest", "tutto")
        return True










def _a_mano() -> str:
    """The sources you export or run by hand, read from the registry (natura a_richiesta or spot).

    The same list the L0 refresh prints as manual (xs-l0-refresh.py MANUALI): it does not download them.
    """
    try:
        import sorgenti as _reg

        ids = sorted(k for k, v in _reg.SORGENTI.items() if v.natura in ("a_richiesta", "spot"))
    except Exception:  # noqa: BLE001 — a broken registry must not break the plan text
        ids = []
    return ", ".join(ids) if ids else "the sources you export or run by hand"


SORGENTI_A_MANO = _a_mano()


CATENA: tuple[Passo, ...] = (
    Passo(
        id="l0_download",
        nome="L0 download",
        strato="L0",
        tipo="fuori_ciclo",
        produce=("file L0 su disco",),
        perche_fuori=(
            "the download has its own run, tools/cross-source/xs-l0-refresh.py "
            f"(--then-ingest = full run). These stay manual, you export or run them yourself: "
            f"{SORGENTI_A_MANO}. The pipeline does not launch it: it REPORTS its age"
        ),
        precondizioni=("eta_l0",),
    ),
    Passo(
        id="l1_personio",
        nome="L1 Personio (nickname map producer)",
        strato="L1",
        consuma=("file L0 su disco",),
        produce=("personio employees.parquet",),
        perche_fuori="does not read the sources: no new fact enters from here",
        precondizioni=("pressione_memoria",),
    ),
    Passo(
        id="l1_personio_assenze",
        nome="L1 Personio absences (daily + hourly)",
        strato="L1",
        consuma=("personio absences-raw.json", "personio absence-periods-raw.json"),
        produce=("personio absences-daily.parquet",),
        perche_fuori="does not read the sources: no new fact enters from here",
        precondizioni=("pressione_memoria",),
    ),
    Passo(
        id="l1_phase1",
        nome="L1 phase 1 (base sources)",
        strato="L1",
        consuma=("file L0 su disco",),
        produce=("parquet per-sorgente", "interactions.parquet"),
        perche_fuori="does not read the sources: no new fact enters from here",
        precondizioni=("pressione_memoria",),
    ),
    Passo(
        id="l1_speaker_analysis",
        nome="L1 Plaud speaker list (producer)",
        strato="L1",
        consuma=("file L0 su disco",),
        produce=("plaud _speaker_analysis.json",),
        perche_fuori="does not read the sources: only regenerates the list, no new fact",
        precondizioni=("pressione_memoria",),
    ),
    Passo(
        id="l1_phase2",
        nome="L1 phase 2 (tactiq + plaud)",
        strato="L1",
        consuma=("contacts-merged.parquet (del run PRECEDENTE)", "plaud _speaker_analysis.json"),
        produce=("tactiq/plaud L1",),
        perche_fuori="does not read the sources: no new fact enters from here",
        precondizioni=("pressione_memoria", "contacts_merged_del_run_precedente"),
    ),
    Passo(
        id="l1_phase3_wa_deep",
        nome="L1 phase 3 (WhatsApp extras: docs + photos)",
        strato="L1",
        tipo="a_richiesta",
        consuma=("whatsapp L1",),
        produce=("whatsapp documents/photos",),
        perche_fuori=(
            "WhatsApp extras (documents and photos), not set up or tested by the author: "
            "they run only when you add --whatsapp-extras to --ingest or --all"
        ),
        precondizioni=("pressione_memoria",),
    ),


    Passo(
        id="l1_inventario",
        nome="L1 Inventory (domains, repos)",
        strato="L2",
        consuma=(
            "gsc/property.json",
            "analytics/property.json",
            "github/repos.json",
        ),
        produce=("inventory/domini.parquet", "inventory/repo.parquet"),




    ),
    Passo(
        id="l2_merge",
        nome="L2 Merge",
        strato="L2",
        consuma=("parquet per-sorgente", "entity-map.json", "interactions.parquet"),
        produce=("contacts-merged.parquet",),
    ),
    Passo(
        id="l2_entity_map_cleanup",
        nome="L2 Entity Map Cleanup",
        strato="L2",
        consuma=("contacts-merged.parquet",),
        produce=("entity-map.json",),
    ),
    Passo(
        id="l2_duckdb", nome="L2 DuckDB Views", strato="L2", consuma=("contacts-merged.parquet",)
    ),
    Passo(id="l2_sqi", nome="L2 Signal Quality Index", strato="L2"),



    Passo(
        id="l3_extract",
        nome="L3 Extract",
        strato="L3",
        tipo="pagato",



        produce=("decisions.parquet",),
        perche_fuori="paid (model calls): needs --all and spending consent",
        precondizioni=("chiave_api", "consenso_spesa"),
    ),
    Passo(
        id="l3_extract_rel",
        nome="L3 Extract Relationships",
        strato="L3",
        tipo="pagato",
        produce=("relationship-facts.parquet",),
        perche_fuori="paid (model calls): needs --all and spending consent",
        precondizioni=("chiave_api", "consenso_spesa"),
    ),
    Passo(
        id="l3_deep_extract",
        nome="L3 Deep Extract",
        strato="L3",
        tipo="pagato",
        produce=("deep-facts.parquet",),
        perche_fuori="paid (model calls): needs --all and spending consent",
        precondizioni=("chiave_api", "consenso_spesa"),
    ),
    Passo(
        id="l2_knowledge_extract",
        nome="L2 Knowledge Extract",
        strato="L2",
        consuma=(
            "contacts-merged.parquet",
            "relationship-facts.parquet",
            "deep-facts.parquet",
        ),
        produce=("knowledge store",),


        precondizioni=("parquet_relazioni_sano", "tar_dello_store"),
    ),


    Passo(
        id="l2_ricorrenze",
        nome="L2 Birthdays, birth and name days",
        strato="L2",
        consuma=("knowledge store", "ricorrenze-verificate.json"),
        produce=("knowledge store", "ricorrenze.json"),
        precondizioni=("tar_dello_store",),
    ),




    Passo(
        id="l2_episodes",
        nome="L2 Episodes",
        strato="L2",
        consuma=("relationship-facts.parquet", "deep-facts.parquet"),
        produce=("knowledge/episodes", "knowledge store"),



        precondizioni=("parquet_relazioni_sano", "tar_dello_store"),
    ),
    Passo(
        id="l2_calendar_episodes",
        nome="L2 Episodes from calendar",
        strato="L2",
        consuma=("knowledge/episodes",),
        produce=("knowledge/episodes",),
    ),
    Passo(
        id="l2_email_participants",
        nome="L2 Email participants",
        strato="L2",
        consuma=("knowledge/episodes", "messages.parquet"),
        produce=("knowledge/episodes",),
    ),
    Passo(
        id="l2_knows",
        nome="L2 KNOWS (who had access)",
        strato="L2",
        consuma=("knowledge/episodes",),
        produce=("knows.parquet",),
    ),
    Passo(
        id="l3_subject_index",
        nome="L3 Subject index",
        strato="L3",
        consuma=("knowledge/episodes",),
        produce=("subject_index.parquet",),



    ),
    Passo(id="l2_attachment_discovery", nome="L2 Attachment Discovery", strato="L2"),
    Passo(id="l2_person_deep_context", nome="L2 Person Deep Context", strato="L2"),
    Passo(id="rq_00_weights", nome="RQ-00 Weights", strato="RQ"),
    Passo(id="rq_01_decay", nome="RQ-01 Decay", strato="RQ"),
    Passo(id="rq_02b_signals", nome="RQ-02b Signals", strato="RQ"),
    Passo(id="rq_03_types", nome="RQ-03 Types", strato="RQ"),
    Passo(id="rq_02_scoring", nome="RQ-02 Scoring", strato="RQ"),
    Passo(id="rqv4_bridge", nome="RQV4 Entity Bridge", strato="RQ"),
    Passo(id="rqv4_backfill", nome="RQV4 Event Backfill", strato="RQ"),
    Passo(id="rqv4_content_quality", nome="RQV4 Content Quality", strato="RQ"),
    Passo(id="rqv4_snapshot", nome="RQV4 Score Snapshot", strato="RQ"),
    Passo(id="l3_shadow", nome="L3 Shadow Extract", strato="L3"),
    Passo(
        id="l3_graph",
        nome="L3 Graph",
        strato="L3",


        consuma=(
            "contacts-merged.parquet",
            "interactions.parquet",
            "relationship-facts.parquet",
            "deep-facts.parquet",
            "shadow-contacts.parquet",
            "entity-map.json",
        ),
        produce=("network-graph",),
        precondizioni=("pressione_memoria",),
    ),
    Passo(
        id="l3_index",
        nome="L3 Index",
        strato="L3",
        consuma=("contacts-merged.parquet",),
        precondizioni=("pressione_memoria",),
    ),
    Passo(
        id="l3_fact_index",
        nome="L3 Fact Index",
        strato="L3",
        consuma=("relationship-facts.parquet",),
        precondizioni=("parquet_relazioni_sano",),
    ),
    Passo(id="l3_decay", nome="L3 Decay", strato="L3"),
    Passo(id="freshness", nome="Freshness", strato="L3"),
    Passo(id="pipeline_status", nome="Pipeline Status", strato="L3"),

    Passo(
        id="l3_calendario_ricorrenze",
        nome="L3 Birthday and Name-day Calendars",
        strato="L3",
        consuma=("ricorrenze.json",),
        produce=("calendari Google Compleanni e Onomastici",),
    ),
)

CATENA_PER_ID: dict[str, Passo] = {p.id: p for p in CATENA}

CATENA_TOTALE = len(CATENA)


def perimetro(modo: str) -> list[Passo]:
    ""
    return [p for p in CATENA if p.nel_perimetro(modo)]


def fuori_perimetro(modo: str) -> list[Passo]:
    ""
    return [p for p in CATENA if not p.nel_perimetro(modo)]


def righe_perimetro(modo: str) -> list[str]:
    ""




    dentro = perimetro(modo)
    fuori = fuori_perimetro(modo)
    righe = [f"Perimeter: {len(dentro)} stages of {CATENA_TOTALE} in the complete chain."]
    if fuori:
        voci = []
        for p in fuori:
            marca = " (PAID)" if p.tipo == "pagato" else ""
            voci.append(f"{p.id}{marca}")
        righe.append("Outside this command: " + " · ".join(voci))


        visti = set()
        for p in fuori:
            if p.perche_fuori and p.perche_fuori not in visti:
                visti.add(p.perche_fuori)
                righe.append(f"  - {p.perche_fuori}")
    return righe


def _load_checkpoint() -> dict:
    ""
    if PIPELINE_CHECKPOINT.exists():
        try:
            return json.loads(PIPELINE_CHECKPOINT.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_checkpoint(stages_run: list[str], *, solo: set[str] | None = None):
    ""


















    precedente = _load_checkpoint()
    mtimes = dict(precedente.get("mtimes", {}))
    girati = set(stages_run)
    non_consumati = []
    for name, path in WATCHED_FILES.items():
        if solo is not None and name not in solo:
            continue
        consumatori = WATCHED_CONSUMERS.get(name)
        if consumatori is None:


            non_consumati.append(f"{name} (no declared consumer)")
            continue
        if not set(consumatori) <= girati:
            mancanti = ", ".join(sorted(set(consumatori) - girati))
            non_consumati.append(f"{name} (missing: {mancanti})")
            continue
        if path.exists():
            mtimes[name] = path.stat().st_mtime

    checkpoint = {
        "timestamp": datetime.now(UTC).isoformat(),
        "mtimes": mtimes,
        "stages_run": stages_run,
    }
    safe_write_json(PIPELINE_CHECKPOINT, checkpoint)
    if non_consumati:
        log.info(
            "  Checkpoint: NOT consumed (left to do next run) — %s",
            " · ".join(non_consumati),
        )




    if solo is None:
        _save_l1_fingerprints(girati)


def _save_l1_fingerprints(girati: set[str]) -> None:
    ""





    if "l2_merge" not in girati:
        return
    try:
        from l1_checkpoint import L1Checkpoint

        for source in L1_FINGERPRINT_SOURCES:
            L1Checkpoint(source, owner=L1_FINGERPRINT_OWNER).save()
    except Exception as e:  # noqa: BLE001 — must never make a run fail
        log.warning("Orchestrator L1 fingerprints not saved: %s", e)


def detect_changes() -> dict[str, bool]:
    ""




    checkpoint = _load_checkpoint()
    prev_mtimes = checkpoint.get("mtimes", {})

    changes = {}
    for name, path in WATCHED_FILES.items():
        if not path.exists():
            changes[name] = False
            continue
        current_mtime = path.stat().st_mtime
        prev_mtime = prev_mtimes.get(name, 0)
        changes[name] = current_mtime > prev_mtime







    try:
        from l1_checkpoint import L1Checkpoint

        l1_any_changed = False
        for source in L1_FINGERPRINT_SOURCES:
            ckpt = L1Checkpoint(source, owner=L1_FINGERPRINT_OWNER)
            if ckpt.has_output_changed():
                l1_any_changed = True
                break

        changes["l1_fingerprints"] = l1_any_changed
    except ImportError:
        log.debug("l1_checkpoint not available, skipping L1 fingerprint check")

    return changes


def _log_metrics(
    name: str, script_path: Path, status: str, elapsed: float, exit_code: int | None
) -> None:
    ""
    try:
        from monitoring.pipeline_metrics import log_pipeline_run


        stem = script_path.stem
        stage = "unknown"
        for s in ("l0", "l1", "l2", "l3"):
            if f"-{s}-" in stem:
                stage = s
                break

        log_pipeline_run(
            script=stem,
            stage=stage,
            source=name,
            status=status,
            duration_s=elapsed,
            exit_code=exit_code,
            caller="orchestrator",
        )
    except Exception:
        pass




_LOG_DEL_RUN = ""


_SEGNALI_DA_FUORI = (-signal.SIGTERM, -signal.SIGINT, -signal.SIGKILL, -signal.SIGHUP)


def _stop_chiesto_dall_app() -> bool:
    ""
    run_dir, run_id = os.environ.get("SBK_RUN_DIR"), os.environ.get("SBK_RUN_ID")
    return bool(run_dir and run_id and (Path(run_dir) / f"{run_id}.ferma").exists())


def _dlq_add_failure(
    name: str,
    script_path: Path,
    error_msg: str,
    error_type: str,
    stderr: str = "",
    extra: dict | None = None,
) -> None:
    ""




    try:
        from pipeline_dlq import add_failure, ultime_righe

        stem = script_path.stem if hasattr(script_path, "stem") else str(script_path)
        stage = "unknown"
        for s in ("l0", "l1", "l2", "l3", "rq"):
            if f"-{s}-" in stem or stem.startswith(f"{s}_") or stem.startswith(f"{s}-"):
                stage = s
                break
        perche = ultime_righe(stderr) if stderr else ""
        add_failure(
            script=stem,
            source=name,
            stage=stage,
            error_message=f"{error_msg}: {perche}" if perche else error_msg,
            error_type=error_type,
            extra={"log": _LOG_DEL_RUN, **(extra or {})},
        )
        log.info(f"  DLQ: failure recorded for {stem}")
    except Exception as dlq_err:
        log.debug(f"  DLQ unavailable: {dlq_err}")



_RE_NOME_DECORATORE = re.compile(r"""@pipeline_step\(\s*name\s*=\s*["']([^"']+)["']""")


def _nomi_in_coda(script_path: Path) -> set[str]:
    ""


    stem = script_path.stem if hasattr(script_path, "stem") else str(script_path)
    try:
        testo = Path(script_path).read_text(encoding="utf-8")
    except (OSError, TypeError, ValueError):
        return {stem}
    return {stem, *_RE_NOME_DECORATORE.findall(testo)}


def _script_della_fonte(fonte: str) -> Path:
    ""
    letture = {
        **L1_SCRIPTS_PRE,
        **L1_SCRIPTS_BASE,
        **L1_SCRIPTS_SPEAKERS,
        **L1_SCRIPTS_DEPENDENT,
        **L1_SCRIPTS_WA_DEEP,
    }
    return letture.get(fonte) or SCRIPTS.get(fonte) or Path(fonte)


def _dlq_marca_recuperati(name: str, script_path: Path, dal_iso: str, tentativo: int) -> int:
    ""





    try:
        from pipeline_dlq import get_all_failures, mark_resolved, si_chiude_da_sola

        nomi = _nomi_in_coda(script_path)
        nota = f"recovered from the line stop: '{name}' closed on attempt {tentativo}"
        marcate = 0
        for v in get_all_failures(include_resolved=False):
            if v.get("script_name") not in nomi:
                continue
            if str(v.get("timestamp") or "") < dal_iso:
                continue



            if not si_chiude_da_sola(v):
                continue
            if mark_resolved(str(v.get("id")), note=nota):
                marcate += 1
        return marcate
    except Exception as dlq_err:  # noqa: BLE001
        log.debug(f"  DLQ not readable for recovery: {dlq_err}")
        return 0


def _dlq_chiudi_superate(name: str, script_path: Path, dal_iso: str) -> int:
    ""





    try:
        from pipeline_dlq import chiudi_superate

        run = os.environ.get("SBK_CODA_RUN", "")
        nota = f"closed: '{name}' closed on {datetime.now():%d/%m/%Y %H:%M}" + (
            f" (run {run})" if run else ""
        )
        return chiudi_superate(_nomi_in_coda(script_path), nota, prima_di=dal_iso)
    except Exception as dlq_err:  # noqa: BLE001
        log.debug(f"  DLQ not readable for closing: {dlq_err}")
        return 0










def _marcatori_stderr() -> tuple[str, ...]:
    base = ("CRITICAL", "ERROR", "WARNING", "⛔", "⚠️")
    try:
        from conio import MARCATORE

        return (*base, MARCATORE)
    except Exception:  # noqa: BLE001 — the filter must work even without it
        return base





STDERR_CODA = 10
STDERR_MAX = 40


def _mostra_stderr(nome: str, testo: str, fallito: bool) -> None:
    ""














    righe = [r for r in (testo or "").strip().split("\n") if r.strip()]
    if not righe:
        return
    if fallito:
        for r in righe[-STDERR_CODA:]:
            log.error(f"  stderr: {r}")
        return
    marcatori = _marcatori_stderr()
    scelte, viste = [], set()
    for r in righe[-STDERR_CODA:] + [x for x in righe if any(m in x for m in marcatori)]:
        if r not in viste:
            viste.add(r)
            scelte.append(r)
    for r in scelte[:STDERR_MAX]:
        grave = any(m in r for m in marcatori)
        (log.warning if grave else log.info)(f"  stderr: {r}")
    if len(scelte) > STDERR_MAX:
        log.warning("  stderr: ...and %d more lines not printed", len(scelte) - STDERR_MAX)


def _chiave_step(nome: str) -> str:
    ""

    return re.sub(r"[^a-z0-9]+", "_", str(nome or "").lower()).strip("_")


def _dlq_falliti_dal(inizio_iso: str, *, con_stato: bool = False):
    ""




























    try:
        from pipeline_dlq import get_all_failures

        voci = get_all_failures(include_resolved=True)
    except Exception as e:  # noqa: BLE001





        log.error(
            "  ⛔ Failure queue NOT readable (%s): the outcome of this run is not "
            "verifiable. What to do: uv run python tools/util/sb-pipeline-ctl.py status",
            e,
        )
        return ([], [], False) if con_stato else []
    fuori, recuperati, visti, visti_rec = [], [], set(), set()
    mio = os.environ.get("SBK_CODA_RUN", "")
    estranei: list[str] = []
    for v in voci:
        quando = str(v.get("timestamp") or "")
        if not quando or quando < inizio_iso:
            continue
        if mio and v.get("run") != mio:
            if v.get("status") != "resolved":
                estranei.append(
                    f"{v.get('script_name')} ({v.get('id')}, run {v.get('run') or '-'})"
                )
            continue
        chiave = str(v.get("script_name") or "")
        if chiave.startswith("xs-"):
            chiave = chiave[3:]




        if v.get("status") == "resolved":
            if chiave not in visti_rec:
                visti_rec.add(chiave)
                recuperati.append(v)
            continue
        if chiave in visti:
            continue
        visti.add(chiave)
        fuori.append(v)
    if estranei:
        log.warning(
            "  Failure queue: %d entries written by other processes while this run was going, they do not count: %s",
            len(estranei),
            ", ".join(estranei[:10]),
        )
    return (fuori, recuperati, True) if con_stato else fuori


def _riepilogo(
    stages_run: list,
    errors: list,
    avvisi: list,
    t_inizio_iso: str,
    elapsed: float,
    *,
    modo: str = "propaga",
    salti: list | None = None,
    piano: list[str] | None = None,
    fonti_non_chiuse: list[str] | None = None,
) -> dict:
    ""


























    morti, recuperati, coda_leggibile = _dlq_falliti_dal(t_inizio_iso, con_stato=True)
    salti = list(salti or [])
    fonti = list(dict.fromkeys(fonti_non_chiuse or []))
    nomi_fonti = {_chiave_step(f) for f in fonti} | {
        _chiave_step(n) for f in fonti for n in _nomi_in_coda(_script_della_fonte(f))
    }

    def _di_una_fonte(v: dict) -> bool:
        nome = str(v.get("script_name") or "")
        return bool({_chiave_step(v.get("source")), _chiave_step(nome)} & nomi_fonti)

    morti_fonti = [v for v in morti if _di_una_fonte(v)]
    morti = [v for v in morti if not _di_una_fonte(v)]
    chiavi_coda = {_chiave_step(v.get("source")) for v in morti}
    chiavi_coda |= {_chiave_step(v.get("script_name")) for v in morti}
    solo_a_mano = [
        e
        for e in errors
        if _chiave_step(e) not in chiavi_coda and _chiave_step(e) not in nomi_fonti
    ]


    falliti = list(
        dict.fromkeys([str(v.get("source") or v.get("script_name")) for v in morti] + solo_a_mano)
    )

    intestazione, codice = esito(
        piano=list(piano if piano is not None else stages_run),
        eseguiti=list(stages_run),
        saltati=salti,
        morti=falliti,
        avvisi=list(avvisi),
        coda_leggibile=coda_leggibile,
        modo=modo,
        fonti_non_chiuse=fonti,
    )

    log.info(f"\n=== {intestazione} ===")
    for riga in righe_perimetro(modo):
        log.info("  %s", riga)
    log.info(f"  Stages run: {', '.join(stages_run) or '(none)'}")
    if salti:
        log.info("  Skipped (declared): %s", " · ".join(str(s) for s in salti))
    if falliti:
        log.error("  Errors (%d, from the failure queue): %s", len(falliti), ", ".join(falliti))
        for v in morti:
            log.error(
                "    - %s (%s) — %s: %s",
                v.get("source"),
                v.get("script_name"),
                v.get("error_type"),
                str(v.get("error_message") or "")[:120],
            )
        if len(errors) != len(falliti):
            log.error(
                "  ⚠️  the hand-written count said %d, the queue has %d: "
                "the steps marked «non-critical, continuing» were not making it into the summary",
                len(errors),
                len(falliti),
            )
        if solo_a_mano:
            log.error(
                "  ⚠️  seen by the orchestrator but NOT in the queue (not recorded): %s",
                ", ".join(solo_a_mano),
            )
    if fonti:
        log.error(
            "  ⛔ Sources not closed (%d), only they stopped and the chain went on: %s",
            len(fonti),
            ", ".join(fonti),
        )
        for v in morti_fonti:
            log.error(
                "    - %s (%s) — %s: %s",
                v.get("source"),
                v.get("script_name"),
                v.get("error_type"),
                str(v.get("error_message") or "")[:120],
            )
    if recuperati:
        log.warning(
            "  🔁 recovered from the line stop (%d) — died and then CLOSED, "
            "they do not count among the failures:",
            len(recuperati),
        )
        for v in recuperati:
            log.warning(
                "    - %s (%s) — %s: %s → %s",
                v.get("source"),
                v.get("script_name"),
                v.get("error_type"),
                str(v.get("error_message") or "")[:80],
                v.get("resolution_note") or "resolved (see queue)",
            )
    incompleti, qualita = _di_qualita(avvisi)
    incompleti, note_stato = _note_di_stato(incompleti)
    if incompleti:


        log.error("  ⛔ completed_with_warnings (%d):", len(incompleti))
        for riga in incompleti:
            log.error("     - %s", riga)
    if qualita:


        log.error("  ⛔ KB quality to check (%d):", len(qualita))
        for riga in qualita:
            log.error("     - %s", riga)
    if note_stato:

        log.warning(
            "  ○ how sources and machine were (%d), they do not make the reread incomplete:",
            len(note_stato),
        )
        for riga in note_stato:
            log.warning("     - %s", riga)
    log.info(f"  Elapsed: {elapsed:.1f}s ({elapsed / 60:.1f}m)")

    return {
        "stages_run": stages_run,
        "errors": falliti,
        "fonti_non_chiuse": fonti,
        "errors_annotati": errors,
        "recuperati": [str(v.get("source") or v.get("script_name")) for v in recuperati],
        "avvisi": avvisi,
        "elapsed": elapsed,
        "salti": [str(s) for s in salti],
        "intestazione": intestazione,
        "exit_code": codice,
        "coda_leggibile": coda_leggibile,
        "modo": modo,
    }


def _closure_check() -> None:
    ""




    ctl = _TOOLS_DIR / "util" / "sb-pipeline-ctl.py"
    if not ctl.exists():
        return
    try:


        cmd = [sys.executable, str(ctl), "check", "--ignora-pid", str(os.getpid())]



        if marca := os.environ.get("SBK_CODA_RUN", ""):
            cmd += ["--del-run", marca]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        for line in (r.stdout or "").strip().splitlines():
            log.info(line)
        if r.returncode != 0:
            log.warning(
                "Closure check: residues remain (see above). "
                "To clean up stale locks: uv run python tools/util/sb-pipeline-ctl.py cleanup"
            )
    except (subprocess.SubprocessError, OSError) as e:
        log.warning("Closure check not performed: %s", e)






FILE_ATTESI: dict[str, tuple[Path, ...]] = {
    "l2_merge": (ENRICHED_DIR / "contacts-merged.parquet",),
    "l2_duckdb": (DATA_ROOT / "sbk.duckdb",),
    "l2_sqi": (ENRICHED_DIR / "signal-quality-index.json",),
    "rq_00_weights": (DATA_ROOT / "rq" / "interaction-weights.parquet",),
    "rq_01_decay": (DATA_ROOT / "rq" / "decay-state.parquet",),
}

_RE_NIENTE_DA_FARE = re.compile(
    r"unchanged|invariat|skipp|up[- ]to[- ]date|nothing (to|new)|niente da|already|no changes", re.I
)

_RE_ERRORE = re.compile(r"\bERROR\b|\bCRITICAL\b|Traceback")

_CONTROLLI_DEL_RUN: dict[str, list[str]] = {"senza_file": [], "veloci": [], "con_errori": []}
_DURATE_TIPICHE: dict[str, float] | None = None


def _durata_tipica(name: str) -> float | None:
    ""
    global _DURATE_TIPICHE
    if _DURATE_TIPICHE is None:
        durate: dict[str, list[float]] = {}
        try:
            with (DATA_ROOT / "system" / "pipeline-metrics.jsonl").open(encoding="utf-8") as fh:
                for riga in fh:
                    try:
                        d = json.loads(riga)
                    except ValueError:
                        continue
                    if d.get("caller") == "orchestrator" and d.get("status") == "completed":
                        if isinstance(d.get("duration_s"), int | float):
                            durate.setdefault(str(d.get("source")), []).append(
                                float(d["duration_s"])
                            )
        except OSError:
            pass
        import statistics

        _DURATE_TIPICHE = {n: statistics.median(v) for n, v in durate.items() if len(v) >= 3}
    return _DURATE_TIPICHE.get(name)


def _controlla_lo_stadio(name: str, t0: float, elapsed: float, result) -> None:
    ""
    uscita = f"{result.stdout or ''}\n{result.stderr or ''}"
    niente_da_fare = bool(_RE_NIENTE_DA_FARE.search(uscita))
    pid = next((p.id for p in CATENA if p.nome == name), None)
    if pid in FILE_ATTESI and not niente_da_fare:
        mancano = [
            f.name
            for f in FILE_ATTESI[pid]
            if not f.exists() or f.stat().st_size == 0 or f.stat().st_mtime < t0 - 1
        ]
        if mancano:
            _CONTROLLI_DEL_RUN["senza_file"].append(f"{name} ({', '.join(mancano)})")
            log.error(
                "  ⛔ %s closed without writing %s: it does not count as closed",
                name,
                ", ".join(mancano),
            )
    tipica = _durata_tipica(name)
    if tipica and tipica >= 30 and elapsed < tipica / 10 and not niente_da_fare:
        _CONTROLLI_DEL_RUN["veloci"].append(
            f"{name}|{elapsed:.1f} s against {tipica:.0f} s usually"
        )
        log.warning("  ⚠️  %s closed in %.1f s, it usually takes %.0f s", name, elapsed, tipica)
    errori = sum(1 for r in (result.stderr or "").splitlines() if _RE_ERRORE.search(r))
    if errori:
        _CONTROLLI_DEL_RUN["con_errori"].append(f"{name}|{errori}")


def _wait_and_budget(step_name: str):
    ""




    try:
        from sbk_resources import (
            SEG_WARN,
            SEG_YIELD,
            budget,
            check_interval,
            pressure,
            shared_state,
            wait_for_headroom,
        )
    except ImportError:
        return None

    st = shared_state()
    log.info("  [resources] %s", st)

    p = pressure()
    if p.should_pause:
        log.warning("  [resources] pressure %s — waiting for space before '%s'", p, step_name)

        if not wait_for_headroom(timeout_s=900, poll_s=max(5.0, check_interval(p.seg_ratio))):





            while (adesso := pressure()).seg_ratio >= SEG_YIELD:
                log.warning(
                    "  [resources] the machine is over the threshold (%s): '%s' waits, under load it does not start",
                    adesso,
                    step_name,
                )
                _aspetta_pausa(step_name)
                wait_for_headroom(
                    threshold=SEG_YIELD,
                    timeout_s=900,
                    poll_s=max(5.0, check_interval(adesso.seg_ratio)),
                )
            if pressure().seg_ratio >= SEG_WARN:
                log.error(
                    "  [resources] still under pressure after 15 min: proceeding with reduced budget"
                )
    b = budget()
    log.info("  [resources] %s", b)
    return b



_GUARDIA_OGNI_S = 5

_PONTE_S = 15



_SOGLIE_NON_LETTE_DETTO = False


def _guardiano_solo_pericolo() -> bool:
    ""

    global _SOGLIE_NON_LETTE_DETTO
    try:
        import impostazioni_pipeline

        return bool(impostazioni_pipeline.leggi()["guardiano"]["solo_pericolo"])
    except Exception as e:  # noqa: BLE001
        if not _SOGLIE_NON_LETTE_DETTO:
            _SOGLIE_NON_LETTE_DETTO = True
            log.error(
                "  ⛔ guardian thresholds not read (%s): the old rule applies, it stops even for quota on a calm Mac",
                e,
            )
        return False


def _run_guarded(cmd: list[str], *, timeout: int, budget, name: str):
    ""















    if budget is None:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)

    import threading

    from sbk_resources import SEG_CRITICAL, pressure, tree_footprint





    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True
    )
    state = {"peak": 0, "killed": None}
    stop = threading.Event()

    def _al_gruppo(sig) -> bool:
        ""
        try:
            os.killpg(proc.pid, sig)
        except ProcessLookupError:
            return False
        except PermissionError:
            try:
                os.kill(proc.pid, sig)
            except ProcessLookupError:
                return False
        return True

    def _gruppo_vivo() -> bool:
        proc.poll()
        return _al_gruppo(0)

    def _fino_a(sigs: tuple) -> None:
        ""
        for sig, wait_s in sigs:
            if not _al_gruppo(sig):
                return
            deadline = time.time() + wait_s
            while time.time() < deadline and _gruppo_vivo():
                time.sleep(0.5)

    def _terminate(reason: str):
        ""
        state["killed"] = reason
        _fino_a(((signal.SIGCONT, 0), (signal.SIGTERM, 10), (signal.SIGKILL, 0)))

    def _inoltra_interruzione():
        ""





        if os.environ.get("SBK_RUN_ID"):
            return
        _fino_a(
            (
                (signal.SIGCONT, 0),
                (signal.SIGINT, 10),
                (signal.SIGTERM, 10),
                (signal.SIGKILL, 0),
            )
        )

    def _guard():
        soft = budget.job_bytes
        hard = int(budget.job_bytes * 1.5)
        frozen_at = None
        frozen_why = None



        solo_pericolo = _guardiano_solo_pericolo()
        if solo_pericolo:
            log.info(
                "  [resources] '%s': the guardian stops it only if the machine is in danger (configuration choice)",
                name,
            )


        avvisato = 0
        while not stop.wait(_GUARDIA_OGNI_S):
            if proc.poll() is not None:
                return
            fp = tree_footprint(proc.pid)
            state["peak"] = max(state["peak"], fp)
            seg = pressure().seg_ratio

            if frozen_at is None:

                if fp > hard and not solo_pericolo:
                    log.error(
                        "  [resources] '%s' over budget (%.1f GB > %.1f GB) — FREEZING",
                        name,
                        fp / 1024**3,
                        hard / 1024**3,
                    )
                    if not _al_gruppo(signal.SIGSTOP):
                        return
                    frozen_at, frozen_why = time.time(), "footprint"
                elif seg >= SEG_CRITICAL:
                    log.error(
                        "  [resources] critical machine (segments %.0f%%) — FREEZING '%s'",
                        seg * 100,
                        name,
                    )
                    if not _al_gruppo(signal.SIGSTOP):
                        return
                    frozen_at, frozen_why = time.time(), "pressione"
                elif fp > soft and fp >= avvisato + 512 * 1024**2:
                    avvisato = fp
                    log.warning(
                        "  [resources] '%s' at %.1f GB (budget %.1f GB)",
                        name,
                        fp / 1024**3,
                        soft / 1024**3,
                    )
                continue


            waited = time.time() - frozen_at
            if frozen_why == "footprint":




                if waited > _PONTE_S:
                    log.error(
                        "  [resources] '%s' stays over budget — TERMINATING (peak %.1f GB)",
                        name,
                        state["peak"] / 1024**3,
                    )
                    _terminate("budget")
                    return
            else:




                if seg < SEG_CRITICAL * 0.9:
                    log.warning("  [resources] pressure back to normal — resuming '%s'", name)
                    if not _al_gruppo(signal.SIGCONT):
                        return
                    frozen_at, frozen_why = None, None
                elif waited > _PONTE_S:
                    log.error(
                        "  [resources] pressure not back within %d s — TERMINATING '%s'",
                        _PONTE_S,
                        name,
                    )
                    _terminate("pressione")
                    return

    t = threading.Thread(target=_guard, daemon=True)
    t.start()
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:










        stop.set()
        log.error("  [resources] '%s' over the timeout — TERMINATING the process", name)
        _terminate("timeout")
        try:
            proc.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            log.error("  [resources] '%s' does not close even after KILL", name)
        raise
    except BaseException:
        stop.set()
        _inoltra_interruzione()
        raise
    finally:
        stop.set()

    if state["peak"]:
        log.info("  [resources] peak '%s': %.2f GB", name, state["peak"] / 1024**3)
    if state["killed"]:
        log.error("  [resources] '%s' TERMINATED by the memory guardian", name)

    cp = subprocess.CompletedProcess(cmd, proc.returncode, out, err)


    cp.guard_kill = state["killed"]

    cp.picco = state["peak"]
    return cp







_FERMATA_TENTATIVI = {
    "memoria_pressione": 4,
    "memoria_budget": 3,
    "lock": 5,
    "timeout": 2,
    "fallito": 2,
    "errore": 2,
    # exit 78 (EX_CONFIG): something is missing that a retry cannot bring (e.g. no embedding model offline)
    "configurazione": 1,
}
# What the log prints for each class (the codes above stay internal).
CLASSI_EN = {
    "memoria_pressione": "memory pressure",
    "memoria_budget": "memory budget",
    "lock": "lock held",
    "timeout": "timeout",
    "fallito": "failed",
    "errore": "error",
    "configurazione": "setup missing, not retried",
}
# A stage exits with this code when it cannot run on this machine as it is set up (sysexits EX_CONFIG).
EXIT_CONFIGURAZIONE = 78
_FERMATA_ATTESA_S = {
    "memoria_pressione": 30,
    "memoria_budget": 30,
    "lock": 120,
    "timeout": 60,
    "fallito": 30,
    "errore": 30,
}


def run_script(
    name: str,
    script_path: Path,
    extra_args: list[str] | None = None,
    expected_output: Path | None = None,
    *,
    timeout_s: int | None = None,
) -> bool:
    ""







    if not script_path.exists():
        log.error(f"Script not found: {script_path}")
        return False

    classe = ""
    dal_iso = datetime.now(UTC).isoformat()
    for tentativo in range(1, max(_FERMATA_TENTATIVI.values()) + 1):
        ok, classe = _run_script_una_volta(
            name, script_path, extra_args, expected_output, timeout_s=timeout_s
        )
        if ok:
            if tentativo > 1:


                marcate = _dlq_marca_recuperati(name, script_path, dal_iso, tentativo)
                log.warning(
                    "  🔁 retry: '%s' CLOSED on attempt %d — %d queue entries marked as recovered",
                    name,
                    tentativo,
                    marcate,
                )
            chiuse = _dlq_chiudi_superate(name, script_path, dal_iso)
            if chiuse:
                log.info(
                    "  failure queue: %d old entries of '%s' closed with the note", chiuse, name
                )
            return True
        consentiti = _FERMATA_TENTATIVI.get(classe, 2)
        if tentativo >= consentiti:
            log.error(
                "  ⛔ '%s' did not close after %d attempts (class: %s)",
                name,
                tentativo,
                CLASSI_EN.get(classe, classe),
            )
            return False
        attesa = _FERMATA_ATTESA_S.get(classe, 30)
        log.warning(
            "  🔁 retry: '%s' died (%s) — attempt %d/%d in %d s",
            name,
            CLASSI_EN.get(classe, classe),
            tentativo + 1,
            consentiti,
            attesa,
        )
        time.sleep(attesa)
    return False


def _cede_per_memoria(result) -> bool:
    ""


    testo = f"{getattr(result, 'stdout', '') or ''}\n{getattr(result, 'stderr', '') or ''}".lower()
    if "another instance" in testo or "lock" in testo:
        return False
    return "memoria" in testo or "pressione" in testo or "memory" in testo


def _run_script_una_volta(
    name: str,
    script_path: Path,
    extra_args: list[str] | None = None,
    expected_output: Path | None = None,
    *,
    timeout_s: int | None = None,
) -> tuple[bool, str]:
    ""
    cmd = [sys.executable, str(script_path)]
    if extra_args:
        cmd.extend(extra_args)

    log.info(f"\n{'=' * 60}")
    log.info(f"RUNNING: {name} ({script_path.name} {' '.join(extra_args or [])})")
    log.info(f"{'=' * 60}")






    _budget = _wait_and_budget(name)




    dal_chiamante = timeout_s is not None
    if dal_chiamante:
        log.info("  Timeout for this step: %.1f h (L1 read cap)", timeout_s / 3600)
    else:
        timeout_s = _timeout_step(name)
    if not dal_chiamante and timeout_s != STEP_TIMEOUT_DEFAULT_S:





        misurato = STEP_DURATA_MISURATA_S.get(name)
        if name in STEP_TIMEOUT_OVERRIDE_S or misurato is None:
            log.info(
                "  Timeout for this step: %.1f h (cap declared in STEP_TIMEOUT_OVERRIDE_S)",
                timeout_s / 3600,
            )
        else:
            misura, dove = misurato
            log.info(
                "  Timeout for this step: %.1f h (%dx the measured duration of %d s — %s)",
                timeout_s / 3600,
                STEP_TIMEOUT_MARGINE,
                misura,
                dove,
            )





    posto = _registra_nel_budget(name, _budget)
    t0 = time.time()
    status = "completed"
    exit_code = None
    try:
        result = _run_guarded(cmd, timeout=timeout_s, budget=_budget, name=name)
        elapsed = time.time() - t0
        exit_code = result.returncode


        if result.stdout:
            for line in result.stdout.strip().split("\n")[-20:]:
                log.info(f"  {line}")
        if result.returncode == EXIT_LOCK_ATTIVO and _cede_per_memoria(result):




            log.warning(
                "  YIELDS ITS SLOT FOR MEMORY (exit 75) after %.1f s: retry when the Mac has space",
                elapsed,
            )
            _mostra_stderr(name, result.stderr, fallito=True)
            _log_metrics(name, script_path, "yield_memoria", elapsed, exit_code)
            _dlq_add_failure(
                name,
                script_path,
                "Exit 75: yields its slot for memory",
                "memory_yield",
                stderr=result.stderr,
            )
            return False, "memoria_pressione"
        if result.returncode == EXIT_LOCK_ATTIVO:



            log.error(
                "  LOCK HELD by another instance (exit 75) after %.1f s: the stage did NOT run",
                elapsed,
            )
            _mostra_stderr(name, result.stderr, fallito=True)
            _log_metrics(name, script_path, "lock", elapsed, exit_code)
            _dlq_add_failure(
                name, script_path, "Exit 75: lock held", "lock_tenuto", stderr=result.stderr
            )
            return False, "lock"
        if result.returncode != 0:
            ucciso = getattr(result, "guard_kill", None)
            if ucciso in ("budget", "pressione"):
                log.error("  KILLED by the memory guardian (%s) in %.1fs", ucciso, elapsed)
                _mostra_stderr(name, result.stderr, fallito=True)
                _log_metrics(name, script_path, f"killed_{ucciso}", elapsed, exit_code)
                picco = (getattr(result, "picco", 0) or 0) / 1024**3


                _dlq_add_failure(
                    name,
                    script_path,
                    f"Memory guardian: {ucciso} (peak {picco:.1f} GB)",
                    "memory_kill",
                )
                return False, f"memoria_{ucciso}"
            log.error(f"  FAILED (exit {result.returncode}) in {elapsed:.1f}s")
            _mostra_stderr(name, result.stderr, fallito=True)
            status = "failed"
            _log_metrics(name, script_path, status, elapsed, exit_code)
            if result.returncode in _SEGNALI_DA_FUORI:



                chiesto = _stop_chiesto_dall_app()
                _dlq_add_failure(
                    name,
                    script_path,
                    f"Exit {result.returncode}: signal {-result.returncode} from outside "
                    "(not the guardian, not the time cap)",
                    "fermato",
                    stderr=result.stderr,
                    extra={
                        "status": "resolved",
                        "resolved_at": datetime.now(UTC).isoformat(),
                        "resolution_note": "stopped on request from the app",
                    }
                    if chiesto
                    else None,
                )
                return False, "fallito"



            if result.returncode == EXIT_CONFIGURAZIONE:
                # Deterministic: the same run fails the same way, so it is not retried.
                _dlq_add_failure(
                    name,
                    script_path,
                    f"Exit {result.returncode}: setup missing (not retried)",
                    "script_failure",
                    stderr=result.stderr,
                )
                return False, "configurazione"
            try:
                from conio import MARCATORE as conio
            except Exception:  # noqa: BLE001 — without the module the usual type remains
                conio = ""
            _dlq_add_failure(
                name,
                script_path,
                f"Exit {result.returncode}",
                "gate_conio" if conio and conio in (result.stderr or "") else "script_failure",
                stderr=result.stderr,
            )
            return False, "fallito"

        log.info(f"  OK in {elapsed:.1f}s")
        try:
            _controlla_lo_stadio(name, t0, elapsed, result)
        except Exception as e:  # noqa: BLE001 — a check that breaks does not make a closed stage dead
            log.warning("  end-of-stage checks not done: %s", e)





        _mostra_stderr(name, result.stderr, fallito=False)


        if expected_output and expected_output.exists():
            if expected_output.stat().st_size == 0:
                log.warning("  WARNING: %s produced empty output file: %s", name, expected_output)
        elif expected_output:
            log.warning("  WARNING: %s exited 0 but output file missing: %s", name, expected_output)

        _log_metrics(name, script_path, status, elapsed, exit_code)
        return True, ""

    except subprocess.TimeoutExpired:
        elapsed = time.time() - t0


        log.error("  TIMEOUT after %.0f s (%.1f h)", timeout_s, timeout_s / 3600)
        _log_metrics(name, script_path, "timeout", elapsed, -2)
        _dlq_add_failure(name, script_path, f"Timeout after {timeout_s}s", "timeout")
        return False, "timeout"
    except Exception as e:
        elapsed = time.time() - t0
        log.error(f"  ERROR: {e}")
        _log_metrics(name, script_path, "error", elapsed, -1)
        _dlq_add_failure(name, script_path, str(e)[:500], type(e).__name__)
        return False, "errore"
    finally:
        if posto is not None:
            posto.release()


def _registra_nel_budget(name: str, budget):
    ""
    if budget is None:
        return None
    try:
        from sbk_resources import Lease

        frac = budget.job_bytes / budget.total_ram
        posto = Lease(f"pipeline:{name}", need_frac=frac, klass="pipeline")
        posto.registra(frac)
        return posto
    except Exception as e:  # noqa: BLE001 — the shared budget is a bonus: the step starts anyway
        log.warning("  [resources] slot in shared budget not registered: %s", e)
        return None


def _quando_ultima_estrazione() -> str:
    ""





    try:
        d = json.loads(KNOWLEDGE_LAST_EXTRACTION_FILE.read_text(encoding="utf-8"))
        return str(d.get("last_extraction", ""))
    except (OSError, ValueError, TypeError):
        return ""


def _allarme_silenzio_kb() -> None:
    ""






    giorni = kb_giorni_di_silenzio()
    if giorni is None and not KNOWLEDGE_LAST_EXTRACTION_FILE.parents[1].exists():
        # A fresh install: no knowledge folder at all yet, so there is no silence to report.
        log.info("  KB: not built yet (nothing downloaded or read so far).")
        return
    if giorni is None:
        log.error(
            "  ⛔ I don't know when the KB last received data (%s missing or unreadable).",
            KNOWLEDGE_LAST_EXTRACTION_FILE,
        )
        return
    if giorni >= KB_SILENZIO_GIORNI:
        log.error(
            "  ⛔ The knowledge store has not received data for %.0f days (threshold %d). "
            "Ingestion idle. What to do: "
            "uv run python tools/cross-source/xs-pipeline-run.py --ingest "
            "(free, rereads the sources already on disk) or --all (includes the two "
            "paid stages, asks for consent).",
            giorni,
            KB_SILENZIO_GIORNI,
        )
    else:
        log.info("  KB: last extraction %.1f days ago.", giorni)


def _gate_estrazione_passata(prima: str, stage_ok: bool) -> list[str]:
    ""












    dopo = _quando_ultima_estrazione()
    if not stage_ok:
        return []
    if not dopo:
        riga = (
            "Knowledge extract exited 0 but last-extraction.json is missing or unreadable: "
            "it is NOT proven that the KB received anything"
        )
        log.error("  ⛔ %s", riga)
        return [riga]
    if dopo == prima:
        riga = (
            f"Knowledge extract exited 0 but last-extraction.json did not advance "
            f"(stuck at {dopo}): the KB received nothing in this run"
        )
        log.error("  ⛔ %s", riga)
        return [riga]
    log.info("  ✅ Extraction recorded: last-extraction.json now says %s", dopo)
    return []








AVVISO_QUALITA = "ratchet PEGGIORATI"


def _di_qualita(avvisi: list) -> tuple[list[str], list[str]]:
    ""
    qualita = [str(a) for a in avvisi if str(a).startswith(AVVISO_QUALITA)]
    return [a for a in avvisi if not str(a).startswith(AVVISO_QUALITA)], qualita














NOTA_VOTI_VECCHI = "quality scores from an earlier run for"

NOTA_VELOCI = "steps closed in under a tenth of their usual time"

NOTA_ERRORI = "steps closed with error lines"
NOTA_MAI_COSTRUITE = "sources declared but never built"
NOTA_MAI_RILETTE = "sources downloaded and never reread"
NOTA_L0_INDIETRO = "L0 behind its own schedule"
NOTA_L0_NON_MISURABILE = "L0 not measurable for"
NOTA_FUORI_REGISTRO = "sources the pipeline runs but the registry does not know"
# Start of each status note -> the short label of the run summary (" · sources to connect: 2").
NOTE_FONTI = {
    NOTA_MAI_COSTRUITE: "sources to connect",
    NOTA_MAI_RILETTE: "sources downloaded and never reread",
    NOTA_L0_INDIETRO: "sources behind",
    NOTA_L0_NON_MISURABILE: "unmeasurable sources",
    NOTA_FUORI_REGISTRO: "sources outside the registry",
    NOTA_VOTI_VECCHI: "sources with old quality scores",
    NOTA_VELOCI: "steps too fast",
    NOTA_ERRORI: "steps closed with errors in the registry",
}
# The same notes as older versions wrote them (Italian), still recognised when old run logs are read.
NOTE_FONTI_VECCHIE = {
    "sorgenti dichiarate e mai costruite": "sources to connect",
    "sorgenti che si scaricano ma nessuno rilegge": "sources downloaded and never reread",
    "L0 oltre il proprio ritmo": "sources behind",
    "L0 non misurabile per": "unmeasurable sources",
    "sorgenti che la pipeline lancia ma il registro non conosce": "sources outside the registry",
    "voti di qualita' del giro prima per": "sources with old quality scores",
    "step chiusi in meno di un decimo del solito": "steps too fast",
    "step chiusi con righe di errore": "steps closed with errors in the registry",
}
AVVISO_PRIMA = "before starting"
# Prefix written by older versions, still recognised when old run logs are read.
AVVISI_PRIMA_VECCHI = ("prima di partire",)


def _note_di_stato(avvisi: list) -> tuple[list, list[str]]:
    ""
    inizi = (*NOTE_FONTI, *NOTE_FONTI_VECCHIE, AVVISO_PRIMA, *AVVISI_PRIMA_VECCHI)
    note = [str(a) for a in avvisi if str(a).startswith(inizi)]
    return [a for a in avvisi if not str(a).startswith(inizi)], note


def _nota_qualita_dei_segnali() -> str:
    ""




    try:
        meta = json.loads((ENRICHED_DIR / "signal-quality-index.json").read_text(encoding="utf-8"))
        mancanti = meta.get("_meta", {}).get("fonti_mancanti") or {}
    except (OSError, ValueError, AttributeError):
        return ""
    if not isinstance(mancanti, dict) or not mancanti:
        return ""
    fonti = sorted(mancanti)
    return f"{NOTA_VOTI_VECCHI}: {', '.join(fonti)} — " + "; ".join(
        f"{f} {mancanti[f]}" for f in fonti
    )


def _fonti_non_indicizzate() -> dict[str, str]:
    ""
    try:
        d = json.loads(FONTI_NON_INDICIZZATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    fonti = d.get("fonti") if isinstance(d, dict) else None
    return {str(k): str(v) for k, v in fonti.items()} if isinstance(fonti, dict) else {}


def _coda_note(note: list[str]) -> str:
    ""
    pezzi = []
    etichette = {**NOTE_FONTI_VECCHIE, **NOTE_FONTI}
    for nota in note:
        inizio = next((k for k in etichette if nota.startswith(k)), None)
        if inizio:
            elenco = nota[len(inizio) :].lstrip(": ").split(" (", 1)[0].split(" — ", 1)[0]
            n = len([x for x in elenco.split(",") if x.strip()])
            pezzi.append(f" · {etichette[inizio]}: {n}")
    prima = sum(1 for nota in note if nota.startswith((AVVISO_PRIMA, *AVVISI_PRIMA_VECCHI)))
    if prima:
        pezzi.append(f" · pre-start notes: {prima}")
    return "".join(pezzi)


def _avvisi_estrazione() -> list[str]:
    ""














    try:
        d = json.loads(KNOWLEDGE_LAST_EXTRACTION_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as e:
        return [f"extraction safeguards NOT read ({type(e).__name__})"]
    st = (d.get("stats") or {}) if isinstance(d, dict) else {}
    fuori = []
    conio = st.get("conio") or {}
    if conio.get("rosso"):
        fuori.append("CONIO GATE RED: " + str(conio.get("perche") or ""))
    for riga in fuori:
        log.error("  ⛔ %s", riga)
    return fuori


def _avviso_l1_non_aggiornato(mode: str) -> None:
    ""














    log.info("\n=== ⚠️  This command does NOT update the sources ===")
    log.info(
        "  %s rebuilds L2+L3 from what L1 has ALREADY written to disk. "
        "No new email, chat, call or CRM record enters from here.",
        FLAG_MODO.get(mode, mode),
    )
    interactions = WATCHED_FILES.get("interactions")
    if interactions is not None and interactions.exists():
        eta_h = (time.time() - interactions.stat().st_mtime) / 3600
        log.info(
            "  Last L1 data on disk (%s): %.0f days ago (%.0f h).",
            interactions.name,
            eta_h / 24,
            eta_h,
        )
    log.info(
        "  To reread the sources from the L0 files already on disk: "
        "uv run python tools/cross-source/xs-pipeline-run.py --ingest "
        "(or --all, which also includes the two paid stages)."
    )











L0_CARTELLA_DIVERSA = {
    "email": "emails",
    "calendar": "calendars",
    "voicememos": "voice-memos",
}


L0_MAX_FILE_SCANSIONATI = 4000


def _l0_dir(sorgente: str) -> Path:



    import sorgenti as _reg

    base = _reg.sorgente_di(sorgente)
    return DATA_ROOT / L0_CARTELLA_DIVERSA.get(base, base)
















NON_E_DATO = (
    "*.log",
    "*_summary.json",
    "*-summary.json",
    "*summary*.json",
    "*-index.json",
    "*index.json",
    "accounts.json",
    "*checkpoint*",
    "*-config.json",
    "*-cache.json",
    "*-partial.json",
    "*-to-scrape.json",
    "*.bak",
    "*.backup*",
)


def _e_dato(f: Path) -> bool:
    from fnmatch import fnmatch

    return not any(fnmatch(f.name, m) for m in NON_E_DATO)


def _mtime_piu_recente(radice: Path, *, salta: tuple[str, ...] = ("processed",)) -> float | None:
    ""




    if not radice.exists():
        return None
    piu_recente = None
    visti = 0
    pile = [radice]
    while pile and visti < L0_MAX_FILE_SCANSIONATI:
        cur = pile.pop()
        try:
            for e in os.scandir(cur):
                if visti >= L0_MAX_FILE_SCANSIONATI:
                    break
                if e.is_dir(follow_symlinks=False):
                    if e.name not in salta and not e.name.startswith("."):
                        pile.append(Path(e.path))
                    continue
                visti += 1
                if not _e_dato(Path(e.path)):
                    continue
                try:
                    m = e.stat().st_mtime
                except OSError:
                    continue
                if piu_recente is None or m > piu_recente:
                    piu_recente = m
        except OSError:
            continue
    return piu_recente


def eta_l0() -> dict[str, float | None]:
    ""





    import sorgenti as _reg





    sorgenti = sorted({*L1_SCRIPTS_PRE, *L1_SCRIPTS_BASE, *L1_SCRIPTS_DEPENDENT})
    if ENABLED_SOURCES:
        # enabled_sources set: the age of the sources it lists only (empty = every source).
        sorgenti = sorted(_solo_abilitate(dict.fromkeys(sorgenti), set()))
    return {s: _eta_di(s, _reg) for s in sorgenti}


def _eta_di(sorgente: str, reg) -> float | None:
    ""

















    radice = _l0_dir(sorgente)
    modelli = reg.dato_di(sorgente)
    if not modelli:
        return _mtime_piu_recente(radice)
    if not radice.exists():
        return None
    tempi = [
        f.stat().st_mtime for m in modelli for f in radice.glob(m) if f.is_file() and _e_dato(f)
    ]



    return max(tempi) if tempi else None


def _stampa_eta_l0() -> list[str]:
    ""








    import sorgenti as _reg

    misure = eta_l0()
    ora = time.time()
    note = []
    log.info("\n=== L0 age (the KB will reach THIS date, not today) ===")
    assenti, vecchie, fuori_registro = [], [], []
    for sorgente, m in sorted(misure.items()):
        giorni = None if m is None else (ora - m) / 86400
        livello, frase = _reg.giudizio(sorgente, giorni)
        if livello == "chiusa":
            log.info("  %s", frase)
            continue
        if m is None and _non_ancora_scaricata(sorgente):
            # No folder under the data root: never downloaded or imported. Not an age problem.
            log.info("  %-12s not downloaded yet", sorgente)
            continue
        if livello == "ignota":
            (fuori_registro if sorgente not in _reg.SORGENTI else assenti).append(sorgente)
            log.warning("  ⚠️  %s", frase)
            continue
        if m is None:


            log.info("  %s", frase)
            continue

        quando = datetime.fromtimestamp(m, UTC).astimezone().strftime("%Y-%m-%d %H:%M")
        riga = f"  {sorgente:<12} {quando}  ({giorni:.1f} days ago)"
        if livello == "attenzione":
            vecchie.append(f"{sorgente} {giorni:.0f}g")
            log.warning("%s  ⚠️  %s", riga, frase.split(": ", 1)[1])
        else:
            log.info(riga)







    solo_l0 = sorted(k for k, v in _reg.attive().items() if not v.l1)
    if solo_l0:
        log.warning(
            "  ◐ downloaded but never reread (%d): %s — the data piles up and no one opens it",
            len(solo_l0),
            ", ".join(solo_l0),
        )
        note.append(f"{NOTA_MAI_RILETTE}: " + ", ".join(solo_l0))

    mancanti = _reg.da_costruire()
    if mancanti:
        log.warning(
            "  ○ declared but never built (%d): %s",
            len(mancanti),
            ", ".join(sorted(mancanti)),
        )
        note.append(
            f"{NOTA_MAI_COSTRUITE}: {', '.join(sorted(mancanti))} "
            "(list and reason in tools/sorgenti.py)"
        )

    if vecchie:
        note.append(f"{NOTA_L0_INDIETRO}: " + ", ".join(vecchie))
    if assenti:
        note.append(f"{NOTA_L0_NON_MISURABILE}: " + ", ".join(assenti))
    if fuori_registro:
        note.append(
            f"{NOTA_FUORI_REGISTRO}: "
            + ", ".join(fuori_registro)
            + " — declare them in tools/sorgenti.py"
        )
    log.info(
        "  The L0 download is NOT orchestrated from here: to update it "
        "`tools/cross-source/xs-l0-refresh.py` (all sources, `--only` for some)."
    )
    return note














SOGLIA_VUOTI_RELAZIONI = 0.05
RELAZIONI_PARQUET = DATA_ROOT / "l3" / "nlp" / "relationship-facts.parquet"

REGISTRO_RIPARAZIONI = DATA_ROOT / "l3" / "meta" / "riparazioni.json"


CURA_RIGENERA = "uv run python tools/cross-source/xs-l3-rigenera-relazioni.py --scrivi"


CURA_COPIA = "uv run python tools/cross-source/xs-l0-refresh.py --brain-copy"


GIORNI_RETE = 7

FONTI_NON_INDICIZZATE = DATA_ROOT / "l3" / "vectordb" / "fonti-non-indicizzate.json"


def registro_riparazioni() -> dict:
    ""
    try:
        d = json.loads(REGISTRO_RIPARAZIONI.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def salute_parquet_relazioni(percorso: Path | None = None) -> dict:
    ""





    percorso = percorso or RELAZIONI_PARQUET
    esito = {
        "percorso": str(percorso),
        "righe": 0,
        "vuoti": None,
        "schema_version": None,
        "sano": True,
        "perche": "",
    }
    if not percorso.exists():


        esito["perche"] = "parquet missing (not yet extracted)"
        return esito
    try:
        import pyarrow.parquet as pq

        tab = pq.read_table(percorso, columns=["predicate", "object"])
        righe = tab.num_rows
        esito["righe"] = righe
        if righe:
            vuoti = 0
            pred = tab.column("predicate").to_pylist()
            obj = tab.column("object").to_pylist()
            for p, o in zip(pred, obj, strict=False):
                if not str(p or "").strip() or not str(o or "").strip():
                    vuoti += 1
            esito["vuoti"] = vuoti / righe
    except Exception as e:  # noqa: BLE001 — misura opzionale, mai fatale
        esito["perche"] = f"symptom NOT measured ({type(e).__name__}: {e})"
        return esito

    try:
        from sbk_config import leggi_sidecar_schema

        esito["schema_version"] = leggi_sidecar_schema(percorso)
    except Exception:  # noqa: BLE001
        esito["schema_version"] = None

    quota = esito["vuoti"]
    if quota is not None and quota > SOGLIA_VUOTI_RELAZIONI:
        fatta = registro_riparazioni().get("rigenera-relazioni")
        esito["sano"] = False
        esito["perche"] = (
            f"{quota:.1%} of the {esito['righe']} rows have empty `predicate` or `object` "
            f"(threshold {SOGLIA_VUOTI_RELAZIONI:.0%}). "
            + (
                f"The registry says the regeneration was already done on {fatta.get('quando')} "
                f"and the symptom did NOT clear: open the case, do not rerun blindly."
                if fatta
                else f"One-shot repair NEVER run. The cure is: {CURA_RIGENERA}"
            )
        )
    return esito


def _store_da_proteggere() -> bool:
    """True if <data root>/knowledge holds at least one file (same test as backup_kb)."""
    kb = DATA_ROOT / "knowledge"
    try:
        return kb.is_dir() and any(p.is_file() for p in kb.rglob("*"))
    except OSError:
        return True


def _tar_dello_store() -> tuple[float | None, str]:
    ""




    try:
        import importlib.util

        perc = _TOOLS_DIR / "util" / "sb-kb-ripara.py"
        spec = importlib.util.spec_from_file_location("sb_kb_ripara_per_pipeline", perc)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        tar = m.tar_piu_recente()
    except Exception as e:  # noqa: BLE001
        return None, f"store tar not verifiable ({type(e).__name__})"
    if tar is None:
        return None, "no store tar found"
    return tar.stat().st_mtime, str(tar)


def _fai_la_copia_del_cervello() -> bool:
    ""



    log.warning(
        "  ⚠️  the brain copy is old or missing: making it now, before changing it"
    )
    t0 = time.time()
    try:
        r = subprocess.run(
            [
                sys.executable,
                str(_TOOLS_DIR / "cross-source" / "xs-l0-refresh.py"),
                "--brain-copy",
                "--dir",
                str(DATA_ROOT / "logs" / "copie-del-cervello"),
            ],
            capture_output=True,
            text=True,
            timeout=3600,
        )
    except (OSError, subprocess.SubprocessError) as e:
        log.error("  ⛔ brain copy failed: %s", e)
        return False
    quando, dove = _tar_dello_store()
    buona = r.returncode == 0 and quando is not None
    buona = buona and (time.time() - quando) / 86400 <= GIORNI_RETE
    if buona:
        log.info("  brain copy done in %.0f s: %s", time.time() - t0, dove)
    else:
        coda = (r.stdout + r.stderr).strip()[-300:]
        log.error("  ⛔ brain copy failed (exit %s): %s", r.returncode, coda)
    return buona





def _chiave_api_presente() -> bool:
    ""




    if os.environ.get("ANTHROPIC_API_KEY"):
        return True
    try:
        from dotenv import load_dotenv

        load_dotenv(_TOOLS_DIR.parent / ".env", override=False)
    except Exception:  # noqa: BLE001
        return False
    return bool(os.environ.get("ANTHROPIC_API_KEY"))





INGRESSI_FERMI: dict[str, tuple[tuple[Path, str], ...]] = {
    "l1_phase2": ((DATA_ROOT / "plaud" / "raw" / "_calendar_crossref.json", "no one regenerates it"),),
    "l2_merge": ((DATA_ROOT / "plaud" / "raw" / "_calendar_crossref.json", "no one regenerates it"),),
    "l1_phase3_wa_deep": (
        (
            DATA_ROOT / "whatsapp" / "attachments-index.json",
            "only the manual WhatsApp import regenerates it",
        ),
    ),
    "l2_person_deep_context": ((DATA_ROOT / "rq" / "top-150-people.json", "no one regenerates it"),),
}
GIORNI_INGRESSO_FERMO = 30


def _ingressi_fermi(dentro: list) -> list[str]:
    ""
    fermi: dict[Path, tuple[str, set[str]]] = {}
    for p in dentro:
        for f, chi in INGRESSI_FERMI.get(p.id, ()):
            if f.exists() and (time.time() - f.stat().st_mtime) / 86400 > GIORNI_INGRESSO_FERMO:
                fermi.setdefault(f, (chi, set()))[1].add(p.nome)
    return [
        f"input idle since {datetime.fromtimestamp(f.stat().st_mtime):%d/%m/%Y}, {chi}: "
        f"{f.name}, read by {', '.join(sorted(stadi))}"
        for f, (chi, stadi) in sorted(fermi.items())
    ]


def precondizioni(modo: str) -> tuple[dict[str, str], list[str]]:
    ""











    dentro = perimetro(modo)
    richieste = {c for p in dentro for c in p.precondizioni}
    blocchi: dict[str, str] = {}
    avvisi: list[str] = _ingressi_fermi(dentro)

    if "chiave_api" in richieste and not _chiave_api_presente():
        blocchi["chiave_api"] = (
            "no model key, ANTHROPIC_API_KEY is not set: the paid stages cannot start. "
            "What to do: put it in .env (or in the environment) and rerun, or use "
            "--ingest to declare that you accept a free run."
        )

    # Phase 2 reads tactiq and plaud: with enabled_sources listing neither, it does not run.
    # A source never downloaded (no folder under the data root) is not read either.
    if (
        "contacts_merged_del_run_precedente" in richieste
        and _togli_mai_scaricate(_solo_abilitate(dict(L1_SCRIPTS_DEPENDENT), set()))[0]
    ):
        cm = WATCHED_FILES.get("contacts_merged")
        if cm is None or not cm.exists():
            avvisi.append(
                "L1 phase 2 (tactiq/plaud) starts without contacts-merged.parquet: "
                "it is the L2 output of the PREVIOUS run (cross-run circularity, not a bug). "
                "On the very first run it uses the calendar+email fallback; from the second it will be full."
            )
        else:
            giorni = (time.time() - cm.stat().st_mtime) / 86400
            if giorni > 14:
                avvisi.append(
                    f"contacts-merged.parquet is {giorni:.0f} days old: L1 phase 2 "
                    "will resolve participants against an old address book."
                )

    if "parquet_relazioni_sano" in richieste:
        salute = salute_parquet_relazioni()
        if not salute["sano"]:
            blocchi["parquet_relazioni_sano"] = (
                f"relationship-facts.parquet TRUNCATED — {salute['perche']}"
            )
        elif salute["schema_version"] is None and salute["righe"]:
            avvisi.append(
                "relationship-facts.parquet without schema sidecar: version unknown, "
                "i.e. written before the writer declared it. "
                f"Symptom measured now: {salute['vuoti']:.2%} empty of {salute['righe']} rows "
                "(below threshold: proceeding)."
            )

    if "tar_dello_store" in richieste and not _store_da_proteggere():
        # A new install: no knowledge store yet, so there is nothing to copy before the
        # first Knowledge Extract builds it.
        log.info("  brain copy not needed: no knowledge store yet (the first run builds it)")
    elif "tar_dello_store" in richieste:
        quando, dove = _tar_dello_store()
        if quando is None:
            blocchi["tar_dello_store"] = (
                f"store safety net: {dove}. What to do: {CURA_COPIA}"
            )
        else:
            giorni = (time.time() - quando) / 86400
            if giorni > GIORNI_RETE:
                blocchi["tar_dello_store"] = (
                    f"the most recent store tar is {giorni:.0f} days old ({dove}), over {GIORNI_RETE}: "
                    f"before changing the brain a new copy is needed. What to do: {CURA_COPIA}"
                )

    if "pressione_memoria" in richieste:
        try:
            from sbk_resources import SEG_YIELD, pressure

            p = pressure()
            if p.seg_ratio >= SEG_YIELD:
                avvisi.append(
                    f"the machine is already under pressure (segments {p.seg_ratio:.0%}): "
                    "the guardian will make the stages wait, the run will take longer. "
                    "uv run python tools/util/sb-pipeline-ctl.py status"
                )
        except Exception:  # noqa: BLE001
            avvisi.append("memory pressure not measurable (sbk_resources not importable)")

    return blocchi, avvisi


def coda_dei_falliti_leggibile() -> bool:
    ""




    try:
        from pipeline_dlq import get_all_failures

        get_all_failures(include_resolved=True)
        return True
    except Exception as e:  # noqa: BLE001
        log.error("  ⛔ Failure queue not readable: %s", e)
        return False









VARIABILE_CONSENSO = "SBK_ALLOW_SPEND"
# Older Italian name of the same variable, still read.
VARIABILE_CONSENSO_VECCHIA = "SBK_CONSENTI_SPESA"


VARIABILE_SPESA_STADI = "SBK_SPESA_STADI"


def _spesa_scelta(pid: str) -> bool:
    ""
    scelti = os.environ.get(VARIABILE_SPESA_STADI)
    if scelti is None:
        return True
    return pid in {s.strip() for s in scelti.split(",") if s.strip()}


def stima_spesa(passi: list[str], *, timeout_s: int = 600) -> list[str]:
    ""













    conteggi = {
        "l3_extract": (
            "l3_extract",
            ["--dry-run", "--all-sources", "--incremental", "--batch-api"],
        ),
        "l3_extract_rel": ("l3_extract_rel", ["--dry-run", "--incremental", "--batch-api"]),
        "l3_deep_extract": ("l3_deep_extract", ["--dry-run", "--incremental", "--batch-api"]),
    }
    righe = []
    for pid in passi:
        chiave, argomenti = conteggi.get(pid, (None, None))
        script = SCRIPTS.get(chiave) if chiave else None
        if script is None or not script.exists():
            righe.append(f"  {pid}: estimate not available (script missing)")
            continue
        try:
            r = subprocess.run(
                [sys.executable, str(script), *argomenti],
                capture_output=True,
                text=True,
                timeout=timeout_s,
            )
            testo = ((r.stdout or "") + "\n" + (r.stderr or "")).strip().splitlines()
            utili = [x for x in testo if re.search(r"\d", x)][-6:]
            if utili:
                righe.append(f"  {pid}:")
                righe.extend(f"     {x.strip()[:160]}" for x in utili)
            else:
                righe.append(f"  {pid}: the count produced no numbers (exit {r.returncode})")
        except subprocess.TimeoutExpired:
            righe.append(f"  {pid}: estimate NOT available (the count exceeded {timeout_s}s)")
        except Exception as e:  # noqa: BLE001
            righe.append(f"  {pid}: estimate NOT available ({type(e).__name__})")
    return righe


def consenso_spesa(passi: list[str], *, consenti_flag: bool, salta_stima: bool = False) -> bool:
    ""








    variabile = next(
        (v for v in (VARIABILE_CONSENSO, VARIABILE_CONSENSO_VECCHIA) if os.environ.get(v, "").strip()),
        VARIABILE_CONSENSO,
    )
    if consenti_flag or os.environ.get(variabile, "").strip().lower() in (
        "1",
        "si",
        "sì",
        "yes",
        "true",
    ):
        log.warning(
            "  Spending consent DECLARED (%s): the paid stages will start — %s",
            "--allow-spend" if consenti_flag else variabile,
            ", ".join(passi),
        )
        return True

    if not sys.stdin.isatty():
        return False

    log.info("\n=== PAID stages in this run ===")
    log.info("  %s", ", ".join(passi))
    if salta_stima:
        log.info("  (estimate of pending documents skipped on request)")
    else:
        log.info("  Counting pending documents (no paid call)...")
        for riga in stima_spesa(passi):
            log.info("%s", riga)
    log.info(
        "  The cost is not written here: it depends on the documents above and on current "
        "prices."
    )
    try:
        risposta = input("\nAuthorize spending for these stages? [yes/NO] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    return risposta in ("s", "si", "sì", "y", "yes")





EXIT_LOCK_ATTIVO = 75
EXIT_INCOMPLETO = 2
EXIT_FALLITO = 1


def esito(
    *,
    piano: list[str],
    eseguiti: list[str],
    saltati: list,
    morti: list[str],
    avvisi: list[str],
    coda_leggibile: bool,
    modo: str,
    fonti_non_chiuse: list[str] | None = None,
) -> tuple[str, int]:
    ""






























    n_piano = len(perimetro(modo))
    fonti = sorted(set(fonti_non_chiuse or []))
    coda_fonti = f", sources not closed: {', '.join(fonti)}" if fonti else ""






    avvisi, qualita = _di_qualita(avvisi)
    coda_qualita = f" · quality to check: {len(qualita)}" if qualita else ""
    avvisi, note_stato = _note_di_stato(avvisi)
    coda_qualita += _coda_note(note_stato)



    salti = [s if isinstance(s, Salto) else Salto(str(s), "motivo_non_dichiarato") for s in saltati]
    # a stage that did not close and let the chain go on is declared: it is in "sources not closed"
    dichiarati = set(eseguiti) | {s.id for s in salti} | set(morti) | set(fonti)
    fantasmi = [x for x in piano if x not in dichiarati]
    gravi = [s for s in salti if not s.innocuo]
    innocui = [s for s in salti if s.innocuo]

    def _coda_innocui() -> str:
        if not innocui:
            return ""
        conta: dict[str, int] = {}
        for s in innocui:
            conta[s.motivo] = conta.get(s.motivo, 0) + 1
        parole = {**MOTIVI_EN, "ripreso": "resumed from the stopped run"}
        return " (" + ", ".join(f"{n} {parole.get(m, m)}" for m, n in conta.items()) + ")"

    if not coda_leggibile:
        return (
            f"Pipeline OUTCOME NOT VERIFIABLE — failure queue unreadable "
            f"({len(eseguiti)}/{n_piano} stages run, the dead cannot be counted)",
            EXIT_FALLITO,
        )
    if morti:
        return (
            f"Pipeline FAILED — dead: {', '.join(sorted(morti))} "
            f"({len(eseguiti)}/{n_piano} run){coda_fonti}",
            EXIT_FALLITO,
        )
    if fantasmi:
        return (
            f"Pipeline INCOMPLETE — {len(eseguiti)}/{n_piano}, "
            f"stages vanished without being declared: {', '.join(fantasmi)}{coda_fonti}",
            EXIT_INCOMPLETO,
        )
    if gravi or avvisi or fonti:
        pezzi = [f"Pipeline INCOMPLETE — {len(eseguiti)}/{n_piano}{_coda_innocui()}{coda_qualita}"]
        if fonti:
            pezzi.append("sources not closed: " + ", ".join(fonti))
        if gravi:
            pezzi.append("skipped: " + ", ".join(str(s) for s in sorted(gravi, key=lambda x: x.id)))
        if avvisi:
            pezzi.append(f"warnings: {len(avvisi)}")
        return (", ".join(pezzi), EXIT_INCOMPLETO)
    return (f"Pipeline Complete — {len(eseguiti)}/{n_piano}{_coda_innocui()}{coda_qualita}", 0)


def _aspetta_pausa(prima_di: str) -> None:
    ""





    run_dir, run_id = os.environ.get("SBK_RUN_DIR"), os.environ.get("SBK_RUN_ID")
    if not run_dir or not run_id:
        return
    f = Path(run_dir) / f"{run_id}.pausa"
    if not f.exists():
        return
    t0 = time.time()
    log.warning("⏸ PAUSE before %s: resumes when the app removes it", prima_di)
    while f.exists():
        time.sleep(2)
    log.warning("▶ RESUME after %d s, before %s", int(time.time() - t0), prima_di)










def stadi_prima_della_spesa() -> list[Passo]:
    ""

    primo = next(i for i, p in enumerate(CATENA) if p.tipo == "pagato")
    return [
        p
        for p in CATENA[:primo]
        if p.tipo != "fuori_ciclo" and (p.tipo != "a_richiesta" or p.id in STADI_A_RICHIESTA_ACCESI)
    ]


def leggi_esito_l1() -> dict | None:
    ""
    try:
        d = json.loads(L1_ESITO_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) else None


def leggi_cancello() -> dict | None:
    ""
    try:
        d = json.loads(CANCELLO_SPESA_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) else None


def _scrivi_stato(percorso: Path, stato: dict) -> None:
    ""

    try:
        percorso.parent.mkdir(parents=True, exist_ok=True)
        safe_write_json(percorso, stato)
    except OSError as e:
        log.error("  ⛔ %s not written (%s): the next run will find it old", percorso.name, e)


def problemi_cancello_salvato(stato: dict | None) -> list[str]:
    ""
    if not stato:
        return [
            "no run has yet closed the chain before the paid steps, so it cannot be verified"
        ]
    problemi = [str(p) for p in stato.get("problemi") or []]
    if stato.get("aperto") is True and not problemi:
        return []
    quando = str(stato.get("quando") or "?")[:16]
    return [f"the last run ({quando}) did not close everything: {p}" for p in problemi] or [
        f"the last run ({quando}) left the gate closed"
    ]


def cancello_spesa(
    *,
    modo: str,
    eseguiti: list[str],
    salti: list[Salto],
    morti: list[str],
    fonti_non_chiuse: list[str] | None = None,
    lettura_filtrata: list[str] | None = None,
    scarico_non_chiuso: list[str] | None = None,
    esito_l1: dict | None = None,
) -> list[str]:
    ""






    problemi = [f"download of {s} not closed" for s in scarico_non_chiuso or []]
    problemi += [f"read of {f} not closed" for f in fonti_non_chiuse or []]
    if lettura_filtrata:
        problemi.append(f"read of only {', '.join(lettura_filtrata)} (--only)")
    per_id = {s.id: s for s in salti}
    nel_perimetro = {p.id for p in perimetro(modo)}
    lettura_ripresa = False
    for p in stadi_prima_della_spesa():
        if p.id in (fonti_non_chiuse or []):
            continue
        if p.id not in nel_perimetro:
            problemi.append(f"{p.nome} outside {FLAG_MODO[modo]}")
        elif p.id in eseguiti:
            continue
        elif p.id in morti:
            problemi.append(f"{p.nome} did not close")
        elif (s := per_id.get(p.id)) is None:
            problemi.append(f"{p.nome} did not start")
        elif s.motivo == "ripreso":
            lettura_ripresa = lettura_ripresa or p.strato == "L1"
        elif s.motivo == "non_elencata":
            continue
        else:
            problemi.append(f"{p.nome} skipped ({s.motivo})")
    if lettura_ripresa:
        if not esito_l1:
            problemi.append("the read of the stopped run did not leave its outcome")
        else:
            problemi += [
                f"read of {f} not closed in the stopped run"
                for f in esito_l1.get("fonti_non_chiuse") or []
            ]
            if esito_l1.get("filtro"):
                problemi.append(
                    f"the read of the stopped run was of only {', '.join(esito_l1['filtro'])}"
                )
    return problemi


def run_pipeline(
    mode: str = "auto",
    dry_run: bool = False,
    l1_gia_girato: bool = False,
    *,
    consenso_paid: bool = False,
    t_inizio_iso: str | None = None,
    stadi_gia_eseguiti: list[str] | None = None,
    avvisi_iniziali: list[str] | None = None,
    riprendi_da: str | None = None,
    solo_stadio: str | None = None,
    fonti_non_chiuse: list[str] | None = None,
    lettura_filtrata: list[str] | None = None,
    scarico_non_chiuso: list[str] | None = None,
    fasi_fuori_elenco: list[str] | None = None,
    niente_scaricato: bool = False,
) -> dict:
    ""



















    t_start = time.time()




    t_inizio_iso = t_inizio_iso or datetime.now(UTC).isoformat()

    modo = normalizza_modo(mode)
    if modo is None:
        log.error("Unknown mode: %r (expected: %s)", mode, ", ".join(MODI))
        return {
            "stages_run": [],
            "stages_skipped": [],
            "errors": [f"unknown mode: {mode}"],
            "elapsed": 0,
            "exit_code": EXIT_FALLITO,
            "intestazione": f"Pipeline FAILED — unknown mode: {mode}",
        }

    stages_run: list[str] = list(stadi_gia_eseguiti or [])
    errors: list[str] = []
    avvisi: list[str] = list(avvisi_iniziali or [])
    salti: list[Salto] = []

    fonti_ferme: list[str] = list(fonti_non_chiuse or [])
    for trovati in _CONTROLLI_DEL_RUN.values():
        trovati.clear()


    log.info("\n=== Perimeter of %s ===", FLAG_MODO.get(modo, modo))
    for riga in righe_perimetro(modo):
        log.info("  %s", riga)

    if modo in ("propaga", "ricostruisci") and not l1_gia_girato:
        _avviso_l1_non_aggiornato(modo)




    blocchi_pre, avvisi_pre = precondizioni(modo)


    avvisi.extend(f"{AVVISO_PRIMA}: {a}" for a in avvisi_pre)
    for riga in avvisi_pre:
        log.warning("  ⚠️  %s", riga)


    def _bloccato(passo: Passo) -> str:
        ""
        for c in passo.precondizioni:
            if c in blocchi_pre:
                return f"{PRECONDIZIONI_EN.get(c, c)}: {blocchi_pre[c]}"
        return ""


    if modo == "propaga":
        changes = detect_changes()
        log.info("\n=== Change Detection ===")
        for name, changed in changes.items():
            log.info("  %s: %s", name, "CHANGED" if changed else "unchanged")




        rifare = stadi_da_rifare(changes)
        run_merge = bool(rifare.get("l2_merge"))
        run_graph = run_merge or bool(rifare.get("l3_graph"))




        run_kb = run_merge or bool(rifare.get("l2_knowledge_extract"))
        run_index = run_merge or bool(rifare.get("l3_index"))
        run_fact_index = run_graph or bool(rifare.get("l3_fact_index"))
        merge_incremental = not changes.get("entity_map", False)




        index_incremental = True
        graph_incremental = True
        decay_incremental = True
        tutto_invariato = not any(changes.values())
    else:


        run_merge = run_graph = run_index = run_fact_index = run_kb = True
        merge_incremental = False
        index_incremental = True
        graph_incremental = False
        decay_incremental = False
        tutto_invariato = False




    decisione: dict[str, bool] = {}
    motivo_salto: dict[str, tuple[str, str]] = {}

    def _decidi(passo: Passo, gira: bool, motivo: str = "invariato", dettaglio: str = "") -> None:
        blocco = _bloccato(passo)




        if gira and blocco and passo.tipo == "pagato":
            gira, motivo, dettaglio = False, "precondizione", blocco
        decisione[passo.id] = gira
        if not gira:
            motivo_salto[passo.id] = (motivo, dettaglio)


    ids_perimetro = [p.id for p in perimetro(modo)]
    ripresi = (
        set(ids_perimetro[: ids_perimetro.index(riprendi_da)])
        if riprendi_da in ids_perimetro
        else set()
    )
    for passo in perimetro(modo):
        if passo.id in ripresi:
            _decidi(
                passo, False, "ripreso", f"closed in the stopped run, resuming from {riprendi_da}"
            )
            continue
        if solo_stadio:


            if passo.id != solo_stadio:
                _decidi(passo, False, "fuori_dal_singolo", f"single-stage run {solo_stadio}")
            elif passo.tipo == "pagato":
                _decidi(
                    passo,
                    consenso_paid or dry_run,
                    "non_autorizzato",
                    "spending not authorized: --allow-spend",
                )
            else:
                _decidi(passo, True)
            continue
        if niente_scaricato and passo.strato != "L1":
            # A first install with nothing downloaded or imported yet: nothing to merge or build.
            _decidi(passo, False, "niente_da_leggere", "nothing downloaded or imported yet")
            continue
        if passo.strato == "L1":






            gia = set(stadi_gia_eseguiti or [])
            if passo.id not in gia and passo.id in (fasi_fuori_elenco or ()):
                _decidi(
                    passo,
                    False,
                    "non_elencata",
                    "none of its sources is in enabled_sources (sbk.config.json)",
                )
            else:
                _decidi(
                    passo,
                    passo.id in gia,
                    "a_monte",
                    "this L1 phase was not run in this run",
                )
        elif passo.tipo == "pagato":








            if consenso_paid and not _spesa_scelta(passo.id):
                _decidi(passo, False, "non_scelto", "paid step not chosen for this run")
            else:
                _decidi(
                    passo,
                    consenso_paid or dry_run,
                    "non_autorizzato",
                    "spending not authorized: --allow-spend, or answer «yes» to the question",
                )
        elif (
            passo.id == "l1_inventario"
            and ENABLED_SOURCES
            and not any(source_enabled(s) for s in ("github", "gsc", "analytics"))
        ):
            # The inventory reads only github, gsc and analytics: none of them is listed.
            _decidi(
                passo,
                False,
                "non_elencata",
                "none of github, gsc, analytics is in enabled_sources (sbk.config.json)",
            )
        elif passo.id in ("l2_merge", "l2_entity_map_cleanup"):
            _decidi(passo, run_merge, "invariato", "no L1 input changed")
        elif passo.id == "l2_knowledge_extract":
            _decidi(passo, run_kb, "invariato", "contacts-merged already seen by the KB")
        elif passo.id == "l2_ricorrenze":
            _decidi(passo, run_kb, "invariato", "KB not changed in this run")
        elif passo.id == "l3_graph":
            _decidi(passo, run_graph, "invariato", "no input changed")
        elif passo.id == "l3_index":
            _decidi(passo, run_index, "invariato", "no input changed")
        elif passo.id == "l3_fact_index":
            _decidi(passo, run_fact_index, "invariato", "no input changed")
        elif passo.id == "l3_shadow":
            _decidi(passo, run_graph, "invariato", "no input changed")
        elif passo.strato == "RQ":
            _decidi(passo, run_kb or modo != "propaga", "invariato", "no merge in this run")
        else:
            _decidi(passo, True)

    if tutto_invariato and not solo_stadio:

        for passo in perimetro(modo):
            decisione[passo.id] = False
            motivo_salto.setdefault(passo.id, ("invariato", "no data changed"))
        log.info("\nAll data unchanged — nothing to propagate")

    piano = [pid for pid, gira in decisione.items() if gira]
    salti = [Salto(pid, *motivo_salto[pid]) for pid, gira in decisione.items() if not gira]





    if "tar_dello_store" in blocchi_pre and any(
        "tar_dello_store" in CATENA_PER_ID[pid].precondizioni for pid in piano
    ):
        if dry_run:
            nota = f"{AVVISO_PRIMA}: the brain copy is old or missing, the real run makes it before starting"
            avvisi.append(nota)
            log.warning("  ⚠️  %s", nota)
            del blocchi_pre["tar_dello_store"]
        elif _fai_la_copia_del_cervello():
            del blocchi_pre["tar_dello_store"]
    for nome, messaggio in blocchi_pre.items():
        log.error("  ⛔ precondition «%s» FALSE — %s", PRECONDIZIONI_EN.get(nome, nome), messaggio)


    log.info("\n=== Pipeline Plan (%s) ===", FLAG_MODO.get(modo, modo))
    for passo in perimetro(modo):
        marca = " [PAID]" if passo.tipo == "pagato" else ""
        if passo.tipo == "pagato" and dry_run and not consenso_paid:
            marca += " — spending consent will be ASKED before starting"
        if decisione.get(passo.id) and (blocco := _bloccato(passo)):
            log.info("  ⛔ %s%s — STOPS THE LINE (precondition): %s", passo.nome, marca, blocco)
        elif decisione.get(passo.id):
            log.info("  ✓ %s%s", passo.nome, marca)
        else:
            m, d = motivo_salto.get(passo.id, ("motivo_non_dichiarato", ""))
            log.info(
                "  – %s%s — SKIPPED (%s)%s", passo.nome, marca, MOTIVI_EN.get(m, m), f": {d}" if d else ""
            )
    log.info(
        "  Total: %d stages to run of %d in the perimeter.", len(piano), len(perimetro(modo))
    )
    if any(p.tipo == "pagato" for p in perimetro(modo)):
        log.info(
            "  The paid steps start only if everything before them has closed, download and read of "
            "every source included, nothing skipped (project decision)."
        )

    if dry_run:




        log.info("\n=== DRY RUN — no script run ===")
        return {
            "stages_run": [],
            "stages_planned": piano,
            "stages_skipped": [str(s) for s in salti],
            "salti": [str(s) for s in salti],
            "errors": [],
            "avvisi": avvisi,
            "elapsed": time.time() - t_start,
            "dry_run": True,
            "l1_aggiornato": l1_gia_girato,
            "modo": modo,
            "exit_code": 0,
            "intestazione": f"DRY RUN {FLAG_MODO[modo]} — {len(piano)}/{len(perimetro(modo))} stages",
        }

    ids_prima_della_spesa = {p.id for p in stadi_prima_della_spesa()}

    def _chiudi() -> dict:
        ""
        _save_checkpoint(stages_run)


        if senza := _CONTROLLI_DEL_RUN["senza_file"]:
            avvisi.append("steps closed without writing their file: " + ", ".join(senza))
        for chiave, nota in (("veloci", NOTA_VELOCI), ("con_errori", NOTA_ERRORI)):
            if trovati := _CONTROLLI_DEL_RUN[chiave]:
                nomi = ", ".join(t.split("|", 1)[0] for t in trovati)
                avvisi.append(
                    f"{nota}: {nomi} — " + "; ".join(t.replace("|", " ") for t in trovati)
                )
        if solo_stadio in ids_prima_della_spesa and (
            solo_stadio in errors or solo_stadio in fonti_ferme
        ):


            _scrivi_stato(
                CANCELLO_SPESA_FILE,
                {
                    "quando": datetime.now(UTC).isoformat(),
                    "modo": modo,
                    "aperto": False,
                    "problemi": [
                        f"{CATENA_PER_ID[solo_stadio].nome} rerun alone did not close"
                    ],
                },
            )
        return {
            **_riepilogo(
                stages_run,
                errors,
                avvisi,
                t_inizio_iso,
                time.time() - t_start,
                modo=modo,
                salti=salti,
                piano=piano,
                fonti_non_chiuse=fonti_ferme,
            ),
            "stages_skipped": [str(s) for s in salti],
            "l1_aggiornato": l1_gia_girato,
        }

    if not piano:
        return _chiudi()



    tocca_il_prima = not solo_stadio and bool(ids_prima_della_spesa & set(piano))
    if tocca_il_prima:
        _scrivi_stato(
            CANCELLO_SPESA_FILE,
            {
                "quando": datetime.now(UTC).isoformat(),
                "modo": modo,
                "aperto": False,
                "problemi": ["the run started at this time did not reach the paid steps"],
            },
        )





    fermata: dict[str, str] = {}

    def _esegui(
        pid: str,
        args: list[str] | None = None,
        *,
        critico: bool = False,
        ferma_la_linea: bool = True,
    ) -> bool:
        ""








        passo = CATENA_PER_ID[pid]
        if fermata:
            salti.append(Salto(pid, "fermata_di_linea", fermata["chi"]))
            log.warning("  ⛔ %s does NOT start: line stopped (%s)", passo.nome, fermata["chi"])
            return False
        if blocco := _bloccato(passo):


            salti.append(Salto(pid, "precondizione", blocco))
            fermata["chi"] = f"{passo.nome}: precondition false"
            log.error(
                "⛔ LINE STOP: %s does not start, precondition false — %s", passo.nome, blocco
            )
            return False
        script = SCRIPTS.get(pid)
        if script is None or not script.exists():
            salti.append(Salto(pid, "precondizione", f"script missing: {script}"))
            log.warning("  ⚠️  %s SKIPPED: script missing (%s)", passo.nome, script)
            return False
        _aspetta_pausa(passo.nome)
        ok = run_script(passo.nome, script, args)
        if ok:
            stages_run.append(pid)
        elif not ferma_la_linea:
            fonti_ferme.append(pid)
            log.error(
                "⛔ %s did not close after the attempts: it stops, the chain goes on "
                "(the paid steps do not).",
                passo.nome,
            )
        else:
            errors.append(pid)
            fermata["chi"] = f"{passo.nome} did not close"
            log.error(
                "⛔ LINE STOP: %s did not close after the attempts — the downstream "
                "stages do not start (resume from the journal).",
                passo.nome,
            )
        return ok

    def _salta_a_valle(motivo: str, dettaglio: str) -> None:
        ""
        # fonti_ferme: stages that ran, did not close and let the chain go on (already reported)
        fatti = set(stages_run) | set(errors) | set(fonti_ferme) | {s.id for s in salti}
        for pid in piano:
            if pid not in fatti:
                salti.append(Salto(pid, motivo, dettaglio))





    if decisione.get("l1_inventario"):
        log.info("\n=== Inventory (domains, repos, people) ===")
        _esegui("l1_inventario", ferma_la_linea=False)


    if decisione.get("l2_merge"):
        if not _esegui("l2_merge", ["--incremental"] if merge_incremental else [], critico=True):
            _salta_a_valle("a_monte", "l2_merge failed")
            return _chiudi()
        if not _rubrica_con_persone():
            # The merge closed with nothing to merge, or with an empty book (a first install with
            # no source that starts a contact): every stage after it reads the merged book, so
            # none has anything to do.
            log.info("  no one in the merged book yet: the stages after the merge have nothing to read")
            _salta_a_valle("niente_da_leggere", "no source that starts a contact has data yet")
            return _chiudi()


    if decisione.get("l2_entity_map_cleanup"):



        _esegui("l2_entity_map_cleanup")



        _save_checkpoint(stages_run, solo={"entity_map"})
        log.info("  Intermediate checkpoint saved (entity-map mtime recorded)")

    if decisione.get("l2_duckdb"):
        _esegui("l2_duckdb")
    if decisione.get("l2_sqi") and _esegui("l2_sqi"):


        if nota := _nota_qualita_dei_segnali():
            avvisi.append(nota)
            log.warning("  ⚠️  %s", nota)











    pagati_nel_piano = [p.id for p in CATENA if p.tipo == "pagato" and decisione.get(p.id)]
    if pagati_nel_piano or tocca_il_prima:
        if solo_stadio:
            problemi = problemi_cancello_salvato(leggi_cancello())
        else:
            problemi = cancello_spesa(
                modo=modo,
                eseguiti=stages_run,
                salti=salti,
                morti=errors,
                fonti_non_chiuse=fonti_ferme,
                lettura_filtrata=lettura_filtrata,
                scarico_non_chiuso=scarico_non_chiuso,
                esito_l1=leggi_esito_l1() if riprendi_da else None,
            )
            _scrivi_stato(
                CANCELLO_SPESA_FILE,
                {
                    "quando": datetime.now(UTC).isoformat(),
                    "modo": modo,
                    "aperto": not problemi,
                    "problemi": problemi,
                },
            )
        if pagati_nel_piano and problemi:
            dettaglio = "before did not close everything: " + "; ".join(problemi)
            log.error("\n=== ⛔ Paid steps STOPPED, the gate is closed ===")
            for riga in problemi:
                log.error("  - %s", riga)
            for pid in pagati_nel_piano:
                decisione[pid] = False
                salti.append(Salto(pid, "cancello_spesa", dettaglio))
        elif pagati_nel_piano:
            log.info("\n=== Spending gate open: everything before has closed ===")

    paid_eseguiti = []
    if any(decisione.get(p.id) for p in CATENA if p.tipo == "pagato"):
        log.info("\n=== PAID stages (consent given) ===")

        if decisione.get("l3_extract"):
            if _esegui("l3_extract", ["--batch-api", "--all-sources", "--incremental"]):
                paid_eseguiti.append("l3_extract")
        if decisione.get("l3_extract_rel"):
            if _esegui("l3_extract_rel", ["--batch-api", "--incremental"]):
                paid_eseguiti.append("l3_extract_rel")
        if decisione.get("l3_deep_extract"):



            if _esegui("l3_deep_extract", ["--batch-api", "--incremental"]):
                paid_eseguiti.append("l3_deep_extract")
        log.info("  Paid stages succeeded: %s", ", ".join(paid_eseguiti) or "(none)")


    if decisione.get("l2_knowledge_extract"):
        _kb_prima = _quando_ultima_estrazione()



        ok = _esegui("l2_knowledge_extract", [] if modo == "ricostruisci" else ["--incremental"])
        avvisi.extend(_gate_estrazione_passata(_kb_prima, ok))





        if _quando_ultima_estrazione() != _kb_prima:
            avvisi.extend(_avvisi_estrazione())
    if decisione.get("l2_ricorrenze"):
        log.info("\n=== Birthdays, birth and name days on the cards ===")
        _esegui("l2_ricorrenze", ["--apply"])






    if decisione.get("l2_episodes"):
        log.info("\n=== Episodes (documents) ===")
        _esegui("l2_episodes", ["--apply"])
    if decisione.get("l2_calendar_episodes"):
        _esegui("l2_calendar_episodes", ["--apply"])
    if decisione.get("l2_email_participants"):
        _esegui("l2_email_participants", ["--apply"])
    if decisione.get("l2_knows"):
        _esegui("l2_knows", ["--apply"])
    if decisione.get("l3_subject_index"):
        _esegui("l3_subject_index", ["build-index"])

    if decisione.get("l2_attachment_discovery"):
        _esegui("l2_attachment_discovery")
    if decisione.get("l2_person_deep_context"):
        _esegui("l2_person_deep_context")






    rq_ids = [p.id for p in CATENA if p.strato == "RQ"]
    if any(decisione.get(pid) for pid in rq_ids):
        log.info("\n=== RQ + RQ V4 (Relationship Quality) ===")







    _rq_a_valle_di_00 = {"rq_01_decay", "rq_02b_signals", "rq_02_scoring"}
    rq_00_morto = False
    rq_00_vuoto = False
    for pid in rq_ids:
        if not decisione.get(pid):
            continue
        if rq_00_morto and pid in _rq_a_valle_di_00:
            salti.append(Salto(pid, "a_monte", "rq-00 dead: interaction-weights stale"))
            continue
        if rq_00_vuoto and pid in _rq_a_valle_di_00:
            log.info("  %s: no interactions weighed yet, nothing to read", pid)
            salti.append(Salto(pid, "niente_da_leggere", "rq-00 found no interactions yet"))
            continue
        extra: list[str] = []
        if pid == "rq_03_types":
            extra = ["--rules-only"]
        if pid == "rqv4_backfill":



            extra = ["--incremental"]
            _copia_bak_events()
        ok = _esegui(pid, extra)
        if pid == "rq_00_weights" and not ok:
            rq_00_morto = True
        if pid == "rq_00_weights" and ok and not (DATA_ROOT / "rq" / "interaction-weights.parquet").exists():
            rq_00_vuoto = True  # a first install: nothing to weigh yet (RQ-00 wrote no weights)
        if pid == "rqv4_backfill" and not ok:
            _ripristina_events_se_piu_piccolo()




    forza = ["--force"] if modo == "ricostruisci" else []
    if decisione.get("l3_shadow"):
        _esegui("l3_shadow", forza)






    if decisione.get("l3_graph"):
        _esegui("l3_graph", ["--incremental"] if graph_incremental else [])
    # The stages after the search index do not read it: when it does not close (on a first run
    # without network the local embedding model cannot be downloaded) it stops alone, and the run
    # says so, but the chain goes on.
    if decisione.get("l3_index") and _esegui(
        "l3_index", ["--incremental"] if index_incremental else [], ferma_la_linea=False
    ):




        for src, perche in sorted(_fonti_non_indicizzate().items()):
            fonti_ferme.append(f"index {src}")
            log.error("  ⛔ search index: %s not indexed (%s)", src, perche)

    if decisione.get("l3_fact_index"):
        _esegui("l3_fact_index", forza)
    if decisione.get("l3_decay"):
        _esegui("l3_decay", ["--incremental"] if decay_incremental else [])
    if decisione.get("freshness"):
        _esegui("freshness")
    if decisione.get("pipeline_status"):
        _esegui("pipeline_status", ["--json-only"])
    if decisione.get("l3_calendario_ricorrenze"):
        log.info("\n=== Birthday and Name-day Calendars ===")
        _esegui("l3_calendario_ricorrenze", ["--apply"])




    _salta_a_valle("motivo_non_dichiarato", "planned and never run")

    return _chiudi()


def _copia_bak_events() -> None:
    ""
    events_db = DATA_ROOT / "rq" / "events.db"
    if not events_db.exists():
        return
    try:
        import shutil

        shutil.copy2(events_db, DATA_ROOT / "rq" / "events.db.bak")
        log.info("  Copied events.db -> events.db.bak (incremental safety)")
    except Exception as exc:  # noqa: BLE001
        log.warning("  events.db backup copy failed: %s", exc)


def _ripristina_events_se_piu_piccolo() -> None:
    ""
    try:
        events_db = DATA_ROOT / "rq" / "events.db"
        bak = DATA_ROOT / "rq" / "events.db.bak"
        cur = events_db.stat().st_size if events_db.exists() else 0
        vecchio = bak.stat().st_size if bak.exists() else 0
        if vecchio > cur:
            import shutil

            shutil.copy2(bak, events_db)
            log.info(
                "  events.db restored from .bak after failed backfill (%d -> %d bytes)",
                cur,
                vecchio,
            )
    except Exception as exc:  # noqa: BLE001
        log.warning("  restore events.db from .bak failed: %s", exc)


def _l1_in_fila() -> bool:
    ""



    return os.environ.get("SBK_L1_SEQUENZIALE", "1") != "0"


def run_l1_pipeline(
    sources: list[str] | None = None,
    dry_run: bool = False,
    profile: bool = False,
    whatsapp_extras: bool = False,
) -> dict:
    """Run the L1 phases. Phase 3 (the WhatsApp extras) runs only with whatsapp_extras=True."""












    t_start = time.time()
    errors = []
    phases_run = []


    pre_scripts = dict(L1_SCRIPTS_PRE)
    base_scripts = dict(L1_SCRIPTS_BASE)
    dep_scripts = dict(L1_SCRIPTS_DEPENDENT)

    if sources:
        pre_scripts = {k: v for k, v in pre_scripts.items() if k in sources}
        base_scripts = {k: v for k, v in base_scripts.items() if k in sources}
        dep_scripts = {k: v for k, v in dep_scripts.items() if k in sources}


    pre_scripts = {k: v for k, v in pre_scripts.items() if v.exists()}
    base_scripts = {k: v for k, v in base_scripts.items() if v.exists()}
    dep_scripts = {k: v for k, v in dep_scripts.items() if v.exists()}

    # sbk.config.json enabled_sources: only the sources you connected
    saltate: set[str] = set()
    prima = {"pre": set(pre_scripts), "base": set(base_scripts), "dep": set(dep_scripts)}
    pre_scripts = _solo_abilitate(pre_scripts, saltate)
    base_scripts = _solo_abilitate(base_scripts, saltate)
    dep_scripts = _solo_abilitate(dep_scripts, saltate)
    # The WhatsApp extras are not set up or tested by the author: only with --whatsapp-extras.
    wa_deep: dict = {}
    if whatsapp_extras:
        wa_deep = {k: v for k, v in L1_SCRIPTS_WA_DEEP.items() if v.exists()}
        if sources:
            wa_deep = {k: v for k, v in wa_deep.items() if k in sources or "whatsapp" in sources}
        prima["wa"] = set(wa_deep)
        wa_deep = _solo_abilitate(wa_deep, saltate)
    # The L1 phases left with no script only because enabled_sources does not list their
    # sources: the plan reports them as "not in enabled_sources", not as a phase that failed.
    fuori_elenco = _fasi_fuori_elenco(prima, pre_scripts, base_scripts, dep_scripts, wa_deep)
    if saltate:
        log.info(
            "enabled_sources (sbk.config.json): L1 skipped for %s, not listed",
            ", ".join(sorted(saltate)),
        )

    all_scripts = {**pre_scripts, **base_scripts, **dep_scripts}
    if not all_scripts:
        log.warning("No L1 scripts to run (check --only filter, enabled_sources or missing files)")
        return {
            "phases_run": [],
            "errors": [],
            "elapsed": 0,
            "l1_aggiornato": False,
            "fasi_fuori_elenco": fuori_elenco,
        }

    # A source with no folder under the data root yet was never downloaded or imported:
    # nothing to read, so its L1 is skipped at once, without attempts and without a failure.
    mai: dict[str, list[str]] = {}
    pre_scripts, mai["pre"] = _togli_mai_scaricate(pre_scripts)
    base_scripts, mai["base"] = _togli_mai_scaricate(base_scripts)
    dep_scripts, mai["dep"] = _togli_mai_scaricate(dep_scripts)
    wa_deep, mai["wa"] = _togli_mai_scaricate(wa_deep)
    mai_tutte = sorted({k for v in mai.values() for k in v})
    # Nothing at all to read: every source this run would read was never downloaded or imported,
    # and no merged book exists from an earlier run. The stages after L1 then have nothing to do.
    niente_scaricato = bool(mai_tutte) and not (
        pre_scripts or base_scripts or dep_scripts or wa_deep
    )
    niente_scaricato = niente_scaricato and not _rubrica_con_persone()
    if mai_tutte:
        log.info(
            "  not downloaded yet, skipped (no folder under the data root): %s",
            ", ".join(mai_tutte),
        )

    par = "one at a time" if _l1_in_fila() else "parallel"
    log.info("\n=== L1 Pipeline Plan ===")
    if pre_scripts:
        log.info(f"  Phase 1-pre (sequential): {', '.join(sorted(pre_scripts))}")
    if base_scripts:
        log.info(f"  Phase 1 ({par}): {', '.join(sorted(base_scripts))}")
    speakers = {k: v for k, v in L1_SCRIPTS_SPEAKERS.items() if v.exists()}
    if "plaud" in dep_scripts and speakers:
        log.info(f"  Phase 2-pre (speaker list): {', '.join(sorted(speakers))}")
    if dep_scripts:
        log.info(f"  Phase 2 ({par}, after Phase 1): {', '.join(sorted(dep_scripts))}")
    if wa_deep:
        log.info(
            f"  Phase 3 (WhatsApp extras, --whatsapp-extras, {par}): {', '.join(sorted(wa_deep))}"
        )
    elif not whatsapp_extras:
        log.info("  Phase 3 (WhatsApp extras): not run, add --whatsapp-extras to ask for it")

    if dry_run:
        log.info("\n=== DRY RUN — no L1 scripts executed ===")
        return {
            "phases_run": [],
            "phases_planned": [
                *([{"phase": "1-pre", "scripts": sorted(pre_scripts)}] if pre_scripts else []),
                {"phase": 1, "scripts": sorted(base_scripts)},
                *(
                    [{"phase": "2-pre", "scripts": sorted(speakers)}]
                    if ("plaud" in dep_scripts and speakers)
                    else []
                ),
                {"phase": 2, "scripts": sorted(dep_scripts)},
                *([{"phase": 3, "scripts": sorted(wa_deep)}] if wa_deep else []),
            ],
            "errors": [],
            "elapsed": time.time() - t_start,
            "dry_run": True,
            "l1_aggiornato": True,
            "fasi_fuori_elenco": fuori_elenco,
            "niente_scaricato": niente_scaricato,
        }

    def _run_l1_phase(scripts: dict[str, Path], phase_name: str) -> list[str]:
        ""






        if not scripts:
            return []






        sequenziale = _l1_in_fila()
        modo = "one at a time (SBK_L1_SEQUENZIALE=1)" if sequenziale else "in parallel"

        log.info(f"\n{'=' * 60}")
        log.info(f"L1 {phase_name}: running {len(scripts)} scripts {modo}")
        log.info(f"{'=' * 60}")
        t_phase = time.time()

        def _leggi(name: str, script_path: Path) -> bool:
            if sequenziale:
                _aspetta_pausa(name)
            return run_script(
                name,
                script_path,
                argomenti_l1(name),
                timeout_s=L1_TIMEOUT_OVERRIDE_S.get(name, L1_PHASE_TIMEOUT_S),
            )

        if sequenziale:
            esiti = {name: _leggi(name, script_path) for name, script_path in scripts.items()}
        else:

            from concurrent.futures import ThreadPoolExecutor

            with ThreadPoolExecutor(max_workers=len(scripts)) as pool:
                futuri = {name: pool.submit(_leggi, name, p) for name, p in scripts.items()}
                esiti = {name: f.result() for name, f in futuri.items()}

        phase_errors = [name for name, ok in esiti.items() if not ok]
        for name in phase_errors:
            log.error(f"  [{name}] NOT CLOSED after the attempts: the source stops, the chain does not")

        phase_elapsed = time.time() - t_phase
        ok_count = len(scripts) - len(phase_errors)
        log.info(f"  {phase_name} completed: {ok_count}/{len(scripts)} OK in {phase_elapsed:.1f}s")

        if profile:
            log.info(f"  [profile] {phase_name}: {phase_elapsed:.1f}s")

        return phase_errors







    if pre_scripts or mai["pre"]:
        pre1_errors = _run_l1_phase(pre_scripts, "Phase 1-pre (personio)")
        errors.extend(pre1_errors)
        phases_run.append("l1_personio")
        if "personio_assenze" in pre_scripts or "personio_assenze" in mai["pre"]:
            phases_run.append("l1_personio_assenze")


    if base_scripts or mai["base"]:
        phase1_errors = _run_l1_phase(base_scripts, "Phase 1 (base)")
        errors.extend(phase1_errors)
        phases_run.append("l1_phase1")






    speakers = {k: v for k, v in L1_SCRIPTS_SPEAKERS.items() if v.exists()}
    if "plaud" in dep_scripts and speakers:
        pre_errors = _run_l1_phase(speakers, "Phase 2-pre (speaker list)")
        errors.extend(pre_errors)
        phases_run.append("l1_speaker_analysis")
    elif "plaud" in mai["dep"]:
        phases_run.append("l1_speaker_analysis")  # no Plaud folder yet: nothing to analyse

    if dep_scripts or mai["dep"]:
        phase2_errors = _run_l1_phase(dep_scripts, "Phase 2 (dependent)")
        errors.extend(phase2_errors)
        phases_run.append("l1_phase2")


    if wa_deep or mai["wa"]:
        # The phase name stays "Phase 3 (WA deep)": the macOS app reads it from the log.
        phase3_errors = _run_l1_phase(wa_deep, "Phase 3 (WA deep)")
        errors.extend(phase3_errors)
        phases_run.append("l1_phase3_wa_deep")

    elapsed = time.time() - t_start






    _speakers_girati = L1_SCRIPTS_SPEAKERS if "plaud" in dep_scripts else {}
    girati = sum(
        len(s) for s in (pre_scripts, base_scripts, dep_scripts, wa_deep, _speakers_girati)
    )
    if errors:
        log.error(
            "\n=== L1 INCOMPLETE — %d/%d sources OK in %.1fs, dead: %s ===",
            girati - len(errors),
            girati,
            elapsed,
            ", ".join(sorted(errors)),
        )
    else:
        log.info("\n=== L1 Complete — %d/%d sources in %.1fs ===", girati, girati, elapsed)

    if profile:
        log.info(f"  [profile] Total L1: {elapsed:.1f}s")



    _scrivi_stato(
        L1_ESITO_FILE,
        {
            "quando": datetime.now(UTC).isoformat(),
            "fasi": phases_run,
            "fonti_non_chiuse": sorted(errors),
            "filtro": sorted(sources) if sources else None,
        },
    )

    return {
        "phases_run": phases_run,
        "errors": errors,
        "filtro": sorted(sources) if sources else None,
        "elapsed": elapsed,
        "l1_aggiornato": True,
        "fasi_fuori_elenco": fuori_elenco,
        "niente_scaricato": niente_scaricato,
    }





def _aggiungi_alias(parser: argparse.ArgumentParser) -> None:
    ""






    for vecchio, nuovo in ALIAS_DEPRECATI.items():
        parser.add_argument(
            vecchio,
            dest="alias_" + vecchio.lstrip("-").replace("-", "_"),
            action="store_true",
            help=f"DEPRECATED since {ALIAS_DEPRECATI_DAL}: use {nuovo} "
            f"(removal not before {ALIAS_RIMOZIONE_NON_PRIMA_DEL})",
        )


def _modo_da_argomenti(args, parser: argparse.ArgumentParser) -> str:
    ""
    scelti: list[tuple[str, str]] = []
    for modo in MODI:
        if getattr(args, modo, False):
            scelti.append((f"{FLAG_MODO[modo]}", modo))
    for vecchio, nuovo in ALIAS_DEPRECATI.items():
        if getattr(args, "alias_" + vecchio.lstrip("-").replace("-", "_"), False):
            scelti.append((vecchio, MODO_DA_FLAG[nuovo]))

    if not scelti:
        parser.error(
            "A command is required. The four, from the most complete to the lightest:\n"
            "  --all        the WHOLE chain, paid stages included (asks for consent)\n"
            "  --ingest     L1+L2+L3 free: rereads the sources already on disk\n"
            "  --rebuild    L2+L3 rebuilt from scratch, except search index and event log which\n"
            "               update (never L1, never L0, never paid)\n"
            "  --propagate  L2+L3 incremental: propagates the snapshot already on disk\n"
            "None of the four downloads L0: the download is tools/cross-source/xs-l0-refresh.py."
        )
    if len({m for _, m in scelti}) > 1:
        parser.error(
            "One command at a time: you asked for " + ", ".join(n for n, _ in scelti) + ". "
            "The four perimeters are mutually exclusive by construction."
        )

    for nome, nuovo in scelti:
        if nome in ALIAS_DEPRECATI:
            log.warning(
                "⚠️  %s is deprecated since %s: use %s. Removal not before %s.",
                nome,
                ALIAS_DEPRECATI_DAL,
                FLAG_MODO[nuovo],
                ALIAS_RIMOZIONE_NON_PRIMA_DEL,
            )
    return scelti[0][1]


def _guardia_flag_ignorati(args, modo: str, parser: argparse.ArgumentParser) -> None:
    ""









    paid_chiesti = [n for n, v in (("--l3-extract", args.l3_extract), ("--deep", args.deep)) if v]
    if paid_chiesti and modo != "tutto":
        parser.error(
            f"{' and '.join(paid_chiesti)}: the paid stages run only inside --all, "
            "which includes them ALL and in the right place in the chain (before knowledge-extract, "
            "not after). What to do: use --all (it asks for spending consent), or "
            "--ingest if you want to declare that you accept a free run."
        )
    if paid_chiesti and modo == "tutto":
        log.warning(
            "⚠️  %s is redundant: --all already includes all three paid stages "
            "(l3-extract, extract-relationships, deep). Deprecated since %s, removal not before "
            "%s.",
            " and ".join(paid_chiesti),
            ALIAS_DEPRECATI_DAL,
            ALIAS_RIMOZIONE_NON_PRIMA_DEL,
        )

    if args.only and modo not in ("ingest", "tutto"):
        parser.error(
            f"--only filters the L1 sources, and {FLAG_MODO[modo]} does not launch L1: the filter would have "
            "no effect. What to do: --ingest --only <sources> (or --all --only ...)."
        )
    if getattr(args, "scarico_non_chiuso", None) and modo not in ("ingest", "tutto"):
        parser.error(
            f"--download-not-closed applies with --ingest or --all, after a download: {FLAG_MODO[modo]} is not a run."
        )
    if getattr(args, "riprendi_da", None):
        ids = [p.id for p in perimetro(modo)]
        if modo not in ("ingest", "tutto"):
            parser.error(f"--resume-from applies with --ingest or --all, not with {FLAG_MODO[modo]}.")
        if args.riprendi_da not in ids:
            parser.error(f"--resume-from {args.riprendi_da}: it is not a stage of {FLAG_MODO[modo]}.")
        if CATENA_PER_ID[args.riprendi_da].strato == "L1" or args.only:
            parser.error(
                "--resume-from restarts after L1: an L1 stopped halfway is redone whole with --ingest."
            )
    if getattr(args, "solo_stadio", None):
        passo_solo = CATENA_PER_ID.get(args.solo_stadio)
        if modo not in ("propaga", "ricostruisci", "tutto"):
            parser.error(
                f"--single-stage applies with --propagate, --rebuild or --all, not with {FLAG_MODO[modo]}."
            )
        if passo_solo is None or args.solo_stadio not in [p.id for p in perimetro(modo)]:
            parser.error(f"--single-stage {args.solo_stadio}: it is not a stage of {FLAG_MODO[modo]}.")
        if passo_solo.strato == "L1":
            parser.error(
                "--single-stage does not apply to L1: the L1 phases are reread with --ingest (--only <sources>)."
            )
        if passo_solo.tipo == "pagato" and modo != "tutto":
            parser.error(
                "--single-stage: a paid stage is launched only with --all --allow-spend."
            )
        if getattr(args, "riprendi_da", None) or args.only:
            parser.error("--single-stage does not combine with --resume-from or --only.")
    if args.profile and modo not in ("ingest", "tutto"):
        parser.error(
            f"--profile measures the L1 phase timings, and {FLAG_MODO[modo]} does not launch L1. "
            "What to do: --ingest --profile."
        )
    if getattr(args, "whatsapp_extras", False) and modo not in ("ingest", "tutto"):
        parser.error(
            f"--whatsapp-extras runs an L1 phase, and {FLAG_MODO[modo]} does not launch L1. "
            "What to do: --ingest --whatsapp-extras (or --all --whatsapp-extras)."
        )
    if args.consenti_spesa and modo != "tutto":
        parser.error(
            f"--allow-spend authorizes the paid stages, and {FLAG_MODO[modo]} has none "
            "in its perimeter. What to do: --all --allow-spend (or drop the flag)."
        )


def main():
    parser = argparse.ArgumentParser(
        description="SBK Smart Pipeline Orchestrator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
The four commands, from the most complete to the lightest:

  xs-pipeline-run.py --all         the WHOLE chain: L1 -> L2 -> the two PAID
                                   stages -> knowledge extract -> RQ -> L3.
                                   Asks for spending consent; without a tty it
                                   requires --allow-spend and does not start.
  xs-pipeline-run.py --ingest      L1+L2+L3 free: rereads the sources
                                   already on disk. The paid ones stay out, and the
                                   plan NAMES them as excluded.
  xs-pipeline-run.py --rebuild     L2+L3 rebuilt from scratch: facts without incremental,
                                   cited people and fact index forced.
                                   The search index and the event log
                                   update, they are not thrown away.
  xs-pipeline-run.py --propagate   L2+L3 incremental (the lightest).
  ... --dry-run                    the plan without executing, PAID included.

⚠️ NONE of the four downloads L0: the download is the run
   tools/cross-source/xs-l0-refresh.py (--then-ingest for the full run), and
   these stay manual (you export or run them yourself): {a_mano}.
   What the pipeline guarantees is to REPORT how old L0 is.

The WhatsApp extras (documents and photos pulled out of the exported chats) are not set
up or tested by the author: they run only with --whatsapp-extras, never by default.

⚠️ --propagate and --rebuild do NOT reread the sources: if L1 is idle
   they rebuild an old snapshot — and now they say so to your face.

The cost of the paid stages is not written here: it is computed from the pending
documents at the time of the question. A figure in a help is false a month later.
        """.replace("{a_mano}", SORGENTI_A_MANO),
    )
    for modo in MODI:
        parser.add_argument(FLAG_MODO[modo], dest=modo, action="store_true", help=_AIUTO_MODI[modo])
        if FLAG_MODO[modo] != f"--{modo}":
            parser.add_argument(f"--{modo}", dest=modo, action="store_true", help=argparse.SUPPRESS)
    _aggiungi_alias(parser)
    parser.add_argument("--dry-run", action="store_true", help="Show the plan without executing")
    parser.add_argument(
        "--allow-spend",
        dest="consenti_spesa",
        action="store_true",
        help=(
            "Authorize the paid stages of --all NON-interactively. "
            f"Equivalent: {VARIABILE_CONSENSO}=1. Needed because the pipeline also runs "
            "from launchd and the monitor, where an input() would block it forever"
        ),
    )
    parser.add_argument(
        "--deep",
        action="store_true",
        help="DEPRECATED: included in --all (see I-0: it was accepted and ignored)",
    )
    parser.add_argument(
        "--l3-extract",
        action="store_true",
        help="DEPRECATED: included in --all (see I-0: it was accepted and ignored)",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Debug logging")
    parser.add_argument(
        "--only",
        type=str,
        default=None,
        help="L1 sources to process, comma-separated (with --ingest / --all)",
    )
    parser.add_argument("--profile", action="store_true", help="Time per L1 phase")
    parser.add_argument(
        "--whatsapp-extras",
        action="store_true",
        help=(
            "With --ingest or --all: also run the WhatsApp extras that pull documents and photos "
            "out of the exported chats (wa-l1-extract-docs.py, wa-l1-extract-photos.py, local only). "
            "Not set up or tested by the author, so they are off unless you add this flag"
        ),
    )
    parser.add_argument(
        "--single-stage",
        dest="solo_stadio",
        default=None,
        metavar="STEP_ID",
        help=(
            "With --propagate, --rebuild or --all: a chain run with ONE single stage, with its chain "
            "arguments, its preconditions and the pipeline lock. The other stages are declared out. "
            "A paid stage only with --all --allow-spend"
        ),
    )
    parser.add_argument(
        "--download-not-closed",
        dest="scarico_non_chiuso",
        default=None,
        metavar="SOURCES",
        help=(
            "With --ingest or --all: the sources whose download did not close in the run, comma-separated (the "
            "run passes them, xs-l0-refresh.py). The free chain runs, the paid steps do not"
        ),
    )
    parser.add_argument(
        "--resume-from",
        dest="riprendi_da",
        default=None,
        metavar="STEP_ID",
        help=(
            "With --ingest or --all: restarts from this stage. L1 and the stages before it closed in the "
            "stopped run and are declared skipped (resumed). Only if nothing has been re-downloaded since"
        ),
    )
    parser.add_argument(
        "--sentinels",
        dest="sentinelle",
        type=_sentinella,
        choices=("blocco", "ombra"),
        metavar="{block,shadow}",
        default="blocco",
        help=(
            "Mode of the four conio sentinels (registry, unknown, relation, "
            "organization) "
            "for knowledge-extract. Default `block`: they used to be born "
            "in `shadow` mode and the orchestrator never turned them on (they counted, they did not block). "
            "An environment variable SBK_REGISTRO/IGNOTO/RELAZIONE already set wins."
        ),
    )
    parser.add_argument(
        "--step",
        dest="solo",
        type=str,
        default=None,
        metavar="STEP_ID",
        help=(
            "Runs ONE single stage of the CHAIN under the memory guardian and timeout "
            "(test, 0.7 review v2). E.g.: --step rq_00_weights. "
            "The ids: xs-pipeline-run.py --step list"
        ),
    )
    parser.add_argument(
        "--step-args",
        dest="solo_args",
        metavar="ARGS",
        type=str,
        default="",
        help="Extra arguments for the --step step (single string, split on spaces)",
    )
    # Older Italian names, kept as hidden aliases (same destinations as the English flags).
    parser.add_argument("--consenti-spesa", dest="consenti_spesa", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--solo-stadio", dest="solo_stadio", help=argparse.SUPPRESS)
    parser.add_argument("--scarico-non-chiuso", dest="scarico_non_chiuso", help=argparse.SUPPRESS)
    parser.add_argument("--riprendi-da", dest="riprendi_da", help=argparse.SUPPRESS)
    parser.add_argument(
        "--sentinelle", dest="sentinelle", type=_sentinella, choices=("blocco", "ombra"), help=argparse.SUPPRESS
    )
    parser.add_argument("--solo", dest="solo", type=str, help=argparse.SUPPRESS)
    parser.add_argument("--solo-args", dest="solo_args", type=str, help=argparse.SUPPRESS)
    args = parser.parse_args()




    for _var in (
        "SBK_REGISTRO",
        "SBK_IGNOTO",
        "SBK_RELAZIONE",
        "SBK_ORGANIZZAZIONE",
        "SBK_ARCHIVIO",
    ):
        os.environ.setdefault(_var, args.sentinelle)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )





    if args.solo:
        if args.solo in ("list", "elenco"):
            for pz in CATENA:
                seg = " (paid)" if pz.tipo == "pagato" else ""
                print(f"  {pz.id:24s} {pz.nome}{seg}")
            return
        passo = next((pz for pz in CATENA if pz.id == args.solo), None)
        if passo is None:
            log.error("--step %s: unknown id (list: --step list)", args.solo)
            sys.exit(2)
        script = SCRIPTS.get(passo.id)
        if script is None or not script.exists():
            log.error("--step %s: stage without a direct executable script", args.solo)
            sys.exit(2)
        if passo.tipo == "pagato" and not args.consenti_spesa:
            log.error(
                "--step %s is a PAID stage: needs an explicit --allow-spend",
                args.solo,
            )
            sys.exit(2)
        extra = args.solo_args.split() if args.solo_args else []

        if not acquire_pid_lock("pipeline-run", logger=log):
            log.error(
                "=== Test not started: another pipeline run holds the lock (exit %d) ===",
                EXIT_LOCK_ATTIVO,
            )
            sys.exit(EXIT_LOCK_ATTIVO)
        log.info("── GUARDED TEST: %s (%s) ──", passo.nome, script.name)
        ok = run_script(passo.nome, script, extra)
        log.info("── outcome: %s ──", "OK" if ok else "FAILED")
        sys.exit(0 if ok else 1)

    modo = _modo_da_argomenti(args, parser)
    _guardia_flag_ignorati(args, modo, parser)
    if getattr(args, "whatsapp_extras", False):
        STADI_A_RICHIESTA_ACCESI.add("l1_phase3_wa_deep")






    consenso = False
    if not args.dry_run:
        blocchi, _ = precondizioni(modo)
        if "chiave_api" in blocchi:
            log.error("⛔ Not starting: %s", blocchi["chiave_api"])
            sys.exit(EXIT_FALLITO)
        if not coda_dei_falliti_leggibile():
            log.error(
                "⛔ Not starting: the failure queue is not readable, so the outcome of this "
                "run would not be verifiable. What to do: "
                "uv run python tools/util/sb-pipeline-ctl.py status"
            )
            sys.exit(EXIT_FALLITO)


    if modo == "tutto" and not args.dry_run:
        passi_paid = [p.id for p in CATENA if p.tipo == "pagato"]
        consenso = consenso_spesa(passi_paid, consenti_flag=args.consenti_spesa)
        if not consenso and not sys.stdin.isatty():



            log.error(
                "⛔ --all includes %d paid stages and this run is not interactive: "
                "I cannot ask for consent, and a default that spends does not exist.\n"
                "   Two honest options:\n"
                "     1) add --allow-spend (or export %s=1) to authorize;\n"
                "     2) use --ingest to declare that you accept a FREE run, "
                "with the two paid stages named as excluded.",
                len(passi_paid),
                VARIABILE_CONSENSO,
            )
            sys.exit(EXIT_FALLITO)
        if not consenso:
            log.warning(
                "⚠️  Spending NOT authorized: the paid stages will be declared skipped "
                "and the run will close INCOMPLETE (exit %d). The rest of the chain runs anyway.",
                EXIT_INCOMPLETO,
            )





    if not args.dry_run and not os.environ.get("SBK_RUN_ID"):
        import un_run_alla_volta

        giro = os.environ.get("SBK_GIRO_PID", "")
        chi = un_run_alla_volta.chi_gira(
            locks=("l0-refresh",),
            salta=frozenset({int(giro)}) if giro.isdigit() else frozenset(),
        )
        if chi:
            log.error(
                "=== Not started: %s is already running — one run at a time (lock held), retry when it "
                "finishes (exit %d) ===",
                ", ".join(chi),
                EXIT_LOCK_ATTIVO,
            )
            sys.exit(EXIT_LOCK_ATTIVO)
    if not args.dry_run and not acquire_pid_lock("pipeline-run", logger=log):




        log.error(
            "=== Not started: lock active — another pipeline run is going ===\n"
            "  It is not a success and it is not a failure: it is «retry» (exit %d).\n"
            "  What to do: uv run python tools/util/sb-pipeline-ctl.py status",
            EXIT_LOCK_ATTIVO,
        )
        sys.exit(EXIT_LOCK_ATTIVO)


    diario = None
    if not args.dry_run:
        import un_run_alla_volta as _diario_run

        diario = _diario_run.diario_inizio("rilettura")




    global _LOG_DEL_RUN
    ambiente_prima = {v: os.environ.get(v) for v in ("SBK_CODA_RUN", "SBK_PASSO_LOG")}
    if not args.dry_run:
        run_dir, run_id = os.environ.get("SBK_RUN_DIR"), os.environ.get("SBK_RUN_ID")
        _LOG_DEL_RUN = os.environ.pop("SBK_PASSO_LOG", "") or (
            str(Path(run_dir) / f"{run_id}.log") if run_dir and run_id else ""
        )
        os.environ["SBK_CODA_RUN"] = (
            run_id or f"pipeline-{datetime.now():%Y%m%d-%H%M%S}-{os.getpid()}"
        )
    try:
        codice = _main_inner(args, modo=modo, consenso=consenso)
    finally:
        if not args.dry_run:
            release_pid_lock("pipeline-run")
            _LOG_DEL_RUN = ""
            for variabile, valore in ambiente_prima.items():
                if valore is None:
                    os.environ.pop(variabile, None)
                else:
                    os.environ[variabile] = valore
    if diario:
        _diario_run.diario_fine(diario, codice)
    sys.exit(codice)


def _main_inner(args, *, modo: str, consenso: bool) -> int:
    ""








    t_inizio_iso = datetime.now(UTC).isoformat()
    avvisi_iniziali: list[str] = []
    stadi_l1: list[str] = []

    fonti_l1_ferme: list[str] = []
    filtro_l1: list[str] | None = None
    fasi_fuori_elenco: list[str] = []
    niente_scaricato = False
    scarico_ko = [
        s.strip() for s in (getattr(args, "scarico_non_chiuso", None) or "").split(",") if s.strip()
    ]
    if scarico_ko:
        log.warning(
            "⚠️  Download not closed in the run: %s. The free chain runs, the paid steps do not.",
            ", ".join(scarico_ko),
        )

    if modo in ("ingest", "tutto"):


        avvisi_iniziali.extend(_stampa_eta_l0())
        if getattr(args, "solo_stadio", None):
            log.info("\n=== Single-stage run %s: L1 is not reread ===", args.solo_stadio)
        elif getattr(args, "riprendi_da", None):
            log.info(
                "\n=== Resume from %s: L1 closed in the stopped run, not reread ===",
                args.riprendi_da,
            )
        else:
            only_sources = [s.strip() for s in args.only.split(",")] if args.only else None
            l1 = run_l1_pipeline(
                sources=only_sources,
                dry_run=args.dry_run,
                profile=args.profile,
                whatsapp_extras="l1_phase3_wa_deep" in STADI_A_RICHIESTA_ACCESI,
            )
            stadi_l1 = list(l1.get("phases_run") or [])
            fonti_l1_ferme = list(l1.get("errors") or [])
            filtro_l1 = only_sources
            fasi_fuori_elenco = list(l1.get("fasi_fuori_elenco") or [])
            niente_scaricato = bool(l1.get("niente_scaricato"))
        if args.dry_run:
            stadi_l1 = [
                f
                for f in (
                    "l1_personio",
                    "l1_personio_assenze",
                    "l1_phase1",
                    "l1_speaker_analysis",
                    "l1_phase2",
                    *(
                        ["l1_phase3_wa_deep"]
                        if "l1_phase3_wa_deep" in STADI_A_RICHIESTA_ACCESI
                        else []
                    ),
                )
                if f not in fasi_fuori_elenco
            ]

    result = run_pipeline(
        mode=modo,
        dry_run=args.dry_run,
        l1_gia_girato=modo in ("ingest", "tutto"),
        consenso_paid=consenso,
        t_inizio_iso=t_inizio_iso,
        stadi_gia_eseguiti=stadi_l1,
        avvisi_iniziali=avvisi_iniziali,
        riprendi_da=getattr(args, "riprendi_da", None),
        solo_stadio=getattr(args, "solo_stadio", None),
        fonti_non_chiuse=fonti_l1_ferme,
        lettura_filtrata=filtro_l1,
        scarico_non_chiuso=scarico_ko,
        fasi_fuori_elenco=fasi_fuori_elenco,
        niente_scaricato=niente_scaricato,
    )

    if args.dry_run:
        log.info("\n=== %s ===", result.get("intestazione", "DRY RUN"))
        return 0






    _closure_check()





    _allarme_silenzio_kb()

    codice = int(result.get("exit_code", EXIT_FALLITO if result.get("errors") else 0))
    log.info("Outcome: %s (exit %d)", result.get("intestazione", "?"), codice)
    return codice


if __name__ == "__main__":
    main()
