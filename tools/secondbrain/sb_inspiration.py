#!/usr/bin/env python3
"""Inspiration section of the SecondBrain app: the things you save to look at later (reels, posts, sites, links,
screenshots, notes, audio), read from <archive folder>/archivio/archivio.jsonl and grouped for the app
(the folder is inspiration.archive_dir in sbk.config.json; unset = Inspiration is off, sb_inspiration_root.py),
with their state (not seen yet, seen, understood) and the groups that wait on you.

Usage: uv run python tools/secondbrain/sb_inspiration.py json   (prints the state the app shows)
"""

from __future__ import annotations

import datetime
import functools
import json
import os
import re
import sys
import threading
import unicodedata
from pathlib import Path
from urllib.parse import urlparse

HOME = os.path.expanduser("~")
if os.path.dirname(os.path.abspath(__file__)) not in sys.path:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sb_inspiration_root  # noqa: E402

# The archive folder: inspiration.archive_dir in sbk.config.json (or SB_INSPIRATION_RADICE).
# Unset = Inspiration is off and stato() says so instead of reading anything.
RADICE = str(sb_inspiration_root.root())
ARCHIVIO = os.path.join(RADICE, "archivio", "archivio.jsonl")
ESPORTAZIONE = os.path.join(RADICE, "archivio", "pagina", "inspiration.json")

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


TESTI = {
    "titolo": "Inspiration",
    "cerca": "Search the items",
    "pagina_online": "Online page",
    "aiuto_pagina_online": "The published page with all the items. Earlier versions may live on other accounts and online they open only with those.",
    "apri_online": "Open online",
    "copia_link": "Copy link",
    "versioni_di_prima": "Earlier versions",
    "progetto": "Project",
    "tutti_i_progetti": "All projects",
    "senza_progetto": "No project",
    "aiuto_tipi": "Show only these types. Click again to drop them from the filter.",
    "vuota": "The things that inspire you end up here.",
    "vuota_come": "Send me a link in your Slack DM, a reel, a post, a site, a screenshot, and you find it here.",
    "nessuno_coi_filtri": "No item with these filters.",
    "togli_filtri": "Clear the filters",
    "capiti": "Understood",
    "capiti_frase": "I have seen the content and understood it.",
    "visti": "Seen, to understand",
    "visti_frase": "I have seen the content, now I'm understanding it.",
    "non_visti": "Not seen yet",
    "non_visti_frase": "Until the content has been seen, the card comes only from the caption.",
    "a_parte": "Probably not items",
    "a_parte_frase": "Files and sites I sent on your behalf, and an audio of yours with no link nearby. They stay here, nothing gets deleted.",
    "aggiornato": "Updated {quando}",
    "errore": "I can't reload the items. What you see is from {ora}.",
    "errore_senza_ora": "I can't reload the items. What you see is the last saved copy.",
    "riprova": "Try again",
    "apri_originale": "Open the original",
    "aiuto_apri_originale": "Opens the content where you found it, in the browser.",
    "rispondi_slack": "Reply on Slack",
    "aiuto_rispondi_slack": "Opens Slack on the message where you sent it to me, to reply in its thread. There the reply stays attached to this item.",
    "precedente": "Previous",
    "successivo": "Next",
    "posizione": "{k} of {n}",
    "aiuto_frecce": "With ← and → you move to the previous and next item, within the filters you chose. Esc goes back to the board.",
    "le_tue_parole": "Your words",
    "ascolta": "Listen",
    "pausa": "Pause",
    "aiuto_ascolta": "Your audio, from the file saved on the Mac.",
    "ascolta_slack": "Listen on Slack",
    "aiuto_ascolta_slack": "Opens Slack on the message with your audio.",

    "nessuna_parola": "You haven't told me anything about this yet.",
    "cosa_mostra": "What it shows",
    "cosa_promette": "What it promises",
    "cose_simili": "Similar things",
    "domanda_per_te": "The question for you",
    "storia": "Story",
    "trascrizione": "Transcript",
    "dove_va": "Where it goes",
    "dalla_didascalia": "From the caption alone, to redo with the content",
    "dalla_didascalia_frase": "I haven't seen the content. These lines come from the caption and the cover, and the searches are redone when I see it.",
    "video_qui": "The video on the Mac",
    "nessuna_copertina": "No cover",

    "fasi_aiuto": "Every understood item goes through five phases. Next to the number is how many are waiting for you",
    "aspettano_te": "{n} waiting for you",

    "per_te": "{n} for you",


    "spunti_conto": "{n} items",
    "spunti_conto_uno": "1 item",
    "per_te_nuovi": "{n} new",
    "per_te_nuovi_uno": "1 new",
    "per_te_aspettano_si": "{n} waiting for the yes",
    "per_te_aspettano_si_uno": "1 waiting for the yes",
    "menu_etichetta": "{nome} {n}",
    "menu_etichetta_per_te": "{nome} {n} · {per_te}",

    "perche_tenuto": "Set aside {quando}",
    "domanda_non_serve": "not needed anymore, item set aside",
    "ho_capito": "Here's what I understood",
    "dove_arrivare": "Where you want to get to",
    "su_cosa_poggia": "What it rests on",
    "giusto": "Right",
    "aiuto_giusto": "You confirm the reason as it's written.",
    "correggi": "Correct",
    "aiuto_correggi": "Tell me how it really is, in writing or by voice, and if needed pick a different outcome.",
    "correzione_segnaposto": "Why you really saved it, and where you want to get to",
    "esito": "For you it's",
    "aiuto_esito": "For me it's this. If it's not so, press Correct and choose.",
    "da_confermare": "to confirm",
    "confermato": "Confirmed {quando}",
    "corretto_da_te": "How it really is, in your words",
    "prima_avevo_capito": "What I had understood before",
    "avevo_detto": "I had said {esito}",
    "cosa_mi_manca": "What I'm missing",
    "cosa_mi_manca_frase": "Answer here, in writing or by voice. The answer goes into the item on its own.",
    "niente_mi_manca": "For now I'm not missing anything.",

    "risposto_a_tutto": "You answered everything, for now I'm not missing anything else.",
    "risposte_date": "Your answers",
    "risposta_data": "Answered {quando}",
    "non_servono_piu": "Earlier questions, no longer needed for the work",
    "rispondi": "Answer",
    "risposta_segnaposto": "Write the answer",
    "invia": "Send",
    "registra": "Record",
    "ferma": "Stop and send",
    "annulla": "Cancel",
    "chiudi": "Close",
    "nascondi": "Hide",
    "registrando": "Recording {secondi}",
    "in_trascrizione": "Your voice answer, I'm transcribing it",
    "aiuto_registra": "You record here with the Mac's microphone. I transcribe it on the Mac, nothing leaves home.",
    "microfono_negato": "The microphone isn't allowed for SBK. Turn it on in System Settings, Privacy and security, Microphone, then press Record again",
    "apri_impostazioni": "Open settings",

    "registrando_per": "Recording {secondi} for “{cosa}”",
    "registrando_perche": "the reason",
    "registrando_dettaglio": "a detail",
    "chiedo_permesso": "I'm asking you for microphone permission",
    "microfono_non_parte": "The microphone didn't start. Check the Mac's audio input, or write the answer",
    "registrazione_corta": "Too short, I didn't send it. Try again",
    "registrazione_annullata": "Recording cancelled, {durata}. I'm keeping it aside",
    "mandala": "Send it anyway",
    "aiuto_registra_occupato": "I'm already recording for another point. Stop that one first",
    "invio_audio": "Sending your voice answer",
    "un_attimo": "One moment",
    "prossimo_che_aspetta": "The next one waiting for you",

    "audio_in_trascrizione": "Your voice answer of {durata}, sent at {ora}. I'm transcribing it",
    "audio_aspetta_memoria": "Your voice answer of {durata} is waiting for the Mac to have free memory. I retried at {ora}",
    "audio_non_riuscita": "I couldn't transcribe your answer. Listen again and rewrite it, or record it again",
    "audio_senza_parlato": "In your audio I didn't hear any words. Try again or write the answer",
    "audio_da_verificare": "I heard “{testo}”, is that right?",
    "audio_trascritta": "from your audio of {durata}",

    "e_giusto": "It's right",
    "aiuto_e_giusto": "The words I heard become your answer",
    "cambia": "Change",
    "aiuto_cambia": "Rewrite the answer, or record it again",
    "togli": "Remove",
    "aiuto_togli": "I remove the answer and the question reopens. The audio stays on the Mac",
    "rispondi_a_tutte": "Answer them all together",
    "aiuto_rispondi_a_tutte": "A single answer, written or by voice, for all the open questions. I split it among the questions",
    "risposta_a_tutte_segnaposto": "Answer them all, one after the other",
    "registrando_tutte": "all the questions",
    "risposta_a_tutte": "Your answer to all {n} together",
    "livello_basso": "I can't hear you yet",


    "rileggi": "Reread now",
    "aiuto_rileggi": "Reads the messages that arrived or changed in your Slack DM since last time and says what's new. The new reels, pages and your audios I download on my own",
    "rilettura_in_corso": "I'm rereading your Slack DM",
    "rilettura_niente": "I reread your DM, {messaggi} messages. Nothing new",
    "rilettura_nuove": "I reread your DM, {messaggi} messages. {cosa}",


    "rilettura_furba_zero": "I looked at your DM, nothing arrived or changed since last time",
    "rilettura_furba_niente": "I read your DM, nothing new",
    "rilettura_furba_nuove": "I read your DM. {cosa}",
    "rilettura_intera_niente": "I reread your whole DM {perche}, {messaggi} messages. Nothing new",
    "rilettura_intera_nuove": "I reread your whole DM {perche}, {messaggi} messages. {cosa}",
    "intera_chiesta": "as you asked",
    "intera_controllo": "for the weekly check",
    "intera_prima": "for the first time",
    "un_messaggio": "1 message",
    "n_messaggi": "{n} messages",
    "spunto_nuovo": "1 new item",
    "spunti_nuovi": "{n} new items",
    "parole_nuove": "your new words on {n}",
    "a_parte_nuove": "{n} in the separate list",
    "parole_su": "Your new words on “{titolo}”",
    "scarichi_partiti": "I'm downloading {cosa}, you see them here as soon as they're downloaded",
    "un_reel": "1 reel",
    "n_reel": "{n} reels",
    "una_pagina": "1 page",
    "n_pagine": "{n} pages",


    "ordine": "Order",

    "aiuto_ordine": "The order of the items. Most recent puts the last one you sent me on top.",
    "ordine_recenti": "Most recent",
    "ordine_vecchi": "Oldest",
    "ordine_progetto": "By project",
    "ordine_per_te": "Those for you first",
    "fase": "Phase",
    "aiuto_fase": "A single phase, or all the items",

    "aiuto_passo_menu": "A single step, those that left the path, or all the items",

    "passi_menu_titolo": "Step",
    "aiuto_ordine_per_te": "First the ones waiting for you, the same ones counted in the menu",

    "menu_tutti": "All steps",
    "menu_tutti_riga": "All the items, from Understand to the ones that left the path",
    "menu_tutti_vuota": "No item yet.",
    "menu_capire_vuota": "No item to understand, for now.",
    "menu_scope_vuota": "No scope to confirm, for now.",
    "menu_contesto_vuota": "No item at Context.",
    "menu_ricerca_vuota": "No item at Research.",
    "menu_implementazione_vuota": "No work to start or in progress.",
    "menu_test_vuota": "No results to read.",
    "menu_riferimento": "References",
    "menu_riferimento_riga": "Kept as a reference, off the path. You reopen them whenever you want",
    "menu_riferimento_vuota": "No reference, for now.",
    "menu_cosa_da_fare": "To do",
    "menu_cosa_da_fare_riga": "The to-dos you confirmed, with a task or still without",
    "menu_cosa_da_fare_vuota": "Nothing to do.",
    "menu_letto": "Studies read",
    "menu_letto_riga": "The studies you read. The card stays here, you reopen them whenever you want",
    "menu_letto_vuota": "No study read.",
    "menu_non_serve": "Not needed",
    "menu_non_serve_riga": "The ones you think aren't needed. They stay in the archive, you reopen them whenever you want",
    "menu_non_serve_vuota": "No item that isn't needed.",
    "mostra": "Show",
    "aiuto_mostra": "Only one project, only one type, or everything",
    "tutti_i_tipi": "All types",
    "solo_tipo": "Only {tipo}",
    "mostra_progetto_e_tipo": "{progetto}, only {tipo}",
    "altro_menu": "More",


    "aiuto_menu_altro": "Inspiration's settings, the DM reread and the online page.",
    "apri_pagina_online": "Open the online page",
    "copia_link_pagina": "Copy the page link",
    "nuovo": "New",
    "aiuto_nuovo": "Came in today from your DM",


    "capisci": "Do it now",


    "aiuto_capisci": "I download it if it's missing and understand it now, before the others and without opening anything. Then I propose the reason and it's your turn",
    "capisci_tutti": "Do them now",
    "aiuto_capisci_tutti": "I understand them now, all the ones not yet understood, without opening anything. Then it's your turn",
    "capisci_pannello": "Understand it in the terminal",

    "capisci_pannello_menu": "Understand it in the terminal",
    "capisci_minore": "Do it now",
    "aiuto_capisci_pannello": "An agent in the terminal understands it, so you see it work",
    "da_capire_visti": "{n} to understand",
    "vai_comprensione": "Go to the terminal",



    "ritmo_spento": "I read and understand only when you ask me, with “Reread the DM now” or “Do it now”",
    "ritmo_acceso": "While the app is open I understand the items already in on my own. The DM I read when you press Reread the DM now",
    "ritmo_ultimo": "I last looked {quando}",
    "ritmo_prossimo": "the next one {quando} if the app stays open",
    "ritmo_adesso": "I'm understanding {cosa}",
    "ritmo_fermo_uno": "{titolo} I can't understand it on my own. Open it and press Do it now",
    "ritmo_fermi": "{n} items I can't understand on my own. Open them and press Do it now",
    "ritmo_scarico": "What I can't download I retry on my own, once an hour",





    "ritmo_acceso_sempre": "I understand the items that arrive on my own, and your DM I read about every {n} minutes",
    "ritmo_letto": "I last read the DM {quando}",
    "ritmo_prossimo_giro": "the next one {quando}",
    "ritmo_tick_fermo": "With the app closed I haven't read the DM since {quando}",
    "ritmo_tick_mai": "With the app closed I haven't read the DM yet",
    "ritmo_dm_spento": "Reading the DM with the app closed is off",


    "ritmo_a_te_uno": "{cosa} I don't open on my own, it's waiting for your yes",
    "ritmo_a_te": "{cosa} I don't open on my own, they're waiting for your yes",
    "ritmo_si_uno": "{cosa} I open and understand on my own, I have your yes",
    "ritmo_si": "{cosa} I open and understand on my own, I have your yes",
    "ritmo_scendono_uno": "{cosa} I'm downloading it, as soon as it's downloaded I understand it on my own",
    "ritmo_scendono": "{cosa} I'm downloading them, as soon as they're downloaded I understand them on my own",
    "pulsante_a_te": "Read {cosa}",
    "aiuto_pulsante_a_te": "I read them one after another and understand them on my own. Then it's your turn",
    "segno_a_te": "Waiting for your yes",

    "segno_a_te_aiuto": "This one I don't open on my own. You give the yes at the top of the board, or in here with Yes, read it",
    "segno_in_arrivo": "I'm downloading it",
    "segno_in_arrivo_aiuto": "I'm downloading it, then I understand it on my own. Nothing needed from you",
    "segno_si": "Your yes is in",
    "segno_si_aiuto": "I open and understand it on my own, nothing else needed from you",
    "segno_lo_capisco": "I'm understanding it",
    "segno_lo_capisco_aiuto": "I've downloaded the content and I'm understanding it. Then it's your turn",
    "un_post_x": "1 X post",
    "n_post_x": "{n} X posts",
    "un_audio": "1 audio of yours to transcribe",
    "n_audio": "{n} audios of yours to transcribe",
    "ultima_rilettura": "DM read {quando}",
    "aiuto_livello": "How well I can hear you",

    "correzione_in_trascrizione": "Your voice correction of {durata}, sent at {ora}. I'm transcribing it",
    "correzione_aspetta_memoria": "Your voice correction of {durata} is waiting for the Mac to have free memory. I retried at {ora}",
    "correzione_non_riuscita": "I couldn't transcribe your correction. Listen again and rewrite it, or record it again",
    "correzione_senza_parlato": "In your audio I didn't hear any words. Try again or write the correction",
    "correzione_da_verificare": "I heard “{testo}”, is that right?",

    "perche_confermato": "Confirmed {quando}",
    "perche_corretto": "Corrected by you {quando}",
    "perche_corretto_voce": "Corrected by voice {quando}, I'm transcribing it",
    "perche_corretto_voce_memoria": "Corrected by voice {quando}, I'm waiting for the Mac's memory",
    "perche_corretto_voce_non_riuscita": "Corrected by voice {quando}, the transcription failed",
    "perche_corretto_voce_senza_parlato": "Corrected by voice {quando}, in the audio I didn't hear any words",
    "perche_corretto_voce_da_verificare": "Corrected by voice {quando}, to verify",
    "dettaglio": "Add a detail, I'll read it",


    "passo_dopo": "After your answer",
    "rileggo_risposta": "I'm rereading everything with your answer {quando}. When I'm done you find the reread reason here",
    "riletto_risposta": "I reread everything with your answer {quando} and rewrote the reason. Tell me if it's right now",
    "riletto_risposta_domande": "I reread everything with your answer {quando} and rewrote the reason. Tell me if it's right now, and above here I'm still missing {domande}",
    "riletto_uguale": "I reread everything with your answer {quando}. The reason stays as it was, tell me if it's right",

    "rileggo_risposta_confermato": "I'm rereading everything with your answer {quando}. When I'm done you find here where you want to get to and the questions redone with your words",

    "rileggo_risposta_in_fila": "I have your answer {quando}. I'll reread everything as soon as I can, when I'm done you find the reread reason here",
    "rileggo_risposta_confermato_in_fila": "I have your answer {quando}. I'll reread everything as soon as I can, when I'm done you find here where you want to get to and the questions redone with your words",
    "riletto_confermato": "I reread everything with your answer {quando}. The reason stays yours, I rewrote where you want to get to and reviewed the questions. Then press Let's work on it",
    "riletto_confermato_uguale": "I reread everything with your answer {quando}. Where you want to get to stays the same, I reviewed the questions. Then press Let's work on it",
    "rilettura_ferma_risposta": "I couldn't reread with your answer {quando}, {motivo}. The answer stays here",
    "risposta_alla_sessione": "The agent in the terminal has your answer {quando} and is carrying on. If it needs anything else it asks you there",
    "risposta_ci_lavoriamo": "I have your answer {quando}. Press Let's work on it, in the terminal I read it and write the steps and the card",
    "risposta_perche_te": "I have your answer {quando}. Tell me if the reason above is right, then Let's work on it",
    "riletto_segno": "Reread with your answer {quando}",
    "prima_dicevo": "Before I said this",
    "dettaglio_segnaposto": "A detail, what's needed, where to get to",
    "ci_lavoriamo": "Let's work on it",
    "aiuto_ci_lavoriamo": "I open an agent on this item in the terminal. It reviews the reason with you, writes the steps and the card, and if it has questions it asks you there.",
    "vai_sessione": "Go to the terminal",
    "aiuto_vai_sessione": "Shows this item's agent in the terminal.",
    "aiuto_vai": "Brings the terminal to the front. If the agent asks you something, you answer it there",
    "sessione_aperta": "This item's agent is in the terminal, opened {quando}",
    "sessione_ha_scritto": "The agent that wrote the card is still open in the terminal",
    "sessione_chiusa": "This item's agent closed in the terminal {quando}",
    "il_piano": "The steps",
    "punto_di_arrivo": "How far it goes",
    "dati_che_servono": "What's needed",
    "cosa_non_fare": "What it doesn't do",
    "la_scheda": "The work card",
    "leggi_scheda": "Read the card",
    "avvia": "Start",
    "aiuto_avvia": "I open a new agent in the terminal that does the work written in the card. One at a time, only with your click.",
    "avvia_conferma_titolo": "Start the work on this item?",
    "avvia_conferma_testo": "I open a new agent in the terminal that reads the card and works up to the endpoint. {permessi} If it has questions it asks you there, and it writes the results here.",

    "avvia_task": "Also create the task in Tasks",
    "aiuto_avvia_task": "It's created in Tasks, with the endpoint and the work folder. The work starts either way, with or without a task",
    "lavoro_avviato": "The work started {quando}. {permessi}",
    "lavoro_finito": "The work finished {quando}",
    "vai_lavoro": "Go to the work",
    "il_ritorno": "The results",
    "leggi_ritorno": "Read the results",
    "ritorno_parziale": "The results so far",
    "ho_letto": "Read",
    "cosa_ne_so": "What I know about it",

    "azione_non_riuscita": "It didn't work",
    "errore_titolo": "It didn't work",
    "motore_scaduto": "The engine didn't respond in time. Try again",



    "non_so_se_andata": "I don't know if it worked. Check if anything changed, then try again if needed",



    "testa_dm_letto": "DM read {quando}",
    "testa_dm_non_letto": "I can't read your DM, what you see is {di_quando}",
    "testa_dm_non_letto_mai": "I can't read your DM",
    "testa_scendono": "{cosa} new, {k} already downloaded",
    "testa_scendono_k1": "{cosa} new, 1 already downloaded",
    "testa_scendono_zero": "{cosa} new, I'm downloading them",
    "testa_scende_uno": "{cosa} new, I'm downloading it",
    "testa_scesi": "{cosa} downloaded, then I understand them on my own",
    "testa_sceso_uno": "{cosa} downloaded, then I understand it on my own",

    "testa_li_capisco": "I understand them on my own",
    "testa_lo_capisco": "Then I understand it on my own",
    "testa_tocca_te": "Then it's your turn",
    "testa_capisco": "I'm understanding {cosa}, {k} already understood",
    "testa_capisco_k1": "I'm understanding {cosa}, 1 already understood",
    "testa_capisco_zero": "I'm understanding {cosa}",
    "testa_capisco_uno": "I'm understanding {cosa}",
    "testa_capiti_tutti": "I understood {cosa}, now I'm writing why you saved them",
    "testa_capito_uno": "I understood {cosa}, now I'm writing why you saved it",


    "testa_capiti_tutti_corta": "I understood {cosa}, writing the reason",
    "testa_capito_uno_corta": "I understood {cosa}, writing the reason",
    "testa_scesi_corta": "{cosa} downloaded, then I understand them",
    "testa_sceso_uno_corta": "{cosa} downloaded, then I understand it",
    "testa_aspettano_si": "{cosa} waiting for your yes",
    "testa_aspetta_si": "{cosa} waiting for your yes",
    "testa_altri_si": "Another {n} waiting for your yes",
    "testa_altro_si": "One more waiting for your yes",
    "testa_pulsante": "Yes, read them",
    "testa_pulsante_uno": "Yes, read it",
    "testa_pulsante_aiuto": "I read them one at a time and understand them on my own, without opening anything for you. Then it's your turn",
    "testa_pulsante_aiuto_uno": "I read it and understand it on my own, without opening anything for you. Then it's your turn",



    "testa_leggo_domanda": "Shall I read {cosa}?",
    "testa_sotto_acceso": "I read them one at a time without your account, then it's your turn. The yes can't be taken back",
    "testa_sotto_spento": "I read one for each yes, without your account, then it's your turn. The yes can't be taken back",

    "testa_sotto_uno": "I read it without your account, then it's your turn. The yes can't be taken back",


    "testa_di_prima": "Another {n} to confirm, proposed earlier",

    "testa_di_prima_uno": "One more to confirm, proposed earlier",
    "testa_mostrameli": "Show them to me",
    "testa_mostra_tutti": "Show them all",
    "apri_in_attivita": "Open in Tasks",

    "testa_mostramelo": "Show it to me",
    "testa_dettagli": "Details",
    "testa_rileggi": "Reread the DM now",

    "dettagli_dm": "From your DM",
    "dettagli_adesso": "Now",
    "dettagli_aspettano_si": "Waiting for your yes",
    "dettagli_si": "Your yes is in",
    "dettagli_fermi": "I can't understand them",
    "dettagli_vietati": "Age-restricted",
    "dettagli_nuovi": "{cosa} {quando}",
    "dettagli_niente_di_nuovo": "Nothing new since last time",
    "dettagli_letto": "DM read {quando}",
    "dettagli_letto_ultima": "I last read it {quando}",
    "dettagli_aspettano_si_riga": "I don't open them on my own, you give the yes",
    "dettagli_aspetta_si_riga": "I don't open it on my own, you give the yes",
    "dettagli_si_riga": "I open and understand them on my own, nothing else needed from you",
    "dettagli_si_riga_uno": "I open and understand it on my own, nothing else needed from you",
    "dettagli_vietato_riga": "{titolo}. Instagram shows it only to those who log in with their account",
    "dettagli_fermo_riga": "{titolo}. {motivo}",
    "dettagli_manca_perche_riga": "{titolo}, understood but without the reason",
    "dettagli_a_vuoto": "Stopped by a mistake of mine",
    "dettagli_a_vuoto_riga": "The content isn't relevant. I restart them one at a time, nothing needed from you",
    "dettagli_a_vuoto_riga_acceso": "The content isn't relevant. They restart on their own, one at a time",
    "dettagli_a_vuoto_riga_uno": "The content isn't relevant. I restart it, nothing needed from you",
    "dettagli_a_vuoto_riga_uno_acceso": "The content isn't relevant. It restarts on its own",
    "dettagli_sparito_riga": "{titolo}. It's gone, the copy and what I had understood remain",

    "segno_scende": "I'm downloading it",
    "segno_scende_aiuto": "I'm downloading it, then I understand it on my own. Nothing needed from you",
    "segno_sceso": "Downloaded, then I understand it",
    "segno_sceso_aiuto": "I downloaded it {quando}. Then I understand it on my own and it's your turn",
    "segno_capisco": "I'm understanding it",
    "segno_capisco_aiuto": "I'm understanding it, I started {quando}. Then it's your turn",
    "segno_capito_scrivo": "I understood it {quando}, then I write why you saved it and it's your turn",
    "segno_capito": "I understood it",
    "segno_riprovo": "I'll try again on my own",
    "segno_riprovo_aiuto": "{motivo}. I'll try again on my own",
    "segno_fermo": "I can't understand it",
    "segno_fermo_aiuto": "I tried three times. {motivo}. Open it and press Do it now",


    "segno_fermo_aiuto_altro": "{motivo}. Open it and press Do it now",
    "dettagli_motivo_ultimo": "Last time",
    "segno_manca_perche": "The reason is missing",
    "segno_manca_perche_aiuto": "I understood it. Why you saved it I'll write when I understand the next item, nothing needed from you",
    "segno_manca_perche_aiuto_spento": "I understood it. Why you saved it I'll write the next time you press Do it now",

    "segno_a_vuoto": "Stopped by a mistake of mine",
    "segno_a_vuoto_aiuto": "It stopped because of a mistake of mine, the content isn't relevant. I restart it, nothing needed from you",
    "segno_a_vuoto_aiuto_acceso": "It stopped because of a mistake of mine, the content isn't relevant. It restarts on its own, one at a time",
    "segno_vietato_aiuto": "Instagram shows it only to those who log in with their account",
    "segno_sparito_aiuto": "It's gone. The copy and what I had understood remain",
    "segno_tocca_te": "Your turn",
    "segno_spento_aiuto": "I understand it when you press Do it now",
    "segno_lavora": "Working",


    "segno_agente_aperto": "Agent open in the terminal since {quando}",
    "segno_lavora_rileggo": "Rereading with your answer",
    "segno_lavora_trascrivo": "Transcribing your answer",

    "riquadro_scende": "I'm downloading it, then I understand it on my own. Nothing needed from you",
    "riquadro_sceso": "I downloaded it {quando}, then I understand it on my own. Nothing needed from you",
    "riquadro_capisco_scrivo": "I understood it {quando}, then I write why you saved it and it's your turn",
    "riquadro_si": "Your yes is in, I open and understand it on my own. Nothing else needed from you",
    "riquadro_aspetta_si": "I don't open it on my own, it's waiting for your yes",


    "riquadro_aspetta_si_domanda": "Shall I read this {cosa}?",
    "riquadro_aspetta_si_dopo": "With Do it now I open and understand it, then it's your turn",
    "riquadro_vietato": "Age-restricted. Instagram shows it only to those who log in with their account",
    "riquadro_sparito": "It's gone. The copy and what I had understood remain",
    "riquadro_perche_in_scrittura": "I understood it, now I'm writing why you saved it. Then it's your turn",
    "riquadro_perche_mancante": "I understood it. Why you saved it I'll write when I understand the next item, nothing needed from you",
    "riquadro_perche_mancante_spento": "I understood it. Why you saved it I'll write the next time you press Do it now",
    "riquadro_a_vuoto": "It stopped because of a mistake of mine, the content isn't relevant. I restart it, nothing needed from you",
    "riquadro_a_vuoto_acceso": "It stopped because of a mistake of mine, the content isn't relevant. It restarts on its own, one at a time",

    "ritmo_vietato_uno": "{cosa} age-restricted, Instagram shows it only to those who log in with their account",
    "ritmo_vietati": "{cosa} age-restricted, Instagram shows them only to those who log in with their account",
    "ritmo_a_vuoto_uno": "{cosa} stopped by a mistake of mine, I restart it",
    "ritmo_a_vuoto_uno_acceso": "{cosa} stopped by a mistake of mine, it restarts on its own",
    "ritmo_a_vuoto": "{cosa} stopped by a mistake of mine, I restart them one at a time",
    "ritmo_a_vuoto_acceso": "{cosa} stopped by a mistake of mine, they restart on their own, one at a time",



    "passo_capire": "Understand",
    "passo_scope": "Scope",
    "passo_contesto": "Context",
    "passo_ricerca": "Research",
    "passo_implementazione": "Implementation",
    "passo_test": "Test",
    "passo_di": "{k} of {n}",
    "adesso_titolo": "Now",
    "fatto_titolo": "Done",
    "dopo_titolo": "After",

    "scope_cosa_intendi": "What you mean",
    "scope_cosa_attivo": "What we do with it",
    "scope_dove_va": "Where it goes",
    "scope_dove_arrivare": "Where you want to get to",
    "scope_info_chiave": "Key info",
    "scope_su_cosa_poggia": "What it rests on",
    "scope_prima_dicevo": "Before I said this",
    "scope_le_tue_parole": "Your words",
    "scope_tipo": "What it is",
    "scope_progetto": "Project",
    "scope_area": "Area",
    "scope_confermato": "Confirmed by you {quando}",
    "scope_altra_domanda": "Another question",
    "scope_altre_domande": "Another {n} questions",


    "strada_riferimento": "I'll keep it as a reference",
    "strada_studio": "We'll study it",


    "strada_cosa_da_fare": "It's a to-do",
    "strada_cosa_da_fare_owner": "It's a to-do, you do it",
    "strada_cosa_da_fare_attivita": "I'll put it in Tasks",
    "strada_cosa_da_fare_team": "It's a to-do for the team",
    "strada_sviluppo": "We'll develop it",
    "strada_non_serve": "Not needed",
    "strada_con_tipo": "{strada}, {tipo}",
    "tipo_funzione": "a feature",
    "tipo_strumento": "a tool to try",
    "tipo_contenuto": "a piece of content",
    "tipo_negozio_sito": "a shop or a site",
    "tipo_idea_societa": "a business idea",
    "tipo_lettura": "a read",


    "giusto_avanti": "Right, go ahead",

    "giusto_sviluppo": "Right, let's develop it",
    "giusto_studio": "Right, let's study it",
    "giusto_tienilo": "Right, keep it as a reference",
    "giusto_non_serve": "Right, not needed",
    "giusto_attivita": "Right, put it in Tasks",
    "giusto_team": "Right, send it to the team",
    "manda_avanti": "Send and go ahead",
    "manda_conferma": "Send and confirm",

    "manda_e_rileggi_aiuto": "I reread with your answer, then you tell me if it's right",
    "manda_e_rileggi_parole_aiuto": "I reread with your words, then you tell me if it's right",
    "aiuto_giusto_avanti": "You confirm the scope and move to Context. There an agent in the terminal, when you start it, writes the steps and the work card",
    "aiuto_giusto_tienilo": "You confirm the scope. The item leaves the path and stays among the references, you reopen it whenever you want",
    "aiuto_giusto_non_serve": "You confirm it isn't needed. The item leaves the path and stays in the archive, you reopen it whenever you want",

    "aiuto_giusto_attivita": "The task is created right away in Tasks. If you later reopen the item the task stays, and if you don't need it you delete it in Tasks",
    "aiuto_giusto_team": "A task is created on ClickUp, in {lista}, and the item leaves the path. You reopen it whenever you want",

    "aiuto_giusto_delicato": "You confirm it's a to-do and the item leaves the path. For a sensitive one I don't create the task, you put it wherever you want",


    "giusto_cosa_da_fare": "Right, it's a to-do",

    "giusto_team_da_fare": "Right, it's a to-do for the team",
    "aiuto_giusto_senza_task": "You confirm it's a to-do. It stays here, and for now no task is created",
    "poi_scope_senza_task": "Then it stays here as a to-do, for now without a task",

    "adesso_task_manca": "It's a to-do, you confirmed it {quando}. There's no task yet",
    "adesso_task_manca_accesa": "It's a to-do, you confirmed it {quando}. There's no task yet, you create it from here",
    "adesso_task_manca_team": "It's a to-do for the team, you confirmed it {quando}. For now I don't create the ClickUp task",
    "segno_da_fare_aiuto_team": "It's a to-do for the team, for now I don't create the ClickUp task",
    "poi_task_manca": "Then the task is created and the item leaves the path",

    "segno_uscito_riferimento": "Kept as a reference",
    "segno_uscito_attivita": "In Tasks",
    "segno_uscito_clickup": "On ClickUp",
    "segno_uscito_letto": "Study read",
    "segno_uscito_non_serve": "Not needed",
    "segno_uscito_da_fare": "To do",
    "segno_da_leggere": "Card to read",
    "segno_da_leggere_aiuto": "The study card is written, you read it and press Read",
    "segno_da_fare": "To do",
    "segno_da_fare_aiuto": "It's a to-do, there's no task yet",
    "uscita_delicato": "It's a to-do, decided {quando}. It's sensitive, you put the task wherever you want",
    "uscita_senza_task": "It's a to-do, decided {quando}. For now I don't create the task, you reopen it whenever you want",
    "crea_task_attivita": "Create the task in Tasks",
    "aiuto_crea_task_attivita": "A task is created in Tasks, just one for this item",
    "crea_task_clickup": "Create the task on ClickUp",
    "aiuto_crea_task_clickup": "A task is created on ClickUp, in {lista}, just one for this item",
    "raddrizza": "Set it straight",
    "aiuto_raddrizza": "Tell me how it really is, in writing or by voice. You can change what we do with it, the project and the area, then I reread everything with your words",
    "campo_scope": "Answer, or tell me what I got wrong",

    "campo_scope_senza_domande": "Tell me what I got wrong, in writing or by voice",
    "manda": "Send",
    "aiuto_manda": "Your answer stays under its question and I read it before going ahead",
    "aiuto_fallo_adesso": "I download it if it's missing and understand it now, before the others and without opening anything for you. Then it's your turn",
    "apri_agente": "Open the agent in the terminal",
    "aiuto_apri_agente": "I open an agent on this item in the terminal. It reads what I understood, your words and the answers, writes the steps and the work card, and if it has questions it asks you there",
    "riapri_agente": "Reopen it in the terminal",
    "aiuto_riapri_agente": "I reopen an agent on this item in the terminal, it restarts from the steps already written and your answers",
    "guarda_terminale": "Look in the terminal",
    "aiuto_guarda_terminale": "Brings the terminal to the front on this item's agent. If it asks you something, you answer it there",
    "aiuto_leggi_scheda": "Opens the work card the agent wrote",
    "aiuto_leggi_ritorno": "Opens the results, what the agent did",
    "aiuto_letto": "Closes the path. The results stay here to reread",
    "riapri": "Reopen",
    "aiuto_riapri": "Goes back to Scope with what I had understood. A task already created stays where it is",
    "rifai": "Redo with the new scope",
    "aiuto_rifai": "The steps done with the old scope go back to be done with the new one. What was there stays readable",
    "tieni": "Keep as is",
    "aiuto_tieni": "The steps done stay as they are, I mark them seen with the new scope",
    "rivedi": "Review",



    "adesso_scope": "Here's what I understood. If it's right confirm it, if not set it straight",


    "adesso_scope_uscita": "Here's what I understood. If it's right confirm it, and if you change your mind later you reopen it. If not set it straight",

    "adesso_scope_resta": "Here's what I understood. If it's right confirm it and it stays here as a to-do, if not set it straight",
    "adesso_scope_perche_confermato": "What you mean you had already confirmed {quando}. Check if the rest fits too",

    "adesso_scope_accanto": "Here's what I understood. Check if it fits with your words below",
    "tutte_le_tue_parole": "All your words",
    "adesso_rileggo": "I'm rereading everything with your answer {quando}. When I'm done you find it here",

    "adesso_rileggo_in_fila": "I have your answer {quando}. I'll reread everything as soon as I can, when I'm done you find it here",
    "adesso_trascrivo": "I'm transcribing your voice answer, then I reread everything with your words",
    "adesso_contesto": "The scope is decided. An agent in the terminal reads what I understood and your words, writes the steps and the work card, and if it has questions it asks you there. It starts with your click",
    "adesso_ricerca": "The steps are written. The work card is missing, the agent in the terminal writes it when you reopen it",


    "adesso_terminale_lavora": "The agent in the terminal has been open since {quando}, to write the steps and the work card. If it has a question it asks you there",


    "adesso_terminale_scope_li": "While it's open you also change the scope there",


    "adesso_cambio_agente": "You changed the scope here {quando}. The agent in the terminal is open, tell it there and you decide together what to redo",
    "adesso_cambio_agente_altro": "The scope changed {quando}. The agent in the terminal is open, tell it there and you decide together what to redo",

    "adesso_cambio_agente_terminale": "You changed the scope with the agent in the terminal {quando}. What to redo of the steps already done you decide there",


    "adesso_agente_domanda": "The agent in the terminal has been open since {quando}. A question for you remains here",
    "adesso_agente_domande": "The agent in the terminal has been open since {quando}. {n} questions for you remain here",
    "aiuto_manda_agente": "Your answer stays under its question and reaches the agent in the terminal",

    "uscita_agente_aperto": "This item's agent is still open in the terminal",
    "adesso_scope_agente": "The scope changed {quando} and is waiting for your Right. If it doesn't add up, tell the agent in the terminal",

    "adesso_scope_agente_mai": "The scope is waiting for your Right. If it doesn't add up, tell the agent in the terminal",


    "adesso_cambio_lavoro": "You changed the scope {quando} and the work in the terminal has already started. If it needs redoing tell the agent there, or keep what's there",
    "adesso_cambio_lavoro_riletto": "I rewrote the scope with your answer {quando} and the work in the terminal has already started. If it needs redoing tell the agent there, or keep what's there",
    "adesso_cambio_lavoro_riscritto": "I rewrote the scope {quando} and the work in the terminal has already started. If it needs redoing tell the agent there, or keep what's there",

    "adesso_scope_lavoro": "Tell me if I understood right. The work in the terminal has already started",
    "aiuto_giusto_lavoro": "You confirm the scope. The work in the terminal has already started, right after you choose whether to tell the agent or keep what's there",
    "aiuto_giusto_agente": "You confirm the scope as it is now. The agent in the terminal stays open, what to redo you decide there",
    "coda_scheda_agente": "If you want to change something first, the agent that wrote it is still open in the terminal",
    "proposta_coda_agente": "If you want it, tell the agent in the terminal",
    "adesso_terminale_chiuso": "The agent in the terminal closed {quando} before finishing. You reopen it and it restarts from what it has already written",

    "adesso_ti_aspetta": "The agent in the terminal has been waiting for you since {quando}",
    "adesso_ti_aspetta_cosa": "The agent in the terminal has been waiting for you since {quando}. {cosa}",
    "adesso_terminale_chiuso_aspettava": "The agent in the terminal closed {quando} while waiting for you. Reopen it and it asks you again for what it needs",
    "segno_ti_aspetta": "Waiting for you in the terminal",
    "adesso_domanda": "Before going ahead I need an answer",
    "adesso_domande": "Before going ahead I need {n} answers",
    "adesso_pronta": "The work card is ready. With Start a new agent in the terminal does the work written there and writes the results here",

    "permessi_costruzione": "Works on a copy, without mail, Slack and CRM",
    "permessi_ricerca": "Reads, searches the web and writes files, without mail, Slack and CRM",
    "adesso_avviata": "The work started {quando}, an agent in the terminal is working on it. If it has a question it asks you there",
    "adesso_avviata_chiuso": "The work's agent closed {quando} before finishing. What it did so far is in the results",

    "adesso_avviata_chiuso_vuoto": "The work's agent closed {quando} before finishing and wrote nothing",
    "adesso_arrivata": "The work finished {quando}. The results are here to read",
    "adesso_letto": "You read the results {quando}. The path is finished",
    "adesso_cambio": "You changed the scope. The steps done with the old one stay readable, choose whether to redo them",

    "adesso_cambio_riletto": "I rewrote the scope with your answer {quando}. The steps done with the old one stay readable, choose whether to redo them",

    "adesso_cambio_riscritto": "I rewrote the scope. The steps done with the old one stay readable, choose whether to redo them",

    "poi_capire": "Then it's your turn. I tell you what I understood and where I'd put it, you tell me if it's right",

    "poi_scope_avanti": "Then nothing starts on its own in the terminal. The agent that writes the steps you open yourself, and until then you can still set the scope straight",
    "poi_scope_riferimento": "Then it leaves the path and stays among the references",
    "poi_scope_non_serve": "Then it leaves the path and stays in the archive",

    "poi_scope_attivita": "The task is created right away in Tasks. If you later reopen the item the task stays, and if you don't need it you delete it in Tasks",
    "poi_scope_team": "Then the task is created on ClickUp and the item leaves the path",
    "poi_scope_delicato": "Then it leaves the path as a to-do, you put the task yourself",
    "poi_contesto": "Then Research. The same agent writes the work card",
    "poi_ricerca": "Then Implementation. With the card ready press Start",

    "poi_contesto_studio": "Then Research. The same agent searches and writes the study card",
    "poi_ricerca_studio": "Then you read the card, and with Read the study is finished",
    "poi_studio_letto": "With Read the study is finished and leaves the path",
    "adesso_studio_scheda": "The agent in the terminal wrote the study card {quando}. Read it, then press Read",
    "aiuto_letto_studio": "The study is finished and leaves the path. The card stays here to reread, you reopen it whenever you want",
    "adesso_contesto_studio": "The scope is decided. An agent in the terminal reads what I understood and your words, writes what to search for and where, and if it has questions it asks you there. It starts with your click",
    "adesso_ricerca_studio": "The steps are written. The study card is missing, the agent in the terminal writes it when you reopen it",
    "adesso_terminale_lavora_studio": "The agent in the terminal has been open since {quando}, to search and write the study card. If it has a question it asks you there",
    "poi_implementazione": "Then Test. The work's results come here, to read",
    "poi_test": "With Read the path is finished",

    "dopo_capire": "I read the content and understand it",
    "dopo_scope": "I tell you what I understood and where it goes, you tell me if it's right",
    "dopo_contesto": "Where it goes with us and how, the steps",
    "dopo_ricerca": "The work card",

    "dopo_contesto_studio": "What to search for and where, the steps",
    "dopo_ricerca_studio": "The card with what the agent finds, to read",
    "fatto_ricerca_studio": "The study card is written",
    "dopo_implementazione": "The work on the card, starts with your click",
    "dopo_test": "The work's results, to read",

    "fatto_capire": "Your words “{parole}”",
    "fatto_capire_senza": "I saw the content and understood it",
    "fatto_contesto": "The steps are written",
    "fatto_ricerca": "The work card is written",
    "fatto_implementazione": "The work is finished",
    "fatto_test": "You read the results",
    "fatto_saltato": "Not done, the work went ahead anyway",

    "uscita_riferimento": "Kept as a reference {quando}. It's off the path, you reopen it whenever you want",
    "uscita_non_serve": "Not needed, decided {quando}. It stays in the archive, you reopen it whenever you want",
    "uscita_clickup": "Sent to ClickUp {quando}, the work goes on there",
    "uscita_attivita": "In Tasks since {quando}. The work goes on there",

    "uscita_attivita_chiusa": "In Tasks since {quando}, and you closed it",
    "uscita_attivita_eliminata": "You had deleted the task from Tasks",
    "uscita_letto": "Read {quando}. The path is finished",
    "titolo_letto": "Read",
    "uscita_task_clickup": "On ClickUp, in {lista}",
    "uscita_task_attivita": "In Tasks",

    "uscita_task_attivita_eliminata": "Deleted from Tasks",
    "segno_uscito_eliminata": "Task deleted",

    "rifalla": "Redo it",
    "aiuto_rifalla": "A new task is created in Tasks. The deleted one stays among the deleted",

    "cambio_titolo": "Change the scope",
    "cambio_adesso_e": "The current scope",
    "cambio_rifa": "Done {quando}, with the new scope it goes back to be done",
    "cambio_rifa_in_corso": "In progress since {quando}, with the new scope it goes back to be done",

    "cambio_rifa_anteprima": "Done {quando}. If you change the scope, you choose whether to redo it",
    "cambio_rifa_in_corso_anteprima": "In progress since {quando}. If you change the scope, the agent finishes anyway and you choose whether to redo it",
    "cambio_resta": "Understand, your words and your answers stay as they are. What was there stays readable, nothing gets deleted",

    "segno_da_confermare": "To confirm",
    "segno_da_confermare_aiuto": "I proposed it to you {quando}. {strada}",

    "segno_nuovo_da_confermare": "New, to confirm",


    "segno_strada_sviluppo": "Shall we develop it?",
    "segno_strada_studio": "Shall we study it?",
    "segno_strada_riferimento": "Shall I keep it as a reference?",

    "segno_strada_riferimento_corta": "Keep it?",
    "segno_strada_team_corta": "For the team?",
    "segno_strada_team": "Is it a to-do for the team?",
    "segno_strada_attivita": "Shall I put it in Tasks?",
    "segno_strada_non_serve": "Not needed?",
    "segno_strada_cosa_da_fare": "Is it a to-do?",
    "segno_domanda_accanto": "{domanda} · {accanto}",
    "segno_dal": "since {quando}",
    "segno_da_scegliere": "To choose",

    "segno_da_dire": "To tell the agent",
    "segno_da_scegliere_aiuto": "You changed the scope, choose whether to redo the steps",

    "segno_da_scegliere_aiuto_riletto": "I rewrote the scope with your answer, choose whether to redo the steps",
    "segno_da_scegliere_aiuto_riscritto": "I rewrote the scope, choose whether to redo the steps",
    "segno_task_da_creare": "Task to create",
    "segno_si_e_fermato": "It stopped",
    "segno_una_domanda": "A question for you",
    "segno_domande": "{n} questions for you",
    "segno_da_far_partire": "To start",
    "segno_contesto_aiuto": "The scope is decided, the agent in the terminal starts with your click",
    "segno_ricerca_aiuto": "The steps are written, the agent in the terminal writes the card when you reopen it",
    "segno_da_avviare": "To start",
    "segno_da_avviare_aiuto": "The card is ready, it starts with Start",
    "segno_ritorno": "Results to read",
    "segno_ritorno_aiuto": "The results are to read",
    "segno_passo": "{nome}, {di}",


    "testa_a_te": "{cosa} new waiting for you",
    "testa_a_te_uno": "{cosa} new waiting for you",
    "testa_altri_a_te": "Another {n} waiting for you",
    "testa_altro_a_te": "One more waiting for you",
    "dettagli_a_te": "Waiting for you",

    "testa_tutti": "{n} waiting for you",
    "testa_tutti_uno": "1 waiting for you",

    "testa_nuovi": "{n} new items to confirm",
    "testa_nuovi_uno": "{n} new item to confirm",
    "testa_nuovi_corta": "{n} to confirm",
    "testa_dopo_da_far_partire": "{n} to start",
    "testa_dopo_da_far_partire_uno": "{n} to start",
    "testa_dopo_domanda": "{n} waiting for an answer from you",
    "testa_dopo_domanda_uno": "{n} waiting for an answer from you",
    "testa_dopo_domanda_corta": "{n} with a question",
    "testa_dopo_da_leggere": "{n} cards to read",
    "testa_dopo_da_leggere_uno": "{n} card to read",
    "testa_dopo_da_avviare": "{n} cards to start",
    "testa_dopo_da_avviare_uno": "{n} card to start",
    "testa_dopo_ritorno": "{n} results to read",
    "testa_dopo_ritorno_uno": "{n} result to read",
    "testa_dopo_da_scegliere": "{n} scope changes to choose",
    "testa_dopo_da_scegliere_uno": "{n} scope change to choose",
    "testa_dopo_da_scegliere_corta": "{n} to choose",
    "testa_dopo_da_dire": "{n} scope changes to tell the agent",
    "testa_dopo_da_dire_uno": "{n} scope change to tell the agent",
    "testa_dopo_task_da_creare": "{n} tasks to create",
    "testa_dopo_task_da_creare_uno": "{n} tasks to create",
    "testa_dopo_fermo": "{n} stuck, to restart",
    "testa_dopo_fermo_uno": "{n} stuck, to restart",
    "testa_dopo_fermo_corta": "{n} stuck",
    "testa_dopo_misti": "{n} waiting for you in the other steps",
    "testa_dopo_misti_uno": "{n} waiting for you in another step",
    "testa_dopo_misti_corta": "{n} in the other steps",
    "dettagli_a_te_riga": "I tell you what I understood, you tell me if it's right",
    "dettagli_a_te_misti": "Among {cosa}",
    "attesa_da_confermare": "proposals to confirm",
    "attesa_domanda": "questions",
    "attesa_da_far_partire": "steps to start",
    "attesa_da_avviare": "cards to start",
    "attesa_ritorno": "results to read",
    "attesa_da_scegliere": "scope changes to choose",
    "attesa_da_dire": "scope changes to tell the agent",
    "attesa_task_da_creare": "tasks to create",
    "attesa_da_leggere": "cards to read",
    "attesa_fermo": "agents to restart",
    "testa_rileggi_aiuto": "I read your DM now. What arrives I download and understand on my own",


    "colonna_adesso": "Now",
    "colonna_fatto": "Done",
    "colonna_dopo": "After",
    "raddrizza_chiudi": "Leave as is",
    "scope_parole_di_owner": "Your words",
    "scope_scegli_strada": "What we do with it",
    "scope_scegli_tipo": "What it is",
    "scope_scegli_progetto": "Project",
    "scope_scegli_area": "Area",
    "passo_corto": "Step {k} of {n}",
    "aiuto_passo_corto": "This item's steps, from Understand to Test",
    "cambio_se_lo_cambi": "If you change it",
    "uscita_titolo": "Off the path",
    "invia_campo": "Send",


    "proposta_in_attesa": "{quando}, while rereading, I proposed a different scope.",
    "proposta_in_attesa_senza_data": "While rereading I proposed a different scope.",
    "proposta_progetto": "for {v}",

    "proposta_invece_di": "{strada} instead of {v}",
    "invece_riferimento": "keep it as a reference",
    "invece_studio": "study it",
    "invece_sviluppo": "develop it",
    "invece_cosa_da_fare": "make it a to-do",
    "invece_non_serve": "leave it aside",
    "proposta_area": "area {v}",
    "proposta_chi_owner": "you do it",
    "proposta_chi_team": "the team does it",
    "proposta_delicato": "it's sensitive",
    "proposta_non_delicato": "it's no longer sensitive",
    "prendi_proposta": "Take the proposal",
    "aiuto_prendi_proposta": "The scope becomes the proposed one. Until you take it, it stays the one you confirmed",



    "imp_titolo": "Inspiration settings",


    "imp_acceso_nome": "I understand the items that arrive on my own",
    "imp_acceso_si": "I do it while the terminal or the app are open. The ones waiting for your yes and the ones I can't open or understand stay put.",
    "imp_acceso_no": "I read and understand only when you ask me.",
    "imp_leggi_dm_nome": "I read your DM on my own",

    "imp_leggi_dm_si": "I read it about every {n} minutes, while the terminal is open.",

    "imp_leggi_dm_no": "I read the DM only when you press “{parola}”.",
    "imp_leggi_dm_dipende": "It works only with the row above turned on.",

    "imp_task_in_attivita_nome": "I put the items' tasks in Tasks",
    "imp_task_in_attivita_si": "The task is created in Tasks when you start an item, confirm a to-do or ask for it.",
    "imp_task_in_attivita_no": "No task is created in Tasks from the items.",

    "imp_nuovo_giorni_nome": "How long it stays new",
    "imp_nuovo_giorni_frase": "An item waiting for you stays new for {n} days, and after that too until you answer or decide something.",
    "imp_nuovo_giorni_frase_uno": "An item waiting for you stays new for 1 day, and after that too until you answer or decide something.",
    "imp_giorno": "{n} day",
    "imp_giorni": "{n} days",

    "imp_task_su_clickup_nome": "I put the team's tasks on ClickUp",
    "imp_task_su_clickup_frase": "Not for now. You decide whether the team's tasks are created on ClickUp when you confirm, without you sending them.",
    "imp_task_su_clickup_acceso": "The team's tasks are created on ClickUp.",


    "imp_traccia": "{cosa} by {chi} {quando} at {ora}",
    "imp_traccia_acceso": "On",
    "imp_traccia_spento": "Off",

    "imp_traccia_cambiato": "Changed",
    "imp_traccia_te": "you",
    "imp_traccia_me": "me",
    "imp_accendi": "Turn on",
    "imp_spegni": "Turn off",
    "imp_cambia": "Change",




    "lista_titolo": "These {n} you can confirm together",

    "lista_titolo_uno": "This one you can confirm from here",

    "lista_frase_riferimento": "Shall I keep them as a reference?",
    "lista_poi_riferimento": "They leave the path and stay among the references, you reopen them whenever you want",
    "lista_frase_studio": "Shall we study them?",
    "lista_poi_studio": "After that nothing starts on its own, you start them whenever you want",
    "lista_frase_sviluppo": "Shall we develop them?",
    "lista_poi_sviluppo": "After that nothing starts on its own, you start them whenever you want",


    "lista_giusto_studio": "Right, let's study these {n}",
    "lista_giusto_studio_uno": "Right, let's study it",
    "lista_giusto_sviluppo": "Right, let's develop these {n}",
    "lista_giusto_sviluppo_uno": "Right, let's develop it",
    "lista_giusto_riferimento": "Right, keep these {n} as a reference",
    "lista_giusto_riferimento_uno": "Right, keep it as a reference",
    "lista_si_aiuto": "I confirm only the ticked ones. Afterwards you can undo the whole group",
    "lista_dedotto_niente": "You didn't write me anything, I inferred it",
    "lista_dedotto_parole": "I don't read it in your words, I inferred it",

    "lista_senza_spunta_dubbio_parola": "In your words there's a “{parola}”, you decide whether to tick it",
    "lista_senza_spunta_dubbio": "In your words there's a doubt, you decide whether to tick it",
    "lista_senza_spunta_persona_nome": "You mention “{chi}”, you decide whether to tick it",
    "lista_senza_spunta_persona": "Maybe you mention someone, you decide whether to tick it",

    "lista_domande_dopo": "After the Right I ask you {n} questions before starting",
    "lista_domande_dopo_uno": "After the Right I ask you one question before starting",
    "lista_poi_con_domande": "For {k} of the {n}, after the Right I ask you a few questions before starting",
    "lista_poi_con_domande_tutti": "For all {n}, after the Right I ask you a few questions before starting",
    "lista_poi_con_domande_uno": "For one of the {n}, after the Right I ask you a few questions before starting",

    "lista_fuori": "The other {n} you look at one by one",
    "lista_fuori_uno": "One more remains, open it and decide there",

    "lista_confermati_studio": "Confirmed {n} to study, {quando}",
    "lista_confermati_studio_uno": "Confirmed 1 to study, {quando}",
    "lista_confermati_sviluppo": "Confirmed {n} to develop, {quando}",
    "lista_confermati_sviluppo_uno": "Confirmed 1 to develop, {quando}",
    "lista_confermati_riferimento": "Confirmed {n} as a reference, {quando}",
    "lista_confermati_riferimento_uno": "Confirmed 1 as a reference, {quando}",
    "lista_confermati": "Confirmed {n} {quando}",
    "lista_confermati_uno": "Confirmed 1 {quando}",
    "lista_annulla": "Undo the whole group",
    "lista_annulla_aiuto": "They go back to be confirmed, along with the reason you confirmed together",

    "lista_annulla_non_tutti": "{k} stay confirmed, you already worked on them",
    "lista_annulla_non_tutti_uno": "1 stays confirmed, you already worked on it",
    "lista_annullati": "You brought them all back to be confirmed",

    "testa_pronti": "{n} to start whenever you want",
    "testa_pronti_uno": "1 to start whenever you want",
    "pronti_parola": "to start",
}



FASI = (
    (
        "perche",
        "The reason",
        "I wrote why I think you saved it. You confirm, correct, or say Let's work on it.",
        "No item to confirm, for now.",
    ),
    (
        "lavorazione",
        "In progress",
        "In the terminal I write the steps and ask you the questions.",
        "Nothing in progress.",
    ),
    (
        "pronta",
        "Ready",
        "The work card is ready, it starts when you press Start.",
        "No card ready to start.",
    ),
    ("avviata", "Started", "The work is in progress in the terminal.", "No work in progress."),
    (
        "arrivata",
        "Arrived",
        "The work is in, there are results to read.",
        "No results to read.",
    ),
    (
        "tenuta",
        "Set aside",
        "Your inspirations and things to keep, with no work.",
        "Nothing set aside.",
    ),

    (
        "in_clickup",
        "In ClickUp",
        "Sent to ClickUp with the task, the work goes on there.",
        "Nothing sent to ClickUp.",
    ),
    (
        "scartata",
        "Discarded",
        "Understood, but not needed. They stay in the archive and you bring them back whenever you want.",
        "Nothing discarded.",
    ),
    ("da_capire", "To understand", "I haven't seen or understood the content yet.", "Nothing to understand."),
    ("tutti", "All items", "All the items.", "No item yet."),
)

ASPETTANO = {"uno": "One is waiting for you.", "tanti": "{n} are waiting for you."}

TOCCA = {
    "te": "Your turn",
    "te_perche": "Your turn, tell me if the reason is right",
    "te_perche_domanda": "Your turn, the reason and a question",
    "te_perche_domande": "Your turn, the reason and {n} questions",
    "te_domanda": "Your turn, a question",
    "te_domande": "Your turn, {n} questions",
    "te_ci_lavoriamo": "Your turn, press Let's work on it and in the terminal I write the steps",
    "te_pronta": "Your turn, the card is ready, it starts when you press Start",
    "te_arrivata": "Your turn, there are results to read",
    "te_chiusa": "Your turn, the agent in the terminal closed without finishing",
    "pipeline": "I haven't written the reason yet, I'll write it on my own",
    "sessione": "I'm working on it in the terminal, I started {quando}",
    "agente": "The work started {quando}, in the terminal",
    "tenuta": "Set aside {quando}, no work",
    "scartata": "Discarded {quando}, it stays in the archive",
    "in_clickup": "Sent to ClickUp {quando}, the work goes on there",
    "letto": "Read {quando}",
    "da_capire": "I haven't seen or understood the content yet",
    "visto_da_capire": "I saw the content {quando}, I still have to understand it",
    "comprensione": "I'm understanding it in the terminal, I started {quando}",
    "comprensione_sottofondo": "I'm understanding it, I started {quando}. Then it's your turn",
    "comprensione_ferma": "{motivo}",
    "comprensione_chiusa": "I was interrupted before finishing understanding it",

    "rilettura": "I'm rereading everything with your answer {quando}",

    "rilettura_in_fila": "I have your answer {quando}, I'll reread everything as soon as I can",
    "": "",
}

DOPO = {
    "da_capire": "When I've seen it I write the reason and it's your turn",
    "da_capire_fallo": "Press Do it now. I download the content, understand it and write the reason, then it's your turn",
    "visto_da_capire": "Press Do it now. I understand it and write the reason, then it's your turn",
    "comprensione": "When I've understood it and written the reason, it's your turn",
    "comprensione_ferma": "Press Do it now again",

    "comprensione_ferma_riprovo": "I'll try again on my own, or press Do it now",
    "da_capire_da_solo": "As soon as I've downloaded it I understand it on my own, then it's your turn",
    "visto_da_capire_da_solo": "I understand it on my own, then it's your turn",
    "perche_pipeline": "Then you confirm or correct it",
    "rilettura": "When I'm done you find the reread reason at the bottom, with Right and Correct, and it's your turn",

    "rilettura_in_fila": "I'll reread everything as soon as I can, then you find the reread reason at the bottom, with Right and Correct, and it's your turn",

    "rilettura_confermato": "When I'm done you find at the bottom where you want to get to and the questions redone with your words, then Let's work on it",
    "rilettura_confermato_in_fila": "I'll reread everything as soon as I can, then you find at the bottom where you want to get to and the questions redone with your words, and after that Let's work on it",
    "perche_te": "With Right or Correct the reason is decided, then Let's work on it opens an agent in the terminal that writes the steps and the card",
    "perche_te_domande": "With Right and the answers, Let's work on it opens an agent in the terminal that writes the steps and the card",
    "lavorazione_apri": "In the terminal I ask you the questions needed and write the card, then press Start",
    "lavorazione_domande_senza_sessione": "Answer below, then Let's work on it opens an agent in the terminal that writes the steps and the card",
    "lavorazione_domande_con_sessione": "With the answers I resume in the terminal and write the card, then press Start",
    "lavorazione_sessione": "When the card is ready it's your turn, press Start",
    "lavorazione_chiusa": "Let's work on it reopens the item's agent in the terminal",
    "pronta": "Start opens the work agent in the terminal, which does what the card says and writes the results here",
    "avviata_agente": "When it finishes you find the results here. If it has a question it asks you there",
    "avviata_te": "With the answer the work resumes",
    "arrivata": "Read closes the path",
}


PERCORSO = {
    "titolo": "The path",
    "fatto": "Done",
    "adesso": "Now",
    "poi": "After",
    "da_capire": "To understand",

    "nomi": {
        "perche": "The reason",
        "lavorazione": "In progress",
        "pronta": "Ready",
        "avviata": "Started",
        "arrivata": "Arrived",
    },
    "da_capire_adesso": "I still have to see the content and understand it. Then I propose the reason",
    "perche_fatto": "Confirmed {quando}",
    "perche_saltato": "Skipped with Let's work on it",
    "perche_adesso": "Tell me if the reason is right. Confirm, correct, or press Let's work on it",
    "perche_rileggo": "I'm rereading with your answer and rewriting the reason. Then you confirm or correct",

    "perche_rileggo_in_fila": "I have your answer, I'll reread everything as soon as I can and rewrite the reason. Then you confirm or correct",
    "perche_poi": "I propose why you saved it, you confirm or correct",
    "lavorazione_fatto": "The work card is written",
    "lavorazione_apri": "Press Let's work on it. In the terminal I read what I understood and your words, ask you the questions and write the card",
    "lavorazione_domanda": "Answer the question here, in writing or by voice. Then I write the card",
    "lavorazione_domande": "Answer the {n} questions here, in writing or by voice. Then I write the card",
    "lavorazione_scrive": "In the terminal I'm writing the work card",

    "lavorazione_poi": "I ask you the questions needed and write the work card",
    "pronta_fatto": "Started {quando}",
    "pronta_adesso": "The card is ready. Press Start and the agent starts, with the card, your answers and your audios",
    "pronta_poi": "When the card is ready press Start",
    "avviata_fatto": "Finished {quando}",
    "avviata_adesso": "The agent is working in the terminal with the card, your answers and your audios, since {quando}",
    "avviata_poi": "The work on the card, with your answers and your audios",
    "arrivata_fatto": "Read {quando}",
    "arrivata_adesso": "The results are here, read them",
    "arrivata_poi": "Read here what it did",
}


FUORI_DAL_PERCORSO = ("tenuta", "scartata", "in_clickup")

SMISTA = {
    "titolo": "Where it goes",
    "si": "Yes",
    "cambia": "Change",
    "rimetti": "Put back",
    "apri_task": "Open the task",
    "aiuto_si": "I send it where it says here. For to do, backlog and roadmap a task is created on ClickUp",
    "aiuto_cambia": "Pick a different outcome, and that's already your confirmation",
    "aiuto_rimetti": "Goes back to how it was. A task already created stays on ClickUp",
    "in_lista": "In {lista}",
    "resta_qui": "Stays here in Inspiration, with Let's work on it",
    "riferimento": "I keep it as a reference, off the path",
    "archivio": "Leaves the path and stays in the archive",
    "progetto": "Project {progetto}",
    "fatto_task": "Sent to ClickUp {quando}, in {lista}",
    "fatto_task_senza": "Sorted {quando}, I didn't create the task",
    "fatto_tenuto": "Kept as a reference {quando}",
    "fatto_scartato": "Discarded {quando}, it stays in the archive",
    "fatto_lavorazione": "To look into here, decided {quando}",
}



_SMISTA_LUCCHETTO = threading.Lock()


def _smista_regole():
    ""


    nome = "sb_inspiration_smista"
    if nome in sys.modules:
        return sys.modules[nome]
    with _SMISTA_LUCCHETTO:
        if nome not in sys.modules:
            import importlib.util

            spec = importlib.util.spec_from_file_location(
                nome, os.path.join(os.path.dirname(os.path.abspath(__file__)), f"{nome}.py")
            )
            m = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(m)
            sys.modules[nome] = m
        return sys.modules[nome]


def _quando_smistato(pc: dict) -> str:
    return str(pc.get("_smistato_quando") or "")


def _maiuscola(t: str) -> str:
    return t[:1].upper() + t[1:] if t else t


def _smistamento(v: dict, L: dict, pc: dict, fase: str) -> dict:
    ""

    S = _smista_regole()
    sm = L.get("smistamento") or {}
    prop = sm.get("proposta") or {}
    conf = sm.get("confermato") or {}
    progetto = (
        str(pc.get("progetto") or "")
        or str((v.get("destinazione") or {}).get("progetto") or "")
        or "altro"
    )
    vuoto = {
        "c_e": False,
        "confermato": False,
        "azioni": {"si": False, "cambia": False, "rimetti": False},
    }
    gesti_qui = fase in ("perche", "lavorazione", "pronta", "tenuta")
    if not (prop or conf):


        if not gesti_qui:
            return vuoto


        perche_scritto = bool(pc.get("testo"))
        return {
            **vuoto,
            "c_e": perche_scritto,
            "esito": "",
            "riga_esito": "",
            "riga_dove": "",
            "esiti": [{"id": e, "parole": _maiuscola(S.ESITI_PAROLE[e])} for e in S.ESITI],
            "azioni": {"si": False, "cambia": perche_scritto, "rimetti": False},
            "parole": SMISTA,
        }
    if conf:
        esito = str(conf.get("esito") or "")
        quando = _quando(conf.get("quando"))
        if esito in S.CON_TASK and conf.get("task"):
            fatto = _frase(
                SMISTA["fatto_task"], quando=quando, lista=conf.get("lista") or "ClickUp"
            )
        elif esito in S.CON_TASK:
            fatto = _frase(SMISTA["fatto_task_senza"], quando=quando)
        else:
            fatto = _frase(
                SMISTA[
                    {"tenuto": "fatto_tenuto", "scartato": "fatto_scartato"}.get(
                        esito, "fatto_lavorazione"
                    )
                ],
                quando=quando,
            )
        return {
            "c_e": True,
            "confermato": True,
            "esito": esito,
            "riga_esito": _maiuscola(S.ESITI_PAROLE.get(esito, esito)),
            "riga_dove": fatto,
            "riga_nota": "",
            "riga_motivo": "",
            "task": str(conf.get("task") or ""),
            "esiti": [],
            "azioni": {"si": False, "cambia": False, "rimetti": True},
            "parole": SMISTA,
        }
    esito = str(prop.get("esito") or "")
    d = S.destinazione(
        esito,
        progetto,
        str(prop.get("attivita") or ""),
        str(prop.get("chi_esegue") or "team"),
        bool(prop.get("delicato")),
    )
    if d["crea_task"]:
        dove = _frase(SMISTA["in_lista"], lista=" / ".join(d["percorso"]))
    elif esito in S.CON_TASK:
        dove = ""
    else:
        dove = {"tenuto": SMISTA["riferimento"], "scartato": SMISTA["archivio"]}.get(
            esito, SMISTA["resta_qui"]
        )
    return {
        "c_e": True,
        "confermato": False,
        "esito": esito,
        "riga_esito": _maiuscola(S.ESITI_PAROLE.get(esito, esito)),
        "riga_dove": dove,
        "riga_nota": d["nota"],
        "riga_motivo": str(prop.get("motivo") or ""),
        "progetto": progetto,
        "task": "",
        "esiti": [
            {"id": e, "parole": _maiuscola(S.ESITI_PAROLE[e])} for e in S.ESITI if e != esito
        ],
        "azioni": {"si": gesti_qui, "cambia": gesti_qui, "rimetti": False},
        "parole": SMISTA,
    }



DA_RILETTURA = "reread after your answer"
SCHEDA_STATO = {
    "te": "Your turn",
    "te_domande": "Your turn · {domande}",
    "confermato": "Confirmed",
    "confermato_domande": "Confirmed · {domande}",
    "una_domanda": "one question",
    "n_domande": "{n} questions",
    "in_trascrizione": "Voice answer being transcribed",
    "rileggo": "Rereading with your answer",
    "pronta": "Card ready",
    "avviata": "Working",
    "arrivata": "Results to read",
    "letto": "Read",
    "tenuta": "Set aside",
    "scartata": "Discarded",
    "in_clickup": "In ClickUp",
    "": "",
}
SERVE_PER = {
    "perche": "I need it to understand the reason",
    "lavorazione": "I need it to start",
    "permesso": "It's your decision",
    "dato": "Only you know it",
}

STATI_AUDIO = {
    "da trascrivere": "in_trascrizione",
    "trascritto": "trascritta",
    "trascritta": "trascritta",
    "senza parlato": "senza_parlato",
    "non riuscita": "non_riuscita",
    "da verificare": "da_verificare",
}

IN_VIAGGIO = ("in_trascrizione", "aspetta_memoria")

RIAPRONO = ("non_riuscita", "senza_parlato", "da_verificare")
SICUREZZA = {
    "alta": "I'm sure of it",
    "media": "It's a reasonable reading",
    "bassa": "I'm guessing",
}
ESITI = (
    ("ispirazione", "an inspiration of yours"),
    ("da tenere", "to set aside"),
    ("flusso", "a flow to create"),
    ("funzione", "a feature to add"),
    ("contenuto", "a piece of content to make"),
    ("altro", "other"),
)
PERMESSI = {
    "costruzione": "It will be able to use the terminal to build and test on a working copy, without mail, Slack and CRM.",
    "ricerca": "It will read, search the web and write files, without the terminal, mail, Slack and CRM.",
}


FRASI = {
    "vietato": "Age-restricted",
    "vietato_aiuto": "Age-restricted, Instagram shows it only to those who log in with their account.",
    "sparito": "It's gone",
    "sparito_aiuto": "It's gone. The copy and what I had understood remain.",
    "non_visto_aiuto": "The content hasn't been seen yet, the card comes only from the caption.",
    "online": "Online, last time {quando}.",
    "online_senza_data": "Online.",
    "da_ricontrollare": "To check again, last time it wasn't showing.",
    "mai_controllato": "I haven't checked yet whether it's online.",
    "non_raggiungibile": "Unreachable at the last check.",

    "audio": "Your audio",
    "audio_durata": "of {durata}",
    "audio_da_trascrivere": "to transcribe",
    "audio_senza_parlato": "no speech",
    "audio_non_riuscito": "the transcription failed",
    "dal_tuo_audio": "from your audio",
    "secondi": "{n} seconds",
    "un_secondo": "one second",
    "meno_di_un_secondo": "less than a second",
    "minuti": "{n} minutes",
    "un_minuto": "one minute",
    "visto": "Content seen",
    "mancano": "{cosa} are missing.",
    "manca": "{cosa} is missing.",
    "senza_titolo": "{tipo} from {dove}",
    "salvato": "saved {quando}",
}



SCHEDE = (
    {
        "id": "da_decidere",
        "nome": "To decide",
        "stati": ("da decidere",),
        "aiuto": "The understood items waiting for a decision from you.",
        "vuota": "Nothing to decide right now.",
    },
    {
        "id": "in_lavorazione",
        "nome": "In progress",
        "stati": ("buttato dentro", "da capire", "capito"),
        "aiuto": "Arrived, to understand or understood. My turn.",
        "vuota": "Nothing in progress.",
    },
    {
        "id": "attivita",
        "nome": "Tasks",
        "stati": ("attività", "promosso"),
        "aiuto": "Turned into a task or an agent's work.",
        "vuota": "No item has become a task yet.",
    },
    {
        "id": "riferimenti",
        "nome": "References",
        "stati": ("riferimento",),
        "aiuto": "Kept as a reference. Nothing is discarded.",
        "vuota": "No reference yet.",
    },
    {
        "id": "tutti",
        "nome": "All",
        "stati": (),
        "aiuto": "All the items, with the understood ones separated from those still to see.",
        "vuota": "No item yet.",
    },
)



TIPI = {
    "video": ("Video", "play.rectangle.fill", "verticale", "Video not seen"),
    "post": ("Post", "photo.on.rectangle", "verticale", "Post not seen"),
    "pagina": ("Page", "link", "orizzontale", "Page not seen"),
    "articolo": ("Article", "link", "orizzontale", "Article not read"),
    "immagine": ("Image", "photo", "orizzontale", "Image not seen"),
    "screenshot": ("Screenshot", "camera.viewfinder", "orizzontale", "Screenshot not seen"),
    "nota": ("Note", "text.quote", "orizzontale", "Note not read"),
    "file": ("File", "doc", "orizzontale", "File not seen"),
    "segnalibro": ("Bookmark", "bookmark", "orizzontale", "Bookmark not seen"),
}

PLURALI = {
    "video": "videos",
    "post": "posts",
    "pagina": "pages",
    "articolo": "articles",
    "immagine": "images",
    "screenshot": "screenshots",
    "nota": "notes",
    "file": "files",
    "segnalibro": "bookmarks",
}
PIATTAFORME = {
    "instagram": "Instagram",
    "linkedin": "LinkedIn",
    "x": "X",
    "twitter": "X",
    "tiktok": "TikTok",
    "youtube": "YouTube",
    "web": "Web",
    "slack": "Slack",
}


def _dict(x) -> dict:
    ""

    return x if isinstance(x, dict) else {}


def _leggi(percorso: str):
    try:
        with open(percorso, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def _leggi_righe(percorso: str) -> list:
    out = []
    try:
        with open(percorso, encoding="utf-8") as fh:
            for riga in fh:
                riga = riga.strip()
                if riga:
                    try:
                        out.append(json.loads(riga))
                    except Exception:
                        continue
    except OSError:
        pass
    return out


def _d(iso: str | None) -> datetime.datetime | None:
    if not iso:
        return None
    try:
        return datetime.datetime.fromisoformat(str(iso)[:19])
    except ValueError:
        return None


def _giorno(iso: str | None) -> str:
    ""
    d = _d(iso)
    if not d:
        return ""
    oggi = datetime.date.today()

    if d.date() == oggi:
        return f"today at {d:%H:%M}"
    if d.date() == oggi - datetime.timedelta(days=1):
        return f"yesterday at {d:%H:%M}"
    breve = f"{MESI[d.month - 1][:3]} {d.day}"
    return breve if d.year == oggi.year else f"{breve} {d.year}"


def _quando(iso: str | None) -> str:
    ""
    d = _d(iso)
    if not d:
        return ""
    oggi = datetime.date.today()
    if d.date() == oggi:
        return f"today at {d:%H:%M}"
    if d.date() == oggi - datetime.timedelta(days=1):
        return f"yesterday at {d:%H:%M}"
    testo = f"{MESI[d.month - 1]} {d.day}"
    return testo if d.year == oggi.year else f"{testo} {d.year}"


def _quando_corto(iso: str | None) -> str:
    ""

    d = _d(iso)
    if not d:
        return ""
    oggi = datetime.date.today()
    if d.date() == oggi:
        return "today"
    if d.date() == oggi - datetime.timedelta(days=1):
        return "yesterday"
    testo = f"{MESI[d.month - 1][:3]} {d.day}"
    return testo if d.year == oggi.year else f"{testo} {d.year}"


def _file(percorso) -> str | None:
    return percorso if isinstance(percorso, str) and percorso and os.path.isfile(percorso) else None


def _dominio(url: str) -> str:
    try:
        host = urlparse(url).netloc
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def _durata_audio(secondi) -> str:
    ""
    try:
        grezzi = float(secondi)
        s = int(round(grezzi))
    except (TypeError, ValueError):
        return ""
    if 0 < grezzi < 1:
        return FRASI["meno_di_un_secondo"]
    if s <= 0:
        return ""

    def sec(n: int) -> str:
        return FRASI["un_secondo"] if n == 1 else FRASI["secondi"].format(n=n)

    if s < 60:
        return sec(s)
    m, r = divmod(s, 60)
    testo = FRASI["un_minuto"] if m == 1 else FRASI["minuti"].format(n=m)
    return f"{testo} and {sec(r)}" if r else testo


def _dal_tuo_audio(p: dict) -> str:
    durata = _durata_audio(p.get("durata_s"))
    return " ".join(
        x
        for x in (
            FRASI["dal_tuo_audio"],
            FRASI["audio_durata"].format(durata=durata) if durata else "",
        )
        if x
    )


def _parole_di_owner(v: dict) -> list[dict]:
    ""


    out, visti = [], set()
    cattura = v.get("cattura") or {}
    voci = [{"testo": cattura.get("testo_di_owner"), "quando": cattura.get("quando")}]
    voci += _dettagli(v)
    for p in voci:
        scritto = str(p.get("testo") or "").strip()
        trascritto = (
            str(p.get("trascrizione") or "").strip() if p.get("audio_stato") == "trascritto" else ""
        )

        righe = [(scritto, scritto == trascritto and bool(trascritto))]
        if trascritto and trascritto != scritto:
            righe.append((trascritto, True))
        for testo, a_voce in righe:
            if not testo or testo in visti:
                continue
            visti.add(testo)
            quando = _quando(p.get("quando"))
            if a_voce:
                quando = ", ".join(x for x in (quando, _dal_tuo_audio(p)) if x)
            out.append(
                {
                    "testo": testo,
                    "quando": quando,

                    "audio": (_file(p.get("audio")) or "") if a_voce else "",
                }
            )
    return out


def _dettagli(v: dict) -> list[dict]:
    ""
    return [
        p
        for p in (v.get("pareri") or [])
        if isinstance(p, dict) and not p.get("domanda") and p.get("su") != "perche"
    ]


def _ha_detto_qualcosa(v: dict) -> bool:
    ""

    if str((v.get("cattura") or {}).get("testo_di_owner") or "").strip():
        return True
    for p in v.get("pareri") or []:
        if isinstance(p, dict) and (p.get("testo") or p.get("audio") or p.get("trascrizione")):
            return True
    return any(
        isinstance(d, dict)
        and (d.get("risposta") or d.get("in_trascrizione"))
        and not _chiusa_dal_sistema(d)
        for d in v.get("domande") or []
    )


def _chiusa_dal_sistema(d: dict) -> bool:
    ""
    if "da_sistema" in d:
        return bool(d.get("da_sistema"))
    return (
        str(d.get("id") or "").startswith("s")
        and bool(d.get("chiusa"))
        and str(d.get("risposta") or "").startswith("chiusa da sola")
    )


def _audio_non_parola(p) -> bool:
    ""
    return isinstance(p, dict) and bool(p.get("audio")) and p.get("audio_stato") != "trascritto"


def _frase_audio(p: dict) -> str:
    ""
    stati = {
        "da trascrivere": "audio_da_trascrivere",
        "senza parlato": "audio_senza_parlato",
        "non riuscita": "audio_non_riuscito",
    }
    durata = _durata_audio(p.get("durata_s"))
    frase = " ".join(
        x
        for x in (FRASI["audio"], FRASI["audio_durata"].format(durata=durata) if durata else "")
        if x
    )
    stato = str(p.get("audio_stato") or "da trascrivere")
    return f"{frase}, {FRASI[stati.get(stato, 'audio_da_trascrivere')]}"


def _audio_di_owner(v: dict) -> list[dict]:
    ""


    return [
        {
            "frase": _frase_audio(p) + ".",
            "quando": _quando(p.get("quando")),
            "permalink": str(p.get("permalink") or ""),
            "audio": _file(p.get("audio")),
        }
        for p in _dettagli(v)
        if _audio_non_parola(p)
    ]


def _ora(iso) -> str:
    d = _d(iso)
    return f"{d:%H:%M}" if d else ""


def _ultimo(pareri: list[dict]) -> dict | None:
    ""
    if not pareri:
        return None
    return max(enumerate(pareri), key=lambda ip: (str(ip[1].get("quando") or ""), ip[0]))[1]


def _stato_audio(info: dict) -> str:
    ""


    if not info.get("audio"):
        return ""
    parola = (
        str(info.get("stato") or info.get("audio_stato") or "da trascrivere")
        .strip()
        .lower()
        .replace("_", " ")
    )
    stato = STATI_AUDIO.get(parola, parola.replace(" ", "_"))
    if stato == "in_trascrizione" and str(info.get("ultimo_esito") or "").startswith("rimandata"):
        stato = "aspetta_memoria"
    return stato


def _frase_stato_audio(stato: str, info: dict, di: str) -> str:
    ""

    chiave = f"{di}_{stato}"
    if not stato or chiave not in TESTI:
        return ""
    frase = TESTI[chiave]
    durata = _durata_audio(info.get("durata_s"))
    if not durata:
        frase = frase.replace(" of {durata}", "")
    ora = _ora(info.get("ultimo_tentativo") if stato == "aspetta_memoria" else info.get("quando"))
    if not ora:
        frase = frase.replace(", sent at {ora}", "").replace(
            ". I retried at {ora}", ""
        )
    testo = " ".join(str(info.get("trascrizione") or "").split())
    if len(testo) > 120:
        testo = testo[:117].rstrip() + "…"
    return frase.format(durata=durata, ora=ora, testo=testo)


def _frase(modello: str, **valori) -> str:
    ""


    for k, val in valori.items():
        if val in ("", None):
            modello = re.sub(r" ?\{" + k + r"\}", "", modello)
    q = valori.get("quando")
    if isinstance(q, str) and q:
        for da in ("da", "Da"):
            pezzo = da + " {quando}"
            if pezzo in modello:
                modello = modello.replace(
                    pezzo, _dal(f"{da} {q}").replace("{", "{{").replace("}", "}}")
                )
    return modello.format(**{k: ("" if x is None else x) for k, x in valori.items()}).strip()


def _dal(testo: str) -> str:
    ""

    testo = re.sub(r"^([Dd])a oggi alle ", r"\1alle ", testo)
    testo = re.sub(r"^([Dd])a il ", r"\1al ", testo)
    return re.sub(r"^([Dd])a l['’]", r"\1all'", testo)


def _conta_domande(n: int) -> str:
    return SCHEDA_STATO["una_domanda"] if n == 1 else SCHEDA_STATO["n_domande"].format(n=n)








_ORDINALI = {2: "2nd", 3: "3rd", 4: "4th", 5: "5th"}



_SOSTITUZIONI_PRIMA = (
    (
        r"la sessione si è chiusa senza scrivere l'esito",
        "la comprensione si è interrotta prima di finire",
    ),
    (r"session[ei] di comprensione", "comprensione"),
    (r"sessione di rilettura", "rilettura"),

    (r"la destinazione del dossier", "dove l'avevo messo io"),
)


_SOSTITUZIONI = (
    (r"la sessione dello spunto", "l'agente dello spunto\x01"),
    (r"la sessione di lavoro", "il lavoro\x01"),
    (r"(?:della|dalla|alla|nella) sessione di lavoro", "del lavoro\x01"),
    (r"una sessione", "un agente\x01"),
    (r"la sessione", "l'agente\x01"),
    (r"le sessioni", "gli agenti\x01"),
    (r"della sessione", "dell'agente\x01"),
    (r"dalla sessione", "dall'agente\x01"),
    (r"alla sessione", "all'agente\x01"),
    (r"nella sessione", "nell'agente\x01"),
    (r"sessione dello spunto", "agente dello spunto\x01"),
    (r"sessione di lavoro", "lavoro\x01"),
    (r"sessioni", "agenti\x01"),
    (r"sessione", "agente\x01"),

    (r"il dossier(?: rifatto)?", "quello che ho capito"),
    (r"del dossier(?: rifatto)?", "di quello che ho capito"),
    (r"dal dossier(?: rifatto)?", "da quello che ho capito"),
    (r"nel dossier(?: rifatto)?", "in quello che ho capito"),
    (r"(?:un|i) dossier(?: rifatto)?", "quello che ho capito"),
    (r"dossier rifatto", "quello che ho capito"),
    (r"dossier", "quello che ho capito"),
    (r"in sottofondo", ""),
    (r"sottofondo", ""),
    (r"tentativi", "volte"),
    (r"tentativo", "volta"),
    (r"giri", "controlli"),
    (r"giro", "controllo"),
    (r"dalla coda", "dal percorso"),
    (r"in coda", "in fila"),
    (r"coda", "fila"),
    (r"tick", "controllo"),
    (r"whisper", "la trascrizione"),
)



def _una_regex(tabella):
    return re.compile(
        r"\b(?:" + "|".join(f"(?P<s{k}>{v})" for k, (v, _) in enumerate(tabella)) + r")\b", re.I
    )


_RE_SOSTITUZIONI_PRIMA = _una_regex(_SOSTITUZIONI_PRIMA)
_RE_SOSTITUZIONI = _una_regex(_SOSTITUZIONI)

_SOSPETTO = re.compile(
    r"[/0-9]|\.(?:md|jsonl?|py|log|m4a|mp4|txt)\b|session|dossier|sottofondo|\bgir[oi]\b|\bcoda\b|\btick\b"
    r"|whisper|quota|tentativ",
    re.I,
)

_P = functools.lru_cache(maxsize=None)(re.compile)


def _owner_first_name() -> str:
    tools = Path(__file__).resolve().parents[1]
    if str(tools) not in sys.path:
        sys.path.insert(0, str(tools))
    from sbk_config import OWNER_NAME

    return OWNER_NAME.split()[0] if OWNER_NAME else "owner"


# Your first name as the history lines write it (sbk.config.json "owner").
_OWN_NAME = _owner_first_name()
_OWN_RX = re.escape(_OWN_NAME)


_RE_FILE = re.compile(
    r"\s*\((?=[^()]*(?:[A-Za-z]/[A-Za-z]|\.md\b|\.jsonl?\b|\.py\b|\.log\b|\.m4a\b))[^()]*\)"
    r"|(?<![\w.~-])(?:[\w.~-]+/){2,}[\w.~-]+"
    r"|(?<![\w.~-])(?:[\w.~-]+/)*[\w~-]+\.(?:md|jsonl?|py|log|m4a|mp4|txt)\b"
)
_RE_ISO = re.compile(r"\b(?:(il|del|dal|al) )?(\d{4}-\d\d-\d\d)(?:[ T](\d\d:\d\d)(?::\d\d)?)?\b")

# The Italian preposition in front of a date in the internal text, said in English.
_ARTICOLI = {"il": "on", "del": "of", "dal": "since", "al": "to"}


def _giorno_parole(data: str) -> str:
    ""
    d = _d(data)
    if not d:
        return data
    oggi = datetime.date.today()
    if d.date() == oggi:
        return "today"
    if d.date() == oggi - datetime.timedelta(days=1):
        return "yesterday"
    testo = f"{MESI[d.month - 1]} {d.day}"
    return testo if d.year == oggi.year else f"{testo} {d.year}"


def _date_parole(testo: str) -> str:
    ""

    def una(m):
        prima, data, ora = m.group(1), m.group(2), m.group(3)
        detta = _quando(f"{data}T{ora}") if ora else _giorno_parole(data)
        if not prima:
            return detta
        if detta.startswith(("today", "yesterday")):
            return detta
        return f"{_ARTICOLI[prima]} {detta}"

    return _RE_ISO.sub(una, testo)



_MASCHILE = {
    "chiusa": "chiuso",
    "aperta": "aperto",
    "partita": "partito",
    "fermata": "fermato",
    "ferma": "fermo",
    "nuova": "nuovo",
    "interrotta": "interrotto",
    "morta": "morto",
    "finita": "finito",
    "scritta": "scritto",
    "conclusa": "concluso",
    "avviata": "avviato",
    "stata": "stato",
    "rimasta": "rimasto",
    "andata": "andato",
    "lanciata": "lanciato",
}
_FEMM = "|".join(_MASCHILE)

_RE_MASCHILE_ACCANTO = re.compile(r"\x01((?:\s+(?:" + _FEMM + r")\b)+)")
_RE_MASCHILE_VERBO = re.compile(
    r"\x01([^.;:,\x01]{0,40}?\b(?:si è|è stat[oa]|è|sono)\s+)(" + _FEMM + r")\b"
)


def _al_maschile(t: str) -> str:
    if "\x01" not in t:
        return t

    def accanto(m):
        return "\x01" + re.sub(r"\w+", lambda x: _MASCHILE.get(x.group(0), x.group(0)), m.group(1))

    t = _RE_MASCHILE_ACCANTO.sub(accanto, t)
    t = re.sub(r"\x01([^.;:,\x01]{0,40}?)\bè stata\b", "\x01\\1è stato", t)
    t = _RE_MASCHILE_VERBO.sub(lambda m: "\x01" + m.group(1) + _MASCHILE[m.group(2)], t)
    return t.replace("\x01", "")


def _parole_semplici(testo: str) -> str:
    ""

    testo = str(testo or "")
    if not _SOSPETTO.search(testo):

        return testo.strip(" ,")
    pezzi = re.split(r"(«[^»]*»)", testo)
    out = []
    for p in pezzi:
        if p.startswith("«"):
            out.append(_date_parole(p))
            continue
        p = _RE_FILE.sub("", p)
        p = _date_parole(p)
        p = _RE_SOSTITUZIONI_PRIMA.sub(lambda m: _SOSTITUZIONI_PRIMA[int(m.lastgroup[1:])][1], p)
        p = _RE_SOSTITUZIONI.sub(lambda m: _SOSTITUZIONI[int(m.lastgroup[1:])][1], p)
        p = _al_maschile(p)

        p = re.sub(r"\bla domanda [ds]\d+\b", "una domanda", p)
        p = re.sub(r"\([ds]\d+(?:, [ds]\d+)*\)\s*", "", p)
        p = re.sub(r"\b[ds]\d+\b", "una domanda", p)
        out.append(p)
    t = "".join(out)

    t = re.sub(r"\b1 domande nuove\b", "una domanda nuova", t)
    t = re.sub(r"\b1 domande superate\b", "una domanda superata", t)
    t = re.sub(r"\b1 domande\b", "una domanda", t)
    t = re.sub(r"\b1 cose che mi mancano\b", "una cosa che mi manca", t)
    t = re.sub(r"\s+([,.])", r"\1", t)
    t = re.sub(r"\(\s*\)", "", t)
    return re.sub(r"\s{2,}", " ", t).strip(" ,")


def _n_domande(n: int) -> str:
    return "one question" if n == 1 else f"{n} questions"


def _ordinale_volta(n: int) -> str:
    return f"for the {_ORDINALI.get(n, f'{n}th')} time"





_STORIA_DI_PRIMA = (
    ("il perché resta il tuo", "cosa intendi resta come l'hai confermato"),
    ("il perché è riscritto con le tue parole", "ho riscritto cosa ho capito con le tue parole"),
    ("nella fase Il perché", "allo Scope"),
)


def _storia_parole(cosa: str) -> str:
    ""

    frase = _storia_parole_di_oggi(cosa)
    pezzi = re.split(r"(«[^»]*»)", frase)
    for i, p in enumerate(pezzi):
        if not p.startswith("«"):
            for vecchio, nuovo in _STORIA_DI_PRIMA:
                p = p.replace(vecchio, nuovo)
            pezzi[i] = p
    return "".join(pezzi)


def _storia_parole_di_oggi(cosa: str) -> str:
    ""

    c = str(cosa or "").strip()

    detta = _storia_scope(c)
    if detta:
        return detta
    m = _P(r"^buttato dentro \(DM Slack, messaggio del (\d{4}-\d\d-\d\d) (\d\d:\d\d)\)$").match(c)
    if m:
        return f"Came in from your DM, you sent it {_quando(f'{m.group(1)}T{m.group(2)}')}"
    m = _P(r"^mandato di nuovo nel DM \((\d{4}-\d\d-\d\d) (\d\d:\d\d)\)$").match(c)
    if m:
        return f"You sent it again in the DM {_quando(f'{m.group(1)}T{m.group(2)}')}"
    if _P(rf"^parere di {_OWN_RX} \(testo col link\)$").match(c):
        return "Your words, written next to the link"
    m = _P(rf"^parere di {_OWN_RX}(?: \((.*)\))?$").match(c)
    if m:

        return "Your words" + (f", {m.group(1)}" if m.group(1) else "")
    m = _P(r"^mandato da te nel DM \((\d{4}-\d\d-\d\d) (\d\d:\d\d)\)").match(c)
    if m:
        return f"You sent it in the DM {_quando(f'{m.group(1)}T{m.group(2)}')}"
    if c == f"ritorno letto da {_OWN_NAME}":
        return "You read the reply"
    if c.startswith(f"dettaglio di {_OWN_NAME} nell'app"):
        return "You added a detail" + (
            ", by voice, to transcribe" if "a voce, da trascrivere" in c else ""
        )
    m = _P(rf"^smistamento rimesso da {_OWN_RX}, era (.*)$").match(c)
    if m:
        return f"You reopened where it goes, it was {m.group(1)}"
    if c.startswith(f"perché corretto a voce da {_OWN_NAME}"):
        return "You corrected by voice what I understood, it counts once your audio is transcribed"
    m = _P(rf"^{_OWN_RX} conferma le parole sentite nell'audio per «[^»]*»: («.*»)$").match(c)
    if m:
        return f"You confirmed the words of your audio, {m.group(1)}"
    m = _P(rf"^{_OWN_RX} ha tolto la risposta a ([^,]+(?:, [ds]\d+)*), la domanda torna aperta").match(c)
    if m:
        quante = len([x for x in m.group(1).split(",") if x.strip()])
        if quante == 1:
            return "You removed the answer to a question, it is open again"
        return f"You removed the answers to {quante} questions, they are open again"
    if c.startswith(f"avviata da {_OWN_NAME}"):
        return "You pressed Start, the work started in the terminal"
    m = _P(r"^trascrizione dell'audio non riuscita .*tentativo (\d+) su (\d+)$").match(c)
    if m:
        return (
            f"The transcription of your audio failed, I tried {m.group(1)} times"
            f" out of {m.group(2)}"
        )
    if _P(rf"^audio di {_OWN_RX} non riuscit[ao]").match(c):
        return "Your audio did not transcribe"
    if c == "registrata, il contenuto non è ancora stato capito":
        return "In, I still have to see and understand the content"
    if c == "registrata, contenuto visto, da capire":
        return "In, I have seen the content and still have to understand it"
    if c.startswith("parlato → senza parlato"):
        return "No one speaks in the video"
    m = _P(r"^contenuto visto, (.*)$").match(c)
    if m:
        return f"Content seen, {_parole_semplici(m.group(1))}"
    m = _P(r"^da «da capire» a «capito», dossier rifatto dal contenuto visto \((.*)\)$").match(c)
    if m:
        return f"Understood from the content seen, {_parole_semplici(m.group(1))}"
    if c == "da «capito» a «da decidere», c'è un tuo parere":
        return "Understood, now you decide"
    m = _P(r"^da «capito» a «da decidere», il dossier dice («.*»)$").match(c)
    if m:
        return f"Understood, now you decide. For me it is {m.group(1)}"
    if c.startswith("comprensione presa dal dossier rifatto"):

        return "I understood the content"
    if _P(r"^(?:re)?importato da ").match(c):
        return "Taken from the earlier archive"
    if _P(r"^archivio v\d+, campi nuovi aggiunti").match(c):
        return "Archive updated, nothing removed"
    if c.startswith("passaggio una tantum da «") and "a «da capire»" in c:
        return "Put back among those to understand, I had not seen the content"
    m = _P(r"^comprensione partita in sottofondo \((.*)\)$").match(c)
    if m and "premuto Fallo adesso" in m.group(1):
        return "You pressed Do it now, I started to understand it"
    if m:
        dentro = m.group(1)
        t = re.search(r"tentativo (\d+)", dentro)
        n = int(t.group(1)) if t else 1
        frase = "I started to understand it" + (" on my own" if "da sola" in dentro else "")
        return frase + (f", {_ordinale_volta(n)}" if n > 1 else "")
    if _P(r"^sessione di comprensione aperta nel terminale").match(c):
        return "I started to understand it in the terminal"
    if c in ("comprensione fatto", "sessione di comprensione fatto"):
        return "I finished understanding it"
    m = _P(r"^(?:sessione di )?comprensione ferm[ao],? (.*)$").match(c)
    if m:

        motivo = _motivo_normale(m.group(1))
        if motivo.lower().startswith(("la comprensione", "understanding")):
            return motivo
        return f"Understanding stopped. {motivo}"
    m = _P(r"^rilettura ferm[ao],? (.*)$").match(c)
    if m:
        motivo = _maiuscola(_parole_semplici(m.group(1)))
        if motivo.lower().startswith("la rilettura"):
            return motivo
        return f"The re-read stopped. {motivo}"
    m = _P(r"^smistamento proposto, (.*)$").match(c)
    if m:
        return f"I proposed where it goes, {_parole_semplici(m.group(1))}"


    m = _P(r"^perché proposto, (.+?), (\d+) cose che mi mancano$").match(c)
    if m:

        esito = _esito_a_scope(m.group(1))
        esito = f"{esito}, " if esito else ""
        return f"I told you what I understood, {esito}{_n_domande(int(m.group(2)))}"
    m = _P(r"^perché proposto, (.*)$").match(c)
    if m:
        return _con_resto("I told you what I understood", m.group(1))
    m = _P(rf"^perché corretto da {_OWN_RX},? ?(.*)$").match(c)
    if m:
        return _con_resto("You corrected what I understood", m.group(1))
    m = _P(rf"^perché confermato da {_OWN_RX},? ?(.*)$").match(c)
    if m:
        return _con_resto("You confirmed what I understood", m.group(1))
    m = _P(r"^perché riscritto, (.*)$").match(c)
    if m:
        return _con_resto("I rewrote what I understood", m.group(1))
    m = _P(rf"^audio di {_OWN_RX} trascritto \((.*)\)$").match(c)
    if m:
        s = re.search(r"(\d+(?:\.\d+)?) s\b", m.group(1))
        durata = _durata_audio(s.group(1)) if s else ""
        return "Your audio is transcribed" + (f", {durata}" if durata else "")
    m = _P(rf"^audio di {_OWN_RX} senza parlato \((.*)\)$").match(c)
    if m:
        s = re.search(r"(\d+(?:\.\d+)?) s\b", m.group(1))
        durata = _durata_audio(s.group(1)) if s else ""
        return "In your audio" + (f" of {durata}" if durata else "") + " I heard no words"
    m = _P(rf"^audio di {_OWN_RX} da verificare, ho sentito («.*?»)").match(c)
    if m:
        return f"In your audio I heard {m.group(1)}, to be checked"
    if _P(rf"^la domanda [ds]\d+ è chiusa con le parole di {_OWN_RX}$").match(c):
        return "You answered a question"
    m = _P(r"^la domanda [ds]\d+ resta aperta, (.*)$").match(c)
    if m:
        motivo = {
            "audio senza parlato": "I heard no words in your audio",
            "audio da verificare": "your audio needs checking",
        }.get(m.group(1), _parole_semplici(m.group(1)))
        return f"A question stays open, {motivo}"


    if _P(r"^la domanda [ds]\d+ non serve più, l'agente nel terminale te la chiede lì$", re.I).match(c):
        return "The agent in the terminal took a question off the app, it asks you there"
    m = _P(r"^la domanda [ds]\d+ non serve più, (.*)$", re.S).match(c)
    if m:
        return f"A question is no longer needed. {_parole_semplici(m.group(1))}"
    m = _P(rf"^risposta di {_OWN_RX} alla domanda [ds]\d+(?: \((.*)\))?$").match(c)
    if m:

        return "You answered a question" + (f", {m.group(1)}" if m.group(1) else "")
    m = _P(rf"^risposta di {_OWN_RX} a (\d+) domande insieme \([^)]*\)(?: \((.*)\))?$").match(c)
    if m:
        dentro = f", {m.group(2)}" if m.group(2) else ""
        return f"You answered {m.group(1)} questions together{dentro}"
    m = _P(r"^l'audio per «[ds]\d+» torna a whisper.*?ho sentito prima («.*?»)").match(c)
    if m:
        return f"I am transcribing your audio again, before I had heard {m.group(1)}"
    m = _P(r"^rilettura partita in sottofondo con la sua risposta delle (\d\d:\d\d)").match(c)
    if m:
        return f"I started re-reading everything with your answer from {m.group(1)}"
    m = _P(r"^rilettura fatto,? ?(.*)$").match(c)
    if m:
        resto = (
            _parole_semplici(m.group(1))
            .replace("dove vuole", "dove vuoi")
            .replace("sue parole", "tue parole")
        )
        return "I re-read everything" + (f", {resto}" if resto else "")

    m = _P(
        r"^la sessione dello spunto è di nuovo aperta nel terminale, era segnata chiusa dalle (\d\d:\d\d)"
    ).match(c)
    if m:
        return (
            f"The idea's agent is open again in the terminal, it showed as closed since {m.group(1)}"
        )
    if c == "la sessione di lavoro è di nuovo aperta nel terminale":
        return "The work is open again in the terminal"
    if _P(r"^sessione dello spunto aperta nel terminale").match(c):

        return "An agent opened in the terminal" + (", on your click" if "Ci lavoriamo" in c else "")
    if c == "sessione dello spunto chiusa":
        return "The agent in the terminal closed"
    if _P(
        r"^la sessione (?:dello spunto|di lavoro|di comprensione) non è più aperta nel terminale"
    ).match(c):
        return "The agent in the terminal is gone"
    m = _P(r"^domanda (?:di )?(.+?) chiusa da sola, (.*)$").match(c)
    if m:

        resto = _parole_semplici(re.sub(r"\s*\(.*$", "", m.group(2)))
        return f"The question from {m.group(1)} is no longer needed, {resto}"
    if c.startswith("il link /p/ è un video solo"):
        return "It is a video, not a post"
    m = _P(r"^disponibilità da «(.+?)» a «(.+?)»").match(c)
    if m:
        return f"Now it is «{m.group(2)}», before it was «{m.group(1)}»"
    m = _P(r"^comprensione superata, il dossier diceva «(.+?)» ma la pagina dice «(.+?)»").match(c)
    if m:
        return f"Re-read from the start, before it said «{m.group(1)}» but the page says «{m.group(2)}»"
    m = _P(r"^da «(.+?)» a «(.+?)»,? ?(.*)$").match(c)
    if m:
        resto = _parole_semplici(m.group(3))
        return f"Moved from «{m.group(1)}» to «{m.group(2)}»" + (f", {resto}" if resto else "")
    return _maiuscola(_parole_semplici(c))



_STRADA_STORIA = {
    "lo tieni come riferimento": "strada_riferimento",
    "da studiare": "strada_studio",
    "una cosa da fare": "strada_cosa_da_fare",
    "da sviluppare": "strada_sviluppo",
    "non serve": "strada_non_serve",
}


def _strada_storia(parola: str) -> str:
    chiave = _STRADA_STORIA.get(parola.strip())
    if not chiave:
        return ""
    t = TESTI[chiave]
    return t[:1].lower() + t[1:]


def _riga_di_scope(s: dict) -> bool:
    cosa = str(s.get("cosa") or "")
    return s.get("evento") == "scope" or cosa.startswith(
        (
            "scope",
            f"domanda di {_OWN_NAME} sullo scope",
            f"riaperto da {_OWN_NAME}",
            f"studio letto da {_OWN_NAME}",
            "proposta di scope nuova",
        )
    )


def _storia_scope(c: str) -> str:
    ""
    a_voce = ", by voice, to transcribe" if c.endswith(" (a voce, da trascrivere)") else ""
    m = _P(rf"^scope confermato da {_OWN_RX}, versione \d+, (.+)$").match(c)
    if m:
        return "You confirmed the scope" + (
            f", {_strada_storia(m.group(1))}" if _strada_storia(m.group(1)) else ""
        )
    m = _P(r"^scope, versione \d+(.*)$").match(c)
    if m:
        coda = m.group(1)
        di_owner = coda.endswith(", scelto da te")
        pezzi = [x.strip() for x in coda.removesuffix(", scelto da te").split(",") if x.strip()]
        detto = []
        for x in pezzi:
            if _strada_storia(x):
                detto.append(_strada_storia(x))
            elif x.startswith("progetto "):
                detto.append(f"for {x[len('progetto ') :]}")
            elif _P(r"^(\d+) domande nuove$").match(x):
                detto.append(x.replace("domande nuove", "new questions"))
            elif x == "1 domanda nuova":
                detto.append("one new question")
        testa = "You changed the scope" if di_owner else "I rewrote the scope"
        return ", ".join([testa, *detto])
    if c.startswith(f"domanda di {_OWN_NAME} sullo scope"):
        return "You asked a question about the scope" + a_voce
    if c.startswith(f"scope raddrizzato da {_OWN_NAME}"):
        return "You corrected the scope" + a_voce
    m = _P(rf"^riaperto da {_OWN_RX}, torna allo scope \(era (.+?)\)(, la task .* resta dov'è)?$").match(c)
    if m:
        return f"You reopened the idea, it was {m.group(1)}" + (
            ", the task stays where it is" if m.group(2) else ""
        )
    if c == f"studio letto da {_OWN_NAME}":
        return "You read the study"
    m = _P(r"^scope cambiato, rifaccio (.+), versione \d+$").match(c)
    if m:
        return f"You chose to redo {m.group(1)} with the new scope"
    m = _P(r"^scope cambiato, (.+) (resta com'è|restano come sono), versione \d+$").match(c)
    if m:
        come = "as it is" if m.group(2) == "resta com'è" else "as they are"
        return f"You kept {m.group(1)} {come}"
    m = _P(r"^proposta di scope nuova dopo la tua conferma, cambia (.+), aspetta te$").match(c)
    if m:
        return f"I proposed another scope, it changes {m.group(1)}"
    m = _P(r"^(\d+) domande nuove per lo scope$").match(c)
    if m:
        return f"I asked you {m.group(1)} new questions about the scope"
    if c == "1 domanda nuova per lo scope":
        return "I asked you a new question about the scope"
    m = _P(r"^progetto in testa allo spunto da «(.+?)» a «(.+?)», come nello scope$").match(c)
    if m:
        return f"The project moved from «{m.group(1)}» to «{m.group(2)}», as in the scope"
    m = _P(r"^le tue parole («.*») erano una domanda e restano una domanda").match(c)
    if m:
        return f"Your words {m.group(1)} stay a question"
    m = _P(r"^le tue parole («.*») erano una correzione e valgono come correzione").match(c)
    if m:
        return f"Your words {m.group(1)} count as a correction"
    m = _P(r"^perché, l'etichetta diventa (.+) come lo scope$").match(c)
    if m:
        return "The why follows the scope"
    return ""



ESITO_A_SCOPE = {
    "una funzione da aggiungere": "a feature",
    "un contenuto da fare": "a piece of content",
    "un flusso da creare": "",
    "da tenere da parte": "to keep as a reference",
    "un'ispirazione tua": "to keep as a reference",
    "altro": "",
}


def _esito_a_scope(testo: str) -> str:
    ""
    t = str(testo or "").strip()
    for vecchia, nuova in ESITO_A_SCOPE.items():
        if t == vecchia:
            return nuova
        if t.startswith(vecchia + ", "):
            resto = _parole_semplici(t[len(vecchia) + 2 :])
            return f"{nuova}, {resto}" if nuova else resto
    return _parole_semplici(t)


def _con_resto(testa: str, resto: str) -> str:
    r = _esito_a_scope(resto)
    return f"{testa}, {r}" if r else testa




_STORIA_DEL_MECCANISMO = re.compile(
    r"^(?:(?:re)?importato da |archivio v\d+, campi nuovi aggiunti)"
)


def _storia_del_meccanismo(cosa: str) -> bool:
    return bool(_STORIA_DEL_MECCANISMO.match(cosa.strip()))


def _storia_vista(storia: list) -> list[dict]:
    ""




    righe = [
        s
        for s in storia
        if isinstance(s, dict) and s.get("cosa") and not _storia_del_meccanismo(str(s["cosa"]))
    ]
    gesti = {str(s.get("quando") or "")[:19] for s in righe if _riga_di_scope(s)}
    out, nascoste = [], []
    for s in righe:
        q = str(s.get("quando") or "")[:19]
        cosa = str(s.get("cosa") or "")
        if (
            q in gesti
            and not _riga_di_scope(s)
            and cosa.startswith(("perché", "smistamento", "progetto in testa"))
        ):
            nascoste.append((q, cosa))
            continue
        out.append(
            {
                "quando": _quando(s.get("quando")),
                "cosa": _storia_parole(cosa),
                "cosa_originale": cosa,
                "_q": q,
                "_scope": _riga_di_scope(s),
            }
        )
    for q, cosa in nascoste:
        r = next((x for x in out if x["_q"] == q and x["_scope"]), None)
        if r is not None:
            r["cosa_originale"] += f" · {cosa}"
    for x in out:
        x.pop("_q")
        x.pop("_scope")
    return out


def _info_audio(d: dict, parere: dict | None) -> dict:
    ""

    p = parere or {}
    info = {
        k: p.get(k)
        for k in (
            "audio_stato",
            "durata_s",
            "ultimo_esito",
            "ultimo_tentativo",
            "quando",
            "trascrizione",
        )
    }
    for k in ("audio_stato", "durata_s", "ultimo_esito", "ultimo_tentativo", "trascrizione"):
        if d.get(k) not in (None, ""):
            info[k] = d[k]
    if d.get("stato") not in (None, ""):
        info["stato"] = d["stato"]

    if d.get("risposta_quando"):
        info["quando"] = d["risposta_quando"]
    if "audio" in d:


        info["audio"] = _file(d.get("audio")) or d.get("audio") or ""
    else:
        info["audio"] = _file(p.get("audio")) or p.get("audio") or ""
    return info


def _domande(v: dict) -> list[dict]:
    ""

    raw = {
        str(d.get("id") or ""): d
        for d in ((v.get("lavorazione") or {}).get("domande") or [])
        if isinstance(d, dict)
    }
    per_domanda: dict[str, list[dict]] = {}
    for p in v.get("pareri") or []:
        if not isinstance(p, dict) or p.get("tolto") or p.get("sostituito"):
            continue
        if p.get("domande"):

            via = {str(x) for x in (p.get("tolto_per") or []) + (p.get("sostituito_per") or [])}
            for ident in p["domande"]:
                if str(ident) not in via:
                    per_domanda.setdefault(str(ident), []).append(p)
        elif p.get("domanda") and p.get("domanda") != "tutte":
            per_domanda.setdefault(str(p["domanda"]), []).append(p)
    out = []
    for d in v.get("domande") or []:
        if not isinstance(d, dict) or not d.get("testo"):
            continue
        ident = str(d.get("id") or "")
        miei = per_domanda.get(ident, [])
        info = _info_audio(d, _ultimo([p for p in miei if p.get("audio")]))
        stato = _stato_audio(info)
        chiusa = bool(d.get("chiusa"))
        if chiusa and stato in IN_VIAGGIO:

            stato = "trascritta"
        elif chiusa and stato in RIAPRONO:


            stato = ""
            info = {k: x for k, x in info.items() if k not in ("audio", "durata_s")}


        in_trascrizione = bool(d.get("in_trascrizione")) and (not stato or stato in IN_VIAGGIO)
        ultimo = _ultimo(miei)
        risp = (raw.get(ident) or {}).get("risposta")


        quando_iso = (
            d.get("risposta_quando")
            or (risp.get("quando") if isinstance(risp, dict) else None)
            or (ultimo or {}).get("quando")
        )
        out.append(
            {
                "id": ident,
                "testo": str(d.get("testo") or ""),
                "serve_per": SERVE_PER.get(str(d.get("serve_per") or ""), ""),

                "passo": _passo_domanda(d),
                "policy": bool(d.get("policy")),

                "fonte_norma": str(d.get("fonte_norma") or ""),
                "chiusa": chiusa,
                "risposta": str(d.get("risposta") or ""),
                "in_trascrizione": in_trascrizione,
                "da": str(d.get("da") or ""),
                "audio": _file(info.get("audio")) or "",
                "durata": _durata_audio(info.get("durata_s")),
                "stato": stato,
                "stato_frase": _frase_stato_audio(stato, info, "audio"),
                "quando_risposta": _quando(quando_iso) if (chiusa or stato) else "",
                "da_sistema": _chiusa_dal_sistema(d),


                "insieme": bool(d.get("insieme")),
                "parole_sentite": " ".join(str(info.get("trascrizione") or "").split())
                if stato == "da_verificare"
                else "",
            }
        )
    return out


ESITI_PAROLE = dict(ESITI)


def _perche(v: dict, pc: dict) -> dict:
    ""

    con_audio = [
        p
        for p in (v.get("pareri") or [])
        if isinstance(p, dict) and p.get("su") == "perche" and p.get("audio")
    ]
    nome = os.path.basename(str(pc.get("correzione_audio") or ""))
    par = next(
        (
            p
            for p in reversed(con_audio)
            if nome and os.path.basename(str(p.get("audio") or "")) == nome
        ),
        None,
    ) or _ultimo(con_audio)



    audio_corr = pc.get("correzione_audio_file") or pc.get("correzione_audio")
    info = _info_audio(
        {
            "audio": audio_corr,
            "stato": pc.get("correzione_stato"),
            "durata_s": pc.get("correzione_durata_s"),
            "ultimo_esito": pc.get("correzione_ultimo_esito"),
            "ultimo_tentativo": pc.get("correzione_ultimo_tentativo"),
            "trascrizione": pc.get("correzione_trascrizione"),
            "risposta_quando": pc.get("correzione_quando"),
        },
        par,
    )
    correzione = str(pc.get("correzione") or "")
    stato_corr = _stato_audio(info) if audio_corr else ""
    if correzione and stato_corr in IN_VIAGGIO:
        stato_corr = "trascritta"
    if "correzione_in_arrivo" in pc:
        in_arrivo = bool(pc.get("correzione_in_arrivo"))
    else:
        in_arrivo = bool(audio_corr) and not correzione
    corretto = bool(correzione or audio_corr)
    confermato = bool(pc.get("confermato"))
    quando_conf = _quando(pc.get("confermato_quando"))
    quando_corr = _quando(info.get("quando")) or quando_conf
    if in_arrivo and stato_corr:
        chiave = {
            "in_trascrizione": "perche_corretto_voce",
            "aspetta_memoria": "perche_corretto_voce_memoria",
            "non_riuscita": "perche_corretto_voce_non_riuscita",
            "senza_parlato": "perche_corretto_voce_senza_parlato",
            "da_verificare": "perche_corretto_voce_da_verificare",
        }.get(stato_corr, "perche_corretto_voce")
        stato_frase = _frase(TESTI[chiave], quando=quando_corr)
    elif confermato and corretto:
        stato_frase = _frase(TESTI["perche_corretto"], quando=quando_conf or quando_corr)
    elif confermato:
        stato_frase = _frase(TESTI["perche_confermato"], quando=quando_conf)
    elif str(pc.get("da") or "") == DA_RILETTURA:

        stato_frase = _frase(TESTI["riletto_segno"], quando=_quando(pc.get("quando")))
    else:
        stato_frase = ""

    di_prima = [x for x in (pc.get("proposte_di_prima") or []) if isinstance(x, dict)]
    prima_dicevo = str(di_prima[-1].get("testo") or "") if di_prima and not confermato else ""
    esito = str(pc.get("esito") or "")
    proposto = str(pc.get("esito_proposto") or "")
    dove = re.sub(r"^\s*vuoi arrivare a\s+", "", str(pc.get("dove_arrivare") or ""), flags=re.I)
    if dove and dove[0].islower():
        dove = dove[0].upper() + dove[1:]
    sicurezza = SICUREZZA.get(str(pc.get("sicurezza") or ""), "")
    poggia = " ".join(str(pc.get("su_cosa_poggia") or "").split())

    poggia = re.sub(
        r"\b([Ll])a destinazione del dossier\b",
        lambda m: ("D" if m.group(1) == "L" else "d") + "ove l'avevo messo io",
        poggia,
    )
    if poggia and len(poggia) > 1 and poggia[0].isupper() and poggia[1].islower():
        poggia = poggia[0].lower() + poggia[1:]
    senza_parole = re.match(r"^nessuna parola tua\b[.,;]?\s*(.*)$", poggia, re.I)
    if sicurezza and senza_parole:

        resto = senza_parole.group(1)
        poggia_frase = f"{sicurezza}, senza parole tue." + (
            f" {_maiuscola(resto)}" if resto else ""
        )
    elif sicurezza and poggia:
        poggia_frase = f"{sicurezza}, per {poggia}"
    elif poggia:
        poggia_frase = poggia[0].upper() + poggia[1:]
    else:
        poggia_frase = sicurezza
    return {
        "c_e": bool(pc.get("testo")),
        "esito": esito,
        "esito_parole": str(pc.get("esito_parole") or ESITI_PAROLE.get(esito, "")),
        "esito_proposto_parole": ESITI_PAROLE.get(proposto, "")
        if proposto and proposto != esito
        else "",
        "testo": str(pc.get("testo") or ""),
        "dove_arrivare": dove,
        "sicurezza": sicurezza,
        "su_cosa_poggia": str(pc.get("su_cosa_poggia") or ""),
        "su_cosa_poggia_frase": poggia_frase,
        "confermato": confermato,
        "confermato_quando": quando_conf,
        "stato_frase": stato_frase,
        "corretto": corretto,
        "correzione": correzione,
        "correzione_in_arrivo": in_arrivo,
        "correzione_in_trascrizione": in_arrivo and stato_corr in IN_VIAGGIO,
        "correzione_stato": stato_corr if in_arrivo else "",
        "correzione_frase": _frase_stato_audio(stato_corr, info, "correzione") if in_arrivo else "",
        "correzione_audio_file": _file(info.get("audio")) or "",
        "correzione_durata": _durata_audio(info.get("durata_s")) if audio_corr else "",
        "prima_dicevo": prima_dicevo,
        "riletto": str(pc.get("da") or "") == DA_RILETTURA and not confermato,
    }


def _letto_quando(ag: dict, v: dict) -> str:
    if ag.get("ritorno_letto_quando"):
        return str(ag["ritorno_letto_quando"])
    for s in reversed(v.get("storia") or []):
        if isinstance(s, dict) and str(s.get("cosa") or "").startswith("ritorno letto"):
            return str(s.get("quando") or "")
    return ""


def _tocca_frase(
    fase, tocca, pc, ses, ag, aperte, chiusa_a_mano, letto_quando, comprensione=None, rilettura=None
) -> str:
    ""
    comprensione = comprensione or {}
    rilettura = rilettura or {}
    n = len(aperte)
    if rilettura.get("aperta"):
        return _frase(
            TOCCA["rilettura_in_fila" if rilettura.get("in_fila") else "rilettura"],
            quando=_quando(rilettura.get("risposta_quando")),
        )

    def domande(k):
        return TOCCA["te_domanda"] if k == 1 else TOCCA["te_domande"].format(n=k)

    if fase == "da_capire":
        if comprensione.get("aperta"):
            return _frase(
                TOCCA[
                    "comprensione_sottofondo" if comprensione.get("sottofondo") else "comprensione"
                ],
                quando=_quando(comprensione.get("aperta_quando")),
            )
        if comprensione.get("ferma"):

            return TOCCA["comprensione_ferma"].format(
                motivo=_motivo_frase(
                    _quando(comprensione.get("ferma_quando")), comprensione["ferma"]
                )
            )
        if comprensione.get("chiusa_senza_finire"):
            return TOCCA["comprensione_chiusa"]
        if comprensione.get("visto_quando"):
            return _frase(
                TOCCA["visto_da_capire"], quando=_quando(comprensione.get("visto_quando"))
            )
        return TOCCA["da_capire"]
    if tocca == "te":
        if chiusa_a_mano or (fase == "avviata" and str(ag.get("stato") or "") == "chiuso"):
            return TOCCA["te_chiusa"]
        if fase == "perche":
            if n == 0:
                return TOCCA["te_perche"]
            return TOCCA["te_perche_domanda"] if n == 1 else TOCCA["te_perche_domande"].format(n=n)
        if fase == "lavorazione":
            return domande(n) if n else TOCCA["te_ci_lavoriamo"]
        if fase == "pronta":
            return TOCCA["te_pronta"]
        if fase == "avviata":
            return domande(len([d for d in aperte if d["da"] == "sessione di lavoro"]) or n)
        if fase == "arrivata":
            return TOCCA["te_arrivata"]
        return TOCCA["te"]
    if tocca == "pipeline":
        return TOCCA["pipeline"]
    if tocca == "sessione":
        return _frase(TOCCA["sessione"], quando=_quando(ses.get("aperta_quando")))
    if tocca == "agente":
        return _frase(TOCCA["agente"], quando=_quando(ag.get("avviato_quando")))
    if fase == "tenuta":
        return _frase(TOCCA["tenuta"], quando=_quando(pc.get("confermato_quando")))
    if fase in ("scartata", "in_clickup"):
        return _frase(TOCCA[fase], quando=_quando(_quando_smistato(pc)))
    if fase == "arrivata" and ag.get("ritorno_letto"):
        return _frase(TOCCA["letto"], quando=_quando(letto_quando))
    return ""


def _dopo_frase(
    fase, tocca, ses, ag, aperte, chiusa_a_mano, ritorno, comprensione=None, rilettura=None
) -> str:
    ""
    comprensione = comprensione or {}
    rilettura = rilettura or {}
    n = len(aperte)
    if rilettura.get("aperta"):
        return DOPO[
            ("rilettura_confermato" if rilettura.get("modo") == "confermato" else "rilettura")
            + ("_in_fila" if rilettura.get("in_fila") else "")
        ]
    if fase == "da_capire":
        if comprensione.get("aperta"):
            return DOPO["comprensione"]
        if comprensione.get("ferma") or comprensione.get("chiusa_senza_finire"):
            return DOPO[
                "comprensione_ferma_riprovo"
                if comprensione.get("riprovo")
                else "comprensione_ferma"
            ]
        if comprensione.get("da_solo"):
            return DOPO[
                "visto_da_capire_da_solo"
                if comprensione.get("visto_quando")
                else "da_capire_da_solo"
            ]
        return (
            DOPO["visto_da_capire"] if comprensione.get("visto_quando") else DOPO["da_capire_fallo"]
        )
    if fase == "perche":
        if tocca == "pipeline":
            return DOPO["perche_pipeline"]
        return DOPO["perche_te_domande"] if n else DOPO["perche_te"]
    if fase == "lavorazione":
        if chiusa_a_mano:
            return DOPO["lavorazione_chiusa"]
        if tocca == "sessione":
            return DOPO["lavorazione_sessione"]
        if n:
            return (
                DOPO["lavorazione_domande_con_sessione"]
                if ses.get("aperta")
                else DOPO["lavorazione_domande_senza_sessione"]
            )
        return DOPO["lavorazione_apri"]
    if fase == "pronta":
        return DOPO["pronta"]
    if fase == "avviata":
        if str(ag.get("stato") or "") == "chiuso" and not ritorno:
            return ""
        return DOPO["avviata_te"] if tocca == "te" else DOPO["avviata_agente"]
    if fase == "arrivata":
        return "" if ag.get("ritorno_letto") else DOPO["arrivata"]
    return ""


def _percorso(
    fase,
    pc,
    ses,
    ag,
    aperte,
    perche,
    chiusa_a_mano,
    ritorno,
    letto_quando,
    rilettura=None,
    in_scrittura=False,
) -> list[dict]:
    ""


    if fase in FUORI_DAL_PERCORSO:
        return []
    cinque = [f for f in FASI if f[0] in ("perche", "lavorazione", "pronta", "avviata", "arrivata")]
    ordine = [f[0] for f in cinque]
    k = ordine.index(fase) if fase in ordine else (-1 if fase == "da_capire" else -1)
    if fase == "arrivata" and ag.get("ritorno_letto"):
        k = len(ordine)
    out = []
    for j, (fid, nome, _aiuto, _vuota) in enumerate(cinque):
        stato = "fatto" if j < k else ("adesso" if j == k else "poi")
        quando, aiuto = "", ""
        if fid == "perche":
            if pc.get("confermato"):
                quando = _quando(pc.get("confermato_quando"))
                aiuto = perche.get("stato_frase") or _frase(PERCORSO["perche_fatto"], quando=quando)
            elif stato == "fatto":
                aiuto = PERCORSO["perche_saltato"]
            elif stato == "adesso" and (rilettura or {}).get("aperta"):
                aiuto = PERCORSO[
                    "perche_rileggo_in_fila" if rilettura.get("in_fila") else "perche_rileggo"
                ]
            elif stato == "adesso" and in_scrittura:

                aiuto = (
                    in_scrittura
                    if isinstance(in_scrittura, str)
                    else TESTI["riquadro_perche_in_scrittura"]
                )
            else:
                aiuto = PERCORSO["perche_adesso"] if stato == "adesso" else PERCORSO["perche_poi"]
        elif fid == "lavorazione":
            if ses.get("aperta_quando"):
                quando = _quando(ses.get("aperta_quando"))
            if chiusa_a_mano and stato == "adesso":
                stato = "avviso"
                aiuto = (
                    _frase(TESTI["sessione_chiusa"], quando=_quando(ses.get("chiusa_quando")))
                    if "sessione_chiusa" in TESTI
                    else TOCCA["te_chiusa"]
                )
            elif ses.get("aperta"):
                aiuto = _frase(TOCCA["sessione"], quando=quando)
            elif stato == "fatto":
                aiuto = PERCORSO["lavorazione_fatto"]
            elif stato == "adesso":
                n = len(aperte)
                aiuto = (
                    PERCORSO["lavorazione_domanda"]
                    if n == 1
                    else (
                        PERCORSO["lavorazione_domande"].format(n=n)
                        if n
                        else PERCORSO["lavorazione_apri"]
                    )
                )
            else:
                aiuto = PERCORSO["lavorazione_poi"]
        elif fid == "pronta":
            aiuto = PERCORSO["pronta_adesso"] if stato == "adesso" else PERCORSO["pronta_poi"]
        elif fid == "avviata":
            if ag.get("avviato_quando"):
                quando = _quando(ag.get("avviato_quando"))
            if stato == "adesso" and str(ag.get("stato") or "") == "chiuso" and not ritorno:
                stato = "avviso"
                aiuto = TOCCA["te_chiusa"]
            elif stato == "poi":
                aiuto = PERCORSO["avviata_poi"]
            else:
                aiuto = _frase(PERCORSO["avviata_adesso"], quando=quando)
        else:
            if ag.get("ritorno_letto"):
                quando = _quando(letto_quando)
                aiuto = _frase(PERCORSO["arrivata_fatto"], quando=quando)
            elif ritorno:
                quando = _quando(ag.get("ritorno_quando"))
                aiuto = PERCORSO["arrivata_adesso"]
            else:
                aiuto = PERCORSO["arrivata_poi"]
        out.append(
            {
                "id": fid,
                "nome": PERCORSO["nomi"].get(fid, nome),
                "stato": stato,
                "quando": quando,
                "aiuto": aiuto,

                "frase": aiuto,
            }
        )
    return out


def _stato_scheda(fase, tocca, pc, ag, aperte, in_viaggio, rilettura=None) -> str:
    ""
    n = len(aperte)
    if (rilettura or {}).get("aperta"):
        return SCHEDA_STATO["rileggo"]
    if fase == "pronta":
        return SCHEDA_STATO["pronta"]
    if fase == "avviata":
        return (
            SCHEDA_STATO["te"]
            if str(ag.get("stato") or "") == "chiuso"
            else SCHEDA_STATO["avviata"]
        )
    if fase == "arrivata":
        return SCHEDA_STATO["letto"] if ag.get("ritorno_letto") else SCHEDA_STATO["arrivata"]
    if fase in FUORI_DAL_PERCORSO:
        return SCHEDA_STATO[fase]
    if fase in ("perche", "lavorazione"):
        if in_viaggio:
            return SCHEDA_STATO["in_trascrizione"]
        if tocca == "te":
            return (
                SCHEDA_STATO["te_domande"].format(domande=_conta_domande(n))
                if n
                else SCHEDA_STATO["te"]
            )
        if pc.get("confermato"):
            return (
                SCHEDA_STATO["confermato_domande"].format(domande=_conta_domande(n))
                if n
                else SCHEDA_STATO["confermato"]
            )
    return ""


def _badge(v: dict, visto: bool) -> dict | None:
    ""
    disp = str(_dict(v.get("disponibilita")).get("stato") or "")
    if disp == "vietato ai minori":
        return {"parola": FRASI["vietato"], "salute": "neutra", "aiuto": FRASI["vietato_aiuto"]}
    if disp in ("rimosso", "sparito"):
        return {"parola": FRASI["sparito"], "salute": "neutra", "aiuto": FRASI["sparito_aiuto"]}
    if (v.get("a_parte") or {}).get("si"):
        return None
    if not visto:
        nome = TIPI.get(v.get("tipo") or "", TIPI["video"])[3]
        return {"parola": nome, "salute": "attenzione", "aiuto": FRASI["non_visto_aiuto"]}
    return None


def _frase_online(v: dict) -> str:
    disp = _dict(v.get("disponibilita"))
    stato = str(disp.get("stato") or "")
    ultima = _quando(disp.get("visto_online_ultima_volta"))
    if stato == "online":
        return FRASI["online"].format(quando=ultima) if ultima else FRASI["online_senza_data"]
    if stato == "vietato ai minori":
        return FRASI["vietato_aiuto"]
    if stato in ("rimosso", "sparito"):
        return FRASI["sparito_aiuto"]
    if stato == "da ricontrollare":
        return FRASI["da_ricontrollare"]
    if stato == "mai controllato":
        return FRASI["mai_controllato"]
    if stato == "non raggiungibile":
        return FRASI["non_raggiungibile"]
    return ""


def _frase_contenuto(v: dict, visto: bool) -> str:
    cv = v.get("contenuto_visto") or {}
    if visto:
        cosa = [str(x) for x in (cv.get("cosa") or []) if x]
        return FRASI["visto"] + (f", {', '.join(cosa)}." if cosa else ".")
    manca = [str(x) for x in (cv.get("manca") or []) if x]
    base = TIPI.get(v.get("tipo") or "", TIPI["video"])[3] + "."
    if not manca:
        return base

    uno = len(manca) == 1 and not re.match(r"^(i|gli|le)\s", manca[0])
    return f"{base} {FRASI['manca' if uno else 'mancano'].format(cosa=', '.join(manca))}"


def _ultima_risposta_app(v: dict) -> str:
    ""

    quandi = []
    for d in (v.get("lavorazione") or {}).get("domande") or []:
        if not isinstance(d, dict) or not d.get("chiusa") or d.get("da_sistema"):
            continue
        risp = d.get("risposta") or {}
        if isinstance(risp, dict) and risp.get("testo") and risp.get("quando"):
            quandi.append(str(risp["quando"]))
    for p in v.get("pareri") or []:
        if not isinstance(p, dict) or p.get("tolto") or p.get("sostituito"):
            continue
        if not str(p.get("via") or "").startswith("app") or not (
            p.get("testo") or p.get("trascrizione")
        ):
            continue
        if p.get("audio") and p.get("audio_stato") != "trascritto":
            continue
        quandi.append(str(p.get("quando") or ""))
    return max(quandi) if quandi else ""


def _passo_dopo(fase, ses, aperte, perche, rilettura, ultima, azioni) -> dict:
    ""


    niente = {"conferma": False, "correggi": False, "ci_lavoriamo": False, "vai_sessione": False}
    out = {
        "c_e": False,
        "stato": "",
        "titolo": TESTI["passo_dopo"],
        "frase": "",
        "quando": "",
        "perche_breve": "",
        "dove_arrivare": "",
        "esito_parole": "",
        "azioni": niente,
    }
    if fase not in ("perche", "lavorazione") or not ultima:
        return out
    quando = _quando(ultima)
    n = len(aperte)
    out.update(c_e=True, quando=quando)
    if rilettura.get("aperta"):
        q = _quando(rilettura.get("risposta_quando")) or quando
        chiave = (
            "rileggo_risposta_confermato"
            if rilettura.get("modo") == "confermato"
            else "rileggo_risposta"
        ) + ("_in_fila" if rilettura.get("in_fila") else "")
        out.update(stato="rileggo", frase=_frase(TESTI[chiave], quando=q))
        return out
    if ses.get("aperta"):
        out.update(
            stato="sessione",
            frase=_frase(TESTI["risposta_alla_sessione"], quando=quando),
            azioni={**niente, "vai_sessione": True},
        )
        return out

    if (
        fase == "lavorazione"
        and rilettura.get("modo") == "confermato"
        and str(rilettura.get("risposta_quando") or "") >= str(ultima)
    ):
        lavora = {**niente, "ci_lavoriamo": bool(azioni.get("ci_lavoriamo"))}
        if rilettura.get("ferma"):
            out.update(
                stato="fermo",
                frase=_frase(
                    TESTI["rilettura_ferma_risposta"], quando=quando, motivo=rilettura["ferma"]
                ),
                azioni=lavora,
            )
            return out
        if rilettura.get("fatta"):
            chiave = (
                "riletto_confermato"
                if rilettura.get("dove_riscritto")
                else "riletto_confermato_uguale"
            )
            out.update(
                stato="riletto",
                frase=_frase(TESTI[chiave], quando=quando),
                perche_breve=str(perche.get("correzione") or perche.get("testo") or ""),
                dove_arrivare=str(perche.get("dove_arrivare") or ""),
                esito_parole=str(perche.get("esito_parole") or ""),
                azioni=lavora,
            )
            return out
    if fase == "lavorazione":
        out.update(
            stato="ci_lavoriamo",
            frase=_frase(TESTI["risposta_ci_lavoriamo"], quando=quando),
            azioni={**niente, "ci_lavoriamo": bool(azioni.get("ci_lavoriamo"))},
        )
        return out
    gesti = {
        "conferma": bool(azioni.get("conferma")),
        "correggi": bool(azioni.get("correggi")),
        "ci_lavoriamo": bool(azioni.get("ci_lavoriamo")),
        "vai_sessione": False,
    }

    per_questa = str(rilettura.get("risposta_quando") or "") >= str(ultima)
    if rilettura.get("ferma") and per_questa:
        out.update(
            stato="fermo",
            frase=_frase(
                TESTI["rilettura_ferma_risposta"], quando=quando, motivo=rilettura["ferma"]
            ),
            azioni=gesti,
        )
        return out
    if rilettura.get("fatta") and per_questa:
        if not rilettura.get("perche_riscritto"):
            chiave = "riletto_uguale"
        else:
            chiave = "riletto_risposta_domande" if n else "riletto_risposta"
        out.update(
            stato="riletto",
            frase=_frase(TESTI[chiave], quando=quando, domande=_conta_domande(n)),
            perche_breve=str(perche.get("testo") or ""),
            dove_arrivare=str(perche.get("dove_arrivare") or ""),
            esito_parole=str(perche.get("esito_parole") or ""),
            azioni=gesti,
        )
        return out
    out.update(
        stato="tocca_a_te", frase=_frase(TESTI["risposta_perche_te"], quando=quando), azioni=gesti
    )
    return out


def _lavorazione(v: dict) -> dict:
    ""


    L = v.get("lavorazione") or {}
    pc = L.get("perche") or {}
    ses = L.get("sessione") or {}
    pi = L.get("piano") or {}
    ag = (v.get("attivita") or {}).get("agente") or {}
    fase = str(v.get("fase") or "").replace("da capire", "da_capire")
    domande = _domande(v)

    pc = {
        **pc,
        "_smistato_quando": ((L.get("smistamento") or {}).get("confermato") or {}).get("quando")
        or "",
    }
    perche = _perche(v, pc)
    if fase in FUORI_DAL_PERCORSO:


        if fase == "tenuta" and pc.get("confermato"):
            perche["stato_frase"] = _frase(
                TESTI["perche_tenuto"], quando=_quando(pc.get("confermato_quando"))
            )
        for d in domande:
            if not d["chiusa"]:
                d.update(
                    chiusa=True,
                    da_sistema=True,
                    risposta=TESTI["domanda_non_serve"],
                    in_trascrizione=False,
                    stato="",
                    stato_frase="",
                )


    aperte = [d for d in domande if not d["chiusa"] and d["stato"] not in IN_VIAGGIO]
    tocca = str(v.get("tocca") or "")
    if (
        tocca != "te"
        and fase in ("perche", "lavorazione")
        and any(d["stato"] in RIAPRONO for d in aperte)
    ):

        tocca = "te"
    aperta = bool(ses.get("aperta"))
    chiusa_a_mano = (
        bool(ses.get("chiusa_quando")) and not aperta and fase in ("perche", "lavorazione")
    )
    avviato = bool(ag.get("avviato_quando") or ag.get("pannello"))
    ritorno = _file(ag.get("ritorno"))
    scheda = _file((L.get("scheda") or {}).get("file"))
    permessi = PERMESSI.get(str(ag.get("permessi") or pi.get("permessi") or ""), "")
    in_viaggio = any(d["stato"] in IN_VIAGGIO for d in domande) or (
        perche["correzione_in_arrivo"] and perche["correzione_stato"] in IN_VIAGGIO
    )
    letto_quando = _letto_quando(ag, v)
    conferma = bool(pc.get("testo")) and not pc.get("confermato") and fase in ("perche", "pronta")

    cv = v.get("contenuto_visto") or {}
    com = L.get("comprensione") or {}
    esito_com = com.get("esito") if isinstance(com.get("esito"), dict) else {}
    comprensione = {
        "visto_quando": str(cv.get("quando") or "") if cv.get("si") else "",
        "aperta": bool(com.get("aperta_quando"))
        and not com.get("chiusa_quando")
        and fase == "da_capire",
        "aperta_quando": str(com.get("aperta_quando") or ""),
        "titolo": _emoji(str(com.get("titolo") or "")),

        "ferma": _parole_semplici(str(esito_com.get("motivo") or ""))
        if esito_com.get("stato") == "fermo" and fase == "da_capire"
        else "",
        "ferma_quando": str(esito_com.get("quando") or com.get("chiusa_quando") or ""),
        "chiusa_senza_finire": bool(com.get("chiusa_quando"))
        and not esito_com
        and fase == "da_capire"
        and bool(com.get("aperta_quando")),

        "sottofondo": bool(com.get("sottofondo")),
    }

    da_solo = _ritmo_acceso()
    comprensione["da_solo"] = da_solo


    comprensione["riprovo"] = da_solo and not _fermo_vero(com)



    aperta_vera = bool(com.get("aperta_quando")) and not com.get("chiusa_quando")
    in_scrittura = aperta_vera and fase == "perche" and not pc.get("testo")
    g3 = _g3(v, str(com.get("aperta_quando") or "")) if fase == "da_capire" or aperta_vera else {}
    sceso = bool(cv.get("si")) or bool(g3.get("sceso"))
    attesa = _attesa(v, fase, aperta_vera, sceso, com)
    comprensione["attesa"] = attesa


    ri = L.get("rilettura") or {}
    esito_ri = ri.get("esito") if isinstance(ri.get("esito"), dict) else {}
    rilettura = {
        "aperta": bool(ri.get("aperta_quando"))
        and not ri.get("chiusa_quando")
        and fase in ("perche", "lavorazione"),

        "in_fila": _rilettura_in_fila(ri),

        "modo": str(ri.get("modo") or "proposta"),
        "dove_riscritto": bool(esito_ri.get("dove_riscritto")),
        "aperta_quando": str(ri.get("aperta_quando") or ""),
        "risposta_quando": str(ri.get("risposta_quando") or ""),
        "fatta": esito_ri.get("stato") == "fatto",
        "ferma": str(esito_ri.get("motivo") or "") if esito_ri.get("stato") == "fermo" else "",
        "quando": str(esito_ri.get("quando") or ri.get("chiusa_quando") or ""),
        "perche_riscritto": bool(esito_ri.get("perche_riscritto")),
    }
    if rilettura["aperta"]:
        tocca = ""
        conferma = False
    azioni = {
        "conferma": conferma,

        "correggi": bool(pc.get("testo"))
        and not rilettura["aperta"]
        and (conferma or perche["correzione_in_arrivo"] or (fase == "lavorazione" and not scheda)),
        "ci_lavoriamo": fase in ("perche", "lavorazione")
        and not aperta
        and not rilettura["aperta"],
        "vai_sessione": aperta,
        "avvia": fase == "pronta",


        "avvia_task": fase == "pronta" and _avvia_task_si(v, fase),
        "vai_lavoro": avviato and not ritorno and ag.get("stato") != "chiuso",
        "ritorno_letto": bool(ritorno) and not ag.get("ritorno_letto"),
        "rispondi": fase not in ("da_capire", "a parte", ""),

        "capisci": fase == "da_capire" and not comprensione["aperta"],

        "capisci_pannello": fase == "da_capire" and not comprensione["aperta"],
        "vai_comprensione": comprensione["aperta"] and not comprensione["sottofondo"],
    }


    azioni["capisci_pannello_menu"] = azioni["capisci_pannello"]
    if attesa in ("scende", "sceso", "si", "riprovo"):
        azioni["capisci_pannello"] = False



    sceso_quando = str(g3.get("sceso_quando") or "") or (
        str(cv.get("quando") or "") if cv.get("si") else ""
    )
    riquadro, riquadro_dopo = "", None


    perche_mancante = (
        fase == "perche"
        and not pc.get("testo")
        and not aperta_vera
        and not rilettura["aperta"]
        and not aperta
    )

    frase_capito = (
        _frase(TESTI["riquadro_capisco_scrivo"], quando=_quando(g3.get("dossier_quando")))
        if g3.get("dossier")
        else TESTI["riquadro_perche_in_scrittura"]
    )
    if in_scrittura:
        riquadro, riquadro_dopo = frase_capito, ""

        azioni["ci_lavoriamo"] = False
    elif attesa == "capisco":
        if g3.get("dossier"):
            riquadro = _frase(
                TESTI["riquadro_capisco_scrivo"], quando=_quando(g3.get("dossier_quando"))
            )
        else:
            riquadro = _frase(
                TOCCA["comprensione_sottofondo" if comprensione["sottofondo"] else "comprensione"],
                quando=_quando(comprensione["aperta_quando"]),
            )
        riquadro_dopo = ""
    elif perche_mancante:
        riquadro = TESTI[
            "riquadro_perche_mancante" if da_solo else "riquadro_perche_mancante_spento"
        ]
        riquadro_dopo = ""
    elif attesa == "a_vuoto":
        riquadro = TESTI["riquadro_a_vuoto_acceso" if _riparte_da_solo() else "riquadro_a_vuoto"]
        riquadro_dopo = ""
    elif attesa == "riprovo":


        esito_q = _dict(com.get("esito"))
        riquadro = TESTI["segno_riprovo_aiuto"].format(
            motivo=_motivo_frase(
                _quando(str(esito_q.get("quando") or com.get("chiusa_quando") or "")),
                _motivo_fermo(com),
            )
        )
        riquadro_dopo = ""
    elif attesa in ("scende", "si", "vietato", "sparito"):
        riquadro, riquadro_dopo = TESTI[f"riquadro_{attesa}"], ""
    elif attesa == "sceso":
        riquadro, riquadro_dopo = _frase(TESTI["riquadro_sceso"], quando=_quando(sceso_quando)), ""
    elif attesa == "aspetta_si":
        riquadro, riquadro_dopo = TESTI["riquadro_aspetta_si"], TESTI["riquadro_aspetta_si_dopo"]
        tipo_v = str(v.get("tipo") or "")
        pf = PIATTAFORME.get(str(v.get("piattaforma") or "").lower(), "")
        if tipo_v == "post" and pf == "LinkedIn":

            riquadro = _frase(
                TESTI["riquadro_aspetta_si_domanda"], cosa=f"{TIPI[tipo_v][0].lower()} {pf}"
            )
    tocca_frase = riquadro or _tocca_frase(
        fase, tocca, pc, ses, ag, aperte, chiusa_a_mano, letto_quando, comprensione, rilettura
    )
    dopo_frase = (
        riquadro_dopo
        if riquadro_dopo is not None
        else _dopo_frase(
            fase, tocca, ses, ag, aperte, chiusa_a_mano, ritorno, comprensione, rilettura
        )
    )
    if attesa in ("vietato", "sparito", "fermo", "aspetta_si", "a_vuoto"):
        contenuto_salute = "attenzione"
    elif cv.get("si"):
        contenuto_salute = "ok"
    else:
        contenuto_salute = "neutra"
    interno = {
        "attesa": attesa,
        "in_scrittura": in_scrittura,
        "frase_capito": frase_capito,
        "perche_mancante": perche_mancante,
        "aperta_vera": aperta_vera,

        "gruppo": [str(x) for x in (com.get("voci") or [])] if aperta_vera else [],
        "aperta_quando": str(com.get("aperta_quando") or ""),
        "sceso": sceso,
        "sceso_quando": sceso_quando,
        "dossier": bool(g3.get("dossier")),
        "dossier_quando": str(g3.get("dossier_quando") or ""),
        "motivo": _motivo_fermo(com),

        "motivo_ultimo": str(_dict(com.get("esito")).get("motivo_ultimo") or ""),
        "tre_volte": int(com.get("tentativi") or 0) >= TENTATIVI_COMPRENSIONE
        and not _ripresa_fermata(com)
        and int(com.get("tentativi_a_vuoto") or 0) < TETTO_A_VUOTO,
        "fermo_quando": str(
            (com.get("esito") or {}).get("quando") or com.get("chiusa_quando") or ""
        )
        if isinstance(com.get("esito") or {}, dict)
        else str(com.get("chiusa_quando") or ""),
        "contenuto_salute": contenuto_salute,
    }
    stato_riquadro = riquadro or (tocca_frase if fase == "da_capire" else "")


    t2 = _tappa2(
        v,
        {
            "fase": fase,
            "L": L,
            "pc": pc,
            "ses": ses,
            "pi": pi,
            "ag": ag,
            "domande": domande,
            "aperte": aperte,
            "tocca": tocca,
            "rilettura": rilettura,
            "in_viaggio": in_viaggio,
            "chiusa_a_mano": chiusa_a_mano,
            "aperta": aperta,
            "ritorno": ritorno,
            "scheda": scheda,
            "attesa": attesa,
            "stato_riquadro": stato_riquadro or tocca_frase,
            "azioni": azioni,
            "perche": perche,
            "in_scrittura": in_scrittura,
            "perche_mancante": perche_mancante,
            "letto_quando": letto_quando,
            "permessi": permessi,
            "comprensione": comprensione,
        },
    )
    interno["nuovo"] = t2.pop("_nuovo")
    interno["nuovo_quando"] = t2.pop("_nuovo_quando")
    rifai = t2.pop("_rifai", None)

    interno["agente_aperto_quando"] = str(ses.get("aperta_quando") or "") if aperta else ""
    if aperta:



        if (t2.get("adesso") or {}).get("chi") == "te":
            tocca = "te"
        elif tocca == "te":
            tocca = "sessione"
    return {
        **t2,
        "_interno": interno,
        "fase": fase,

        "smistamento": _smistamento(v, L, pc, fase),
        "tocca": tocca,
        "tocca_frase": tocca_frase,

        "stato_riquadro": stato_riquadro,
        "stato_scheda": _stato_scheda(fase, tocca, pc, ag, aperte, in_viaggio, rilettura),

        "percorso": _percorso(
            fase,
            pc,
            ses,
            ag,
            aperte,
            perche,
            chiusa_a_mano,
            ritorno,
            letto_quando,
            rilettura,
            frase_capito if in_scrittura else False,
        ),
        "percorso_parole": {k: PERCORSO[k] for k in ("titolo", "fatto", "adesso", "poi")},
        "dopo_frase": dopo_frase,
        "rilettura": {
            "aperta": rilettura["aperta"],
            "in_fila": rilettura["aperta"] and rilettura["in_fila"],
            "quando": _quando(rilettura["aperta_quando"]) if rilettura["aperta_quando"] else "",
            "fatta": rilettura["fatta"],
            "ferma": rilettura["ferma"],
        },

        "passo_dopo": _passo_dopo(
            fase,
            {"aperta": aperta},
            aperte,
            perche,
            rilettura,
            _ultima_risposta_app(v),
            azioni,
        ),
        "comprensione": {
            "aperta": comprensione["aperta"],
            "quando": _quando(comprensione["aperta_quando"])
            if comprensione["aperta_quando"]
            else "",
            "titolo": comprensione["titolo"],
            "sottofondo": comprensione["sottofondo"],
        },
        "perche": perche,
        "domande": domande,
        "sessione": {
            "aperta": aperta,
            "c_e": bool(ses.get("aperta_quando")),
            "titolo": str(ses.get("titolo") or ""),
            "quando": _quando(ses.get("aperta_quando")),
            "chiusa_quando": _quando(ses.get("chiusa_quando")),
        },
        "piano": {
            "c_e": bool(pi.get("passi") or pi.get("punto_di_arrivo")),
            "passi": [str(x) for x in pi.get("passi") or []],
            "dati": [str(x) for x in pi.get("dati") or []],
            "punto_di_arrivo": str(pi.get("punto_di_arrivo") or ""),
            "cosa_non_fare": [str(x) for x in pi.get("cosa_non_fare") or []],
            "permessi": PERMESSI.get(str(pi.get("permessi") or ""), ""),
        },
        "scheda": scheda,
        "lavoro": {
            "avviato": avviato,
            "titolo": str(ag.get("titolo") or ""),
            "quando": _quando(ag.get("avviato_quando")),
            "permessi": permessi,
            "ritorno": ritorno,
            "ritorno_parziale": _file(ag.get("ritorno_parziale")),
            "ritorno_letto": bool(ag.get("ritorno_letto")),
            "finito_quando": _quando(ag.get("ritorno_quando")) if ritorno else "",
            "letto_quando": _quando(letto_quando) if ag.get("ritorno_letto") else "",
            "chiuso": str(ag.get("stato") or "") == "chiuso",
            "task": str((v.get("attivita") or {}).get("task_url") or ""),



            **_task_del_lavoro(v),

            **(
                {"task_rifai": rifai}
                if rifai
                and str((v.get("attivita") or {}).get("task_url") or "").startswith("attivita:")
                else {}
            ),
        },
        "cartella": str(L.get("cartella") or ""),

        "cartella_registro": os.path.join(RADICE, "archivio"),
        "azioni": azioni,
    }









PASSI6 = ("capire", "scope", "contesto", "ricerca", "implementazione", "test")

PASSI_STUDIO = PASSI6[:4]

USCITE = ("riferimento", "cosa_da_fare", "non_serve", "letto")
STRADE = ("riferimento", "studio", "cosa_da_fare", "sviluppo", "non_serve")
STRADE_USCITA = ("riferimento", "cosa_da_fare", "non_serve")
TIPI_SCOPE = ("funzione", "strumento", "contenuto", "negozio_sito", "idea_societa", "lettura")

def _progetti_scope() -> tuple[str, ...]:
    """Projects for scope tagging: "inspiration.projects" in sbk.config.json, otherwise your
    own organisations ("organisations.names"); then SBK, personale (personal), altro (other)."""
    tools = Path(__file__).resolve().parents[1]
    if str(tools) not in sys.path:
        sys.path.insert(0, str(tools))
    try:
        from sbk_config import OWN_ORG_DISPLAY_NAMES, user_cfg
    except ImportError:
        own: list[str] = []
    else:
        own = [str(p).strip() for p in (user_cfg("inspiration.projects", []) or OWN_ORG_DISPLAY_NAMES)]
    return tuple(dict.fromkeys([p for p in own if p] + ["SBK", "personale", "altro"]))


PROGETTI_SCOPE = _progetti_scope()
# Areas for scope tagging. Override via user config.
AREE_PAROLE = {
    "prodotto": "Product",
    "marketing": "Marketing",
    "contenuti": "Content",
    "social": "Social",
    "sito": "Site",
    "ecommerce": "E-commerce",
    "vendite": "Sales",
    "operativo": "Operations",
    "altro": "Other",
}


PASSO_DA_SERVE_PER = {
    "perche": "scope",
    "lavorazione": "contesto",
    "dato": "contesto",
    "permesso": "implementazione",
    "": "scope",
}

NUOVO_GIORNI = 3

DOMANDE_A_VISTA = 2

_CHIAVI_PERCORSO = frozenset(
    ("audio", "permalink", "file", "cartella", "correzione_audio", "correzione_audio_file", "url")
)


def _adesso_ora() -> datetime.datetime:
    ""
    return datetime.datetime.now()


def _nfc(x):
    ""

    if isinstance(x, str):
        return unicodedata.normalize("NFC", x)
    if isinstance(x, list):
        return [_nfc(y) for y in x]
    if isinstance(x, dict):
        return {k: (y if k in _CHIAVI_PERCORSO else _nfc(y)) for k, y in x.items()}
    return x


def _nfc_di_owner(v: dict) -> dict:
    ""


    if not isinstance(v, dict):
        return v
    v = dict(v)
    if isinstance(v.get("pareri"), list):
        v["pareri"] = _nfc(v["pareri"])
    if isinstance(v.get("cattura"), dict):
        v["cattura"] = {**v["cattura"], "testo_di_owner": _nfc(v["cattura"].get("testo_di_owner"))}
    if isinstance(v.get("domande"), list):
        v["domande"] = [
            {
                **d,
                **{k: _nfc(d[k]) for k in ("risposta", "trascrizione") if k in d},
            }
            if isinstance(d, dict)
            else d
            for d in v["domande"]
        ]
    if isinstance(v.get("domande_owner"), list):
        v["domande_owner"] = [
            {**d, "risposta": _nfc(d["risposta"])} if isinstance(d, dict) and "risposta" in d else d
            for d in v["domande_owner"]
        ]
    L = v.get("lavorazione")
    if isinstance(L, dict):
        L = dict(L)
        if isinstance(L.get("perche"), dict):
            L["perche"] = {
                **L["perche"],
                **{
                    k: _nfc(L["perche"][k])
                    for k in ("correzione", "correzione_trascrizione")
                    if k in L["perche"]
                },
            }
        if isinstance(L.get("domande"), list):
            L["domande"] = [
                {**d, "risposta": _nfc(d["risposta"])}
                if isinstance(d, dict) and "risposta" in d
                else d
                for d in L["domande"]
            ]
        if isinstance(L.get("scope"), dict):
            L["scope"] = {
                **L["scope"],
                **{
                    k: _nfc(L["scope"][k])
                    for k in ("correzioni", "domande_di_owner", "info_chiave", "verbo_di_owner")
                    if k in L["scope"]
                },
            }
        v["lavorazione"] = L
    return v


def _passo_domanda(d: dict) -> str:
    ""

    p = str(d.get("passo") or "")
    if p in PASSI6:
        return p
    if d.get("policy"):
        return "scope"
    if str(d.get("da") or "") == "sessione di lavoro":
        return "implementazione"
    return PASSO_DA_SERVE_PER.get(str(d.get("serve_per") or ""), "scope")


def _strada_derivata(v: dict, fase: str) -> str:
    ""

    L = _dict(v.get("lavorazione"))
    pc = _dict(L.get("perche"))
    sm = _dict(L.get("smistamento"))
    esito_sm = str(
        _dict(sm.get("confermato")).get("esito") or _dict(sm.get("proposta")).get("esito") or ""
    )
    if fase == "tenuta":
        return "riferimento"
    if fase == "scartata":
        return "non_serve"
    if fase == "in_clickup":
        return "cosa_da_fare"
    if not pc.get("testo"):
        return ""
    if esito_sm == "scartato":
        return "non_serve"
    if esito_sm == "tenuto":
        return "riferimento"
    if str(_dict(v.get("destinazione")).get("tipo") or "") == "da leggere":
        return "studio"
    if esito_sm in ("to do", "backlog") and str(pc.get("esito") or "") in (
        "contenuto",
        "da tenere",
        "ispirazione",
    ):
        return "cosa_da_fare"
    return "sviluppo"


def _scope_di(v: dict, fase: str) -> dict:
    ""

    L = _dict(v.get("lavorazione"))
    pc = _dict(L.get("perche"))
    sm = _dict(L.get("smistamento"))
    prop = _dict(sm.get("proposta"))
    conf = _dict(sm.get("confermato"))
    dest = _dict(v.get("destinazione"))
    strada = _strada_derivata(v, fase)
    derivato = {
        "versione": 0,
        "quando": str(pc.get("quando") or ""),
        "da": "derivato",
        "cosa_intendi": str(pc.get("testo") or ""),
        "verbo_di_owner": "",
        "strada": strada,
        "tipo": "",
        "progetto": str(pc.get("progetto") or dest.get("progetto") or ""),
        "area": str(conf.get("attivita") or prop.get("attivita") or ""),
        "chi": str(prop.get("chi_esegue") or "team") if strada == "cosa_da_fare" else "",
        "delicato": bool(prop.get("delicato")),
        "dove_arrivare": str(pc.get("dove_arrivare") or ""),
        "info_chiave": [],
        "altre_linee": [str(x) for x in (dest.get("secondarie") or []) if x],
        "sicurezza": str(pc.get("sicurezza") or ""),
        "su_cosa_poggia": str(pc.get("su_cosa_poggia") or ""),
        "confermato": bool(pc.get("confermato")) and bool(conf),
        "confermato_quando": str(conf.get("quando") or pc.get("confermato_quando") or "")
        if pc.get("confermato") and conf
        else "",
        "correzioni": [],
        "domande_di_owner": [],
        "storia": [x for x in (pc.get("proposte_di_prima") or []) if isinstance(x, dict)],
    }
    scritto = _dict(L.get("scope"))
    if not scritto:
        return derivato
    return {**derivato, **{k: x for k, x in scritto.items() if x is not None}}


def _passo_di(v: dict, fase: str, scope: dict, L: dict) -> str:
    ""


    scritto = str(v.get("passo") or L.get("passo") or "")
    studio = scope.get("strada") == "studio" and scope.get("confermato")
    if scritto in PASSI6 or scritto in USCITE or scritto == "a_parte":

        return "ricerca" if studio and scritto in PASSI6[4:] else scritto
    if fase == "a parte":
        return "a_parte"
    if fase == "tenuta":
        return "riferimento"
    if fase == "scartata":
        return "non_serve"
    if fase == "in_clickup":
        return "cosa_da_fare"
    if fase in ("arrivata", "pronta", "avviata") and studio:
        return "ricerca"
    if fase == "arrivata":
        return "test"
    if fase in ("pronta", "avviata"):
        return "implementazione"
    if fase in ("da_capire", "") or not _dict(L.get("perche")).get("testo"):
        return "capire"
    if not scope.get("confermato"):
        return "scope"
    if scope.get("strada") in STRADE_USCITA:
        return scope["strada"]
    pi = _dict(L.get("piano"))
    return (
        "ricerca"
        if (pi.get("file") or pi.get("passi") or pi.get("punto_di_arrivo"))
        else "contesto"
    )


def _parola_progetto(p: str) -> str:
    if not p or p == "altro":
        return TESTI["senza_progetto"]
    return _maiuscola(p)


def _dove_pulito(testo: str) -> str:
    dove = re.sub(r"^\s*vuoi arrivare a\s+", "", str(testo or ""), flags=re.I)
    return _maiuscola(dove) if dove else ""


def _chiave_owner_da_fare() -> str:
    ""

    return (
        "strada_cosa_da_fare_attivita"
        if _cfg().get("task_in_attivita") is True
        else "strada_cosa_da_fare_owner"
    )


def _chiave_cosa_da_fare(scope: dict) -> str:
    ""

    if scope.get("delicato"):
        return "strada_cosa_da_fare"
    if scope.get("chi") == "owner":
        return _chiave_owner_da_fare()
    return "strada_cosa_da_fare_team"


def _strada_frase(scope: dict) -> str:
    strada = str(scope.get("strada") or "")
    if not strada:
        return ""
    if strada == "cosa_da_fare":
        base = TESTI[_chiave_cosa_da_fare(scope)]
    else:
        base = TESTI.get(f"strada_{strada}", "")
    tipo = str(scope.get("tipo") or "")

    if (
        strada in ("studio", "sviluppo")
        and tipo in TIPI_SCOPE
        and not (strada == "sviluppo" and tipo == "lettura")
    ):
        return TESTI["strada_con_tipo"].format(strada=base, tipo=TESTI[f"tipo_{tipo}"])
    return base


def _dove_va_frase(scope: dict) -> str:
    pezzi = [_parola_progetto(str(scope.get("progetto") or ""))]
    area = str(scope.get("area") or "")
    if area and area != "altro":

        pezzi.append(AREE_PAROLE.get(area, area))
    return ", ".join(pezzi)


def _riga_scope(scope: dict) -> str:
    ""
    return ". ".join(x for x in (_strada_frase(scope), _dove_va_frase(scope)) if x)


def _lista_team(scope: dict, v: dict) -> dict:
    ""
    S = _smista_regole()
    prop = _dict(_dict(_dict(v.get("lavorazione")).get("smistamento")).get("proposta"))
    esito = str(prop.get("esito") or "")
    return S.destinazione(
        esito if esito in S.CON_TASK else "to do",
        str(scope.get("progetto") or "") or "altro",
        str(scope.get("area") or ""),
        "team",
        bool(scope.get("delicato")),
    )





RIGHE = {
    "giusto": "scope --giusto",
    "raddrizza": "scope",
    "capisci": "capisci",
    "rispondi": "rispondi",
    "ci_lavoriamo": "ci-lavoriamo",
    "vai": "vai",
    "vai_lavoro": "vai --lavoro",
    "avvia": "avvia",
    "letto": "ritorno-letto",

    "letto_studio": "letto",
    "riapri": "riapri",
    "rifai": "scope --rifai",
    "tieni": "scope --tieni",
    "crea_task": "crea-task",

    "rifalla": "crea-task --rifai",

    "prendi_proposta": "scope --prendi-proposta",
    "leggi_scheda": "",
    "leggi_ritorno": "",
}


def _pulsante(verbo: str, parola: str, aiuto: str = "", parola_con_testo: str = "") -> dict:
    ""

    return {
        "verbo": verbo,
        "riga": RIGHE.get(verbo, ""),
        "riga_con_testo": RIGHE.get(verbo, ""),
        "parola": parola,
        "parola_con_testo": parola_con_testo or parola,
        "aiuto": aiuto,
        "aiuto_con_testo": aiuto,
    }


def _secondario(verbo: str, parola: str, aiuto: str = "") -> dict:
    return {"verbo": verbo, "riga": RIGHE.get(verbo, ""), "parola": parola, "aiuto": aiuto}


def _giusto(scope: dict, v: dict) -> tuple[dict, str]:
    ""
    strada = str(scope.get("strada") or "")
    if strada == "riferimento":
        return (
            _pulsante(
                "giusto",
                TESTI["giusto_tienilo"],
                TESTI["aiuto_giusto_tienilo"],
                TESTI["manda_conferma"],
            ),
            TESTI["poi_scope_riferimento"],
        )
    if strada == "non_serve":
        return (
            _pulsante(
                "giusto",
                TESTI["giusto_non_serve"],
                TESTI["aiuto_giusto_non_serve"],
                TESTI["manda_conferma"],
            ),
            TESTI["poi_scope_non_serve"],
        )
    if strada == "cosa_da_fare":
        if scope.get("delicato"):

            return (
                _pulsante(
                    "giusto",
                    TESTI["giusto_cosa_da_fare"],
                    TESTI["aiuto_giusto_delicato"],
                    TESTI["manda_conferma"],
                ),
                TESTI["poi_scope_delicato"],
            )
        if not _task_accese(scope):

            return (
                _pulsante(
                    "giusto",
                    TESTI[
                        "giusto_cosa_da_fare"
                        if scope.get("chi") == "owner"
                        else "giusto_team_da_fare"
                    ],
                    TESTI["aiuto_giusto_senza_task"],
                    TESTI["manda_conferma"],
                ),
                TESTI["poi_scope_senza_task"],
            )
        if scope.get("chi") == "owner":
            return (
                _pulsante(
                    "giusto",
                    TESTI["giusto_attivita"],
                    TESTI["aiuto_giusto_attivita"],
                    TESTI["manda_conferma"],
                ),
                TESTI["poi_scope_attivita"],
            )
        d = _lista_team(scope, v)
        aiuto = TESTI["aiuto_giusto_team"].format(lista=" / ".join(d.get("percorso") or []))
        if d.get("nota"):
            aiuto += f". {_maiuscola(d['nota'])}"
        return (
            _pulsante("giusto", TESTI["giusto_team"], aiuto, TESTI["manda_conferma"]),
            TESTI["poi_scope_team"],
        )
    if strada in ("sviluppo", "studio"):

        return (
            _pulsante(
                "giusto",
                TESTI[f"giusto_{strada}"],
                TESTI["aiuto_giusto_avanti"],
                TESTI["manda_conferma"],
            ),
            TESTI["poi_scope_avanti"],
        )

    return (
        _pulsante(
            "giusto", TESTI["giusto_avanti"], TESTI["aiuto_giusto_avanti"], TESTI["manda_avanti"]
        ),
        TESTI["poi_scope_avanti"],
    )


def _giusto_resta_nel_percorso(scope: dict) -> bool:
    ""

    return str(scope.get("strada") or "") not in STRADE_USCITA


def _esce_col_giusto(scope: dict) -> bool:
    ""


    strada = str(scope.get("strada") or "")
    if strada in ("riferimento", "non_serve"):
        return True
    if strada == "cosa_da_fare":
        return bool(scope.get("delicato")) or _task_accese(scope)
    return False


def _avvia_task_si(v: dict, fase: str) -> bool:
    ""

    if _cfg().get("task_in_attivita") is not True:
        return False
    return not _scope_di(v, fase).get("delicato")


def _task_accese(scope: dict) -> bool:
    ""

    chiave = "task_in_attivita" if scope.get("chi") == "owner" else "task_su_clickup"
    return _cfg().get(chiave) is True


def _nuovo_giorni(cfg: dict | None = None) -> int:
    try:
        n = int((cfg if cfg is not None else _cfg()).get("nuovo_giorni"))
    except (TypeError, ValueError):
        return NUOVO_GIORNI
    return n if n >= 0 else NUOVO_GIORNI


def _nuovo(attese: list[str], ultimo_gesto: str) -> tuple[bool, str]:
    ""


    date = [a[:19] for a in attese if a]
    if not date:
        return bool(attese), ""
    piu_nuova = max(date)
    soglia = (_adesso_ora() - datetime.timedelta(days=_nuovo_giorni())).isoformat(
        timespec="seconds"
    )
    nuovo = any(d >= soglia or (ultimo_gesto and d > ultimo_gesto) for d in date)
    return nuovo, piu_nuova




CAMPI_STRUTTURA = ("strada", "tipo", "progetto", "area", "chi", "delicato")



DA_RISCRITTURA_QUIETA = ("rilettura",)


def _struttura_scope(x: dict) -> tuple:
    ""
    return tuple(
        bool(x.get(k)) if k == "delicato" else str(x.get(k) or "") for k in CAMPI_STRUTTURA
    )


def _domande_di_owner_aperte(x: dict) -> int:
    ""
    return sum(
        1
        for q in x.get("domande_di_owner") or []
        if isinstance(q, dict)
        and not str(q.get("risposta") or "").strip()
        and not q.get("non_era_una_domanda")
    )


def _versione_di(x: dict) -> int:
    try:
        return int(x.get("versione") or 0)
    except (TypeError, ValueError):
        return 0


def _versione_prima(scope: dict, versione: int) -> dict | None:
    ""


    prima = [
        x
        for x in scope.get("storia") or []
        if isinstance(x, dict)
        and "fonte" not in x
        and "versione" in x
        and _versione_di(x) < versione
    ]
    if not prima:
        return None
    return max(prima, key=lambda x: (_versione_di(x), str(x.get("quando") or "")))


def _quando_della_proposta(scope: dict) -> str:
    ""




    quando = str(scope.get("quando") or "")
    cur = scope
    while str(cur.get("da") or "") in DA_RISCRITTURA_QUIETA:
        prima = _versione_prima(scope, _versione_di(cur))
        if prima is None or str(prima.get("da") or "") == "owner":
            break
        if _struttura_scope(prima) != _struttura_scope(cur):
            break
        if _domande_di_owner_aperte(cur) > _domande_di_owner_aperte(prima):
            break
        q = str(prima.get("quando") or "")
        if not q:
            break
        quando, cur = q, prima
    return quando


def _altre_attese_allo_scope(v: dict, passo: str) -> list[str]:
    ""

    out = [
        str(d.get("quando") or "")[:19]
        for d in v.get("domande") or []
        if isinstance(d, dict)
        and not d.get("chiusa")
        and not d.get("in_trascrizione")
        and str(d.get("passo") or "") == passo
    ]
    L = _dict(v.get("lavorazione"))
    ses = _dict(L.get("sessione"))
    ag = _dict(_dict(v.get("attivita")).get("agente"))
    for a in (ses.get("aspetta") if ses.get("aperta") else None, ag.get("aspetta")):
        if isinstance(a, dict) and a.get("si"):
            out.append(str(a.get("quando") or a.get("letto_quando") or "")[:19])
            break
    return [x for x in out if x]


def _attese_con_la_proposta_di_prima(
    attese: list[str], qs: dict, passo: str, scope: dict, v: dict
) -> list[str]:
    ""



    if passo != "scope" or not attese or "proposta" not in (qs.get("aspetta") or []):
        return attese
    q_prop = str(scope.get("quando") or "")[:19]
    q_prima = _quando_della_proposta(scope)[:19]
    if not q_prop or not q_prima or q_prima >= q_prop or attese[0][:19] != q_prop:
        return attese
    return [max([q_prima, *_altre_attese_allo_scope(v, passo)])]


def _q(x) -> str:
    return _quando(str(x or ""))


def _in_mano_all_agente(d: dict, v: dict, ses: dict) -> bool:
    ""


    if d.get("policy"):
        return False
    if str(d.get("da") or "") == "sessione dello spunto":
        return True
    raw = next(
        (
            x
            for x in v.get("domande") or []
            if isinstance(x, dict) and str(x.get("id")) == str(d.get("id"))
        ),
        {},
    )
    quando = str(raw.get("quando") or "")[:19]
    aperta = str(ses.get("aperta_quando") or "")[:19]
    return bool(quando and aperta and quando < aperta)


def _domanda_a_vista(d: dict) -> dict:
    ""


    return {
        "id": d["id"],
        "testo": d["testo"],
        "risposta": d.get("risposta") or "",
        "policy": bool(d.get("policy")),
        "fonte_norma": d.get("fonte_norma") or "",
    }


def _tappa2(v: dict, c: dict) -> dict:
    ""

    fase = c["fase"]
    L, pc, ses, pi, ag = c["L"], c["pc"], c["ses"], c["pi"], c["ag"]
    scope = _scope_di(v, fase)
    passo = _passo_di(v, fase, scope, L)
    aperte = c["aperte"]
    if c["aperta"]:


        aperte = [d for d in aperte if not _in_mano_all_agente(d, v, ses)]


    fin_qui = PASSI6[: PASSI6.index(passo) + 1] if passo in PASSI6 else ()
    aperte_passo = [d for d in aperte if d.get("passo") in fin_qui]
    if passo == "scope":
        aperte_passo = [d for d in aperte if d.get("passo") == "scope"]

    di_scope = [d for d in aperte if d.get("passo") == "scope"]

    domanda = _domanda_a_vista

    altre = di_scope[DOMANDE_A_VISTA:]
    strada = str(scope.get("strada") or "")
    versione = int(scope.get("versione") or 0)


    parole = [
        _nfc(str(x.get("testo") if isinstance(x, dict) else x))
        for x in scope.get("parole_di_owner_accanto") or []
        if (x.get("testo") if isinstance(x, dict) else x)
    ]
    if not parole:
        parole = [p["testo"] for p in _parole_di_owner(v)]
        if pc.get("correzione") and pc["correzione"] not in parole:
            parole.append(str(pc["correzione"]))


    le_tue_parole = _le_tue_parole(v, scope)
    gia = {le_tue_parole["prima"], *le_tue_parole["altre"]} if le_tue_parole else set()
    uscita_v0 = versione == 0 and strada in ("riferimento", "non_serve")
    accanto = [x for x in parole if x not in gia] if uscita_v0 else []
    info = [
        str(x.get("testo") if isinstance(x, dict) else x)
        for x in scope.get("info_chiave") or []
        if (x.get("testo") if isinstance(x, dict) else x)
    ]

    prima = []
    for x in scope.get("storia") or []:
        t = str(
            (x.get("cosa_intendi") or x.get("testo") or "") if isinstance(x, dict) else ""
        ).strip()
        if t and t != str(scope.get("cosa_intendi") or "").strip() and t not in prima:
            prima.append(t)
    dove = _dove_pulito(scope.get("dove_arrivare"))
    if str(scope.get("dove_arrivare") or "") == str(pc.get("dove_arrivare") or ""):
        dove = c["perche"].get("dove_arrivare") or dove
    S = _smista_regole()
    scope_out = {
        "versione": versione,
        "da": str(scope.get("da") or ""),
        "cosa_intendi": str(scope.get("cosa_intendi") or ""),
        "verbo_di_owner": str(scope.get("verbo_di_owner") or ""),
        "strada": strada,
        "strada_frase": _strada_frase(scope),
        "tipo": str(scope.get("tipo") or ""),
        "progetto": str(scope.get("progetto") or ""),
        "area": str(scope.get("area") or ""),
        "chi": str(scope.get("chi") or ""),
        "delicato": bool(scope.get("delicato")),
        "dove_arrivare": dove,
        "dove_va_frase": _dove_va_frase(scope) if strada else "",
        "info_chiave": info,

        "su_cosa_poggia_frase": _poggia_semplice(c["perche"].get("su_cosa_poggia_frase") or ""),
        "prima_dicevo": prima,
        "confermato": bool(scope.get("confermato")),


        "aspetta_task": bool(scope.get("aspetta_task")),
        "strada_da": str(scope.get("strada_da") or ""),
        "verbo": {
            "strade": [str(x) for x in _dict(scope.get("verbo")).get("strade") or []],
            "parole": [str(x) for x in _dict(scope.get("verbo")).get("parole") or []],
            "strada": str(_dict(scope.get("verbo")).get("strada") or ""),
        },
        "confermato_frase": _frase(
            TESTI["scope_confermato"], quando=_q(scope.get("confermato_quando"))
        )
        if scope.get("confermato")
        else "",
        "domande": [domanda(d) for d in di_scope[:DOMANDE_A_VISTA]],
        "altre_domande": [domanda(d) for d in altre],
        "altre_domande_frase": (
            TESTI["scope_altra_domanda"]
            if len(altre) == 1
            else TESTI["scope_altre_domande"].format(n=len(altre))
        )
        if altre
        else "",


        "le_tue_parole": le_tue_parole,

        "raddrizza_riga": f"{RIGHE['raddrizza']} --versione {versione}",


        "parole_di_owner_accanto": accanto,

        "scelte": _scelte(),
    }

    task_manca = _task_manca(passo, scope, c)
    c = {**c, "task_manca": task_manca}
    uscita = None if task_manca else _uscita(passo, scope, c, v)


    rifai = (
        _gesto_rifalla(versione)
        if passo not in ("", "a_parte", "capire") and _rifalla_si(v, scope)
        else None
    )
    if rifai and uscita and _dict(uscita.get("task")).get("dove") == "attivita":
        uscita["task"]["rifai"] = rifai
    cambio = _cambio_scope(passo, scope, c, v)
    adesso, attese = _adesso_di(passo, scope, scope_out, c, v, aperte_passo, uscita, cambio)
    if rifai:


        adesso["secondari"].append(_secondario("rifalla", TESTI["rifalla"], TESTI["aiuto_rifalla"]))


    scope_out["proposta_in_attesa"] = _proposta_in_attesa(scope)
    if scope_out["proposta_in_attesa"] and c["aperta"]:

        pr = scope_out["proposta_in_attesa"]
        pr["frase"] = f"{pr['frase']}. {TESTI['proposta_coda_agente']}"
    elif scope_out["proposta_in_attesa"] and passo not in ("capire", "scope", "a_parte", ""):
        adesso["secondari"].append(
            _secondario("prendi_proposta", TESTI["prendi_proposta"], TESTI["aiuto_prendi_proposta"])
        )


    for g in [adesso["pulsante"], *adesso["secondari"]]:
        if g and g.get("verbo") in _GESTI_CON_VERSIONE and g.get("riga"):
            g["riga"] = f"{g['riga']} --versione {versione}"


        rct = str((g or {}).get("riga_con_testo") or "")
        if rct and rct.split(" ")[0] in _VERBI_CON_VERSIONE and "--versione" not in rct:
            g["riga_con_testo"] = f"{rct} --versione {versione}"
    percorso6 = _percorso6(
        "cosa_da_fare" if task_manca else passo, scope, c, v, adesso, cambio, parole
    )
    fatto = [
        {
            "passo": p["id"],
            "nome": p["nome"],
            "quando_frase": p["quando"],
            "riassunto": p["riassunto"],
            "rivedi": p["rivedi"],


            "raddrizza": p["id"] == "scope"
            and (passo not in ("capire", "scope") or task_manca)
            and not c["aperta"],



            **(
                {"riapri": _gesto_riapri(versione)}
                if p["id"] == "scope"
                and scope.get("confermato")
                and passo in PASSI6[2:]
                and not task_manca
                and not c["aperta"]
                else {}
            ),
        }
        for p in percorso6
        if p["stato"] in ("fatto", "rifare")
    ]
    dopo = [
        {"passo": p["id"], "nome": p["nome"], "frase": p["riassunto"]}
        for p in percorso6
        if p["stato"] == "dopo"
    ]



    qs = L.get("quando_owner")
    ultimo = ""
    if isinstance(qs, dict):
        attese = [str(qs.get("aspetta_quando") or "")] if adesso["chi"] == "te" else []
        attese = [a for a in attese if a]
        ultimo = str(qs.get("ultimo_gesto") or "")

        attese = _attese_con_la_proposta_di_prima(attese, qs, passo, scope, v)
    elif passo == "scope":

        q_prop, q_prima = str(scope.get("quando") or ""), _quando_della_proposta(scope)
        if q_prop and q_prima and q_prima < q_prop:
            attese = [q_prima if a == q_prop else a for a in attese]
    nuovo, nuovo_quando = _nuovo(attese, ultimo[:19])
    return {
        "passo": passo,
        "percorso6": percorso6,
        "scope": scope_out,
        "adesso": adesso,
        "fatto": fatto,
        "dopo": dopo,
        "cambio_scope": cambio,
        "uscita": uscita,

        "task_manca": task_manca,
        "_nuovo": nuovo and adesso["chi"] == "te",
        "_nuovo_quando": nuovo_quando,


        "_rifai": None if uscita and _dict(uscita.get("task")).get("rifai") else rifai,
    }


def _scelte() -> dict:
    ""

    return _scelte_per(_chiave_owner_da_fare())


def _gesto_riapri(versione: int) -> dict:
    ""

    g = _secondario("riapri", TESTI["riapri"], TESTI["aiuto_riapri"])
    g["riga"] = f"{g['riga']} --versione {versione}"
    return g


def _gesto_rifalla(versione: int) -> dict:
    ""

    g = _secondario("rifalla", TESTI["rifalla"], TESTI["aiuto_rifalla"])
    g["riga"] = f"{g['riga']} --versione {versione}"
    return g


@functools.lru_cache(maxsize=2)
def _scelte_per(chiave_owner: str) -> dict:
    S = _smista_regole()
    return {
        "strade": [{"id": s, "parola": TESTI[f"strada_{s}"]} for s in STRADE],
        "tipi": [{"id": t, "parola": _maiuscola(TESTI[f"tipo_{t}"])} for t in TIPI_SCOPE],
        "progetti": [{"id": p, "parola": _parola_progetto(p)} for p in PROGETTI_SCOPE],
        "aree": [{"id": a, "parola": AREE_PAROLE.get(a, a)} for a in S.ATTIVITA],
        "chi": [
            {"id": "owner", "parola": TESTI[chiave_owner]},
            {"id": "team", "parola": TESTI["strada_cosa_da_fare_team"]},
        ],
    }



_GESTI_CON_VERSIONE = frozenset(

    (
        "giusto",
        "raddrizza",
        "prendi_proposta",
        "tieni",
        "rifai",
        "letto_studio",
        "riapri",
        "crea_task",
        "rifalla",
    )
)

_VERBI_CON_VERSIONE = frozenset(RIGHE[g].split(" ")[0] for g in _GESTI_CON_VERSIONE)


def _le_tue_parole(v: dict, scope: dict) -> dict | None:
    ""


    voci = []
    da_scope = [x for x in scope.get("parole_di_owner_accanto") or [] if isinstance(x, dict)]
    if da_scope:

        for x in da_scope:
            if str(x.get("domanda") or "") or not str(x.get("testo") or "").strip():
                continue
            voci.append((str(x.get("quando") or ""), _nfc(str(x["testo"]).strip())))
    else:
        cattura = _dict(v.get("cattura"))
        if str(cattura.get("testo_di_owner") or "").strip():
            voci.append((str(cattura.get("quando") or ""), str(cattura["testo_di_owner"]).strip()))
        for p in v.get("pareri") or []:
            if not isinstance(p, dict) or p.get("tolto") or p.get("sostituito") or p.get("domanda"):
                continue
            t = str(p.get("testo") or "").strip() or (
                str(p.get("trascrizione") or "").strip()
                if p.get("audio_stato") == "trascritto"
                else ""
            )
            if t:
                voci.append((str(p.get("quando") or ""), t))
    visti, testi = set(), []
    for _q_, t in sorted(voci, key=lambda x: x[0], reverse=True):
        if t not in visti:
            visti.add(t)
            testi.append(t)
    if not testi:
        return None


    audio_voci = []
    for p in sorted(
        (x for x in v.get("pareri") or [] if isinstance(x, dict)),
        key=lambda x: str(x.get("quando") or ""),
        reverse=True,
    ):
        if not p.get("audio") or p.get("tolto") or p.get("sostituito") or p.get("domanda"):
            continue
        file = _file(p.get("audio")) or ""
        trascrizione = (
            _nfc(str(p.get("trascrizione") or "").strip())
            if p.get("audio_stato") == "trascritto"
            else ""
        )
        if not (file or trascrizione):
            continue
        audio_voci.append(
            {
                "file": file,
                "quando": _quando(p.get("quando")),
                "trascrizione": trascrizione,
                "frase": _frase_audio(p) if _audio_non_parola(p) else "",
            }
        )
    altre = testi[1:]
    return {
        "prima": testi[0],
        "altre": altre,
        "audio": bool(audio_voci),
        "audio_voci": audio_voci,
        "tutte_parola": TESTI["tutte_le_tue_parole"] if (altre or audio_voci) else "",
    }


def _proposta_in_attesa(scope: dict) -> dict | None:
    ""

    pd = scope.get("proposta_dopo")
    if not isinstance(pd, dict) or not scope.get("confermato"):
        return None

    cambi = []
    if pd.get("strada") in STRADE:
        nuova = {
            "strada": pd["strada"],
            "chi": pd.get("chi") or scope.get("chi"),
            "tipo": pd.get("tipo", scope.get("tipo")),
        }
        frase_strada = _strada_frase(nuova)
        di_ora = str(scope.get("strada") or "")
        if di_ora in STRADE and di_ora != pd["strada"]:
            base = _strada_frase({**nuova, "tipo": ""})
            resto = frase_strada[len(base) :] if frase_strada.startswith(base) else ""
            frase_strada = (
                TESTI["proposta_invece_di"].format(strada=base, v=TESTI[f"invece_{di_ora}"]) + resto
            )
        cambi.append(frase_strada)
    elif pd.get("tipo") in TIPI_SCOPE:
        cambi.append(_strada_frase({**scope, "tipo": pd["tipo"]}))
    if pd.get("progetto"):
        cambi.append(TESTI["proposta_progetto"].format(v=_parola_progetto(str(pd["progetto"]))))
    if pd.get("area"):
        a = str(pd["area"])
        cambi.append(TESTI["proposta_area"].format(v=AREE_PAROLE.get(a, a)))
    if pd.get("chi") in ("owner", "team") and "strada" not in pd:
        cambi.append(TESTI[f"proposta_chi_{pd['chi']}"])
    if "delicato" in pd:
        cambi.append(TESTI["proposta_delicato" if pd.get("delicato") else "proposta_non_delicato"])
    cambi = [x for x in cambi if x]
    if not cambi:
        return None
    quando = _q(pd.get("quando"))
    testa = (
        _maiuscola(TESTI["proposta_in_attesa"].format(quando=quando))
        if quando
        else TESTI["proposta_in_attesa_senza_data"]
    )
    frase = f"{testa} {_maiuscola(', '.join(cambi))}"
    return {
        "frase": frase,
        "quando": quando,
        "campi": [k for k in ("strada", "tipo", "progetto", "area", "chi", "delicato") if k in pd],
    }




_POGGIA = (
    (r"(?:il|un) giro di comprensione", "la comprensione"),
    (r"nel giro di comprensione", "nella comprensione"),
    (r"dal giro di comprensione", "dalla comprensione"),
    (r"del giro di comprensione", "della comprensione"),
    (r"giri? di comprensione", "comprensione"),
    (r"il dossier(?: rifatto)?", "quello che ho capito"),
    (r"del dossier(?: rifatto)?", "di quello che ho capito"),
    (r"dal dossier(?: rifatto)?", "da quello che ho capito"),
    (r"nel dossier(?: rifatto)?", "in quello che ho capito"),
    (r"(?:un|i) dossier(?: rifatto)?", "quello che ho capito"),
    (r"dossier(?: rifatto)?", "quello che ho capito"),
)
_RE_POGGIA = _una_regex(_POGGIA)


def _poggia_semplice(testo: str) -> str:
    pezzi = re.split(r"(«[^»]*»)", str(testo or ""))
    return "".join(
        p if p.startswith("«") else _RE_POGGIA.sub(lambda m: _POGGIA[int(m.lastgroup[1:])][1], p)
        for p in pezzi
    )


def _nome_passo(p: str) -> str:
    return TESTI.get(f"passo_{p}", "")


def _task_manca(passo: str, scope: dict, c: dict) -> bool:
    ""



    L = c["L"]
    for dato in (scope.get("aspetta_task"), L.get("task_manca"), scope.get("task_manca")):
        if isinstance(dato, bool):
            return dato
    if scope.get("strada") != "cosa_da_fare" or not scope.get("confermato"):
        return False
    if scope.get("delicato") or passo not in ("cosa_da_fare", "scope"):
        return False
    conf = _dict(_dict(L.get("smistamento")).get("confermato"))
    return not (_dict(scope.get("task")).get("id") or conf.get("task"))


def _gesto_crea_task(scope: dict, v: dict) -> dict:
    ""
    if scope.get("chi") == "owner":
        return _secondario(
            "crea_task", TESTI["crea_task_attivita"], TESTI["aiuto_crea_task_attivita"]
        )
    lista = " / ".join(_lista_team(scope, v).get("percorso") or [])
    return _secondario(
        "crea_task",
        TESTI["crea_task_clickup"],
        _frase(TESTI["aiuto_crea_task_clickup"], lista=lista),
    )


def _uscita(passo: str, scope: dict, c: dict, v: dict) -> dict | None:
    ""
    if passo not in USCITE:
        return None
    L = c["L"]
    conf = _dict(_dict(L.get("smistamento")).get("confermato"))
    quando = _q(
        scope.get("confermato_quando") or conf.get("quando") or c["pc"].get("confermato_quando")
    )
    task = None
    if passo == "riferimento":
        frase = _frase(TESTI["uscita_riferimento"], quando=quando)
    elif passo == "non_serve":
        frase = _frase(TESTI["uscita_non_serve"], quando=quando)
    elif passo == "letto":
        frase = _frase(
            TESTI["uscita_letto"], quando=_q(scope.get("letto_quando") or c["letto_quando"])
        )
    else:

        t = _dict(scope.get("task"))
        dove = str(
            t.get("dove")

            or (
                "attivita"
                if str(conf.get("lista") or "").startswith("Attività")
                or str(conf.get("task") or "").startswith("attivita:")
                else ""
            )
            or ("clickup" if conf.get("task") else "")
        )
        ident = str(t.get("id") or conf.get("task") or "")
        if ident.startswith("attivita:"):
            ident = ident[len("attivita:") :]
        if dove == "attivita":


            att = _in_attivita(v)
            stato = att.get("stato", "")
            if stato == "eliminata":
                frase = TESTI["uscita_attivita_eliminata"]
            elif stato == "chiusa":
                frase = _frase(TESTI["uscita_attivita_chiusa"], quando=quando)
            else:
                frase = _frase(TESTI["uscita_attivita"], quando=quando)
            task = {
                "dove_frase": TESTI[
                    "uscita_task_attivita_eliminata"
                    if stato == "eliminata"
                    else "uscita_task_attivita"
                ],
                "id": att.get("id") or ident,
                "dove": "attivita",
                "stato": stato,
                "stato_nome": att.get("stato_nome", ""),
            }
        elif not ident and scope.get("delicato"):

            frase = _frase(TESTI["uscita_delicato"], quando=quando)
        else:
            frase = _frase(TESTI["uscita_clickup" if ident else "uscita_senza_task"], quando=quando)
            lista = str(conf.get("lista") or t.get("lista") or "")
            task = (
                {
                    "dove_frase": _frase(TESTI["uscita_task_clickup"], lista=lista)
                    if lista
                    else "ClickUp",
                    "id": ident,

                    "dove": "clickup",
                    "stato": "",
                    "stato_nome": "",
                }
                if ident
                else None
            )
    out = {
        "tipo": passo,
        "frase": frase,
        "riapri_parola": TESTI["riapri"],
        "riapri_aiuto": TESTI["aiuto_riapri"],
    }
    if task:
        out["task"] = task
    elif passo == "cosa_da_fare" and not scope.get("delicato") and _task_accese(scope):


        out["crea_task"] = _gesto_crea_task(scope, v)
    return out



_DOPO_SCOPE = ("contesto", "ricerca", "implementazione", "test")


def _fatti_dopo_scope(c: dict) -> dict:
    ""

    pi, ag, ses = c["pi"], c["ag"], c["ses"]
    scheda_d = _dict(c["L"].get("scheda"))
    out = {}

    if (pi.get("passi") or pi.get("punto_di_arrivo")) and not pi.get("rifare"):
        out["contesto"] = ("fatto", str(pi.get("quando") or ""), pi.get("con_scope_versione"))
    elif c["aperta"]:
        out["contesto"] = (
            "in_corso",
            str(ses.get("aperta_quando") or ""),
            ses.get("con_scope_versione"),
        )
    if c["scheda"] and not scheda_d.get("rifare"):
        out["ricerca"] = (
            "fatto",
            str(scheda_d.get("quando") or ""),
            scheda_d.get("con_scope_versione"),
        )
    elif "contesto" in out and out["contesto"][0] == "fatto" and c["aperta"]:
        out["ricerca"] = (
            "in_corso",
            str(ses.get("aperta_quando") or ""),
            ses.get("con_scope_versione"),
        )
    if c["ritorno"]:
        out["implementazione"] = (
            "fatto",
            str(ag.get("ritorno_quando") or ""),
            ag.get("con_scope_versione"),
        )
    elif ag.get("avviato_quando") or ag.get("pannello"):
        out["implementazione"] = (
            "in_corso",
            str(ag.get("avviato_quando") or ""),
            ag.get("con_scope_versione"),
        )
    if ag.get("ritorno_letto"):
        out["test"] = ("fatto", str(c["letto_quando"] or ""), ag.get("con_scope_versione"))
    return out


def _cambio_chi(cambio: dict) -> str:
    ""




    da = str((cambio or {}).get("da") or "")
    if not da or da == "owner":
        return ""
    return "_riletto" if (cambio or {}).get("parole_dopo") else "_riscritto"


def _cambio_scope(passo: str, scope: dict, c: dict, v: dict) -> dict | None:
    ""


    if not scope.get("confermato") or passo in USCITE or passo in ("capire", "scope", "a_parte"):
        return None
    fatti = _fatti_dopo_scope(c)

    dall_archivio = c["L"].get("scope_cambio") if "scope_cambio" in c["L"] else False
    if isinstance(dall_archivio, dict):
        for x in dall_archivio.get("passi") or []:
            if isinstance(x, dict) and x.get("passo") in _DOPO_SCOPE:
                fatti[x["passo"]] = (
                    "fatto",
                    str(x.get("quando") or ""),
                    x.get("con_scope_versione"),
                )
    if not fatti:
        return None
    versione = int(scope.get("versione") or 0)
    rifa, da_decidere = [], False
    if isinstance(dall_archivio, dict) and dall_archivio.get("passi"):
        da_decidere = True
    for p in _DOPO_SCOPE:
        if p not in fatti:
            continue
        stato, quando, con = fatti[p]
        chiave = "cambio_rifa_in_corso" if stato == "in_corso" else "cambio_rifa"
        rifa.append(
            {
                "passo": p,
                "nome": _nome_passo(p),
                "quando_frase": _q(quando),
                "frase": _frase(TESTI[chiave], quando=_q(quando)),
                "_anteprima": _frase(TESTI[chiave + "_anteprima"], quando=_q(quando)),
            }
        )
        if dall_archivio is False:

            try:
                if con is not None and int(con) < versione:
                    da_decidere = True
            except (TypeError, ValueError):
                pass

    for r in rifa:
        anteprima = r.pop("_anteprima")
        if not da_decidere:
            r["frase"] = anteprima
    riga = _riga_scope(scope)



    con_agente = bool(da_decidere and c["aperta"])


    con_lavoro = bool(da_decidere and not con_agente and (c.get("azioni") or {}).get("vai_lavoro"))
    if con_agente or con_lavoro:
        for r in rifa:
            r["frase"] = ""
    return {

        "adesso_e": riga,
        "rifa": rifa,
        "resta_frase": TESTI["cambio_resta"],
        "pulsante_rifai": "" if con_agente or con_lavoro else TESTI["rifai"],
        "pulsante_tieni": "" if con_agente else TESTI["tieni"],
        "aiuto_rifai": "" if con_agente or con_lavoro else TESTI["aiuto_rifai"],
        "aiuto_tieni": "" if con_agente else TESTI["aiuto_tieni"],
        "da_decidere": da_decidere,


        "da": str(dall_archivio.get("da") or "") if isinstance(dall_archivio, dict) else "",
        "parole_dopo": str(dall_archivio.get("parole_dopo") or "")
        if isinstance(dall_archivio, dict)
        else "",

        **({"con_agente": True} if con_agente else {}),

        **({"con_lavoro": True} if con_lavoro else {}),
    }


def _ti_aspetta(out: dict, aspetta, verbo: str, attese: list) -> bool:
    ""


    a = _dict(aspetta)
    if not a.get("si"):
        return False
    quando = str(a.get("quando") or a.get("letto_quando") or "")
    cosa = str(a.get("cosa") or "").strip().rstrip(".")
    frase = _frase(
        TESTI["adesso_ti_aspetta_cosa" if cosa else "adesso_ti_aspetta"],
        quando=_q(quando),
        cosa=cosa,
    )
    if verbo == "vai":


        frase = f"{frase.rstrip('.')}. {TESTI['adesso_terminale_scope_li']}"
    out.update(
        chi="te",
        salute="accento",
        frase=frase,
        pulsante=_pulsante(verbo, TESTI["guarda_terminale"], TESTI["aiuto_guarda_terminale"]),
        secondari=[],
        campo=None,
        domande=[],
        altre_domande=[],
        altre_domande_frase="",
    )
    attese.append(quando)
    return True


def _adesso_di(
    passo: str,
    scope: dict,
    scope_out: dict,
    c: dict,
    v: dict,
    aperte_passo: list,
    uscita: dict | None,
    cambio: dict | None,
) -> tuple[dict, list[str]]:
    ""

    fase, ses, ag, pc = c["fase"], c["ses"], c["ag"], c["pc"]
    azioni, rilettura, attesa = c["azioni"], c["rilettura"], c["attesa"]
    out = {
        "passo": passo,
        "titolo": _nome_passo(passo)
        or TESTI.get(f"strada_{passo}")
        or TESTI.get(f"titolo_{passo}", ""),
        "chi": "nessuno",
        "frase": "",
        "salute": "neutra",
        "pulsante": None,
        "secondari": [],
        "campo": None,
        "poi": "",
        "avanzamento": "",
        "domande": [],

        "altre_domande": [],
        "altre_domande_frase": "",
    }
    attese: list[str] = []
    campo = {"segnaposto": TESTI["campo_scope"], "audio": True}
    campo_risposta = {"segnaposto": TESTI["risposta_segnaposto"], "audio": True}
    studio = scope.get("strada") == "studio" and bool(scope.get("confermato"))

    def t(chiave):
        ""
        return TESTI.get(f"{chiave}_studio", TESTI[chiave]) if studio else TESTI[chiave]

    def frase_domande():
        ""
        n = min(len(aperte_passo), DOMANDE_A_VISTA)
        return TESTI["adesso_domanda"] if n == 1 else TESTI["adesso_domande"].format(n=n)

    def con_campo_risposta(pulsante):
        ""

        if pulsante and pulsante.get("verbo") != "rispondi":
            pulsante.update(
                parola_con_testo=TESTI["manda"],
                riga_con_testo=RIGHE["rispondi"],

                aiuto_con_testo=TESTI["aiuto_manda_agente" if c["aperta"] else "aiuto_manda"],
            )
        return pulsante

    def domande_qui():
        def una(d):
            return {
                "id": d["id"],
                "testo": d["testo"],
                "risposta": d.get("risposta") or "",
                "policy": bool(d.get("policy")),
                "fonte_norma": d.get("fonte_norma") or "",
            }

        out["domande"] = [una(d) for d in aperte_passo[:DOMANDE_A_VISTA]]
        altre = aperte_passo[DOMANDE_A_VISTA:]
        out["altre_domande"] = [una(d) for d in altre]
        out["altre_domande_frase"] = (
            (
                TESTI["scope_altra_domanda"]
                if len(altre) == 1
                else TESTI["scope_altre_domande"].format(n=len(altre))
            )
            if altre
            else ""
        )
        if out["domande"]:
            out["campo"] = campo_risposta
            con_campo_risposta(out["pulsante"])
        for d in aperte_passo:
            raw = next(
                (
                    x
                    for x in v.get("domande") or []
                    if isinstance(x, dict) and str(x.get("id")) == d["id"]
                ),
                {},
            )
            attese.append(str(raw.get("quando") or ""))

    if passo in ("", "a_parte"):
        return out, attese
    if c.get("task_manca"):


        quando = _q(scope.get("confermato_quando"))
        out["titolo"] = TESTI["strada_cosa_da_fare"]
        if _task_accese(scope):
            crea = _gesto_crea_task(scope, v)
            out.update(
                chi="te",
                salute="accento",
                frase=_frase(TESTI["adesso_task_manca_accesa"], quando=quando),
                pulsante=_pulsante(crea["verbo"], crea["parola"], crea["aiuto"]),
                poi=TESTI["poi_task_manca"],
            )
            attese.append(str(scope.get("confermato_quando") or ""))
        else:

            chiave = "adesso_task_manca_team" if scope.get("chi") != "owner" else "adesso_task_manca"
            out.update(frase=_frase(TESTI[chiave], quando=quando))
        return out, attese
    if uscita:
        out.update(
            frase=uscita["frase"],
            secondari=[_secondario("riapri", TESTI["riapri"], TESTI["aiuto_riapri"])],
        )
        if c["aperta"]:


            out["poi"] = TESTI["uscita_agente_aperto"]
            out["secondari"].append(
                _secondario("vai", TESTI["guarda_terminale"], TESTI["aiuto_guarda_terminale"])
            )
        if uscita.get("crea_task"):


            crea = uscita["crea_task"]
            out.update(
                chi="te",
                salute="accento",
                pulsante=_pulsante(crea["verbo"], crea["parola"], crea["aiuto"]),
            )
        return out, attese
    if cambio and cambio.get("con_agente"):



        nel_terminale = "terminale" in str(scope.get("da_dettaglio") or "")
        if not _cambio_chi(cambio) and not nel_terminale:
            chiave = "adesso_cambio_agente"
        elif str(cambio.get("da") or "") == "owner" and nel_terminale:
            chiave = "adesso_cambio_agente_terminale"
        else:
            chiave = "adesso_cambio_agente_altro"
        out.update(
            chi="te",
            frase=_frase(TESTI[chiave], quando=_q(scope.get("quando"))),
            salute="accento",
            pulsante=_pulsante("vai", TESTI["guarda_terminale"], TESTI["aiuto_guarda_terminale"]),
            secondari=[],
        )
        attese.append(str(scope.get("quando") or ""))
        return out, attese
    if cambio and cambio.get("con_lavoro"):


        chi_ = _cambio_chi(cambio)
        out.update(
            chi="te",
            frase=_frase(
                TESTI["adesso_cambio_lavoro" + chi_],
                quando=_q(cambio.get("parole_dopo") if chi_ == "_riletto" else scope.get("quando")),
            ),
            salute="accento",
            pulsante=_pulsante("vai_lavoro", TESTI["guarda_terminale"], TESTI["aiuto_guarda_terminale"]),
            secondari=[_secondario("tieni", TESTI["tieni"], TESTI["aiuto_tieni"])],
        )
        attese.append(str(scope.get("quando") or ""))
        return out, attese
    if cambio and cambio.get("da_decidere"):
        out.update(
            chi="te",
            frase=_frase(
                TESTI["adesso_cambio" + _cambio_chi(cambio)], quando=_q(cambio.get("parole_dopo"))
            ),
            salute="accento",
            pulsante=_pulsante("rifai", TESTI["rifai"], TESTI["aiuto_rifai"]),
            secondari=[_secondario("tieni", TESTI["tieni"], TESTI["aiuto_tieni"])],
        )
        attese.append(str(scope.get("quando") or ""))
        return out, attese
    if rilettura.get("aperta"):
        out.update(
            chi="sistema",
            frase=_frase(
                TESTI["adesso_rileggo_in_fila" if rilettura.get("in_fila") else "adesso_rileggo"],
                quando=_q(rilettura.get("risposta_quando")),
            ),
        )
        return out, attese
    if c["in_viaggio"] and passo in ("scope", "contesto", "ricerca"):
        out.update(chi="sistema", frase=TESTI["adesso_trascrivo"])
        return out, attese
    if passo == "capire":
        out.update(chi="sistema", frase=c["stato_riquadro"], poi=TESTI["poi_capire"])
        if azioni.get("capisci"):
            minore = _secondario("capisci", TESTI["capisci_minore"], TESTI["aiuto_fallo_adesso"])
            if attesa == "aspetta_si":

                out.update(
                    chi="te",
                    salute="accento",
                    pulsante=_pulsante(
                        "capisci", TESTI["testa_pulsante_uno"], TESTI["testa_pulsante_aiuto_uno"]
                    ),
                )
                attese.append(str(_dict(v.get("cattura")).get("quando") or ""))
            elif attesa in ("fermo", "spento"):
                out.update(
                    chi="te",
                    salute="attenzione" if attesa == "fermo" else "accento",
                    pulsante=_pulsante(
                        "capisci", TESTI["capisci_minore"], TESTI["aiuto_fallo_adesso"]
                    ),
                )
                attese.append(str(_dict(v.get("cattura")).get("quando") or ""))
            elif attesa in ("vietato", "sparito"):
                out.update(chi="nessuno", salute="attenzione", poi="")
            else:
                out["secondari"] = [minore]
        elif attesa in ("vietato", "sparito"):
            out.update(chi="nessuno", salute="attenzione", poi="")
        return out, attese
    if passo == "scope":
        if c["aperta"] and not scope.get("confermato"):



            pulsante, _poi = _giusto(scope, v)
            pulsante.update(
                parola_con_testo=pulsante["parola"],
                riga_con_testo=pulsante["riga"],
                aiuto_con_testo=pulsante["aiuto"],
            )
            if _giusto_resta_nel_percorso(scope):
                pulsante.update(
                    aiuto=TESTI["aiuto_giusto_agente"], aiuto_con_testo=TESTI["aiuto_giusto_agente"]
                )
            out.update(
                chi="te",
                salute="accento",

                frase=_frase(
                    TESTI[
                        "adesso_scope_agente_mai"
                        if not int(scope.get("versione") or 0)
                        else "adesso_scope_agente"
                    ],
                    quando=_q(scope.get("quando")),
                ),
                pulsante=pulsante,
                secondari=[_secondario("vai", TESTI["guarda_terminale"], TESTI["aiuto_guarda_terminale"])],
                poi="",
            )
            attese.append(str(scope.get("quando") or ""))
            return out, attese
        if c["aperta"]:
            out.update(
                chi="sessione",
                frase=_frase(TESTI["adesso_terminale_lavora"], quando=_q(ses.get("aperta_quando")))
                + ". "
                + TESTI["adesso_terminale_scope_li"],
                secondari=[_secondario("vai", TESTI["guarda_terminale"], TESTI["aiuto_guarda_terminale"])],
            )
            return out, attese
        pulsante, poi = _giusto(scope, v)
        accanto = bool(
            scope_out.get("le_tue_parole")
            and scope_out["versione"] == 0
            and scope_out["strada"] in ("riferimento", "non_serve")
        )
        uscita_dopo = scope_out["strada"] in STRADE_USCITA


        esce = _esce_col_giusto(scope)
        if scope_out["versione"] == 0 and pc.get("confermato") and pc.get("confermato_quando"):

            frase = _frase(
                TESTI["adesso_scope_perche_confermato"], quando=_q(pc.get("confermato_quando"))
            )
        elif accanto:
            frase = TESTI["adesso_scope_accanto"]
        elif esce:
            frase = TESTI["adesso_scope_uscita"]
        elif uscita_dopo:
            frase = TESTI["adesso_scope_resta"]
        else:
            frase = TESTI["adesso_scope"]
        if azioni.get("vai_lavoro") and frase == TESTI["adesso_scope"]:


            frase = TESTI["adesso_scope_lavoro"]
            poi = ""
            if pulsante and _giusto_resta_nel_percorso(scope):
                pulsante.update(
                    aiuto=TESTI["aiuto_giusto_lavoro"], aiuto_con_testo=TESTI["aiuto_giusto_lavoro"]
                )
        secondari = [_secondario("raddrizza", TESTI["raddrizza"], TESTI["aiuto_raddrizza"])]
        domande_scope = scope_out.get("domande") or []

        campo = {
            **campo,
            "segnaposto": TESTI["campo_scope" if domande_scope else "campo_scope_senza_domande"],
        }
        if uscita_dopo and pulsante:



            pulsante.update(
                parola_con_testo=TESTI["manda"],
                riga_con_testo=RIGHE["raddrizza"],
                aiuto_con_testo=TESTI[
                    "manda_e_rileggi_aiuto" if domande_scope else "manda_e_rileggi_parole_aiuto"
                ],
            )
        out.update(
            chi="te",
            salute="accento",
            frase=frase,
            pulsante=pulsante,
            secondari=secondari,
            campo=campo,
            poi=poi,
        )
        attese.append(str(scope.get("quando") or pc.get("quando") or ""))
        for d in aperte_passo:
            raw = next(
                (
                    x
                    for x in v.get("domande") or []
                    if isinstance(x, dict) and str(x.get("id")) == d["id"]
                ),
                {},
            )
            attese.append(str(raw.get("quando") or ""))
        return out, attese
    if passo in ("contesto", "ricerca"):
        out["poi"] = t(f"poi_{passo}")
        scheda_d = _dict(c["L"].get("scheda"))
        if studio and passo == "ricerca" and c["scheda"] and not scheda_d.get("rifare"):


            out.update(
                chi="te",
                salute="accento",
                frase=_frase(TESTI["adesso_studio_scheda"], quando=_q(scheda_d.get("quando"))),
                pulsante=_pulsante("letto_studio", TESTI["ho_letto"], TESTI["aiuto_letto_studio"]),
                secondari=[
                    _secondario("leggi_scheda", TESTI["leggi_scheda"], TESTI["aiuto_leggi_scheda"])
                ],
                poi=TESTI["poi_studio_letto"],
            )
            if c["aperta"]:

                out["frase"] = f"{out['frase']}. {TESTI['coda_scheda_agente']}"
                out["secondari"].append(
                    _secondario("vai", TESTI["guarda_terminale"], TESTI["aiuto_guarda_terminale"])
                )
            attese.append(str(scheda_d.get("quando") or ""))
            domande_qui()
            return out, attese
        if c["aperta"]:

            if _ti_aspetta(out, ses.get("aspetta"), "vai", attese):
                return out, attese
            if aperte_passo:


                n = min(len(aperte_passo), DOMANDE_A_VISTA)
                out.update(
                    chi="te",
                    salute="accento",
                    frase=_frase(
                        TESTI["adesso_agente_domanda" if n == 1 else "adesso_agente_domande"],
                        quando=_q(ses.get("aperta_quando")),
                        n=n,
                    )
                    + ". "
                    + TESTI["adesso_terminale_scope_li"],
                    pulsante=_pulsante("rispondi", TESTI["manda"], TESTI["aiuto_manda_agente"]),
                    secondari=[
                        _secondario("vai", TESTI["guarda_terminale"], TESTI["aiuto_guarda_terminale"])
                    ],
                )
                domande_qui()
                return out, attese
            out.update(
                chi="sessione",
                frase=_frase(t("adesso_terminale_lavora"), quando=_q(ses.get("aperta_quando")))
                + ". "
                + TESTI["adesso_terminale_scope_li"],
                secondari=[_secondario("vai", TESTI["guarda_terminale"], TESTI["aiuto_guarda_terminale"])],
            )
            return out, attese
        if c["chiusa_a_mano"]:

            aspettava = bool(_dict(ses.get("aspetta")).get("si"))
            out.update(
                chi="te",
                salute="attenzione",
                frase=_frase(
                    TESTI["adesso_terminale_chiuso_aspettava" if aspettava else "adesso_terminale_chiuso"],
                    quando=_q(ses.get("chiusa_quando")),
                ),
                pulsante=_pulsante(
                    "ci_lavoriamo", TESTI["riapri_agente"], TESTI["aiuto_riapri_agente"]
                ),
            )
            attese.append(str(ses.get("chiusa_quando") or ""))
            domande_qui()
            return out, attese
        if aperte_passo:
            out.update(
                chi="te",
                salute="accento",
                frase=frase_domande(),
                pulsante=_pulsante("rispondi", TESTI["manda"], TESTI["aiuto_manda"]),
                secondari=[
                    _secondario(
                        "ci_lavoriamo",
                        TESTI["apri_agente" if passo == "contesto" else "riapri_agente"],
                        TESTI[
                            "aiuto_apri_agente" if passo == "contesto" else "aiuto_riapri_agente"
                        ],
                    )
                ],
            )
            domande_qui()
            return out, attese
        if passo == "contesto":
            out.update(
                chi="te",
                salute="accento",
                frase=t("adesso_contesto"),
                pulsante=_pulsante(
                    "ci_lavoriamo", TESTI["apri_agente"], TESTI["aiuto_apri_agente"]
                ),
            )
            attese.append(str(scope.get("confermato_quando") or ""))
        else:
            out.update(
                chi="te",
                salute="accento",
                frase=t("adesso_ricerca"),
                pulsante=_pulsante(
                    "ci_lavoriamo", TESTI["riapri_agente"], TESTI["aiuto_riapri_agente"]
                ),
            )
            attese.append(str(c["pi"].get("quando") or ""))
        return out, attese
    if passo == "implementazione":
        out["poi"] = TESTI["poi_implementazione"]
        if fase == "pronta":

            codice = str(ag.get("permessi") or c["pi"].get("permessi") or "")
            aiuto = TESTI["aiuto_avvia"]
            if TESTI.get(f"permessi_{codice}"):
                aiuto = f"{aiuto} {TESTI[f'permessi_{codice}']}"
            out.update(
                chi="te",
                salute="accento",
                frase=TESTI["adesso_pronta"],
                pulsante=_pulsante("avvia", TESTI["avvia"], aiuto),
                secondari=[
                    _secondario("leggi_scheda", TESTI["leggi_scheda"], TESTI["aiuto_leggi_scheda"])
                ],
            )
            if c["aperta"]:

                out["frase"] = f"{out['frase']}. {TESTI['coda_scheda_agente']}"
                out["secondari"].append(
                    _secondario("vai", TESTI["guarda_terminale"], TESTI["aiuto_guarda_terminale"])
                )
            attese.append(str(_dict(c["L"].get("scheda")).get("quando") or ""))
            return out, attese
        if str(ag.get("stato") or "") == "chiuso":
            out.update(
                chi="te",
                salute="attenzione",
                frase=_frase(
                    TESTI[
                        "adesso_avviata_chiuso"
                        if _file(ag.get("ritorno_parziale"))
                        else "adesso_avviata_chiuso_vuoto"
                    ],
                    quando=_q(ag.get("chiuso_quando") or ag.get("avviato_quando")),
                ),
                secondari=[
                    _secondario(
                        "leggi_ritorno", TESTI["ritorno_parziale"], TESTI["aiuto_leggi_ritorno"]
                    )
                ]
                if _file(ag.get("ritorno_parziale"))
                else [],
            )
            attese.append(str(ag.get("chiuso_quando") or ag.get("avviato_quando") or ""))
            return out, attese

        if _ti_aspetta(out, ag.get("aspetta"), "vai_lavoro", attese):
            return out, attese

        lavoro = [d for d in c["aperte"] if d.get("da") == "sessione di lavoro"]
        if lavoro:
            aperte_passo[:] = lavoro
            out.update(
                chi="te",
                salute="accento",
                frase=frase_domande(),
                pulsante=_pulsante("rispondi", TESTI["manda"], TESTI["aiuto_manda"]),
                secondari=[
                    _secondario("vai_lavoro", TESTI["guarda_terminale"], TESTI["aiuto_guarda_terminale"])
                ],
            )
            domande_qui()
            return out, attese
        out.update(
            chi="sessione",
            frase=_frase(TESTI["adesso_avviata"], quando=_q(ag.get("avviato_quando"))),
            secondari=[_secondario("vai_lavoro", TESTI["guarda_terminale"], TESTI["aiuto_guarda_terminale"])],
        )
        return out, attese

    if ag.get("ritorno_letto"):
        out.update(chi="nessuno", frase=_frase(TESTI["adesso_letto"], quando=_q(c["letto_quando"])))
        return out, attese
    out.update(
        chi="te",
        salute="accento",
        frase=_frase(TESTI["adesso_arrivata"], quando=_q(ag.get("ritorno_quando"))),
        pulsante=_pulsante("letto", TESTI["ho_letto"], TESTI["aiuto_letto"]),
        secondari=[
            _secondario("leggi_ritorno", TESTI["leggi_ritorno"], TESTI["aiuto_leggi_ritorno"])
        ],
        poi=TESTI["poi_test"],
    )
    attese.append(str(ag.get("ritorno_quando") or ""))
    return out, attese


def _percorso6(
    passo: str, scope: dict, c: dict, v: dict, adesso: dict, cambio: dict | None, parole: list
) -> list[dict]:
    ""

    if passo in ("", "a_parte"):
        return []
    pc, ag = c["pc"], c["ag"]
    fatti = _fatti_dopo_scope(c)
    rifa = (
        {r["passo"] for r in (cambio or {}).get("rifa") or []}
        if (cambio or {}).get("da_decidere")
        else set()
    )
    strada = str(scope.get("strada") or "")
    studio = strada == "studio" and passo in (*PASSI_STUDIO, "letto")
    if studio:

        ids = list(PASSI_STUDIO)
    elif passo in USCITE or (strada in STRADE_USCITA and passo in ("capire", "scope")):

        ids = ["capire", "scope"]
    else:
        ids = list(PASSI6)
    k = PASSI6.index(passo) if passo in PASSI6 else len(ids)

    def testo(chiave):
        return TESTI.get(f"{chiave}_studio", TESTI[chiave]) if studio else TESTI[chiave]

    if passo == "test" and ag.get("ritorno_letto"):
        k = len(ids)
    out = []
    for j, p in enumerate(ids):
        stato = "fatto" if j < k else ("adesso" if j == k else "dopo")
        quando, riassunto, rivedi = "", "", False
        if p == "capire":
            quando = _q(pc.get("quando")) if stato == "fatto" else ""
            if stato == "fatto":
                corta = parole[0] if parole else ""
                if len(corta) > 60:
                    corta = corta[:57].rstrip() + "…"
                riassunto = (
                    _frase(TESTI["fatto_capire"], parole=corta)
                    if corta
                    else TESTI["fatto_capire_senza"]
                )
                rivedi = True
        elif p == "scope":
            if stato == "fatto":
                quando = _q(scope.get("confermato_quando") or pc.get("confermato_quando"))
                riassunto = _riga_scope(scope)
                rivedi = True
        elif stato == "fatto":
            f = fatti.get(p)
            if f and f[0] == "fatto":
                quando = _q(f[1])
                riassunto = testo(f"fatto_{p}")
                rivedi = True
            else:
                stato = "saltato"
                riassunto = TESTI["fatto_saltato"]
        if stato == "adesso":
            riassunto = adesso.get("frase") or ""
            if p == "implementazione" and ag.get("avviato_quando"):
                quando = _q(ag.get("avviato_quando"))
            elif p in ("contesto", "ricerca") and c["aperta"]:
                quando = _q(c["ses"].get("aperta_quando"))
            elif p == "test":
                quando = _q(ag.get("ritorno_quando"))
        elif stato == "dopo":
            riassunto = testo(f"dopo_{p}")
        if p in rifa and stato != "adesso":

            stato = "rifare"
        out.append(
            {
                "id": p,
                "nome": _nome_passo(p),
                "stato": stato,
                "quando": quando,
                "riassunto": riassunto,
                "rivedi": rivedi,
            }
        )
    return out


def domande_a_vista(v: dict, dove: str = "adesso") -> list[str]:
    ""



    L = _voce(v).get("lavorazione") or {}
    riquadro = L.get("scope" if dove == "scope" else "adesso") or {}
    return [
        str(d["id"])
        for d in riquadro.get("domande") or []
        if isinstance(d, dict) and str(d.get("id") or "")
    ]



EMOJI_SLACK = {
    "point_down": "👇", "point_right": "👉", "point_up": "👆", "point_left": "👈", "star": "⭐", "brain": "🧠",
    "flamingo": "🦩", "recycle": "♻️", "one": "1️⃣", "two": "2️⃣", "three": "3️⃣", "four": "4️⃣", "five": "5️⃣",
    "six": "6️⃣", "seven": "7️⃣", "eight": "8️⃣", "nine": "9️⃣", "sports_medal": "🏅", "first_place_medal": "🥇",
    "second_place_medal": "🥈", "third_place_medal": "🥉", "x": "❌", "hotsprings": "♨️", "thread": "🧵",
    "mechanical_arm": "🦾", "fire": "🔥", "rocket": "🚀", "bulb": "💡", "warning": "⚠️", "eyes": "👀",
    "white_check_mark": "✅", "heavy_check_mark": "✔️", "arrow_right": "➡️", "arrow_down": "⬇️", "tada": "🎉",
    "robot_face": "🤖", "sparkles": "✨", "chart_with_upwards_trend": "📈", "moneybag": "💰", "100": "💯",
}

PAESI_SLACK = {"us", "gb", "fr", "es", "de", "it", "jp", "kr", "cn", "ru", "eu"}
_CODICE_EMOJI = re.compile(r"(?<![\w:/]):([a-z0-9][a-z0-9_+\-]*):(?![\w/])")


def _bandiera(paese: str) -> str:
    return "".join(chr(0x1F1E6 + ord(c) - ord("a")) for c in paese)


def _emoji(testo: str, togli: bool = True) -> str:
    ""


    def uno(m):
        nome = m.group(1)
        if nome in EMOJI_SLACK:
            return EMOJI_SLACK[nome]
        if nome.startswith("flag-") and len(nome) == 7 and nome[5:].isalpha():
            return _bandiera(nome[5:])
        if nome in PAESI_SLACK:
            return _bandiera(nome)

        return "" if togli and any(c.isalpha() for c in nome) else m.group(0)

    return re.sub(r"  +", " ", _CODICE_EMOJI.sub(uno, str(testo or ""))).strip()


def _anteprima(cattura: dict) -> tuple[str, str]:
    ""


    an = cattura.get("anteprima") if isinstance(cattura, dict) else None
    if not isinstance(an, dict):
        return "", ""
    pezzi = [x.strip() for x in str(an.get("titolo") or "").split(" | ")]
    titolo = pezzi[0] or str(an.get("testo") or "").strip().split("\n")[0]
    autore = pezzi[1] if len(pezzi) > 1 else ""
    return _emoji(titolo), _emoji(autore)


def _voce(v: dict) -> dict:

    v = _nfc_di_owner(v)
    tipo = str(v.get("tipo") or "video")
    nome_tipo, simbolo, forma, _ = TIPI.get(tipo, TIPI["video"])
    piattaforma = str(v.get("piattaforma") or "")
    cattura = v.get("cattura") or {}
    copia = _dict(v.get("copia"))
    cv = v.get("contenuto_visto") or {}
    visto = bool(cv.get("si"))
    capito = str(v.get("parte") or "") == "capiti"
    stato = str(v.get("stato") or "")
    scheda = next((s["id"] for s in SCHEDE if stato in s["stati"]), "in_lavorazione")
    dest = v.get("destinazione") or {}
    progetto = str(dest.get("progetto") or "")
    comp = v.get("comprensione") or {}
    url = str(v.get("url") or "")
    autore = _emoji(str(v.get("autore") or "").strip())
    chi = autore or _dominio(url)
    parole = _parole_di_owner(v)


    pareri = [p for p in (v.get("pareri") or []) if isinstance(p, dict)]
    ultimo = max(pareri, key=lambda p: str(p.get("quando") or ""), default=None)
    frase_audio = _frase_audio(ultimo) if ultimo is not None and _audio_non_parola(ultimo) else ""



    if (
        frase_audio
        and parole
        and str(ultimo.get("audio_stato") or "") in ("senza parlato", "non riuscita")
    ):
        frase_audio = ""
    titolo = str(v.get("titolo") or "").strip()
    frase_owner = _emoji(parole[-1]["testo"], togli=False) if parole else ""
    titolo_sono_parole = False
    if not titolo and parole:


        titolo, frase_owner = f"«{parole[-1]['testo']}»", ""
        titolo_sono_parole = True
    elif not titolo:
        titolo = FRASI["senza_titolo"].format(
            tipo=nome_tipo, dove=PIATTAFORME.get(piattaforma, piattaforma or "web")
        )
    simili = [
        {
            "nome": str(s.get("nome") or ""),
            "url": str(s.get("url") or ""),
            "perche": str(s.get("perche") or ""),
        }
        for s in (comp.get("simili") or [])
        if isinstance(s, dict) and s.get("nome")
    ]
    destinazione = " · ".join(
        x for x in (progetto, str(dest.get("tipo") or ""), str(dest.get("obiettivo") or "")) if x
    )
    ricerca = " ".join(
        x
        for x in (
            titolo,
            chi,
            progetto,
            str(dest.get("obiettivo") or ""),
            " ".join(p["testo"] for p in parole),
            str(v.get("categoria") or ""),
        )
        if x
    )
    lav = _lavorazione(v)
    interno = lav.pop("_interno", {})

    ricerca = _ricerca_allargata(ricerca, v, lav)


    if lav.get("passo") == "cosa_da_fare" or lav.get("task_manca"):
        scheda = "attivita"


    nessuna_parola_vale = not _ha_detto_qualcosa(v)
    return {
        "id": str(v.get("id") or ""),
        "tipo": tipo,
        "nome_tipo": nome_tipo,
        "simbolo": simbolo,
        "forma": forma,
        "piattaforma": PIATTAFORME.get(piattaforma, piattaforma.capitalize()),

        "titolo": _emoji(titolo, togli=not titolo_sono_parole),
        "sotto": " · ".join(x for x in (chi, _giorno(cattura.get("quando"))) if x),
        "quando": str(cattura.get("quando") or ""),
        "progetto": progetto,


        "progetto_a_vista": _progetto_a_vista(lav, progetto),
        "scheda": scheda,
        "parte": "capiti" if capito else ("visti" if visto else "non_visti"),
        "visto": visto,
        "badge": _badge(v, visto),

        "segno": {"tipo": "", "parola": "", "aiuto": "", "salute": "neutra"},

        "contenuto_salute": interno.get("contenuto_salute", "ok" if visto else "neutra"),
        "_interno": interno,

        "titolo_sono_parole": titolo_sono_parole,
        "frase_owner": frase_owner,
        "frase_audio": frase_audio,
        "nessuna_parola_vale": nessuna_parola_vale,
        "copertina": _file(copia.get("copertina")) or _file(copia.get("copertina_originale")),
        "anteprima_titolo": _anteprima(cattura)[0],
        "anteprima_autore": _anteprima(cattura)[1],
        "video": _file(copia.get("video")),
        "trascrizione": _file(copia.get("trascrizione")),
        "url": url,
        "permalink": str(cattura.get("permalink") or ""),
        "ricerca": ricerca,


        "fase": lav["fase"],
        "tocca": lav["tocca"],


        "passo": lav["passo"],
        "passo_frase": _frase(
            TESTI["segno_passo"],
            nome=_nome_passo(lav["passo"]),
            di=TESTI["passo_di"].format(**_k_di_n(lav)),
        )
        if lav["passo"] in PASSI6 and not lav.get("task_manca")
        else "",
        "lavorazione": lav,
        "dettaglio": {
            "testa": " · ".join(
                x
                for x in (
                    chi,
                    PIATTAFORME.get(piattaforma, piattaforma.capitalize()),
                    FRASI["salvato"].format(quando=_quando(cattura.get("quando")))
                    if cattura.get("quando")
                    else "",
                )
                if x
            ),
            "destinazione": destinazione,
            "contenuto": _frase_contenuto(v, visto),
            "online": _frase_online(v),
            "parole_owner": parole,
            "nessuna_parola_vale": nessuna_parola_vale,

            "audio_owner": _audio_di_owner(v),
            "promette": str(comp.get("promette") or ""),
            "realizzato": str(comp.get("realizzato") or ""),
            "simili": simili,

            "dalla_didascalia": not visto,
            "domande": [
                str(d.get("testo") or "")
                for d in (v.get("domande_owner") or [])
                if isinstance(d, dict) and d.get("testo")
            ],



            "storia": _storia_vista(v.get("storia") or []),
        },

        **_campi_filtri_voce(v, interno, autore),
    }


def _progetto_a_vista(lav: dict, progetto: str) -> str:
    sc = lav.get("scope") or {}
    p = str(sc.get("progetto") or "") if sc.get("strada") else progetto
    return "" if not p or p == "altro" else _maiuscola(p)


def _k_di_n(lav: dict) -> dict:
    ""

    ids = [p.get("id") for p in lav.get("percorso6") or []] or list(PASSI6)
    passo = lav.get("passo")
    k = ids.index(passo) + 1 if passo in ids else PASSI6.index(passo) + 1
    return {"k": k, "n": max(len(ids), k)}


def _ordine_progetti(voci: list, campo: str = "progetto") -> list[dict]:
    conti: dict[str, int] = {}
    for v in voci:
        conti[v[campo]] = conti.get(v[campo], 0) + 1
    return [
        {"nome": p or TESTI["senza_progetto"], "id": p, "n": n}
        for p, n in sorted(conti.items(), key=lambda x: (not x[0], -x[1], x[0]))
    ]











RICERCA_IN_PIU_TETTO = 5000

_TRASCRIZIONE_LETTURA_MAX = 4 * RICERCA_IN_PIU_TETTO


def _iso_o_vuota(x) -> str:
    ""
    d = _d(str(x or ""))
    return d.isoformat(timespec="seconds") if d is not None else ""


def _testo_trascrizione(percorso) -> str:
    ""

    p = _file(percorso)
    if not p:
        return ""
    try:
        with open(p, encoding="utf-8", errors="replace") as fh:
            return unicodedata.normalize("NFC", fh.read(_TRASCRIZIONE_LETTURA_MAX))
    except OSError:
        return ""


def _ricerca_allargata(ricerca: str, v: dict, lav: dict) -> str:
    ""


    sc = _dict(lav.get("scope"))
    comp = _dict(v.get("comprensione"))
    pezzi = (
        sc.get("cosa_intendi"),
        sc.get("dove_arrivare"),
        comp.get("promette"),
        comp.get("realizzato"),
        comp.get("serve"),
        _testo_trascrizione(_dict(v.get("copia")).get("trascrizione")),
    )
    in_piu = " ".join(" ".join(str(x).split()) for x in pezzi if isinstance(x, str) and x.strip())
    if len(in_piu) > RICERCA_IN_PIU_TETTO:
        taglio = in_piu[: RICERCA_IN_PIU_TETTO + 1]
        in_piu = taglio[: taglio.rfind(" ")] if " " in taglio else taglio[:RICERCA_IN_PIU_TETTO]
    in_piu = in_piu.strip()
    return f"{ricerca} {in_piu}" if ricerca and in_piu else (ricerca or in_piu)


def _campi_filtri_voce(v: dict, interno: dict, autore: str) -> dict:
    ""



    qs = _dict(_dict(v.get("lavorazione")).get("quando_owner"))


    interno["audio_di_owner"] = any(
        isinstance(p, dict) and p.get("audio") for p in v.get("pareri") or []
    )
    return {
        "proposto_quando": _iso_o_vuota(interno.get("nuovo_quando")),
        "ultimo_gesto_quando": _iso_o_vuota(qs.get("ultimo_gesto")),
        "autore": autore,
    }





TESTI_FILTRI = {
    "filtri_titolo": "Filters",

    "filtri_dim_passo": TESTI["passi_menu_titolo"],

    "filtri_dim_a_che_punto": "Status",
    "filtri_dim_cosa_ne_facciamo": "What we do with it",
    "filtri_dim_che_cosa_e": "What it is",
    "filtri_dim_progetto": "Project",
    "filtri_dim_area": "Area",
    "filtri_dim_le_tue_parole": "Your words",
    "filtri_dim_domande": "Questions",
    "filtri_dim_da_dove": "From where",
    "filtri_dim_contenuto": "Format",
    "filtri_dim_quando": "When it arrived",
    "filtri_dim_attesa": "How long it's been waiting for you",

    "filtri_voce_domanda": "Questions for you",
    "filtri_voce_da_leggere": "To read",
    "filtri_voce_agente_aperto": "Agent open in the terminal",
    "filtri_voce_fermo": "Stuck",
    "filtri_voce_altri": "Set aside",
    "filtri_voce_non_detto": "Nothing said yet",
    "filtri_voce_senza_area": "No area",
    "filtri_voce_parole": "With your words",
    "filtri_voce_audio": "With an audio of yours",
    "filtri_voce_senza_parole": "Without your words",
    "filtri_voce_con_domande": "With questions",
    "filtri_voce_domande_legge": "With legal questions",
    "filtri_voce_senza_domande": "Without questions",
    "filtri_voce_senza_dove": "Unknown",
    "filtri_voce_senza_tipo": "Unknown",
    "filtri_voce_oggi": "Today",
    "filtri_voce_ultimi_giorni": "In the last {n} days",

    "filtri_voce_prima_di": "More than {n} days ago",
    "filtri_voce_giorni_fa": "More than {n} days ago",
    "filtri_voce_senza_data": "No date",
    "filtri_voce_meno_di": "Less than {n} days ago",
    "filtri_voce_non_ti_aspetta": "Not waiting for you",
    "filtri_ordine": "Sort by",
    "filtri_ordine_attesa": "Waiting for you the longest",
    "filtri_gruppo": "Group by",
    "filtri_gruppo_niente": "No group",
    "filtri_pronti": "Ready-made",
    "filtri_salvati": "Saved filters",
    "filtri_salva": "Save this filter",
    "filtri_salva_aiuto": "You find it here under the name you give it",
    "filtri_togli": "Remove",
    "filtri_togli_aiuto": "It leaves the list, you can save it again whenever you want",
    "filtri_togli_tutti": "Clear the filters",

    "filtri_tuoi": "Yours",
    "filtri_togli_salvato": "Remove a saved filter",
    "filtri_nome_segnaposto": "The filter name",
    "filtri_salva_pulsante": "Save",

    "aiuto_filtri": (
        "You can pick several entries. Under the same heading one is enough, under different headings they all apply. The number "
        "next to each entry takes into account the choices under the other headings."
    ),
    "aiuto_filtri_salvati": (
        "The ready-made filters and the ones you saved. Pick one and all its choices come back, including the order and the groups."
    ),
    "aiuto_raggruppa": "The items split into groups, each with its own heading and number.",

    "filtri_pronto_nuovi": "New, to confirm",
    "filtri_pronto_arretrati": "To confirm, proposed earlier",
    "filtri_pronto_riferimento": "To keep as a reference",
    "filtri_pronto_team": "To do for the team",
    "filtri_pronto_mie_parole": "With your words, to confirm",
    "filtri_pronto_legge": "Legal questions",
    "filtri_pronto_terminale": "Waiting for you in the terminal",
}

_TESTI_PRIMA_DEI_FILTRI = frozenset(TESTI)
TESTI.update(TESTI_FILTRI)


FILTRI_GIORNI_SETTIMANA = 7
FILTRI_GIORNI_MESE = 30


FILTRI_SALVATI_NOME = "filtri-salvati.json"
FILTRI_SALVATI_LUCCHETTO = ".filtri-salvati.lock"
FILTRI_SALVATI_FORMATO = "inspiration-filtri-salvati"

FILTRI_NOME_MAX = 60


def _voci_filtro(*coppie) -> list[dict]:
    return [{"id": i, "nome": n} for i, n in coppie]





FILTRI_UNA_VOCE = frozenset(
    (
        "passo",
        "a_che_punto",
        "cosa_ne_facciamo",
        "che_cosa_e",
        "progetto",
        "area",
        "da_dove",
        "contenuto",
    )
)


PASSO_TUTTI = "tutti"


def filtri_dimensioni() -> list[dict]:
    ""






    sett, mese = FILTRI_GIORNI_SETTIMANA, FILTRI_GIORNI_MESE
    S = _smista_regole()
    dims = (
        (


            "passo",
            _voci_filtro(
                *((i, TESTI[k]) for i, k, _ in MENU_PASSI if i != PASSO_TUTTI),
                ("senza", TESTI["filtri_voce_altri"]),
            ),
        ),
        (
            "a_che_punto",
            _voci_filtro(
                ("nuovi", TESTI["segno_nuovo_da_confermare"]),
                ("da_confermare", TESTI["segno_da_confermare"]),
                ("domanda", TESTI["filtri_voce_domanda"]),
                ("ti_aspetta", TESTI["segno_ti_aspetta"]),
                ("da_dire", TESTI["segno_da_dire"]),
                ("da_far_partire", TESTI["segno_da_far_partire"]),
                ("da_leggere", TESTI["filtri_voce_da_leggere"]),
                ("da_scegliere", TESTI["segno_da_scegliere"]),
                ("task_da_creare", TESTI["segno_task_da_creare"]),
                ("agente_aperto", TESTI["filtri_voce_agente_aperto"]),
                ("al_lavoro", TESTI["segno_lavora"]),
                ("capisco", TESTI["segno_capisco"]),
                ("fermo", TESTI["filtri_voce_fermo"]),
                *(
                    (u, TESTI[f"menu_{u}"])
                    for u in ("riferimento", "cosa_da_fare", "letto", "non_serve")
                ),
                ("senza", TESTI["filtri_voce_altri"]),
            ),
        ),
        (
            "cosa_ne_facciamo",
            _voci_filtro(
                ("sviluppo", TESTI["strada_sviluppo"]),
                ("studio", TESTI["strada_studio"]),


                ("cosa_da_fare_owner", TESTI[_chiave_owner_da_fare()]),
                ("cosa_da_fare_team", TESTI["strada_cosa_da_fare_team"]),
                ("cosa_da_fare", TESTI["strada_cosa_da_fare"]),
                ("riferimento", TESTI["strada_riferimento"]),
                ("non_serve", TESTI["strada_non_serve"]),
                ("senza", TESTI["filtri_voce_non_detto"]),
            ),
        ),
        (
            "che_cosa_e",
            _voci_filtro(
                *((t, _maiuscola(TESTI[f"tipo_{t}"])) for t in TIPI_SCOPE),
                ("senza", TESTI["filtri_voce_non_detto"]),
            ),
        ),
        (
            "progetto",
            _voci_filtro(
                *((p.lower(), _parola_progetto(p)) for p in PROGETTI_SCOPE if p != "altro"),
                ("senza", TESTI["senza_progetto"]),
            ),
        ),
        (
            "area",
            _voci_filtro(
                *((a, AREE_PAROLE.get(a, _maiuscola(a))) for a in S.ATTIVITA),
                ("senza", TESTI["filtri_voce_senza_area"]),
            ),
        ),
        (
            "le_tue_parole",
            _voci_filtro(
                ("parole", TESTI["filtri_voce_parole"]),
                ("audio", TESTI["filtri_voce_audio"]),
                ("senza", TESTI["filtri_voce_senza_parole"]),
            ),
        ),
        (
            "domande",
            _voci_filtro(
                ("con", TESTI["filtri_voce_con_domande"]),
                ("legge", TESTI["filtri_voce_domande_legge"]),
                ("senza", TESTI["filtri_voce_senza_domande"]),
            ),
        ),
        (


            "da_dove",
            _voci_filtro(
                *((p.lower(), p) for p in dict.fromkeys(PIATTAFORME.values())),
                ("senza", TESTI["filtri_voce_senza_dove"]),
            ),
        ),
        (
            "contenuto",
            _voci_filtro(
                *((t, TIPI[t][0]) for t in TIPI),
                ("senza", TESTI["filtri_voce_senza_tipo"]),
            ),
        ),
        (
            "quando",
            _voci_filtro(
                ("oggi", TESTI["filtri_voce_oggi"]),
                ("settimana", TESTI["filtri_voce_ultimi_giorni"].format(n=sett)),
                ("mese", TESTI["filtri_voce_ultimi_giorni"].format(n=mese)),

                ("prima", TESTI["filtri_voce_giorni_fa"].format(n=mese)),
                ("senza", TESTI["filtri_voce_senza_data"]),
            ),
        ),
        (
            "attesa",
            _voci_filtro(
                ("meno_settimana", TESTI["filtri_voce_meno_di"].format(n=sett)),
                ("piu_settimana", TESTI["filtri_voce_prima_di"].format(n=sett)),
                ("piu_mese", TESTI["filtri_voce_prima_di"].format(n=mese)),
                ("senza", TESTI["filtri_voce_non_ti_aspetta"]),
            ),
        ),
    )
    return [
        {
            "id": i,
            "nome": TESTI[f"filtri_dim_{i}"],
            "piu_voci": i not in FILTRI_UNA_VOCE,
            "voci": voci,
        }
        for i, voci in dims
    ]




FILTRI_ORDINI = (
    ("recenti", "ordine_recenti"),
    ("vecchi", "ordine_vecchi"),
    ("attesa", "filtri_ordine_attesa"),

    ("per_te", "ordine_per_te"),
)




FILTRI_GRUPPI = (
    ("niente", "filtri_gruppo_niente"),
    ("progetto", "filtri_dim_progetto"),
    ("strada", "filtri_dim_cosa_ne_facciamo"),
    ("a_che_punto", "filtri_dim_a_che_punto"),
)


FILTRI_GRUPPI_DIMENSIONE = {
    "niente": "",
    "progetto": "progetto",
    "strada": "cosa_ne_facciamo",
    "a_che_punto": "a_che_punto",
}


_DA_CONFERMARE = ("nuovi", "da_confermare")
FILTRI_PRONTI = (
    ("nuovi", "filtri_pronto_nuovi", {"a_che_punto": ("nuovi",)}, "recenti", "niente"),
    (
        "arretrati",
        "filtri_pronto_arretrati",
        {"a_che_punto": ("da_confermare",)},
        "attesa",
        "strada",
    ),
    (
        "riferimento",
        "filtri_pronto_riferimento",
        {"a_che_punto": _DA_CONFERMARE, "cosa_ne_facciamo": ("riferimento",)},
        "recenti",
        "niente",
    ),
    (
        "team",
        "filtri_pronto_team",
        {"a_che_punto": _DA_CONFERMARE, "cosa_ne_facciamo": ("cosa_da_fare_team",)},
        "recenti",
        "progetto",
    ),
    (
        "mie_parole",
        "filtri_pronto_mie_parole",
        {"a_che_punto": _DA_CONFERMARE, "le_tue_parole": ("parole",)},
        "recenti",
        "niente",
    ),
    ("legge", "filtri_pronto_legge", {"domande": ("legge",)}, "recenti", "progetto"),
    ("terminale", "filtri_pronto_terminale", {"a_che_punto": ("ti_aspetta", "da_dire")}, "attesa", "niente"),
)


def valida_filtro(filtro, dims: list[dict] | None = None) -> tuple[dict | None, str]:
    ""




    if not isinstance(filtro, dict) or set(filtro) - {"scelte", "ordine", "gruppo"}:
        return None, "forma"
    scelte = filtro.get("scelte", {})
    if not isinstance(scelte, dict):
        return None, "forma"
    dims = dims if dims is not None else filtri_dimensioni()
    voci = {d["id"]: [x["id"] for x in d["voci"]] for d in dims}
    pulite = {}
    for dim, scelta in scelte.items():
        if dim not in voci:
            return None, "dimensione"
        if not isinstance(scelta, list) or not all(isinstance(x, str) for x in scelta):
            return None, "forma"
        if dim == "passo" and PASSO_TUTTI in scelta:

            continue
        if any(x not in voci[dim] for x in scelta):
            return None, "voce"
        if scelta:
            pulite[dim] = [x for x in voci[dim] if x in scelta]
    ordine = filtro.get("ordine", "recenti")
    if ordine not in {i for i, _ in FILTRI_ORDINI}:
        return None, "ordine"
    gruppo = filtro.get("gruppo", "niente")
    if gruppo not in {i for i, _ in FILTRI_GRUPPI}:
        return None, "gruppo"
    return {
        "scelte": {d: pulite[d] for d in voci if d in pulite},
        "ordine": ordine,
        "gruppo": gruppo,
    }, ""


def filtri_pronti() -> list[dict]:
    ""
    dims = filtri_dimensioni()
    out = []
    for i, k, scelte, ordine, gruppo in FILTRI_PRONTI:
        filtro, _ = valida_filtro(
            {"scelte": {d: list(x) for d, x in scelte.items()}, "ordine": ordine, "gruppo": gruppo},
            dims,
        )
        out.append({"id": i, "nome": TESTI[k], "filtro": filtro})
    return out


def nome_filtro(nome) -> str:
    ""
    return " ".join(unicodedata.normalize("NFC", str(nome or "")).split())


def leggi_filtri_salvati(percorso: str | None = None) -> tuple[list[dict], bool]:
    ""
    p = percorso or os.path.join(RADICE, "archivio", FILTRI_SALVATI_NOME)
    try:
        with open(p, encoding="utf-8") as fh:
            d = json.load(fh)
    except FileNotFoundError:
        return [], True
    except (OSError, ValueError):
        return [], False
    righe = d.get("filtri") if isinstance(d, dict) else None
    if not isinstance(righe, list):
        return [], False
    return [r for r in righe if isinstance(r, dict)], True


def filtri_salvati_a_vista(righe: list[dict]) -> list[dict]:
    ""

    out = []
    for r in righe:
        nome = nome_filtro(r.get("nome"))
        if not nome or r.get("tolto") or not isinstance(r.get("filtro"), dict):
            continue
        out.append(
            {"id": nome, "nome": nome, "filtro": r["filtro"], "quando": str(r.get("quando") or "")}
        )
    return out


def _voce_a_che_punto(v: dict) -> str:
    ""

    if v.get("a_parte"):
        return "senza"
    s = _dict(v.get("segno"))
    tipo, pm = str(s.get("tipo") or ""), str(v.get("passo_menu") or "")
    if pm in USCITE and tipo in ("uscito", "da_fare", ""):
        return pm
    if tipo == "da_confermare":
        return "nuovi" if s.get("salute") == "accento" else "da_confermare"
    if tipo == "domanda":
        return "ti_aspetta" if s.get("parola") == TESTI["segno_ti_aspetta"] else "domanda"
    return {
        "da_dire": "da_dire",
        "da_far_partire": "da_far_partire",
        "da_avviare": "da_far_partire",
        "tocca_te": "da_far_partire",
        "da_leggere": "da_leggere",
        "ritorno": "da_leggere",
        "da_scegliere": "da_scegliere",
        "task_da_creare": "task_da_creare",
        "agente_aperto": "agente_aperto",
        "lavora": "al_lavoro",
        "capisco": "capisco",
        "scende": "capisco",
        "fermo": "fermo",
        "da_fare": "cosa_da_fare",
    }.get(tipo, "senza")


def _giorni_fa(iso: str) -> float | None:
    d = _d(iso)
    if d is None:
        return None
    if d.tzinfo is not None:
        d = d.replace(tzinfo=None)
    return (_adesso_ora() - d).total_seconds() / 86400


def _voci_quando(iso: str) -> list[str]:
    ""



    d = _d(iso)
    if d is None:
        return []
    if d.tzinfo is not None:
        d = d.replace(tzinfo=None)
    adesso = _adesso_ora()
    d = min(d, adesso)
    giorni = (adesso - d).total_seconds() / 86400
    return [
        q
        for q, si in (
            ("oggi", d.date() == adesso.date()),
            ("settimana", giorni < FILTRI_GIORNI_SETTIMANA),

            ("mese", giorni <= FILTRI_GIORNI_MESE),
            ("prima", giorni > FILTRI_GIORNI_MESE),
        )
        if si
    ]


def _filtro_spunto(v: dict, voci: dict) -> dict:
    ""

    L = _dict(v.get("lavorazione"))
    sc = _dict(L.get("scope"))
    d = _dict(v.get("dettaglio"))
    strada = str(sc.get("strada") or "")
    if strada == "cosa_da_fare":
        chi = str(sc.get("chi") or "")
        strada = f"cosa_da_fare_{chi}" if chi in ("owner", "team") else strada
    parole = []
    if d.get("parole_owner") or v.get("nessuna_parola_vale") is False:
        parole.append("parole")
    if (
        _dict(v.get("_interno")).get("audio_di_owner")
        or d.get("audio_owner")
        or v.get("frase_audio")
        or any(isinstance(p, dict) and p.get("audio") for p in d.get("parole_owner") or [])
    ):
        parole.append("audio")
    domande = {}
    for x in (
        *(sc.get("domande") or []),
        *(sc.get("altre_domande") or []),
        *(_dict(L.get("adesso")).get("domande") or []),
    ):
        if isinstance(x, dict):
            domande[str(x.get("id") or x.get("testo") or len(domande))] = bool(x.get("policy"))
    quando = _voci_quando(str(v.get("quando") or ""))
    attesa_g = _giorni_fa(str(v.get("proposto_quando") or ""))
    attesa = []
    if attesa_g is not None:
        attesa = [
            a
            for a, si in (
                ("meno_settimana", attesa_g < FILTRI_GIORNI_SETTIMANA),
                ("piu_settimana", attesa_g >= FILTRI_GIORNI_SETTIMANA),
                ("piu_mese", attesa_g >= FILTRI_GIORNI_MESE),
            )
            if si
        ]
    grezzo = {

        "passo": [] if v.get("a_parte") else [str(v.get("passo_menu") or "")],
        "a_che_punto": [_voce_a_che_punto(v)],
        "cosa_ne_facciamo": [strada],
        "che_cosa_e": [str(sc.get("tipo") or "")],
        "progetto": [str(v.get("progetto_a_vista") or "").lower()],
        "area": [str(sc.get("area") or "")],
        "le_tue_parole": parole,
        "domande": (["con", "legge"] if any(domande.values()) else ["con"]) if domande else [],
        "da_dove": [str(v.get("piattaforma") or "").lower()],
        "contenuto": [str(v.get("tipo") or "")],
        "quando": quando,
        "attesa": attesa,
    }
    out = {}
    for dim, ammessi in voci.items():
        dentro = [x for x in grezzo.get(dim, []) if x and x != "senza" and x in ammessi]
        out[dim] = dentro or ["senza"]
    return out


def _filtro_per_spunti(voci_bacheca: list) -> None:
    ""

    ammessi = {d["id"]: {x["id"] for x in d["voci"]} for d in filtri_dimensioni()}
    for v in voci_bacheca:
        v["faccette"] = _filtro_spunto(v, ammessi)


def _campi_filtri_bacheca() -> dict:
    ""


    righe, si_legge = leggi_filtri_salvati()
    return {
        "filtri": {
            "dimensioni": filtri_dimensioni(),
            "ordini": [{"id": i, "nome": TESTI[k]} for i, k in FILTRI_ORDINI],
            "gruppi": [
                {"id": i, "nome": TESTI[k], "dimensione": FILTRI_GRUPPI_DIMENSIONE[i]}
                for i, k in FILTRI_GRUPPI
            ],
        },
        "filtri_pronti": filtri_pronti(),
        "filtri_salvati": filtri_salvati_a_vista(righe),

        "filtri_salvati_si_legge": si_legge,
    }


def stato() -> dict:
    ""
    global _CFG_DELLA_BACHECA, _ATTIVITA_DELLA_BACHECA
    if not sb_inspiration_root.is_on():
        return {"ok": False, "spenta": True, "messaggio": sb_inspiration_root.OFF_MESSAGE}
    try:
        return _stato()
    finally:
        _CFG_DELLA_BACHECA = None
        _ATTIVITA_DELLA_BACHECA = None


def _stato() -> dict:
    esportazione = _leggi(ESPORTAZIONE)
    try:



        import sb_inspiration_azioni as az


        if os.path.realpath(az.CASA_ARCHIVIO) == os.path.realpath(os.path.join(RADICE, "archivio")):
            voci = esportazione.get("voci") if isinstance(esportazione, dict) else None
            if az.importa(voci if isinstance(voci, list) else None).get("scritto"):
                esportazione = _leggi(ESPORTAZIONE)
    except Exception:
        pass


    global _CFG_DELLA_BACHECA
    _CFG_DELLA_BACHECA = _leggi_ritmo()
    if isinstance(esportazione, dict) and isinstance(esportazione.get("voci"), list):
        grezze, fonte, file_fonte = esportazione["voci"], "esportazione", ESPORTAZIONE
    else:
        grezze, fonte, file_fonte = _leggi_righe(ARCHIVIO), "archivio", ARCHIVIO
        esportazione = {}


    global _ATTIVITA_DELLA_BACHECA
    _ATTIVITA_DELLA_BACHECA = _stati_in_attivita(grezze)
    tutte = [
        _voce(v) | {"a_parte": bool((v.get("a_parte") or {}).get("si"))}
        for v in grezze
        if isinstance(v, dict)
    ]
    spunti = [v for v in tutte if not v["a_parte"]]
    a_parte = [v for v in tutte if v["a_parte"]]
    for gruppo in (spunti, a_parte):
        gruppo.sort(key=lambda v: v["quando"], reverse=True)
    schede = []
    for s in SCHEDE:
        n = len(spunti) if s["id"] == "tutti" else sum(1 for v in spunti if v["scheda"] == s["id"])
        schede.append(
            {"id": s["id"], "nome": s["nome"], "n": n, "aiuto": s["aiuto"], "vuota": s["vuota"]}
        )
    da_decidere = next(s for s in schede if s["id"] == "da_decidere")
    tipi: dict[str, int] = {}
    for v in spunti:
        tipi[v["tipo"]] = tipi.get(v["tipo"], 0) + 1
    try:
        aggiornato = datetime.datetime.fromtimestamp(os.path.getmtime(file_fonte))
        quando = _quando(aggiornato.isoformat())
        if aggiornato.date() < datetime.date.today() - datetime.timedelta(days=1):
            quando += f" at {aggiornato:%H:%M}"
        frase_aggiornato = TESTI["aggiornato"].format(quando=quando)
    except OSError:
        frase_aggiornato = ""
    fasi = _fasi(spunti)
    cfg = _CFG_DELLA_BACHECA
    _segni_da_capire(spunti, cfg)
    for v in spunti:
        v["segno"] = _segno(v)
        if _pronto_quieto(v):


            v["segno"] = {**v["segno"], "salute": "neutra"}
    testa = _testa(spunti, cfg, file_fonte, frase_aggiornato)
    ritmo = _ritmo(file_fonte, spunti)
    da_capire_visti = len(_per_te(spunti, cfg))

    quanti_aspettano_te = _aspettano_te_nuovi(spunti)

    contati = {id(v) for v in (*_nuovi_per_te(spunti), *_aspettano_su_di_te(spunti))}
    for v in tutte:
        v["per_te"] = id(v) in contati
        v["passo_menu"] = _passo_menu(v)

        v["pronto"] = _pronto_quieto(v)

    _filtro_per_spunti(tutte)
    passi_menu = _passi_menu(spunti)

    lista = lista_da_confermare(spunti)
    confermati_in_lista = gruppi_confermati(grezze)
    pronti = _pronti(spunti)
    for v in tutte:
        v.pop("_interno", None)
    return {
        "ok": True,

        "testa": testa,

        "spunti_frase": TESTI["spunti_conto_uno"]
        if len(spunti) == 1
        else TESTI["spunti_conto"].format(n=len(spunti)),
        "fonte": fonte,
        "file": file_fonte,

        "ultima_rilettura": _ultima_rilettura(file_fonte),

        "cartella": os.path.dirname(file_fonte),
        "aggiornato": frase_aggiornato,


        "da_capire_visti": da_capire_visti,

        "ritmo": ritmo,

        "impostazioni": impostazioni(cfg),

        **_campi_filtri_bacheca(),


        "lista_da_confermare": lista,
        "gruppi_confermati": confermati_in_lista,

        "pronti": pronti,

        "aspettano_te": next((f["aspettano_te"] for f in fasi if f["id"] == "tutti"), 0),


        "aspettano_te_nuovi": quanti_aspettano_te,
        "scheda_iniziale": "da_decidere" if da_decidere["n"] else "tutti",
        "schede": schede,
        "tipi": [
            {
                "id": t,
                "nome": TIPI.get(t, TIPI["video"])[0],
                "simbolo": TIPI.get(t, TIPI["video"])[1],
                "plurale": PLURALI.get(t, t),
                "n": n,
            }
            for t, n in sorted(tipi.items(), key=lambda x: -x[1])
        ],
        "progetti": _ordine_progetti(spunti),

        "progetti_a_vista": _ordine_progetti(spunti, "progetto_a_vista"),
        "parti": [
            {"id": "capiti", "titolo": TESTI["capiti"], "frase": TESTI["capiti_frase"]},
            {"id": "visti", "titolo": TESTI["visti"], "frase": TESTI["visti_frase"]},
            {"id": "non_visti", "titolo": TESTI["non_visti"], "frase": TESTI["non_visti_frase"]},
        ],
        "voci": spunti,
        "a_parte": a_parte,

        "fasi": fasi,



        "passi_menu": passi_menu,
        "esiti": [{"id": i, "parole": p} for i, p in ESITI],
        "domande": [
            {"testo": str(d.get("testo") or ""), "voci": [str(x) for x in d.get("voci") or []]}
            for d in (esportazione.get("domande") or [])
            if isinstance(d, dict) and d.get("testo")
        ],
        "testi": TESTI,
    }



TENTATIVI_COMPRENSIONE = 3

TICK_VIVO_MIN = 25


def _leggi_ritmo(casa: str | None = None) -> dict:
    ""
    try:
        d = json.loads(
            Path(casa or os.path.join(RADICE, "archivio"), "capisci-da-solo.json").read_text(
                encoding="utf-8"
            )
        )
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}




_CFG_DELLA_BACHECA: dict | None = None


_ATTIVITA_DELLA_BACHECA: dict | None = None


def _ha_task_in_attivita(v: dict) -> bool:
    ""

    L = v.get("lavorazione") if isinstance(v.get("lavorazione"), dict) else {}
    sc = _dict(L.get("scope"))
    t = _dict(sc.get("task"))
    if t.get("dove") == "attivita" and t.get("id"):
        return True
    valori = (
        _dict(v.get("link")).get("task"),
        _dict(v.get("attivita")).get("task_url"),
        _dict(_dict(L.get("smistamento")).get("confermato")).get("task"),
        t.get("id"),
    )
    return any(str(x or "").startswith("attivita:") for x in valori)


def _stati_in_attivita(grezze: list) -> dict:
    ""




    if not any(isinstance(v, dict) and _ha_task_in_attivita(v) for v in grezze):
        return {}
    try:
        import sb_inspiration_azioni as az

        if os.path.realpath(az.CASA_ARCHIVIO) != os.path.realpath(os.path.join(RADICE, "archivio")):
            return {}
        d = az.origini_in_attivita()
    except Exception:  # noqa: BLE001 the board still loads, without the tasks' state
        return {}
    return d if isinstance(d, dict) else {}


def _task_del_lavoro(v: dict) -> dict:
    ""
    t = str(_dict(v.get("attivita")).get("task_url") or "")
    if t.startswith("attivita:"):
        att = _in_attivita(v)
        return {
            "task_dove": "attivita",
            "task_stato": att.get("stato", ""),
            "task_stato_nome": att.get("stato_nome", ""),
        }
    return {"task_dove": "clickup" if t else "", "task_stato": "", "task_stato_nome": ""}


def _rifalla_si(v: dict, scope: dict) -> bool:
    ""

    if scope.get("delicato") or _cfg().get("task_in_attivita") is not True:
        return False
    return _ha_task_in_attivita(v) and _in_attivita(v).get("stato") == "eliminata"


def _in_attivita(v: dict) -> dict:
    ""

    t = (_ATTIVITA_DELLA_BACHECA or {}).get(str(v.get("id") or ""))
    if not isinstance(t, dict) or not t.get("id"):
        return {}
    stato = "eliminata" if t.get("eliminata") else ("chiusa" if t.get("chiusa") else "viva")
    return {"id": str(t["id"]), "stato": stato, "stato_nome": str(t.get("stato_nome") or "")}


def _cfg() -> dict:
    return _CFG_DELLA_BACHECA if _CFG_DELLA_BACHECA is not None else _leggi_ritmo()


def _ritmo_acceso() -> bool:
    return bool(_cfg().get("acceso"))








IMPOSTAZIONI_VOCI = (
    ("acceso", "interruttore", True),
    ("leggi_dm", "interruttore", True),
    ("task_in_attivita", "interruttore", True),
    ("nuovo_giorni", "numero", True),
    ("task_su_clickup", "interruttore", False),
)
NUOVO_GIORNI_MINIMO = 1
NUOVO_GIORNI_MASSIMO = 14

VALORI_INTERRUTTORE = {"acceso": True, "spento": False}



TRACCIA_IMPOSTAZIONI = "impostazioni_traccia"

DA_IMPOSTAZIONI = {"owner": "imp_traccia_te", "secondbrain": "imp_traccia_me"}




INTERVALLO_CONTROLLO_MIN = 10


def _intervallo_minuti(cfg: dict | None = None, intervallo: int | None = None) -> int:
    ""

    if intervallo:
        return int(intervallo)
    try:
        n = int((cfg if cfg is not None else _cfg()).get("intervallo_minuti"))
    except (TypeError, ValueError):
        n = 0
    return n if n > 0 else INTERVALLO_CONTROLLO_MIN


def _valore_impostazione(cfg: dict, chiave: str):
    ""

    if chiave == "acceso":
        return bool(cfg.get("acceso"))
    if chiave == "leggi_dm":
        return cfg.get("leggi_dm") is not False
    if chiave == "nuovo_giorni":
        return _nuovo_giorni(cfg)
    return cfg.get(chiave) is True


def _frase_impostazione(chiave: str, valore, dipende: bool, n: int) -> str:
    if chiave == "acceso":
        return TESTI["imp_acceso_si"].format(n=n) if valore else TESTI["imp_acceso_no"]
    if chiave == "leggi_dm":
        if dipende:
            return TESTI["imp_leggi_dm_dipende"]
        if valore:
            return TESTI["imp_leggi_dm_si"].format(n=n)
        return TESTI["imp_leggi_dm_no"].format(parola=TESTI["testa_rileggi"])
    if chiave == "task_in_attivita":
        return TESTI["imp_task_in_attivita_si" if valore else "imp_task_in_attivita_no"]
    if chiave == "nuovo_giorni":
        if valore == 1:
            return TESTI["imp_nuovo_giorni_frase_uno"]
        return TESTI["imp_nuovo_giorni_frase"].format(n=valore)
    return TESTI["imp_task_su_clickup_acceso" if valore else "imp_task_su_clickup_frase"]


def _data_piena(d: datetime.datetime) -> str:
    ""

    oggi = _adesso_ora().date()
    if d.date() == oggi:
        return "today"
    if d.date() == oggi - datetime.timedelta(days=1):
        return "yesterday"
    testo = f"{MESI[d.month - 1]} {d.day}"
    return testo if d.year == _adesso_ora().year else f"{testo} {d.year}"


def _frase_traccia(t, tipo: str, valore) -> str:
    ""


    if not isinstance(t, dict):
        return ""
    chi = DA_IMPOSTAZIONI.get(str(t.get("da") or ""))
    d = _d(t.get("quando"))
    if not chi or d is None or "valore" not in t or t.get("valore") != valore:
        return ""
    if tipo == "numero":
        cosa = TESTI["imp_traccia_cambiato"]
    else:
        cosa = TESTI["imp_traccia_acceso" if valore else "imp_traccia_spento"]
    return TESTI["imp_traccia"].format(
        cosa=cosa, chi=TESTI[chi], quando=_data_piena(d), ora=f"{d:%H:%M}"
    )


def _gesto_impostazione(chiave: str, tipo: str, valore) -> dict:
    ""


    if tipo == "numero":
        return {
            "verbo": "impostazioni",
            "riga": f"impostazioni --da owner {chiave}",
            "parola": TESTI["imp_cambia"],
            "aiuto": "",
        }
    return {
        "verbo": "impostazioni",
        "riga": f"impostazioni --da owner {chiave} {'spento' if valore else 'acceso'}",
        "parola": TESTI["imp_spegni" if valore else "imp_accendi"],
        "aiuto": "",
    }


def impostazioni(cfg: dict | None = None, intervallo: int | None = None) -> dict:
    ""


    cfg = cfg if isinstance(cfg, dict) else _cfg()
    n = _intervallo_minuti(cfg, intervallo)
    traccia = _dict(cfg.get(TRACCIA_IMPOSTAZIONI))
    acceso = bool(cfg.get("acceso"))
    voci = []
    for chiave, tipo, si_cambia in IMPOSTAZIONI_VOCI:
        valore = _valore_impostazione(cfg, chiave)
        dipende = chiave == "leggi_dm" and not acceso
        voce = {
            "chiave": chiave,
            "nome": TESTI[f"imp_{chiave}_nome"],
            "tipo": tipo,
            "valore": valore,
            "frase": _frase_impostazione(chiave, valore, dipende, n),
            "da_chi_quando": _frase_traccia(traccia.get(chiave), tipo, valore),
            "dipende": dipende,
        }
        if tipo == "numero":
            voce["minimo"], voce["massimo"] = NUOVO_GIORNI_MINIMO, NUOVO_GIORNI_MASSIMO
        if si_cambia and not dipende:
            voce["cambia"] = _gesto_impostazione(chiave, tipo, valore)
        voci.append(voce)
    return {"titolo": TESTI["imp_titolo"], "voci": voci}






def _cartelle_contenuto(v: dict) -> list[Path]:
    ""

    base = Path(RADICE, "archivio", "contenuti")
    nomi = []
    dichiarata = str(_dict(v.get("copia")).get("cartella") or "")
    if dichiarata:
        nomi.append(os.path.basename(dichiarata.rstrip("/")))
    ident = str(v.get("id") or "").replace(":", "-")
    if ident:
        nomi += [ident, ident + "-"]
    out, visti = [], set()
    for n in nomi:
        if n and n not in visti:
            visti.add(n)
            out.append(base / n)
    return out


def _iso_file(st) -> str:
    return datetime.datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds")


def _g3(v: dict, aperta_quando: str) -> dict:
    ""


    tipo = str(v.get("tipo") or "")
    out = {
        "sceso": False,
        "sceso_quando": "",
        "calcolato": False,
        "dossier": False,
        "dossier_quando": "",
    }
    for cartella in _cartelle_contenuto(v):
        try:
            voci = list(os.scandir(cartella))
        except OSError:
            continue
        for e in voci:
            nome = e.name
            contenuto = (
                nome == "video.mp4"
                if tipo == "video"
                else (nome.startswith("slide-") or nome == "pagina.html")
            )
            try:
                if contenuto and not out["sceso"]:
                    out.update(sceso=True, sceso_quando=_iso_file(e.stat()))
                elif nome == "calcolo.json":
                    out["calcolato"] = True
                elif nome == "DOSSIER.md" and aperta_quando:
                    quando = _iso_file(e.stat())
                    if quando >= aperta_quando[:19]:
                        out.update(dossier=True, dossier_quando=quando)
            except OSError:
                continue
    return out


def _rilettura_in_fila(ri: dict) -> bool:
    ""



    cartella = str(ri.get("cartella") or "")
    if not ri.get("aperta_quando") or ri.get("chiusa_quando") or not cartella:
        return False
    try:
        processo = json.loads((Path(cartella) / "processo.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        return True
    except (OSError, ValueError):
        return False
    return not (isinstance(processo, dict) and processo.get("claude_partito"))


def _attesa(v: dict, fase: str, aperta_vera: bool, sceso: bool, com: dict) -> str:
    ""



    if fase != "da_capire":
        return ""
    disp = str(_dict(v.get("disponibilita")).get("stato") or "")
    if disp == "vietato ai minori":
        return "vietato"
    if disp in ("rimosso", "sparito"):
        return "sparito"
    cfg = _cfg()
    ident = str(v.get("id") or "")

    if ident in (cfg.get("senza_accesso") or []):
        return "sparito"
    if aperta_vera:
        return "capisco"


    if _ripresa_fermata(com):
        return "fermo" if cfg.get("acceso") else "spento"



    if ident in (cfg.get("fermi_a_vuoto") or []) or (
        "fermi_a_vuoto" not in cfg
        and ident in (cfg.get("si_di_owner") or [])
        and ident in (cfg.get("fermi") or [])
    ):
        return "a_vuoto"
    if not cfg.get("acceso"):
        return "spento"
    if ident in (cfg.get("fermi") or []):
        return "fermo"
    if ident in (cfg.get("si_di_owner") or []) or ident in (cfg.get("in_fila_col_si") or []):
        return "si"
    tentativi = int(com.get("tentativi") or 0)
    esito = com.get("esito") if isinstance(com.get("esito"), dict) else {}
    chiusa_male = bool(com.get("chiusa_quando")) and esito.get("stato") != "fatto"
    if ident in (cfg.get("fermi") or []) or (chiusa_male and tentativi >= TENTATIVI_COMPRENSIONE):
        return "fermo"
    if chiusa_male and _fermo_vero(com):
        return "fermo"

    if ident in (cfg.get("aspettano_te") or []) or (
        not sceso and str(v.get("piattaforma") or "") == "linkedin"
    ):
        return "aspetta_si"
    if chiusa_male:
        return "riprovo"
    return "sceso" if sceso else "scende"



TETTO_A_VUOTO = 12


def _ripresa_fermata(com: dict) -> bool:
    ""
    esito = _dict(com.get("esito"))
    return (
        bool(com.get("ripresa_a_vuoto"))
        and bool(com.get("chiusa_quando"))
        and esito.get("stato") == "fermo"
        and not esito.get("a_vuoto")
    )


def _fermo_vero(com: dict) -> bool:
    ""


    if not com.get("chiusa_quando"):
        return False
    esito = _dict(com.get("esito"))
    if esito.get("stato") == "fatto":
        return False
    if _ripresa_fermata(com):
        return True
    if int(com.get("tentativi_a_vuoto") or 0) >= TETTO_A_VUOTO:
        return True
    return int(com.get("tentativi") or 0) >= TENTATIVI_COMPRENSIONE


def _aiuto_fermo(i: dict) -> str:
    ""

    motivo = _motivo_frase(_quando(i.get("fermo_quando")), i.get("motivo"))
    if "Fallo adesso" in motivo:
        return motivo
    chiave = "segno_fermo_aiuto" if i.get("tre_volte", True) else "segno_fermo_aiuto_altro"
    return TESTI[chiave].format(motivo=motivo)


def _riparte_da_solo() -> bool:
    ""
    return _cfg().get("riparti_fermi_a_vuoto") in (True, "uno")



_MOTIVI_SENZA_SOGGETTO = re.compile(r"^(si è |non è partita|è andata |si sono |ha superato )", re.I)

_MINUSCOLE = re.compile(
    r"^(La|Il|Lo|Gli|I|Le|L'|Un|Una|Nessun|Nessuna|Non|Si|Ho|Mi|Adesso|Quando|Questo|Questa|È)\b"
)


def _motivo_normale(motivo: str) -> str:
    ""


    m = _parole_semplici(str(motivo or "")).strip().rstrip(".")
    if not m:
        return "Understanding stopped before it finished"
    if re.match(r"^si è interrott[ao] prima di finire$", m, re.I):
        return "Understanding stopped before it finished"
    if _MOTIVI_SENZA_SOGGETTO.match(m):

        m = "la comprensione " + m[:1].lower() + m[1:]
    return _maiuscola(m)


def _motivo_frase(quando: str, motivo: str) -> str:
    ""

    m = _motivo_normale(motivo)
    if not quando:
        return m
    if _MINUSCOLE.match(m):
        m = m[:1].lower() + m[1:]
    return f"{_maiuscola(quando)}, {m}"


def _motivo_fermo(com: dict) -> str:
    esito = _dict(com.get("esito"))
    return _motivo_normale(str(esito.get("motivo") or ""))


def _virgolette(titolo: str) -> str:
    ""
    t = str(titolo or "").strip()
    if t.startswith("«") and t.endswith("»"):
        t = t[1:-1].strip()
    return f"«{t[:40]}{'…' if len(t) > 40 else ''}»"


def _da_iso(valore) -> datetime.datetime | None:
    try:
        return datetime.datetime.fromisoformat(str(valore or ""))
    except ValueError:
        return None


def _per_te(spunti: list, cfg: dict) -> list:
    ""


    da_capire = [
        v
        for v in spunti
        if v.get("fase") == "da_capire"
        and not ((v.get("lavorazione") or {}).get("comprensione") or {}).get("aperta")
    ]
    if not cfg.get("acceso") or not isinstance(cfg.get("aspettano_te"), list):


        fuori = set(cfg.get("fermi_a_vuoto") or []) | set(cfg.get("senza_accesso") or [])
        return [
            v["id"]
            for v in spunti
            if v.get("fase") == "da_capire"
            and v["id"] not in fuori
            and (v.get("_interno") or {}).get("attesa") not in ("vietato", "sparito", "a_vuoto")
        ]


    return [v["id"] for v in da_capire if (v.get("_interno") or {}).get("attesa") == "aspetta_si"]


def _giro_legge_il_dm(cfg: dict) -> bool:
    ""



    tick = _da_iso(cfg.get("ultimo_tick"))
    if tick is None or cfg.get("leggi_dm") is False:
        return False
    return datetime.datetime.now() - tick <= datetime.timedelta(minutes=TICK_VIVO_MIN)


def _errore_del_giro(testo: str) -> str:
    ""

    t = _parole_semplici(testo).strip()
    t = re.sub(r"^Adesso\s+", "", t)
    t = re.sub(
        r",? quindi non lo capisco ancora\.?$",
        ", fino ad allora non capisco niente. Poi riparto da solo",
        t,
    )
    return _maiuscola(t)


def _ritmo(file_fonte: str, spunti: list) -> dict:
    ""




    cfg = _cfg()
    acceso = bool(cfg.get("acceso"))
    titoli = {v["id"]: (v.get("titolo") or v["id"]) for v in spunti}
    in_corso = [
        v["id"]
        for v in spunti
        if ((v.get("lavorazione") or {}).get("comprensione") or {}).get("aperta")
    ]
    fermi = [i for i in (cfg.get("fermi") or []) if i in titoli]
    righe = []
    adesso = datetime.datetime.now()
    n = _intervallo_minuti(cfg)
    tick = _da_iso(cfg.get("ultimo_tick"))
    tick_vivo = _giro_legge_il_dm(cfg)
    frase = TESTI["ritmo_spento"]


    letto = _quando(
        str(
            _dict(
                _leggi(
                    os.path.join(
                        os.path.dirname(os.path.dirname(file_fonte)), "ultima-rilettura.json"
                    )
                )
            ).get("quando")
            or ""
        )
    )
    righe_letto = [TESTI["ritmo_letto"].format(quando=letto)] if letto else []
    if acceso and tick_vivo:
        frase = TESTI["ritmo_acceso_sempre"].format(n=n)
        righe += righe_letto
        if cfg.get("ultimo_scarico"):
            righe.append(TESTI["ritmo_scarico"])
    elif acceso:
        frase = TESTI["ritmo_acceso"].format(n=n)
        righe += righe_letto
        if cfg.get("leggi_dm") is False:
            righe.append(TESTI["ritmo_dm_spento"])
        else:
            righe.append(
                _frase(
                    TESTI["ritmo_tick_fermo"], quando=_quando(tick.isoformat(timespec="seconds"))
                )
                if tick
                else TESTI["ritmo_tick_mai"]
            )
        if cfg.get("ultimo_scarico"):
            righe.append(TESTI["ritmo_scarico"])
    if in_corso:
        righe.append(
            TESTI["ritmo_adesso"].format(
                cosa=", ".join(_virgolette(titoli[i]) for i in in_corso[:3])
                + (f" and {len(in_corso) - 3} more" if len(in_corso) > 3 else "")
            )
        )

    fermi_a_te = [
        i
        for i in fermi
        if i not in (cfg.get("si_di_owner") or []) and i not in (cfg.get("fermi_a_vuoto") or [])
    ]
    if acceso and fermi_a_te:

        righe.append(
            TESTI["ritmo_fermo_uno"].format(titolo=_virgolette(titoli[fermi_a_te[0]]))
            if len(fermi_a_te) == 1
            else TESTI["ritmo_fermi"].format(n=len(fermi_a_te))
        )


    if acceso and cfg.get("ultimo_errore"):
        righe.append(_errore_del_giro(str(cfg["ultimo_errore"])))
    per_te = _per_te(spunti, cfg) if acceso else []
    a_te = [i for i in per_te if i not in fermi]
    voci = {v["id"]: v for v in spunti}

    def attesa(i):
        return (voci[i].get("_interno") or {}).get("attesa", "")

    if a_te:
        cosa = _quanti_per_tipo([voci[i] for i in a_te])
        righe.append(
            (TESTI["ritmo_a_te_uno"] if len(a_te) == 1 else TESTI["ritmo_a_te"]).format(cosa=cosa)
        )

    si = (
        [
            i
            for i in (cfg.get("si_di_owner") or [])
            if i in voci
            and voci[i].get("fase") == "da_capire"
            and i not in per_te
            and i not in in_corso

            and attesa(i) == "si"
        ]
        if acceso
        else []
    )
    if si:
        cosa = _quanti_per_tipo([voci[i] for i in si])
        righe.append(
            (TESTI["ritmo_si_uno"] if len(si) == 1 else TESTI["ritmo_si"]).format(cosa=cosa)
        )

    scendono = (
        [
            v["id"]
            for v in spunti
            if v.get("fase") == "da_capire"
            and not v.get("visto")
            and v["id"] not in per_te
            and v["id"] not in in_corso
            and v["id"] not in si
            and attesa(v["id"])
            not in ("fermo", "vietato", "sparito", "aspetta_si", "capisco", "a_vuoto", "sceso")
        ]
        if acceso
        else []
    )
    a_vuoto = [v["id"] for v in spunti if acceso and attesa(v["id"]) == "a_vuoto"]
    if a_vuoto:
        cosa = _quanti_per_tipo([voci[i] for i in a_vuoto])
        chiave = "ritmo_a_vuoto_uno" if len(a_vuoto) == 1 else "ritmo_a_vuoto"
        if _riparte_da_solo():
            chiave += "_acceso"
        righe.append(TESTI[chiave].format(cosa=cosa))
    vietati = [v["id"] for v in spunti if acceso and attesa(v["id"]) == "vietato"]
    if vietati:
        cosa = _quanti_per_tipo([voci[i] for i in vietati])
        righe.append(
            (TESTI["ritmo_vietato_uno"] if len(vietati) == 1 else TESTI["ritmo_vietati"]).format(
                cosa=cosa
            )
        )
    if scendono:
        cosa = _quanti_per_tipo([voci[i] for i in scendono])
        righe.append(
            (TESTI["ritmo_scendono_uno"] if len(scendono) == 1 else TESTI["ritmo_scendono"]).format(
                cosa=cosa
            )
        )
    return {
        "acceso": acceso,
        "frase": frase,
        "righe": righe,

        "pulsante": TESTI["pulsante_a_te"].format(cosa=_quanti_per_tipo([voci[i] for i in per_te]))
        if per_te
        else "",
        "pulsante_aiuto": TESTI["aiuto_pulsante_a_te"] if per_te else "",
        "in_corso": in_corso,
        "fermi": fermi,

        "anche_ad_app_chiusa": bool(
            acceso
            and tick is not None
            and adesso - tick <= datetime.timedelta(minutes=TICK_VIVO_MIN)
        ),
        "ultimo_tick": str(cfg.get("ultimo_tick") or ""),
    }


def _quanti_per_tipo(voci: list) -> str:
    ""

    gruppi: dict[str, int] = {}
    for v in voci:
        tipo = str(v.get("tipo") or "")
        piattaforma = str(v.get("piattaforma") or "")
        gruppi[(tipo, piattaforma)] = gruppi.get((tipo, piattaforma), 0) + 1
    parti = []
    for (tipo, piattaforma), n in sorted(gruppi.items(), key=lambda x: -x[1]):
        nome = TIPI.get(tipo, (tipo or "item",))[0].lower() if n == 1 else PLURALI.get(tipo, tipo)
        dove = f" {piattaforma}" if piattaforma and piattaforma != "Web" else ""
        if tipo == "video" and piattaforma == "Instagram":
            nome, dove = "reel", ""
        parti.append(f"{n} {nome}{dove}")
    if len(parti) > 1:
        return ", ".join(parti[:-1]) + " and " + parti[-1]
    return parti[0] if parti else ""


def _segni_da_capire(spunti: list, cfg: dict) -> None:
    ""






    acceso = bool(cfg.get("acceso"))
    for v in spunti:
        i = v.get("_interno") or {}
        att = i.get("attesa", "")
        if i.get("in_scrittura") or att == "capisco":
            capito = i.get("in_scrittura") or i.get("dossier")
            v["badge"] = {
                "parola": TESTI["segno_capito" if capito else "segno_lo_capisco"],
                "salute": "neutra",
                "aiuto": i.get("frase_capito") if capito else TESTI["segno_lo_capisco_aiuto"],
            }
            continue
        if v.get("fase") != "da_capire" or not acceso:
            continue
        b = v.get("badge")
        if b and b.get("parola") in (FRASI["vietato"], FRASI["sparito"]):
            continue
        if att == "a_vuoto":
            v["badge"] = {
                "parola": TESTI["segno_a_vuoto"],
                "salute": "neutra",
                "aiuto": TESTI[
                    "segno_a_vuoto_aiuto_acceso" if _riparte_da_solo() else "segno_a_vuoto_aiuto"
                ],
            }
        elif att == "aspetta_si":
            v["badge"] = {
                "parola": TESTI["segno_a_te"],
                "salute": "attenzione",
                "aiuto": TESTI["segno_a_te_aiuto"],
            }
        elif att == "si":
            v["badge"] = {
                "parola": TESTI["segno_si"],
                "salute": "neutra",
                "aiuto": TESTI["segno_si_aiuto"],
            }
        elif att == "fermo":
            v["badge"] = {
                "parola": TESTI["segno_fermo"],
                "salute": "attenzione",
                "aiuto": _aiuto_fermo(i),
            }
        elif att in ("scende", "riprovo") and not v.get("visto"):
            v["badge"] = {
                "parola": TESTI["segno_in_arrivo"],
                "salute": "neutra",
                "aiuto": TESTI["segno_in_arrivo_aiuto"],
            }
        elif att in ("sceso", "riprovo", "scende"):
            v["badge"] = {
                "parola": TESTI["segno_sceso"],
                "salute": "neutra",
                "aiuto": _frase(TESTI["segno_sceso_aiuto"], quando=_quando(i.get("sceso_quando"))),
            }


def _segno(v: dict) -> dict:
    ""



    i = v.get("_interno") or {}
    att = i.get("attesa", "")
    L = v.get("lavorazione") or {}
    fase = v.get("fase") or ""

    passo = str(L.get("passo") or "")

    def s(tipo, parola, aiuto, salute="neutra"):
        return {"tipo": tipo, "parola": parola, "aiuto": aiuto, "salute": salute}



    u = L.get("uscita") or {}
    if passo in USCITE and u.get("frase") and not (L.get("adesso") or {}).get("pulsante"):
        return s("uscito", _parola_uscita(u), str(u["frase"]))
    if fase in FUORI_DAL_PERCORSO:
        return s("", "", "")
    if fase == "da_capire":
        quando_fermo = _quando(i.get("fermo_quando"))
        if att == "vietato":
            return s("fermo", FRASI["vietato"], TESTI["segno_vietato_aiuto"], "attenzione")
        if att == "sparito":
            return s("fermo", FRASI["sparito"], TESTI["segno_sparito_aiuto"], "attenzione")
        if att == "capisco":
            if i.get("dossier"):

                aiuto = _frase(
                    TESTI["segno_capito_scrivo"], quando=_quando(i.get("dossier_quando"))
                )
                return s("capisco", TESTI["segno_capito"], aiuto)
            aiuto = _frase(TESTI["segno_capisco_aiuto"], quando=_quando(i.get("aperta_quando")))
            return s("capisco", TESTI["segno_capisco"], aiuto)
        if att == "a_vuoto":
            chiave = "segno_a_vuoto_aiuto_acceso" if _riparte_da_solo() else "segno_a_vuoto_aiuto"
            return s("fermo", TESTI["segno_a_vuoto"], TESTI[chiave], "attenzione")
        if att == "si":
            return s("scende", TESTI["segno_si"], TESTI["segno_si_aiuto"])
        if att == "aspetta_si":

            return s("da_far_partire", TESTI["segno_a_te"], TESTI["segno_a_te_aiuto"])
        if att == "fermo":
            return s("fermo", TESTI["segno_fermo"], _aiuto_fermo(i), "attenzione")
        if att == "riprovo":
            aiuto = TESTI["segno_riprovo_aiuto"].format(
                motivo=_motivo_frase(quando_fermo, i.get("motivo"))
            )
            return s("capisco", TESTI["segno_riprovo"], aiuto)
        if att == "scende":
            return s("scende", TESTI["segno_scende"], TESTI["segno_scende_aiuto"])
        if att == "sceso":
            aiuto = _frase(TESTI["segno_sceso_aiuto"], quando=_quando(i.get("sceso_quando")))
            return s("capisco", TESTI["segno_sceso"], aiuto)

        return s("tocca_te", TESTI["segno_tocca_te"], TESTI["segno_spento_aiuto"], "accento")
    if i.get("in_scrittura"):
        return s(
            "capisco",
            TESTI["segno_capito"],
            i.get("frase_capito") or TESTI["riquadro_perche_in_scrittura"],
        )
    tocca = L.get("tocca") or ""
    perche = L.get("perche") or {}
    if i.get("perche_mancante"):


        chiave = (
            "segno_manca_perche_aiuto" if _ritmo_acceso() else "segno_manca_perche_aiuto_spento"
        )
        return s("capisco", TESTI["segno_capito"], TESTI[chiave])
    if (L.get("rilettura") or {}).get("aperta"):
        return s("lavora", TESTI["segno_lavora_rileggo"], L.get("tocca_frase") or "")
    if L.get("stato_scheda") == SCHEDA_STATO["in_trascrizione"]:
        return s("lavora", TESTI["segno_lavora_trascrivo"], SCHEDA_STATO["in_trascrizione"])



    if passo in PASSI6[1:] or passo in USCITE:
        return _segno_dal_passo(L, i, s)
    if tocca in ("sessione", "agente"):
        return s("lavora", TESTI["segno_lavora"], L.get("tocca_frase") or "")
    return s("", "", "")


def _parola_uscita(u: dict) -> str:
    ""
    tipo = str(u.get("tipo") or "")
    if tipo == "cosa_da_fare":
        task = u.get("task") or {}
        if not task:
            return TESTI["segno_uscito_da_fare"]
        if task.get("stato") == "eliminata":

            return TESTI["segno_uscito_eliminata"]
        if task.get("dove_frase") == TESTI["uscita_task_attivita"]:
            return TESTI["segno_uscito_attivita"]
        return TESTI["segno_uscito_clickup"]
    return TESTI.get(f"segno_uscito_{tipo}", "")


def _domanda_strada(sc: dict) -> str:
    ""

    strada = str(sc.get("strada") or "")
    if strada == "cosa_da_fare":
        if sc.get("delicato"):
            return TESTI["segno_strada_cosa_da_fare"]
        if sc.get("chi") == "owner":
            return TESTI[
                "segno_strada_attivita" if _task_accese(sc) else "segno_strada_cosa_da_fare"
            ]
        return TESTI["segno_strada_team"]
    return TESTI.get(f"segno_strada_{strada}", "") if strada else ""


def _con_domanda(segno: dict, sc: dict, domanda: str, accanto: str) -> dict:
    ""


    corta = domanda
    if str(sc.get("strada") or "") == "riferimento":
        corta = TESTI["segno_strada_riferimento_corta"]
    elif domanda == TESTI["segno_strada_team"]:
        corta = TESTI["segno_strada_team_corta"]
    parola = (
        TESTI["segno_domanda_accanto"].format(domanda=domanda, accanto=accanto)
        if accanto
        else domanda
    )
    return {
        **segno,
        "parola": parola,
        "domanda": domanda,
        "domanda_corta": corta,
        "accanto": accanto,
    }


def _segno_dal_passo(L: dict, i: dict, s) -> dict:
    ""

    passo = str(L.get("passo") or "")
    a = L.get("adesso") or {}
    sc = L.get("scope") or {}
    cambio = L.get("cambio_scope") or {}
    chi = a.get("chi")
    salute = "accento" if i.get("nuovo") else "neutra"
    if L.get("task_manca"):

        p = a.get("pulsante") or {}
        if p.get("verbo") == "crea_task":
            return s("task_da_creare", TESTI["segno_task_da_creare"], p.get("aiuto") or "", salute)
        aiuto = TESTI[
            "segno_da_fare_aiuto" if sc.get("chi") == "owner" else "segno_da_fare_aiuto_team"
        ]
        return s("da_fare", TESTI["segno_da_fare"], aiuto)
    if (
        chi == "sessione"
        and passo in ("scope", "contesto", "ricerca")
        and i.get("agente_aperto_quando")
    ):


        parola = _frase(
            TESTI["segno_agente_aperto"], quando=_quando_corto(i["agente_aperto_quando"])
        )
        return s("agente_aperto", parola, a.get("frase") or "")
    if chi == "sessione" or (chi == "sistema" and passo != "scope"):
        return s("lavora", TESTI["segno_lavora"], a.get("frase") or "")
    if chi != "te":
        return s("", "", "")
    if cambio.get("con_agente") or cambio.get("con_lavoro"):

        return s("da_dire", TESTI["segno_da_dire"], a.get("frase") or "")
    if cambio.get("da_decidere"):
        aiuto = TESTI["segno_da_scegliere_aiuto" + _cambio_chi(cambio)]
        return s("da_scegliere", TESTI["segno_da_scegliere"], aiuto, salute)
    if passo in USCITE:
        p = a.get("pulsante") or {}
        if p.get("verbo") == "crea_task":
            return s("task_da_creare", TESTI["segno_task_da_creare"], p.get("aiuto") or "", salute)
        return s("", "", "")
    if passo == "scope":
        pezzi = [_maiuscola(sc.get("strada_frase") or "")]
        n = len(sc.get("domande") or []) + len(sc.get("altre_domande") or [])
        if n:
            pezzi.append(_n_domande(n))
        aiuto = " · ".join(x for x in pezzi if x)
        domanda = _domanda_strada(sc)
        if not i.get("nuovo"):
            q = _quando(i.get("nuovo_quando"))
            if q:
                aiuto = _frase(TESTI["segno_da_confermare_aiuto"], quando=q, strada=aiuto)
            if not domanda:
                return s("da_confermare", TESTI["segno_da_confermare"], aiuto)

            qc = _quando_corto(i.get("nuovo_quando"))
            accanto = _frase(TESTI["segno_dal"], quando=qc) if qc else ""
            return _con_domanda(s("da_confermare", "", aiuto), sc, domanda, accanto)
        if not domanda:
            return s("da_confermare", TESTI["segno_nuovo_da_confermare"], aiuto, "accento")

        return _con_domanda(s("da_confermare", "", aiuto, "accento"), sc, domanda, TESTI["nuovo"])
    if a.get("salute") == "attenzione":
        return s("fermo", TESTI["segno_si_e_fermato"], a.get("frase") or "", "attenzione")
    if (a.get("pulsante") or {}).get("verbo") in ("vai", "vai_lavoro"):

        return s("domanda", TESTI["segno_ti_aspetta"], a.get("frase") or "", salute)
    domande = a.get("domande") or []
    if domande:
        n = len(domande)
        parola = TESTI["segno_una_domanda"] if n == 1 else TESTI["segno_domande"].format(n=n)
        return s("domanda", parola, a.get("frase") or "", salute)
    if (a.get("pulsante") or {}).get("verbo") == "letto_studio":

        return s("da_leggere", TESTI["segno_da_leggere"], TESTI["segno_da_leggere_aiuto"], salute)
    if passo in ("contesto", "ricerca"):
        return s(
            "da_far_partire", TESTI["segno_da_far_partire"], TESTI[f"segno_{passo}_aiuto"], salute
        )
    if passo == "implementazione":
        return s("da_avviare", TESTI["segno_da_avviare"], TESTI["segno_da_avviare_aiuto"], salute)
    if passo == "test":
        return s("ritorno", TESTI["segno_ritorno"], TESTI["segno_ritorno_aiuto"], salute)
    return s("", "", "")


def _lettura_non_riuscita(casa: str, letto_quando: str) -> bool:
    ""

    try:
        with open(os.path.join(casa, "giro-tick.log"), "rb") as fh:
            fh.seek(0, os.SEEK_END)
            fh.seek(max(0, fh.tell() - 16384))
            coda_log = fh.read().decode("utf-8", "replace")
    except OSError:
        return False
    for riga in reversed(coda_log.splitlines()):
        if " giro: dm " not in riga:
            continue
        quando = riga.split(" ", 1)[0]
        if "giro: dm non letto" not in riga or "già rileggendo" in riga:
            return False
        return quando[:19] > str(letto_quando or "")[:19]
    return False



TESTA_MAX = 70


def _la_prima_che_sta(*frasi: str) -> str:
    ""
    candidate = [f for f in frasi if f]
    for f in candidate:
        if len(f) <= TESTA_MAX:
            return f
    return min(candidate, key=len) if candidate else ""


def _quanti_corto(voci: list, piattaforma: bool = True) -> str:
    ""

    tipi = {(str(v.get("tipo") or ""), str(v.get("piattaforma") or "")) for v in voci}
    n = len(voci)
    if len(tipi) == 1 and piattaforma:
        return _quanti_per_tipo(voci)
    if len({t for t, _ in tipi}) == 1:
        tipo, pf = next(iter(tipi))
        if tipo == "video" and pf == "Instagram":
            return f"{n} reel"
        nome = TIPI.get(tipo, (tipo or "item",))[0].lower() if n == 1 else PLURALI.get(tipo, tipo)
        return f"{n} {nome}"
    return "1 item" if n == 1 else f"{n} items"


def _di_quando(quando: str) -> str:
    ""
    return f"from {quando}" if quando else ""


def _testa(spunti: list, cfg: dict, file_fonte: str, frase_aggiornato: str) -> dict:
    ""


    casa = os.path.dirname(os.path.dirname(file_fonte))
    try:
        ril = json.loads(Path(casa, "ultima-rilettura.json").read_text(encoding="utf-8"))
        ril = ril if isinstance(ril, dict) else {}
    except (OSError, ValueError, TypeError):
        ril = {}
    letto = str(ril.get("quando") or "")

    def att(v):
        return (v.get("_interno") or {}).get("attesa", "")

    def interno(v):
        return v.get("_interno") or {}

    in_moto = [
        v
        for v in spunti
        if att(v) in ("scende", "sceso", "capisco") or interno(v).get("in_scrittura")
    ]


    aspettano = [v for v in spunti if att(v) in ("aspetta_si", "spento")]
    col_si = [v for v in spunti if att(v) == "si"]

    fermi = [v for v in spunti if att(v) in ("fermo", "sparito")]
    a_vuoto = [v for v in spunti if att(v) == "a_vuoto"]
    vietati = [v for v in spunti if att(v) == "vietato"]


    frase_moto, chiusa, avanzamento = "", "", ""
    n = len(in_moto)
    if n:
        cosa = _quanti_per_tipo(in_moto)
        non_scesi = [v for v in in_moto if not interno(v).get("sceso")]
        in_comprensione = [v for v in in_moto if interno(v).get("aperta_vera")]
        moto_voci = in_moto
        if non_scesi:
            k = n - len(non_scesi)
            if n == 1:
                chiave = "testa_scende_uno"
                chiusa = TESTI["testa_lo_capisco"]
            else:
                chiave = (
                    "testa_scendono_k1"
                    if k == 1
                    else ("testa_scendono" if k else "testa_scendono_zero")
                )
                chiusa = TESTI["testa_li_capisco"]
        elif in_comprensione:


            per_id_moto = {v["id"]: v for v in spunti}
            ids_gruppo = []
            for v in in_comprensione:
                for i in interno(v).get("gruppo") or [v["id"]]:
                    if i in per_id_moto and i not in ids_gruppo:
                        ids_gruppo.append(i)
            gruppo = [per_id_moto[i] for i in ids_gruppo]
            n, cosa, moto_voci = len(gruppo), _quanti_per_tipo(gruppo), gruppo
            k = sum(1 for v in gruppo if interno(v).get("dossier") or v.get("fase") != "da_capire")
            if n > 1 and k == n:
                chiave = "testa_capiti_tutti"
            elif n == 1 and k == 1:

                chiave = "testa_capito_uno"
            elif n > 1 and k:
                chiave = "testa_capisco_k1" if k == 1 else "testa_capisco"
            elif n > 1:
                chiave = "testa_capisco_zero"
            else:
                chiave = "testa_capisco_uno"
            chiusa = TESTI["testa_tocca_te"]
        else:
            k = 0
            chiave = "testa_scesi" if n > 1 else "testa_sceso_uno"
        frase_moto = _frase(TESTI[chiave], cosa=cosa, k=k)
        frase_moto_corta = _frase(
            TESTI.get(chiave + "_corta", TESTI[chiave]), cosa=_quanti_corto(moto_voci), k=k
        )
        if n > 1 and (non_scesi or in_comprensione):
            avanzamento = f"{k} su {n}"
    frase_si = frase_si_corta = ""
    if aspettano:
        chiave_si = "testa_aspettano_si" if len(aspettano) > 1 else "testa_aspetta_si"
        frase_si = _frase(TESTI[chiave_si], cosa=_quanti_per_tipo(aspettano))
        frase_si_corta = _frase(TESTI[chiave_si], cosa=_quanti_corto(aspettano, piattaforma=False))
        frase_si_minima = (
            TESTI["testa_altro_si"]
            if len(aspettano) == 1
            else TESTI["testa_altri_si"].format(n=len(aspettano))
        )



    a_te = _nuovi_per_te(spunti)
    frase_te, frase_te_corta, frase_te_minima = _frasi_per_te(spunti)
    tutti = len(a_te) + len(aspettano)
    frase_tutti = TESTI["testa_tutti_uno"] if tutti == 1 else TESTI["testa_tutti"].format(n=tutti)
    non_letto = _lettura_non_riuscita(casa, letto)
    if non_letto:
        frase = (
            TESTI["testa_dm_non_letto"].format(di_quando=_di_quando(_quando(letto)))
            if letto
            else TESTI["testa_dm_non_letto_mai"]
        )
        salute = "attenzione"
    elif aspettano:

        if chiusa == TESTI["testa_tocca_te"]:
            chiusa = ""


        con_te = (
            [
                f"{frase_moto}. {frase_te}. {frase_si}" if n else "",
                f"{frase_moto_corta}. {frase_te}. {frase_si}" if n else "",
                f"{frase_moto_corta}. {frase_te_corta}. {frase_si_corta}" if n else "",

                f"{frase_moto_corta}. {frase_te_corta}. {frase_si_minima}" if n else "",
                f"{frase_moto_corta}. {frase_te_minima}. {frase_si_minima}" if n else "",

                f"{frase_moto}. {frase_tutti}" if n else "",
                f"{frase_moto_corta}. {frase_tutti}" if n else "",
            ]
            if a_te
            else []
        )
        con_te_senza_moto = (
            [
                f"{frase_te}. {frase_si}",
                f"{frase_te_corta}. {frase_si}",
                f"{frase_te_corta}. {frase_si_corta}",
                f"{frase_te_corta}. {frase_si_minima}",
                f"{frase_te_minima}. {frase_si_minima}",
            ]
            if a_te
            else []
        )
        if n and a_te:
            frase = _la_prima_che_sta(
                *[x for x in con_te if len(x) <= TESTA_MAX],
                *con_te_senza_moto,
            )
        elif n:
            frase = _la_prima_che_sta(
                f"{frase_moto}. {chiusa}. {frase_si}" if chiusa else "",
                f"{frase_moto}. {frase_si}",
                f"{frase_moto_corta}. {frase_si}",
                f"{frase_moto}. {frase_si_corta}",
                f"{frase_moto_corta}. {frase_si_corta}",
                f"{frase_moto_corta}. {frase_si_minima}",
            )
        elif a_te:
            frase = _la_prima_che_sta(*con_te_senza_moto)
        else:
            frase = _la_prima_che_sta(frase_si, frase_si_corta)
        salute = "in_corso" if n else "ok"
    elif n and a_te:

        frase = _la_prima_che_sta(
            *[
                x
                for x in (
                    f"{frase_moto}. {frase_te}",
                    f"{frase_moto_corta}. {frase_te}",
                    f"{frase_moto_corta}. {frase_te_corta}",
                    f"{frase_moto_corta}. {frase_te_minima}",
                )
                if len(x) <= TESTA_MAX
            ],
            frase_te,
            frase_te_corta,
            frase_te_minima,
        )
        salute = "in_corso"
    elif n:
        frase = _la_prima_che_sta(
            f"{frase_moto}. {chiusa}" if chiusa else "",
            frase_moto,
            frase_moto_corta,
        )
        salute = "in_corso"
    elif a_te:
        frase = _la_prima_che_sta(frase_te, frase_te_corta, frase_te_minima)
        salute = "ok"
    else:
        frase = (
            _frase(TESTI["testa_dm_letto"], quando=_quando(letto)) if letto else frase_aggiornato
        )
        salute = "ok"
    uno = len(aspettano) == 1
    acceso = bool(cfg.get("acceso"))


    pulsante_riga = (
        (TESTI["testa_pulsante_uno"] if uno else TESTI["testa_pulsante"]) if aspettano else ""
    )
    pulsante_si = (
        _frase(TESTI["pulsante_a_te"], cosa=_quanti_per_tipo(aspettano)) if aspettano else ""
    )


    sotto_si = (
        (
            TESTI["testa_sotto_uno"]
            if uno
            else TESTI["testa_sotto_acceso" if acceso else "testa_sotto_spento"]
        )
        if aspettano
        else ""
    )
    aiuto_si = sotto_si
    pulsante, aiuto, verbo = pulsante_si, aiuto_si, "capisci tutte"
    if non_letto:


        pulsante, aiuto, verbo = TESTI["testa_rileggi"], TESTI["testa_rileggi_aiuto"], "rileggi"

    def titoli(voci):
        return [_virgolette(v.get("titolo") or v.get("id") or "") for v in voci[:10]]

    dettagli = []
    righe_dm = []
    if non_letto:
        righe_dm.append(frase)
    nuove = [x for x in (ril.get("nuove") or []) if isinstance(x, dict)]
    per_id = {v["id"]: v for v in spunti}
    if nuove:
        quante = (
            TESTI["spunto_nuovo"] if len(nuove) == 1 else TESTI["spunti_nuovi"].format(n=len(nuove))
        )
        righe_dm.append(
            _frase(
                TESTI["dettagli_nuovi"],
                cosa=_maiuscola(quante),
                quando=_quando(str(ril.get("quando_esito") or letto)),
            )
        )
        righe_dm += titoli([per_id[x["id"]] for x in nuove if x.get("id") in per_id])
    elif letto:
        righe_dm.append(TESTI["dettagli_niente_di_nuovo"])
    if letto:

        righe_dm.append(
            _frase(
                TESTI["dettagli_letto_ultima" if non_letto else "dettagli_letto"],
                quando=_quando(letto),
            )
        )
    if righe_dm:
        dettagli.append({"titolo": TESTI["dettagli_dm"], "righe": righe_dm})
    righe_adesso = [". ".join(x for x in (frase_moto, chiusa) if x)] if frase_moto else []
    if not acceso:
        righe_adesso.append(TESTI["ritmo_spento"])
    elif _giro_legge_il_dm(cfg):

        righe_adesso.append(TESTI["ritmo_acceso_sempre"].format(n=_intervallo_minuti(cfg)))
    else:
        righe_adesso.append(TESTI["ritmo_acceso"])
    if acceso and cfg.get("ultimo_errore"):
        righe_adesso.append(_errore_del_giro(str(cfg["ultimo_errore"])))
    dettagli.append({"titolo": TESTI["dettagli_adesso"], "righe": righe_adesso})
    if a_te:
        dettagli.append(
            {
                "titolo": TESTI["dettagli_a_te"],
                "righe": [f"{frase_te}. {_riga_nuovi(a_te)}"] + titoli(a_te),
            }
        )
    if aspettano:
        dettagli.append(
            {
                "titolo": TESTI["dettagli_aspettano_si"],
                "righe": [
                    f"{_maiuscola(_quanti_per_tipo(aspettano))}. "
                    + TESTI[
                        "dettagli_aspetta_si_riga"
                        if len(aspettano) == 1
                        else "dettagli_aspettano_si_riga"
                    ]
                ]
                + titoli(aspettano),


                "pulsante": pulsante_si if verbo != "capisci tutte" else "",
                "pulsante_verbo": "capisci tutte" if verbo != "capisci tutte" else "",
                "pulsante_aiuto": aiuto_si if verbo != "capisci tutte" else "",
            }
        )
    if col_si:
        dettagli.append(
            {
                "titolo": TESTI["dettagli_si"],
                "righe": [
                    f"{_maiuscola(_quanti_per_tipo(col_si))}. "
                    + TESTI["dettagli_si_riga_uno" if len(col_si) == 1 else "dettagli_si_riga"]
                ]
                + titoli(col_si),
            }
        )
    if fermi:
        dettagli.append(
            {
                "titolo": TESTI["dettagli_fermi"],
                "righe": [

                    TESTI["dettagli_fermo_riga"].format(
                        titolo=_virgolette(v.get("titolo") or v["id"]),
                        motivo=_motivo_normale(interno(v).get("motivo"))
                        + (
                            ". "
                            + _motivo_frase(
                                TESTI["dettagli_motivo_ultimo"], interno(v).get("motivo_ultimo")
                            )
                            if interno(v).get("motivo_ultimo")
                            else ""
                        ),
                    )
                    if att(v) == "fermo"
                    else _frase(
                        TESTI["dettagli_sparito_riga"],
                        titolo=_virgolette(v.get("titolo") or v["id"]),
                    )
                    for v in fermi[:10]
                ],
            }
        )
    if a_vuoto:
        dettagli.append(
            {
                "titolo": TESTI["dettagli_a_vuoto"],
                "righe": [
                    f"{_maiuscola(_quanti_per_tipo(a_vuoto))}. "
                    + TESTI[
                        (
                            "dettagli_a_vuoto_riga_uno"
                            if len(a_vuoto) == 1
                            else "dettagli_a_vuoto_riga"
                        )
                        + ("_acceso" if _riparte_da_solo() else "")
                    ]
                ]
                + titoli(a_vuoto),
            }
        )
    if vietati:
        dettagli.append(
            {
                "titolo": TESTI["dettagli_vietati"],
                "righe": [
                    _frase(
                        TESTI["dettagli_vietato_riga"],
                        titolo=_virgolette(v.get("titolo") or v["id"]),
                    )
                    for v in vietati[:10]
                ],
            }
        )
    righe = _righe_testa(
        spunti,
        non_letto=frase if non_letto else "",
        aspettano=aspettano,
        pulsante_si=pulsante_riga,
        sotto_si=sotto_si,
        frase_moto=". ".join(x for x in (frase_moto, chiusa) if x) if frase_moto else "",
        avanzamento=avanzamento,
        quiete=frase if not (non_letto or aspettano or a_te or n) else "",
    )
    return {
        "frase": frase,
        "salute": salute,
        "avanzamento": avanzamento,
        "pulsante": pulsante,
        "pulsante_verbo": verbo,
        "pulsante_aiuto": aiuto,
        "dettagli": dettagli,
        "dettagli_parola": TESTI["testa_dettagli"],
        "rileggi_parola": TESTI["testa_rileggi"],


        "righe": righe,
    }


def _riga(ident: str, frase: str, **altro) -> dict:
    ""


    r = {
        "id": ident,
        "frase": frase,
        "pulsante": "",
        "pulsante_verbo": "",
        "pulsante_aiuto": "",
        "vista": "",

        "gettone": "",
        "sotto": "",
        "ids": [],
        "avanzamento": "",
    }
    r.update(altro)
    return r



GETTONI_VISTA = {"nuovi": "filtri_pronto_nuovi", "di_prima": "filtri_pronto_arretrati"}


def _di_prima_da_confermare(spunti: list) -> list:
    ""

    out = []
    for v in spunti:
        L = v.get("lavorazione") or {}
        segno = v.get("segno") or {}
        if L.get("passo") != "scope" or L.get("task_manca"):
            continue
        if (L.get("adesso") or {}).get("chi") != "te":
            continue
        if segno.get("tipo") == "da_confermare" and segno.get("salute") != "accento":
            out.append(v)
    return out


def _vista(ident: str, voci: list, frase: str) -> dict:
    ""
    uno = len(voci) == 1
    return _riga(
        ident,
        frase,
        pulsante=TESTI["testa_mostramelo" if uno else "testa_mostrameli"],
        vista=ident,
        gettone=TESTI[GETTONI_VISTA[ident]] if ident in GETTONI_VISTA else "",
        ids=[str(v.get("id") or "") for v in voci],
    )


def _righe_testa(
    spunti: list,
    *,
    non_letto: str,
    aspettano: list,
    pulsante_si: str,
    sotto_si: str,
    frase_moto: str,
    avanzamento: str,
    quiete: str,
) -> list[dict]:
    ""


    righe = []
    if non_letto:
        righe.append(
            _riga(
                "dm",
                non_letto,
                pulsante=TESTI["testa_rileggi"],
                pulsante_verbo="rileggi",
                pulsante_aiuto=TESTI["testa_rileggi_aiuto"],
            )
        )
    if aspettano:
        righe.append(
            _riga(
                "aspettano_si",
                _frase(TESTI["testa_leggo_domanda"], cosa=_quanti_per_tipo(aspettano)),
                pulsante=pulsante_si,
                pulsante_verbo="capisci tutte",
                pulsante_aiuto=sotto_si,
                sotto=sotto_si,
                ids=[str(v.get("id") or "") for v in aspettano],
            )
        )
    nuovi, _dopo = _gruppi_per_te(spunti)
    if nuovi:
        chiave = "testa_nuovi_uno" if len(nuovi) == 1 else "testa_nuovi"
        righe.append(_vista("nuovi", nuovi, TESTI[chiave].format(n=len(nuovi))))
    di_prima = _di_prima_da_confermare(spunti)
    if di_prima:
        frase = (
            TESTI["testa_di_prima_uno"]
            if len(di_prima) == 1
            else TESTI["testa_di_prima"].format(n=len(di_prima))
        )
        righe.append(_vista("di_prima", di_prima, frase))


    if frase_moto:
        righe.append(_riga("moto", frase_moto, avanzamento=avanzamento))
    if not righe and quiete:
        righe.append(_riga("quiete", quiete))



    return righe


def _ultima_rilettura(file_fonte: str) -> str:
    ""

    try:
        casa = os.path.dirname(os.path.dirname(file_fonte))
        esito = json.loads(Path(casa, "ultima-rilettura.json").read_text(encoding="utf-8"))
        quando = _quando(str(esito.get("quando") or ""))
    except (OSError, ValueError, TypeError):
        return ""
    return TESTI["ultima_rilettura"].format(quando=quando) if quando else ""



_PASSI_DOPO_SCOPE = ("contesto", "ricerca", "implementazione", "test")



SEGNI_DOPO_SCOPE = (
    "da_dire",
    "da_far_partire",
    "domanda",
    "da_leggere",
    "da_avviare",
    "ritorno",
    "da_scegliere",
    "task_da_creare",
    "fermo",
)


def _solo_domande_di_scope(v: dict) -> bool:
    ""

    L = v.get("lavorazione") or {}
    aperte = [d for d in L.get("domande") or [] if isinstance(d, dict) and not d.get("chiusa")]
    return bool(aperte) and all(d.get("passo") == "scope" for d in aperte)


def _gruppi_per_te(spunti: list) -> tuple[list, list]:
    ""




    nuovi, dopo = [], []
    for v in spunti:
        L = v.get("lavorazione") or {}
        segno = v.get("segno") or {}
        passo = L.get("passo")
        if (L.get("adesso") or {}).get("chi") != "te":
            continue
        if _pronto_quieto(v):


            continue
        if passo == "scope" and not L.get("task_manca"):
            if segno.get("tipo") == "da_confermare" and segno.get("salute") == "accento":
                nuovi.append(v)
        elif passo in (*PASSI6[1:], *USCITE) and segno.get("tipo") in SEGNI_DOPO_SCOPE:
            if segno.get("tipo") == "domanda" and _solo_domande_di_scope(v):
                continue
            dopo.append(v)
    return nuovi, dopo


def _nuovi_per_te(spunti: list) -> list:
    ""
    nuovi, dopo = _gruppi_per_te(spunti)
    return nuovi + dopo


def _aspettano_su_di_te(spunti: list) -> list:
    ""
    return [
        v for v in spunti if (v.get("_interno") or {}).get("attesa") in ("aspetta_si", "spento")
    ]


def _frasi_per_te(spunti: list) -> tuple[str, str, str]:
    ""


    nuovi, dopo = _gruppi_per_te(spunti)
    if not (nuovi or dopo):
        return "", "", ""
    lunghe, corte = [], []
    if nuovi:
        uno = len(nuovi) == 1
        lunghe.append(TESTI["testa_nuovi_uno" if uno else "testa_nuovi"].format(n=len(nuovi)))
        corte.append(TESTI["testa_nuovi_corta"].format(n=len(nuovi)))
    if dopo:
        tipi = {(v.get("segno") or {}).get("tipo") for v in dopo}
        uno = len(dopo) == 1
        tipo = tipi.pop() if len(tipi) == 1 else "misti"
        chiave = f"testa_dopo_{tipo}" + ("_uno" if uno else "")
        lunghe.append(TESTI[chiave].format(n=len(dopo)))
        corta = f"testa_dopo_{tipo}_corta"
        corte.append(TESTI[corta if corta in TESTI and not uno else chiave].format(n=len(dopo)))
    tot = len(nuovi) + len(dopo)
    minima = TESTI["testa_altro_a_te"] if tot == 1 else TESTI["testa_altri_a_te"].format(n=tot)
    return _maiuscola(", ".join(lunghe)), _maiuscola(", ".join(corte)), minima


def _riga_nuovi(voci: list) -> str:
    ""

    tipi = []
    for v in voci:
        t = (v.get("segno") or {}).get("tipo") or ""
        if t and t not in tipi:
            tipi.append(t)
    if tipi == ["da_confermare"]:
        return TESTI["dettagli_a_te_riga"]
    nomi = [TESTI[f"attesa_{t}"] for t in tipi if f"attesa_{t}" in TESTI]
    if not nomi:
        return TESTI["dettagli_a_te_riga"]
    cosa = nomi[0] if len(nomi) == 1 else ", ".join(nomi[:-1]) + " and " + nomi[-1]
    return TESTI["dettagli_a_te_misti"].format(cosa=cosa)


def _aspettano_te_nuovi(spunti: list) -> int:
    ""

    return len(_nuovi_per_te(spunti)) + len(_aspettano_su_di_te(spunti))










STRADE_LISTA = ("riferimento", "studio", "sviluppo")

VIA_LISTA = "lista "

GRUPPI_A_VISTA = 10



DUBBI_IN_PIU = (
    r"\bnon (lo )?so\b",
    r"\bnon sono sicur",
    r"\bnon ne sono sicur",
    r"\bboh\b",
    # English
    r"\bi don'?t know\b",
    r"\bnot sure\b",
    r"\bno idea\b",
)


PERSONA_FORME = (
    r"@\w",
    r"\b(lo|la|li|le|ne) (potrebbe|potrebbero|puo|possono|deve|devono|dovrebbe|dovrebbero) (fare|seguire|gestire|occupar)",
    r"\b(fallo|falla|falli|fatelo|farlo|farla|farli|fargli|fare) fare a\b",
    r"\bchied(i|ere|o|iamo|erlo|erla) a\b",
    r"\b(insieme|assieme) (a|al|alla|con)\b",
    r"\b(il|al|del|col|con il|dal|per il) team\b",
    r"\bseguit[oaie] da\b",
    r"\bse ne (occupa|occupano)\b",
    # English
    r"\b(he|she|they|someone) (could|should|can|must) (do|follow|handle|take care of|own)\b",
    r"\b(have|let|get) \w+ (do|handle|take care of) it\b",
    r"\bask \w+ to\b",
    r"\btogether with\b",
    r"\b(the|with the|for the|to the) team\b",
    r"\b(handled|followed|owned) by\b",
    r"\btakes? care of it\b",
)



# Common words and public vendor/platform names that must not be read as person
# names. User-specific brands come in via PROGETTI_SCOPE (user config).
NOMI_NON_PERSONE = frozenset(
    x.lower()
    for x in (
        *PROGETTI_SCOPE,
        *PIATTAFORME.values(),
        "AI", "Claude", "ChatGPT", "GPT", "OpenAI", "Gemini", "Google", "Meta", "Facebook", "WhatsApp", "Apple", "Mac",
        "iPhone", "Notion", "Shopify", "Figma", "Canva", "Excel", "GitHub", "SBK",
        "Inspiration", "Attività", "ClickUp", "Second", "Brain", "Amazon",
        "Reel", "Reels", "Ads", "Repo", "Plaud", "Whisper", "Sales",
        "Management", "Marketing", "Business", "Growth", "Operations", "Product", "Head", "Founder",
    )
)


def _pronto_quieto(v: dict) -> bool:
    ""


    L = v.get("lavorazione") or {}
    sc = L.get("scope") or {}
    if L.get("passo") != "contesto" or (v.get("segno") or {}).get("tipo") != "da_far_partire":
        return False
    if sc.get("strada") not in ("studio", "sviluppo") or not sc.get("confermato"):
        return False
    return not (L.get("sessione") or {}).get("c_e") and not (L.get("lavoro") or {}).get("avviato")


def _aperte_allo_scope(domande) -> list[dict]:
    ""

    return [
        d
        for d in domande or []
        if isinstance(d, dict) and not d.get("chiusa") and d.get("passo") == "scope"
    ]


def domande_aperte_allo_scope(v: dict) -> list[dict]:
    ""
    return _aperte_allo_scope(_domande(v))


def _aspetta_il_giusto(v: dict) -> bool:
    ""

    L = v.get("lavorazione") or {}
    return (
        L.get("passo") == "scope"
        and not L.get("task_manca")
        and (L.get("adesso") or {}).get("chi") == "te"
        and (v.get("segno") or {}).get("tipo") == "da_confermare"
    )


def _in_arrivo(v: dict) -> bool:
    ""

    L = v.get("lavorazione") or {}
    if (L.get("perche") or {}).get("correzione_in_arrivo"):
        return True
    if any(
        isinstance(d, dict) and not d.get("chiusa") and d.get("stato") in IN_VIAGGIO
        for d in L.get("domande") or []
    ):
        return True
    return bool(v.get("frase_audio"))


def fuori_dalla_lista(v: dict) -> str:
    ""




    L = v.get("lavorazione") or {}
    sc = L.get("scope") or {}
    if L.get("passo") != "scope" or L.get("task_manca") or sc.get("confermato"):
        return "passo"
    if sc.get("strada") not in STRADE_LISTA:
        return "strada"
    if _aperte_allo_scope(L.get("domande")):
        return "domande"
    if sc.get("delicato"):
        return "delicato"
    if (L.get("perche") or {}).get("confermato"):


        return "perche_confermato"
    if (L.get("sessione") or {}).get("aperta"):
        return "agente"
    if (L.get("lavoro") or {}).get("avviato"):
        return "lavoro"
    if (L.get("rilettura") or {}).get("aperta"):
        return "rilettura"
    if _in_arrivo(v):
        return "in_arrivo"
    if L.get("cambio_scope"):
        return "passi_fatti"
    if (L.get("adesso") or {}).get("chi") != "te":
        return "passo"
    if (v.get("_interno") or {}).get("nuovo"):

        return "nuovo"
    return ""


def _normale(testo: str) -> str:
    ""

    t = unicodedata.normalize("NFD", str(testo or "").lower().replace("’", "'"))
    t = "".join(c for c in t if not unicodedata.combining(c))
    return " ".join(t.split())


@functools.lru_cache(maxsize=4)
def _segni_incerto(percorso: str, _mtime: float) -> tuple[str, ...]:
    try:
        d = json.loads(Path(percorso).read_text(encoding="utf-8"))
        segni = (d.get("incerto") or {}).get("segni") or []
    except (OSError, ValueError, AttributeError):
        segni = []
    return tuple(str(x) for x in segni if isinstance(x, str))


def _dubbi() -> tuple[str, ...]:
    ""
    f = os.path.join(RADICE, "archivio", "verbi-di-owner.json")
    try:
        m = os.path.getmtime(f)
    except OSError:
        return DUBBI_IN_PIU
    return (*_segni_incerto(f, m), *DUBBI_IN_PIU)


def _ha_dubbio(testo: str) -> bool:
    return _dubbio_trovato(testo)[0]


def _dubbio_trovato(testo: str) -> tuple[bool, str]:
    ""


    t = _normale(testo)
    for segno in _dubbi():
        try:
            m = re.search(segno, t)
        except re.error:
            continue
        if m:
            return True, _nel_testo(testo, m.group(0))
    return False, ""


def _nel_testo(testo: str, pezzo: str) -> str:
    ""


    cercato = " ".join(str(pezzo or "").split())
    k = len(cercato.split())
    parole = str(testo or "").split()
    if not k:
        return ""
    for i in range(len(parole) - k + 1):
        finestra = " ".join(parole[i : i + k]).strip(".,;:!?«»\"“”()'’-")
        if finestra and _normale(finestra).startswith(cercato):
            return finestra
    return ""


def _nomina_qualcuno(testo: str) -> bool:
    ""


    return _nome_trovato(testo)[0]


def _nome_trovato(testo: str) -> tuple[bool, str]:
    ""


    t = _normale(testo)
    per_forma = any(re.search(f, t) for f in PERSONA_FORME)
    noti = _nomi_noti()

    def grande(p: str) -> bool:
        pulita = p.strip("'’-")
        return bool(
            pulita
            and pulita[0].isupper()
            and not pulita.isupper()
            and not any(c.isupper() for c in pulita[1:])
            and not any(c.isdigit() for c in pulita)
            and _normale(pulita) not in noti
        )

    for frase in re.split(r"[.!?\n;«»\"“”()]+", str(testo or "")):
        parole = re.findall(r"[^\W\d_][\w'’-]*", frase)
        for i, p in enumerate(parole[1:], start=1):
            if not grande(p):
                continue
            nome = [p.strip("'’-")]
            for q in parole[i + 1 :]:
                if not grande(q):
                    break
                nome.append(q.strip("'’-"))
            return True, " ".join(nome)
    return per_forma, ""


@functools.lru_cache(maxsize=1)
def _nomi_noti() -> frozenset:
    return frozenset(_normale(x) for x in NOMI_NON_PERSONE)


def _strada_dalle_sue_parole(sc: dict) -> bool:
    ""


    da = str(sc.get("strada_da") or "")
    if da:
        return da == "verbo"
    verbo = str((sc.get("verbo") or {}).get("strada") or "")
    return bool(int(sc.get("versione") or 0) and verbo and verbo == sc.get("strada"))


def _riga_lista(v: dict, tipi: dict | None = None) -> dict:
    ""


    L = v.get("lavorazione") or {}
    sc = L.get("scope") or {}
    i = v.get("_interno") or {}
    tp = sc.get("le_tue_parole") or {}
    parole = [x for x in [tp.get("prima"), *(tp.get("altre") or [])] if x] if tp else []
    dalle_sue = _strada_dalle_sue_parole(sc)
    testo = " ".join(parole)
    trovato = ""
    if not dalle_sue:
        perche = "dedotto"
    else:
        dubbio, parola = _dubbio_trovato(testo)
        persona, chi = (False, "") if dubbio else _nome_trovato(testo)
        perche = "dubbio" if dubbio else ("persona" if persona else "")
        trovato = parola if dubbio else chi
    dedotto_frase = (
        "" if dalle_sue else TESTI["lista_dedotto_parole" if parole else "lista_dedotto_niente"]
    )

    if perche == "dubbio":
        senza_frase = (
            TESTI["lista_senza_spunta_dubbio_parola"].format(parola=trovato)
            if trovato
            else TESTI["lista_senza_spunta_dubbio"]
        )
    elif perche == "persona":
        senza_frase = (
            TESTI["lista_senza_spunta_persona_nome"].format(chi=trovato)
            if trovato
            else TESTI["lista_senza_spunta_persona"]
        )
    else:
        senza_frase = dedotto_frase


    tipi = tipi if tipi is not None else _voci_che_cosa_e()
    tipo = str(sc.get("tipo") or "")
    tipo_frase = tipi.get(tipo, "") if tipo and tipo != "senza" else ""
    quando = str(i.get("nuovo_quando") or "")
    qc = _quando_corto(quando)


    dopo = (
        [
            d
            for d in L.get("domande") or []
            if isinstance(d, dict) and not d.get("chiusa") and d.get("passo") != "scope"
        ]
        if sc.get("strada") != "riferimento"
        else []
    )
    return {
        "id": str(v.get("id") or ""),
        "versione": int(sc.get("versione") or 0),
        "titolo": str(v.get("titolo") or ""),
        "copertina": v.get("copertina") or "",
        "strada_frase": str(sc.get("strada_frase") or ""),

        "tipo_frase": tipo_frase,

        "parole_di_owner": parole[0] if parole else "",
        "dedotto": not dalle_sue,
        "dedotto_frase": dedotto_frase,
        "spuntata": not perche,
        "senza_spunta": perche,
        "senza_spunta_frase": senza_frase,

        "senza_spunta_parola": trovato,
        "progetto": str(v.get("progetto_a_vista") or ""),
        "da_quando": _frase(TESTI["segno_dal"], quando=qc) if qc else "",
        "da_quando_iso": quando,
        "nuovo": bool(i.get("nuovo")),
        "domande_dopo": len(dopo),


        "domande_del_dopo": [_domanda_a_vista(d) for d in dopo],
        "domande_dopo_frase": (
            TESTI["lista_domande_dopo_uno"]
            if len(dopo) == 1
            else TESTI["lista_domande_dopo"].format(n=len(dopo))
        )
        if dopo
        else "",
    }


def _parola_giusto(strada: str, n: int) -> str:
    ""

    if n <= 0 or strada not in STRADE_LISTA:
        return ""
    if n == 1:
        return TESTI[f"lista_giusto_{strada}_uno"]
    return TESTI[f"lista_giusto_{strada}"].format(n=n)


def _poi_domande(k: int, n: int) -> str:
    ""


    if not k or n <= 1:
        return ""
    if k == n:
        return TESTI["lista_poi_con_domande_tutti"].format(n=n)
    if k == 1:
        return TESTI["lista_poi_con_domande_uno"].format(n=n)
    return TESTI["lista_poi_con_domande"].format(k=k, n=n)


def _voci_che_cosa_e() -> dict:
    ""

    for d in filtri_dimensioni():
        if d.get("id") == "che_cosa_e":
            return {str(x.get("id")): str(x.get("nome") or "") for x in d.get("voci") or []}
    return {}


def lista_da_confermare(spunti: list) -> dict:
    ""






    candidati = [v for v in spunti if _aspetta_il_giusto(v)]
    entrano, motivi = [], {}
    for v in candidati:
        m = fuori_dalla_lista(v)
        if m:
            motivi[m] = motivi.get(m, 0) + 1
        else:
            entrano.append(v)
    tipi = _voci_che_cosa_e()
    gruppi = []
    for strada in STRADE_LISTA:
        voci = [v for v in entrano if (v["lavorazione"].get("scope") or {}).get("strada") == strada]
        if not voci:
            continue
        righe = [_riga_lista(v, tipi) for v in voci]
        righe = [r for r in righe if r["spuntata"]] + [r for r in righe if not r["spuntata"]]
        spuntate = sum(1 for r in righe if r["spuntata"])
        k = sum(1 for r in righe if r["domande_dopo"])
        gruppi.append(
            {
                "strada": strada,
                "frase": TESTI[f"lista_frase_{strada}"],
                "poi": TESTI[f"lista_poi_{strada}"],

                "con_domande_dopo": k,
                "poi_domande": _poi_domande(k, len(righe)),
                "n": len(righe),
                "spuntate": spuntate,
                "conferma": {
                    "verbo": "conferma_lista",
                    "riga": f"conferma-lista --strada {strada} --",



                    "parola": _parola_giusto(strada, spuntate),
                    "parole": {str(x): _parola_giusto(strada, x) for x in range(1, len(righe) + 1)},
                    "parola_uno": _parola_giusto(strada, 1),
                    "parola_molti": _parola_giusto(strada, len(righe)),
                    "aiuto": TESTI["lista_si_aiuto"],
                },
                "righe": righe,
            }
        )
    n_fuori = len(candidati) - len(entrano)


    dentro = {id(v) for v in entrano}
    di_prima = sum(1 for v in _di_prima_da_confermare(spunti) if id(v) not in dentro)
    n_lista = sum(g["n"] for g in gruppi)
    return {

        "titolo": (
            TESTI["lista_titolo_uno"] if n_lista == 1 else TESTI["lista_titolo"].format(n=n_lista)
        )
        if n_lista
        else "",

        "n": n_lista,
        "gruppi": gruppi,
        "fuori": {

            "n": n_fuori,

            "frase": (
                TESTI["lista_fuori_uno"]
                if di_prima == 1
                else TESTI["lista_fuori"].format(n=di_prima)
            )
            if di_prima
            else "",
            "di_prima": di_prima,
            "per_motivo": motivi,
        },
    }


def _dopo(iso_a: str, iso_b: str) -> bool:
    ""
    return bool(iso_a and iso_b) and str(iso_a)[:19] >= str(iso_b)[:19]


def _contesto_scritto_dopo(cartella: str, quando: str) -> bool:
    ""
    if not (cartella and quando):
        return False
    try:
        m = os.path.getmtime(os.path.join(cartella, "CONTESTO.json"))
    except OSError:
        return False
    return _dopo(datetime.datetime.fromtimestamp(m).isoformat(timespec="seconds"), quando)


def fuori_dall_annullo(g: dict, via: str) -> str:
    ""



    L = g.get("lavorazione") or {}
    sc = L.get("scope") or {}
    if not sc.get("confermato") or str(sc.get("confermato_via") or "") != via:
        return "a_mano"
    quando = str(sc.get("confermato_quando") or "")
    if sc.get("letto_quando"):
        return "letto"
    ses = L.get("sessione") or {}
    if ses.get("aperta") or _dopo(str(ses.get("aperta_quando") or ""), quando):
        return "agente"
    ag = _dict(_dict(g.get("attivita")).get("agente"))
    if ag.get("avviato_quando") or ag.get("pannello"):
        return "lavoro"
    if _dict(L.get("scheda")).get("file"):
        return "scheda"
    pi = _dict(L.get("piano"))
    if pi.get("file") or pi.get("passi") or pi.get("punto_di_arrivo"):
        return "contesto"
    if _contesto_scritto_dopo(str(L.get("cartella") or ""), quando):
        return "contesto"
    task = (
        _dict(g.get("link")).get("task")
        or _dict(g.get("attivita")).get("task_url")
        or _dict(_dict(L.get("smistamento")).get("confermato")).get("task")
    )
    if task:
        return "task"
    return ""


def gruppi_confermati(grezze: list) -> list[dict]:
    ""



    gruppi: dict[str, dict] = {}
    for g in grezze:
        if not isinstance(g, dict):
            continue
        sc = _dict(_dict(g.get("lavorazione")).get("scope"))
        ident = str(g.get("id") or "")
        via = str(sc.get("confermato_via") or "")
        if sc.get("confermato") and via.startswith(VIA_LISTA):
            x = gruppi.setdefault(via, {"ancora": [], "riaperti": [], "quando": []})
            x["ancora"].append(g)
            x["quando"].append(str(sc.get("confermato_quando") or ""))
        for c in sc.get("conferme_di_prima") or []:
            cv = str(_dict(c).get("confermato_via") or "")
            if cv.startswith(VIA_LISTA):
                x = gruppi.setdefault(cv, {"ancora": [], "riaperti": [], "quando": []})
                if ident not in x["riaperti"]:
                    x["riaperti"].append(ident)
                x["quando"].append(str(_dict(c).get("confermato_quando") or ""))
    out = []
    for via, x in gruppi.items():
        ancora_ids = [str(g.get("id") or "") for g in x["ancora"]]
        riaperti = [i for i in x["riaperti"] if i not in ancora_ids]
        riapribili = [g for g in x["ancora"] if not fuori_dall_annullo(g, via)]
        quando = min((q for q in x["quando"] if q), default="")
        n = len(ancora_ids) + len(riaperti)
        gid = via[len(VIA_LISTA) :]
        strada = next((s for s in STRADE_LISTA if gid.endswith(f"-{s}")), "")
        q = _quando(quando)

        chiave = f"lista_confermati_{strada}" if strada else "lista_confermati"
        frase = _frase(TESTI[chiave + ("_uno" if n == 1 else "")], n=n, quando=q).rstrip(" ,")
        voce = {
            "id": gid,
            "strada": strada,
            "quando": q,
            "quando_iso": quando,
            "n": n,
            "ancora": len(ancora_ids),
            "riaperti": len(riaperti),
            "frase": frase,
            "ids": ancora_ids + riaperti,
        }
        k = len(ancora_ids) - len(riapribili)
        if riapribili:
            voce["annulla"] = {
                "verbo": "riapri_lista",
                "riga": f"riapri-lista {gid}",
                "parola": TESTI["lista_annulla"],
                "aiuto": TESTI["lista_annulla_aiuto"],
            }
            if k:
                voce["annulla_frase"] = (
                    TESTI["lista_annulla_non_tutti_uno"]
                    if k == 1
                    else TESTI["lista_annulla_non_tutti"].format(k=k)
                )
        elif not ancora_ids:
            voce["annulla_frase"] = TESTI["lista_annullati"]
        out.append(voce)
    out.sort(key=lambda x: x["quando_iso"], reverse=True)
    return out[:GRUPPI_A_VISTA]


def _pronti(spunti: list) -> dict:
    ""


    voci = [v for v in spunti if _pronto_quieto(v)]
    n = len(voci)
    frase = (
        (TESTI["testa_pronti_uno"] if n == 1 else TESTI["testa_pronti"].format(n=n)) if n else ""
    )
    out = {
        "n": n,
        "frase": frase,
        "parola": TESTI["pronti_parola"],
        "ids": [str(v.get("id") or "") for v in voci],
    }
    if n:
        out["riga"] = _vista("pronti", voci, frase)
    return out




MENU_PASSI = (
    ("tutti", "menu_tutti", "tutti"),
    *((p, f"passo_{p}", "passi") for p in PASSI6),
    ("riferimento", "menu_riferimento", "uscite"),
    ("cosa_da_fare", "menu_cosa_da_fare", "uscite"),
    ("letto", "menu_letto", "uscite"),
    ("non_serve", "menu_non_serve", "uscite"),
)


def _passo_menu(v: dict) -> str:
    ""

    L = v.get("lavorazione") or {}
    if L.get("task_manca"):
        return "cosa_da_fare"
    passo = str(L.get("passo") or v.get("passo") or "")
    return passo if passo in (*PASSI6, *USCITE) else "capire"


def _passi_menu(spunti: list) -> list[dict]:
    ""


    out = []
    for ident, chiave, gruppo in MENU_PASSI:
        dentro = spunti if ident == "tutti" else [v for v in spunti if v.get("passo_menu") == ident]
        te = sum(1 for v in dentro if v.get("per_te"))
        riga = (
            TESTI[f"menu_{ident}_riga"] if f"menu_{ident}_riga" in TESTI else TESTI[f"dopo_{ident}"]
        )
        per_te_frase = _per_te_frase(ident, te)


        if per_te_frase and te != len(dentro):
            etichetta = TESTI["menu_etichetta_per_te"].format(
                nome=TESTI[chiave], n=len(dentro), per_te=per_te_frase
            )
        elif dentro:
            etichetta = TESTI["menu_etichetta"].format(nome=TESTI[chiave], n=len(dentro))
        else:
            etichetta = TESTI[chiave]
        out.append(
            {
                "id": ident,
                "nome": TESTI[chiave],
                "gruppo": gruppo,
                "staccata": gruppo == "uscite",
                "n": len(dentro),
                "per_te": te,
                "aspettano_te": te,
                "per_te_frase": per_te_frase,
                "etichetta": etichetta,
                "aiuto": riga,
                "frase": riga,
                "vuota": TESTI[f"menu_{ident}_vuota"],
            }
        )
    return out


def _per_te_frase(ident: str, te: int) -> str:
    ""

    if not te or ident == "tutti":
        return ""
    uno = te == 1
    if ident == "scope":
        return TESTI["per_te_nuovi_uno"] if uno else TESTI["per_te_nuovi"].format(n=te)
    if ident == "capire":
        return (
            TESTI["per_te_aspettano_si_uno"] if uno else TESTI["per_te_aspettano_si"].format(n=te)
        )
    return TESTI["per_te"].format(n=te)


def _fasi(spunti: list) -> list[dict]:
    ""
    out = []
    for i, nome, aiuto, vuota in FASI:
        dentro = spunti if i == "tutti" else [v for v in spunti if v.get("fase") == i]
        te = sum(1 for v in dentro if v.get("tocca") == "te")
        coda = ASPETTANO["uno"] if te == 1 else (ASPETTANO["tanti"].format(n=te) if te else "")
        out.append(
            {
                "id": i,
                "nome": nome,
                "n": len(dentro),
                "aspettano_te": te,
                "aiuto": aiuto,
                "frase": f"{aiuto} {coda}".strip(),
                "vuota": vuota,
            }
        )
    return out


def per_app() -> dict:
    return stato()


def main(argv: list[str]) -> int:
    if argv[1:2] in (["-h"], ["--help"]):
        print(__doc__)
        return 0
    if argv[1:2] == ["json"]:
        print(json.dumps(stato(), ensure_ascii=False))
        return 0
    print("usage: sb_inspiration.py json", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
