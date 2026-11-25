#!/usr/bin/env python3
"""The SecondBrain tasks engine: your tasks live here as an append-only event log; the app calls it through
`sb-motore.py cose ...` (no arguments prints the page as JSON, a verb such as nuova, fatta or priorita changes a task).
"""























































from __future__ import annotations

import contextlib
import copy
import errno
import fcntl
import functools
import json
import math
import os
import re
import sys
import threading
import time
import unicodedata
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sb_cose as C  # noqa: E402 le parole delle date e delle stime, e la lettura di ClickUp per l'importazione


CARTELLA = Path(os.environ.get("SB_ATTIVITA_DIR") or Path.home() / ".sbk-data" / "attivita")





TIPI = ("da_fare", "in_corso", "aspetta", "fatta", "non_serve")
TIPI_CHIUSI = ("fatta", "non_serve")


SEGNI = {
    "da_fare": ("circle", "circle.dashed", "circle.dotted", "square"),
    "in_corso": (
        "circle.lefthalf.filled",
        "circle.bottomhalf.filled",
        "play.circle",
        "square.lefthalf.filled",
    ),
    "aspetta": ("pause.circle", "person.crop.circle.badge.clock", "hourglass.circle", "clock"),
    "fatta": ("checkmark.circle.fill", "checkmark.seal.fill", "checkmark.square.fill"),
    "non_serve": ("xmark.circle", "minus.circle", "slash.circle"),
}

SEGNO_DUBBIO = "questionmark.circle"
COLORI = ("grigio", "blu", "viola", "giallo", "arancio", "verde", "rosso")
STATI_PARTENZA = (
    ("da_fare", "da_fare", "circle", "grigio"),
    ("in_corso", "in_corso", "circle.lefthalf.filled", "blu"),
    ("in_attesa", "aspetta", "pause.circle", "giallo"),
    ("s-aspetta-te", "aspetta", "person.crop.circle.badge.clock", "arancio"),
    ("s-piu-avanti", "da_fare", "circle.dashed", "grigio"),
    ("fatta", "fatta", "checkmark.circle.fill", "verde"),
    ("s-non-serve", "non_serve", "xmark.circle", "grigio"),
)

NOME_PARTENZA = {
    "da_fare": "stato_nome_da_fare",
    "in_corso": "stato_nome_in_corso",
    "in_attesa": "stato_nome_in_attesa",
    "s-aspetta-te": "stato_nome_aspetta_te",
    "s-piu-avanti": "stato_nome_piu_avanti",
    "fatta": "stato_nome_fatta",
    "s-non-serve": "stato_nome_non_serve",
}

SENZA_AREA = "senza_area"


IMPOSTAZIONI_PARTENZA = {
    "veloci_minuti": 30,
    "urgenti": {"p1": True, "giorni_prima": 6, "giorni_dopo": 7},
    "settimana": {
        "inizio": 0,
        "giorni": [0, 1, 2, 3, 4],
        "dalle": "09:00",
        "alle": "19:00",
        "giornata_minuti": 480,
    },
}

PRIORITA = {0: "P0", 1: "P1", 2: "P2", 3: "P3"}

DA_CLICKUP = {"urgent": 1, "high": 2, "normal": 3, "low": 3, None: 3}

CAMPI = ("titolo", "descrizione", "stato", "priorita", "scadenza", "stima", "area", "pianificata")

DURATA_SENZA_STIMA = 30

STIMA_MAX = 60_000
MESI_BREVI = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")
GIORNI_BREVI = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

FATTE_GIORNI = 30
GRANDE = 9_999_999_999_999

TESTI = {
    "titolo": "Tasks",
    "sottotitolo": "Your to-do list. Your tasks live here, changes don't go to ClickUp.",
    "area_altro": "Other",

    "voce_priorita_0": "P0, emergency",
    "aiuto_priorita": "P0 is an emergency, you drop everything and do it. P1 high, P2 medium, P3 low.",
    "aiuto_stato": "Where it stands. Change it here.",
    "aiuto_stima": "How long it takes. Change it here.",
    "aiuto_data": "Pick a new due date here.",
    "aiuto_area": "The area it belongs to, for example Legal or Acme. Change it here.",
    "aiuto_cerchio_da_fare": "To do. One click marks it done (⌘K).",
    "aiuto_cerchio_in_corso": "In progress. One click marks it done (⌘K).",
    "aiuto_cerchio_in_attesa": "Waiting. One click marks it done (⌘K).",
    "aiuto_cerchio_fatta": "Done. One click reopens it (⌘K).",

    "colonna_task": "Task",
    "colonna_stato": "Status",
    "colonna_priorita": "Priority",
    "colonna_scadenza": "Due date",
    "colonna_stima": "Estimated time",
    "colonna_area": "Area",
    "colonna_cambio": "Last change",
    "colonna_creata": "Created on",
    "colonne_rimetti": "Reset columns",

    "vista_urgenti": "Urgent",
    "aiuto_vista_urgenti": "P0s, P1s and those due in the last seven days or the next six.",
    "vuoto_vista_urgenti": "No urgent task.",
    "vista_veloci": "Quick",
    "aiuto_vista_veloci": "Tasks of half an hour or less. By due date first, then by priority.",
    "vuoto_vista_veloci": "No task of half an hour or less.",
    "vista_attese": "Waiting on you",
    "aiuto_vista_attese": "The decisions and go-aheads only you can give.",
    "vuoto_vista_attese": "No decision is waiting on you.",


    "vista_tutte": "Table",
    "aiuto_vista_tutte": "All open tasks in a table, split by priority.",
    "vuoto_vista_tutte": "There is no open task.",
    "vista_foglio": "Sheet",
    "aiuto_vista_foglio": "All open tasks in a compact table, one row per task, like a spreadsheet.",
    "vuoto_vista_foglio": "There is no open task.",
    "vista_bacheca": "Board",
    "aiuto_vista_bacheca": "All open tasks in columns by priority. Drag a task to another column to change its priority.",
    "vuoto_vista_bacheca": "There is no open task.",
    "vista_calendario": "Calendar",
    "aiuto_vista_calendario": "All open tasks on their due day. Drag a task onto a day to give it that date.",
    "vuoto_vista_calendario": "No task with a date.",
    "aiuto_vista_mia": "A view you made yourself. Right-click to rename, duplicate or delete it.",
    "vuoto_vista_mia": "No task in this view.",
    "vista_in_corso": "In progress",
    "aiuto_vista_in_corso": "The ones you have started.",
    "vuoto_vista_in_corso": "Nothing in progress.",
    "vista_fatte": "Done",
    "aiuto_vista_fatte": "Closed tasks, done or no longer needed, most recent on top. Reopen them here.",
    "vuoto_vista_fatte": "No task done.",
    "vista_eliminate": "Deleted",
    "aiuto_vista_eliminate": "These you have deleted. You can put them back in the list.",
    "vuoto_vista_eliminate": "No task deleted.",

    "aiuto_nuova_vista": "Adds a view that starts from the filters of this one.",
    "nome_vista_nuova": "New view",
    "nome_vista_copia": "{nome} {n}",
    "altre_viste": "Other views",
    "aiuto_altre_viste": "The views that don't fit here.",
    "rinomina": "Rename",
    "duplica": "Duplicate",
    "duplica_tabella": "Duplicate as table",
    "duplica_foglio": "Duplicate as sheet",
    "duplica_bacheca": "Duplicate as board",
    "duplica_calendario": "Duplicate as calendar",
    "nascondi_vista": "Hide",
    "elimina_vista": "Delete the view",
    "rimetti_vista": "Reset it",
    "viste_nascoste": "Hidden views",
    "viste_eliminate": "Deleted views",
    "aiuto_vista_cambiata": "This view has extra filters, not saved.",

    "filtra": "Filter",
    "aiuto_filtra": "Shows only the tasks you pick. Switching view drops the unsaved filters.",
    "mostra": "Show",
    "aiuto_mostra": "How this view looks. Groups, order, done tasks and layout stay in the view, columns and titles apply to all.",
    "menu_gruppi": "Groups",
    "menu_ordine": "Order",
    "menu_colonne": "Columns",
    "menu_fatte": "Done in this view",
    "menu_righe": "Titles",
    "menu_modo": "Layout",
    "nessun_gruppo": "No group",
    "ordine_pronto": "The view's order",
    "ordine_titolo": "Title",
    "crescente": "Ascending",
    "decrescente": "Descending",
    "fatte_no": "Don't show them",
    "fatte_7_giorni": "Last 7 days",
    "fatte_tutte": "All",

    "fatte_tasto_mostra": "Show done tasks",
    "fatte_tasto_nascondi": "Hide done tasks",
    "aiuto_fatte_tasto_mostra": "Brings back the done tasks of this view, at the bottom.",
    "aiuto_fatte_tasto_nascondi": "Removes the done tasks from this view. A just-closed task lingers a moment, then leaves.",
    "righe_una": "On one line",
    "righe_due": "On two lines",
    "togli_filtri": "Clear filters",


    "vuoto_filtri": "With these filters there is no task.",
    "settimana_non_arrivata": "The week has not arrived.",
    "salva_nella_vista": "Save in the view",
    "salva_come_vista": "Save as a new view",
    "filtro_scadute": "Overdue",
    "filtro_oggi": "Today",
    "filtro_settimana": "Within 7 days",
    "filtro_con_data": "With a date",
    "filtro_senza_data": "No date",
    "filtro_fino_30": "Up to 30 minutes",
    "filtro_fino_120": "Up to 2 hours",
    "filtro_senza_stima": "No estimated time",
    "pastiglia": "{valori}",

    "gruppo_scadute": "Overdue",
    "gruppo_oggi": "Today",
    "gruppo_domani": "Tomorrow",
    "gruppo_settimana": "Within 7 days",

    "gruppo_dopo": "Later",
    "gruppo_senza": "No date",
    "gruppo_fatte_vista": "Done",
    "nuova_qui": "New task here",
    "aiuto_apri_gruppo": "Shows the tasks of this group.",
    "aiuto_chiudi_gruppo": "Hides the tasks of this group.",

    "fatta": "Mark done",
    "fatte_tante": "Mark done",
    "riapri": "Reopen",
    "elimina": "Delete",
    "elimina_tante": "Delete the {n}",
    "aiuto_elimina": "Removes it from the list. It stays among the deleted ones and can be put back, also with ⌘Z.",
    "ripristina": "Put back in the list",
    "aiuto_ripristina": "Puts it back among the open tasks, as it was.",
    "apri_dettaglio": "Open the detail",
    "modifica_titolo": "Edit the title",
    "copia_titolo": "Copy the title",
    "copia_titoli": "Copy the titles",
    "apri_clickup": "Open as it was on ClickUp",
    "aiuto_apri_clickup": "Opens the page this task came from. What you change here does not change there.",
    "scelte_tanti": "{n} tasks selected",
    "togli_scelta": "Deselect",
    "data_scegli": "Pick a day…",
    "data_togli": "Remove the date",
    "stima_togli": "Remove the estimated time",
    "foglio_sposta": "Move",
    "aggiungi": "Add",

    "aiuto_chiudi_dettaglio": "Closes the detail (Esc).",
    "descrizione_segnaposto": "Write a note here",
    "titolo_segnaposto": "The task title",
    "creata": "Created {giorno}",
    "ultimo_cambio": "Last change {giorno}",
    "intanto_cambiata": "Meanwhile it changed somewhere else.",
    "tieni_la_mia": "Keep mine",
    "prendi_nuova": "Take the new one",
    "dettaglio_tante": "Changes here apply to all {n}.",

    "conteggio_task": "{n} tasks",
    "conteggio_scelte_uno": "one selected",
    "conteggio_scelte_tanti": "{n} selected",
    "annulla": "Cancel",
    "riprova": "Retry",
    "aiuto_annulla_riga": "Undoes the last action (⌘Z).",

    "menu_task": "Task",
    "voce_nuova": "New task",
    "voce_dettaglio": "Show or hide the detail",
    "voce_cerca": "Search the tasks",
    "voce_scegli_tutte": "Select all",
    "voce_deseleziona": "Deselect",
    "voce_vista_prima": "Previous view",
    "voce_vista_dopo": "Next view",
    "voce_rileggi": "Reload the tasks",
    "voce_fatte": "Open the done ones",
    "voce_eliminate": "Open the deleted ones",

    "nuova_segnaposto": "New task, type and press Enter",
    "aiuto_nuova": "Type the title and press Enter. At the end you can add the priority and the date, for example «p1 domani» (Italian date words).",
    "aiuto_etichetta": "I read it at the end of the title. With the cross it stays written in the title and does not become priority or date.",
    "cerca": "Search the tasks",
    "ricerca_vuota": "No task with «{q}».",
    "nessuna_qui_altrove": "None here. There are {n} among all the tasks.",
    "nessuna_qui_altrove_uno": "None here. There is one among all the tasks.",
    "cerca_fra_tutte": "Search across all",
    "togli_ricerca": "Clear the search",

    "aiuto_bacheca": "Drag a task to another column to give it that value.",
    "colonna_vuota": "None",
    "aiuto_colonna_fatta": "Today's done tasks. Drop a task here to mark it done.",
    "aiuto_colonna_chiusa": "Empty column. You can drop a task here.",
    "cal_scadute": "Overdue",
    "cal_senza_data": "No date",
    "cal_piu": "+{n}",
    "cal_oggi": "Today",
    "aiuto_cal_oggi": "Back to this month.",
    "aiuto_mese_prima": "The previous month.",
    "aiuto_mese_dopo": "The next month.",
    "aiuto_cassetto": "The tasks with no day on the calendar. Drag one onto a day to give it that date.",
    "cassetto_chiuso": "{s} overdue · {n} no date",
    "cassetto_scadute": "{n} overdue",
    "cassetto_scaduta": "one overdue",
    "cassetto_senza": "{n} no date",
    "cassetto_unisci": "{a} · {b}",
    "aiuto_cassetto_chiuso": "Shows the overdue ones and those with no date.",
    "cal_nessuna_scaduta": "None overdue.",
    "cal_nessuna_senza": "None without a date.",
    "aiuto_giorno_passato": "A past day. You can't drop a task here.",
    "nuova_nel_giorno": "New task for {quando}",


    "aiuto_detta": "Dictate a task or a change, for example «move Quarterly Report to Monday and make it P0» (⇧⌘N).",
    "voce_detta": "Dictate…",
    "aiuto_scrivi_comando": "Write a request about your tasks the way you would say it. A background session reads it and replies here.",
    "comando_segnaposto": "Write what you want, for example «move Quarterly Report to Monday and make it P0»",
    "manda_comando": "Send",
    "ti_ascolto": "Listening {tempo}",
    "fatto_dettato": "Done",
    "aiuto_fatto_dettato": "I send it to the session that works on your tasks (⌘↩ or ⇧⌘N).",
    "annulla_dettato": "Cancel",
    "aiuto_annulla_dettato": "Stops without sending. The audio is kept aside (Esc).",
    "livello_basso": "I can't hear you yet",
    "aiuto_livello": "How well I hear you",
    "chiedo_microfono": "Asking macOS for the microphone",
    "invio_dettato": "Sending it",
    "microfono_negato": "The microphone is not allowed for SBK. Turn it on in System Settings, Privacy & Security, Microphone, then try again.",
    "microfono_non_parte": "The microphone did not start. Check the Mac's audio input, or type the request.",
    "microfono_occupato": "The microphone is already recording a reply in Inspiration.",
    "apri_impostazioni": "Open Settings",
    "dettato_corto": "Too short, I didn't send it. Try again.",
    "dettato_da_parte": "Dictation cancelled after {durata}. I'm keeping it aside.",
    "manda_lo_stesso": "Send it anyway",
    "dettato_non_mandato": "A dictation from {ora} did not reach the session. The audio is saved here.",
    "manda_dettato": "Send it",
    "aiuto_manda_dettato": "Sends it to the session that works on your tasks, as if you had just said it.",
    "chiudi_richiesta": "Close",
    "aiuto_chiudi_richiesta": "Removes it from here. It stays in the request log.",
    "richieste_altre": "{n} more",
    "richieste_altra": "One more",
    "correggi_segnaposto": "Write the correct sentence",
    "risposta_segnaposto": "Your reply",
    "aiuto_ascolta": "Replay the audio you sent.",
    "aiuto_voce_lavora": "A voice request is being processed.",
    "aiuto_voce_chiede": "A voice request is waiting on you.",
    "aiuto_voce_registra": "You are dictating a request for the tasks.",



    "aiuto_barra": "{sottotitolo} {numero} (⌘T).",

    "fatte_altre_uno": "Show the other one too",
    "fatte_altre": "Show the other {n} too",


    "titolo_stato_da_area": "All open tasks of an area in one status",
    "togli_stato_in": "Remove the status and move its tasks to…",
    "togli_area_in": "Remove the area and move its tasks to…",
    "aiuto_n_aperte": "{n} open tasks",
    "conteggio_a_vista": "{n} shown of {tot}",
    "azione_commenta": "Comment",
    "azione_commento-togli": "Comment removed",
    "errore_filtri_senza_task": "These filters together leave no task, I'm not saving them in the view.",


    "barra_segnaposto": "Ask or dictate something about your tasks",
    "ferma": "Stop",
    "aiuto_ferma": "Stops and I send it to the session that works on your tasks (⌘↩ or ⇧⌘N).",
    "aiuto_microfono": "Click to speak and click to send, or press and hold and release to send (⇧⌘N).",
    "lavoro_da": "I've been working on it for {n} seconds",
    "lavoro_da_minuti": "I've been working on it for {n} minutes",
    "lavoro_da_minuto": "I've been working on it for a minute",
    "aiuto_filo": "Today's requests. Click to open or close them.",
    "filo_vuoto": "Here you see what you ask me about the tasks and what I did",
    "aiuto_gesto": "Click to see it in the list.",
    "aiuto_numero_zero": "None urgent.",
    "aiuto_numero": "{n} urgent, none P0.",
    "aiuto_numero_uno": "One urgent, none P0.",
    "aiuto_numero_uno_p0": "One urgent, and it's P0.",
    "aiuto_numero_p0_uno": "{n} urgent, one is P0.",
    "aiuto_numero_p0_tanti": "{n} urgent, {p} are P0.",

    "breve_oggi": "today",
    "breve_domani": "tomorrow",
    "breve_ieri": "yesterday",
    "breve_giorni_fa": "{n} days ago",
    "breve_giorno": "{giorno} {n}",
    "breve_data": "{n} {mese}",
    "breve_data_anno": "{n} {mese} {anno}",


    "breve_minuti": "{n} min",
    "breve_ore_minuti": "{h} h {mm}",
    "chiusa_oggi": "Done today",
    "chiusa_ieri": "Done yesterday",
    "chiusa_il": "Done {giorno}",
    "chiusa_non_serve_oggi": "Closed today",
    "chiusa_non_serve_ieri": "Closed yesterday",
    "chiusa_non_serve_il": "Closed {giorno}",
    "eliminata_oggi": "Deleted today",
    "eliminata_ieri": "Deleted yesterday",
    "eliminata_il": "Deleted {giorno}",

    "rivedi_ferme_uno": "Review the P1 overdue since {mese}",
    "rivedi_ferme_tanti": "Review the {n} P1s overdue since {mese}",
    "modo_tabella": "Table",
    "modo_foglio": "Sheet",
    "modo_bacheca": "Board",
    "modo_calendario": "Calendar",

    "esito_fatta": "Done.",
    "esito_fatte_tante": "{n} tasks done.",
    "esito_riaperta": "Reopened.",
    "esito_riaperte_tante": "{n} tasks reopened.",
    "esito_stato": "The status is now {nome}.",
    "esito_stato_tante": "{n} tasks now have status {nome}.",
    "esito_priorita": "It's now {nome}.",
    "esito_priorita_tante": "{n} tasks are now {nome}.",
    "esito_data_davanti": "It's now due {quando}.",
    "esito_data_tante": "{n} tasks are now due {quando}.",
    "esito_data_passata": "The due date is now {quando}, already past.",
    "esito_data_passata_tante": "{n} tasks now have the due date {quando}, already past.",
    "aiuto_scadeva": "It should have been done by {giorno}.",
    "filtro_scelta": "{nome} {n}",
    "esito_data_tolta": "Date removed.",
    "esito_data_tolta_tante": "Date removed from {n} tasks.",
    "esito_stima": "The estimated time is now {quanto}.",
    "esito_stima_tante": "{n} tasks now have an estimated time of {quanto}.",
    "esito_stima_tolta": "Estimated time removed.",
    "esito_stima_tolta_tante": "Estimated time removed from {n} tasks.",
    "esito_area": "It's now in {area}.",
    "esito_area_tante": "{n} tasks are now in {area}.",
    "esito_titolo": "Title changed.",
    "esito_descrizione": "Description saved.",
    "esito_descrizione_aggiunta": "Added to the description.",
    "esito_descrizione_aggiunta_tante": "Added to the description of {n} tasks.",
    "esito_niente": "It was already like that.",
    "esito_nuova": "Added.",

    "esito_origine_c_era": "It was already there.",
    "errore_origine_eliminata": "It was already there, and it's among the deleted ones. I did not make another.",
    "errore_origine_fonte": "The origin source is a short name, no spaces, lowercase.",
    "errore_origine_id": "The origin also needs its id, on one line.",
    "errore_origine_url": "The origin address must be a web page, http or https.",

    "apri_origine": "Open the page it came from",
    "aiuto_apri_origine": "Opens the page this task came from. What you change here does not change there.",
    "apri_origine_clickup": "Open as it was on ClickUp",
    "aiuto_apri_origine_clickup": "Opens the task on ClickUp as it was when it arrived. What you change here does not change there.",
    "apri_origine_inspiration": "Open the idea",
    "aiuto_apri_origine_inspiration": "Opens the Inspiration idea this task came from.",
    "esito_nuova_altrove": "Added. It's not in this view, you'll find it in All.",
    "esito_eliminata": "Deleted.",
    "esito_eliminate_tante": "{n} tasks deleted.",
    "esito_ripristinata": "Put back in the list.",
    "esito_ripristinate_tante": "{n} tasks put back in the list.",
    "esito_annullato": "Undone.",
    "esito_rifatto": "Redone.",
    "esito_vista_nuova": "View added.",
    "esito_vista_nome": "Name changed.",
    "esito_vista_duplicata": "View duplicated.",
    "esito_vista_nascosta": "View hidden. You'll find it again in the +, under Hidden views.",
    "esito_vista_mostrata": "The view is visible again.",
    "esito_vista_eliminata": "View deleted.",
    "esito_vista_ripristinata": "View restored.",

    "esito_vista_ripristinata_nome": "View restored with the name {nome}, because {prima} already existed.",
    "esito_vista_rimessa": "The view is as it was at the start.",
    "esito_vista_salvata": "Saved in the view.",
    "esito_viste_ordine": "View order changed.",
    "esito_importate_uno": "I brought in one task from ClickUp.",
    "esito_importate_tanti": "I brought in {n} tasks from ClickUp.",
    "esito_importate_zero": "There was nothing new to bring in from ClickUp.",
    "riga_esito": "{esito} · {titolo}",

    "azione_fatta": "Done",
    "azione_riapri": "Reopen",
    "azione_stato": "Status",
    "azione_priorita": "Priority",
    "azione_data": "Due date",
    "azione_stima": "Estimated time",
    "azione_area": "Area",
    "azione_titolo": "Title",
    "azione_descrizione": "Description",
    "azione_elimina": "Delete",
    "azione_ripristina": "Put back in the list",
    "azione_nuova": "New task",
    "azione_vista": "View",
    "azione_tante": "{azione} on {n} tasks",

    "errore_sparita": "This task is gone.",
    "errore_titolo": "The title can't be empty.",
    "errore_valore": "I don't know that value.",
    "errore_giorno": "I didn't understand that day.",
    "errore_comando": "I don't know how to make this change.",
    "errore_motore": "Something didn't respond as it should. Try again.",
    "errore_lettura": "Your tasks file can't be read.",
    "errore_cambiata_dopo": "You changed it again afterwards, I won't put it back as it was.",
    "errore_cambiata_altrove": "Meanwhile it changed somewhere else, I won't put it back as it was.",
    "errore_cambiata_telefono": "Meanwhile it changed on the phone, I won't put it back as it was.",

    "errore_fuori_chiave": "The change that came from outside has no readable key.",
    "errore_fuori_da": "The change that came from outside doesn't say where it comes from.",
    "errore_annulla_sparito": "I can't find that action anymore, I can't undo it.",
    "errore_intanto": "Meanwhile it changed somewhere else, I didn't write yours.",
    "errore_vista_sparita": "This view is gone.",
    "errore_vista_pronta": "It's one of the built-in views, you can hide it but not delete it.",
    "errore_vista_non_pronta": "It's a view of yours, there's no starting version to restore.",
    "errore_ultima_vista": "It's the last view left, it can't be removed.",
    "errore_modo": "I don't know this layout.",
    "errore_nome_vuoto": "The name can't be empty.",
    "errore_campo_vista": "This view has no setting with that name.",


    "stato_nome_da_fare": "To do",
    "stato_nome_in_corso": "In progress",
    "stato_nome_in_attesa": "Waiting",
    "stato_nome_aspetta_te": "Waiting on you",
    "stato_nome_piu_avanti": "Later",
    "stato_nome_fatta": "Done",
    "stato_nome_non_serve": "No longer needed",
    "tipo_da_fare": "Open, to do",
    "tipo_in_corso": "Open, in progress",
    "tipo_aspetta": "Open, waiting on someone",
    "tipo_fatta": "Closed, done",
    "tipo_non_serve": "Closed, no longer needed",
    "aiuto_tipo_da_fare": "Open, to start. Counts among the urgent and the quick ones.",
    "aiuto_tipo_in_corso": "Open, you're working on it.",
    "aiuto_tipo_aspetta": "Open, waiting on someone or something.",
    "aiuto_tipo_fatta": "Closed because done. Counts among the done ones.",
    "aiuto_tipo_non_serve": "Closed because no longer needed. Sits with the done ones but isn't counted among them.",
    "filtro_tipo_da_fare": "All to start",

    "filtri_pronti": "Built-in filters",


    "motore_altra_versione": "The Tasks engine is a different version, update the app.",
    "aiuto_filtri_pronti": "Urgent, Quick and Waiting on you. They apply to the view you have open, like the other filters.",
    "filtro_tipo_in_corso": "All the started ones",
    "filtro_tipo_aspetta": "All the waiting ones",
    "aiuto_cerchio_aperta": "{nome}. One click marks it done (⌘K).",
    "aiuto_cerchio_chiusa": "{nome}. One click reopens it (⌘K).",
    "aiuto_stato_sconosciuto": "This status is no longer in the settings.",
    "aiuto_stato_tolto": "You removed this status from the settings. The closed tasks stay here.",
    "nello_stato_oggi": "{nome} since today",
    "nello_stato_ieri": "{nome} since yesterday",
    "nello_stato_giorni": "{nome} for {n} days",
    "colore_grigio": "Gray",
    "colore_blu": "Blue",
    "colore_viola": "Purple",
    "colore_giallo": "Yellow",
    "colore_arancio": "Orange",
    "colore_verde": "Green",
    "colore_rosso": "Red",
    "colore_nessuno": "No color",

    "impostazioni_titolo": "Tasks",
    "impostazioni_stati": "Statuses",
    "impostazioni_aree": "Areas",
    "impostazioni_veloci": "Quick",
    "impostazioni_urgenti": "Urgent",
    "impostazioni_settimana": "Week",
    "aiuto_impostazioni_stati": "The task statuses. The type decides whether a task is open or closed, the name is up to you.",
    "aiuto_impostazioni_aree": "The task areas. You rename, merge and remove them without losing the tasks.",
    "aiuto_impostazioni_veloci": "Tasks with an estimated time up to this sit among the Quick ones. Those with no estimated time don't.",
    "aiuto_impostazioni_urgenti": "Which tasks sit among the urgent ones. The P0s are always there.",
    "aiuto_impostazioni_settimana": "Your work week. The calendar shows these days and these hours, and a day is worth what you write here, even when you write 1g in the estimated time.",
    "impostazioni_apri": "Tasks settings…",
    "modifica_stati": "Edit the statuses…",
    "modifica_aree": "Edit the areas…",
    "stato_nuovo": "New status",
    "area_nuova": "New area…",
    "stato_segnaposto": "The status name",
    "area_segnaposto": "The area name",
    "stato_per_le_nuove": "For new tasks",
    "aiuto_stato_per_le_nuove": "New tasks and the ones you reopen start from this status.",
    "stati_tolti": "Removed statuses",
    "aree_tolte": "Removed areas",
    "togli_stato": "Remove the status",
    "togli_area": "Remove the area",
    "unisci_area": "Merge into…",
    "aiuto_unisci_area": "The tasks of this area show in the one you pick. Separate puts them back as they were.",
    "separa_area": "Separate",
    "rimetti": "Restore",
    "sposta_task_in": "Move the tasks to…",
    "senza_area": "No area",
    "aiuto_senza_area": "Removes the area.",
    "urgenti_p1": "Also the P1s",
    "urgenti_giorni_prima": "Becomes urgent how many days before the due date",
    "urgenti_giorni_dopo": "Stays urgent how many days after the due date",
    "settimana_inizio": "The week starts",
    "settimana_giorni": "Work days",
    "settimana_dalle": "From",
    "settimana_alle": "To",
    "settimana_giornata": "A day is worth",
    "stato_da_area": "Move the tasks of {area} to the status {stato}",
    "aiuto_stato_da_area": "A single action for all open tasks of the area. ⌘Z puts them back as they were.",

    "stima_scrivi": "Enter the time…",
    "stima_segnaposto": "for example 1h30",
    "aiuto_stima_scrivi": "Write how long it takes, for example 45m, 1h30 or 90m. A number on its own is minutes.",
    "durata_minuto": "one minute",
    "durata_mezzora": "half an hour",
    "durata_minuti": "{n} minutes",
    "durata_ora": "one hour",
    "durata_ore": "{n} hours",
    "durata_e_mezza": " and a half",
    "durata_e_minuti": " and {n} minutes",
    "durata_e_un_minuto": " and one minute",
    "breve_ore_tonde": "{h} h",
    "somma_gruppo": "{totale} estimated",
    "somma_senza_uno": "one without time",
    "somma_senza": "{n} without time",
    "somma_su_giornata": "{totale} of {giornata}",
    "somma_separatore": " · ",
    "filtro_veloci": "Up to {quanto}",
    "aiuto_vista_veloci_soglia": "Tasks of {quanto} or less. By due date first, then by priority.",
    "vuoto_vista_veloci_soglia": "No task of {quanto} or less.",
    "aiuto_vista_urgenti_p1": "P0s, P1s and those due in the last {dopo} days or the next {prima}.",
    "aiuto_vista_urgenti_p0": "P0s and those due in the last {dopo} days or the next {prima}.",

    "colonna_inizio": "Start",
    "colonna_chiusa": "Closed on",
    "colonna_rinvii": "Reschedules",
    "colonna_commenti": "Comments",
    "aiuto_inizio": "When you work on it. The due date stays as it is.",
    "aiuto_oltre_scadenza": "It's planned after the due date.",
    "aiuto_da_ripianificare": "It was planned and isn't done.",
    "breve_giorno_ora": "{giorno} {ora}",
    "quando_alle": "{giorno} at {ora}",
    "esito_pianificata": "Planned {quando}.",

    "esito_pianificata_passata": "Planned {quando}, an hour already past.",
    "esito_pianificata_giorno_passato": "Planned {quando}, a day already past.",
    "esito_pianificate_fila": "{n} tasks planned from {quando}, one after another.",
    "esito_pianificate_giorno": "{n} tasks planned {quando}.",
    "esito_pianificata_tolta": "Removed from the calendar.",
    "esito_pianificata_tolta_tante": "{n} tasks removed from the calendar.",
    "azione_pianifica": "Start",
    "togli_dal_calendario": "Remove from the calendar",
    "errore_quando": "I didn't understand that day or time.",
    "errore_calendario": "The calendar can't be read right now. The tasks stay as they are.",

    "aiuto_cambio_te": "Changed by you {quando}",
    "aiuto_cambio_voce": "Changed by voice {quando}",
    "aiuto_cambio_annulla": "Put back as it was {quando}",
    "aiuto_cambio_impostazioni": "Changed from the settings {quando}",
    "aiuto_cambio_clickup": "Born on ClickUp {quando}. Never changed here.",
    "aiuto_cambio_altro": "Changed {quando}",

    "aiuto_cambio_telefono": "Changed from the phone {quando}",


    "aiuto_cambio_spunto": "Changed from an idea {quando}",
    "aiuto_rinvii_uno": "Due date rescheduled once. It was first due {giorno}.",
    "aiuto_rinvii_tanti": "Due date rescheduled {n} times. It was first due {giorno}.",
    "colonne_a_destra_una": "one more column on the right",
    "colonne_a_destra": "{n} more columns on the right",

    "ordina_per": "Sort by",
    "poi_per": "Then by",
    "poi_ancora_per": "Then again by",
    "ordine_nessuno": "None",
    "torna_ordine_vista": "Back to the view's order",
    "ordine_parole_primo": "by {campo}",
    "ordine_parole_poi": ", then by {campo}",
    "ordine_tre_al_piu": "You can sort by at most three columns.",
    "aiuto_intestazione": "Click to sort by this column. With ⇧ you add it after the current order.",
    "ordine_campo_scadenza": "due date",
    "ordine_campo_priorita": "priority",
    "ordine_campo_stima": "estimated time",
    "ordine_campo_titolo": "title",
    "ordine_campo_area": "area",
    "ordine_campo_stato": "status",
    "ordine_campo_cambio": "last change",
    "ordine_campo_creata": "creation date",
    "ordine_campo_inizio": "start",
    "ordine_campo_chiusa": "closing date",
    "ordine_campo_rinvii": "reschedules",
    "ordine_campo_commenti": "comments",
    "verso_scadenza_su": "Nearest first",
    "verso_scadenza_giu": "Farthest first",
    "verso_inizio_su": "Nearest first",
    "verso_inizio_giu": "Farthest first",
    "verso_priorita_su": "P0 to P3",
    "verso_priorita_giu": "P3 to P0",
    "verso_stima_su": "Shortest first",
    "verso_stima_giu": "Longest first",
    "verso_titolo_su": "A to Z",
    "verso_titolo_giu": "Z to A",
    "verso_area_su": "A to Z",
    "verso_area_giu": "Z to A",
    "verso_stato_su": "In the order of the statuses",
    "verso_stato_giu": "In reverse order",
    "verso_cambio_su": "Oldest first",
    "verso_cambio_giu": "Most recent first",
    "verso_creata_su": "Oldest first",
    "verso_creata_giu": "Most recent first",
    "verso_chiusa_su": "Oldest first",
    "verso_chiusa_giu": "Most recent first",
    "verso_rinvii_su": "Least rescheduled first",
    "verso_rinvii_giu": "Most rescheduled first",
    "verso_commenti_su": "Fewest comments first",
    "verso_commenti_giu": "Most comments first",

    "commenti_titolo": "Comments",
    "commenta": "Comment",
    "commenta_segnaposto": "Write a comment",
    "commenti_vuoto": "No comment.",
    "commenti_mostra_cambi": "Also show the changes",
    "aiuto_commenti_colonna": "How many comments it has. One click opens the comments in the detail.",
    "togli_commento": "Remove the comment",
    "aiuto_togli_commento": "Removes it from the task. ⌘Z puts it back.",
    "scritto_da_te": "Written by you",
    "detto_a_voce": "Said by voice",
    "da_una_richiesta": "From a voice request",
    "ultimo_commento": "Last comment {quando}",
    "esito_commento": "Comment added.",
    "esito_commento_tolto": "Comment removed.",
    "azione_commento": "Comment",
    "errore_commento_vuoto": "The comment is empty.",
    "errore_commento_sparito": "This comment is gone.",
    "chi_te": "You",
    "chi_voce": "By voice",
    "chi_clickup": "From ClickUp",
    "chi_impostazioni": "From the settings",
    "chi_annulla": "Put back as it was",
    "chi_altro": "From somewhere else",
    "chi_telefono": "From the phone",
    "chi_spunto": "From an idea",
    "storia_nata": "Created",
    "storia_titolo": "Title «{valore}»",
    "storia_stato": "The status is now {valore}",
    "storia_priorita": "It's now {valore}",
    "storia_scadenza": "Now due {valore}",
    "storia_scadenza_tolta": "Date removed",
    "storia_stima": "Estimated time {valore}",
    "storia_stima_tolta": "Estimated time removed",
    "storia_area": "Now in {valore}",
    "storia_area_tolta": "Now with no area",
    "storia_descrizione": "Description changed",
    "storia_pianificata": "Planned {valore}",
    "storia_pianificata_tolta": "Removed from the calendar",
    "storia_eliminata": "Deleted",
    "storia_ripristinata": "Put back in the list",
    "storia_commento": "Comment «{valore}»",
    "storia_commento_tolto": "Comment removed",
    "storia_commento_rimesso": "Comment put back",

    "esito_stato_nuovo": "Status added.",
    "esito_stato_nome": "Name changed.",
    "esito_stato_tipo": "Type changed.",
    "esito_stato_segno": "Icon changed.",
    "esito_stato_colore": "Color changed.",
    "esito_stati_ordine": "Status order changed.",
    "esito_stato_predefinito": "New tasks start from {nome}.",
    "esito_stato_tolto": "Status removed.",
    "esito_stato_tolto_spostate": "Status removed. {n} tasks now have status {nome}.",
    "esito_stato_rimesso": "Status restored.",
    "esito_stato_da_area": "{n} tasks of {area} now have status {stato}.",
    "esito_area_aggiunta": "Area added.",
    "esito_area_unita": "Merged into {nome}. Its {n} tasks are now there.",
    "esito_area_separata": "Area separated, its tasks went back to {nome}.",
    "esito_area_tolta": "Area removed.",
    "esito_area_tolta_in": "Area removed, its tasks are now in {nome}.",
    "esito_area_tolta_senza": "Area removed, its tasks now have no area.",
    "esito_area_rimessa": "Area restored.",
    "esito_aree_ordine": "Area order changed.",
    "esito_area_colore": "Color changed.",
    "esito_imposta": "Setting saved.",
    "esito_area_creata": "Now in {area}, a new area.",
    "esito_area_creata_tante": "{n} tasks now in {area}, a new area.",
    "esito_area_tolta_via": "Now with no area.",
    "esito_area_tolta_via_tante": "{n} tasks now have no area.",
    "azione_impostazioni": "Settings",

    "errore_stato": "This status doesn't exist. The statuses are {elenco}.",
    "errore_stato_nome_usato": "There's already a status with this name.",
    "errore_stato_era_di": "It's an old name of {nome}. Pick another one.",
    "errore_ultimo_stato": "You need at least one status for to-do tasks and one for done ones.",
    "errore_stato_con_task": "There are {n} tasks in this status. Pick where to move them.",

    "errore_stato_con_task_una": "There's one task in this status. Pick where to move it.",
    "errore_tipo_con_task": "There are {n} tasks in this status. Make a new status of the type you want and move them there.",
    "errore_tipo_con_task_una": "There's one task in this status. Make a new status of the type you want and move it there.",
    "errore_stato_lungo": "A status name goes on one line, eighty characters at most.",
    "errore_stato_nome_tolto": "There's a removed status with this name. Restore it instead of making another.",
    "errore_tipo_con_eliminate": "This status has deleted tasks you could restore. Make a new status of the type you want.",
    "errore_tipo": "I don't know this type.",
    "errore_segno": "This icon isn't among those of the type.",
    "errore_segno_usato": "Another status of the same type already has this icon.",
    "errore_colore": "I don't know this color.",
    "errore_predefinito": "New tasks start from an open status.",
    "errore_area": "This area doesn't exist.",
    "errore_area_era_di": "It's an old name of {nome}. Pick it from the menu, or write a different name.",
    "errore_area_nome_usato": "There's already an area with this name.",
    "errore_area_con_task": "There are {n} tasks in this area. Pick where to move them.",
    "errore_area_con_task_una": "There's one task in this area. Pick where to move it.",
    "errore_area_unisci_se_stessa": "An area can't be merged into itself.",
    "errore_area_giro": "This would merge the areas in a circle.",
    "errore_impostazione": "I don't know this setting.",
    "errore_impostazione_valore": "This value for the setting isn't valid.",
    "errore_ordine_livelli": "You can sort by at most three columns, each once.",
    "errore_durata": "I didn't understand how long. Write for example 45m, 1h30 or 90m.",
    "errore_durata_intervallo": "Write a single value, for example 1h30.",
    "errore_durata_negativa": "The time can't be negative.",
    "errore_durata_secondi": "Here you write in minutes and hours, not seconds.",
    "errore_durata_troppo": "The estimated time goes up to a thousand hours at most.",
    "errore_vista_nome_usato": "There's already a view with this name.",
    "errore_viste_illeggibili": "Your views file can't be opened right now, I didn't change anything.",
    "avviso_viste_illeggibili": "Your saved views can't be read right now. You see the built-in ones, yours aren't lost.",
    "errore_testo_file": "The text to save can't be read.",
    "errore_scrittura": "Your tasks file can't be written right now. I didn't change anything.",

    "errore_scrittura_viste": "Your views file can't be written right now. I didn't change anything.",
    "errore_scrittura_impostazioni": "The statuses and areas file can't be written right now. I didn't change anything.",
    "errore_disco_pieno": "The Mac's disk is full. I didn't change anything, free up some space and try again.",
    "esito_gia_fatto": "It was already done.",
    "errore_area_lunga": "An area name goes on one line, eighty characters at most.",
}



TESTI_SETTIMANA = {
    "aiuto_scala": "Look at a day, the week or the month.",
    "aiuto_settimana_prima": "The previous week (←).",
    "aiuto_settimana_dopo": "The next week (→).",
    "aiuto_giorno_prima": "The previous day (←).",
    "aiuto_giorno_dopo": "The next day (→).",
    "aiuto_settimana_oggi": "Back to today (T).",
    "fascia_meno": "Show less",
    "aiuto_fascia_meno": "Close the all-day band.",
    "aiuto_griglia": "Drop a task here to give it a time. Double-click for a new task at that time.",
    "aiuto_blocco_task": "Drag it to move it. Pull the bottom edge to change the estimated time.",
    "aiuto_maniglia": "Pull to change the estimated time.",
    "nuova_alle": "{quando} at {ora}",
    "aiuto_carico": "Tasks planned for {task} over a day of {giornata}.",
}




CONTRATTO = 1

MODI = ("tabella", "foglio", "bacheca", "calendario")

FILTRI_PRONTI = ("urgenti", "veloci", "attese")
CAMPI_GRUPPO = ("nessuno", "priorita", "stato", "area", "scadenza")

CAMPI_ORDINE = (
    "pronto",
    "scadenza",
    "priorita",
    "stima",
    "titolo",
    "area",
    "stato",
    "cambio",
    "creata",
    "inizio",
    "chiusa",
    "rinvii",
    "commenti",
)


VERSO_DI_PARTENZA = {
    "cambio": "giu",
    "creata": "giu",
    "chiusa": "giu",
    "rinvii": "giu",
    "commenti": "giu",
}
LIVELLI_MAX = 3

COLONNE = (
    ("cerchio", True, True, None),
    ("task", True, True, "titolo"),
    ("priorita", True, True, "priorita"),
    ("scadenza", True, True, "scadenza"),
    ("inizio", False, True, "inizio"),
    ("stima", True, True, "stima"),
    ("area", True, True, "area"),
    ("stato", False, True, "stato"),
    ("cambio", False, False, "cambio"),
    ("creata", False, False, "creata"),
    ("chiusa", False, False, "chiusa"),
    ("rinvii", False, False, "rinvii"),
    ("commenti", False, False, "commenti"),
)
FATTE_VISTA = ("no", "7_giorni", "tutte")
FILTRO_SCADENZA = ("scadute", "oggi", "settimana", "con_data", "senza")
FILTRO_STIMA = ("fino_30", "fino_120", "senza")

ID_RISERVATI = ("fatte", "eliminate")
SCALE = ("giorno", "settimana", "mese")
FILTRO_VUOTO = {
    "priorita": [],
    "stato": [],
    "area": [],
    "scadenza": None,
    "stima": None,
    "pronto": None,
}


def _vista(modo: str = "tabella", **altro) -> dict:
    base = {
        "nome": None,
        "modo": modo,
        "regola": None,
        "filtro": copy.deepcopy(FILTRO_VUOTO),
        "gruppo": "nessuno",
        "gruppi_chiusi": [],
        "ordine": None,
        "colonne_tabella": None,
        "fatte": "no",
        "nascosta": False,
        "eliminata": False,

        "scala": "mese",

        "calendari_nascosti": None,
        "rifiutati": False,
    }
    for k, v in altro.items():
        if k == "filtro":
            base["filtro"].update(v)
        else:
            base[k] = v
    return base






PRONTE = {
    "tutte": _vista(gruppo="priorita", gruppi_chiusi=["3"]),
    "foglio": _vista("foglio"),
    "bacheca": _vista("bacheca", gruppo="priorita"),
    "calendario": _vista("calendario"),
    "urgenti": _vista(regola="urgenti", gruppo="scadenza", nascosta=True),
    "veloci": _vista(filtro={"stima": "fino_30"}, nascosta=True),
    "attese": _vista(filtro={"area": [C.AREA_ATTESE]}, nascosta=True),
}

PRONTE_IN_TESTA = ("tutte", "foglio", "bacheca", "calendario")
VERSIONE_VISTE = 2


class Errore(Exception):
    def __init__(self, chiave: str, **altro):
        super().__init__(chiave)
        self.chiave = chiave
        self.altro = altro





def _file() -> Path:
    return CARTELLA / "eventi.jsonl"





_CODA: list[dict] | None = None

_UNA_VOLTA: list[str] = []



_FUORI: list[dict] = []



_TENUTO: dict = {"thread": None, "volte": 0}


class _Lucchetto:
    def __enter__(self):
        global _CODA
        if _TENUTO["thread"] == threading.get_ident():

            _TENUTO["volte"] += 1
            self.dentro = (_CODA, len(_CODA) if _CODA is not None else 0)
            return self
        self.dentro = None
        CARTELLA.mkdir(parents=True, exist_ok=True)
        self.fh = open(CARTELLA / ".lucchetto", "a+")  # noqa: SIM115 si chiude in __exit__
        fcntl.flock(self.fh, fcntl.LOCK_EX)
        _CODA = []
        _TENUTO.update(thread=threading.get_ident(), volte=1)
        return self

    def __exit__(self, tipo, *_):
        global _CODA
        if self.dentro is not None:
            _TENUTO["volte"] -= 1
            coda, da = self.dentro
            if tipo is not None and _CODA is not None:


                del _CODA[da if _CODA is coda else 0 :]
            return
        try:
            if tipo is None:
                _svuota_coda()
        finally:
            _CODA = None
            _TENUTO.update(thread=None, volte=0)
            fcntl.flock(self.fh, fcntl.LOCK_UN)
            self.fh.close()


def _ora() -> str:
    return C._adesso().isoformat(timespec="seconds")


def _chi(da: str | None) -> str:
    ""


    return da or (_FUORI[0]["da"] if _FUORI else None) or os.environ.get("SB_ATTIVITA_DA") or "app"


def _ora_fuori() -> str | None:
    ""

    ms = _FUORI[0].get("ms") if _FUORI else None
    return C._da_ms(ms).isoformat(timespec="seconds") if type(ms) is int else None


def _nuovo_id(n: int = 12) -> str:
    return uuid.uuid4().hex[:n]


def _fino_al_disco(fh) -> None:
    ""

    fh.flush()
    try:
        fcntl.fcntl(fh.fileno(), fcntl.F_FULLFSYNC)
    except (AttributeError, OSError):
        os.fsync(fh.fileno())


def _scrivi(evento: dict) -> str:
    ""

    evento.setdefault("eid", _nuovo_id())
    if "ms" not in evento and evento.get("t") == _ora():

        evento["ms"] = _adesso_ms()
    if _UNA_VOLTA:
        evento["una_volta"] = _UNA_VOLTA[0]
    if _FUORI and "fuori" not in evento:

        evento["fuori"] = dict(_FUORI[0])
    if _CODA is not None:
        _CODA.append(evento)
    else:
        _scrivi_righe(_file(), [evento])
    return evento["eid"]


def _svuota_coda() -> None:
    ""
    global _CODA
    if _CODA:
        righe, _CODA = _CODA, []
        _scrivi_righe(_file(), _in_lotto(righe))


def _in_lotto(righe: list[dict]) -> list[dict]:
    ""



    if len(righe) < 2:
        return righe
    lid = _nuovo_id()
    return [{**r, "lotto": [lid, len(righe)]} for r in righe]


def _senza_lotti_a_meta(eventi: list[dict]) -> list[dict]:
    ""
    conti: dict = {}
    for e in eventi:
        lo = e.get("lotto")
        if lo is not None and lo.__class__ is list and len(lo) == 2:
            if lo[0].__class__ is str and lo[1].__class__ is int:
                conti.setdefault(lo[0], [lo[1], 0])[1] += 1
    a_meta = {k for k, (n, visti) in conti.items() if visti < n}
    if not a_meta:
        return eventi
    return [e for e in eventi if not (e.get("lotto").__class__ is list and len(e["lotto"]) == 2
                                      and e["lotto"][0].__class__ is str and e["lotto"][0] in a_meta)]


def _scrivi_righe(percorso: Path, righe: list[dict]) -> None:
    ""



    testo = "".join(json.dumps(r, ensure_ascii=False, allow_nan=False) + "\n" for r in righe)


    with open(percorso, "a+b", buffering=0) as f:
        lunghezza = os.lseek(f.fileno(), 0, os.SEEK_END)
        a_capo = b""
        if lunghezza > 0:
            f.seek(-1, os.SEEK_END)
            if f.read(1) != b"\n":
                a_capo = b"\n"
        dati = memoryview(a_capo + testo.encode("utf-8", "replace"))
        try:
            while dati:
                scritti = f.write(dati)
                if not scritti:
                    raise OSError(errno.ENOSPC, os.strerror(errno.ENOSPC))
                dati = dati[scritti:]
            _fino_al_disco(f)
        except OSError:


            with contextlib.suppress(OSError):
                os.ftruncate(f.fileno(), lunghezza)
                _fino_al_disco(f)
            raise


def _eventi() -> list[dict]:
    ""
    try:
        righe = _file().read_bytes().decode("utf-8", "replace").split("\n")
    except FileNotFoundError:
        return []
    except OSError as e:


        raise Errore("errore_lettura") from e
    out = []
    for riga in righe:
        try:
            e = json.loads(riga)
        except (ValueError, RecursionError):

            continue
        if isinstance(e, dict):
            out.append(e)
    return _senza_lotti_a_meta(out)


_GIORNO = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_GIORNO_ORA = re.compile(r"^\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2})?$")
_DATE_BUONE: dict[str, bool] = {}


def _data_buona(v, con_ora: bool = False) -> bool:
    ""

    if v.__class__ is not str:
        return False
    tenute = _DATE_BUONE_ORA if con_ora else _DATE_BUONE
    r = tenute.get(v)
    if r is None:
        r = False
        if (_GIORNO_ORA if con_ora else _GIORNO).match(v):
            try:
                datetime.strptime(v, "%Y-%m-%dT%H:%M" if "T" in v else "%Y-%m-%d")
                r = True
            except ValueError:
                r = False
        tenute[v] = r
    return r


_MANCA = object()
_MOMENTI: dict[str, str | None] = {}
_DATE_BUONE_ORA: dict[str, bool] = {}
_CANONICO = re.compile(r"\d{4}-\d\d-\d\dT(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d$")


def _momento(v) -> str | None:
    ""


    if v.__class__ is not str or not 10 <= len(v) <= 40:
        return None

    r = _MOMENTI.get(v, _MANCA)
    if r is not _MANCA:
        return r
    if len(v) == 19 and _CANONICO.match(v) and _data_buona(v[:10]):

        _MOMENTI[v] = v
        return v
    try:
        d = datetime.fromisoformat(v)
        if d.tzinfo is not None:
            d = d.astimezone(C.FUSO).replace(tzinfo=None)
        out = (
            d.replace(microsecond=0).isoformat(timespec="seconds")
            if 1900 <= d.year <= 9998
            else None
        )
    except (ValueError, OverflowError, OSError):
        out = None
    _MOMENTI[v] = out
    return out


_PIANIFICATE: dict[str, tuple[str, str | None] | None] = {}


def _pianificata_locale(v) -> tuple[str, str | None] | None:
    ""


    if not isinstance(v, str):
        return None
    if v in _PIANIFICATE:
        return _PIANIFICATE[v]
    out = None
    if len(v) == 10:
        if _data_buona(v):
            out = (v, None)
    else:
        m = _momento(v)
        if m is not None and "T" in v:
            out = (m[:10], m[11:16])
    _PIANIFICATE[v] = out
    return out


_INVISIBILI = re.compile("[​‌‍⁠﻿­]")


def _vuoto(testo) -> bool:
    ""
    return not _INVISIBILI.sub("", str(testo or "")).strip()


def _pulito(testo: str) -> str:
    ""

    if testo.isascii():
        return testo
    try:
        testo.encode("utf-8")
        return testo
    except UnicodeEncodeError:
        return testo.encode("utf-8", "replace").decode("utf-8")


def _sani(campi: dict) -> dict:
    ""



    out = {}
    for k, v in campi.items():
        if k == "titolo" or k == "descrizione":


            if v.__class__ is str:
                out[k] = v
            elif v is None and k == "descrizione":
                out[k] = ""
            continue


        chiave = (k, v.__class__, v)
        try:
            r = _SANI_TENUTI[chiave]
        except KeyError:
            r = _sano_uno(k, v)
            if len(_SANI_TENUTI) < 100_000:
                _SANI_TENUTI[chiave] = r
        except TypeError:
            r = _sano_uno(k, v)
        if r is not _SCARTO:
            out[k] = r
    return out


_SANI_TENUTI: dict = {}
_SCARTO = object()


def _sano_uno(k: str, v):
    ""
    if k == "stato":
        return _pulito(v) if isinstance(v, str) and v and len(v) <= 200 else _SCARTO
    if k == "priorita":
        return v if type(v) is int and 0 <= v <= 3 else _SCARTO
    if k == "scadenza":
        return v if v is None or _data_buona(v) else _SCARTO
    if k == "pianificata":
        return v if v is None or _pianificata_locale(v) is not None else _SCARTO
    if k == "stima":
        return v if v is None or (type(v) is int and 0 < v <= STIMA_MAX) else _SCARTO
    if k == "area":
        if v is None or isinstance(v, str):
            return _pulito(v) if v else None
        return _SCARTO
    if k == "chiusa":
        if v is None:
            return None
        m = _momento(v)
        return m if m is not None else _SCARTO
    if k == "origine":
        return v if v is None or isinstance(v, dict) else _SCARTO
    return _SCARTO



_VUOTA = {
    "titolo": "",
    "descrizione": "",
    "stato": "da_fare",
    "priorita": 2,
    "scadenza": None,
    "stima": None,
    "area": None,
    "pianificata": None,
    "origine": None,
}


def _cambio_annullato(t: dict, e: dict, nuovi: dict) -> dict | None:
    ""


    storia = t.get("cambi_contati") or ()
    if e.get("annulla"):
        return next((x for x in reversed(storia) if x["eid"] == e["annulla"]), None)
    da = str(e.get("da") or "")
    rid = da[len("annulla:") :] if da.startswith("annulla:") else None
    campi = {"stato", "scadenza"} & set(nuovi)
    return next(
        (
            x
            for x in reversed(storia)
            if rid and x["da"] == rid and not x.get("annullato") and x["campi"] & campi
        ),
        None,
    )


def _annullo(e: dict) -> bool:
    ""
    return bool(e.get("annulla")) or str(e.get("da") or "").startswith("annulla:")


def _adesso_ms() -> int:
    ""
    fissa = os.environ.get("SB_COSE_ADESSO")
    if not fissa:
        return int(time.time() * 1000)
    if fissa not in _ADESSO_FISSO:
        d = datetime.fromisoformat(fissa)
        _ADESSO_FISSO[fissa] = int(d.timestamp() * 1000) if d.tzinfo else C._in_ms(d)
    return _ADESSO_FISSO[fissa]


_ADESSO_FISSO: dict[str, int] = {}


_MS_ORA: dict[str, int] = {}


def _ms_locale(quando: str) -> int:
    ""

    ora = quando[:13]
    if ora not in _MS_ORA:
        _MS_ORA[ora] = C._in_ms(datetime.fromisoformat(ora + ":00"))
    return _MS_ORA[ora] + int(quando[14:16] or 0) * 60_000 + int(quando[17:19] or 0) * 1000



_ORA_DI = {
    "creata": "creata",
    "cambiata": "cambiata",
    "stato_da": "stato_da",
    "eliminata": "eliminata_t",
    "chiusa": "chiusa",
}


def _ms_di_campo(t: dict, chiave: str) -> int | None:
    ""


    k = chiave + "_ms"
    v = t.get(k)
    if v.__class__ is tuple:
        return v[0]
    quando = t.get(_ORA_DI[chiave])
    if not quando:
        return None
    ms = v if ms_torna(v, quando) else _ms_locale(quando)
    t[k] = (ms,)
    return ms


def _ms_evento(e: dict, quando: str) -> int:
    ""


    ms = e.get("ms")
    if ms_torna(ms, quando):
        return ms
    return _ms_locale(quando)


def ms_torna(ms, quando: str) -> bool:
    ""

    if type(ms) is not int or not 0 < ms < 10**14:
        return False
    try:
        scarto = ms - _ms_locale(quando)
    except (ValueError, OverflowError, OSError):
        return False
    if abs(scarto) <= 5000:
        return True


    if abs(scarto - 3_600_000) <= 5000:
        with contextlib.suppress(ValueError, OverflowError, OSError):
            return abs((C._da_ms(ms) - datetime.fromisoformat(quando)).total_seconds()) <= 5
    return False


def _applica(task: dict[str, dict], e: dict) -> None:
    ""


    tid, tipo = e.get("id"), e.get("tipo")
    quando = _momento(e.get("t"))
    if not isinstance(tid, str) or not tid or quando is None:
        return
    tid = _pulito(tid)
    if tipo == "crea":
        campi = e.get("campi")
        if tid in task or not isinstance(campi, dict):

            return
        sani = _sani(campi)
        t = {
            "id": tid,
            "creata": quando,
            "cambiata": quando,
            "eliminata": False,
            "eliminata_t": None,
            **_VUOTA,
            **sani,
        }




        t.update(cambiata_da=e.get("da"), stato_da=quando, rinvii=0, scadenza_prima=t["scadenza"],
                 riga_interna=_riga_interna_di(t))


        ms = e.get("ms")
        t.update(creata_ms=ms, cambiata_ms=ms, stato_da_ms=ms, eliminata_ms=None)

        t["nata_con"] = sani
        t["chiusa_ms"] = ms if t.get("chiusa") == quando else None
        task[tid] = t
        return
    t = task.get(tid)
    if t is None:
        return
    if tipo == "cambia":
        campi = e.get("campi")
        if not isinstance(campi, dict):
            return
        nuovi = _sani(campi)




        foto = bersaglio = None
        if "stato" in nuovi or "scadenza" in nuovi:
            foto = {
                k: t.get(k)
                for k in ("stato_da", "stato_da_ms", "scadenza_ultima", "scadenza_prima")
            }
            if _annullo(e):
                bersaglio = _cambio_annullato(t, e, nuovi)
        if "scadenza" in nuovi:


            if t.get("scadenza"):
                t["scadenza_ultima"] = t["scadenza"]
            vecchia, nuova = t.get("scadenza") or t.get("scadenza_ultima"), nuovi["scadenza"]
            if not t.get("scadenza_prima"):
                t["scadenza_prima"] = nuova
            if vecchia and nuova and nuova > vecchia and not _annullo(e):
                t["rinvii"] = t.get("rinvii", 0) + 1
                t.setdefault("rinvii_eid", []).append(e.get("eid"))
            elif (
                vecchia
                and nuova
                and nuova > vecchia
                and e.get("annulla") in t.get("rinvii_tolti", ())
            ):

                t["rinvii"] = t.get("rinvii", 0) + 1
                t.setdefault("rinvii_eid", []).append(e.get("eid"))
            elif vecchia and nuova and nuova < vecchia and _annullo(e) and t.get("rinvii"):
                tolto = e.get("annulla")
                if tolto is None or tolto in t.get("rinvii_eid", ()):
                    t["rinvii"] -= 1
                    t.setdefault("rinvii_tolti", []).append(e.get("eid"))
        ms = e.get("ms")
        if "stato" in nuovi and nuovi["stato"] != t.get("stato"):
            t["stato_da"], t["stato_da_ms"] = quando, ms
        if "chiusa" in nuovi:
            t["chiusa_ms"] = ms if nuovi["chiusa"] == quando else None
        t.update(nuovi)
        t["cambiata"], t["cambiata_ms"] = quando, ms
        t["cambiata_da"] = e.get("da")
        if foto is not None:
            if bersaglio is not None:
                prima = bersaglio["foto"]
                if "stato" in nuovi:
                    t["stato_da"], t["stato_da_ms"] = prima["stato_da"], prima["stato_da_ms"]
                if "scadenza" in nuovi:
                    t["scadenza_ultima"], t["scadenza_prima"] = (
                        prima["scadenza_ultima"],
                        prima["scadenza_prima"],
                    )
                bersaglio["annullato"] = True
            t.setdefault("cambi_contati", []).append(
                {
                    "eid": e.get("eid"),
                    "da": e.get("da"),
                    "campi": {"stato", "scadenza"} & set(nuovi),
                    "foto": foto,
                }
            )
    elif tipo in ("elimina", "ripristina"):
        ms = e.get("ms")
        t["eliminata"] = tipo == "elimina"
        t["eliminata_t"] = quando if tipo == "elimina" else None
        t["eliminata_ms"] = ms if tipo == "elimina" else None
        t["cambiata"], t["cambiata_ms"] = quando, ms
        t["cambiata_da"] = e.get("da")
    elif tipo == "commento":
        testo = e.get("testo")
        if isinstance(testo, str) and not _vuoto(testo) and isinstance(e.get("eid"), str):


            t.setdefault("commenti", {})[e["eid"]] = (
                quando,
                _pulito(testo[:200]),
                _ms_evento(e, quando),
            )
    elif tipo in ("commento_tolto", "commento_rimesso"):
        c = e.get("commento")
        da, a = (
            ("commenti", "commenti_tolti")
            if tipo == "commento_tolto"
            else ("commenti_tolti", "commenti")
        )
        if c in t.get(da, {}):
            t.setdefault(a, {})[c] = t[da].pop(c)


def _carica_di(ids, eventi: list[dict] | None = None) -> dict[str, dict]:
    ""

    voluti = set(ids)
    ev = _eventi() if eventi is None else eventi
    return _carica(
        [e for e in ev if (x := e.get("id")).__class__ is str and (x in voluti or not x.isascii())]
    )


def _carica(eventi: list[dict] | None = None) -> dict[str, dict]:
    ""


    task: dict[str, dict] = {}
    for e in _eventi() if eventi is None else eventi:
        try:
            _applica(task, e)
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
    return task


def _valori_area(eventi: list[dict]) -> list[str]:
    ""

    visti: dict[str, None] = {}
    for e in eventi:
        c = e.get("campi")
        if isinstance(c, dict):
            a = c.get("area")
            if a and isinstance(a, str) and a not in visti and not _vuoto(a):
                visti[a] = None
    return list(visti)





def _file_impostazioni() -> Path:
    return CARTELLA / "impostazioni.jsonl"


_IMP_CACHE: dict = {}


def _righe_impostazioni() -> list[dict]:
    try:
        righe = _file_impostazioni().read_bytes().decode("utf-8", "replace").split("\n")
    except OSError:
        return []
    out = []
    for r in righe:
        try:
            d = json.loads(r)
        except (ValueError, RecursionError):
            continue
        if isinstance(d, dict):
            out.append(d)
    return _senza_lotti_a_meta(out)


def _stati_partenza() -> dict[str, dict]:
    out = {}
    for n, (sid, tipo, segno, colore) in enumerate(STATI_PARTENZA):
        out[sid] = {
            "id": sid,
            "nome": TESTI[NOME_PARTENZA[sid]],
            "tipo": tipo,
            "segno": segno,
            "colore": colore,
            "ordine": n,
            "tolto": False,
            "in": None,
            "nomi_prima": [],
        }
    return out


def _imp_da_righe(righe: list[dict]) -> dict:
    ""

    imp = {
        "stati": _stati_partenza(),
        "aree": {},
        "predefinito": None,
        "aree_ordinate": False,
        **copy.deepcopy(IMPOSTAZIONI_PARTENZA),
    }
    for r in righe:
        try:
            voce, dopo = r.get("voce"), r.get("dopo")
            if voce == "stato" and isinstance(r.get("id"), str) and isinstance(dopo, dict):
                s = imp["stati"].setdefault(
                    r["id"],
                    {"id": r["id"], "nome": r["id"], "tipo": "da_fare", "segno": "circle", "colore": "grigio",
                     "ordine": len(imp["stati"]), "tolto": False, "in": None, "nomi_prima": []},
                )


                s.update(
                    {k: v for k, v in dopo.items() if k in _CAMPI_STATO and _CAMPI_STATO[k](v)}
                )
                if s.get("tipo") not in TIPI:
                    s["tipo"] = "da_fare"
            elif voce == "area" and isinstance(r.get("id"), str) and isinstance(dopo, dict):
                a = imp["aree"].setdefault(r["id"], {"id": r["id"]})
                a.update({k: v for k, v in dopo.items() if k in _CAMPI_AREA and _CAMPI_AREA[k](v)})
            elif voce == "stati_ordine" and isinstance(dopo, list):
                dopo = [x for x in dopo if isinstance(x, str)]
                for n, sid in enumerate(x for x in dopo if x in imp["stati"]):
                    imp["stati"][sid]["ordine"] = n


                fila = _fila_stati(
                    [x for x in dopo if x in imp["stati"]],
                    [x["id"] for x in sorted(imp["stati"].values(), key=lambda x: x["ordine"])],
                    imp["stati"],
                )
                for n, sid in enumerate(fila):
                    imp["stati"][sid]["ordine"] = n
            elif voce == "aree_ordine" and dopo is None:

                for a in imp["aree"].values():
                    a.pop("ordine", None)
                imp["aree_ordinate"] = False
            elif voce == "aree_ordine" and isinstance(dopo, list):
                for n, aid in enumerate(x for x in dopo if isinstance(x, str)):
                    imp["aree"].setdefault(aid, {"id": aid})["ordine"] = n
                imp["aree_ordinate"] = True
            elif voce == "predefinito":
                imp["predefinito"] = dopo if isinstance(dopo, str) else None
            elif voce == "imposta" and r.get("chiave") in IMPOSTAZIONI_PARTENZA:
                imp[r["chiave"]] = _valida_imposta(r["chiave"], dopo, imp[r["chiave"]])
        except Exception:  # noqa: BLE001 nessuna riga strana spegne niente, anche qui
            continue
    _stati_che_servono(imp)
    return imp


def _fila_stati(voluti: list[str], tutti: list[str], stati: dict) -> list[str]:
    ""

    fila = list(voluti)
    for sid in tutti:
        if sid in fila or sid not in stati:
            continue
        tipo = stati[sid]["tipo"]
        stesso = [i for i, x in enumerate(fila) if stati[x]["tipo"] == tipo]
        if stesso:
            fila.insert(stesso[-1] + 1, sid)
        elif not _chiuso_tipo(tipo):
            aperti = [i for i, x in enumerate(fila) if not _chiuso_tipo(stati[x]["tipo"])]
            if aperti:
                fila.insert(aperti[-1] + 1, sid)
            else:
                fila.append(sid)
        else:
            fila.append(sid)
    return fila


def _testo_pieno(v) -> bool:
    return isinstance(v, str) and not _vuoto(v)


def _intero(v) -> bool:
    return type(v) is int



_CAMPI_STATO = {
    "nome": _testo_pieno,
    "tipo": lambda v: v in TIPI,
    "segno": _testo_pieno,
    "colore": _testo_pieno,
    "ordine": _intero,
    "tolto": lambda v: type(v) is bool,
    "in": lambda v: v is None or isinstance(v, str),
    "nomi_prima": lambda v: isinstance(v, list) and all(isinstance(x, str) for x in v),
}
_CAMPI_AREA = {
    "nome": _testo_pieno,
    "nomi": lambda v: isinstance(v, list) and all(isinstance(x, str) for x in v),
    "ordine": lambda v: v is None or _intero(v),
    "colore": lambda v: v is None or isinstance(v, str),
    "unita_in": lambda v: v is None or isinstance(v, str),
    "tolta": lambda v: type(v) is bool,
    "senza": lambda v: type(v) is bool,
    "prima_togli": lambda v: v is None or isinstance(v, dict),
}


def _stati_che_servono(imp: dict) -> None:
    ""

    for tipo in ("da_fare", "fatta"):
        if any(s["tipo"] == tipo and not s.get("tolto") for s in imp["stati"].values()):
            continue
        s = imp["stati"].get(tipo)
        if s is None or s.get("tipo") != tipo:
            s = imp["stati"][tipo] = _stati_partenza()[tipo]
        s["tolto"] = False


def _imp() -> dict:
    ""
    f = _file_impostazioni()
    try:
        st = f.stat()
        firma = (str(f), st.st_mtime_ns, st.st_size)
    except OSError:
        firma = (str(f), None, None)
    if _IMP_CACHE.get("firma") != firma:


        _IMP_CACHE["imp"] = _imp_da_righe([])
        _IMP_CACHE["firma"] = firma
        _IMP_CACHE["imp"] = _imp_da_righe(_righe_impostazioni() if firma[1] is not None else [])
    return _IMP_CACHE["imp"]


def _scrivi_impostazione(riga: dict) -> str:
    ""

    return _scrivi_impostazioni([riga])[0]


def _scrivi_impostazioni(righe: list[dict]) -> list[str]:
    ""
    righe = [{"eid": _nuovo_id(), "t": _ora(), "da": _chi(r.pop("da", None)), **r} for r in righe]
    CARTELLA.mkdir(parents=True, exist_ok=True)

    _svuota_coda()
    try:
        _scrivi_righe(_file_impostazioni(), _in_lotto(righe))
    except OSError as e:
        raise _di_file(e, "impostazioni") from None
    _IMP_CACHE.clear()
    return [r["eid"] for r in righe]


def _stati_in_ordine(imp: dict, anche_tolti: bool = False) -> list[dict]:
    return [
        s
        for s in sorted(imp["stati"].values(), key=lambda s: s["ordine"])
        if anche_tolti or not s.get("tolto")
    ]


def _chiuso_tipo(tipo: str) -> bool:
    return tipo in TIPI_CHIUSI


def _stato_di(imp: dict, sid) -> dict:
    ""

    s = imp["stati"].get(sid)
    if s is not None:
        return s
    return {"id": sid, "nome": str(sid), "tipo": "da_fare", "segno": SEGNO_DUBBIO, "colore": "grigio",
            "ordine": len(imp["stati"]), "tolto": False, "in": None, "nomi_prima": [], "sconosciuto": True}


def _chiuso(imp: dict, sid) -> bool:

    tenuti = _CHIUSI_TENUTI.get(id(imp))
    if tenuti is None or tenuti[0] is not imp:
        tenuti = _CHIUSI_TENUTI[id(imp)] = (imp, {})
        if len(_CHIUSI_TENUTI) > 64:
            _CHIUSI_TENUTI.clear()
            _CHIUSI_TENUTI[id(imp)] = tenuti
    try:
        return tenuti[1][sid]
    except KeyError:
        r = tenuti[1][sid] = _chiuso_tipo(_stato_di(imp, sid)["tipo"])
        return r
    except TypeError:
        return _chiuso_tipo(_stato_di(imp, sid)["tipo"])


_CHIUSI_TENUTI: dict = {}


def _primo_di_tipo(imp: dict, tipo: str) -> dict | None:
    return next((s for s in _stati_in_ordine(imp) if s["tipo"] == tipo), None)


def _predefinito(imp: dict) -> str:
    ""
    p = imp["stati"].get(imp.get("predefinito") or "")
    if p and not p.get("tolto") and not _chiuso_tipo(p["tipo"]):
        return p["id"]
    primo = _primo_di_tipo(imp, "da_fare")
    return primo["id"] if primo else "da_fare"


def _stato_fatta(imp: dict) -> str:
    primo = _primo_di_tipo(imp, "fatta")
    return primo["id"] if primo else "fatta"


def _risolvi_stato(imp: dict, testo: str) -> str | None:
    ""

    testo = (testo or "").strip()
    if not testo:
        return None
    if testo[:5].casefold() == "tipo:" and testo[5:].strip().casefold() in TIPI:


        tipo = testo[5:].strip().casefold()
        pre = imp["stati"].get(_predefinito(imp))
        if pre and pre["tipo"] == tipo:
            return pre["id"]
        primo = _primo_di_tipo(imp, tipo)
        return primo["id"] if primo else None
    s = imp["stati"].get(testo)
    if s is None:

        chiave = _chiave_area(testo)
        s = next((x for x in _stati_in_ordine(imp, True) if x["id"].casefold() == chiave), None)
    if s is None:
        s = next(
            (x for x in _stati_in_ordine(imp) if _chiave_area(x["nome"]) == chiave), None
        ) or next(
            (
                x
                for x in _stati_in_ordine(imp, True)
                if chiave in {_chiave_area(n) for n in [x["nome"], *x["nomi_prima"]]}
            ),
            None,
        )
    visti = set()
    while s is not None and s.get("tolto") and s.get("in") and s["id"] not in visti:
        visti.add(s["id"])
        s = imp["stati"].get(s["in"])
    if s is None or s.get("tolto"):
        return None
    return s["id"]





_APOSTROFI = str.maketrans({"’": "'", "‘": "'", "`": "'", "´": "'", "ʼ": "'"})


def _piega(testo: str) -> str:
    ""


    testo = testo or ""
    if testo.isascii():
        return testo.casefold().replace("`", "'").strip()
    return _piega_lenta(testo)


@functools.lru_cache(maxsize=16384)
def _piega_lenta(testo: str) -> str:
    t = unicodedata.normalize("NFKD", testo.translate(_APOSTROFI).casefold())
    if not t.isascii():
        t = "".join(c for c in t if not unicodedata.combining(c))
    for a, b in (("œ", "oe"), ("æ", "ae"), ("ø", "o"), ("ł", "l"), ("đ", "d")):
        t = t.replace(a, b)
    return t.strip()


@functools.lru_cache(maxsize=4096)
def _chiave_area(nome: str) -> str:
    ""


    if not nome.isascii():
        nome = _INVISIBILI.sub("", nome)
    return " ".join(unicodedata.normalize("NFC", nome).casefold().split())



_ID_AREA = re.compile(r"^(?:n:.+|a-[0-9a-f]{6})$")


class Aree:
    ""



    def __init__(self, imp: dict, valori: list[str]):
        self.defs: dict[str, dict] = {}
        for v in valori:
            aid = v if v in imp["aree"] or _ID_AREA.match(v) else "n:" + _chiave_area(v)
            d = self.defs.setdefault(
                aid, {"id": aid, "nome": _nome_una_riga(v) if aid != v else v[2:], "nomi": [], "ordine": None,
                      "colore": None, "unita_in": None, "tolta": False, "senza": False}
            )
            if aid != v and v not in d["nomi"]:
                d["nomi"].append(v)
        for aid, a in imp["aree"].items():
            d = self.defs.setdefault(
                aid, {"id": aid, "nome": aid[2:] if aid.startswith("n:") else aid, "nomi": [], "ordine": None,
                      "colore": None, "unita_in": None, "tolta": False, "senza": False}
            )
            for k in ("nome", "ordine", "colore", "unita_in", "tolta", "senza", "prima_togli"):
                if k in a:
                    d[k] = a[k]
            for n in a.get("nomi") or []:
                if n not in d["nomi"]:
                    d["nomi"].append(n)
        self.nomi: dict[str, str] = {}
        for aid, d in self.defs.items():
            if d["nome"] not in d["nomi"]:
                d["nomi"].append(d["nome"])
            for n in d["nomi"]:
                self.nomi.setdefault(_chiave_area(n), aid)
        self.ordinate = imp.get("aree_ordinate", False)
        self._finali: dict = {}

        self.da_imp = {aid for aid, a in imp["aree"].items() if set(a) - {"id", "ordine"}}
        self.con_task: set | None = None

    def finale(self, valore) -> str:
        ""
        if valore.__class__ is str and valore in self._finali:
            return self._finali[valore]
        if not valore or valore == SENZA_AREA or not isinstance(valore, str) or _vuoto(valore):
            return SENZA_AREA
        aid = valore if valore in self.defs else self.nomi.get(_chiave_area(str(valore)))
        if aid is None:
            aid = "n:" + _chiave_area(str(valore))
        visti = set()
        while aid in self.defs and aid not in visti:
            visti.add(aid)
            d = self.defs[aid]
            if d.get("unita_in") and d["unita_in"] in self.defs:
                aid = d["unita_in"]
                continue
            if d.get("tolta") and d.get("senza"):
                aid = SENZA_AREA
            break
        self._finali[valore] = aid
        return aid

    def nome(self, aid: str) -> str:
        if aid == SENZA_AREA:
            return TESTI["senza_area"]
        d = self.defs.get(aid)
        return d["nome"] if d else str(aid)

    def visibili(self, conta: dict[str, int] | None = None) -> list[dict]:
        ""




        conta = conta or {}
        con_task = self.con_task
        vive = [
            d
            for d in self.defs.values()
            if not d.get("unita_in")
            and (
                (
                    not d.get("tolta")
                    and (con_task is None or d["id"] in self.da_imp or d["id"] in con_task)
                )
                or (d.get("tolta") and conta.get(d["id"], 0) > 0)
            )
        ]
        if self.ordinate:
            return sorted(
                vive, key=lambda d: (d["ordine"] is None, d["ordine"] or 0, _piega(d["nome"]))
            )
        return sorted(vive, key=lambda d: (-conta.get(d["id"], 0), d["nome"].casefold()))

    def cerca(self, testo: str) -> str | None:
        ""
        testo = (testo or "").strip()
        if not testo:
            return None
        if testo in self.defs:
            return testo
        return self.nomi.get(_chiave_area(testo))


def _aree(eventi: list[dict] | None = None, imp: dict | None = None) -> Aree:
    return Aree(imp or _imp(), _valori_area(_eventi() if eventi is None else eventi))


def crea(campi: dict, da: str | None = None, quando: str | None = None) -> str:
    return _crea(campi, da, quando)[0]


def _crea(campi: dict, da: str | None = None, quando: str | None = None) -> tuple[str, str]:
    with _Lucchetto():
        return _crea_dentro(campi, da, quando)


def _crea_dentro(campi: dict, da: str | None = None, quando: str | None = None) -> tuple[str, str]:
    ""

    titolo = (campi.get("titolo") or "").strip()
    if _vuoto(titolo):
        raise Errore("errore_titolo")
    quando = quando or _ora_fuori()
    imp = _imp()


    pieni = {
        "titolo": titolo,
        "descrizione": campi.get("descrizione") or "",
        "stato": campi.get("stato") or _predefinito(imp),
        "priorita": campi.get("priorita", 2),
        "scadenza": campi.get("scadenza"),
        "stima": campi.get("stima"),
        "area": campi.get("area") or None,
        "origine": campi.get("origine"),
    }
    if campi.get("pianificata"):
        pieni["pianificata"] = campi["pianificata"]
    if _chiuso(imp, pieni["stato"]):
        pieni["chiusa"] = quando or _ora()
    tid = uuid.uuid4().hex[:10]
    eid = _scrivi(
        {"t": quando or _ora(), "id": tid, "tipo": "crea", "da": _chi(da), "campi": pieni}
    )
    return tid, eid


def _cambia_dentro(
    tutte: dict[str, dict], tid: str, campi: dict, da: str | None, gruppo: str | None
) -> tuple[dict, str | None]:
    ""

    t = tutte[tid]

    chiusa_data = campi.get("chiusa") if _momento(campi.get("chiusa")) else None
    nuovi = {k: v for k, v in campi.items() if k in CAMPI and t.get(k) != v}
    if "descrizione" in nuovi and t.get("riga_interna") and nuovi["descrizione"] == _mostrata(t):

        del nuovi["descrizione"]
    if not nuovi:
        return {}, None
    if "stato" in nuovi:

        chiusa = chiusa_data or _ora_fuori() or _ora()
        nuovi["chiusa"] = chiusa if _chiuso(_imp(), nuovi["stato"]) else None
    prima = {k: t.get(k) for k in nuovi}
    evento = {
        "t": _ora(),
        "id": tid,
        "tipo": "cambia",
        "da": _chi(da),
        "campi": nuovi,
        "prima": prima,
    }
    if gruppo:
        evento["gruppo"] = gruppo
    eid = _scrivi(evento)
    _applica(tutte, evento)
    return {k: v for k, v in prima.items() if k in CAMPI}, eid


def _controlla(tutte: dict[str, dict], ids: list[str]) -> None:
    for tid in ids:
        t = tutte.get(tid)
        if t is None or t["eliminata"]:
            raise Errore("errore_sparita")


def cambia(tid: str, campi: dict, da: str | None = None) -> dict:
    ""
    with _Lucchetto():
        tutte = _carica_di([tid])
        _controlla(tutte, [tid])
        prima_t = dict(tutte[tid])
        prima, eid = _cambia_dentro(tutte, tid, campi, da, None)
    return {**prima_t, "prima": prima, "eid": eid}


def cambia_tante(
    ids: list[str], campi: dict, da: str | None = None, era: dict | None = None
) -> dict:
    ""

    gruppo = _nuovo_id(8) if len(ids) > 1 else None
    with _Lucchetto():
        tutte = _carica_di(ids)
        _controlla(tutte, ids)
        if era:
            for tid in ids:
                for k, v in era.items():
                    if _mostrato(tutte[tid], k) != v:
                        raise Errore("errore_intanto", intanto=_mostrato(tutte[tid], k))
        prima, eventi = {}, []
        for tid in ids:
            p, eid = _cambia_dentro(tutte, tid, campi, da, gruppo)
            prima[tid] = p
            if eid:
                eventi.append(eid)
        titoli = {tid: tutte[tid]["titolo"] for tid in ids}
    return {
        "prima": prima,
        "eventi": eventi,
        "gruppo": gruppo if eventi else None,
        "titoli": titoli,
    }


def aggiungi_descrizione(ids: list[str], testo: str, da: str | None = None) -> dict:
    ""


    testo = (testo or "").strip()
    if not testo:
        raise Errore("errore_valore")
    gruppo = _nuovo_id(8) if len(ids) > 1 else None
    with _Lucchetto():
        tutte = _carica_di(ids)
        _controlla(tutte, ids)
        prima, eventi = {}, []
        for tid in ids:
            vecchia = tutte[tid].get("descrizione") or ""
            nuova = f"{vecchia.rstrip()}\n\n{testo}" if vecchia.strip() else testo
            p, eid = _cambia_dentro(tutte, tid, {"descrizione": nuova}, da, gruppo)
            prima[tid] = p
            if eid:
                eventi.append(eid)
        titoli = {tid: tutte[tid]["titolo"] for tid in ids}
    return {"prima": prima, "eventi": eventi, "gruppo": gruppo, "titoli": titoli}


def _segna_dentro(
    tutte: dict[str, dict], tid: str, tipo: str, da: str | None, gruppo: str | None = None
) -> str | None:
    ""
    if tutte[tid]["eliminata"] == (tipo == "elimina"):
        return None
    evento = {"t": _ora(), "id": tid, "tipo": tipo, "da": _chi(da)}
    if gruppo:
        evento["gruppo"] = gruppo
    eid = _scrivi(evento)
    _applica(tutte, evento)
    return eid


def _segna_tante(ids: list[str], tipo: str, da: str | None = None) -> dict:
    ""
    gruppo = _nuovo_id(8) if len(ids) > 1 else None
    with _Lucchetto():
        tutte = _carica_di(ids)
        for tid in ids:
            if tid not in tutte:
                raise Errore("errore_sparita")
        eventi = []
        for tid in ids:
            eid = _segna_dentro(tutte, tid, tipo, da, gruppo)
            if eid:
                eventi.append(eid)
        titoli = {tid: tutte[tid]["titolo"] for tid in ids}
    return {"eventi": eventi, "gruppo": gruppo, "titoli": titoli}


def annulla(eids: list[str], da: str | None = None) -> dict:
    ""



    with _Lucchetto():
        return _annulla_dentro(eids, da)


def _cambiata_dopo(t: dict) -> Errore:
    ""

    da = str(t.get("cambiata_da") or "app")
    if da == "telefono":

        return Errore("errore_cambiata_telefono")
    return Errore(
        "errore_cambiata_dopo"
        if da == "app" or da.startswith("annulla:")
        else "errore_cambiata_altrove"
    )


def _annulla_dentro(eids: list[str], da: str | None = None) -> dict:
    ""
    tutti = _eventi()
    posto = {e.get("eid"): i for i, e in enumerate(tutti) if e.get("eid")}
    if not eids or any(x not in posto for x in eids):
        raise Errore("errore_annulla_sparito")


    simulate = _carica_di(
        {i for x in eids if (i := tutti[posto[x]].get("id")).__class__ is str}, tutti
    )
    inversi = []
    for i in sorted({posto[x] for x in eids}, reverse=True):
        e = tutti[i]
        t = simulate.get(e.get("id"))
        if t is None:
            raise Errore("errore_sparita")
        tipo = e.get("tipo")
        if tipo == "cambia":
            if t["eliminata"]:
                raise Errore("errore_sparita")
            campi = e.get("campi") if isinstance(e.get("campi"), dict) else {}
            prima = e.get("prima") if isinstance(e.get("prima"), dict) else {}
            scritti = {k: v for k, v in _sani(campi).items() if k in CAMPI}
            if not scritti or any(t.get(k) != v for k, v in scritti.items()):
                raise _cambiata_dopo(t)
            indietro = {k: _sani({k: prima.get(k)}).get(k) for k in scritti}
            if any(
                indietro.get(k) is None for k in ("titolo", "stato", "priorita") if k in indietro
            ):

                raise Errore("errore_annulla_sparito")
            if "stato" in indietro:
                vecchia = prima.get("chiusa")
                chiuso = _chiuso(_imp(), indietro["stato"])
                indietro["chiusa"] = (vecchia or _ora()) if chiuso else None
            inv = {
                "tipo": "cambia",
                "campi": indietro,
                "prima": {k: t.get(k) for k in indietro},
            }
        elif tipo in ("commento", "commento_tolto", "commento_rimesso") and t["eliminata"]:
            raise Errore(
                "errore_sparita"
            )
        elif tipo == "commento":

            if e["eid"] not in t.get("commenti", {}):
                raise _cambiata_dopo(t)
            inv = {"tipo": "commento_tolto", "commento": e["eid"]}
        elif tipo in ("commento_tolto", "commento_rimesso"):
            quale = e.get("commento")
            dove = "commenti" if tipo == "commento_tolto" else "commenti_tolti"
            if quale in t.get(dove, {}):
                raise _cambiata_dopo(t)
            altro = "commento_rimesso" if tipo == "commento_tolto" else "commento_tolto"
            inv = {"tipo": altro, "commento": quale}
        elif tipo in ("crea", "ripristina"):
            if t["eliminata"]:
                raise _cambiata_dopo(t)
            nata = {**_VUOTA, **(t.get("nata_con") or {})}
            if tipo == "crea" and any(t.get(k) != nata.get(k) for k in CAMPI):

                raise _cambiata_dopo(t)
            inv = {"tipo": "elimina"}
        elif tipo == "elimina":
            if not t["eliminata"]:
                raise _cambiata_dopo(t)
            inv = {"tipo": "ripristina"}
        else:
            raise Errore("errore_annulla_sparito")
        inv = {"t": _ora(), "id": e["id"], "da": _chi(da), **inv, "annulla": e["eid"]}
        _applica(simulate, inv)
        inversi.append(inv)
    gruppo = _nuovo_id(8) if len(inversi) > 1 else None
    nuovi = []
    for inv in inversi:
        if gruppo:
            inv["gruppo"] = gruppo
        nuovi.append(_scrivi(inv))



    def profondita(e, n=0):
        while isinstance(e.get("annulla"), str) and e["annulla"] in posto and n < 10_000:
            e, n = tutti[posto[e["annulla"]]], n + 1
        return n

    rifare = profondita(tutti[posto[eids[0]]]) % 2 == 1
    ids = list(dict.fromkeys(inv["id"] for inv in inversi))
    return {
        "eventi": nuovi,
        "ids": ids,
        "rifare": rifare,
        "titoli": {i: simulate[i]["titolo"] for i in ids},
    }





_MS_GIORNO: dict[str, int] = {}


def _ms(giorno: str | None) -> int | None:
    ""

    if not giorno:
        return None
    if giorno not in _MS_GIORNO:
        _MS_GIORNO[giorno] = C._in_ms(datetime.fromisoformat(giorno).replace(hour=12))
    return _MS_GIORNO[giorno]


def _come_prima(t: dict) -> dict:
    ""
    return {
        "id": t["id"],
        "priority": t["priorita"],
        "due_date": _ms(t.get("scadenza")),
        "time_estimate": t["stima"] * 60000 if t.get("stima") else None,
        "date_created": _ms_di_campo(t, "creata") or C._in_ms(datetime.fromisoformat(t["creata"])),
        "date_updated": _ms_di_campo(t, "cambiata")
        or C._in_ms(datetime.fromisoformat(t["cambiata"])),
    }





# Documented internal-annotation format stripped from imported task descriptions:
# a leading "Stato al <DD/MM[/YY]>:" status line, optionally followed by an "Owner:" line.
# Adjust this pattern if your task descriptions use a different convention.
_RIGA_INTERNA = re.compile(
    r"^\s*Stato all?'?\s?\d{1,2}/\d{1,2}(?:/\d{2,4})?\s*:[^\n]*(?:\n|$)(?:[ \t]*Owner:[^\n]*(?:\n|$))?"
)


def _riga_interna_di(t: dict) -> str | None:
    ""
    if not (isinstance(t.get("origine"), dict) and t["origine"].get("fonte") == "clickup"):
        return None
    m = _RIGA_INTERNA.match(t.get("descrizione") or "")
    return m.group(0) if m and m.group(0).strip() else None


def _mostrata(t: dict) -> str:
    ""


    testo = t.get("descrizione") or ""
    riga = t.get("riga_interna")
    if not riga or not testo.startswith(riga):
        return testo
    return testo[len(riga) :].lstrip("\n")


def _mostrato(t: dict, campo: str):
    return _mostrata(t) if campo == "descrizione" else t.get(campo)


def _urgente(t: dict, c: dict, oggi: datetime, imp: dict | None = None) -> bool:
    ""


    u = (imp or _imp())["urgenti"]
    if t["priorita"] == 0 or (u.get("p1", True) and t["priorita"] == 1):
        return True
    g = _giorni_da(t.get("scadenza"), oggi)
    return g is not None and -int(u.get("giorni_prima", 6)) <= g <= int(u.get("giorni_dopo", 7))


@functools.lru_cache(maxsize=65536)
def _giorno10(giorno: str) -> date:
    return date.fromisoformat(giorno)


def _giorno_di(giorno: str) -> date:
    ""
    return _giorno10(giorno[:10])


def _giorni_da(giorno: str | None, oggi: datetime) -> int | None:
    ""
    if not giorno:
        return None
    return _giorni_fra(giorno[:10], oggi)


@functools.lru_cache(maxsize=65536)
def _giorni_fra(giorno10: str, oggi: datetime) -> int:
    ""
    return (oggi.date() - _giorno10(giorno10)).days


def _breve(giorno: str | None, oggi: datetime, davanti: bool) -> tuple[str, str]:
    ""


    g = _giorni_da(giorno, oggi)
    if g is None:
        return "", "vuota"
    d = _giorno10(giorno)
    data = (
        TESTI["breve_data"].format(n=d.day, mese=MESI_BREVI[d.month - 1])
        if d.year == oggi.year
        else TESTI["breve_data_anno"].format(n=d.day, mese=MESI_BREVI[d.month - 1], anno=d.year)
    )
    if g == 0:
        return TESTI["breve_oggi"], "oggi"
    if g == -1:
        return TESTI["breve_domani"], "vicina"
    if -6 <= g <= -2:
        return TESTI["breve_giorno"].format(giorno=GIORNI_BREVI[d.weekday()], n=d.day), "vicina"
    if g < -6:
        return data, "lontana"
    tono = "scaduta" if davanti else "passata"
    if g == 1:
        return TESTI["breve_ieri"], tono
    if g <= 6:
        return TESTI["breve_giorni_fa"].format(n=g), tono
    return data, tono


def _gruppo_scadenza(giorno: str | None, oggi: datetime) -> str:
    g = _giorni_da(giorno, oggi)
    if g is None:
        return "senza"
    if g >= 1:
        return "scadute"
    if g == 0:
        return "oggi"
    if g == -1:
        return "domani"
    return "settimana" if g >= -6 else "dopo"





def numero(n) -> str:
    ""
    return f"{n:,}".replace(",", ".") if isinstance(n, int) and not isinstance(n, bool) else str(n)


def _stima_breve(m: int | None) -> str:
    ""
    if not m:
        return ""
    if m < 60:
        return TESTI["breve_minuti"].format(n=m)
    ore, resto = divmod(m, 60)
    if resto == 0:
        return TESTI["breve_ore_tonde"].format(h=ore)
    return TESTI["breve_ore_minuti"].format(h=ore, mm=f"{resto:02d}")


def stima_campo(m: int | None) -> str:
    ""
    if not m:
        return ""
    if m < 60:
        return f"{m}m"
    ore, resto = divmod(m, 60)
    return f"{ore}h" if not resto else f"{ore}h{resto:02d}"


def stima_frase(m: int | None) -> str:
    ""
    if not m:
        return ""
    if m < 60:
        return TESTI["durata_minuto"] if m == 1 else TESTI["durata_minuti"].format(n=m)
    ore, resto = divmod(m, 60)
    base = TESTI["durata_ora"] if ore == 1 else TESTI["durata_ore"].format(n=numero(ore))
    if not resto:
        return base
    if resto == 30:
        return base + TESTI["durata_e_mezza"]
    return base + (
        TESTI["durata_e_un_minuto"] if resto == 1 else TESTI["durata_e_minuti"].format(n=resto)
    )


_NUMERI_PAROLA = {
    "un": 1, "uno": 1, "una": 1, "due": 2, "tre": 3, "quattro": 4, "cinque": 5, "sei": 6, "sette": 7, "otto": 8,
    "nove": 9, "dieci": 10, "undici": 11, "dodici": 12, "quindici": 15, "venti": 20, "venticinque": 25, "trenta": 30,
    "quaranta": 40, "quarantacinque": 45, "cinquanta": 50,
}
_UNITA = {
    **dict.fromkeys(("m", "min", "mins", "minuto", "minuti", "minute", "minutes", "'"), 1),
    **dict.fromkeys(("h", "hr", "hrs", "ora", "ore", "hour", "hours"), 60),
    **dict.fromkeys(
        ("g", "gg", "giorno", "giorni", "giornata", "giornate", "day", "days", "d"), "giorno"
    ),
}
_RIEMPITIVI = re.compile(
    r"\b(?:circa|più o meno|piu o meno|all'incirca|massimo|max|ca)\.?(?=\s|$)|~"
)


DURATA_MAX_CARATTERI = 80


_INTERVALLO_SEGNI = re.compile(r"\d\s*[a-zà-ú']*\s*[-–—~/]\s*\d")
_NUMERO_PAROLA_O_CIFRA = re.compile(
    r"^(?:\d+(?:[.,]\d+)?|un|uno|una|due|tre|quattro|cinque|sei|sette|otto|nove|dieci)$"
)

_FRAZIONI = {"1/2": " mezza ", "1/4": " un quarto ", "3/4": " tre quarti "}


def _e_intervallo(t: str) -> bool:
    ""

    if _INTERVALLO_SEGNI.search(t):
        return True
    parole = re.findall(r"[\wà-ú]+", t.replace("'", " "))
    fase = 0
    for i, p in enumerate(parole):
        numero = bool(_NUMERO_PAROLA_O_CIFRA.match(p))
        if p == "o" and 0 < i < len(parole) - 1:
            prima = parole[i - 1]
            dopo = parole[i + 1]
            if (
                _NUMERO_PAROLA_O_CIFRA.match(prima) or prima in _UNITA
            ) and _NUMERO_PAROLA_O_CIFRA.match(dopo):
                return True
        if fase == 0 and p in ("fra", "tra", "da"):
            fase = 1
        elif fase == 1 and numero:
            fase = 2
        elif fase == 2 and p in ("e", "a"):
            fase = 3
        elif fase == 3 and numero:
            return True
    return False


_SECONDI = re.compile(r"\d\s*(?:s|sec|secondi|secondo|seconds?)\b")
_TOKEN = re.compile(r"\d+(?::\d+)?(?:[.,]\d+)?|[a-zà-ú½]+|'")


def leggi_durata(testo, giornata: int | None = None) -> int | None:
    ""




    giornata = giornata or _imp()["settimana"].get("giornata_minuti") or 480
    t = str(testo if testo is not None else "").strip().casefold()
    if (re.fullmatch(r"[\d\s.,:']+", t) and len(re.sub(r"\D", "", t)) > 9) or re.search(
        r"\d{10,}", t
    ):



        raise Errore("errore_durata_troppo")
    if len(t) > DURATA_MAX_CARATTERI:
        raise Errore("errore_durata")
    t = t.replace("’", "'").replace("`", "'").replace("½", " mezza ")
    for frazione, parole in _FRAZIONI.items():
        t = re.sub(rf"(?<![\d/]){re.escape(frazione)}(?![\d/])", parole, t)
    if _e_intervallo(t):
        raise Errore("errore_durata_intervallo")

    t = t.strip().rstrip(".").strip()
    t = re.sub(r"\s+", " ", _RIEMPITIVI.sub(" ", t)).strip().rstrip(".").strip()
    if t in ("", "togli", "nessuno", "niente", "none", "0", "0m", "0 min", "0 minuti", "zero"):
        return None
    if re.match(r"^-\s*\d", t):
        raise Errore("errore_durata_negativa")
    if _SECONDI.search(t):
        raise Errore("errore_durata_secondi")

    t = re.sub(r"\bmezz'?\s?ora\b", "mezza ora", t)
    t = re.sub(r"\bun'\s?ora\b", "una ora", t)
    t = re.sub(r"\bd'\s?ora\b", "ora", t)
    t = re.sub(r"(\d)([a-zà-ú'])", r"\1 \2", t)
    t = re.sub(r"([a-zà-ú])(\d)", r"\1 \2", t)
    pezzi = _TOKEN.findall(t)
    if "".join(pezzi).replace(" ", "") != re.sub(r"[\s]", "", t):
        raise Errore("errore_durata")
    totale, ultima, sospeso, sospeso_testo = 0.0, None, None, ""
    i = 0

    def unita_di(p):
        u = _UNITA.get(p)
        return giornata if u == "giorno" else u

    while i < len(pezzi):
        p = pezzi[i]
        dopo = pezzi[i + 1] if i + 1 < len(pezzi) else None
        if re.fullmatch(r"\d+:\d+", p):
            if sospeso is not None or ultima is not None:
                raise Errore("errore_durata")
            h, mm = (int(x) for x in p.split(":"))
            if mm > 59:
                raise Errore("errore_durata")
            totale += h * 60 + mm
            ultima = 1
        elif re.fullmatch(r"\d+(?:[.,]\d+)?", p) or p in _NUMERI_PAROLA:
            if sospeso is not None:
                raise Errore("errore_durata")
            if p in _NUMERI_PAROLA:
                if p == "tre" and dopo == "quarti":
                    sospeso, sospeso_testo, i = 0.75, "frazione", i + 1
                elif p in ("un", "uno", "una") and dopo == "quarto":
                    sospeso, sospeso_testo, i = 0.25, "frazione", i + 1
                else:
                    sospeso, sospeso_testo = float(_NUMERI_PAROLA[p]), "intero"
            else:
                sospeso, sospeso_testo = float(p.replace(",", ".")), p
        elif p in ("mezza", "mezzo"):
            if sospeso is not None:
                raise Errore("errore_durata")
            if dopo is not None and dopo in _UNITA:
                sospeso, sospeso_testo = 0.5, "frazione"
            elif ultima in (60,) or (ultima is not None and ultima != 1):
                totale += ultima / 2
            else:
                raise Errore("errore_durata")
        elif p == "e":
            if sospeso is not None or ultima is None or dopo is None:
                raise Errore("errore_durata")
        elif p in _UNITA:
            u = unita_di(p)
            if sospeso is None:
                raise Errore("errore_durata")
            if ultima is not None and u >= ultima:
                raise Errore("errore_durata")
            if "." in sospeso_testo and len(sospeso_testo.split(".")[1]) >= 3:


                raise Errore("errore_durata")
            if u == 60 and "." in sospeso_testo and len(sospeso_testo.split(".")[1]) == 2:
                ore, mm = (int(x) for x in sospeso_testo.split("."))
                if mm > 59:
                    raise Errore("errore_durata")
                valore = ore * 60 + mm
            else:
                valore = sospeso * u
            if u == 1 and ultima == 60 and sospeso >= 60:
                raise Errore("errore_durata")
            totale += valore
            ultima, sospeso, sospeso_testo = u, None, ""
        else:
            raise Errore("errore_durata")
        i += 1
    if sospeso is not None:
        if ultima is None:

            if sospeso_testo in ("intero", "frazione"):
                if sospeso_testo == "frazione":
                    raise Errore("errore_durata")
                totale += sospeso
            elif "," in sospeso_testo:
                totale += sospeso * 60
            elif "." in sospeso_testo:
                intera, dec = sospeso_testo.split(".")
                if len(dec) >= 3:
                    raise Errore(
                        "errore_durata"
                    )
                if len(dec) == 2:
                    if int(dec) > 59:
                        raise Errore("errore_durata")
                    totale += int(intera) * 60 + int(dec)
                else:
                    totale += sospeso * 60
            else:
                totale += sospeso
        elif ultima == 60:
            if sospeso_testo == "frazione":
                totale += sospeso * 60
            elif sospeso >= 60 or sospeso != int(sospeso):
                raise Errore("errore_durata")
            else:
                totale += sospeso
        elif ultima not in (1, 60) and sospeso_testo == "frazione":
            totale += sospeso * ultima
        else:
            raise Errore("errore_durata")
    if totale > STIMA_MAX + 1:
        raise Errore("errore_durata_troppo")

    minuti = math.floor(totale + 0.5 + 1e-9)
    if minuti > STIMA_MAX:
        raise Errore("errore_durata_troppo")
    if minuti <= 0:
        if totale > 0:
            return 1
        return None
    return minuti


def durata(testo: str) -> dict:
    ""
    try:
        m = leggi_durata(testo)
    except Errore as e:
        return {"ok": False, "errore": TESTI[e.chiave]}
    frase = stima_frase(m)
    return {
        "ok": True,
        "minuti": m,
        "frase": frase,
        "anteprima": frase[:1].upper() + frase[1:] if frase else TESTI["stima_togli"],
        "breve": _stima_breve(m),
        "campo": stima_campo(m),
    }





def _chiavi_filtro(t: dict, oggi: datetime, area_id: str | None = None, tipo: str | None = None,
                   veloci: int | None = None, urgente: bool = False, attese: str | None = None) -> list[str]:
    ""


    gs = _gruppo_scadenza(t.get("scadenza"), oggi)
    out = [
        f"priorita:{t['priorita']}",
        f"stato:{t['stato']}",
        f"stato:tipo:{tipo or 'da_fare'}",
        f"area:{area_id or SENZA_AREA}",
        f"scadenza:{gs}",
        "scadenza:senza" if gs == "senza" else "scadenza:con_data",
    ]

    if gs in ("oggi", "domani", "settimana"):
        out.append("scadenza:settimana")
    m = t.get("stima")
    if not m:
        out.append("stima:senza")
    else:
        if m <= (veloci or C.VELOCE):
            out.append("stima:fino_30")
        if m <= 120:
            out.append("stima:fino_120")

    if urgente:
        out.append("pronto:urgenti")
    if m and m <= (veloci or C.VELOCE):
        out.append("pronto:veloci")
    if attese and area_id == attese:
        out.append("pronto:attese")


    return list(dict.fromkeys(out))


def _passa(chiavi: list[str], filtro: dict | None) -> bool:
    ""
    for campo, valori in (filtro or {}).items():
        if valori in (None, [], ""):
            continue
        scelti = valori if isinstance(valori, list) else [valori]
        if not any(f"{campo}:{v}" in chiavi for v in scelti):
            return False
    return True


def _chiusa_parole(quando: str | None, oggi: datetime, chiave: str = "chiusa") -> str:
    if not quando:
        return ""
    d = datetime.fromisoformat(quando)
    g = (oggi.date() - d.date()).days

    if g == 0:
        return TESTI[f"{chiave}_oggi"]
    if g == 1:
        return TESTI[f"{chiave}_ieri"]
    return TESTI[f"{chiave}_il"].format(giorno=C._il(d, oggi))


def _data_corta(quando: str | None, oggi: datetime) -> str:
    ""
    if not quando:
        return ""
    return _data_corta_giorno(quando[:10], oggi)


@functools.lru_cache(maxsize=65536)
def _data_corta_giorno(giorno10: str, oggi: datetime) -> str:
    d = _giorno10(giorno10)
    g = (oggi.date() - d).days
    if g == 0:
        return TESTI["breve_oggi"]
    if g == 1:
        return TESTI["breve_ieri"]
    if 2 <= g <= 6:
        return TESTI["breve_giorni_fa"].format(n=g)
    if d.year == oggi.year:
        return TESTI["breve_data"].format(n=d.day, mese=MESI_BREVI[d.month - 1])
    return TESTI["breve_data_anno"].format(n=d.day, mese=MESI_BREVI[d.month - 1], anno=d.year)


def _quando_alle(quando: str, oggi: datetime, con_ora: bool = True) -> str:
    ""

    return _quando_alle_tenuto(quando, oggi, con_ora)


@functools.lru_cache(maxsize=65536)
def _quando_alle_tenuto(quando: str, oggi: datetime, con_ora: bool) -> str:
    d = datetime.fromisoformat(quando[:19])
    g = (oggi.date() - d.date()).days
    giorno = TESTI["breve_oggi"] if g == 0 else TESTI["breve_ieri"] if g == 1 else C._il(d, oggi)
    if not con_ora or len(quando) <= 10:
        return giorno
    return TESTI["quando_alle"].format(giorno=giorno, ora=f"{d.hour}:{d.minute:02d}")


_RICHIESTA_VOCE = re.compile(r"^\d{4}-\d{2}-\d{2}-\d{6}-[0-9a-f]{4}$")


def _chi_ha(da) -> str:
    ""

    da = str(da or "")
    if da == "app":
        return "te"
    if da == "telefono":
        return "telefono"
    if da == "inspiration":
        return "spunto"
    if da.startswith("annulla:"):
        return "annulla"
    if _RICHIESTA_VOCE.match(da):
        return "voce"
    if da == "importa-clickup":
        return "clickup"
    if da == "impostazioni":
        return "impostazioni"
    return "altro"


def _ms_di(quando: str | None) -> int | None:
    ""
    if not quando:
        return None
    try:
        return C._in_ms(datetime.fromisoformat(quando[:19]))
    except ValueError:
        return None


def _ora_corta(hhmm: str) -> str:
    ""
    h, m = hhmm.split(":")
    return f"{int(h)}:{m}"


def _pianificata_parole(v, oggi: datetime) -> str:
    ""
    p = _pianificata_locale(v)
    if p is None:
        return ""
    parole = C._quando_parole(datetime.strptime(p[0], "%Y-%m-%d"), oggi)
    return TESTI["quando_alle"].format(giorno=parole, ora=_ora_corta(p[1])) if p[1] else parole


def _inizio_passato(v, stima, oggi: datetime, blocco: bool = True) -> bool:
    ""

    p = _pianificata_locale(v)
    if not p:
        return False
    giorno, ora = p
    if ora is None:
        return _giorno_di(giorno) < oggi.date()
    inizio = _ms_pianificata(v) or _ms_di(f"{giorno}T{ora}")
    durata = (stima or DURATA_SENZA_STIMA) if blocco else 0
    return inizio + durata * 60_000 <= _adesso_ms()


def _ms_pianificata(v) -> int | None:
    ""
    if not isinstance(v, str) or len(v) <= 16 or not re.search(r"[+-]\d{2}:?\d{2}$|Z$", v):
        return None
    try:
        d = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        return None
    return int(d.timestamp() * 1000) if d.tzinfo else None


def _inizio(t: dict, oggi: datetime, aperta: bool) -> dict:
    ""
    p = _pianificata_locale(t.get("pianificata"))
    if not p:
        return {}
    giorno, ora = p
    breve, tono = _breve(giorno, oggi, False)
    if ora:
        breve = TESTI["breve_giorno_ora"].format(giorno=breve, ora=_ora_corta(ora))


    passata = aperta and _inizio_passato(t["pianificata"], t.get("stima"), oggi)
    oltre = bool(aperta and t.get("scadenza") and giorno > t["scadenza"])
    aiuto = TESTI["aiuto_da_ripianificare"] if passata else TESTI["aiuto_inizio"]
    if oltre:
        aiuto = f"{aiuto} {TESTI['aiuto_oltre_scadenza']}"
    return {
        "pianificata": t["pianificata"],
        "pianificata_giorno": giorno,
        "pianificata_ora": ora,
        "inizio_breve": breve,
        "tono_inizio": "da_ripianificare" if passata else tono,
        "inizio_parole": _pianificata_parole(t["pianificata"], oggi),
        "inizio_aiuto": aiuto,
        "oltre_scadenza": oltre,


        "o_inizio": _ms_pianificata(t["pianificata"]) or _ms_di(f"{giorno}T{ora or '00:00'}"),
    }


class Contesto:
    ""

    def __init__(self, imp: dict, aree: Aree, tutte: list[dict], forma: dict | None = None):
        self.imp, self.aree = imp, aree

        self.forma = forma or {}
        self.veloci = int(imp.get("veloci_minuti") or C.VELOCE)

        self.attese = aree.finale(C.AREA_ATTESE)
        piegati = {x: _piega(x) for x in {t.get("titolo") or "" for t in tutte}}
        rango = {n: i for i, n in enumerate(sorted(set(piegati.values())))}

        self.rango_titolo = {x: rango[p] for x, p in piegati.items()}
        vive = sorted(aree.defs, key=lambda a: (_piega(aree.nome(a)), a))
        self.rango_area = {a: i for i, a in enumerate(vive)}
        self.ordine_stato = {s["id"]: n for n, s in enumerate(_stati_in_ordine(imp, True))}


def _voce(t: dict, oggi: datetime, ctx: Contesto | None = None) -> dict:
    if ctx is None:
        ctx = Contesto(_imp(), _aree(), [t])
    imp = ctx.imp
    c = ctx.forma.get(t["id"]) or _come_prima(t)
    sd = _stato_di(imp, t["stato"])
    chiuso = _chiuso_tipo(sd["tipo"])
    aperta = not t["eliminata"] and not chiuso
    davanti = aperta and _urgente(t, c, oggi, imp)
    frase, tono, aiuto = C._frase_scadenza(c, oggi)
    if tono == "spenta" and t.get("scadenza"):

        aiuto = TESTI["aiuto_scadeva"].format(
            giorno=C._il(datetime.fromisoformat(t["scadenza"]), oggi)
        )
    if not davanti and tono == "allarme":
        tono = "piana"
    breve, tono_breve = _breve(t.get("scadenza"), oggi, davanti)
    gs = _gruppo_scadenza(t.get("scadenza"), oggi)
    area_id = ctx.aree.finale(t.get("area"))
    area = ctx.aree.nome(area_id)
    chiusa = t.get("chiusa") if chiuso else None
    m = t.get("stima")
    nello = _giorni_da(t.get("stato_da"), oggi)
    chi = _chi_ha(t.get("cambiata_da"))
    if chi == "clickup":
        aiuto_cambio = TESTI["aiuto_cambio_clickup"].format(
            quando=_quando_alle(t["cambiata"], oggi, False)
        )
    else:
        aiuto_cambio = TESTI[f"aiuto_cambio_{chi}"].format(quando=_quando_alle(t["cambiata"], oggi))

    o = t.get("origine")
    spunto = (
        o["id"].strip()
        if isinstance(o, dict) and o.get("fonte") == "inspiration" and isinstance(o.get("id"), str)
        else ""
    )
    v = {
        "id": t["id"],
        "titolo": t["titolo"],
        "area": area,
        "urgente": t["priorita"] == 0,
        "davanti": davanti,
        "segno": "",
        "scadenza": frase,
        "tono": tono,
        "aiuto_scadenza": aiuto,
        "con_data": bool(t.get("scadenza")),
        "quanto": stima_frase(m),

        "dettaglio": _mostrata(t),
        "fermo": TESTI["ultimo_cambio"].format(
            giorno=C._data_lunga(C._da_ms(c["date_updated"]), oggi)
        ),


        "link": url if (buono := _link_buono(url := (t.get("origine") or {}).get("url"))) else None,



        **({"link_fonte": str(t["origine"].get("fonte") or "")} if buono or spunto else {}),

        **({"link_id": spunto} if spunto else {}),
        "priorita": t["priorita"],
        "priorita_nome": PRIORITA.get(t["priorita"], "P2"),
        "stato": sd["id"],
        "stato_nome": sd["nome"],
        "ultimo_cambio": C._data_lunga(C._da_ms(c["date_updated"]), oggi),
        "creata": C._data_lunga(C._da_ms(c["date_created"]), oggi),
        "o_priorita": t["priorita"],

        "o_scadenza": c["due_date"],
        "o_stima": m,
        "o_cambio": c["date_updated"],
        "o_creata": c["date_created"],
        "o_stato": ctx.ordine_stato.get(sd["id"], len(ctx.ordine_stato)),

        "giorno": t.get("scadenza"),

        "scadenza_breve": breve,
        "tono_breve": tono_breve,
        "stima_min": m,
        "stima_breve": _stima_breve(m),
        "gruppo_di": {
            "priorita": str(t["priorita"]),
            "stato": sd["id"],
            "area": area_id,
            "scadenza": gs,
        },

        "o_scadenza_gruppo": (
            -(c["due_date"] or 0) if gs == "scadute" else (c["due_date"] or GRANDE)
        ),
        "filtro_chiavi": _chiavi_filtro(
            t,
            oggi,
            area_id,
            sd["tipo"],
            ctx.veloci,
            davanti if aperta else (not t["eliminata"] and _urgente(t, c, oggi, imp)),
            ctx.attese,
        ),
        "aperta": aperta,
        "chiusa": chiusa,
        "chiusa_parole": _chiusa_parole(
            chiusa, oggi, "chiusa_non_serve" if sd["tipo"] == "non_serve" else "chiusa"
        ),
        "fatta_oggi": bool(chiusa) and datetime.fromisoformat(chiusa).date() == oggi.date(),
        "eliminata": t["eliminata"],
        "eliminata_parole": _chiusa_parole(t.get("eliminata_t"), oggi, "eliminata")
        if t["eliminata"]
        else "",

        "stato_tipo": sd["tipo"],
        "stato_segno": sd["segno"],
        "stato_colore": sd["colore"],
        "area_id": area_id,
        "o_area": None if area_id == SENZA_AREA else ctx.rango_area.get(area_id),
        "o_titolo": ctx.rango_titolo.get(t["titolo"]),
        "cambio_breve": _data_corta(t["cambiata"], oggi),
        "cambio_aiuto": aiuto_cambio,
        "creata_breve": _data_corta(t["creata"], oggi),
        "o_nello_stato": _ms_di_campo(t, "stato_da") or _ms_di(t.get("stato_da")),
        "nello_stato_giorni": nello,
    }
    if sd.get("sconosciuto"):
        v["stato_sconosciuto"] = True
    if sd.get("tolto"):
        v["stato_tolto"] = True
    if m:
        v["stima_campo"] = stima_campo(m)
        v["stima_frase"] = v["quanto"]
    if chiusa:
        v["chiusa_breve"] = _data_corta(chiusa, oggi)
        v["o_chiusa"] = _ms_di_campo(t, "chiusa") or _ms_di(chiusa)
    rinvii = t.get("rinvii") or 0



    if rinvii > 0:
        v["rinvii"] = rinvii
        v["o_rinvii"] = rinvii
        prima = t.get("scadenza_prima")
        giorno = C._il(datetime.strptime(prima, "%Y-%m-%d"), oggi) if prima else ""
        v["rinvii_aiuto"] = (
            TESTI["aiuto_rinvii_uno"].format(giorno=giorno)
            if rinvii == 1
            else TESTI["aiuto_rinvii_tanti"].format(n=numero(rinvii), giorno=giorno)
        )
    commenti = t.get("commenti") or {}
    if commenti:
        ultimo = max(commenti.values(), key=lambda c: c[2])[0]
        v["commenti_n"] = len(commenti)
        v["o_commenti"] = len(commenti)
        v["ultimo_commento_parole"] = TESTI["ultimo_commento"].format(
            quando=_quando_alle(ultimo, oggi)
        )
    v.update(_inizio(t, oggi, aperta))
    return v


def _fresca(t: dict, oggi: datetime, adesso: int | None = None) -> bool:
    ""

    adesso = adesso or _adesso_ms()
    nata = _ms_di_campo(t, "creata") or _ms_locale(t["creata"])
    return adesso - nata < 86_400_000





def _calendario(oggi: datetime) -> list[dict]:
    ""
    lunedi = oggi - timedelta(days=oggi.weekday())
    giorni = []
    for i in range(35):
        d = lunedi + timedelta(days=i)
        con_mese = i == 0 or d.day == 1
        giorni.append(
            {
                "giorno": d.strftime("%Y-%m-%d"),
                "etichetta": f"{d.day} {C.MESI[d.month - 1]}" if con_mese else str(d.day),
                "oggi": d.date() == oggi.date(),
            }
        )
    return giorni


def _mese(oggi: datetime, quale: str | None) -> dict:
    ""
    try:
        primo = datetime.strptime(quale, "%Y-%m") if quale else oggi.replace(day=1)

        if not (datetime(1, 2, 1) <= primo <= datetime(9999, 11, 1)):
            raise ValueError(quale)
    except (ValueError, TypeError):
        primo = oggi.replace(day=1)
    primo = primo.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    dopo = (primo.replace(day=28) + timedelta(days=4)).replace(day=1)
    prima = (primo - timedelta(days=1)).replace(day=1)
    inizio = primo - timedelta(days=primo.weekday())
    fine = dopo - timedelta(days=1)
    fine = fine + timedelta(days=6 - fine.weekday())
    giorni = []
    d = inizio
    while d <= fine:
        etichetta = (
            f"{d.day} {MESI_BREVI[d.month - 1]}" if d.day == 1 or d == inizio else str(d.day)
        )
        giorni.append(
            {
                "giorno": d.strftime("%Y-%m-%d"),
                "numero": d.day,
                "etichetta": etichetta,
                "oggi": d.date() == oggi.date(),
                "passato": d.date() < oggi.date(),
                "fuori": d.month != primo.month,
                "festivo": d.weekday() >= 5,
                "quando": C._quando_parole(d, oggi),
            }
        )
        d += timedelta(days=1)
    return {
        "id": primo.strftime("%Y-%m"),
        "titolo": f"{C.MESI[primo.month - 1]} {primo.year}",
        "prima": prima.strftime("%Y-%m"),
        "dopo": dopo.strftime("%Y-%m"),
        "oggi": oggi.strftime("%Y-%m"),
        "settimane": len(giorni) // 7,
        "giorni": giorni,
    }





def _file_viste() -> Path:
    return CARTELLA / "viste.json"


def _forma_viste(dati) -> bool:
    return (
        isinstance(dati, dict)
        and isinstance(dati.get("viste"), dict)
        and isinstance(dati.get("ordine", []), list)
        and isinstance(dati.get("tolte", {}), dict)
    )



_VISTE_ILLEGGIBILI: dict = {}


def _leggi_viste() -> dict:
    ""


    _VISTE_ILLEGGIBILI.clear()
    try:
        dati = json.loads(_file_viste().read_text(encoding="utf-8"))
        if _forma_viste(dati):
            return _viste_di_adesso(dati)
    except FileNotFoundError:
        pass
    except (OSError, UnicodeDecodeError) as e:
        if not isinstance(e, UnicodeDecodeError):
            _VISTE_ILLEGGIBILI["si"] = True
    except (ValueError, RecursionError):
        pass
    return {"versione": VERSIONE_VISTE, "ordine": [], "viste": {}}


def _viste_di_adesso(dati: dict) -> dict:
    ""



    if isinstance(dati.get("versione"), int) and dati["versione"] >= VERSIONE_VISTE:
        return dati
    dati = {**dati, "versione": VERSIONE_VISTE, "viste": dict(dati.get("viste") or {})}
    for vid in FILTRI_PRONTI:
        sua = dati["viste"].get(vid)
        dati["viste"][vid] = {**(sua if isinstance(sua, dict) else {}), "nascosta": True}
    ordine = [x for x in dati.get("ordine") or [] if isinstance(x, str)]
    if ordine:
        dati["ordine"] = [*PRONTE_IN_TESTA, *(x for x in ordine if x not in PRONTE_IN_TESTA)]
    return dati


def _salva_viste(dati: dict) -> None:
    ""

    f = _file_viste()
    if _VISTE_ILLEGGIBILI:
        raise Errore("errore_viste_illeggibili")
    if f.exists():

        try:
            buono = _forma_viste(json.loads(f.read_text(encoding="utf-8")))
        except (ValueError, RecursionError):
            buono = False
        except OSError as e:
            raise Errore("errore_viste_illeggibili") from e
        if not buono:
            try:
                f.rename(
                    f.with_name(f"viste.rotto-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}.json")
                )
            except OSError as e:
                raise _di_file(e, "viste") from None
    tmp = f.with_name(".viste.json.tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(dati, fh, ensure_ascii=False, indent=1)
            _fino_al_disco(fh)
        os.replace(tmp, f)
    except OSError as e:
        with contextlib.suppress(OSError):
            tmp.unlink()
        raise _di_file(e, "viste") from None

    with contextlib.suppress(OSError):
        fd = os.open(f.parent, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def _di_file(e: OSError, quale: str) -> OSError:
    ""
    e.sb_file = quale
    return e


def _tutte_le_viste(dati: dict) -> list[tuple[str, dict]]:
    ""

    salvate = dati.get("viste", {})
    tutte: dict[str, dict] = {}
    for vid, base in PRONTE.items():
        sua = salvate.get(vid)
        v = {**copy.deepcopy(base), **(sua if isinstance(sua, dict) else {}), "pronta": vid}
        tutte[vid] = _pulita_vista(v, base)
    for vid, v in salvate.items():


        if vid not in PRONTE and vid not in ID_RISERVATI and isinstance(v, dict):
            tutte[vid] = _pulita_vista({**_vista(), **v, "pronta": None}, _vista())

    ordine = list(
        dict.fromkeys(x for x in dati.get("ordine", []) if isinstance(x, str) and x in tutte)
    )
    resto = [x for x in tutte if x not in ordine]
    return [(x, tutte[x]) for x in ordine + resto]


def _pulita_vista(v: dict, base: dict) -> dict:
    ""
    for campo in (
        "filtro",
        "gruppo",
        "gruppi_chiusi",
        "ordine",
        "fatte",
        "modo",
        "scala",
        "calendari_nascosti",
        "rifiutati",
    ):
        try:
            v[campo] = _valida(campo, v.get(campo), stretto=False)
        except Errore:
            v[campo] = copy.deepcopy(base.get(campo))
            if campo == "filtro":
                v[campo] = {**FILTRO_VUOTO, **(base.get("filtro") or {})}
    if not isinstance(v.get("nome"), str) or _vuoto(v.get("nome")):
        v["nome"] = None
    else:
        v["nome"] = _nome_una_riga(v["nome"])
    if v.get("regola") not in (None, "urgenti"):
        v["regola"] = None

    if v.get("base") not in PRONTE:
        v["base"] = None
    try:
        v["colonne_tabella"] = _valida("colonne_tabella", v.get("colonne_tabella"))
    except Errore:
        v["colonne_tabella"] = None
    for campo in ("nascosta", "eliminata"):
        v[campo] = bool(v.get(campo))
    return v




_INVISIBILI_NON_COLLA = re.compile("[\u200b\u2060\ufeff\u00ad]")
_COLLA_AI_BORDI = re.compile("(?:^|(?<=\\s))[\u200c\u200d]+|[\u200c\u200d]+(?=\\s|$)")
_COLLA_DOPPIA = re.compile("([\u200c\u200d])[\u200c\u200d]+")


def _nome_una_riga(nome: str) -> str:
    ""

    if nome.isascii():
        return " ".join(nome.split())
    t = " ".join(_INVISIBILI_NON_COLLA.sub("", nome).split())
    if "\u200c" in t or "\u200d" in t:
        t = _COLLA_DOPPIA.sub(r"\1", _COLLA_AI_BORDI.sub("", t))
        t = " ".join(t.split())
    return t


def _nome_vista(vid: str, v: dict) -> str:
    return v.get("nome") or (
        TESTI[f"vista_{vid}"] if v.get("pronta") else TESTI["nome_vista_nuova"]
    )


def _ordine_pronto(vid: str, oggi: datetime, forma: dict):
    def scad(t):

        d = forma[t["id"]]["due_date"]
        return (d is None, d or 0)

    def nuova_prima(t):
        return -forma[t["id"]]["date_created"]

    if vid == "urgenti":
        return lambda t: (t["priorita"] != 0, scad(t), nuova_prima(t))
    if vid == "veloci":
        return lambda t: (scad(t), t["priorita"])
    if vid == "attese":
        return lambda t: (scad(t), nuova_prima(t))

    adesso = _adesso_ms()
    return lambda t: (not _fresca(t, oggi, adesso), t["priorita"], scad(t), nuova_prima(t))


def _nella_vista(
    v: dict, t: dict, voce: dict, forma: dict, oggi: datetime, imp: dict | None = None
) -> bool:
    if v.get("regola") == "urgenti" and not _urgente(t, forma[t["id"]], oggi, imp):
        return False
    return _passa(voce["filtro_chiavi"], v.get("filtro"))


def _filtro_risolto(filtro: dict, ctx: Contesto) -> dict:
    ""



    f = dict(filtro or {})
    f["area"] = list(dict.fromkeys(ctx.aree.finale(x) for x in filtro.get("area") or []))
    stati = []
    for x in filtro.get("stato") or []:
        if x.startswith("tipo:"):
            stati.append(x)
            continue
        s = ctx.imp["stati"].get(x)
        if s is not None and not s.get("tolto"):
            stati.append(x)
            continue
        r = _risolvi_stato(ctx.imp, x)
        if r:
            stati.append(r)
        else:


            stati.append(x)
    f["stato"] = list(dict.fromkeys(stati))
    return f


def _ordine_parole(livelli: list[dict] | None) -> str:
    if not livelli or len(livelli) < 2:
        return ""
    pezzi = [
        TESTI["ordine_parole_primo"].format(campo=TESTI[f"ordine_campo_{livelli[0]['campo']}"])
    ]
    for liv in livelli[1:]:
        pezzi.append(TESTI["ordine_parole_poi"].format(campo=TESTI[f"ordine_campo_{liv['campo']}"]))
    return "".join(pezzi)


_LETTERE = (
    "zero",
    "uno",
    "due",
    "tre",
    "quattro",
    "cinque",
    "sei",
    "sette",
    "otto",
    "nove",
    "dieci",
)


def _in_lettere(n) -> str:
    ""
    return _LETTERE[n] if isinstance(n, int) and 0 <= n < len(_LETTERE) else str(n)


def _testo_vista(chiave: str, pronta: str | None, imp: dict) -> str:
    ""
    if pronta == "veloci":
        m = int(imp.get("veloci_minuti") or 30)
        quanto = TESTI["durata_mezzora"] if m == 30 else stima_frase(m)
        return TESTI[f"{chiave}_vista_veloci_soglia"].format(quanto=quanto)
    if pronta == "urgenti" and chiave == "aiuto":
        u = imp["urgenti"]
        return TESTI[
            "aiuto_vista_urgenti_p1" if u.get("p1", True) else "aiuto_vista_urgenti_p0"
        ].format(
            dopo=_in_lettere(u.get("giorni_dopo", 7)), prima=_in_lettere(u.get("giorni_prima", 6))
        )
    if pronta:
        return TESTI.get(f"{chiave}_vista_{pronta}", "")
    return TESTI[f"{chiave}_vista_mia"]


def _schede(dati, aperte, chiuse, voci, forma, oggi, ctx: Contesto) -> tuple[list, list, list]:
    schede, nascoste, eliminate = [], [], []
    for vid, v in _tutte_le_viste(dati):
        if v.get("eliminata"):
            eliminate.append({"id": vid, "nome": _nome_vista(vid, v)})
            continue
        if v.get("nascosta"):
            nascoste.append({"id": vid, "nome": _nome_vista(vid, v)})
        filtro = _filtro_risolto(v["filtro"], ctx)
        vv = {**v, "filtro": filtro}

        chiave = _ordine_pronto(v.get("pronta") or v.get("base") or "", oggi, forma)
        righe = sorted(
            (t for t in aperte if _nella_vista(vv, t, voci[t["id"]], forma, oggi, ctx.imp)),
            key=chiave,
        )
        senza_stato = {**filtro, "stato": []}

        def passa_chiusa(t):

            if v.get("regola") == "urgenti" and not _urgente(t, forma[t["id"]], oggi, ctx.imp):
                return False
            return _passa(voci[t["id"]]["filtro_chiavi"], senza_stato)

        fatte = []
        if v.get("fatte") in ("7_giorni", "tutte"):

            limite = (oggi - timedelta(days=7)).strftime("%Y-%m-%d")
            fatte = [
                t["id"]
                for t in chiuse
                if (v["fatte"] == "tutte" or (t.get("chiusa") or t["cambiata"])[:10] >= limite)
                and passa_chiusa(t)
            ]

        fatte_oggi = [t["id"] for t in chiuse if voci[t["id"]]["fatta_oggi"] and passa_chiusa(t)]
        pronta = v.get("pronta")
        com_era = pronta is not None and {
            k: v.get(k) for k in PRONTE[pronta] if k not in ("nascosta", "eliminata")
        } != {k: x for k, x in PRONTE[pronta].items() if k not in ("nascosta", "eliminata")}
        livelli = v.get("ordine") or None
        gruppo = v.get("gruppo") if v.get("gruppo") in CAMPI_GRUPPO else "nessuno"
        chiusi = [str(x) for x in v.get("gruppi_chiusi") or []]
        if gruppo == "area":
            chiusi = list(dict.fromkeys(ctx.aree.finale(x) for x in chiusi))
        schede.append(
            {
                "id": vid,
                "nome": _nome_vista(vid, v),
                "nome_suo": bool(v.get("nome")),
                "pronta": pronta,
                "modo": v.get("modo") if v.get("modo") in MODI else "tabella",
                "regola": v.get("regola"),
                "filtro": filtro,
                "gruppo": gruppo,
                "gruppi_chiusi": chiusi,


                "ordine": livelli[0] if livelli else None,
                "ordine_livelli": livelli or [],
                "ordine_parole": _ordine_parole(livelli),
                "colonne_tabella": v.get("colonne_tabella"),
                "scala": v.get("scala") if v.get("scala") in SCALE else "mese",
                "calendari_nascosti": v.get("calendari_nascosti"),
                "rifiutati": bool(v.get("rifiutati")),
                "fatte": v.get("fatte") if v.get("fatte") in FATTE_VISTA else "no",
                "nascosta": bool(v.get("nascosta")),
                "cambiata": com_era,
                "aiuto": _testo_vista("aiuto", pronta, ctx.imp),
                "vuoto": _testo_vista("vuoto", pronta, ctx.imp),
                "numero": len(righe),
                "id_righe": [t["id"] for t in righe],
                "id_fatte": fatte,
                "id_fatte_oggi": fatte_oggi,
                "base": v.get("base"),
            }
        )
    return schede, nascoste, eliminate


def _conta_aree(aperte: list[dict], voci: dict) -> dict[str, int]:
    conta: dict[str, int] = {}
    for t in aperte:
        a = voci[t["id"]]["area_id"]
        conta[a] = conta.get(a, 0) + 1
    return conta


def _gruppi_per(aperte: list[dict], voci: dict, ctx: Contesto) -> dict:
    ""



    conta = _conta_aree(aperte, voci)
    aree = [{"id": d["id"], "nome": d["nome"], "valore": d["id"]} for d in ctx.aree.visibili(conta)]
    aree.append({"id": SENZA_AREA, "nome": TESTI["senza_area"], "valore": SENZA_AREA})
    return {
        "priorita": {
            "verbo": "priorita",
            "gruppi": [
                {"id": str(n), "nome": nome, "valore": str(n)} for n, nome in PRIORITA.items()
            ],
        },
        "stato": {
            "verbo": "stato",
            "gruppi": [
                {
                    "id": s["id"],
                    "nome": s["nome"],
                    "valore": s["id"],
                    "tipo": s["tipo"],
                    "chiuso": _chiuso_tipo(s["tipo"]),
                }
                for s in _stati_in_ordine(ctx.imp)
            ]


            + _gruppi_stati_fuori(aperte, ctx),
        },
        "area": {"verbo": "area", "gruppi": aree},
        "scadenza": {
            "verbo": "data",
            "gruppi": [
                {"id": "scadute", "nome": TESTI["gruppo_scadute"], "valore": None},
                {"id": "oggi", "nome": TESTI["gruppo_oggi"], "valore": _giorno("oggi")},
                {"id": "domani", "nome": TESTI["gruppo_domani"], "valore": _giorno("domani")},
                {
                    "id": "settimana",
                    "nome": TESTI["gruppo_settimana"],
                    "valore": _giorno("settimana"),
                },
                {"id": "dopo", "nome": TESTI["gruppo_dopo"], "valore": _giorno("mese")},
                {"id": "senza", "nome": TESTI["gruppo_senza"], "valore": "togli"},
            ],
        },
    }


def _gruppi_stati_fuori(aperte: list[dict], ctx: Contesto) -> list[dict]:
    noti = {s["id"] for s in _stati_in_ordine(ctx.imp)}
    out = []
    for sid in dict.fromkeys(t["stato"] for t in aperte):
        if sid not in noti and isinstance(sid, str):
            s = _stato_di(ctx.imp, sid)
            out.append({"id": sid, "nome": s["nome"], "valore": None, "tipo": s["tipo"],
                        "chiuso": False, "tolto": True})
    return out


def _filtri(aperte: list[dict], voci: dict, ctx: Contesto) -> dict:
    conteggi: dict[str, int] = {}
    for t in aperte:
        for k in voci[t["id"]]["filtro_chiavi"]:
            conteggi[k] = conteggi.get(k, 0) + 1

    def n(chiave):
        return conteggi.get(chiave, 0)

    conta = _conta_aree(aperte, voci)
    aree = [
        {"id": d["id"], "nome": d["nome"], "n": conta.get(d["id"], 0)}
        for d in ctx.aree.visibili(conta)
    ]
    if conta.get(SENZA_AREA):
        aree.append({"id": SENZA_AREA, "nome": TESTI["senza_area"], "n": conta[SENZA_AREA]})
    aperti = [s for s in _stati_in_ordine(ctx.imp) if not _chiuso_tipo(s["tipo"])]
    stati = [{"id": s["id"], "nome": s["nome"], "n": n(f"stato:{s['id']}")} for s in aperti]


    noti = {s["id"] for s in aperti}
    for sid in dict.fromkeys(t["stato"] for t in aperte):
        if sid not in noti:
            stati.append(
                {"id": sid, "nome": _stato_di(ctx.imp, sid)["nome"], "n": n(f"stato:{sid}")}
            )
    for tipo in ("da_fare", "in_corso", "aspetta"):
        if sum(1 for s in aperti if s["tipo"] == tipo) > 1:
            stati.append(
                {
                    "id": f"tipo:{tipo}",
                    "nome": TESTI[f"filtro_tipo_{tipo}"],
                    "n": n(f"stato:tipo:{tipo}"),
                }
            )
    return {
        "priorita": {
            "nome": TESTI["colonna_priorita"],
            "una": False,
            "scelte": [
                {"id": str(k), "nome": v, "n": n(f"priorita:{k}")} for k, v in PRIORITA.items()
            ],
        },
        "area": {"nome": TESTI["colonna_area"], "una": False, "scelte": aree},
        "scadenza": {
            "nome": TESTI["colonna_scadenza"],
            "una": True,
            "scelte": [
                {"id": k, "nome": TESTI[f"filtro_{nome}"], "n": n(f"scadenza:{k}")}
                for k, nome in (
                    ("scadute", "scadute"),
                    ("oggi", "oggi"),
                    ("settimana", "settimana"),
                    ("con_data", "con_data"),
                    ("senza", "senza_data"),
                )
            ],
        },
        "stima": {
            "nome": TESTI["colonna_stima"],
            "una": True,
            "scelte": [
                {
                    "id": "fino_30",
                    "nome": TESTI["filtro_veloci"].format(quanto=stima_frase(ctx.veloci)),
                    "n": n("stima:fino_30"),
                },
                {"id": "fino_120", "nome": TESTI["filtro_fino_120"], "n": n("stima:fino_120")},
                {"id": "senza", "nome": TESTI["filtro_senza_stima"], "n": n("stima:senza")},
            ],
        },
        "stato": {"nome": TESTI["colonna_stato"], "una": False, "scelte": stati},

        "pronto": {
            "nome": TESTI["filtri_pronti"],
            "una": True,
            "scelte": _filtri_pronti(conteggi, ctx),
        },
    }


def _filtri_pronti(conteggi: dict[str, int], ctx: Contesto) -> list[dict]:
    ""

    return [
        {
            "id": x,
            "nome": TESTI[f"vista_{x}"],
            "aiuto": _testo_vista("aiuto", x, ctx.imp),
            "vuoto": _testo_vista("vuoto", x, ctx.imp),
            "filtro": {"pronto": x},
            "n": conteggi.get(f"pronto:{x}", 0),
        }
        for x in FILTRI_PRONTI
    ]


def _aiuto_numero(n: int, p0: int) -> str:
    if n == 0:
        return TESTI["aiuto_numero_zero"]
    if n == 1:

        return TESTI["aiuto_numero_uno_p0" if p0 else "aiuto_numero_uno"]
    if p0 == 0:
        return TESTI["aiuto_numero"].format(n=numero(n))
    if p0 == 1:
        return TESTI["aiuto_numero_p0_uno"].format(n=numero(n))
    return TESTI["aiuto_numero_p0_tanti"].format(n=numero(n), p=numero(p0))


def _info_stati(imp: dict, tutte: list[dict]) -> list[dict]:
    ""
    tot: dict[str, int] = {}
    for t in tutte:
        if t["eliminata"]:
            continue
        tot[t["stato"]] = tot.get(t["stato"], 0) + 1
    predefinito = _predefinito(imp)
    out = []
    for s in _stati_in_ordine(imp, True):
        chiuso = _chiuso_tipo(s["tipo"])
        out.append(
            {
                "id": s["id"],
                "nome": s["nome"],
                "tipo": s["tipo"],
                "chiuso": chiuso,
                "segno": s["segno"],
                "colore": s["colore"],
                "ordine": s["ordine"],
                "predefinito": s["id"] == predefinito,
                "tolto": bool(s.get("tolto")),
                "in": s.get("in"),
                "nomi_prima": list(s.get("nomi_prima") or []),
                "n_aperte": 0 if chiuso else tot.get(s["id"], 0),
                "n": tot.get(s["id"], 0),
            }
        )
    return out


def _info_aree(ctx: Contesto, tutte: list[dict], voci: dict, conta: dict[str, int]) -> list[dict]:
    ""
    n_aperte, n = {}, {}
    for t in tutte:
        if t["eliminata"]:
            continue
        diretta = ctx.aree.cerca(t.get("area") or "") or SENZA_AREA
        n[diretta] = n.get(diretta, 0) + 1
        if voci[t["id"]]["aperta"]:
            n_aperte[diretta] = n_aperte.get(diretta, 0) + 1
    vive = ctx.aree.visibili(conta)
    resto = [d for d in ctx.aree.defs.values() if d not in vive]
    out = []
    for d in [*vive, *sorted(resto, key=lambda d: _piega(d["nome"]))]:
        out.append(
            {
                "id": d["id"],
                "nome": d["nome"],
                "nomi": [x for x in d["nomi"] if x != d["nome"]],
                "ordine": d.get("ordine"),
                "colore": d.get("colore"),
                "unita_in": d.get("unita_in"),
                "tolta": bool(d.get("tolta")),
                "senza": bool(d.get("senza")),
                "n_aperte": n_aperte.get(d["id"], 0),
                "n": n.get(d["id"], 0),
            }
        )
    return out


def _info_impostazioni(imp: dict) -> dict:
    return {
        "veloci_minuti": int(imp.get("veloci_minuti") or 30),
        "urgenti": dict(imp["urgenti"]),
        "settimana": dict(imp["settimana"]),
        "predefinito": _predefinito(imp),
    }


def _scelte_impostazioni() -> dict:
    return {
        "scelte_tipi": [
            {
                "id": t,
                "nome": TESTI[f"tipo_{t}"],
                "aiuto": TESTI[f"aiuto_tipo_{t}"],
                "chiuso": _chiuso_tipo(t),
            }
            for t in TIPI
        ],
        "scelte_segni": {t: list(v) for t, v in SEGNI.items()},
        "scelte_colori": [{"id": c, "nome": TESTI[f"colore_{c}"]} for c in COLORI],
        "giorni_lunghi": list(C.GIORNI),
    }


def _colonne_info() -> list[dict]:
    ""

    out = []
    for cid, accesa, si_cambia, campo in COLONNE:
        out.append(
            {
                "id": cid,
                "nome": TESTI.get(f"colonna_{cid}", ""),
                "accesa": accesa,
                "si_cambia": si_cambia,
                "ordinabile": campo is not None,
                "campo_ordine": campo,
                "verso_di_partenza": VERSO_DI_PARTENZA.get(campo, "su") if campo else None,
            }
        )
    return out


def _ordini() -> list[dict]:
    out = []
    for o in CAMPI_ORDINE:
        nome = (
            TESTI["ordine_pronto"]
            if o == "pronto"
            else TESTI["ordine_titolo"]
            if o == "titolo"
            else TESTI[f"colonna_{o}"]
        )
        voce = {"id": o, "nome": nome}
        if o != "pronto":
            voce.update(
                su=TESTI[f"verso_{o}_su"],
                giu=TESTI[f"verso_{o}_giu"],
                verso_di_partenza=VERSO_DI_PARTENZA.get(o, "su"),
            )
        out.append(voce)
    return out


_CAL: dict = {}


def _calendario_modulo():
    ""

    if "m" not in _CAL:
        try:
            import sb_attivita_calendario as K  # noqa: PLC0415
        except Exception:  # noqa: BLE001
            K = None
        _CAL["m"] = K
    return _CAL["m"]


def _task_calendario(tutte: dict[str, dict], imp: dict) -> list[dict]:
    ""
    return [
        {"id": t["id"], "scadenza": t.get("scadenza"), "pianificata": t.get("pianificata"), "stima": t.get("stima"),
         "stato": t["stato"], "chiusa": _chiuso(imp, t["stato"]), "priorita": t["priorita"]}
        for t in tutte.values() if not t["eliminata"]
    ]


def _vista_calendario(vid: str | None) -> dict:
    ""

    if not vid:
        return {}
    try:
        v = next(x for i, x in _tutte_le_viste(_leggi_viste()) if i == vid)
    except StopIteration:
        return {}
    out = {"scala": v.get("scala"), "rifiutati": bool(v.get("rifiutati"))}
    if v.get("calendari_nascosti") is not None:
        out["calendari_nascosti"] = list(v["calendari_nascosti"])
    return out





def pagina(
    mese: str | None = None,
    tutte_le_fatte: bool = False,
    settimana: str | None = None,
    scala: str | None = None,
    vista: str | None = None,
) -> dict:
    oggi = C._adesso()
    ev = _eventi()
    tutte = _carica(ev)
    imp = _imp()
    aree = Aree(imp, _valori_area(ev))
    del ev
    aperte = [t for t in tutte.values() if not t["eliminata"] and not _chiuso(imp, t["stato"])]

    limite = (oggi - timedelta(days=FATTE_GIORNI)).strftime("%Y-%m-%d")

    chiuse_tutte = sorted(
        (t for t in tutte.values() if not t["eliminata"] and _chiuso(imp, t["stato"])),
        key=lambda t: _ms_di_campo(t, "chiusa") or _ms_di_campo(t, "cambiata"),
        reverse=True,
    )
    chiuse = [
        t
        for t in chiuse_tutte
        if tutte_le_fatte or (t.get("chiusa") or t["cambiata"])[:10] >= limite
    ]
    eliminate = sorted(
        (t for t in tutte.values() if t["eliminata"]),
        key=lambda t: _ms_di_campo(t, "eliminata") or _ms_di_campo(t, "cambiata"),
        reverse=True,
    )
    forma = {t["id"]: _come_prima(t) for t in tutte.values()}
    aree.con_task = {aree.finale(t.get("area")) for t in tutte.values() if not t["eliminata"]}
    ctx = Contesto(imp, aree, [*aperte, *chiuse_tutte, *eliminate], forma)


    voci = {t["id"]: _voce(t, oggi, ctx) for t in [*aperte, *chiuse_tutte, *eliminate]}
    adesso = _adesso_ms()

    def scad(t):

        d = forma[t["id"]]["due_date"]
        return (d is None, d or 0)

    def nuova_prima(t):
        return -forma[t["id"]]["date_created"]

    urgenti = sorted(
        (t for t in aperte if _urgente(t, forma[t["id"]], oggi, imp)),
        key=lambda t: (t["priorita"] != 0, scad(t), nuova_prima(t)),
    )
    attese = aree.finale(C.AREA_ATTESE)

    viste = [
        ("urgenti", urgenti),
        (
            "in_corso",
            sorted(
                (t for t in aperte if voci[t["id"]]["stato_tipo"] == "in_corso"),
                key=lambda t: (t["priorita"], scad(t)),
            ),
        ),
        (
            "veloci",
            sorted(
                (t for t in aperte if (t.get("stima") or 10**9) <= ctx.veloci),
                key=lambda t: (scad(t), t["priorita"]),
            ),
        ),
        (
            "attese",
            sorted(
                (t for t in aperte if voci[t["id"]]["area_id"] == attese),
                key=lambda t: (scad(t), nuova_prima(t)),
            ),
        ),
        (
            "tutte",
            sorted(
                aperte,
                key=lambda t: (
                    not _fresca(t, oggi, adesso),
                    t["priorita"],
                    scad(t),
                    nuova_prima(t),
                ),
            ),
        ),
    ]
    ferme = [t for t in aperte if t["priorita"] <= 1 and C._ferma(forma[t["id"]], oggi)]
    frase_ferme = ""
    if ferme:
        m = C.MESI[int(min(t["scadenza"] for t in ferme)[5:7]) - 1]
        chiave = "rivedi_ferme_uno" if len(ferme) == 1 else "rivedi_ferme_tanti"
        frase_ferme = TESTI[chiave].format(n=numero(len(ferme)), mese=m)
    colonne = {
        c: TESTI[f"colonna_{c}"]
        for c in (
            "task",
            "priorita",
            "scadenza",
            "stima",
            "area",
            "cambio",
            "creata",
            "stato",
            "inizio",
            "chiusa",
            "rinvii",
            "commenti",
        )
    }
    schede, nascoste, viste_eliminate = _schede(
        _leggi_viste(), aperte, chiuse_tutte, voci, forma, oggi, ctx
    )
    avviso = TESTI["avviso_viste_illeggibili"] if _VISTE_ILLEGGIBILI else ""
    p0 = sum(1 for t in aperte if t["priorita"] == 0)
    conta_aree = _conta_aree(aperte, voci)
    id_chiuse = {t["id"] for t in chiuse}
    cal = _calendario_modulo()
    out = {
        "ok": True,
        "contratto": CONTRATTO,
        "verdetto": "",
        "letto": "",
        "avviso": avviso,
        "davanti": len(urgenti),
        "aperte": len(aperte),
        "righe": [voci[t["id"]] for t in aperte],
        "viste": [
            {
                "id": vid,
                "titolo": TESTI[f"vista_{vid}"],
                "aiuto": TESTI[f"aiuto_vista_{vid}"],
                "vuoto": TESTI[f"vuoto_vista_{vid}"],
                "id_righe": [t["id"] for t in righe],
            }
            for vid, righe in viste
        ],
        "colonne": colonne,
        "scelte_priorita": [{"id": str(n), "nome": nome} for n, nome in PRIORITA.items()],
        "scelte_stato": [{"id": s["id"], "nome": s["nome"]} for s in _stati_in_ordine(imp)],
        "scelte_stima": [{"id": str(m), "nome": stima_frase(m)} for m in (5, 15, 30, 60, 120)],


        "scelte_data": [{**x, "id": _giorno(x["id"]) or x["id"]} for x in C._scelte_data(oggi)],

        "aree": [d["nome"] for d in aree.visibili(conta_aree)],
        "ferme": {"frase": frase_ferme, "id_righe": [t["id"] for t in ferme]},

        "modi": [{"id": m, "nome": TESTI[f"modo_{m}"]} for m in MODI],
        "giorni_brevi": list(GIORNI_BREVI),
        "calendario": _calendario(oggi),

        "schede": schede,
        "schede_nascoste": nascoste,
        "schede_eliminate": viste_eliminate,
        "speciali": [
            {
                "id": "fatte",
                "nome": TESTI["vista_fatte"],
                "aiuto": TESTI["aiuto_vista_fatte"],
                "vuoto": TESTI["vuoto_vista_fatte"],
                "id_righe": [t["id"] for t in chiuse],
                "altre": len(chiuse_tutte) - len(chiuse),
            },
            {
                "id": "eliminate",
                "nome": TESTI["vista_eliminate"],
                "aiuto": TESTI["aiuto_vista_eliminate"],
                "vuoto": TESTI["vuoto_vista_eliminate"],
                "id_righe": [t["id"] for t in eliminate],
                "altre": 0,
            },
        ],
        "righe_chiuse": [voci[t["id"]] for t in chiuse]
        + [
            voci[i]
            for i in dict.fromkeys(i for sc in schede for i in sc["id_fatte"])
            if i not in id_chiuse
        ],
        "righe_eliminate": [voci[t["id"]] for t in eliminate],

        "fatte_oggi_n": sum(
            1
            for t in chiuse
            if voci[t["id"]]["fatta_oggi"] and voci[t["id"]]["stato_tipo"] == "fatta"
        ),
        "gruppi_per": _gruppi_per(aperte, voci, ctx),
        "filtri": (filtri := _filtri(aperte, voci, ctx)),

        "filtri_pronti": filtri["pronto"]["scelte"],
        "ordini": _ordini(),
        "scelte_stima_brevi": [
            {"id": str(m), "nome": _stima_breve(m)} for m in (5, 15, 30, 60, 120)
        ],
        "p0": p0,
        "aiuto_numero": (aiuto_numero := _aiuto_numero(len(urgenti), p0)),
        "mese": _mese(oggi, mese),

        "stati": _info_stati(imp, list(tutte.values())),
        "aree_def": _info_aree(ctx, list(tutte.values()), voci, conta_aree),
        "impostazioni": _info_impostazioni(imp),
        "durata_giornata_minuti": int(imp["settimana"].get("giornata_minuti") or 480),
        "colonne_info": _colonne_info(),
        **_scelte_impostazioni(),
        "testi": {
            **TESTI,
            "aiuto_barra": TESTI["aiuto_barra"].format(
                sottotitolo=TESTI["sottotitolo"], numero=aiuto_numero.rstrip(".")
            ),
        },
    }

    out["testi_calendario"] = {
        **TESTI_SETTIMANA,
        **(cal.TESTI if cal is not None and isinstance(getattr(cal, "TESTI", None), dict) else {}),
    }
    if settimana is not None:

        out["settimana"] = None
        r = None
        if cal is not None:
            argomenti = [
                "--settimana",
                *([settimana] if settimana else []),
                *(["--giorno"] if scala == "giorno" else []),
            ]
            try:
                r = cal.esegui(argomenti, task=_task_calendario(tutte, imp), impostazioni=_info_impostazioni(imp),
                               vista=_vista_calendario(vista))
            except Exception:  # noqa: BLE001 la porta del modulo non alza, ma la pagina resta sana comunque
                r = None
        if isinstance(r, dict) and r.get("ok") and isinstance(r.get("settimana"), dict):
            out["settimana"] = r["settimana"]
        else:
            err = r.get("errore") if isinstance(r, dict) else None
            out["settimana_errore"] = (
                err if isinstance(err, str) and err else TESTI["errore_calendario"]
            )
    return out




_PRIO = re.compile(r"^p([0-3])$")
_DATE_UNA = {"oggi": "oggi", "domani": "domani", "dopodomani": "dopodomani"}
_GIORNI_SENZA_ACCENTO = {g.replace("ì", "i"): i for i, g in enumerate(C.GIORNI)}


def _senza_accento_giorno(parola: str) -> str:
    ""
    p = unicodedata.normalize("NFC", parola).casefold().replace("’", "'")
    if p.endswith("i'"):
        p = p[:-1]
    return p.replace("ì", "i").replace("í", "i")


def _giorno_da_parola(parole: list[str], oggi: datetime) -> tuple[int, str | None]:
    ""

    base = oggi.replace(hour=12, minute=0, second=0, microsecond=0)
    if (
        len(parole) >= 3
        and parole[-3:-1] in (["fra", "una"], ["tra", "una"])
        and parole[-1] == "settimana"
    ):
        return 3, (base + timedelta(days=7)).strftime("%Y-%m-%d")
    if (
        len(parole) >= 3
        and parole[-3:-1] in (["fra", "un"], ["tra", "un"])
        and parole[-1] == "mese"
    ):
        return 3, C._da_ms(C._quando("mese", oggi)).strftime("%Y-%m-%d")
    if not parole:
        return 0, None

    if len(parole) >= 2 and parole[-2:] == ["dopo", "domani"]:
        return 2, (base + timedelta(days=2)).strftime("%Y-%m-%d")
    ultima = _senza_accento_giorno(parole[-1])
    if ultima in ("oggi", "domani"):
        return 1, C._da_ms(C._quando(ultima, oggi)).strftime("%Y-%m-%d")
    if ultima == "dopodomani":
        return 1, (base + timedelta(days=2)).strftime("%Y-%m-%d")
    if ultima in _GIORNI_SENZA_ACCENTO:
        avanti = (_GIORNI_SENZA_ACCENTO[ultima] - base.weekday()) % 7 or 7
        return 1, (base + timedelta(days=avanti)).strftime("%Y-%m-%d")
    return 0, None



_DAVANTI_ALLA_DATA = ("entro", "per", "questo", "questa", "prossimo", "prossima")

_ATTACCATA = "()[]{}«»\"'.,;:!?…“”"


def capisci(testo: str) -> dict:
    ""






    oggi = C._adesso()
    testo = str(testo or "")
    pezzi = [(m.start(), m.end()) for m in re.finditer(r"\S+", testo)]
    chiavi = [testo[a:b].strip(_ATTACCATA).casefold() for a, b in pezzi]
    n = len(pezzi)
    priorita, giorno, stima, etichette = None, None, None, []

    def coda(k: int) -> str:
        return testo[pezzi[n - k][0] : pezzi[n - 1][1]]

    for _ in range(3):
        if n < 2:
            break
        ultima = chiavi[n - 1]
        m = _PRIO.match(ultima)
        if m and priorita is None:
            priorita = int(m.group(1))
            etichette.append({"tipo": "priorita", "testo": PRIORITA[priorita], "parole": coda(1)})
            n -= 1
            continue
        quante, g = _giorno_da_parola(chiavi[:n], oggi)
        if g and giorno is None and quante < n:
            if n - quante >= 2 and chiavi[n - quante - 1] in _DAVANTI_ALLA_DATA:
                quante += 1
            giorno = g
            d = datetime.strptime(g, "%Y-%m-%d")
            etichette.append(
                {"tipo": "scadenza", "testo": C._quando_parole(d, oggi), "parole": coda(quante)}
            )
            n -= quante
            continue
        break
    titolo = testo[: pezzi[n - 1][1]].strip() if etichette else testo.strip()
    tutte = list(reversed(etichette))
    return {
        "ok": True,
        "titolo": titolo,
        "priorita": priorita,
        "scadenza": giorno,
        "stima": stima,
        "etichette": tutte,
        "etichette_tutte": tutte,
    }





def _esito(messaggio: str, annulla: list[str] | None = None, **altro) -> dict:

    messaggio = re.sub(r"\.\.+$", ".", messaggio)
    out = {"ok": True, "messaggio": messaggio, "testo_annulla": TESTI["annulla"], **altro}
    if annulla:
        out["annulla"] = annulla
    return out


def _giorno(parola: str) -> str | None:
    ""
    parola = _senza_accento_giorno(" ".join(str(parola or "").split()))
    try:
        ms = C._quando(parola, C._adesso())
        giorno = C._da_ms(ms).strftime("%Y-%m-%d") if ms else None
    except (C.Errore, ValueError, OverflowError, OSError) as e:

        raise Errore("errore_giorno") from e
    if giorno is not None and not _data_buona(giorno):
        raise Errore("errore_giorno")
    return giorno


def _ids(arg: str) -> list[str]:
    ids = [x for x in arg.split(",") if x]
    if not ids:
        raise Errore("errore_sparita")
    return list(dict.fromkeys(ids))


def _riga(messaggio: str, titoli: dict, ids: list[str]) -> str:
    ""
    if len(ids) != 1:
        return messaggio.rstrip(".")
    return TESTI["riga_esito"].format(esito=messaggio.rstrip("."), titolo=titoli.get(ids[0], ""))


def _azione(chiave: str, n: int) -> str:
    nome = TESTI[f"azione_{chiave}"]
    return nome if n <= 1 else TESTI["azione_tante"].format(azione=nome, n=numero(n))


def _gesto(
    arg: str,
    campo: str,
    valore,
    messaggio: str,
    tante: str,
    annulla: bool,
    azione: str,
    era: dict | None = None,
) -> dict:
    ""

    ids = _ids(arg)
    r = cambia_tante(ids, {campo: valore}, era=era)
    if len(ids) > 1:
        messaggio = tante
    altro = {
        "eventi": r["eventi"],
        "gruppo": r["gruppo"],
        "ids": ids,
        "azione": _azione(azione, len(ids)),
        "riga": _riga(messaggio, r["titoli"], ids),
    }
    if not r["eventi"]:
        altro["riga"] = _riga(TESTI["esito_niente"], r["titoli"], ids)
        if not annulla:


            messaggio = TESTI["esito_niente"]
    if annulla:
        return _esito(TESTI["esito_annullato"], **altro)
    if len(ids) != 1 or campo not in r["prima"][ids[0]]:
        return _esito(messaggio, **altro)
    v = r["prima"][ids[0]][campo]
    indietro = "togli" if v is None else str(v)
    return _esito(messaggio, [campo if campo != "scadenza" else "data", ids[0], indietro], **altro)


def _opzione(resto: list[str], nome: str) -> tuple[list[str], str | None]:
    if nome in resto:
        i = resto.index(nome)
        if i + 1 < len(resto):
            return resto[:i] + resto[i + 2 :], resto[i + 1]
        return resto[:i], None
    return resto, None


def _area_da_scrivere(
    valore: str, da: str | None = None, valori: list[str] | None = None
) -> tuple[str | None, bool]:
    ""



    v = (valore or "").strip()
    if not v or v == SENZA_AREA or v.casefold() == TESTI["senza_area"].casefold():
        return None, False
    aree = Aree(_imp(), valori) if valori is not None else _aree()
    trovata = aree.cerca(v)
    if trovata is None and v.casefold() == "togli":
        return None, False
    if trovata is not None:
        finale = aree.finale(trovata)
        return (None if finale == SENZA_AREA else finale), False
    aid = "a-" + _nuovo_id(6)
    imp = _imp()
    dopo = {"nome": v, "nomi": [v], "tolta": False}
    if imp.get("aree_ordinate"):
        dopo["ordine"] = 1 + max((a.get("ordine") or 0 for a in imp["aree"].values()), default=0)
    _scrivi_impostazione({"voce": "area", "cosa": "area-nuova", "id": aid, "dopo": dopo, "da": da})
    return aid, True


def _con_fuso(giorno: str, hhmm: str) -> str:
    ""
    h, m = (int(x) for x in hhmm.split(":"))
    d = datetime.strptime(giorno, "%Y-%m-%d").replace(hour=h, minute=m, tzinfo=C.FUSO)
    return d.isoformat(timespec="seconds")


def leggi_pianificata(testo: str) -> str | None:
    ""



    t = " ".join(str(testo or "").split())
    if t.casefold() in ("togli", "nessuna", "nessuno"):
        return None
    cal = _calendario_modulo()
    if cal is not None:
        try:
            v = cal.leggi_pianificata(t)
        except Exception as e:  # noqa: BLE001 l'Errore del modulo, o qualunque guasto: la frase è la nostra
            raise Errore("errore_quando") from e
        if v is None or _pianificata_locale(v) is not None:
            return v
        raise Errore("errore_quando")
    m = re.fullmatch(
        r"(\d{4}-\d{2}-\d{2})(?:[T ](\d{1,2}):(\d{2})(?::\d{2})?([+-]\d{2}:?\d{2}|Z)?)?", t
    )
    if m:
        giorno, hh, mm, fuso = m.groups()
        if fuso:
            locale = _momento(t.replace(" ", "T").replace("Z", "+00:00"))
            if locale is None:
                raise Errore("errore_quando")


            try:
                d = datetime.fromisoformat(t.replace(" ", "T").replace("Z", "+00:00"))
                return (
                    d.astimezone(C.FUSO)
                    .replace(second=0, microsecond=0)
                    .isoformat(timespec="seconds")
                )
            except (ValueError, OverflowError):
                return _con_fuso(locale[:10], locale[11:16])
        if not _data_buona(giorno):
            raise Errore("errore_quando")
        if hh is None:
            return giorno
        if int(hh) > 23 or int(mm) > 59:
            raise Errore("errore_quando")
        return _con_fuso(giorno, f"{int(hh):02d}:{mm}")
    pezzi = [x for x in t.casefold().split() if x not in ("alle", "all'", "a")]
    if not pezzi:
        raise Errore("errore_quando")
    parola = _senza_accento_giorno(pezzi[0])
    base = C._adesso()
    if parola == "oggi":
        giorno = base.strftime("%Y-%m-%d")
    elif parola == "domani":
        giorno = (base + timedelta(days=1)).strftime("%Y-%m-%d")
    elif parola == "dopodomani":
        giorno = (base + timedelta(days=2)).strftime("%Y-%m-%d")
    elif parola in _GIORNI_SENZA_ACCENTO:
        avanti = (_GIORNI_SENZA_ACCENTO[parola] - base.weekday()) % 7 or 7
        giorno = (base + timedelta(days=avanti)).strftime("%Y-%m-%d")
    else:
        raise Errore("errore_quando")
    if len(pezzi) == 1:
        return giorno
    m = re.fullmatch(r"(\d{1,2})(?:[:.](\d{2}))?", pezzi[1])
    if len(pezzi) > 2 or not m or int(m.group(1)) > 23 or int(m.group(2) or 0) > 59:
        raise Errore("errore_quando")
    return _con_fuso(giorno, f"{int(m.group(1)):02d}:{m.group(2) or '00'}")


def _in_fila(inizio: str, durate: list[int | None]) -> list[str]:
    ""

    giorno, ora = _pianificata_locale(inizio)
    d = datetime.strptime(f"{giorno}T{ora}", "%Y-%m-%dT%H:%M")
    out = []
    for durata in durate:
        out.append(_con_fuso(d.strftime("%Y-%m-%d"), d.strftime("%H:%M")))
        d += timedelta(minutes=durata or DURATA_SENZA_STIMA)
    if out and _ms_pianificata(inizio) is not None:


        out[0] = inizio
    return out





_CHIAVE = re.compile(r"^\s*([^\s=]*)\s*=(.*)$", re.S)
CHIAVI_NUOVA = ("area", "priorita", "scadenza", "stato", "stima", "pianificata", "inizio",
                "origine_fonte", "origine_id", "origine_url", "se_eliminata")


_FONTE = re.compile(r"[a-z][a-z0-9_-]{0,31}")
ORIGINE_ID_MAX = 200
ORIGINE_URL_MAX = 2000


SCHEMI_ORIGINE = ("http", "https")


def _origine_da(fonte, ident, url) -> dict:
    ""
    fonte = (fonte or "").strip()
    ident = (ident or "").strip()
    if not _FONTE.fullmatch(fonte):
        raise Errore("errore_origine_fonte")
    if not ident or len(ident) > ORIGINE_ID_MAX or _nome_una_riga(ident) != ident or _vuoto(ident):
        raise Errore("errore_origine_id")
    out = {"fonte": fonte, "id": ident}
    if url is not None and url.strip():
        url = url.strip()
        if not _link_buono(url):
            raise Errore("errore_origine_url")
        out["url"] = url
    return out


@functools.lru_cache(maxsize=4096)
def _link_buono_tenuto(url: str) -> bool:
    schema = url.split(":", 1)[0].casefold() if ":" in url else ""
    return not (
        len(url) > ORIGINE_URL_MAX
        or schema not in SCHEMI_ORIGINE
        or not url[len(schema) + 1 :].startswith("//")
        or any(c.isspace() or unicodedata.category(c) in ("Cc", "Cf") for c in url)
    )


_LINK_ASCII = re.compile(r"(?i:https?)://[\x21-\x7e]*")


def _link_buono(url) -> bool:
    ""

    if url.__class__ is not str:
        return False
    if url.isascii():
        return len(url) <= ORIGINE_URL_MAX and _LINK_ASCII.fullmatch(url) is not None
    return _link_buono_tenuto(url)


def _con_origine(eventi: list[dict], fonte: str, ident: str) -> list[str]:
    ""
    out = []
    for e in eventi:
        if e.get("tipo") != "crea":
            continue
        o = (e.get("campi") or {}).get("origine") if isinstance(e.get("campi"), dict) else None
        if (
            isinstance(o, dict)
            and o.get("fonte") == fonte
            and o.get("id") == ident
            and isinstance(e.get("id"), str)
        ):
            out.append(e["id"])
    return out


def _task_dell_origine(eventi: list[dict], fonte: str, ident: str) -> dict | None:
    ""
    ids = _con_origine(eventi, fonte, ident)
    if not ids:
        return None
    tutte = _carica_di(ids, eventi)
    vive = [tutte[i] for i in ids if i in tutte and not tutte[i]["eliminata"]]
    if vive:
        return vive[-1]
    morte = [tutte[i] for i in ids if i in tutte]
    return morte[-1] if morte else None


def origine(fonte: str, ident: str) -> dict:
    ""
    o = _origine_da(fonte, ident, None)
    t = _task_dell_origine(_eventi(), o["fonte"], o["id"])
    if t is None:
        return {"ok": True, "c_e": False, "id": None, "stato": None, "stato_nome": None, "chiusa": False,
                "eliminata": False}
    imp = _imp()
    return {"ok": True, "c_e": True, "id": t["id"], "stato": t["stato"], "stato_nome": _stato_di(imp, t["stato"])["nome"],
            "chiusa": _chiuso(imp, t["stato"]), "eliminata": t["eliminata"]}


def origini(fonte: str) -> dict:
    ""


    fonte = _origine_da(fonte, "x", None)["fonte"]
    eventi = _eventi()
    per_id: dict[str, list[str]] = {}
    for e in eventi:
        if e.get("tipo") != "crea" or not isinstance(e.get("id"), str):
            continue
        o = (e.get("campi") or {}).get("origine") if isinstance(e.get("campi"), dict) else None
        if isinstance(o, dict) and o.get("fonte") == fonte and isinstance(o.get("id"), str):
            per_id.setdefault(o["id"], []).append(e["id"])
    tutte = _carica_di([t for ids in per_id.values() for t in ids], eventi) if per_id else {}
    imp = _imp() if per_id else None
    out = {}
    for ident, ids in per_id.items():
        vive = [tutte[i] for i in ids if i in tutte and not tutte[i]["eliminata"]]
        morte = [tutte[i] for i in ids if i in tutte]
        t = vive[-1] if vive else (morte[-1] if morte else None)
        if t is None:
            continue
        out[ident] = {"id": t["id"], "stato": t["stato"], "stato_nome": _stato_di(imp, t["stato"])["nome"],
                      "chiusa": _chiuso(imp, t["stato"]), "eliminata": t["eliminata"]}
    return {"ok": True, "fonte": fonte, "origini": out}



AREA_MAX = 80


def _nome_area(valore) -> str | None:
    ""
    if _vuoto(valore):
        return None

    nome = _nome_una_riga(str(valore)).rstrip(" .") or _nome_una_riga(str(valore))
    if len(nome) > AREA_MAX:
        raise Errore("errore_area_lunga")
    return nome


def _verbo_nuova(resto: list[str]) -> dict:
    ""



    titolo, campi, da_fuori = resto[0], {}, {}
    if _vuoto(titolo):
        raise Errore("errore_titolo")
    coppie, posizione = [], []
    for x in resto[1:]:
        m = _CHIAVE.match(x)
        (coppie if m else posizione).append(m.groups() if m else x)
    area = None
    if coppie or posizione:
        if len(posizione) == 1 and _PRIO_FORMA.match(posizione[0].strip().casefold()):
            campi["priorita"] = _leggi_priorita(posizione[0])
        elif posizione:
            if len(posizione) > 2:
                raise Errore("errore_valore")
            area = posizione[0]
            if len(posizione) == 2 and posizione[1].strip():
                campi["priorita"] = _leggi_priorita(posizione[1])
        for k, v in coppie:
            k = _piega(k)
            if k not in CHIAVI_NUOVA or not v.strip():
                continue
            if k == "area":
                area = v
            elif k == "priorita":
                campi["priorita"] = _leggi_priorita(v)
            elif k == "scadenza":
                campi["scadenza"] = _giorno(v.strip())
            elif k == "stato":
                sid = _risolvi_stato(_imp(), v)
                if sid is None:
                    raise Errore("errore_stato", elenco=_elenco_stati(_imp()))
                campi["stato"] = sid
            elif k == "stima":
                campi["stima"] = leggi_durata(v)
            elif k.startswith("origine_") or k == "se_eliminata":
                da_fuori[k] = v
            else:
                campi["pianificata"] = leggi_pianificata(v)
    else:
        letto = capisci(titolo)
        if letto["etichette_tutte"]:
            titolo = letto["titolo"]
            if letto["priorita"] is not None:
                campi["priorita"] = letto["priorita"]
            if letto["scadenza"]:
                campi["scadenza"] = letto["scadenza"]
    campi["titolo"] = titolo
    if da_fuori:
        if "origine_fonte" not in da_fuori or "origine_id" not in da_fuori:
            raise Errore(
                "errore_origine_id" if "origine_fonte" in da_fuori else "errore_origine_fonte"
            )
        se_eliminata = (da_fuori.get("se_eliminata") or "").strip().casefold()
        if se_eliminata not in ("", "nuova"):
            raise Errore("errore_valore")
        campi["origine"] = _origine_da(
            da_fuori["origine_fonte"], da_fuori["origine_id"], da_fuori.get("origine_url")
        )
    nome_area = _nome_area(area)
    area_nuova = False
    with _Lucchetto():
        if campi.get("origine"):


            c_era = _task_dell_origine(_eventi(), campi["origine"]["fonte"], campi["origine"]["id"])
            if c_era is not None and not c_era["eliminata"]:
                return _esito(TESTI["esito_origine_c_era"], None, id=c_era["id"], eventi=[], ids=[c_era["id"]],
                              c_era=True, eliminata=False)
            if c_era is not None and se_eliminata != "nuova":
                return {"ok": False, "errore": TESTI["errore_origine_eliminata"], "sparita": False,
                        "id": c_era["id"], "c_era": True, "eliminata": True}
        if nome_area is not None:
            campi["area"], area_nuova = _area_da_scrivere(nome_area)
        tid, eid = _crea_dentro(campi)
    titolo = campi["titolo"].strip()
    return _esito(
        TESTI["esito_nuova"],
        ["elimina", tid],
        id=tid,
        eventi=[eid],
        gruppo=None,
        ids=[tid],
        azione=_azione("nuova", 1),
        riga=_riga(TESTI["esito_nuova"], {tid: titolo}, [tid]),
        area_nuova=area_nuova,
    )


def _elenco_stati(imp: dict) -> str:
    nomi = [s["nome"] for s in _stati_in_ordine(imp)]
    return nomi[0] if len(nomi) == 1 else ", ".join(nomi[:-1]) + " e " + nomi[-1]


def _cambia_scelte(ids: list[str], scegli, da: str | None = None, prepara=None) -> dict:
    ""

    gruppo = _nuovo_id(8) if len(ids) > 1 else None
    with _Lucchetto():
        tutte = _carica_di(ids)
        _controlla(tutte, ids)
        if prepara is not None:
            prepara(tutte)
        prima, eventi, scritti = {}, [], {}
        for tid in ids:
            campi = scegli(tutte[tid])
            if not campi:
                prima[tid] = {}
                continue
            p, eid = _cambia_dentro(tutte, tid, campi, da, gruppo)
            prima[tid] = p
            if eid:
                eventi.append(eid)
                scritti[tid] = campi
        titoli = {tid: tutte[tid]["titolo"] for tid in ids}
    return {"prima": prima, "eventi": eventi, "gruppo": gruppo if len(eventi) > 1 else (gruppo if eventi else None),
            "titoli": titoli, "scritti": scritti}


def _altro_gesto(r: dict, ids: list[str], azione: str, messaggio: str) -> dict:
    altro = {
        "eventi": r["eventi"],
        "gruppo": r["gruppo"],
        "ids": ids,
        "azione": _azione(azione, len(ids)),
        "riga": _riga(messaggio, r["titoli"], ids),
    }
    if not r["eventi"]:
        altro["riga"] = _riga(TESTI["esito_niente"], r["titoli"], ids)
    return altro


def _verbo_fatta(arg: str) -> dict:
    ""
    ids = _ids(arg)
    imp = _imp()
    r = cambia_tante(ids, {"stato": _stato_fatta(imp)})
    messaggio = (
        TESTI["esito_fatta"]
        if len(ids) == 1
        else TESTI["esito_fatte_tante"].format(n=numero(len(ids)))
    )
    vecchio = None
    if len(ids) == 1 and r["eventi"]:

        vecchio = ["stato", ids[0], r["prima"][ids[0]]["stato"]]
    return _esito(messaggio, vecchio, **_altro_gesto(r, ids, "fatta", messaggio))


def _verbo_riapri(arg: str) -> dict:
    ""

    ids = _ids(arg)
    imp = _imp()
    verso = _predefinito(imp)
    r = _cambia_scelte(ids, lambda t: {"stato": verso} if _chiuso(imp, t["stato"]) else None)
    messaggio = (
        TESTI["esito_riaperta"]
        if len(ids) == 1
        else TESTI["esito_riaperte_tante"].format(n=numero(len(ids)))
    )
    return _esito(messaggio, **_altro_gesto(r, ids, "riapri", messaggio))


def _verbo_stato(arg: str, testo: str) -> dict:
    ""

    imp = _imp()
    sid = _risolvi_stato(imp, testo)
    if sid is None:
        raise Errore("errore_stato", elenco=_elenco_stati(imp))
    nome = imp["stati"][sid]["nome"]
    ids = _ids(arg)
    return _gesto(
        arg,
        "stato",
        sid,
        TESTI["esito_stato"].format(nome=nome),
        TESTI["esito_stato_tante"].format(n=numero(len(ids)), nome=nome),
        False,
        "stato",
    )


def _verbo_stima(arg: str, testo: str) -> dict:
    ""
    quanti = len(_ids(arg))
    m = leggi_durata(testo)
    if m is None:
        return _gesto(arg, "stima", None, TESTI["esito_stima_tolta"],
                      TESTI["esito_stima_tolta_tante"].format(n=numero(quanti)), False, "stima")
    quanto = stima_frase(m)
    return _gesto(arg, "stima", m, TESTI["esito_stima"].format(quanto=quanto),
                  TESTI["esito_stima_tante"].format(n=numero(quanti), quanto=quanto), False, "stima")


def _verbo_area(arg: str, valore: str, era: str | None) -> dict:
    ""

    ids = _ids(arg)
    if _vuoto(valore):
        raise Errore("errore_valore")
    valore = _nome_area(valore) if valore.strip() not in (SENZA_AREA,) else valore.strip()
    gruppo = _nuovo_id(8) if len(ids) > 1 else None
    with _Lucchetto():

        ev = _eventi()
        tutte = _carica_di(ids, ev)
        _controlla(tutte, ids)
        valori = _valori_area(ev)
        aree = Aree(_imp(), valori)
        if era is not None:
            for tid in ids:
                ora = aree.finale(tutte[tid].get("area"))
                if era not in (ora, aree.nome(ora)):
                    raise Errore("errore_intanto", intanto=aree.nome(ora))
        aid, nuova = _area_da_scrivere(valore, valori=valori)
        if nuova:
            aree = Aree(_imp(), valori)
        prima, eventi = {}, []
        for tid in ids:
            if aree.finale(tutte[tid].get("area")) == (aid or SENZA_AREA):
                prima[tid] = {}
                continue
            p, eid = _cambia_dentro(tutte, tid, {"area": aid}, None, gruppo)
            prima[tid] = p
            if eid:
                eventi.append(eid)
        titoli = {tid: tutte[tid]["titolo"] for tid in ids}
        nome = aree.nome(aid or SENZA_AREA)
    if aid is None:
        messaggio = (
            TESTI["esito_area_tolta_via"]
            if len(ids) == 1
            else TESTI["esito_area_tolta_via_tante"].format(n=numero(len(ids)))
        )
    elif nuova:
        messaggio = (TESTI["esito_area_creata"].format(area=nome) if len(ids) == 1
                     else TESTI["esito_area_creata_tante"].format(n=numero(len(ids)), area=nome))
    else:
        messaggio = (TESTI["esito_area"].format(area=nome) if len(ids) == 1
                     else TESTI["esito_area_tante"].format(n=numero(len(ids)), area=nome))
    r = {"eventi": eventi, "gruppo": gruppo if eventi else None, "titoli": titoli}
    vecchio = None
    if len(ids) == 1 and "area" in prima[ids[0]]:
        v = prima[ids[0]]["area"]
        vecchio = ["area", ids[0], v if v else SENZA_AREA]
    return _esito(messaggio, vecchio, area_id=aid or SENZA_AREA, area_nuova=nuova,
                  **_altro_gesto(r, ids, "area", messaggio))


def _verbo_pianifica(resto: list[str]) -> dict:
    ""



    resto, durata_testo = _opzione(resto, "--durata")
    if len(resto) < 2:
        raise Errore("errore_comando")
    ids = _ids(resto[0])
    valore = leggi_pianificata(" ".join(resto[1:]))

    durata_min = leggi_durata(durata_testo) if durata_testo is not None else None
    con_ora = valore is not None and _pianificata_locale(valore)[1] is not None
    fila: dict[str, str] = {}

    def scegli(t):
        campi = {"pianificata": valore}
        if con_ora:
            if not fila:

                tutte = scegli.tutte
                durate = [durata_min or tutte[x].get("stima") for x in ids]
                fila.update(zip(ids, _in_fila(valore, durate), strict=True))
            campi["pianificata"] = fila[t["id"]]
        if durata_testo is not None:
            campi["stima"] = durata_min
        return campi

    r = _cambia_scelte(ids, scegli, prepara=lambda tutte: setattr(scegli, "tutte", tutte))
    oggi = C._adesso()
    if valore is None:
        messaggio = (TESTI["esito_pianificata_tolta"] if len(ids) == 1
                     else TESTI["esito_pianificata_tolta_tante"].format(n=numero(len(ids))))
    else:
        parole = _pianificata_parole(valore, oggi)
        passato = _inizio_passato(valore, None, oggi, blocco=False)
        if len(ids) == 1 and passato:
            chiave = "esito_pianificata_passata" if con_ora else "esito_pianificata_giorno_passato"
            messaggio = TESTI[chiave].format(quando=parole)
        elif len(ids) == 1:
            messaggio = TESTI["esito_pianificata"].format(quando=parole)
        else:
            chiave = "esito_pianificate_fila" if con_ora else "esito_pianificate_giorno"
            messaggio = TESTI[chiave].format(n=numero(len(ids)), quando=parole)
    vecchio = None
    if len(ids) == 1 and r["eventi"]:
        p = r["prima"][ids[0]]
        vecchio = ["pianifica", ids[0], p.get("pianificata") or "togli"]
        if "stima" in p:
            vecchio += ["--durata", str(p["stima"]) if p["stima"] else "togli"]
    pianificate = [{"id": tid, "pianificata": c["pianificata"]} for tid, c in r["scritti"].items()]
    return _esito(
        messaggio, vecchio, pianificate=pianificate, **_altro_gesto(r, ids, "pianifica", messaggio)
    )





def commenta(ids: list[str], testo: str, da: str | None = None, via: str = "testo",
             audio: str | None = None) -> dict:
    ""

    testo = (testo or "").strip()
    if _vuoto(testo):

        raise Errore("errore_commento_vuoto")
    gruppo = _nuovo_id(8) if len(ids) > 1 else None
    with _Lucchetto():
        tutte = _carica_di(ids)
        _controlla(tutte, ids)
        eventi = []
        for tid in ids:
            e = {
                "t": _ora(),
                "id": tid,
                "tipo": "commento",
                "da": _chi(da),
                "testo": testo,
                "via": via,
            }
            if audio:
                e["audio"] = audio
            if gruppo:
                e["gruppo"] = gruppo
            eventi.append(_scrivi(e))
        titoli = {tid: tutte[tid]["titolo"] for tid in ids}
    return {"eventi": eventi, "gruppo": gruppo, "titoli": titoli}


def _verbo_commenta(arg: str, testo: str) -> dict:
    ids = _ids(arg)
    r = commenta(ids, testo)
    m = TESTI["esito_commento"]
    return _esito(m, commento=r["eventi"][0], eventi=r["eventi"], gruppo=r["gruppo"], ids=ids,
                  azione=_azione("commento", len(ids)), riga=_riga(m, r["titoli"], ids))


def _verbo_commento_togli(eid: str) -> dict:
    with _Lucchetto():
        tutti = _eventi()
        e = next((x for x in tutti if x.get("eid") == eid and x.get("tipo") == "commento"), None)
        if e is None:
            raise Errore("errore_commento_sparito")
        tutte = _carica_di([e["id"]] if isinstance(e.get("id"), str) else [], tutti)
        t = tutte.get(e.get("id"))
        if t is not None and t["eliminata"]:


            raise Errore("errore_sparita")
        if t is None or eid not in t.get("commenti", {}):
            raise Errore("errore_commento_sparito")
        nuovo = _scrivi(
            {
                "t": _ora(),
                "id": t["id"],
                "tipo": "commento_tolto",
                "da": _chi(None),
                "commento": eid,
            }
        )
    m = TESTI["esito_commento_tolto"]
    return _esito(m, eventi=[nuovo], ids=[t["id"]], azione=_azione("commento", 1),
                  riga=_riga(m, {t["id"]: t["titolo"]}, [t["id"]]))


def _valore_storia(campo: str, v, imp: dict, aree: Aree, oggi: datetime) -> str:
    if campo == "stato":
        return _stato_di(imp, v)["nome"]
    if campo == "priorita":
        return PRIORITA.get(v, str(v))
    if campo == "scadenza":
        return C._quando_parole(datetime.strptime(v, "%Y-%m-%d"), oggi)
    if campo == "stima":
        return stima_frase(v)
    if campo == "area":
        return aree.nome(aree.finale(v))
    if campo == "pianificata":
        return _pianificata_parole(v, oggi)
    return str(v)


def _frase_storia(e: dict, imp: dict, aree: Aree, oggi: datetime) -> str:
    tipo = e.get("tipo")
    if tipo == "crea":
        return TESTI["storia_nata"]
    if tipo == "elimina":
        return TESTI["storia_eliminata"]
    if tipo == "ripristina":
        return TESTI["storia_ripristinata"]
    if tipo == "commento_tolto":
        return TESTI["storia_commento_tolto"]
    if tipo == "commento_rimesso":
        return TESTI["storia_commento_rimesso"]
    frasi = []
    campi = e.get("campi") if isinstance(e.get("campi"), dict) else {}
    for k, v in _sani(campi).items():
        if k in ("chiusa", "origine"):
            continue
        if k == "descrizione":
            frasi.append(TESTI["storia_descrizione"])
        elif k == "titolo":
            frasi.append(TESTI["storia_titolo"].format(valore=v))
        elif v in (None, "") and k in ("scadenza", "stima", "area", "pianificata"):
            frasi.append(TESTI[f"storia_{k}_tolta"])
        elif k in ("stato", "priorita", "scadenza", "stima", "area", "pianificata"):
            frasi.append(TESTI[f"storia_{k}"].format(valore=_valore_storia(k, v, imp, aree, oggi)))
    return ". ".join(frasi)


def descrizione_intera(tid: str) -> dict:
    ""

    t = _carica_di([tid], _eventi()).get(tid)
    if t is None:
        raise Errore("errore_sparita")
    return {"ok": True, "id": tid, "titolo": t["titolo"], "descrizione": _mostrata(t)}


def commenti(tid: str) -> dict:
    ""


    oggi = C._adesso()
    ev = _eventi()
    tutte = _carica_di([tid], ev)
    t = tutte.get(tid)
    if t is None:
        raise Errore("errore_sparita")
    imp = _imp()
    aree = Aree(imp, _valori_area(ev))
    visibili = set(t.get("commenti", {}))
    lista, cambi = [], []
    posto = {}
    for i, e in enumerate(ev):
        if e.get("id") != tid or not isinstance(e.get("t"), str):
            continue

        posto[id(e)] = (_ms_evento(e, e["t"]), i)
        chi = _chi_ha(e.get("da"))
        if e.get("tipo") == "commento" and e.get("eid") in visibili:
            audio = e.get("audio")
            via = e.get("via") or "testo"
            lista.append(
                {
                    "eid": e["eid"],
                    "t": e["t"],
                    "quando": _quando_alle(e["t"], oggi),
                    "testo": e.get("testo") or "",
                    "via": via,
                    "chi": chi,
                    "da_parole": TESTI["detto_a_voce"] if via == "voce" else (
                        TESTI["da_una_richiesta"] if chi == "voce" else
                        TESTI["chi_telefono"] if chi == "telefono" else
                        TESTI["chi_spunto"] if chi == "spunto" else TESTI["scritto_da_te"]),
                    "audio": str(CARTELLA / audio) if audio and (CARTELLA / audio).is_file() else "",
                    "_o": posto[id(e)],
                }
            )
        elif e.get("tipo") in (
            "crea",
            "cambia",
            "elimina",
            "ripristina",
            "commento_tolto",
            "commento_rimesso",
        ):
            cosa = _frase_storia(e, imp, aree, oggi)
            if not cosa:
                continue
            cambi.append(
                {"eid": e.get("eid"), "t": e["t"], "quando": _quando_alle(e["t"], oggi), "tipo": e.get("tipo"),
                 "cosa": cosa, "chi": chi, "chi_parole": TESTI[f"chi_{chi}"], "_o": posto[id(e)]}
            )
    filo = sorted([{**c, "genere": "commento"} for c in lista] + [{**c, "genere": "cambio"} for c in cambi],
                  key=lambda x: x["_o"])
    for x in (*lista, *cambi, *filo):
        x.pop("_o", None)
    return {"ok": True, "id": tid, "titolo": t["titolo"], "commenti": lista, "cambi": cambi, "filo": filo,
            "vuoto": TESTI["commenti_vuoto"]}


def _verbo_segna(arg: str, tipo: str, annulla_vecchio: bool) -> dict:
    ids = _ids(arg)
    r = _segna_tante(ids, tipo)
    if tipo == "elimina":
        messaggio = (
            TESTI["esito_eliminata"]
            if len(ids) == 1
            else TESTI["esito_eliminate_tante"].format(n=numero(len(ids)))
        )
    else:
        messaggio = (
            TESTI["esito_ripristinata"]
            if len(ids) == 1
            else TESTI["esito_ripristinate_tante"].format(n=numero(len(ids)))
        )
    if annulla_vecchio:
        messaggio = TESTI["esito_annullato"]

    altro = _altro_gesto(
        {**r, "gruppo": r["gruppo"] if r["eventi"] else None}, ids, tipo, messaggio
    )
    vecchio = (
        ["ripristina", ids[0]]
        if tipo == "elimina" and len(ids) == 1 and not annulla_vecchio and r["eventi"]
        else None
    )
    return _esito(messaggio, vecchio, **altro)


def _attivi_del_gruppo(chiave: str) -> list[str]:
    ""

    tutti = _eventi()
    figli: dict[str, list[str]] = {}
    for e in tutti:
        if isinstance(e.get("annulla"), str) and isinstance(e.get("eid"), str):
            figli.setdefault(e["annulla"], []).append(e["eid"])

    def attivo(eid: str, n: int = 0) -> bool:
        return n > 1000 or not any(attivo(f, n + 1) for f in figli.get(eid, ()))

    return [
        e["eid"]
        for e in tutti
        if isinstance(e.get("eid"), str)
        and not e.get("annulla")
        and chiave in (e.get("gruppo"), e.get("una_volta"))
        and attivo(e["eid"])
    ]


def _verbo_annulla(eids: list[str]) -> dict:
    if eids[:1] == ["--gruppo"]:


        if len(eids) != 2:
            raise Errore("errore_comando")
        eids = _attivi_del_gruppo(eids[1])
        if not eids:
            return _esito(
                TESTI["esito_niente"], eventi=[], ids=[], riga=TESTI["esito_niente"].rstrip(".")
            )
    r = annulla(eids)
    messaggio = TESTI["esito_rifatto"] if r["rifare"] else TESTI["esito_annullato"]
    return _esito(
        messaggio,
        eventi=r["eventi"],
        ids=r["ids"],
        riga=_riga(messaggio, r["titoli"], r["ids"]),
    )





COLORE_DI_TIPO = {
    "da_fare": "grigio",
    "in_corso": "blu",
    "aspetta": "giallo",
    "fatta": "verde",
    "non_serve": "grigio",
}
_ORA_HHMM = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def _valida_imposta(chiave: str, valore, attuale):
    ""
    if chiave == "veloci_minuti":

        m = leggi_durata(str(valore)) if isinstance(valore, str | float) else valore
        if type(m) is not int or not 1 <= m <= 24 * 60:
            raise Errore("errore_impostazione_valore")
        return m
    if not isinstance(valore, dict):
        raise Errore("errore_impostazione_valore")
    out = {**attuale, **valore}
    if chiave == "urgenti":
        if set(out) - {"p1", "giorni_prima", "giorni_dopo"} or not isinstance(out["p1"], bool):
            raise Errore("errore_impostazione_valore")
        for k, alto in (("giorni_prima", 60), ("giorni_dopo", 365)):
            if type(out[k]) is not int or not 0 <= out[k] <= alto:
                raise Errore("errore_impostazione_valore")
        return out
    if chiave == "settimana":
        if set(out) - {"inizio", "giorni", "dalle", "alle", "giornata_minuti"}:
            raise Errore("errore_impostazione_valore")
        g = out["giorni"]
        if (type(out["inizio"]) is not int or not 0 <= out["inizio"] <= 6 or not isinstance(g, list) or not g
                or any(type(x) is not int or not 0 <= x <= 6 for x in g) or len(set(g)) != len(g)):
            raise Errore("errore_impostazione_valore")
        if not all(isinstance(out[k], str) and _ORA_HHMM.match(out[k]) for k in ("dalle", "alle")):
            raise Errore("errore_impostazione_valore")
        if out["dalle"] >= out["alle"]:
            raise Errore("errore_impostazione_valore")
        m = out["giornata_minuti"]
        m = leggi_durata(m, 480) if isinstance(m, str) else m
        if type(m) is not int or not 30 <= m <= 24 * 60:
            raise Errore("errore_impostazione_valore")
        out["giornata_minuti"] = m
        out["giorni"] = sorted(g)
        return out
    raise Errore("errore_impostazione")


def _nome_impostazione(valore, troppo: str) -> str:
    ""

    if _vuoto(valore):
        raise Errore("errore_nome_vuoto")
    nome = _nome_una_riga(str(valore)).rstrip(" .") or _nome_una_riga(str(valore))
    if _vuoto(nome):
        raise Errore("errore_nome_vuoto")
    if len(nome) > AREA_MAX:
        raise Errore(troppo)
    return nome


def _nome_libero_stato(imp: dict, nome: str, mio: str | None = None) -> None:
    ""



    chiave = _chiave_area(nome)
    for s in _stati_in_ordine(imp, True):
        if s["id"] == mio:
            continue
        if _chiave_area(s["nome"]) == chiave and s.get("tolto"):

            raise Errore("errore_stato_nome_tolto", stato_che_era=s["id"])
        if _chiave_area(s["nome"]) == chiave or s["id"].casefold() == chiave:
            raise Errore("errore_stato_nome_usato")
        if chiave in {_chiave_area(n) for n in s.get("nomi_prima") or []}:
            raise Errore("errore_stato_era_di", nome=s["nome"], stato_che_era=s["id"])


def _regole_stati(imp: dict, cambiato: dict) -> None:
    ""
    stati = {**imp["stati"], cambiato["id"]: cambiato}
    vivi = [s for s in stati.values() if not s.get("tolto")]
    if not any(s["tipo"] == "da_fare" for s in vivi) or not any(s["tipo"] == "fatta" for s in vivi):
        raise Errore("errore_ultimo_stato")


def _segno_libero(imp: dict, tipo: str, mio: str | None = None) -> str:
    usati = {s["segno"] for s in _stati_in_ordine(imp) if s["tipo"] == tipo and s["id"] != mio}
    return next((x for x in SEGNI[tipo] if x not in usati), SEGNI[tipo][0])


def _task_nello_stato(
    tutte: dict, sid: str, solo_aperte: bool, imp: dict, eliminate: bool = False
) -> list[dict]:
    return [
        t for t in tutte.values()
        if (eliminate or not t["eliminata"]) and t["stato"] == sid and (not solo_aperte or not _chiuso(imp, t["stato"]))
    ]


def _esito_imp(chiave: str, annulla: list[str] | None, **altro) -> dict:
    messaggio = altro.pop("messaggio", None) or TESTI[chiave]
    return _esito(messaggio, annulla, azione=TESTI["azione_impostazioni"], **altro)


def _riga_imp(voce: str, cosa: str, ident: str | None, dopo, prima=None) -> str:
    return _scrivi_impostazione(_riga_imp_di(voce, cosa, ident, dopo, prima))


def _riga_imp_di(voce: str, cosa: str, ident: str | None, dopo, prima=None) -> dict:
    riga = {
        "voce": voce,
        "cosa": cosa,
        "dopo": dopo,
        "da": "impostazioni" if not os.environ.get("SB_ATTIVITA_DA") else None,
    }
    if ident is not None:
        riga["id"] = ident
    if prima is not None:
        riga["prima"] = prima
    return riga


def _verbi_stato(verbo: str, resto: list[str], tutte: dict, imp: dict) -> dict:
    if verbo == "stato-nuovo" and len(resto) >= 2:
        nome, tipo = _nome_impostazione(resto[0], "errore_stato_lungo"), resto[1]
        if tipo not in TIPI:
            raise Errore("errore_tipo")
        _nome_libero_stato(imp, nome)
        sid = "s-" + _nuovo_id(6)
        ordine = [s["id"] for s in _stati_in_ordine(imp, True)]
        dopo_id = resto[2] if len(resto) > 2 and resto[2] in imp["stati"] else None
        if dopo_id is None:
            stesso = [s["id"] for s in _stati_in_ordine(imp, True) if s["tipo"] == tipo]
            if stesso:
                dopo_id = stesso[-1]
            elif not _chiuso_tipo(tipo):
                aperti = [
                    s["id"] for s in _stati_in_ordine(imp, True) if not _chiuso_tipo(s["tipo"])
                ]
                dopo_id = aperti[-1] if aperti else None
        posto = ordine.index(dopo_id) + 1 if dopo_id in ordine else len(ordine)
        ordine.insert(posto, sid)

        _scrivi_impostazioni([
            _riga_imp_di("stato", verbo, sid, {"nome": nome, "tipo": tipo, "segno": _segno_libero(imp, tipo),
                                               "colore": COLORE_DI_TIPO[tipo], "ordine": posto, "tolto": False,
                                               "in": None, "nomi_prima": []}),
            _riga_imp_di("stati_ordine", verbo, None, ordine),
        ])
        return _esito_imp("esito_stato_nuovo", ["stato-togli", sid], id=sid)
    if verbo == "stato-nuovo":
        raise Errore("errore_tipo")
    if verbo == "stati-ordine" or verbo == "stato-ordine":
        if not resto:
            raise Errore("errore_comando")
        prima = [s["id"] for s in _stati_in_ordine(imp, True)]
        voluto = [x for x in dict.fromkeys(resto[0].split(",")) if x in imp["stati"]]
        nuovo = _fila_stati(voluto, prima, imp["stati"])
        if nuovo == prima:
            return _esito_imp("esito_niente", None)
        _riga_imp("stati_ordine", "stato-ordine", None, nuovo, prima)
        return _esito_imp("esito_stati_ordine", ["stato-ordine", ",".join(prima)])
    if not resto:
        raise Errore("errore_comando")
    s = imp["stati"].get(resto[0])
    if s is None:
        raise Errore("errore_stato", elenco=_elenco_stati(imp))
    sid = s["id"]
    if verbo == "stato-nome" and len(resto) == 2:
        nome = _nome_impostazione(resto[1], "errore_stato_lungo")
        if nome == s["nome"]:
            return _esito_imp("esito_niente", None, id=sid)
        _nome_libero_stato(imp, nome, sid)
        nomi = [
            x
            for x in dict.fromkeys([*(s.get("nomi_prima") or []), s["nome"]])
            if _chiave_area(x) != _chiave_area(nome)
        ]
        _riga_imp("stato", verbo, sid, {"nome": nome, "nomi_prima": nomi}, {"nome": s["nome"]})
        return _esito_imp("esito_stato_nome", ["stato-nome", sid, s["nome"]], id=sid)
    if verbo == "stato-tipo" and len(resto) in (2, 3):
        tipo = resto[1]
        if tipo not in TIPI:
            raise Errore("errore_tipo")
        if tipo == s["tipo"]:
            return _esito_imp("esito_niente", None, id=sid)


        dentro = _task_nello_stato(tutte, sid, False, imp, eliminate=True)
        if _chiuso_tipo(tipo) != _chiuso_tipo(s["tipo"]) and dentro:
            vive = [t for t in dentro if not t["eliminata"]]
            if not vive:
                raise Errore("errore_tipo_con_eliminate", n=len(dentro))
            raise Errore("errore_tipo_con_task", n=len(vive))
        segno = resto[2] if len(resto) == 3 else None
        if segno is not None and segno not in SEGNI[tipo]:
            raise Errore("errore_segno")
        if segno is not None and any(
            x["segno"] == segno and x["tipo"] == tipo and x["id"] != sid
            for x in _stati_in_ordine(imp)
        ):
            raise Errore("errore_segno_usato")
        if segno is None:
            segno = s["segno"] if s["segno"] in SEGNI[tipo] else _segno_libero(imp, tipo, sid)
        _regole_stati(imp, {**s, "tipo": tipo})
        _riga_imp(
            "stato",
            verbo,
            sid,
            {"tipo": tipo, "segno": segno},
            {"tipo": s["tipo"], "segno": s["segno"]},
        )
        return _esito_imp("esito_stato_tipo", ["stato-tipo", sid, s["tipo"], s["segno"]], id=sid)
    if verbo == "stato-segno" and len(resto) == 3:
        segno, colore = resto[1], resto[2]
        if segno not in SEGNI[s["tipo"]]:
            raise Errore("errore_segno")
        if colore not in COLORI:
            raise Errore("errore_colore")
        if any(
            x["segno"] == segno and x["tipo"] == s["tipo"] and x["id"] != sid
            for x in _stati_in_ordine(imp)
        ):
            raise Errore("errore_segno_usato")
        if (segno, colore) == (s["segno"], s["colore"]):
            return _esito_imp("esito_niente", None, id=sid)
        _riga_imp(
            "stato",
            verbo,
            sid,
            {"segno": segno, "colore": colore},
            {"segno": s["segno"], "colore": s["colore"]},
        )

        chiave = "esito_stato_colore" if segno == s["segno"] else "esito_stato_segno"
        return _esito_imp(chiave, ["stato-segno", sid, s["segno"], s["colore"]], id=sid)
    if verbo == "stato-predefinito" and len(resto) == 1:
        if s.get("tolto") or _chiuso_tipo(s["tipo"]):
            raise Errore("errore_predefinito")
        prima = imp.get("predefinito") or _predefinito(imp)
        if prima == sid:
            return _esito_imp("esito_niente", None, id=sid)
        _riga_imp("predefinito", verbo, None, sid, prima)
        return _esito_imp("esito_stato_predefinito", ["stato-predefinito", prima], id=sid,
                          messaggio=TESTI["esito_stato_predefinito"].format(nome=s["nome"]))
    if verbo == "stato-togli":
        resto2, dove = _opzione(resto, "--in")
        if s.get("tolto"):
            return _esito_imp("esito_niente", None, id=sid)
        _regole_stati(imp, {**s, "tolto": True})
        aperte = _task_nello_stato(tutte, sid, True, imp)
        destinazione = None
        if dove is not None:
            destinazione = _risolvi_stato(imp, dove)
            if destinazione is None or destinazione == sid:
                raise Errore("errore_stato", elenco=_elenco_stati(imp))
        if aperte and destinazione is None:
            raise Errore("errore_stato_con_task", n=len(aperte))
        gruppo = _nuovo_id(8) if len(aperte) > 1 else None
        eventi = []
        for t in aperte:
            _, eid = _cambia_dentro(tutte, t["id"], {"stato": destinazione}, "impostazioni", gruppo)
            if eid:
                eventi.append(eid)
        _riga_imp(
            "stato",
            verbo,
            sid,
            {"tolto": True, "in": destinazione},
            {"tolto": False, "in": s.get("in")},
        )
        inverso = ["stato-rimetti", sid] + (["--eventi", ",".join(eventi)] if eventi else [])
        if eventi:
            nome = imp["stati"][destinazione]["nome"]
            return _esito_imp("esito_stato_tolto", inverso, id=sid, eventi=eventi, spostate=len(eventi),
                              messaggio=TESTI["esito_stato_tolto_spostate"].format(n=numero(len(eventi)), nome=nome))
        return _esito_imp("esito_stato_tolto", inverso, id=sid, eventi=[], spostate=0)
    if verbo == "stato-rimetti":
        resto2, eventi = _opzione(resto, "--eventi")
        if not s.get("tolto"):
            return _esito_imp("esito_niente", None, id=sid)
        rimessi = []
        if eventi:

            rimessi = _annulla_dentro([x for x in eventi.split(",") if x], "impostazioni")["eventi"]
        dove = s.get("in")
        _riga_imp("stato", verbo, sid, {"tolto": False, "in": None}, {"tolto": True, "in": dove})
        inverso = ["stato-togli", sid] + (["--in", dove] if dove and eventi else [])
        return _esito_imp("esito_stato_rimesso", inverso, id=sid, eventi=rimessi)
    raise Errore("errore_comando")


def _conta_aree_vive(tutte: dict, imp: dict, aree: Aree) -> dict[str, int]:
    ""
    conta: dict[str, int] = {}
    for t in tutte.values():
        if not t["eliminata"] and not _chiuso(imp, t["stato"]):
            a = aree.finale(t.get("area"))
            conta[a] = conta.get(a, 0) + 1
    aree.con_task = {aree.finale(t.get("area")) for t in tutte.values() if not t["eliminata"]}
    return conta


def _verbi_area(verbo: str, resto: list[str], tutte: dict, imp: dict, aree: Aree) -> dict:
    def libero(nome: str, mio: str | None = None) -> None:
        if _chiave_area(nome) in (_chiave_area(TESTI["senza_area"]), SENZA_AREA, "togli"):
            raise Errore("errore_area_nome_usato")
        c = aree.cerca(nome)
        if c is not None and c != mio:
            d = aree.defs[c]

            if _chiave_area(d["nome"]) == _chiave_area(nome):
                raise Errore("errore_area_nome_usato", area_che_era=c, nome_di=d["nome"])
            raise Errore(
                "errore_area_era_di", nome=aree.nome(aree.finale(c)), area_che_era=aree.finale(c)
            )

    def quante(aid: str, solo_aperte: bool = False) -> int:
        return sum(
            1 for t in tutte.values()
            if not t["eliminata"] and aree.finale(t.get("area")) == aid and (not solo_aperte or not _chiuso(imp, t["stato"]))
        )

    if verbo == "area-nuova" and resto:
        nome = _nome_impostazione(resto[0], "errore_area_lunga")
        libero(nome)
        aid = "a-" + _nuovo_id(6)
        dopo = {"nome": nome, "nomi": [nome], "tolta": False}
        if imp.get("aree_ordinate"):
            dopo["ordine"] = 1 + max(
                (a.get("ordine") or 0 for a in imp["aree"].values()), default=0
            )
        _riga_imp("area", verbo, aid, dopo)
        return _esito_imp("esito_area_aggiunta", ["area-togli", aid], id=aid)
    if verbo == "area-ordine" and resto:



        conta = _conta_aree_vive(tutte, imp, aree)
        prima = [d["id"] for d in aree.visibili(conta)]
        if resto[0] == "-":
            if not imp.get("aree_ordinate"):
                return _esito_imp("esito_niente", None)
            _riga_imp("aree_ordine", verbo, None, None, prima)
            return _esito_imp("esito_aree_ordine", ["area-ordine", ",".join(prima)])
        voluto = [x for x in dict.fromkeys(resto[0].split(",")) if x in aree.defs]
        if not voluto:
            raise Errore("errore_area")
        nuovo = voluto + [x for x in prima if x not in voluto]
        if nuovo == prima and imp.get("aree_ordinate"):
            return _esito_imp("esito_niente", None)
        _riga_imp("aree_ordine", verbo, None, nuovo, prima)
        inverso = (
            ["area-ordine", ",".join(prima)] if imp.get("aree_ordinate") else ["area-ordine", "-"]
        )
        return _esito_imp("esito_aree_ordine", inverso)
    if not resto:
        raise Errore("errore_comando")
    aid = aree.cerca(resto[0])
    if aid is None:
        raise Errore("errore_area")
    d = aree.defs[aid]
    if verbo == "area-nome" and len(resto) == 2:
        nome = _nome_impostazione(resto[1], "errore_area_lunga")
        if nome == d["nome"]:
            return _esito_imp("esito_niente", None, id=aid)
        libero(nome, aid)
        nomi = list(dict.fromkeys([*d["nomi"], d["nome"], nome]))
        _riga_imp("area", verbo, aid, {"nome": nome, "nomi": nomi}, {"nome": d["nome"]})
        return _esito_imp("esito_vista_nome", ["area-nome", aid, d["nome"]], id=aid)
    if verbo == "area-unisci" and len(resto) == 2:
        dove = aree.cerca(resto[1])
        if dove is None or aree.defs[dove].get("tolta"):
            raise Errore("errore_area")
        if dove == aid:
            raise Errore("errore_area_unisci_se_stessa")
        if aree.finale(dove) == aid:
            raise Errore("errore_area_giro")
        n = quante(aid)
        _riga_imp("area", verbo, aid, {"unita_in": dove}, {"unita_in": d.get("unita_in")})
        return _esito_imp("esito_area_unita", ["area-separa", aid], id=aid, quante=n,
                          messaggio=TESTI["esito_area_unita"].format(nome=aree.nome(aree.finale(dove)), n=numero(n)))
    if verbo == "area-separa" and len(resto) == 1:
        if not d.get("unita_in"):
            return _esito_imp("esito_niente", None, id=aid)
        _riga_imp("area", verbo, aid, {"unita_in": None}, {"unita_in": d["unita_in"]})

        return _esito_imp("esito_area_separata", ["area-unisci", aid, d["unita_in"]], id=aid,
                          messaggio=TESTI["esito_area_separata"].format(nome=aree.nome(aid)))
    if verbo == "area-togli":
        resto2, dove = _opzione(resto, "--in")
        senza = "--senza" in resto2
        if d.get("tolta"):
            return _esito_imp("esito_niente", None, id=aid)
        n = quante(aid)
        prima = {"tolta": False, "unita_in": d.get("unita_in"), "senza": bool(d.get("senza"))}
        if dove is not None:
            dest = aree.cerca(dove)
            if dest is None or aree.defs[dest].get("tolta"):
                raise Errore("errore_area")
            if dest == aid or aree.finale(dest) == aid:
                raise Errore("errore_area_unisci_se_stessa")
            _riga_imp(
                "area", verbo, aid, {"tolta": True, "unita_in": dest, "prima_togli": prima}, prima
            )
            return _esito_imp("esito_area_tolta_in", ["area-rimetti", aid], id=aid, quante=n,
                              messaggio=TESTI["esito_area_tolta_in"].format(nome=aree.nome(aree.finale(dest))))
        if senza:
            _riga_imp(
                "area", verbo, aid, {"tolta": True, "senza": True, "prima_togli": prima}, prima
            )
            return _esito_imp("esito_area_tolta_senza", ["area-rimetti", aid], id=aid, quante=n)
        if n:
            raise Errore("errore_area_con_task", n=n)
        _riga_imp("area", verbo, aid, {"tolta": True, "prima_togli": prima}, prima)
        return _esito_imp("esito_area_tolta", ["area-rimetti", aid], id=aid, quante=0)
    if verbo == "area-rimetti" and len(resto) == 1:
        if not d.get("tolta"):
            return _esito_imp("esito_niente", None, id=aid)
        pt = d.get("prima_togli") or {}
        dopo = {"tolta": False, "unita_in": pt.get("unita_in"), "senza": bool(pt.get("senza"))}
        _riga_imp(
            "area",
            verbo,
            aid,
            dopo,
            {"tolta": True, "unita_in": d.get("unita_in"), "senza": d.get("senza")},
        )
        inverso = ["area-togli", aid]
        if d.get("senza"):
            inverso.append("--senza")
        elif d.get("unita_in") and d.get("unita_in") != pt.get("unita_in"):
            inverso += ["--in", d["unita_in"]]
        return _esito_imp("esito_area_rimessa", inverso, id=aid)
    if verbo == "area-colore" and len(resto) == 2:
        colore = None if resto[1] in ("togli", "") else resto[1]
        if colore is not None and colore not in COLORI:
            raise Errore("errore_colore")
        if colore == d.get("colore"):
            return _esito_imp("esito_niente", None, id=aid)
        _riga_imp("area", verbo, aid, {"colore": colore}, {"colore": d.get("colore")})
        return _esito_imp(
            "esito_area_colore", ["area-colore", aid, d.get("colore") or "togli"], id=aid
        )
    raise Errore("errore_comando")


def _verbo_stato_da_area(resto: list[str], tutte: dict, imp: dict, aree: Aree) -> dict:
    ""

    if len(resto) != 2:
        raise Errore("errore_comando")
    aid = aree.cerca(resto[0])
    if aid is None:
        raise Errore("errore_area")
    aid = aree.finale(aid)
    sid = _risolvi_stato(imp, resto[1])
    if sid is None:
        raise Errore("errore_stato", elenco=_elenco_stati(imp))
    scelte = [
        t for t in tutte.values()
        if not t["eliminata"] and not _chiuso(imp, t["stato"]) and aree.finale(t.get("area")) == aid
        and t["stato"] != sid
    ]
    gruppo = _nuovo_id(8) if len(scelte) > 1 else None
    eventi = []
    for t in scelte:
        _, eid = _cambia_dentro(tutte, t["id"], {"stato": sid}, "impostazioni", gruppo)
        if eid:
            eventi.append(eid)
    if not eventi:
        return _esito(TESTI["esito_niente"], eventi=[], ids=[], azione=TESTI["azione_impostazioni"])
    m = TESTI["esito_stato_da_area"].format(
        n=len(eventi), area=aree.nome(aid), stato=imp["stati"][sid]["nome"]
    )
    return _esito(m, ["annulla", *eventi], eventi=eventi, gruppo=gruppo, ids=[t["id"] for t in scelte],
                  azione=TESTI["azione_impostazioni"], riga=m)


def impostazioni() -> dict:
    ""
    ev = _eventi()
    tutte = _carica(ev)
    imp = _imp()
    aree = Aree(imp, _valori_area(ev))
    ctx = Contesto(imp, aree, [])
    oggi = C._adesso()
    voci = {}
    for t in tutte.values():
        sd = _stato_di(imp, t["stato"])
        voci[t["id"]] = {
            "aperta": not t["eliminata"] and not _chiuso_tipo(sd["tipo"]),
            "area_id": aree.finale(t.get("area")),
        }
    del oggi
    aperte = [t for t in tutte.values() if voci[t["id"]]["aperta"]]
    return {
        "ok": True,
        "stati": _info_stati(imp, list(tutte.values())),
        "aree_def": _info_aree(ctx, list(tutte.values()), voci, _conta_aree(aperte, voci)),
        "impostazioni": _info_impostazioni(imp),
        **_scelte_impostazioni(),
        "testi": TESTI,
    }


def esegui_impostazioni(verbo: str, resto: list[str]) -> dict:
    ""

    with _Lucchetto():
        ev = _eventi()
        tutte = _carica(ev)
        imp = _imp()


        resto, in_fondo = _opzioni_in_fondo(resto, ("--se",))
        se = in_fondo.get("--se")
        if se is not None and verbo in _GUARDATI:
            try:
                atteso = json.loads(se)
            except (ValueError, RecursionError):
                raise Errore("errore_valore") from None
            if _valore_imp(verbo, resto, imp, tutte, Aree(imp, _valori_area(ev))) != atteso:
                raise Errore("errore_cambiata_dopo")
        r = _esegui_impostazioni_dentro(verbo, resto, ev, tutte, imp)
        inverso = r.get("annulla")
        if (
            isinstance(inverso, list)
            and inverso
            and inverso[0] in _GUARDATI
            and "--se" not in inverso
        ):
            imp2 = _imp()
            dopo = _valore_imp(inverso[0], inverso[1:], imp2, tutte, Aree(imp2, _valori_area(ev)))
            r["annulla"] = [*inverso, "--se", json.dumps(dopo, ensure_ascii=False)]
        return r



_GUARDATI = frozenset(("imposta", "stato-nome", "stato-segno", "stato-tipo", "stato-predefinito", "stato-ordine",
                       "area-nome", "area-colore", "area-ordine"))


def _valore_imp(verbo: str, args: list[str], imp: dict, tutte: dict, aree: Aree):
    ""
    if verbo == "imposta":
        return imp.get(args[0]) if args else None
    if verbo == "stato-predefinito":
        return imp.get("predefinito") or _predefinito(imp)
    if verbo == "stato-ordine":
        return [s["id"] for s in _stati_in_ordine(imp, True)]
    if verbo == "area-ordine":
        if not imp.get("aree_ordinate"):
            return None
        return [d["id"] for d in aree.visibili(_conta_aree_vive(tutte, imp, aree))]
    if verbo.startswith("stato-"):
        s = imp["stati"].get(args[0]) if args else None
        if s is None:
            return None
        return {"stato-nome": s["nome"], "stato-segno": [s["segno"], s["colore"]],
                "stato-tipo": [s["tipo"], s["segno"]]}.get(verbo)
    aid = aree.cerca(args[0]) if args else None
    d = aree.defs.get(aid) if aid else None
    if d is None:
        return None
    return {"area-nome": d["nome"], "area-colore": d.get("colore")}.get(verbo)


def _esegui_impostazioni_dentro(
    verbo: str, resto: list[str], ev: list[dict], tutte: dict, imp: dict
) -> dict:
    if verbo == "imposta":
        if len(resto) != 2 or resto[0] not in IMPOSTAZIONI_PARTENZA:
            raise Errore("errore_impostazione")
        try:
            valore = json.loads(resto[1])
        except ValueError:
            valore = resto[1]
        prima = imp[resto[0]]
        nuovo = _valida_imposta(resto[0], valore, prima)
        if nuovo == prima:
            return _esito_imp("esito_niente", None)
        riga = {"voce": "imposta", "cosa": verbo, "chiave": resto[0], "dopo": nuovo, "prima": prima,
                "da": "impostazioni" if not os.environ.get("SB_ATTIVITA_DA") else None}
        _scrivi_impostazione(riga)
        return _esito_imp(
            "esito_imposta", ["imposta", resto[0], json.dumps(prima, ensure_ascii=False)]
        )
    if verbo == "stato-da-area":
        return _verbo_stato_da_area(resto, tutte, imp, Aree(imp, _valori_area(ev)))
    if verbo.startswith(("stato-", "stati-")):
        return _verbi_stato(verbo, resto, tutte, imp)
    return _verbi_area(verbo, resto, tutte, imp, Aree(imp, _valori_area(ev)))






CAMPI_GUARDIA = ("filtro", "gruppo", "gruppi_chiusi", "ordine", "fatte", "modo", "regola", "colonne_tabella", "scala",
                 "calendari_nascosti", "rifiutati")


def _guardia_vista(v: dict) -> str:
    return json.dumps({k: v.get(k) for k in CAMPI_GUARDIA}, ensure_ascii=False)


def _cerca_vista(dati: dict, vid: str) -> dict:
    for x, v in _tutte_le_viste(dati):
        if x == vid:
            return v
    raise Errore("errore_vista_sparita")


def _visibili(dati: dict) -> list[str]:
    return [x for x, v in _tutte_le_viste(dati) if not v.get("nascosta") and not v.get("eliminata")]


def _scrivi_vista(dati: dict, vid: str, v: dict) -> None:
    salvata = {k: x for k, x in v.items() if k != "pronta"}
    salvata["cambiata_il"] = _ora()
    dati.setdefault("viste", {})[vid] = salvata


def _metti_in_ordine(dati: dict, vid: str, dopo: str | None) -> None:
    ordine = [x for x, _ in _tutte_le_viste(dati) if x != vid]
    i = ordine.index(dopo) + 1 if dopo in ordine else len(ordine)
    ordine.insert(i, vid)
    dati["ordine"] = ordine


def _nome_libero(dati: dict, base: str) -> str:
    nomi = {
        _chiave_area(_nome_vista(x, v)) for x, v in _tutte_le_viste(dati) if not v.get("eliminata")
    }
    if _chiave_area(base) not in nomi:
        return base
    n = 2
    while _chiave_area(TESTI["nome_vista_copia"].format(nome=base, n=n)) in nomi:
        n += 1
    return TESTI["nome_vista_copia"].format(nome=base, n=n)


def _valida(campo: str, valore, stretto: bool = True):
    ""

    if campo == "filtro":
        if not isinstance(valore, dict):
            raise Errore("errore_valore")
        f = copy.deepcopy(FILTRO_VUOTO)
        for k in ("priorita", "stato", "area"):
            x = valore.get(k) or []

            f[k] = list(dict.fromkeys(
                str(y) for y in (x if isinstance(x, list) else [x])
                if isinstance(y, str | int) and not isinstance(y, bool) and str(y).strip()
            ))
        for k, buoni in (
            ("scadenza", FILTRO_SCADENZA),
            ("stima", FILTRO_STIMA),
            ("pronto", FILTRI_PRONTI),
        ):
            x = valore.get(k)

            if isinstance(x, list) and len(x) == 1:
                x = x[0]
            if x in (None, "", []):
                f[k] = None
            elif isinstance(x, str) and x in buoni:
                f[k] = x
            elif stretto:
                raise Errore("errore_valore")
            else:
                f[k] = None
        return f
    if campo == "gruppo":
        if valore not in CAMPI_GRUPPO:
            raise Errore("errore_valore")
        return valore
    if campo == "gruppi_chiusi":
        if not isinstance(valore, list):
            raise Errore("errore_valore")
        return [str(x) for x in valore]
    if campo == "ordine":


        if valore is None or valore == []:
            return None
        livelli = [valore] if isinstance(valore, dict) else valore
        if not isinstance(livelli, list):
            raise Errore("errore_valore")
        out = []
        for liv in livelli:
            if (
                not isinstance(liv, dict)
                or liv.get("campo") not in CAMPI_ORDINE
                or liv.get("verso") not in ("su", "giu")
            ):
                raise Errore("errore_valore")
            out.append({"campo": liv["campo"], "verso": liv["verso"]})
        campi = [x["campo"] for x in out]
        if "pronto" in campi:
            if len(out) > 1:
                raise Errore("errore_ordine_livelli")
            return None
        if len(out) > LIVELLI_MAX or len(set(campi)) != len(campi):
            raise Errore("errore_ordine_livelli")
        return out
    if campo == "colonne_tabella":

        if valore is None:
            return None
        if (
            not isinstance(valore, list)
            or len(valore) > 50
            or not all(isinstance(x, str) and x for x in valore)
        ):
            raise Errore("errore_valore")
        return list(dict.fromkeys(valore))
    if campo == "fatte":
        if valore not in FATTE_VISTA:
            raise Errore("errore_valore")
        return valore
    if campo == "modo":
        if valore not in MODI:
            raise Errore("errore_modo")
        return valore
    if campo == "scala":
        if valore not in SCALE:
            raise Errore("errore_valore")
        return valore
    if campo == "calendari_nascosti":
        if valore is None:
            return None
        if not isinstance(valore, list) or not all(isinstance(x, str) for x in valore):
            raise Errore("errore_valore")
        return list(dict.fromkeys(valore))
    if campo == "rifiutati":
        if not isinstance(valore, bool):
            raise Errore("errore_valore")
        return valore
    raise Errore("errore_campo_vista")


def _vista_con_registro(verbo: str, resto: list[str]) -> dict:
    ""


    r = esegui_vista(verbo, resto)
    rid = os.environ.get("SB_ATTIVITA_DA") or ""
    if r.get("ok") and r.get("annulla") and _RICHIESTA_VOCE.match(rid):
        cart = CARTELLA / "voce" / rid
        if cart.is_dir():

            with contextlib.suppress(OSError, ValueError):
                _scrivi_righe(cart / "VISTE.jsonl", [{"t": _ora(), "gesto": [verbo, *resto], "annulla": r["annulla"],
                                                      "id": r.get("id") or (resto[0] if resto else "")}])
    return r


def esegui_vista(verbo: str, resto: list[str]) -> dict:
    ""

    with _Lucchetto():
        dati = _leggi_viste()
        if verbo == "vista-nuova" and resto:
            modo = resto[0]
            if modo not in MODI:
                raise Errore("errore_modo")
            da = _cerca_vista(dati, resto[1]) if len(resto) > 1 else None
            vid = "v-" + _nuovo_id(6)
            v = _vista(modo)
            if da:
                v["regola"] = da.get("regola")
                v["filtro"] = copy.deepcopy(da.get("filtro") or FILTRO_VUOTO)
                v["ordine"] = copy.deepcopy(da.get("ordine"))
                v["gruppo"] = da.get("gruppo") or "nessuno"
                v["base"] = da.get("pronta") or da.get("base")
            if modo == "bacheca" and v["gruppo"] == "nessuno":
                v["gruppo"] = "priorita"
            if modo == "calendario":
                v["gruppo"] = "nessuno"
            v["nome"] = _nome_libero(dati, TESTI["nome_vista_nuova"])
            _scrivi_vista(dati, vid, v)
            _metti_in_ordine(dati, vid, resto[1] if len(resto) > 1 else None)
            _salva_viste(dati)


            return _esito(
                TESTI["esito_vista_nuova"],
                ["vista-togli", vid],
                id=vid,
                azione=TESTI["azione_vista"],
            )
        if verbo == "vista-duplica" and resto:
            orig = _cerca_vista(dati, resto[0])
            modo = resto[1] if len(resto) > 1 else orig.get("modo")
            if modo not in MODI:
                raise Errore("errore_modo")
            vid = "v-" + _nuovo_id(6)
            v = {
                **copy.deepcopy(orig),
                "pronta": None,
                "base": orig.get("pronta") or orig.get("base"),
                "modo": modo,
                "nascosta": False,
                "eliminata": False,
            }
            if modo == "bacheca" and v.get("gruppo") == "nessuno":
                v["gruppo"] = "priorita"
            if modo == "calendario":
                v["gruppo"] = "nessuno"

            radice = re.sub(r" \d+$", "", _nome_vista(resto[0], orig)) or _nome_vista(
                resto[0], orig
            )
            v["nome"] = _nome_libero(dati, radice)
            _scrivi_vista(dati, vid, v)
            _metti_in_ordine(dati, vid, resto[0])
            _salva_viste(dati)
            return _esito(
                TESTI["esito_vista_duplicata"],
                ["vista-togli", vid],
                id=vid,
                azione=TESTI["azione_vista"],
            )
        if verbo == "vista-ordine" and resto:
            prima = [x for x, _ in _tutte_le_viste(dati)]
            voluto = list(dict.fromkeys(x for x in resto[0].split(",") if x in prima))
            nuovo = voluto + [x for x in prima if x not in voluto]
            if nuovo == prima:
                return _esito(TESTI["esito_niente"], azione=TESTI["azione_vista"])
            dati["ordine"] = nuovo
            _salva_viste(dati)
            return _esito(
                TESTI["esito_viste_ordine"],
                ["vista-ordine", ",".join(prima)],
                azione=TESTI["azione_vista"],
            )
        if verbo == "vista-rimetti-tolta" and len(resto) == 1:
            tolta = (dati.get("tolte") or {}).get(resto[0])
            if not isinstance(tolta, dict) or not isinstance(tolta.get("vista"), dict):
                raise Errore("errore_vista_sparita")
            vid = resto[0]
            messaggio = TESTI["esito_vista_ripristinata"]
            nome = _nome_vista(vid, tolta["vista"])
            libero = _nome_libero(dati, nome)
            if libero != nome:
                tolta["vista"]["nome"] = libero
                messaggio = TESTI["esito_vista_ripristinata_nome"].format(nome=libero, prima=nome)
            dati.setdefault("viste", {})[vid] = tolta["vista"]
            dati["tolte"].pop(vid, None)
            ordine = [x for x, _ in _tutte_le_viste(dati) if x != vid]
            posto = tolta.get("posto") if isinstance(tolta.get("posto"), int) else len(ordine)
            ordine.insert(max(0, min(posto, len(ordine))), vid)
            dati["ordine"] = ordine
            _salva_viste(dati)
            return _esito(
                messaggio,
                ["vista-togli", vid],
                id=vid,
                azione=TESTI["azione_vista"],
            )
        if not resto:
            raise Errore("errore_comando")
        vid = resto[0]
        v = _cerca_vista(dati, vid)
        if verbo == "vista-togli" and len(resto) == 1:


            if v.get("pronta"):
                raise Errore("errore_vista_pronta")
            if vid in _visibili(dati) and len(_visibili(dati)) <= 1:
                raise Errore("errore_ultima_vista")
            posto = [x for x, _ in _tutte_le_viste(dati)].index(vid)
            salvata = (dati.get("viste") or {}).pop(vid, None)
            dati.setdefault("tolte", {})[vid] = {"vista": salvata, "posto": posto, "t": _ora()}
            dati["ordine"] = [x for x in dati.get("ordine", []) if x != vid]
            _salva_viste(dati)
            return _esito(TESTI["esito_vista_eliminata"], ["vista-rimetti-tolta", vid], id=vid,
                          azione=TESTI["azione_vista"])
        if verbo == "vista-nome" and len(resto) == 2:
            vecchio = v.get("nome") or _nome_vista(vid, v)
            nuovo = _nome_una_riga(resto[1])
            if not nuovo and not v.get("pronta"):
                raise Errore("errore_nome_vuoto")
            if nuovo == (v.get("nome") or ""):
                return _esito(TESTI["esito_niente"], id=vid, azione=TESTI["azione_vista"])

            if nuovo and _chiave_area(nuovo) in {
                _chiave_area(_nome_vista(x, w))
                for x, w in _tutte_le_viste(dati)
                if x != vid and not w.get("eliminata")
            }:
                raise Errore("errore_vista_nome_usato")
            v["nome"] = nuovo or None
            _scrivi_vista(dati, vid, v)
            _salva_viste(dati)

            if not v.get("pronta") or vecchio != TESTI.get(f"vista_{v['pronta']}"):
                indietro = vecchio
            else:
                indietro = ""
            return _esito(
                TESTI["esito_vista_nome"],
                ["vista-nome", vid, indietro],
                id=vid,
                azione=TESTI["azione_vista"],
            )
        if verbo in ("vista-nascondi", "vista-elimina"):
            if verbo == "vista-elimina" and v.get("pronta"):
                raise Errore("errore_vista_pronta")
            campo = "nascosta" if verbo == "vista-nascondi" else "eliminata"
            if v.get(campo):

                return _esito(TESTI["esito_niente"], id=vid, azione=TESTI["azione_vista"])
            if vid in _visibili(dati) and len(_visibili(dati)) <= 1:
                raise Errore("errore_ultima_vista")
            v[campo] = True
            _scrivi_vista(dati, vid, v)
            _salva_viste(dati)
            inverso = "vista-mostra" if campo == "nascosta" else "vista-ripristina"
            chiave = "esito_vista_nascosta" if campo == "nascosta" else "esito_vista_eliminata"
            return _esito(TESTI[chiave], [inverso, vid], id=vid, azione=TESTI["azione_vista"])
        if verbo in ("vista-mostra", "vista-ripristina"):
            campo = "nascosta" if verbo == "vista-mostra" else "eliminata"
            if not v.get(campo):
                return _esito(TESTI["esito_niente"], id=vid, azione=TESTI["azione_vista"])
            v[campo] = False
            messaggio = TESTI[
                "esito_vista_mostrata" if campo == "nascosta" else "esito_vista_ripristinata"
            ]
            if campo == "eliminata":


                nome = _nome_vista(vid, v)
                libero = _nome_libero(dati, nome)
                if libero != nome:
                    v["nome"] = libero
                    messaggio = TESTI["esito_vista_ripristinata_nome"].format(
                        nome=libero, prima=nome
                    )
            _scrivi_vista(dati, vid, v)
            _salva_viste(dati)
            inverso = "vista-nascondi" if campo == "nascosta" else "vista-elimina"
            return _esito(messaggio, [inverso, vid], id=vid, azione=TESTI["azione_vista"])
        if verbo == "vista-rimetti":
            pronta = v.get("pronta")
            if not pronta:
                raise Errore("errore_vista_non_pronta")
            vecchia = json.dumps({k: x for k, x in v.items() if k != "pronta"}, ensure_ascii=False)
            dati.get("viste", {}).pop(vid, None)
            if bool(v.get("nascosta")) != bool(PRONTE[pronta].get("nascosta")):


                dati.setdefault("viste", {})[vid] = {"nascosta": bool(v.get("nascosta"))}
            _salva_viste(dati)
            return _esito(
                TESTI["esito_vista_rimessa"],
                [
                    "vista-imposta",
                    vid,
                    "tutto",
                    vecchia,
                    "--se",
                    _guardia_vista(_cerca_vista(dati, vid)),
                ],
                id=vid,
                azione=TESTI["azione_vista"],
            )
        resto, se = _opzione(resto, "--se")
        if verbo == "vista-imposta" and len(resto) == 3:
            campo = resto[1]
            if se is not None:


                try:
                    atteso = json.loads(se)
                except (
                    ValueError,
                    RecursionError,
                ) as e:
                    raise Errore("errore_valore") from None
                if campo == "tutto":
                    cambiata = not isinstance(atteso, dict) or any(
                        v.get(k) != x for k, x in atteso.items()
                    )
                else:
                    cambiata = v.get(campo) != atteso
                if cambiata:
                    raise Errore("errore_cambiata_dopo")
            try:
                valore = json.loads(resto[2])
            except (ValueError, RecursionError):
                raise Errore("errore_valore") from None
            if campo == "tutto":


                if not isinstance(valore, dict):
                    raise Errore("errore_valore")
                vecchia = json.dumps(
                    {k: x for k, x in v.items() if k != "pronta"}, ensure_ascii=False
                )
                nuova = _pulita_vista(
                    {**v, **valore}, PRONTE.get(v.get("pronta") or "") or _vista()
                )
                if nuova.get("pronta") and nuova.get("eliminata"):
                    raise Errore("errore_vista_pronta")
                if (
                    (nuova.get("nascosta") or nuova.get("eliminata"))
                    and vid in _visibili(dati)
                    and len(_visibili(dati)) <= 1
                ):
                    raise Errore("errore_ultima_vista")
                if not nuova.get("pronta") and not nuova.get("nome"):
                    nuova["nome"] = v.get("nome")
                _scrivi_vista(dati, vid, nuova)
                _salva_viste(dati)
                return _esito(
                    TESTI["esito_vista_salvata"],
                    ["vista-imposta", vid, "tutto", vecchia, "--se", _guardia_vista(nuova)],
                    id=vid,
                    azione=TESTI["azione_vista"],
                )
            grezzo = valore
            valore = _valida(campo, valore)
            if valore == v.get(campo):
                return _esito(TESTI["esito_niente"], id=vid, azione=TESTI["azione_vista"])
            if campo == "gruppo" and v.get("modo") == "bacheca" and valore == "nessuno":
                raise Errore("errore_valore")
            if campo == "modo" and valore == "bacheca" and v.get("gruppo") == "nessuno":



                prima = json.dumps(
                    {"modo": v.get("modo"), "gruppo": v.get("gruppo")}, ensure_ascii=False
                )
                v["modo"], v["gruppo"] = "bacheca", "priorita"
                _scrivi_vista(dati, vid, v)
                _salva_viste(dati)
                return _esito(
                    TESTI["esito_vista_salvata"],
                    [
                        "vista-imposta",
                        vid,
                        "tutto",
                        prima,
                        "--se",
                        json.dumps({"modo": "bacheca", "gruppo": "priorita"}),
                    ],
                    id=vid,
                    azione=TESTI["azione_vista"],
                )


            grezza = (dati.get("viste") or {}).get(vid)
            vecchio = json.dumps(
                grezza[campo] if isinstance(grezza, dict) and campo in grezza else v.get(campo),
                ensure_ascii=False,
            )
            v[campo] = valore
            if se is not None and campo == "ordine" and isinstance(grezzo, dict):

                v[campo] = grezzo
            _scrivi_vista(dati, vid, v)
            _salva_viste(dati)
            return _esito(
                TESTI["esito_vista_salvata"],
                [
                    "vista-imposta",
                    vid,
                    campo,
                    vecchio,
                    "--se",
                    json.dumps(valore, ensure_ascii=False),
                ],
                id=vid,
                azione=TESTI["azione_vista"],
            )
    raise Errore("errore_comando")



VERBI_IMPOSTAZIONI = {
    "stato-nuovo", "stato-nome", "stato-tipo", "stato-segno", "stato-ordine", "stati-ordine", "stato-predefinito",
    "stato-togli", "stato-rimetti", "stato-da-area", "area-nuova", "area-nome", "area-unisci", "area-separa",
    "area-togli", "area-rimetti", "area-ordine", "area-colore", "imposta",
}


def _verbo_calendario(verbo: str, resto: list[str]) -> dict:
    ""

    cal = _calendario_modulo()
    if cal is None:
        return {"ok": False, "errore": TESTI["errore_calendario"], "sparita": False}
    resto, vid = _opzione(resto, "--vista")
    imp = _imp()
    impostazioni = _info_impostazioni(imp)
    if verbo in ("calendario-aggiorna", "calendario-stato"):
        r = cal.esegui([verbo], impostazioni=impostazioni)
    else:
        argomenti = [verbo, *resto]
        if verbo == "buchi":
            resto, durata_testo = _opzione(resto, "--durata")
            if not resto:
                raise Errore("errore_comando")
            argomenti = ["buchi", *resto]
            if durata_testo is not None:
                m = leggi_durata(durata_testo)
                if m is None:
                    raise Errore("errore_durata")
                argomenti += ["--durata", str(m)]
        tutte = _carica()
        if verbo == "buchi" and (resto[0] not in tutte or tutte[resto[0]]["eliminata"]):
            raise Errore("errore_sparita")
        r = cal.esegui(argomenti, task=_task_calendario(tutte, imp), impostazioni=impostazioni,
                       vista=_vista_calendario(vid))
    if not isinstance(r, dict):
        return {"ok": False, "errore": TESTI["errore_calendario"], "sparita": False}
    if not r.get("ok"):
        return {**r, "errore": r.get("errore") or TESTI["errore_calendario"], "sparita": False}
    return r


def _una_volta(chiave: str, verbo: str, resto: list[str]) -> dict:
    ""


    fatti = [e for e in _eventi() if e.get("una_volta") == chiave and isinstance(e.get("eid"), str)]
    if fatti:
        ids = list(dict.fromkeys(str(e.get("id")) for e in fatti))
        tutte = _carica_di(ids)
        titoli = {t: (tutte.get(t) or {}).get("titolo", "") for t in ids}
        altro = {
            "eventi": [e["eid"] for e in fatti],
            "ids": ids,
            "riga": _riga(TESTI["esito_gia_fatto"], titoli, ids),
        }
        if fatti[0].get("tipo") == "crea":
            altro["id"] = ids[0]
        return _esito(TESTI["esito_gia_fatto"], **altro)
    _UNA_VOLTA[:] = [str(chiave)[:100]]
    try:
        return esegui([verbo, *resto])
    finally:
        _UNA_VOLTA.clear()





_CHIAVE_FUORI = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,99}")

VERBI_FUORI = frozenset(("nuova", "fatta", "riapri", "stato", "priorita", "data", "scadenza", "stima", "pianifica",
                         "titolo", "descrizione", "descrizione-aggiungi", "area", "commenta", "elimina",
                         "ripristina"))


def _file_fuori() -> Path:
    ""

    return CARTELLA / "fuori.jsonl"


def _arrivato(chiave: str, eventi: list[dict]) -> dict | None:
    ""


    try:
        righe = _file_fuori().read_bytes().decode("utf-8", "replace").split("\n")
    except FileNotFoundError:
        righe = []
    except OSError as e:
        raise Errore("errore_lettura") from e
    for riga in reversed(righe):
        try:
            r = json.loads(riga)
        except (ValueError, RecursionError):
            continue
        if isinstance(r, dict) and r.get("chiave") == chiave:
            return {"esito": "gia_arrivato", "primo": r.get("esito"), "arrivato": r.get("t")}
    fatti = [e for e in eventi if e.get("una_volta") == chiave and isinstance(e.get("eid"), str)]
    if fatti:
        ids = list(dict.fromkeys(str(e.get("id")) for e in fatti))
        return {
            "esito": "gia_arrivato",
            "primo": None,
            "eventi": [e["eid"] for e in fatti],
            "ids": ids,
        }
    return None


def da_fuori(chiave: str, da: str, ms: int | None, lavoro) -> dict:
    ""










    chiave = str(chiave or "")
    if not _CHIAVE_FUORI.fullmatch(chiave):
        raise Errore("errore_fuori_chiave")
    da = str(da or "")
    if not _FONTE.fullmatch(da):
        raise Errore("errore_fuori_da")
    fuori: dict = {"da": da, "chiave": chiave, "ms": None}
    if type(ms) is int and 0 < ms < 10**14:
        adesso = _adesso_ms()
        fuori["ms"] = min(ms, adesso)
        if ms > adesso:
            fuori["ms_detto"] = ms
    with _Lucchetto():
        eventi = _eventi()
        gia = _arrivato(chiave, eventi)
        if gia is not None:
            return gia
        _UNA_VOLTA[:] = [chiave]
        _FUORI[:] = [fuori]
        try:
            esito = lavoro(eventi)


            _svuota_coda()
            riga = {"t": _ora(), "chiave": chiave, "da": da, "ms": fuori["ms"], "esito": esito}
            _scrivi_righe(_file_fuori(), [riga])
        finally:
            _UNA_VOLTA.clear()
            _FUORI.clear()
    return esito


class _NonFinito(Exception):
    ""


def _verbo_fuori(resto: list[str]) -> dict:
    ""



    if len(resto) < 5 or resto[3] not in VERBI_FUORI:
        raise Errore("errore_comando")
    da, chiave, ms_testo, verbo, *argomenti = resto
    ms = int(ms_testo) if ms_testo.strip().isdigit() and len(ms_testo.strip()) < 15 else None

    def lavoro(_eventi):
        r = esegui([verbo, *argomenti])
        if not r.get("ok") and r.get("dettaglio"):
            raise _NonFinito(r)
        return r

    try:
        r = da_fuori(chiave, da, ms, lavoro)
    except _NonFinito as e:
        return e.args[0]
    if r.get("esito") != "gia_arrivato":
        return r
    if isinstance(r.get("primo"), dict):
        return {**r["primo"], "gia_arrivato": True}
    ids = r.get("ids") or []
    return _esito(
        TESTI["esito_gia_fatto"], eventi=r.get("eventi") or [], ids=ids, gia_arrivato=True
    )






_ERA_VERBI = {"stato": ("stato", 4), "fatta": ("stato", 3), "riapri": ("stato", 3), "priorita": ("priorita", 4),
              "data": ("scadenza", 4), "scadenza": ("scadenza", 4), "stima": ("stima", 4),
              "pianifica": ("pianificata", 4)}


def _era_letto(campo: str, testo: str, imp: dict):
    ""

    if campo == "priorita":
        return _leggi_priorita(testo)
    if campo == "scadenza":
        return _giorno(testo)
    if campo == "stima":
        return leggi_durata(testo)
    if campo == "pianificata":
        return leggi_pianificata(testo)
    return (testo or "").strip()


def _era_torna(campo: str, t: dict, voluto, imp: dict) -> bool:
    ""

    if campo == "stato":
        s = _stato_di(imp, t.get("stato"))
        nomi = {
            _chiave_area(n) for n in [s["nome"], *s.get("nomi_prima", [])] if isinstance(n, str)
        }
        return voluto == t.get("stato") or _chiave_area(voluto) in nomi
    if campo == "pianificata":
        return _pianificata_locale(voluto) == _pianificata_locale(t.get("pianificata"))
    return voluto == t.get(campo)


def _era_di_adesso(campo: str, t: dict, imp: dict) -> str:
    ""
    if campo == "stato":
        return _stato_di(imp, t.get("stato"))["nome"]
    if campo == "priorita":
        return PRIORITA.get(t.get("priorita"), str(t.get("priorita")))
    if campo == "stima":
        return str(t["stima"]) if t.get("stima") else "togli"
    return str(t.get(campo) or "togli")


def _controlla_era(campo: str, arg: str, testo: str) -> None:
    ""

    ids = _ids(arg)
    tutte = _carica_di(ids)
    _controlla(tutte, ids)
    imp = _imp()
    voluto = _era_letto(campo, testo, imp)
    for tid in ids:
        if not _era_torna(campo, tutte[tid], voluto, imp):
            raise Errore("errore_intanto", intanto=_era_di_adesso(campo, tutte[tid], imp))


def _argomento(a) -> str:
    ""

    a = str(a)
    try:
        a.encode("utf-8")
        return a
    except UnicodeEncodeError:
        return a.encode("utf-8", "surrogateescape").decode("utf-8", "replace")



TESTO_FILE_MAX = 8_000_000


def _opzioni_in_fondo(resto: list[str], nomi: tuple[str, ...]) -> tuple[list[str], dict]:
    ""

    trovate: dict[str, str] = {}
    while len(resto) >= 2 and resto[-2] in nomi and resto[-2] not in trovate:
        trovate[resto[-2]] = resto[-1]
        resto = resto[:-2]
    return resto, trovate


def _testi_da_file(
    resto: list[str], f_testo: str | None = None, f_era: str | None = None
) -> list[str]:
    ""





    def leggi(percorso):
        try:
            p = Path(percorso)
            if p.stat().st_size > TESTO_FILE_MAX:
                raise Errore("errore_testo_file")
            return _argomento(p.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError) as e:
            raise Errore("errore_testo_file") from e

    if f_testo is not None:
        resto = [*resto, leggi(f_testo)]
    if f_era is not None:
        resto = [*resto, "--era", leggi(f_era)]
    return resto


_PRIO_FORMA = re.compile(r"^p?0*([0-3])(?:\.0+)?$")


def _leggi_priorita(testo) -> int:
    ""
    m = _PRIO_FORMA.match(str(testo or "").strip().casefold())
    if not m or not str(testo).strip().isascii():
        raise Errore("errore_valore")
    return int(m.group(1))


def esegui(argv: list[str]) -> dict:
    ""
    try:



        argv = [unicodedata.normalize("NFC", _argomento(a)) for a in argv]
        if not argv or argv[0].startswith("--"):
            resto, mese = _opzione(argv, "--mese")
            resto, vista = _opzione(resto, "--vista")
            settimana = None
            if "--settimana" in resto:
                i = resto.index("--settimana")
                dopo = resto[i + 1] if i + 1 < len(resto) else ""
                settimana = "" if dopo.startswith("--") else dopo
            return pagina(
                mese=mese,
                tutte_le_fatte="--fatte" in argv,
                settimana=settimana,
                scala="giorno" if "--giorno" in argv else None,
                vista=vista,
            )
        verbo, resto = argv[0], argv[1:]


        resto, in_fondo = _opzioni_in_fondo(resto, ("--una-volta", "--testo-file", "--era-file"))
        resto = _testi_da_file(resto, in_fondo.get("--testo-file"), in_fondo.get("--era-file"))
        una_volta = in_fondo.get("--una-volta")
        if verbo == "fuori":

            if una_volta:
                raise Errore("errore_comando")
            return _verbo_fuori(resto)
        if una_volta and not verbo.startswith("vista-"):
            return _una_volta(una_volta, verbo, resto)
        if verbo.startswith("vista-"):
            return _vista_con_registro(verbo, resto)
        if verbo == "annulla":
            return _verbo_annulla(resto)
        if verbo == "capisci" and resto:
            return capisci(resto[0])
        if verbo == "durata":
            return durata(" ".join(resto))
        if verbo == "impostazioni":
            return impostazioni()
        if verbo in VERBI_IMPOSTAZIONI:
            return esegui_impostazioni(verbo, resto)
        if verbo in ("commenti", "storia") and len(resto) == 1:
            return commenti(resto[0])
        if verbo == "descrizione-leggi" and len(resto) == 1:
            return descrizione_intera(resto[0])
        if verbo in ("settimana", "buchi", "calendario-aggiorna", "calendario-stato"):
            return _verbo_calendario(verbo, resto)
        if verbo in _ERA_VERBI and len(resto) >= _ERA_VERBI[verbo][1] and resto[-2] == "--era":


            with _Lucchetto():
                _controlla_era(_ERA_VERBI[verbo][0], resto[0], resto[-1])
                return esegui([verbo, *resto[:-2]])
        if verbo == "pianifica":
            return _verbo_pianifica(resto)


        era = None
        if verbo in ("titolo", "descrizione", "area") and len(resto) >= 3 and resto[2] == "--era":
            if len(resto) != 4:
                raise Errore("errore_valore")
            era, resto = resto[3], resto[:2]


        if verbo == "nuova" and resto:
            return _verbo_nuova(resto)
        if verbo == "origine" and len(resto) == 2:
            return origine(resto[0], resto[1])
        if verbo == "origini" and len(resto) == 1:
            return origini(resto[0])
        if verbo == "fatta" and len(resto) == 1:
            return _verbo_fatta(resto[0])
        if verbo == "riapri" and len(resto) == 1:
            return _verbo_riapri(resto[0])
        if verbo == "stato" and len(resto) >= 2:
            return _verbo_stato(resto[0], " ".join(resto[1:]))
        if verbo == "priorita" and len(resto) == 2:

            n = _leggi_priorita(resto[1])
            return _gesto(
                resto[0],
                "priorita",
                n,
                TESTI["esito_priorita"].format(nome=PRIORITA[n]),
                TESTI["esito_priorita_tante"].format(
                    n=numero(len(_ids(resto[0]))), nome=PRIORITA[n]
                ),
                False,
                "priorita",
            )
        if verbo in ("data", "scadenza") and len(resto) == 2:
            giorno = _giorno(resto[1])
            quanti = len(_ids(resto[0]))
            if giorno is None:
                return _gesto(
                    resto[0],
                    "scadenza",
                    None,
                    TESTI["esito_data_tolta"],
                    TESTI["esito_data_tolta_tante"].format(n=numero(quanti)),
                    False,
                    "data",
                )
            quando = C._quando_parole(datetime.strptime(giorno, "%Y-%m-%d"), C._adesso())

            passata = giorno < C._adesso().strftime("%Y-%m-%d")
            return _gesto(
                resto[0],
                "scadenza",
                giorno,
                TESTI["esito_data_passata" if passata else "esito_data_davanti"].format(
                    quando=quando
                ),
                TESTI["esito_data_passata_tante" if passata else "esito_data_tante"].format(
                    n=numero(quanti), quando=quando
                ),
                False,
                "data",
            )
        if verbo == "stima" and len(resto) >= 2:
            return _verbo_stima(resto[0], " ".join(resto[1:]))
        if verbo == "descrizione-aggiungi" and len(resto) == 2:
            ids = _ids(resto[0])
            r = aggiungi_descrizione(ids, resto[1])
            messaggio = (
                TESTI["esito_descrizione_aggiunta"]
                if len(ids) == 1
                else TESTI["esito_descrizione_aggiunta_tante"].format(n=numero(len(ids)))
            )
            return _esito(
                messaggio,
                eventi=r["eventi"],
                gruppo=r["gruppo"],
                ids=ids,
                azione=_azione("descrizione", len(ids)),
                riga=_riga(messaggio, r["titoli"], ids),
            )
        if verbo == "commenta" and len(resto) == 2:
            return _verbo_commenta(resto[0], resto[1])
        if verbo == "commento-togli" and len(resto) == 1:
            return _verbo_commento_togli(resto[0])
        if verbo == "area" and len(resto) == 2:
            return _verbo_area(resto[0], resto[1], era)
        if verbo in ("titolo", "descrizione") and len(resto) == 2:
            if verbo == "titolo" and _vuoto(resto[1]):
                raise Errore("errore_titolo")
            valore = resto[1].strip() if verbo != "descrizione" else resto[1]
            messaggio = TESTI[f"esito_{verbo}"]
            return _gesto(
                resto[0],
                verbo,
                valore,
                messaggio,
                messaggio,
                False,
                verbo,
                era={verbo: era} if era is not None else None,
            )
        if verbo in ("elimina", "ripristina") and len(resto) == 1:
            return _verbo_segna(resto[0], verbo, False)
        if verbo == "importa":
            return importa()
        return {"ok": False, "errore": TESTI["errore_comando"]}
    except Errore as e:
        out = {"ok": False, "errore": TESTI[e.chiave], "sparita": e.chiave == "errore_sparita"}
        if e.altro:



            chiave = (
                e.chiave + "_una"
                if e.altro.get("n") == 1 and e.chiave + "_una" in TESTI
                else e.chiave
            )
            try:
                out["errore"] = TESTI[chiave].format(**{k: numero(v) for k, v in e.altro.items()})
            except (KeyError, IndexError, ValueError):
                pass
        out.update(e.altro)
        return out
    except C.Errore as e:
        return {"ok": False, "errore": C.TESTI[e.chiave], "sparita": False}
    except OSError as e:


        chiave = (
            "errore_disco_pieno"
            if e.errno in (errno.ENOSPC, errno.EDQUOT, errno.EFBIG)
            else {
                "viste": "errore_scrittura_viste",
                "impostazioni": "errore_scrittura_impostazioni",
            }.get(getattr(e, "sb_file", None), "errore_scrittura")
        )
        return {"ok": False, "errore": TESTI[chiave], "sparita": False, "riprova": False,
                "dettaglio": type(e).__name__}
    except Exception as e:  # noqa: BLE001 l'app aspetta sempre un JSON, mai una traccia
        return {
            "ok": False,
            "errore": TESTI["errore_motore"],
            "sparita": False,
            "dettaglio": type(e).__name__,
        }




INTERO_MIN, INTERO_MAX = -(2**63), 2**63 - 1


def _ripulito(x):
    ""
    if x is None or isinstance(x, bool):
        return x
    if isinstance(x, int):
        return x if INTERO_MIN <= x <= INTERO_MAX else None
    if isinstance(x, float):
        return x if x == x and x not in (float("inf"), float("-inf")) else None
    if isinstance(x, str):
        return _pulito(x)
    if isinstance(x, dict):
        return {_pulito(str(k)): _ripulito(v) for k, v in x.items()}
    if isinstance(x, list | tuple):
        return [_ripulito(v) for v in x]
    return _pulito(str(x))


def _surrogato_solo(testo: str) -> bool:
    ""

    i = testo.find("\\ud")
    while i >= 0:
        prima = i
        while prima > 0 and testo[prima - 1] == "\\":
            prima -= 1
        if (i - prima) % 2:
            i = testo.find("\\ud", i + 1)
            continue
        c = testo[i + 3 : i + 4]
        if (
            c in ("8", "9", "a", "b")
            and testo[i + 6 : i + 9] == "\\ud"
            and testo[i + 9 : i + 10] in ("c", "d", "e", "f")
        ):
            i = testo.find("\\ud", i + 12)
            continue
        if c in ("8", "9", "a", "b", "c", "d", "e", "f"):
            return True
        i = testo.find("\\ud", i + 1)
    return False


def json_per_app(risposta) -> bytes:
    ""


    try:




        testo = json.dumps(risposta, allow_nan=False, separators=(",", ":"))
        if not _surrogato_solo(testo):
            return testo.encode("ascii")
        return json.dumps(
            risposta, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        ).encode("utf-8")
    except (ValueError, TypeError, UnicodeEncodeError, RecursionError):
        try:
            return json.dumps(
                _ripulito(risposta), ensure_ascii=False, allow_nan=False, separators=(",", ":")
            ).encode("utf-8")
        except (ValueError, TypeError, UnicodeEncodeError, RecursionError):
            return json.dumps(
                {"ok": False, "errore": TESTI["errore_motore"], "sparita": False}
            ).encode("utf-8")





def _pulita(testo: str) -> str:
    ""

    testo = re.sub(r"^\s*Area:[^·\n]*(?:·\s*)?", "", (testo or "").strip())
    righe = [r for r in testo.splitlines() if not r.lstrip().startswith("Fonte:")]
    return re.sub(r"\n{3,}", "\n\n", C._PALLINI.sub("", "\n".join(righe))).strip()


def importa() -> dict:
    ""

    gia = {(t.get("origine") or {}).get("id") for t in _carica().values()}
    pagina_n, nuove = 0, 0
    while pagina_n < 20:
        d = C._api(
            "GET", f"/list/{C.LISTA}/task?page={pagina_n}&include_closed=false&subtasks=true"
        )
        for t in d.get("tasks", []):
            if t.get("id") in gia:
                continue
            prio = (t.get("priority") or {}).get("priority")
            testo = t.get("text_content") or t.get("description") or ""
            ms = int(t["due_date"]) if t.get("due_date") else None
            nata = C._da_ms(int(t["date_created"])) if t.get("date_created") else C._adesso()
            crea(
                {
                    "titolo": C._titolo(t.get("name") or ""),
                    "descrizione": _pulita(testo),
                    "priorita": DA_CLICKUP.get(prio, 3),
                    "scadenza": C._da_ms(ms).strftime("%Y-%m-%d") if ms else None,
                    "stima": round(int(t["time_estimate"]) / 60000)
                    if t.get("time_estimate")
                    else None,
                    "area": C._area({"name": t.get("name") or "", "description": testo}),
                    "origine": {
                        "fonte": "clickup",
                        "id": t.get("id"),
                        "url": t.get("url"),
                        "nome": t.get("name"),
                        "priorita": prio,

                        "descrizione": testo,
                    },
                },
                da="importa-clickup",
                quando=nata.isoformat(timespec="seconds"),
            )
            nuove += 1
        if d.get("last_page", True) or not d.get("tasks"):
            break
        pagina_n += 1
    if not nuove:
        return _esito(TESTI["esito_importate_zero"], importate=0)
    chiave = "esito_importate_uno" if nuove == 1 else "esito_importate_tanti"
    return _esito(TESTI[chiave].format(n=numero(nuove)), importate=nuove)


if __name__ == "__main__":
    if sys.argv[1:2] in (["-h"], ["--help"]):
        print(__doc__)
        sys.exit(0)
    sys.stdout.buffer.write(json_per_app(esegui(sys.argv[1:])) + b"\n")
