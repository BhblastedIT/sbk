""









from __future__ import annotations


STADI: dict[str, tuple[str, str]] = {
    "l0_download": (
        "Source download",
        "Brings the new data from the automatic sources onto the Mac, one after another. The three manual ones stay out.",
    ),
    "l1_personio": (
        "Employees from Personio",
        "Prepares the list of employees, used to recognize nicknames on Slack.",
    ),
    "l1_personio_assenze": (
        "Absences from Personio",
        "Puts vacations and leaves into a day-by-day table.",
    ),
    "l1_phase1": (
        "Reading the main sources",
        "Re-reads the sources already downloaded, from email to voice memos.",
    ),
    "l1_speaker_analysis": (
        "List of Plaud recordings",
        "Updates the list of recordings to read.",
    ),
    "l1_phase2": (
        "Reading calls and recordings",
        "Re-reads Tactiq and Plaud, after the people are already known.",
    ),
    "l1_phase3_wa_deep": (
        "WhatsApp documents and photos",
        "Only when you ask for it: pulls documents and photos out of the exported chats. "
        "Not set up or tested by the author.",
    ),
    "l2_merge": ("Merging contacts", "Puts the people from all sources into a single address book."),
    "l2_entity_map_cleanup": (
        "Cleaning up links",
        "Removes the links left without a person after the merge.",
    ),
    "l2_duckdb": (
        "Views for questions",
        "Prepares the database that queries the files without copying them.",
    ),
    "l2_sqi": (
        "Signal quality",
        "Separates noise from signal by sender, channel, recording and call.",
    ),
    "l3_extract": ("Decisions from the texts", "The model reads the texts and pulls out the decisions."),
    "l3_extract_rel": (
        "Relationships from the texts",
        "The model reads the texts and pulls out who is connected to whom.",
    ),
    "l3_deep_extract": (
        "Facts from the texts",
        "The model reads the texts more deeply and pulls out the facts.",
    ),
    "l1_inventario": (
        "Inventory",
        "Merges the inventory sources into three tables: domains, repos and people.",
    ),
    "l2_knowledge_extract": (
        "Facts into the brain",
        "Writes the new facts into the cards for people and companies. It's the only step that brings new facts.",
    ),
    "l2_ricorrenze": (
        "Birthdays and name days",
        "Puts dates of birth, birthdays and name days onto the cards.",
    ),
    "l2_episodes": (
        "Episodes",
        "Groups the facts by document, i.e. by meeting, thread, call or note.",
    ),
    "l2_calendar_episodes": (
        "Meetings from the calendar",
        "Each calendar event becomes an episode with the participants.",
    ),
    "l2_email_participants": (
        "Email recipients",
        "Adds to the email episodes whoever received the message.",
    ),
    "l2_knows": (
        "Who had access",
        "For each person, the episodes they were present at or received.",
    ),
    "l3_subject_index": ("Topic index", "For each topic, who had access to it."),
    "l2_attachment_discovery": (
        "Attachments of the main people",
        "Finds the files exchanged with the main people, across all sources.",
    ),
    "l2_person_deep_context": (
        "Complete profiles",
        "For the main people, pulls together everything that is known.",
    ),
    "rq_00_weights": ("Weight of interactions", "Gives each interaction a weight by type."),
    "rq_01_decay": (
        "State of relationships over time",
        "Says whether a relationship is active, cooling, dormant or over.",
    ),
    "rq_02b_signals": (
        "Relationship signals",
        "Gathers the signals of each relationship, one row per person.",
    ),
    "rq_03_types": (
        "Relationship type",
        "Says what kind of relationship it is, for example colleague, former employee or investor, with fixed rules and "
        "never calling the model. Those the rules don't recognize stay unknown.",
    ),
    "rq_02_scoring": (
        "Relationship score",
        "A score from 1 to 10 for each relationship, with the trend and the circle.",
    ),
    "rqv4_bridge": (
        "One code per person",
        "Reduces to a single code the four ways a person is recorded.",
    ),
    "rqv4_backfill": (
        "Event log",
        "Adds the new interactions to the event log.",
    ),
    "rqv4_content_quality": (
        "Depth of conversations",
        "Measures how personal or strategic the conversations with each person are.",
    ),
    "rqv4_snapshot": (
        "Snapshot of the scores",
        "Recomputes the expired scores and saves the day's snapshot.",
    ),
    "l3_shadow": (
        "People mentioned",
        "Finds who is named in conversations but is not in the address book.",
    ),
    "l3_graph": (
        "Relationship graph",
        "The map of who is connected to whom, with the groups and the paths to an introduction.",
    ),
    "l3_index": (
        "Search index",
        "Prepares the semantic search over email, calls, chats and documents. Runs on the Mac.",
    ),
    "l3_fact_index": (
        "Fact index",
        "Allows questions like «who works on AI» over the extracted facts.",
    ),
    "l3_decay": (
        "Relationships that are cooling",
        "Prepares the alerts about relationships cooling more than usual.",
    ),
    "freshness": ("Data freshness", "The report on how old each source's data is."),
    "pipeline_status": (
        "Pipeline status",
        "Snapshots the pipeline status to a file. In the chain it does not write to Google Sheets.",
    ),
    "l3_calendario_ricorrenze": (
        "Birthday calendars",
        "Updates your Google calendars, only with the people you have chosen.",
    ),
}


FONTI: dict[str, tuple[str, str]] = {
    "email": ("Email", "Your mail and the work mailboxes"),
    "calendar": ("Calendar", "Appointments, past and future"),
    "microsoft365": ("Microsoft 365", "Your Outlook mail, calendar and contacts"),
    "imap-caldav": ("IMAP and CalDAV", "Any mailbox and calendar you reach with an app password"),
    "zoom": ("Zoom", "Your meetings, who was there and the transcripts"),
    "databases": ("Your databases", "People and events from a database of your own"),
    "teams": ("Microsoft Teams", "Your 1:1 and group chats at work"),
    "contacts": ("Contacts", "Your address book, from an export or Google Contacts"),
    "telegram": ("Telegram", "The chats you export from Telegram Desktop"),
    "hubspot": ("HubSpot", "Your CRM contacts, companies, deals, notes and tasks"),
    "pipedrive": ("Pipedrive", "Your CRM persons, deals, activities and notes"),
    "atlassian": ("Jira and Confluence", "Your issues and the pages you wrote"),
    "linear": ("Linear", "Your issues, with status, due dates and comments"),
    "fireflies": ("Fireflies", "Your meetings, transcripts and action items"),
    "fathom": ("Fathom", "Your meetings, summaries and action items"),
    "granola": ("Granola", "Your meeting notes and who was there"),
    "slack": ("Slack", "Channels and direct messages"),
    "whatsapp": ("WhatsApp", "The chats you export from your phone"),
    "attio": ("Attio", "The CRM, with companies, deals, notes and recordings"),
    "gdrive": ("Google Drive", "The documents on Drive"),
    "plaud": ("Plaud", "The recordings from the recorder"),
    "tactiq": ("Tactiq", "The call transcripts"),
    "notion": ("Notion", "The pages, read-only"),
    "whoop": ("Whoop", "Sleep, recovery and strain"),
    "voicememos": ("Voice memos", "The voice memos from your iPhone"),
    "linkedin": ("LinkedIn", "Profiles and conversations"),
    "ai-history": ("AI history", "What you typed to your AI assistants, to learn how you work"),
    "clickup":("ClickUp", "The tasks, who does what, by when, what is closed"),
    "personio": ("Personio", "The staff directory"),
    "docusign": ("DocuSign", "The signed contracts"),
    "github": ("GitHub", "The repos, the people you work with, your issues, pull requests and reviews"),
    "gsc": ("Search Console", "Who arrives on the sites, and searching for what"),
    "analytics": ("Google Analytics", "What visitors do on the sites"),
    "chatgpt": ("ChatGPT", "The conversations with ChatGPT"),
    "manus": ("Manus", "The analyses done with Manus"),
}


COME_A_MANO: dict[str, str] = {
    "whatsapp": "You export the chats from your phone and the import brings them in.",
    "voicememos": "You copy the memos into the voice-memos folder. The Mac won't let you read the system one.",
    "linkedin": "You download the export from LinkedIn.",
    "ai-history": "You ask for it: SBK reads your Claude Code logs and the AI chat exports you give it.",
    "databases": "You ask for it: SBK runs the read-only queries you declared on your own database.",
    "telegram": "You export your data from Telegram Desktop and the import brings it in.",
}


PASSI_A_MANO: dict[str, str] = {


    "whatsapp": "One chat at a time, from your phone with Export chat (iPhone and Android both have it), then "
    "move the file to the Mac (AirDrop, Files, a cable or your own cloud drive) and ask Claude to import it. "
    "That brings that chat in. The full update brings all the chats together: it needs a separate export tool "
    "on a computer, SBK does not include one, the choice is yours.",
    "voicememos": "Open Voice Memos on the Mac, select the new recordings and copy them into SBK's voice-memos "
    "folder.",
    "linkedin": "On linkedin.com ask for a copy of your data, from the privacy settings. An email arrives, "
    "usually within 24 hours. Download the zip and ask Claude to import it.",
    "ai-history": "Ask Claude to read your Claude Code logs. If you used other AI chats, download their "
    "exports and ask Claude to import them. Then look at what would be sent to the model, and only if you "
    "agree let it write the files on how you work.",
    "databases": "Ask Claude to read your databases again. It runs the queries you declared in sbk.config.json, "
    "read-only, then maps the rows to people and events.",
    "telegram": "In Telegram Desktop open Settings, Advanced, Export Telegram data. Tick Personal chats and "
    "Private groups, untick Only my messages, choose Machine-readable JSON and export. Then ask Claude to "
    "import the folder.",
}



A_PARTE: dict[str, str] = {}


TOCCA_A_TE: dict[str, str] = {
    "whatsapp": "Your turn, export the chats again from your phone.",
    "voicememos": "Your turn, copy the memos from the iPhone.",
    "linkedin": "Your turn, download the export from LinkedIn.",
    "ai-history": "Your turn, ask Claude to read your AI history again.",
    "databases": "Your turn, ask Claude to read your databases again.",
    "telegram": "Your turn, export your data again from Telegram Desktop.",
}


PASSI_GIRO: dict[str, str] = {
    "email-allegati": "Mail attachments",
    "docusign-pdf": "DocuSign, the contract PDFs",
    "slack-index": "Slack, channel list",
    "slack-canali": "Slack, channels",
    "slack-dm": "Slack, direct messages",
    "contacts-google": "Contacts, Google",
    "backup-kb": "Backup of the brain",
    "ingest": "Re-read and update",
    "tutto": "Re-read with the paid steps",
}

NATURE: dict[str, str] = {
    "continua": "arrives continuously",
    "periodica": "arrives in waves",
    "a_richiesta": "fetched when needed",
    "chiusa": "closed",
    "da_costruire": "to be connected",
}


GRUPPI_FONTI: tuple[dict, ...] = (
    {"id": "a_mano", "nome": "Updated by hand", "nota": "your turn", "chiuso": False},
    {"id": "da_sole", "nome": "Download on their own", "nota": "in the full run", "chiuso": False},
    {"id": "inventari", "nome": "Inventories", "nota": "in the full run", "chiuso": False},
    {"id": "da_collegare", "nome": "To connect", "nota": "still to be built", "chiuso": True},
    {"id": "chiuse", "nome": "Closed", "nota": "nothing arrives anymore", "chiuso": True},
)



FASI: tuple[dict, ...] = (
    {
        "id": "scarico",
        "nome": "Download",
        "etichetta": "L0",
        "primo": "l0_download",
        "descrizione": "The new data arrives on the Mac, source by source.",
    },
    {
        "id": "lettura",
        "nome": "Reading",
        "etichetta": "L1",
        "primo": "l1_personio",
        "descrizione": "Each downloaded source becomes a table the pipeline can read.",
    },
    {
        "id": "unione",
        "nome": "Merge",
        "etichetta": "L2",
        "primo": "l2_merge",
        "descrizione": "People are recognized from one source to another.",
    },
    {
        "id": "estrazione",
        "nome": "Extraction from texts",
        "etichetta": "L3",
        "primo": "l3_extract",
        "descrizione": "The model reads the texts and pulls out decisions, relationships and facts. It costs, it starts only if "
        "you decide so.",
    },
    {
        "id": "conoscenza",
        "nome": "Knowledge",
        "etichetta": "L2 · L3",

        "primo": "l2_knowledge_extract",
        "descrizione": "The new facts enter the brain, with episodes and profiles.",
    },
    {
        "id": "relazioni",
        "nome": "Relationships",
        "etichetta": "RQ",
        "primo": "rq_00_weights",
        "descrizione": "How strong each relationship is and how it's going.",
    },
    {
        "id": "grafo",
        "nome": "Graph and indexes",
        "etichetta": "L3",
        "primo": "l3_shadow",
        "descrizione": "The graph, the search, the final checks and the birthday calendars.",
    },
)


RUN: dict[str, dict] = {
    "full": {
        "nome": "Full run free",
        "frase": "Downloads all the sources and then re-reads and updates, at no cost.",
    },
    "full_completa": {
        "nome": "Complete full run",
        "frase": "Like the free one, plus the paid steps you choose, with the expected cost.",
    },
    "l0": {
        "nome": "Download all sources",
        "frase": "Only the source download for the round, in lanes as in the full run, without re-reading them.",
    },
    "ingest": {
        "nome": "Re-read and update",
        "frase": "Re-reads the sources already downloaded and carries them up to the brain, at no cost.",
    },
    "propaga": {
        "nome": "Propagate",
        "frase": "Redoes the steps after reading. On its own it brings no new facts.",
    },
    "ricostruisci": {
        "nome": "Rebuild",
        "frase": "Like Propagate, but redoes everything from the merge onward.",
    },
    "tutto": {
        "nome": "The whole chain with spending",
        "frase": "Re-reads and also does the three paid steps. Does not download the sources.",
    },
}







VOCABOLARIO: dict[str, dict[str, dict[str, str]]] = {
    "run": {
        "in_corso": {"parola": "in progress", "salute": "in_corso", "aiuto": "It's running right now."},
        "ok": {
            "titolo": "finished",
            "parola": "finished",
            "salute": "ok",
            "aiuto": "It closed all of its steps.",
        },
        "incompleto": {
            "titolo": "finished, incomplete",
            "parola": "incomplete",
            "salute": "attenzione",
            "aiuto": "It reached the end, but at least one step did not close.",
        },
        "fallito": {
            "titolo": "failed",
            "parola": "failed",
            "salute": "errore",
            "aiuto": "It stopped on an error, the later steps did not start.",
        },
        "fermato": {
            "titolo": "stopped",
            "parola": "stopped by you",
            "salute": "neutra",
            "simbolo": "fermato",
            "aiuto": "Stopped before the end with Stop.",
        },
        "interrotto": {
            "titolo": "interrupted",
            "parola": "interrupted",
            "salute": "attenzione",
            "aiuto": "It was interrupted without saying how it ended, for example by a Mac restart. It needs to be redone.",
        },
        "non_partito": {
            "titolo": "did not start",
            "parola": "did not start",
            "salute": "neutra",
            "simbolo": "fermato",
            "aiuto": "It did not start, another run was already running.",
        },
        "sconosciuto": {
            "titolo": "finished without saying how",
            "parola": "unknown outcome",
            "salute": "neutra",
            "simbolo": "non_misurata",
            "aiuto": "The log does not say how it ended.",
        },
    },
    "passo": {
        "fatto": {"parola": "done", "salute": "ok", "aiuto": "The step closed fine."},
        "in_corso": {"parola": "in progress", "salute": "in_corso", "aiuto": "It's running right now."},
        "ritento": {
            "parola": "retry",
            "salute": "attenzione",
            "aiuto": "It did not close, and it retries on its own. There are three attempts.",
        },
        "fallito": {
            "parola": "failed",
            "salute": "errore",
            "aiuto": "It did not close even on the last attempt. The run continues with the others.",
        },
        "saltato": {
            "parola": "out of this run",
            "salute": "neutra",
            "simbolo": "saltato",
            "aiuto": "It did not run in this run, because nothing had changed or because it is not part of it.",
        },
        "interrotto": {
            "parola": "interrupted",
            "salute": "attenzione",
            "aiuto": "It stopped halfway, it needs to be redone.",
        },
        "da_fare": {
            "parola": "to do",
            "salute": "neutra",
            "simbolo": "mai",
            "aiuto": "It still has to start.",
        },
    },
    "regola": {
        "sì": {
            "parola": "respected",
            "salute": "ok",
            "simbolo": "spunta",
            "aiuto": "Today's code respects it.",
        },
        "in parte": {
            "parola": "partly",
            "salute": "attenzione",
            "simbolo": "in_parte",
            "aiuto": "The code respects it only partly, the evidence says what's missing.",
        },
        "no": {
            "parola": "not respected",
            "salute": "errore",
            "simbolo": "no",
            "aiuto": "Today's code does not respect it, the evidence says why.",
        },
        "": {
            "parola": "not verified",
            "salute": "neutra",
            "simbolo": "non_misurata",
            "aiuto": "No one verified it against today's code, or its evidence cites code that no longer exists.",
        },
    },
    "chi": {
        "app": {"parola": "Handled from here", "salute": "in_corso"},
        "tu": {"parola": "Your turn", "salute": "attenzione"},
        "claude": {"parola": "Claude handles it", "salute": "neutra"},
        "nessuno": {"parola": "Nothing to do", "salute": "neutra"},
        "": {"parola": "To look at", "salute": "neutra"},
    },
}



GUIDA: dict = {
    "titolo": "How to read SBK",
    "sottotitolo": "Everything has a color, a symbol and a word. The color alone is never enough.",
    "legenda": [
        {
            "parola": "Done",
            "salute": "ok",
            "frase": "Green only with proof: a successful download or a step that read the current data.",
        },
        {
            "parola": "Hasn't run since…",
            "salute": "neutra",
            "simbolo": "non_gira",
            "frase": "Gray: new data arrived after its last round. It says since when it hasn't run, and Re-read and update "
            "brings it in.",
        },
        {
            "parola": "To look at",
            "salute": "attenzione",
            "frase": "Orange: idle for longer than its rhythm, or new data waiting for more than a day.",
        },
        {
            "parola": "Failed",
            "salute": "errore",
            "frase": "Red: the last attempt didn't go through. There's always a way to redo it.",
        },
        {"parola": "In progress", "salute": "in_corso", "frase": "Blue: it's running right now."},
        {
            "parola": "You decide",
            "salute": "neutra",
            "simbolo": "a_pagamento",
            "frase": "The card: it calls the metered model and starts only if you choose it.",
        },
        {
            "parola": "By hand",
            "salute": "neutra",
            "simbolo": "manuale",
            "frase": "The hand: you bring it, or it's idle because you decided so.",
        },
    ],
    "sezioni": "Overview says whether you can trust the data and what to fix. Sources shows where the data comes from and "
    "how fresh it is. Pipeline shows all the steps, phase by phase, with the last time of each. Run follows "
    "what's running, with the lanes and the log, including runs launched from a terminal. Spending and API key holds the estimate "
    "of the paid steps and whether your ANTHROPIC_API_KEY is set. Rules says how each source is downloaded and what each step does. "
    "Tools holds the alerts, the settings, the Mac's memory and the disk. Mail holds the rules for your mailboxes, "
    "who stays in the Main inbox and who goes to a label. To sign holds the contracts awaiting your signature. Pages "
    "holds the pages I prepared for you, Inspiration the things you save because they inspire you.",
    "run": "Full run free downloads all the sources, makes a copy of the brain and re-reads at no cost. Complete, top "
    "right, does the same plus the paid steps you choose, with the expected cost and two confirmations before "
    "spending. The download goes in lanes: base, Slack, ClickUp and Drive together, if the Mac's memory allows. One run "
    "at a time, and you can close the window, the run keeps going.",
    "nota": "Hover over a symbol, a colored word or a number and it tells you what it means. Search for anything "
    "with ⌘F, commands too. With ⌘ and the section number you switch from one to another, in the order of the "
    "sidebar, ⌘0 for Inspiration and ⌘⇧P for Pages.",
}






CAPSULA: dict[str, str] = {
    "full_run": "Last full run {quando}",
    "scarico": "Last download {quando}",
    "senza_rilettura": "without re-read",
    "incompleto": "incomplete",
    "non_finito": "not finished",
    "interrotto": "interrupted",
    "fermato": "stopped by you",
    "in_corso": "in progress",
    "mai": "No full run yet",
    "da_terminale": "From a terminal",
    "aiuto": "Nothing is running now. Green if the last full run, download and re-read, finished; orange if it's incomplete or "
    "not finished; gray if after the download the re-read did not start. Click for the Run section (⌘J).",
    "aiuto_mai": "Nothing is running now, and there hasn't been a full run yet. Click for the Run section (⌘J).",
    "aiuto_run": "The run that's running now and the step it reached. The line below is the share of time already done. Click "
    "to follow it in the Run section (⌘J).",
    "aiuto_terminale": "A run started from a terminal. Click to follow it in the Run section (⌘J).",
}







COMPLETA: dict[str, str] = {
    "bottone": "Complete",
    "aiuto_bottone": "Complete full run, paid. Before starting I ask you for two confirmations.",
    "aiuto_bottone_stima": "With all the steps the last estimate is {cifra}.",
    "titolo": "Complete full run",
    "titolo_tutto": "The whole chain with spending",
    "sottotitolo": "Confirmation 1 of 2. Choose the paid steps. Until you also confirm step 2 nothing starts "
    "and nothing is spent.",
    "sottotitolo_tutto": "Confirmation 1 of 2. Re-reads the sources already downloaded and runs the paid steps you choose, without "
    "downloading. Until you also confirm step 2 nothing starts and nothing is spent.",
    "step_a_pagamento": "Paid steps",
    "scegli_tutti": "Choose all",
    "togli_tutti": "Clear all",
    "totale": "Chosen total",
    "conteggio": "{n} of {m} steps",
    "nessuno_scelto": "Choose at least one step, or use the Full run free.",
    "annulla": "Cancel",
    "avanti": "Next, {cifra}",
    "avanti_senza_stima": "Next without estimate",
    "ricalcola": "Recompute the estimate",
    "aiuto_ricalcola": "Counts again the documents to read with three dry runs, without spending anything. It may take "
    "a few minutes.",
    "cifra": "about {n} $",
    "zero": "0 $",
    "da_calcolare": "to be computed",
    "incompleto": "incomplete",
    "documenti": "{n} documents to read",
    "documenti_mai": "documents not yet counted",
    "fermo_dal": "idle since {data}",
    "mai_fatto": "never done",
    "chiave_nessuna": "ANTHROPIC_API_KEY is not set, so the paid steps cannot start. Put it in .env or in the environment.",
    "chiave_paga": "The paid steps use {nome}.",
    "stima": "Estimate {quando}.",
    "stima_dopo_run": "Estimate {quando}, made after the last run.",
    "nota": "It's an estimate, the real figure may change.",
    "nota_scarico": "It counts the documents already downloaded, and this run's download adds more, so the real figure may "
    "rise.",
    "nota_tetto": "No batch starts if it costs more than this figure plus {pct}%, the margin you set in Tools.",
    "nota_errore": "{errore} What you see is {quando}.",
    "nota_in_corso": "In gray the last estimate, {quando}. I recompute it now by counting the documents, without spending "
    "anything. It may take a few minutes.",
    "nota_in_corso_prima": "Counting the documents to read, without spending anything. It may take a few minutes.",
    "conferma_titolo": "Really spend {cifra}?",
    "conferma_titolo_senza_stima": "Really spend, without an estimate?",
    "conferma_messaggio": "Confirmation 2 of 2. {step} will start, paid{chiave}. After this click the spending begins.",
    "conferma_chiave": ", with the key «{nome}»",
    "conferma_si": "Yes, spend {cifra}",
    "conferma_si_senza_stima": "Yes, start and spend",
    "e": "and",
}

MESI = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


def nome_stadio(sid: str, tecnico: str) -> str:
    return STADI.get(sid, (tecnico, ""))[0]


def frase_stadio(sid: str) -> str:
    return STADI.get(sid, ("", ""))[1]


def nome_fonte(fid: str) -> str:
    return FONTI.get(fid, (fid, ""))[0]


def descrizione_fonte(fid: str, cosa_e: str = "") -> str:
    return FONTI.get(fid, ("", cosa_e))[1]
