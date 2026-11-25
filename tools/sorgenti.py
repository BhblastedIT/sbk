#!/usr/bin/env python3
""










































from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Sorgente:
    id: str
    cosa_e: str
    natura: str
    genere: str



    ritmo_giorni: int | None = None
    chiusa_il: str = ""
    perche: str = ""
    note: str = ""

    come_si_aggiorna: str = ""









    dato_in: tuple[str, ...] = ()









    stadi_l1: tuple[tuple[str, str], ...] = ()






    l1: str = ""



_VIVE = [
    Sorgente(
        "email",
        "your mailboxes",
        "continua",
        "comunicazione",
        3,
        come_si_aggiorna="tools/email/em-l0-download.py --all",
        l1="tools/email/em-l1-enrich.py",

        stadi_l1=(
            ("email_allegati", "tools/email/em-l1-allegati.py"),
        ),
        note="each mailbox is your own Google login (tools/email/em-l0-auth.py <label>), "
        "listed in emails/accounts.json; without --since it picks up from the last run",
    ),
    Sorgente(
        "calendar",
        "appointments, past and future",
        "continua",
        "comunicazione",
        3,
        come_si_aggiorna="tools/calendar/ca-l0-download.py",
        l1="tools/calendar/ca-l1-extract.py",
    ),
    # microsoft365 and imap-caldav write into the mail and calendar slots above
    # (emails/<label>/, calendars/<label>/), so their L1 is the kernel's em-l1-enrich.py and
    # ca-l1-extract.py. Never list ("email", ...) or ("calendar", ...) in their stadi_l1: those
    # stage names would then belong to them and the email and calendar sources would break.
    Sorgente(
        "microsoft365",
        "your Outlook mail, calendar and contacts (Microsoft 365 or Outlook.com)",
        "continua",
        "comunicazione",
        3,
        come_si_aggiorna="tools/microsoft365/ms-l0-download.py --all",
        l1="tools/email/em-l1-enrich.py",
        dato_in=("*/state.json",),
        note="personal access only: your own app registration (public client, no secret), "
        "your own read scopes User.Read, Mail.Read, Calendars.Read, Contacts.Read and "
        "offline_access; sign in once per mailbox with tools/microsoft365/ms-l0-auth.py "
        "--account <label>. Writes into the existing slots: emails/<label>/messages.parquet "
        "(read by em-l1-enrich), calendars/<label>/events.parquet (read by ca-l1-extract) and "
        "the microsoft365:<label> rows of contacts/contacts.parquet (read by "
        "xs-l1-contacts-enrich, which runs outside the runner). Mail is incremental per folder "
        "(Graph delta); the calendar re-reads a moving window. Tested with a mocked Graph only",
    ),
    Sorgente(
        "imap-caldav",
        "any IMAP mailbox and CalDAV or ICS calendar, with your own app password",
        "continua",
        "comunicazione",
        3,
        come_si_aggiorna="tools/imap-caldav/ic-l0-download.py",
        l1="tools/email/em-l1-enrich.py",
        dato_in=("state/*.json", "state/*-uids.parquet", "raw/*/objects.parquet"),
        note="personal access only: an app-specific password (iCloud, Fastmail, Yahoo, any IMAP "
        "host), a CalDAV app password or a calendar link; Outlook.com through your own app "
        "registration (IMAP.AccessAsUser.All for your own mailbox, device code). Writes into the existing "
        "mail and calendar slots, read by em-l1-enrich.py (stage email) and ca-l1-extract.py "
        "(stage calendar). Incremental by UIDVALIDITY + UID and CONDSTORE MODSEQ on IMAP, by "
        "ctag + ETag on CalDAV, by ETag on ICS. Tested with mocked servers only",
    ),
    Sorgente(
        "slack",
        "channels and direct messages",
        "continua",
        "comunicazione",
        3,
        come_si_aggiorna="tools/slack/sl-l0-channel-index.py && tools/slack/sl-l0-download.py",
        l1="tools/slack/sl-l1-enrich.py",
        note="the workspace your personal Slack app is installed in, read with your user "
        "token: the channels you are in, your DMs and group DMs. DMs run with "
        "tools/slack/sl-l0-download-dm.py",
    ),
    Sorgente(
        "whatsapp",
        "your chats, exported from the phone",
        "a_richiesta",
        "comunicazione",
        30,
        come_si_aggiorna="tools/whatsapp/wa-l0l3-full.py --skip-analysis  # chat exports (.zip/.txt) "
        "from whatsapp/raw, other folders with --zip-dir; a bulk text export: "
        "tools/whatsapp/wa-l0-import-history.py --text-dir <folder>",
        l1="tools/whatsapp/wa-l1-enrich.py",
        note="on request: you export the chats from your phone (iPhone or Android, Export chat) "
        "and SBK imports the files. That bulk export then import is the path the author uses "
        "and tested. Live reading of WhatsApp is not set up, so nothing arrives on its own: "
        "the 30 days are only a reminder to export again. The extras that pull documents and "
        "photos out of the chats are not set up or tested by the author and run only with "
        "xs-pipeline-run.py --ingest --whatsapp-extras",
    ),
    Sorgente(
        "attio",
        "the CRM: companies, deals, notes, recordings",
        "continua",
        "lavoro",
        7,
        come_si_aggiorna="tools/attio/at-l0-download.py",
        l1="tools/attio/at-l1-enrich.py",
        note="supports multiple workspaces, each in its own folder (for example attio/ and "
        "attio-agency/). Recorded calls are stored one file per recording, with an inventory "
        "in call-recordings.parquet and a receipt in _coverage.json; L1 and L3 read every configured workspace",
    ),
    Sorgente(
        "gdrive",
        "the documents on Drive",
        "continua",
        "lavoro",
        7,
        come_si_aggiorna="tools/gdrive/gd-l0-download.py --mode full-sync",
        l1="tools/gdrive/gd-l1-enrich.py",
        note="each account is your own Google login (tools/gdrive/gd-l0-auth.py --account "
        "<label>). Full history with --days 0; afterwards incremental, unchanged files are skipped",
    ),
    Sorgente(
        "plaud",
        "the recorder's recordings",
        "continua",
        "comunicazione",
        7,
        come_si_aggiorna="tools/plaud/pl-l0-download.py",
        l1="tools/plaud/pl-l1-enrich.py",
    ),
    Sorgente(
        "tactiq",
        "call transcripts",
        "continua",
        "comunicazione",
        14,
        come_si_aggiorna="tools/tactiq/tq-l0-download.py",
        l1="tools/tactiq/tq-l1-enrich.py",
        note="transcript fallback behind Attio, which takes precedence; also covers meetings "
        "shared with the account",
    ),
    Sorgente(
        "zoom",
        "your Zoom meetings: participants and cloud-recording transcripts",
        "continua",
        "comunicazione",
        7,
        come_si_aggiorna="tools/zoom/zm-l0-download.py",
        l1="tools/zoom/zm-l1-enrich.py",
        dato_in=("raw/state.json", "raw/meetings/*.json"),
        note="personal access only: your own user-managed Zoom app with PKCE, user-level scopes, "
        "the `me` context. Reads meetings you host that have a cloud recording (Pro plan or "
        "higher), their participant lists and the audio-transcript VTT; --include-unrecorded adds "
        "past scheduled meetings without a recording. Writes the generic intake contract "
        "(plugin-contacts / plugin-interactions, read by tools/cross-source/plugin_intake.py): "
        "people reach the contact merge and the person facts; meetings are written as done, so "
        "they are never commitments, and the transcript text is not read by the kernel yet. "
        "Incremental on the last completed day minus zoom.overlap_days. Tested with a mocked API only",
    ),
    Sorgente(
        "notion",
        "the pages, read-only",
        "chiusa",
        "lavoro",
        perche="decommissioned as a source: the downloader no longer runs and is not "
        "maintained, but pages already fetched remain and are still read.",
        l1="tools/notion/no-l1-enrich.py",
        note="deprecated source",
    ),
    Sorgente(
        "whoop",
        "sleep, recovery, strain",
        "continua",
        "personale",
        7,
        come_si_aggiorna="tools/whoop/wp-l0-download.py",
        l1="tools/whoop/wp-l1-process.py",
        note="sleep, recovery and strain metrics pulled via an API token; used to "
        "correlate physiological state with what happened over time.",
    ),
    Sorgente(
        "voicememos",
        "the phone's voice memos",
        "spot",
        "personale",
        None,
        come_si_aggiorna="tools/voice-memos/vm-l0-transcribe.py",
        l1="tools/voice-memos/vm-l1-enrich.py",
        note="treated as spot: freshness in days is not meaningful, because a memo is "
        "recorded only when there is something to record.",
    ),
    Sorgente(
        "linkedin",
        "profiles and conversations",
        "a_richiesta",
        "lavoro",
        30,
        come_si_aggiorna="tools/linkedin/li-l0-import-export.py",
        dato_in=("processed/*.parquet", "raw/*.parquet", "enriched/*.parquet"),
        l1="tools/linkedin/li-l1-enrich.py",
        note="⚠️ respect provider rate limits. The "
        "safe path goes through a CRM connector. It has a lane in the knowledge extract, but "
        "with minting of new entities disabled by default (configurable): it enriches people "
        "already known and leaves new ones out.",
    ),
    Sorgente(
        "databases",
        "people and events from your own database (SQLite, PostgreSQL, MySQL)",
        "a_richiesta",
        "lavoro",
        30,
        come_si_aggiorna="tools/databases/db-l0-download.py",
        dato_in=("raw/*.parquet", "state.json"),
        l1="tools/databases/db-l1-enrich.py",
        note="your own database, read with SELECT/WITH queries you declare in sbk.config.json "
        "(databases.sources) and a column map to the generic intake; the connection string "
        "stays in the Keychain (sbk-databases/<connection>) or in SBK_DB_URL_<NAME>. "
        "Incremental per source when it declares cursor + key. Read by the kernel through the "
        "generic intake (tools/cross-source/plugin_intake.py). PostgreSQL and MySQL need an "
        "optional driver you add yourself (uv add 'psycopg[binary]>=3.2' or "
        "uv add 'pymysql>=1.1') or the duckdb driver",
    ),
    Sorgente(
        "ai-history",
        "what you typed to AI assistants: Claude Code logs, ChatGPT, Claude.ai and Manus exports",
        "a_richiesta",
        "personale",
        30,
        come_si_aggiorna="tools/ai-history/ai-l0-claude-code.py  # your Claude Code logs; "
        "exports you downloaded: tools/ai-history/ai-l0-import-export.py <export.zip|folder>",
        dato_in=("messages.jsonl",),
        l1="tools/ai-history/ai-l3-how-you-work.py",
        note="on request, never in the full run. The two readers are local (nothing leaves "
        "the machine) and keep only what you typed, with secrets redacted. The reader of "
        "messages.jsonl is ai-l3-how-you-work.py: its step 1 is local; its step 2 sends a "
        "sample to a model only with --yes (--dry-run shows what would go) and writes your "
        "identity files in sbk/identity/, which git ignores",
    ),
    Sorgente(
        "clickup",
        "tasks: who does what, by when, and what is closed",
        "continua",
        "lavoro",
        7,
        come_si_aggiorna="tools/clickup/cu-l0-backup.py",
        l1="tools/clickup/cu-l1-enrich.py",
        note="the task system. The backup feeds an L1 stage and a lane in the knowledge "
        "extract that produces `commitment` entities in the store. Supports multiple workspaces.",
    ),
    Sorgente(
        "personio",
        "the personnel records",
        "periodica",
        "lavoro",





        7,
        come_si_aggiorna="tools/personio/pe-l0-download.py",
        l1="tools/personio/pe-l1-enrich.py",
        stadi_l1=(("personio_assenze", "tools/personio/pe-l2-absences-daily.py"),),
        note=(
            "an HR source: it changes when someone joins or leaves. Downloads several "
            "targets (people records, absences in days and in hours, balances, contract "
            "history, documents, compensation, org chart); attendance records are not included"
        ),
    ),
    Sorgente(
        "docusign",
        "signed contracts",
        "periodica",
        "lavoro",
        30,


        come_si_aggiorna="tools/docusign/ds-l0-api.py",
        l1="tools/docusign/ds-l1-enrich.py",

        stadi_l1=(("docusign_pdf", "tools/docusign/ds-l1-pdf.py"),),
        note="a contracts source: it changes when something is signed. Fetched via API for "
        "the primary account; related accounts share the same integration key but require "
        "their own user's consent. Freemium accounts have no API access",
    ),
]



# Closed sources: known to the code but not run. Each says where its data goes instead.
_CHIUSE = [
    Sorgente(
        "chatgpt",
        "ChatGPT conversations (older reader)",
        "chiusa",
        "lavoro",
        perche="replaced by the ai-history source, which imports your ChatGPT export.",
        note="tools/chatgpt/cg-l1-enrich.py still classifies a conversations.json you put in "
        "<data root>/chatgpt/; to run it, move this entry into the active list",
    ),
    Sorgente(
        "manus",
        "analyses made with Manus",
        "chiusa",
        "lavoro",
        perche="not a pipeline source: import your Manus export through the ai-history source.",
    ),
]







_INVENTARIO = [
    Sorgente(
        "github",
        "repositories (list, top-level folders, README), the people you work with, your issues, "
        "pull requests and reviews",
        "periodica",
        "inventario",
        7,
        come_si_aggiorna="tools/github/gh-l0-download.py  # inventory only: "
        "tools/github/gh-l0-inventory.py",
        l1="tools/cross-source/xs-l1-inventario.py",
        stadi_l1=(("github_intake", "tools/github/gh-l1-enrich.py"),),
        dato_in=("repos.json", "state.json"),
        note="personal access only: your own fine-grained or classic personal access token, GET "
        "calls only. Inventory: not every file, the list plus top-level folders and README "
        "(github.trees or --trees), incremental on `pushed_at`. Work: issues and PRs where you "
        "are author or assignee, open PRs where your review is requested by name, PRs you "
        "reviewed, searched from the last run minus one day; collaborators only of repositories "
        "where you can push. gh-l1-enrich.py writes the generic intake contract "
        "(plugin-contacts / plugin-interactions). Tested with a mocked API only",
    ),
    Sorgente(
        "gsc",
        "Search Console: whether anyone reaches the sites, and what they searched for",
        "periodica",
        "inventario",
        30,
        come_si_aggiorna="tools/gsc/gs-l0-inventory.py",
        l1="tools/cross-source/xs-l1-inventario.py",
        note="the verified properties. ⚠️ the data lags by two to three days: the window "
        "stops a few days back, otherwise the most recent days look like a drop.",
    ),
    Sorgente(
        "analytics",
        "GA4: what visitors do on the sites, not just how many arrive",
        "periodica",
        "inventario",
        30,
        come_si_aggiorna="tools/analytics/ga-l0-inventory.py",
        l1="tools/cross-source/xs-l1-inventario.py",
        note="⚠️ covers only the properties that carry a GA4 tag, fewer than Search Console. "
        "The gap matters: coverage questions go to GSC, GA4 only counts where a tag was installed.",
    ),
]


# Sources you plan to connect but have no script for yet: add a Sorgente(..., "da_costruire", ...)
# here and the pipeline dry run lists it as "declared but never built". Empty in a fresh install.
_DA_COSTRUIRE: list[Sorgente] = []

SORGENTI: dict[str, Sorgente] = {s.id: s for s in (*_VIVE, *_INVENTARIO, *_CHIUSE, *_DA_COSTRUIRE)}


def attive() -> dict[str, Sorgente]:
    ""
    return {k: v for k, v in SORGENTI.items() if v.natura not in ("chiusa", "da_costruire")}


def chiuse() -> dict[str, Sorgente]:
    return {k: v for k, v in SORGENTI.items() if v.natura == "chiusa"}


def da_costruire() -> dict[str, Sorgente]:
    return {k: v for k, v in SORGENTI.items() if v.natura == "da_costruire"}




STADI_L1: dict[str, str] = {
    stadio: sid for sid, s in SORGENTI.items() for stadio, _script in s.stadi_l1
}


def sorgente_di(id_o_stadio: str) -> str:
    ""




    return STADI_L1.get(id_o_stadio, id_o_stadio)











DATO_DEI_LETTORI: dict[str, tuple[tuple[str, ...], str]] = {
    "email": (
        ("*/messages.parquet",),
        "one mailbox per folder; filtered-messages.parquet at the top is a stale derivative",
    ),
    "email_allegati": (
        ("*/allegati/indice.parquet",),
        "the attachment index for each mailbox, written by em-l0-allegati.py",
    ),
}


def dato_di(id_o_stadio: str) -> tuple[str, ...]:
    ""
    if id_o_stadio in DATO_DEI_LETTORI:
        return DATO_DEI_LETTORI[id_o_stadio][0]
    s = SORGENTI.get(sorgente_di(id_o_stadio))
    return s.dato_in if s else ()


def giudizio(sorgente_id: str, giorni: float | None) -> tuple[str, str]:
    ""




    s = SORGENTI.get(sorgente_di(sorgente_id))
    if s is None:
        return "ignota", (
            f"{sorgente_id}: not in the source registry. "
            "Either it is new and must be declared in `tools/sorgenti.py`, or it should not be here."
        )
    if s.natura == "chiusa":
        return "chiusa", f"{sorgente_id}: closed — {s.perche.split('.')[0]}."
    if s.natura == "da_costruire":
        return "da_costruire", f"{sorgente_id}: declared but never built — {s.cosa_e}."
    if s.natura == "spot":

        eta = f"{giorni:.1f} days" if giorni is not None else "age not measurable"
        return "ok", f"{sorgente_id}: spot, {eta} — days do not matter for this source."
    if giorni is None:
        return "ignota", f"{sorgente_id}: age not measurable."
    soglia = s.ritmo_giorni or 7
    if giorni > soglia:
        return "attenzione", (
            f"{sorgente_id}: {giorni:.0f} days without new data, and for a "
            f"{s.natura} source the silence stops being normal after {soglia}."
        )
    return "ok", f"{sorgente_id}: {giorni:.1f} days."


__all__ = [
    "SORGENTI",
    "STADI_L1",
    "Sorgente",
    "attive",
    "chiuse",
    "da_costruire",
    "giudizio",
    "sorgente_di",
]
