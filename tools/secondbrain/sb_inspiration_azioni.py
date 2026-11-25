#!/usr/bin/env python3
""
























































from __future__ import annotations

import argparse
import contextlib
import datetime
import fcntl
import hashlib
import importlib.util
import inspect
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

QUI = Path(__file__).resolve().parent
ROOT = QUI.parents[1]
RADICE = Path(
    os.environ.get("SB_INSPIRATION_RADICE")
    or Path.home() / ".sbk-data" / "inspiration"
)
CASA_ARCHIVIO = RADICE / "archivio"
MODELLI = QUI / "inspiration"
VENV = ROOT / ".venv" / "bin" / "python"




LEGGI_DM = Path(os.environ.get("SB_LEGGI_DM") or CASA_ARCHIVIO / "leggi-dm.py")
TRASCRIVI = CASA_ARCHIVIO / "trascrivi-audio.py"
ULTIMA_RILETTURA = CASA_ARCHIVIO / "ultima-rilettura.json"
RILEGGI_LOG = CASA_ARCHIVIO / "rileggi.log"



CAPISCI_DA_SOLO = CASA_ARCHIVIO / "capisci-da-solo.json"
AGENT_CLI = os.environ.get("SB_AGENT_CLI") or "agent-cli"








def _trova_claude():
    scelto = os.environ.get("SB_CLAUDE_CLI")
    if scelto:
        return scelto
    for p in (
        shutil.which("claude"),
        Path.home() / ".local" / "bin" / "claude",
        "/opt/homebrew/bin/claude",
        "/usr/local/bin/claude",
    ):
        if p and Path(p).exists():
            return str(p)
    return "claude"


CLAUDE = _trova_claude()






POOL_SWITCH = Path(os.environ.get("SB_POOL_SWITCH") or ROOT / "tools" / "account-pool" / "switch")





MODELLO_PER_LAVORO = {
    "comprensione": "opus",
    "rilettura": "opus",
    "smistamento": "opus",
    "arretrati": "haiku",
}
STRUMENTO_SOTTOFONDO = {
    "comprensione": "inspiration-comprensione",
    "rilettura": "inspiration-rilettura",
    "smistamento": "inspiration-smistamento",
    "arretrati": "inspiration-arretrati",
}

SMISTAMENTO_GIRO = Path(
    os.environ.get("SB_SMISTAMENTO_GIRO") or (RADICE / "archivio" / "smistamento-giro.json")
)
BLOCCO_SMISTAMENTO = int(os.environ.get("SB_BLOCCO_SMISTAMENTO") or 15)
ATTREZZI_SMISTAMENTO = "Read,Write,Glob,Grep"



ARRETRATI_GIRO = Path(
    os.environ.get("SB_ARRETRATI_GIRO") or (RADICE / "archivio" / "arretrati-giro.json")
)
LUCCHETTO_ARRETRATI = CASA_ARCHIVIO / ".arretrati-giro.lock"

ATTREZZI_ARRETRATI = "Read,Write,Edit,Glob,Grep,Bash"


VIETATO_ARCHIVIO = "Bash(*archivio.py*)"
DA_ARRETRATI = "rilettura degli arretrati"




IMPOSTAZIONI_ARRETRATI = (
    "punti_per_gruppo",
    "punti_al_giorno",
    "voci_per_gruppo",
    "equivalente_per_sessione",
)


# Optional account-pool quota file(s): set SB_QUOTA_EFFETTIVO (os.pathsep-separated)
# to point at your own quota-effective.json. Default looks under ~/.config.
QUOTA_EFFETTIVO = [
    Path(p)
    for p in (
        os.environ.get("SB_QUOTA_EFFETTIVO")
        or str(Path.home() / ".config" / "quota" / "quota-effective.json")
    ).split(os.pathsep)
    if p
]

ATTESA_PRESTITO_S = int(os.environ.get("SB_ATTESA_PRESTITO_S") or 600)
LUCCHETTO_COMPRENSIONE = CASA_ARCHIVIO / ".comprensione.lock"


LUCCHETTO_RILETTURA = CASA_ARCHIVIO / ".rilettura.lock"






ATTREZZI_RILETTURA = "Read,Write,Glob,Grep"
DA_RILETTURA = "rilettura dopo la tua risposta"

QUIETE_RILETTURA_S = int(os.environ.get("SB_QUIETE_RILETTURA_S") or 25)

TENTATIVI_COMPRENSIONE = 3
RIPROVA_COMPRENSIONE_S = int(os.environ.get("SB_RIPROVA_COMPRENSIONE_S") or 1800)






VUOTI_DI_FILA = 6
TETTO_A_VUOTO = 12


CODICI_A_VUOTO = (
    "lancio",
    "scaricatore-occupato",
    "senza-prestiti",
    "prestito-nessuno",
    "prestito-occupato",
    "prestito-vietato",
    "memoria",
)

DISPONIBILITA_DEFINITIVE = ("vietato ai minori", "rimosso", "privato")


REGISTRO_GIRO = CASA_ARCHIVIO / "giro-tick.log"

LUCCHETTO_SCARICHI = CASA_ARCHIVIO / ".scarichi.lock"
SCARICHI_IN_CORSO = CASA_ARCHIVIO / "scarichi-in-corso.json"


LUCCHETTO_CFG = CASA_ARCHIVIO / ".capisci-da-solo.lock"




CHIAVI_DI_FUORI = (
    "acceso",
    "leggi_dm",
    "interruttore",
    "dopo_minuti",
    "riparti_fermi_a_vuoto",
    "task_in_attivita",
    "task_su_clickup",
    "passaggio_intero_minuti",
    "nuovo_giorni",


    "impostazioni_traccia",
)

TETTO_COMPRENSIONE_S = 3 * 3600

CONTROLLO_SCARICHI_S = int(os.environ.get("SB_CONTROLLO_SCARICHI_S") or 3600)


INTERVALLO_CONTROLLO_MIN = 10


ATTESA_A_VUOTO_S = int(os.environ.get("SB_ATTESA_A_VUOTO_S") or INTERVALLO_CONTROLLO_MIN * 60)

TICK_VIVO_MIN = 25
LUCCHETTO_GIRO = CASA_ARCHIVIO / ".giro.lock"

DM_LETTURA = CASA_ARCHIVIO / "dm-lettura.json"

LUCCHETTO_AVVII = CASA_ARCHIVIO / ".avvii.lock"


INTERVALLO_TENTATIVI_S = 600
TENTATIVI = 7

QUIETE_S = 25

CONTROLLO_SESSIONI_S = 10



TERMINALE_ASSENTE_VOLTE = 3
TERMINALE_ASSENTE_S = int(os.environ.get("SB_TERMINALE_ASSENTE_S") or 120)


TERMINALE_ASSENTE_FRA_LETTURE_S = 1

ORFANO_QUIETE_S = 60

GIRO_SCOMPONI = "scomponi"


ATTREZZI_SPUNTO = "Read,Write,Edit,Glob,Grep,WebSearch,WebFetch"
ATTREZZI_RICERCA = ATTREZZI_SPUNTO
ATTREZZI_COSTRUZIONE = "Read,Write,Edit,Glob,Grep,WebSearch,WebFetch,Bash"

VIETATI_COSTRUZIONE = "Bash(security:*) Bash(curl:*) Bash(wget:*) Bash(gh:*) Bash(npx:*) Bash(pip install:*) Bash(npm install:*)"



# project -> (organization, project) working-folder map; load from user config.
# Default keeps only a generic fallback.
DOVE_LAVORA = {
    "altro": ("default", "inspiration"),
}

AVVISO_RIPRENDI = (
    "resume. The user answered in SBK. Re-read RISPOSTE.json in this folder and continue from where you were, following "
    "the folder's instructions. If you need anything else from the user, ask them here."
)



AVVISO_SCOPE = (
    "resume. The user changed the scope in SBK and confirmed it. Re-read RISPOSTE.json in this folder, the current scope "
    "is in the scope field. Tell them here what changes in the work and what you redo, and continue with the new scope."
)



RISPOSTE_FUORI_IMPRONTA = ("aggiornato", "scope", "scope_alla_partenza")





SEGNAPOSTO_APERTURA = "da-avvisare-dopo-l-apertura"


FRASI = {
    "gia_partito": "Work on this idea has already started",
    "solo_pronta": "Only an idea with a ready card can be started",
    "scheda_sparita": "This idea's card can no longer be found on the Mac",
    "fase_sbagliata_sessione": "For this idea, Work on it isn't needed right now",
    "altra_sessione_in_apertura": "I'm already starting another job. Try again shortly",
    "terminale_non_apre": "the terminal did not open the agent. Is it open? Try again",
    "terminale_non_risponde": "the terminal is not responding. Is it open? Try again shortly",

    "terminale_non_lo_trova": "the terminal can no longer find this agent. If it doesn't reappear I'll mark it closed on my own, and from there you can reopen it",
    "cartella_lavoro": "I can't find where to put the working folder. Try again shortly, and if it happens again tell me in the terminal",


    "sessione_chiusa_riapri": "The terminal job on this idea closed {quando}. What I wrote stays here, with Work on it I resume from there",
    "sessione_chiusa_resta": "The terminal job on this idea closed. The card and the answers stay here",
    "lavoro_chiuso": "The terminal job is no longer open. What I've written so far is in the result",
    "lavoro_finito": "The job is done. The result is here",
    "task_non_creata": "The job started, but ClickUp did not create the task. You can create it later, from the backlog",
    "task_non_creata_ferma": "ClickUp did not create the task, the job did not start. Try again, or start without the task",



    "avvia_task_nata": "The job started, the task is in Activities",
    "avvia_task_c_era": "The job started. The task was already in Activities",
    "avvia_task_c_era_clickup": "The job started. The task was already on ClickUp and stays that one",
    "avvia_task_non_nata": "The job started. The task in Activities was not created, you can create it from the idea",

    "avvia_task_eliminata": "The job started. You had deleted the task from Activities, you recreate it from the idea",
    "avvia_task_delicato": "The job started. It's a sensitive matter, so I don't create the task",
    "avvia_task_spenta": "The job started. Tasks from ideas are turned off, so I don't create it",
    "avvia_descrizione_lavoro": "The job started on {quando} from an Inspiration idea, and you follow it from there",
    "non_andata": "It didn't work, try again",



    "agente_aperto_da_segnare": "The agent is already open in the terminal and you can talk to it there. Press again in a moment, so I find it here too without opening another one",

    "agente_non_visto_in_terminale": "I don't see the agent I had opened in the terminal. If you closed it, press again in a couple of minutes and I'll open a new one",

    "lavoro_aperto_scheda_di_prima": "The job agent is already open in the terminal with the previous card. To start it with the new one, close it in the terminal and press Start again",
    "lavoro_aperto_permessi_di_prima": "The job agent is already open in the terminal with the previous permissions. To start it with the new ones, close it in the terminal and press Start again",
    "lavoro_aperto_scheda_e_permessi_di_prima": "The job agent is already open in the terminal with the previous card and permissions. To start it with the new ones, close it in the terminal and press Start again",

    "niente_da_capire": "I've already understood this idea, there's nothing to understand here right now",
    "comprensione_in_corso": "I'm already understanding this idea. As soon as I'm done you'll see it here",
    "scendono_da_soli": "The remaining ones I download and understand on my own, nothing is needed from you",

    "scendono_da_soli_spento": "The remaining ones I'm already downloading. When they've arrived press again and I'll understand them",

    "scende_gia": "I'm already downloading it, I'll understand it as soon as it arrives. Nothing is needed from you",
    "scende_gia_spento": "I'm already downloading it. When it has arrived press again and I'll understand it",



    "senza_accesso_tutte": "The remaining ones Instagram shows only to those who sign in with their account",
    "fermi_uno_alla_volta": "The posts stuck by an error of mine restart on their own, one at a time",
    "fermi_non_ripartono": "The posts stuck by an error of mine are not restarting now",
    "col_si_da_soli": "The ones with your yes I open on my own, one at a time. Nothing is needed from you",
    "fermi_uno_per_uno": "The remaining ones got stuck. Open them one by one and press Do it now",
    "si_tenuto": "Your yes stays, it starts on its own as soon as possible",

    "uno_parte_altri_in_fila": "One post I read now, the other {n} I read on my own, one at a time",
    "uno_parte_altro_in_fila": "One post I read now, the other I read on my own later",
    "uno_parte_altri_aspettano": "One post I read now, the other {n} are still waiting for your yes",
    "uno_parte_altro_aspetta": "One post I read now, the other is still waiting for your yes",

    "quota_manca": "From this Mac I can't reach the Claude subscriptions right now, so I don't understand it yet",


    "quota_nessuno": "No Claude subscription is free right now{quando}. When one comes back I'll understand it on my own",
    "quota_nessuno_spento": "No Claude subscription is free right now{quando}. When one comes back, press Do it now again",
    "claude_manca": "I can't find Claude on this Mac, so I don't understand it yet. It's an error of mine, the content has nothing to do with it",
    "prestito_vietato": "I don't understand it yet because of an error of mine with the subscriptions, the content has nothing to do with it",


    "comprensione_prestito_nessuno": "No Claude subscription was free{quando}",
    "comprensione_prestito_occupato": "The Claude subscriptions were all busy even after {attesa} of waiting",
    "comprensione_prestito_vietato": "It didn't start because of an error of mine with the subscriptions, the content has nothing to do with it",

    "comprensione_non_partita": "It didn't start because of an error of mine, the content has nothing to do with it",
    "comprensione_senza_esito": "Understanding was interrupted before finishing",
    "comprensione_senza_memoria": "The Mac had no free memory for half an hour, I'll try again later",
    "comprensione_tempo": "Understanding went past three hours and I stopped it",

    "comprensione_a_vuoto_troppe": "It didn't start because of an error of mine {n} times, the content has nothing to do with it. I'll try again when you press Do it now",

    "rilettura_senza_esito": "The re-read was interrupted before finishing",
    "rilettura_non_partita": "The re-read didn't start because of an error of mine",
    "rilettura_senza_memoria": "The Mac had no free memory for half an hour",
    "rilettura_tempo": "The re-read went past three hours and was stopped",
    "rilettura_senza_proposta": "The re-read finished without writing the proposal",
    "rilettura_risposta_in_corso": "I'm still re-reading everything with your answer. As soon as I'm done you'll see it here",

    "rilettura_risposta_in_fila": "I have your answer and I'll re-read everything as soon as I can. As soon as I'm done you'll see it here",
    "rilettura_quota_manca": "From this Mac I can't reach the Claude subscriptions right now, so I'm not re-reading the idea with your answer. The answer stays here",
    "rilettura_quota_nessuno": "No Claude subscription is free right now{quando}, so I'm not re-reading the idea with your answer. The answer stays here",
    "rilettura_prestito_nessuno": "For the re-read no Claude subscription was free{quando}",
    "rilettura_prestito_occupato": "The Claude subscriptions were all busy even after {attesa} of waiting",
    "rilettura_prestito_vietato": "The re-read didn't start because of an error of mine with the subscriptions",
    "rilettura_niente": "There's no answer of yours to re-read here right now",

    "smistamento_non_partita": "sorting didn't start, claude didn't launch on the Mac",
    "smistamento_prestito_vietato": "AccountPool doesn't lend an account for this model",
    "smistamento_senza_esito": "the sorting session closed without writing the outcome",
    "smistamento_senza_memoria": "the Mac had no free memory for half an hour, I'll try again next round",
    "smistamento_tempo": "the sorting session went past three hours and was stopped",
    "smistamento_prestito_nessuno": "AccountPool had no subscription to give{quando}",
    "smistamento_prestito_occupato": "AccountPool had all its loans busy and I waited {attesa}",
    "smistamento_quota_manca": "AccountPool isn't on this Mac, background sorting can't start",
    "smistamento_quota_nessuno": "AccountPool has no subscription to give right now{quando}, sorting restarts next round",

    "lavoro_sconosciuto": "the job «{chi}» has no model of its own, it won't start",


    "arretrati_quota_manca": "from this Mac I can't reach the Claude subscriptions, the backlog re-read won't start",
    "arretrati_prestito_vietato": "the subscriptions don't lend a model to the backlog re-read",
    "arretrati_prestito_nessuno": "no subscription with a free model{quando}",
    "arretrati_prestito_occupato": "the Claude subscriptions were all busy even after {attesa} of waiting",
    "arretrati_senza_memoria": "the Mac had no free memory to start, the idea goes back in the queue",
    "arretrati_memoria_alta": "the Mac's memory rose too high, I stopped the re-read and the idea goes back in the queue",
    "arretrati_non_partita": "the re-read didn't start, claude didn't launch on the Mac",
    "arretrati_tempo": "the re-read went past three hours and was stopped",
    "arretrati_senza_esito": "the re-read closed without writing the outcome",
    "arretrati_acceso": "backlog re-read on, group of {n} ideas",
    "arretrati_spento": "backlog re-read off",
    "arretrati_senza_impostazioni": "the backlog re-read numbers are missing ({chiavi}), it won't start",
    "arretrati_quota_di_prima": "the previous group's quota isn't read yet, the backlog re-read won't restart",
    "arretrati_gruppo_finito": "group done, {n} ideas re-read, the backlog re-read stops until the next turn-on",
    "arretrati_quota_non_letta": "the quota after the group isn't read, the last reading is from before the end of the group",
    "arretrati_gruppo_sopra": "subscription {account} took {punti} points in this group, over the {tetto}",
    "arretrati_giorno_sopra": "subscription {account} took {punti} points today, over the {tetto}",
    "arretrati_storte": "two re-reads in a row ended badly, the backlog re-read stops",
    "arretrati_prestito": "the subscription loan didn't arrive, the backlog re-read stops",
    "arretrati_preparatore": "the idea's entry didn't get prepared, the backlog re-read stops",
    "arretrati_cambiato": "the idea changed while I was re-reading it ({cosa}), the new proposal didn't go in",
    "arretrati_verifica_rossa": "the row check isn't green, the new proposal didn't go in",
    "arretrati_senza_riga": "the re-read didn't leave the idea's row, the new proposal didn't go in",
    "arretrati_scritto": "new proposal written",
    "arretrati_uguale": "the re-read proposal is the same as the previous one",
    "arretrati_rimandata": "the user's controls were busy, the idea goes back in the queue",
    "arretrati_non_presa": "the archive didn't take the proposal ({motivo})",

    "arretrati_cara": "re-reading {voce} cost {costo} of equivalent, over the {tetto}, the backlog re-read stops",
    "arretrati_costo_non_letto": "the cost of re-reading {voce} can't be read, the backlog re-read stops",
    "archivio_vecchio": "The archive on the Mac doesn't know this action yet. Update it and try again",

    "smista_senza_proposta": "For this idea I don't have a proposal yet for where it goes. Choose with Change",
    "smista_gia": "This idea is already sorted. If you want to change it, Reset first",
    "smista_in_corso": "I'm already sending another idea. Try again shortly",
    "smista_lista_sparita": "The list {lista} is no longer on ClickUp, I didn't create the task. Choose another outcome or tell me in the terminal",
    "smista_task_no": "ClickUp didn't create the task in {lista}. Try again shortly, the idea stays as it was",
    "smista_esito": "I don't know this outcome",

    "lettore_assente": "The reader for your DM can't be found on the Mac. Tell me in the terminal",
    "rilettura_in_corso": "I'm already re-reading your DM. Wait for it to finish",
    "rilettura_non_riuscita": "I couldn't read your DM on Slack. Try again shortly, and if it happens again tell me in the terminal",


    "scope_riferimento": "Done, I'm keeping it as a reference",
    "scope_non_serve": "Done, I'm filing it among the ones that aren't needed",
    "scope_attivita": "Done, it's in Activities",
    "scope_attivita_c_era": "It was already in Activities, I didn't make another one",
    "scope_team": "Done, I sent it to the team in {lista}",
    "scope_team_c_era": "The task for the team already existed, I didn't make another one",

    "scope_avanti": "Confirmed. Whenever you want, open the agent below",


    "scope_confermato": "Done, the scope is confirmed",
    "scope_raddrizzato": "I took what you told me, I'm re-reading the idea with your words",
    "scope_raddrizzato_giusto": "I took what you told me and the scope is confirmed",
    "scope_risposte": "I have your answers, I'm re-reading the idea with what you told me",
    "scope_non_ancora": "I'm still understanding it. When I'm done I'll tell you what I understood",
    "scope_senza_strada": "I still don't know what to do with this idea. Tell me with Correct",
    "scope_valore": "I don't know this choice",
    "scope_tipo_senza_strada": "The type is chosen only for a study or a development",
    "scope_gia": "This idea's scope is already confirmed",
    "scope_uscito": "This idea has already gone out. If you want to change it, Reopen first",
    "scope_a_voce_in_arrivo": "I'm still listening to your audio. When I've understood it you can confirm",
    "scope_risposte_illeggibili": "I didn't receive the answers properly, try again",
    "scope_delicato": "It's a sensitive matter, I won't file it anywhere on my own. Tell me where it goes",
    "scope_task_spenta": "For now I don't create the task",


    "scope_senza_task": "Done, it's to-do. The task isn't there yet",
    "crea_task_niente": "This idea isn't a to-do, there's no task to create here",

    "scope_task_di_prima": "Done, it's a to-do. The previous task already exists and stays where it is, {dove}",
    "scope_task_due": "Done, now there are two tasks, one {qui} and one {li}",

    "scope_cambiato": "The scope changed while you were looking at it. Re-read it and then decide",

    "scope_parole_prima_di_uscire": "I took what you told me and I'm re-reading the idea. When I'm done you confirm it",

    "scope_parole_prima_di_uscire_agente": "I took your words. With the agent open in the terminal I'm not re-reading the idea",

    "scope_agente_aperto": "With the agent open in the terminal you change the scope there, by talking to it. Here I didn't change anything",

    "scope_rifai_lavoro_aperto": "The job already started in the terminal. If it has to be redone with the new scope, tell the agent there. Here I didn't change anything",

    "scope_delicato_esce": "Done, it's a to-do. It's sensitive, so I don't create the task",
    "crea_task_delicato": "For a sensitive matter I don't create the task",

    "letto_aspetta_scheda": "The research hasn't written the card yet. When it's there you read it and say Read",
    "avvia_studio": "A study doesn't get started. When the card is there you read it and say Read",

    "scope_proposta_presa": "Done, I took the new proposal and the scope is confirmed this way",
    "scope_niente_proposta": "There's no new proposal to take",
    "scope_prendi_da_sola": "The new proposal is taken on its own, with no other choices",

    "letto": "Done, you've read it",
    "letto_niente": "Read applies only to a study with a confirmed scope",
    "scope_attivita_no": "The task didn't go into Activities, the idea stays as it was. Try again shortly",

    "scope_attivita_eliminata": "You had deleted this task from Activities, I didn't make another one",


    "rifai_task_nata": "Done, the task is back in Activities",
    "rifai_niente": "In Activities there's no deleted task for this idea, I didn't make another one",


    "task_descrizione_no": "Only the description didn't get written, add it yourself if needed",
    "scope_tieni_o_rifai": "Choose one thing only, keep or redo",
    "scope_niente_da_rifare": "With the new scope there's nothing to redo",
    "scope_tieni": "I keep what was there, marked as seen with the new scope",

    "scope_rifai": "It goes back to to-do with the new scope and restarts on your click. The previous one you can still read",
    "riapri": "The idea goes back to scope-to-confirm",

    "tutte_una_alla_volta": "Answer one question at a time, so I don't also close the ones you don't see",
    "riapri_con_task": "The idea goes back to scope-to-confirm. The task stays where it is",
    "riapri_niente": "This idea hasn't gone out, there's nothing to reopen",


    "impostazione_sconosciuta": "This setting doesn't exist, I didn't change anything",
    "impostazione_solo_lettura": "This one can only be viewed from here, I didn't change anything",
    "impostazione_valore": "Here you choose on or off, I didn't change anything",
    "impostazione_giorni": "You choose a number from {minimo} to {massimo}, I didn't change anything",



    "lista_coppie": "I didn't understand which ideas to confirm, open the list again and try again",
    "lista_strada": "Together you can only confirm references, studies and developments",
    "lista_confermati": "Confirmed {n}",
    "lista_confermati_uno": "Confirmed 1",
    "lista_con_fuori": "{k} I left out, look at them one by one",
    "lista_con_fuori_uno": "1 I left out, open it and decide there",
    "lista_niente": "I didn't confirm anything, look at them one by one",
    "lista_fuori_non_c_e": "I can't find it anymore",
    "lista_fuori_versione": "It changed while you were looking",
    "lista_fuori_strada": "This one is confirmed only by opening it",
    "lista_fuori_strada_cambiata": "What we do with it has now changed",
    "lista_fuori_passo": "It's no longer waiting for your Right",
    "lista_fuori_gia": "It was already confirmed",
    "lista_fuori_domande": "It has a question for you",
    "lista_fuori_delicato": "It's a sensitive matter, open it and decide there",
    "lista_fuori_perche_confermato": "You had already confirmed the reason yourself, open it and decide there",
    "lista_fuori_agente": "You're talking to the agent about it, it's decided there",
    "lista_fuori_lavoro": "The job has already started",
    "lista_fuori_rilettura": "I'm re-reading it, wait for it to finish",
    "lista_fuori_in_arrivo": "A word from you is on its way, wait for it to arrive",
    "lista_fuori_passi_fatti": "There are steps done with a previous scope, open it and decide there",
    "lista_fuori_nuovo": "It's a new proposal, open it and decide there",
    "lista_fuori_non_andata": "It didn't work, open it and try again there",

    "lista_riaperti": "{n} go back to confirm, including the reason you had confirmed together",
    "lista_riaperti_uno": "1 goes back to confirm, including the reason you had confirmed together",
    "lista_annulla_niente": "In this group there's nothing left to undo",
    "lista_annulla_fuori": "{k} stay confirmed",
    "lista_annulla_fuori_uno": "1 stays confirmed",
    "lista_resta_a_mano": "You confirmed it again yourself",
    "lista_resta_riaperto": "You already sent it back to confirm yourself",
    "lista_resta_letto": "You already marked it read",
    "lista_resta_agente": "You opened the agent",
    "lista_resta_lavoro": "The job started",
    "lista_resta_scheda": "The card already exists",
    "lista_resta_contesto": "The context is already written",
    "lista_resta_task": "It has a task",
    "lista_resta_non_andata": "It didn't work, open it and use Reopen",
}


class Errore(Exception):
    ""


class Avviso(Errore):
    ""



class Eliminata(Errore):
    ""



_ARCH = None


def arch():
    ""
    global _ARCH
    if _ARCH is None:
        p = CASA_ARCHIVIO / "archivio.py"
        spec = importlib.util.spec_from_file_location("archivio_inspiration", p)
        m = importlib.util.module_from_spec(spec)
        sys.modules["archivio_inspiration"] = m
        spec.loader.exec_module(m)
        _ARCH = m
    return _ARCH


def _parole():
    ""

    if str(QUI) not in sys.path:
        sys.path.insert(0, str(QUI))
    import sb_inspiration

    return sb_inspiration


def _adesso():
    return datetime.datetime.now().isoformat(timespec="seconds")


def _accetta(f, nome):
    ""
    try:
        return nome in inspect.signature(f).parameters
    except (TypeError, ValueError):
        return False


def _terminale(*argomenti, timeout=60):
    ""
    try:
        r = subprocess.run(
            [AGENT_CLI, *argomenti, "--json"], capture_output=True, text=True, timeout=timeout
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    try:
        d = json.loads(r.stdout or "{}")
    except ValueError:
        return None
    return d.get("result", d) if isinstance(d, dict) else None


def terminale_stato(handle):
    ""



    if not handle:
        return "assente"
    d = _terminale("terminal", "show", "--terminal", handle, timeout=30)
    if not isinstance(d, dict) or not d:
        return None
    if d.get("ok") is False or d.get("error"):
        codice = (
            str((d.get("error") or {}).get("code") or "")
            if isinstance(d.get("error"), dict)
            else ""
        )
        return "assente" if codice in ("terminal_handle_stale", "terminal_not_found") else None
    t = d.get("terminal")
    if not isinstance(t, dict) or not t:
        return None
    if str(t.get("status") or "running") == "exited":
        return "finito"
    return "assente" if t.get("orphaned") else "vivo"


def terminale_vivo(handle):
    ""

    stato = terminale_stato(handle)
    return None if stato is None else stato == "vivo"


TERMINALI_NON_VISTI = CASA_ARCHIVIO / ".terminali-non-visti.json"


_DA_LEGGERE = object()


def _conta_non_visto(c, adesso):
    ""


    c = c if isinstance(c, dict) else {}
    c = {"prima": float(c.get("prima") or adesso), "volte": int(c.get("volte") or 0) + 1}
    return c, c["volte"] >= TERMINALE_ASSENTE_VOLTE and adesso - c["prima"] >= TERMINALE_ASSENTE_S


def _terminale_morto(handle, adesso=None, stato=_DA_LEGGERE, segna_morto=False):
    ""



    if stato is _DA_LEGGERE:
        stato = terminale_stato(handle)
    if stato is None:
        return False
    adesso = time.time() if adesso is None else adesso
    with _lucchetto(TERMINALI_NON_VISTI.with_suffix(".lock")):
        try:
            conti = json.loads(TERMINALI_NON_VISTI.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            conti = {}
        conti = conti if isinstance(conti, dict) else {}
        prima = json.loads(json.dumps(conti))
        if stato == "vivo":
            morto = False
            conti.pop(handle, None)
        elif stato == "finito":
            morto = True
            conti.pop(handle, None)
        else:
            c, morto = _conta_non_visto(conti.get(handle), adesso)
            if morto:
                conti.pop(handle, None)
            else:
                conti[handle] = c
        if morto and segna_morto:
            conti["_morti"] = sorted(set(conti.get("_morti") or []) | {handle})
        if conti != prima:
            _scrivi_json(TERMINALI_NON_VISTI, conti)
    return morto


def _processo_vivo(pid):
    ""

    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    try:
        r = subprocess.run(
            ["ps", "-o", "command=", "-p", str(pid)], capture_output=True, text=True, timeout=10
        )
    except (OSError, subprocess.TimeoutExpired):
        return True
    return "-sottofondo" in (r.stdout or "")


def _comprensione_viva(com):
    ""

    if com.get("pid"):
        return _processo_vivo(com["pid"])
    return terminale_vivo(com.get("terminale")) is not False


def _scrivi_json(percorso, dati):
    percorso = Path(percorso)
    percorso.parent.mkdir(parents=True, exist_ok=True)
    tmp = percorso.with_name(percorso.name + f".tmp{os.getpid()}")
    tmp.write_text(json.dumps(dati, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, percorso)


def _titolo(r, prefisso):
    t = re.sub(r"\s+", " ", r.get("titolo") or r["id"]).strip()
    return f"{prefisso} · {t[:48]}" + ("…" if len(t) > 48 else "")


@contextlib.contextmanager
def _uno_alla_volta():
    LUCCHETTO_AVVII.parent.mkdir(parents=True, exist_ok=True)
    with open(LUCCHETTO_AVVII, "a+") as fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Errore(FRASI["altra_sessione_in_apertura"]) from None
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


@contextlib.contextmanager
def _lucchetto(percorso, aspetta=True):
    ""
    percorso.parent.mkdir(parents=True, exist_ok=True)
    with open(percorso, "a+") as fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX if aspetta else fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)




ATTESA_GESTO_S = float(os.environ.get("SB_ATTESA_GESTO_S") or 60)


@contextlib.contextmanager
def _lucchetto_atteso(percorso, secondi=None):
    ""

    secondi = ATTESA_GESTO_S if secondi is None else secondi
    percorso.parent.mkdir(parents=True, exist_ok=True)
    with open(percorso, "a+") as fh:
        fine = time.time() + secondi
        while True:
            try:
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.time() >= fine:
                    yield False
                    return
                time.sleep(0.1)
        try:
            yield True
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


@contextlib.contextmanager
def _scrittura_archivio(a):
    ""




    lucchetto = getattr(a, "lucchetto", None)
    if not callable(lucchetto):
        yield
        return
    with lucchetto():
        yield


def _apri_pannello(cartella, titolo, attrezzi, primo_messaggio, vietati=""):
    ""















    vuoto = cartella / "mcp-vuoto.json"
    vuoto.write_text('{"mcpServers": {}}\n')
    cartella_in_impostazioni = json.dumps(
        {"permissions": {"additionalDirectories": [str(cartella)]}}
    )


    parti = [
        "command",
        "claude",
        "--settings",
        cartella_in_impostazioni,
        "--tools",
        attrezzi,
        "--strict-mcp-config",
        "--mcp-config",
        str(vuoto),
    ]
    if vietati:
        parti += ["--disallowedTools", vietati]
    parti += ["-n", titolo, primo_messaggio]
    comando = f"cd {shlex.quote(str(ROOT))} && " + " ".join(
        shlex.quote(p) if p != "command" else p for p in parti
    )
    d = _terminale(
        "terminal",
        "create",
        "--worktree",
        f"path:{ROOT}",
        "--title",
        titolo,
        "--command",
        comando,
        timeout=60,
    )
    t = (d or {}).get("terminal") or d or {}
    handle = t.get("handle") or ""
    if not handle:
        raise Errore(FRASI["terminale_non_apre"])
    return handle, str(t.get("leafId") or "")


def _primo_messaggio(cartella, cosa):
    return (
        f"You are a session dedicated to an Inspiration idea, opened by the user in SBK. Your folder is {cartella}. "
        f"Read {cosa} in that folder and get started. Write only there."
    )


def _account_runner(chi):
    ""

    modulo = POOL_SWITCH / "account_runner.py"
    try:
        if not modulo.is_file():
            raise ImportError(str(modulo))
        m = sys.modules.get("account_runner")
        if m is None or Path(getattr(m, "__file__", "") or "").resolve() != modulo.resolve():
            spec = importlib.util.spec_from_file_location("account_runner", modulo)
            m = importlib.util.module_from_spec(spec)
            sys.modules["account_runner"] = m
            spec.loader.exec_module(m)
    except (ImportError, OSError, AttributeError):
        sys.modules.pop("account_runner", None)
        raise Errore(
            FRASI.get(f"{chi}_quota_manca")
            or FRASI["quota_manca" if chi == "comprensione" else "rilettura_quota_manca"]
        ) from None
    return m


def _quando_torna(fino):
    ""

    if not fino:
        return ""
    try:
        return ", the first comes back at " + datetime.datetime.fromtimestamp(float(fino)).strftime(
            "%H:%M"
        )
    except (TypeError, ValueError, OSError, OverflowError):
        return ""


def _modello(chi):
    ""

    try:
        return MODELLO_PER_LAVORO[chi]
    except KeyError:
        raise Errore(FRASI["lavoro_sconosciuto"].format(chi=chi)) from None


def _prestito_in_vista(chi):
    ""





    sbq = _account_runner(chi)
    try:
        d = sbq.disponibile(_modello(chi), strumento=STRUMENTO_SOTTOFONDO[chi])
    except sbq.Vietato as e:
        print(f"{_adesso()} loan: AccountPool says no ({e})", file=sys.stderr, flush=True)
        raise Errore(FRASI["prestito_vietato"]) from None
    except Exception as e:  # noqa: BLE001
        print(
            f"{_adesso()} loan: AccountPool doesn't answer on who would give ({e!r}), the background decides",
            file=sys.stderr,
            flush=True,
        )
        return sbq
    if not isinstance(d, dict) or d.get("account") or d.get("occupato"):
        return sbq
    if chi == "comprensione":

        acceso = _ritmo_acceso()
        e = Errore(
            FRASI["quota_nessuno" if acceso else "quota_nessuno_spento"].format(
                quando=_quando_torna(d.get("fino"))
            )
        )
        e.promette = (
            acceso
        )
        raise e
    raise Errore(
        (FRASI.get(f"{chi}_quota_nessuno") or FRASI["rilettura_quota_nessuno"]).format(
            quando=_quando_torna(d.get("fino"))
        )
    )


def _attesa_parole(secondi):
    ""
    if secondi >= 120:
        return f"{secondi // 60} minutes"
    if secondi >= 60:
        return "one minute"
    return f"{secondi} seconds"


def _prendi_prestito(sbq, chi, voci, titolo):
    ""



    nome = STRUMENTO_SOTTOFONDO[chi]
    modello = _modello(chi)
    args = {
        "audit": ",".join(str(v) for v in voci),
        "lavoro": str(titolo)[:80],
        "dominio": "sbk",
        "durata_max": TETTO_COMPRENSIONE_S + 600,
    }
    try:
        try:
            return sbq.prendi(nome, modello, **args), None
        except sbq.Occupato as e:
            if ATTESA_PRESTITO_S <= 0:
                raise
            print(
                f"{_adesso()} {chi}: {e.perche}, waiting up to {ATTESA_PRESTITO_S // 60} minutes",
                flush=True,
            )
            return sbq.prendi(nome, modello, attesa=ATTESA_PRESTITO_S, **args), None
    except sbq.Occupato as e:
        return None, (
            "occupato",
            FRASI[f"{chi}_prestito_occupato"].format(attesa=_attesa_parole(ATTESA_PRESTITO_S)),
            e.perche,
        )
    except sbq.Nessuno as e:
        return None, (
            "nessuno",
            FRASI[f"{chi}_prestito_nessuno"].format(quando=_quando_torna(e.fino)),
            e.perche,
        )
    except sbq.Vietato as e:
        return None, ("vietato", FRASI.get(f"{chi}_prestito_vietato") or str(e), str(e))


def _esito_claude(cartella):
    ""
    try:
        d = json.loads((Path(cartella) / "claude-esito.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def _comando_claude(cartella, attrezzi, primo_messaggio, vietati, titolo, modello):
    ""



    vuoto = cartella / "mcp-vuoto.json"
    vuoto.write_text('{"mcpServers": {}}\n')
    parti = [
        CLAUDE,
        "-p",
        "--add-dir",
        str(cartella),
        "--tools",
        attrezzi,
        "--strict-mcp-config",
        "--mcp-config",
        str(vuoto),
        "--permission-mode",
        "bypassPermissions",
        "--output-format",
        "json",
        "--model",
        modello,
    ]
    if vietati:
        parti += ["--disallowedTools", vietati]
    parti += ["-n", titolo, primo_messaggio]
    return parti


def _comprensione_in_sottofondo(cartella, titolo):
    ""

    log = open(cartella / "processo.log", "a")  # noqa: SIM115 stays open in the child process
    p = subprocess.Popen(
        [
            str(VENV if VENV.exists() else sys.executable),
            "-I",
            str(Path(__file__)),
            "comprensione-sottofondo",
            "--cartella",
            str(cartella),
            "--titolo",
            titolo,
        ],
        stdout=log,
        stderr=log,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
        cwd=str(ROOT),
    )
    return p.pid


def _voci_del_contesto(cartella):
    try:
        ctx = json.loads((Path(cartella) / "CONTESTO.json").read_text(encoding="utf-8"))
        return [str(v.get("id")) for v in ctx.get("voci") or [] if v.get("id")]
    except (OSError, ValueError, AttributeError):
        return []


def _risorse():
    ""
    if str(ROOT / "tools") not in sys.path:
        sys.path.insert(0, str(ROOT / "tools"))
    import sbk_resources as sr

    return sr


def _pressione():
    ""


    sr = _risorse()
    finta = os.environ.get("SB_FINTA_PRESSIONE")
    if finta:
        try:
            seg = float(Path(finta).read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            seg = 0.0
    else:
        seg = sr.pressure().seg_ratio
    return seg, sr.SEG_OK, sr.SEG_WARN


def _con_memoria(fai, nome="inspiration-comprensione", attesa_s=1800, soglia=None):
    ""





    if os.environ.get("SB_FINTO_LEASE"):
        return fai()
    sr = _risorse()

    if soglia is None:
        soglia = min(float(os.environ.get("SB_SOGLIA_AMMISSIONE") or 65) / 100, sr.SEG_YIELD - 0.02)
    frazione = 0.03
    scadenza = time.time() + attesa_s
    while True:
        pressione = _pressione()[0]
        if pressione < soglia:
            lz = sr.Lease(nome, need_frac=frazione)
            lz.registra(
                frazione
            )
            try:
                return fai()
            finally:
                lz.release()
        if time.time() >= scadenza:
            return None
        print(
            f"{_adesso()} {nome}: the Mac's pressure is at {pressione * 100:.0f}%, waiting for it to drop below {soglia * 100:.0f}%",
            flush=True,
        )
        time.sleep(60)


def comprensione_sottofondo(cartella, titolo):
    ""




    return _sessione_sottofondo(
        Path(cartella),
        titolo,
        "SESSIONE-COMPRENSIONE.md",
        ATTREZZI_COSTRUZIONE,
        VIETATI_COSTRUZIONE,
        "comprensione",
        _voci_del_contesto(cartella),
    )



PASSO_GUARDIA_S = float(os.environ.get("SB_PASSO_GUARDIA_S") or 5)


def _ferma_gruppo(proc, term_s=5, kill_s=3):
    ""

    for segnale, attesa in ((15, term_s), (9, kill_s)):
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(proc.pid, segnale)
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=attesa)
            return


def _aspetta_claude(proc, guardia=None):
    ""

    if guardia is None:
        try:
            return proc.wait(timeout=TETTO_COMPRENSIONE_S)
        except subprocess.TimeoutExpired:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(proc.pid, 15)
            with contextlib.suppress(subprocess.TimeoutExpired):
                proc.wait(timeout=30)
            return "tempo"
    fine = time.time() + TETTO_COMPRENSIONE_S
    while True:
        with contextlib.suppress(subprocess.TimeoutExpired):
            return proc.wait(timeout=PASSO_GUARDIA_S)
        if guardia():
            _ferma_gruppo(proc)
            return "memoria"
        if time.time() >= fine:
            _ferma_gruppo(proc, term_s=30)
            return "tempo"


def _guardia_memoria():
    ""
    seg, _ok, warn = _pressione()
    if seg >= warn:
        print(
            f"{_adesso()} arretrati: memory at {seg * 100:.0f}%, over {warn * 100:.0f}%, stopping the session",
            flush=True,
        )
        return True
    return False


def _sessione_sottofondo(cartella, titolo, istruzioni, attrezzi, vietati, chi, voci, guardia=None):
    ""








    processo = cartella / "processo.json"
    stato = {
        "pid": os.getpid(),
        "titolo": titolo,
        "chi": chi,
        "inizio": _adesso(),
        "fine": "",
        "uscita": None,
        "account": "",
    }
    _scrivi_json(processo, stato)

    def fermo(motivo, codice="", dettaglio=""):
        ""


        if not (cartella / "ESITO.json").is_file():
            _scrivi_json(
                cartella / "ESITO.json",
                {
                    "stato": "fermo",
                    "motivo": motivo,
                    "voci": list(voci),
                    "quando": _adesso(),
                    "da": "processo",
                    **({"codice": codice} if codice else {}),
                    **({"dettaglio": dettaglio} if dettaglio else {}),
                },
            )

    def chiudi(uscita):
        stato.update(fine=_adesso(), uscita=uscita)
        _scrivi_json(processo, stato)
        return uscita

    try:
        modello = _modello(chi)
    except Errore as e:
        fermo(str(e), codice="lavoro-sconosciuto")
        return chiudi(2)
    try:
        sbq = _account_runner(chi)
    except Errore as e:
        fermo(str(e), codice="senza-prestiti")
        return chiudi(2)
    cmd = _comando_claude(
        cartella, attrezzi, _primo_messaggio(cartella, istruzioni), vietati, titolo, modello
    )
    esito_claude = {}

    def gira():
        ""


        prestito, guaio = _prendi_prestito(sbq, chi, voci, titolo)
        if prestito is None:
            return guaio
        with prestito as p:
            stato.update(account=p.account, prestito=p.id)
            _scrivi_json(processo, stato)
            print(
                f"{_adesso()} {chi}: claude starting ({titolo}, account {p.account} on loan from AccountPool, {p.id})",
                flush=True,
            )
            with open(cartella / "claude-esito.json", "w") as out:
                try:
                    proc = subprocess.Popen(
                        cmd,
                        cwd=str(ROOT),
                        env=p.ambiente(),
                        stdin=subprocess.DEVNULL,
                        stdout=out,
                        start_new_session=True,
                    )
                except OSError as e:


                    print(f"{_adesso()} {chi}: claude won't start ({e!r})", flush=True)
                    p.restituisci("did not start")
                    return ("lancio", repr(e)[:160])

                stato["claude_partito"] = _adesso()
                _scrivi_json(processo, stato)
                uscita = _aspetta_claude(proc, guardia)
            esito_claude.update(_esito_claude(cartella))
            if esito_claude:
                with contextlib.suppress(Exception):
                    p.uso(
                        esito_claude
                    )
            for nome in ("ESITO.json", "RILETTURA.json", "SMISTAMENTO.jsonl"):
                if (cartella / nome).is_file():
                    with contextlib.suppress(Exception):
                        p.prodotto(cartella / nome)
            finale = _json_di(cartella / "ESITO.json")
            finale = finale if isinstance(finale, dict) else {}
            p.restituisci(
                "over three hours"
                if uscita == "tempo"
                else "stopped for memory"
                if uscita == "memoria"
                else str(finale.get("stato") or "no outcome")
            )
            return uscita




    memoria = {}
    if chi == "rilettura":
        memoria = {"nome": "inspiration-rilettura"}
    elif chi == "arretrati":
        memoria = {"nome": "inspiration-arretrati", "attesa_s": 0, "soglia": _pressione()[1]}
    with _lucchetto(LUCCHETTO_RILETTURA if chi == "rilettura" else LUCCHETTO_COMPRENSIONE):
        uscita = _con_memoria(gira, **memoria)
    if uscita is None:
        fermo(FRASI[f"{chi}_senza_memoria"], codice="memoria")
        return chiudi(75)
    if uscita == "memoria":
        fermo(FRASI[f"{chi}_memoria_alta"], codice="memoria-alta")
        return chiudi(75)
    if isinstance(uscita, tuple) and uscita[0] == "lancio":
        fermo(FRASI[f"{chi}_non_partita"], codice="lancio", dettaglio=uscita[1])
        return chiudi(3)
    if isinstance(uscita, tuple):
        codice, motivo, dettaglio = uscita
        print(f"{_adesso()} {chi}: no loan from AccountPool, {dettaglio}", flush=True)
        fermo(motivo, codice=f"prestito-{codice}", dettaglio=str(dettaglio)[:160])
        return chiudi({"occupato": 76, "nessuno": 7}.get(codice, 2))
    if uscita == "tempo":
        fermo(FRASI[f"{chi}_tempo"], codice="tempo")
        return chiudi(1)
    print(
        f"{_adesso()} {chi}: claude closed, exit {uscita}, "
        f"{esito_claude.get('subtype') or '-'}, {esito_claude.get('num_turns') or '?'} turns",
        flush=True,
    )
    if not (cartella / "ESITO.json").is_file():

        dettaglio = ""
        if esito_claude.get("is_error") or uscita != 0:
            dettaglio = str(esito_claude.get("result") or esito_claude.get("subtype") or "")[:160]
            dettaglio = dettaglio or f"uscita {uscita}"
        fermo(FRASI[f"{chi}_senza_esito"], codice="senza-esito", dettaglio=dettaglio)
        return chiudi(1 if uscita == 0 else uscita)
    try:
        finale = json.loads((cartella / "ESITO.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        finale = {}
    return chiudi(0 if finale.get("stato") == "fatto" else 1)





def _json_di(percorso):
    try:
        return json.loads(Path(percorso).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _parole_di_owner(r):
    ""

    out, visti = [], set()

    def metti(quando, via, testo, **altro):
        testo = " ".join(str(testo or "").split())
        if not testo or testo in visti:
            return
        visti.add(testo)
        out.append({"quando": str(quando or ""), "via": str(via or ""), "testo": testo, **altro})

    c = r.get("cattura") or {}
    metti(c.get("quando"), "frase accanto al link", c.get("testo_di_owner"))
    for p in r.get("pareri") or []:
        if not isinstance(p, dict) or p.get("tolto") or p.get("sostituito"):
            continue
        if p.get("audio") and (p.get("audio_stato") or "da trascrivere") != "trascritto":
            continue
        altro = {}
        if p.get("domande"):
            altro["domande"] = [str(x) for x in p["domande"]]
        elif p.get("domanda"):
            altro["domande"] = [str(p["domanda"])]
        if p.get("su") == "perche":
            altro["su"] = "perche"
        metti(p.get("quando"), p.get("via"), p.get("trascrizione") or p.get("testo"), **altro)
    return out


def _scelte_di_owner(r):
    ""

    try:
        sc = _scope_di(arch(), r)
    except Exception:  # noqa: BLE001 - no archive, no choices
        return {}
    return {k: sc.get(k) for k in sorted(sc.get("campi_di_owner") or []) if k in CAMPI_DI_OWNER}


def _impronta_parole(r):
    ""


    testi = [x["testo"] for x in _parole_di_owner(r)]
    scelte = _scelte_di_owner(r)
    if scelte:
        testi.append(json.dumps(scelte, ensure_ascii=False, sort_keys=True))
    return hashlib.sha256(json.dumps(testi, ensure_ascii=False).encode()).hexdigest()[:16]


def _ultima_risposta(a, r):
    ""

    dall_app = [x for x in _parole_di_owner(r) if x["via"].startswith("app")]
    scelte = _scelte_di_owner(r)
    if not dall_app and not scelte:
        return None
    if not dall_app:

        sc = _scope_di(a, r)
        return {
            "quando": str(sc.get("quando") or _adesso()),
            "via": "app, choice in the scope",
            "testo": "The user chose " + ", ".join(f"{k} {v}" for k, v in scelte.items()),
            "domande": [],
            "scelte": scelte,
        }
    u = dall_app[-1]
    testi = {d["id"]: d["testo"] for d in a.domande_di(r)}
    out = {
        "quando": u["quando"],
        "via": u["via"],
        "testo": u["testo"],
        "domande": [{"id": i, "testo": testi.get(i, "")} for i in u.get("domande") or []],
    }

    if u["testo"].rstrip().endswith("?") and not u.get("domande"):
        out["forma"] = "domanda"
    if scelte:
        out["scelte"] = scelte
    return out


def _contesto_rilettura(a, r, ultima, cl):
    ""

    v = _contesto(r)
    pc = r["lavorazione"]["perche"]
    dossier = str(((v.get("comprensione") or {}).get("dossier")) or "") or str(
        CASA_ARCHIVIO / "contenuti" / a.nome_cartella(r["id"]) / "DOSSIER.md"
    )
    return {
        "voci": [r["id"]],
        "voce": v,
        "dossier": dossier,
        "cartella_contenuti": str(_cartella_contenuti(a, r)),
        "parole_di_owner": _parole_di_owner(r),
        "risposta_nuova": ultima,
        "perche_di_adesso": {
            k: pc.get(k)
            for k in (
                "esito",
                "testo",
                "dove_arrivare",
                "progetto",
                "sicurezza",
                "su_cosa_poggia",
                "da",
                "quando",
            )
        },
        "domande": a.domande_di(r),
        "esiti": list(
            getattr(
                a, "ESITI", ("ispirazione", "da tenere", "flusso", "funzione", "contenuto", "altro")
            )
        ),
        "brief_perche": str(CASA_ARCHIVIO / "PERCHE-BRIEF.md"),
        "cartella": str(cl),
        "avvio": "risposta",


        "modo": "confermato" if pc.get("confermato") else "proposta",
        "correzione_di_owner": str(pc.get("correzione") or ""),

        "smistamento_di_adesso": (r["lavorazione"].get("smistamento") or {}).get("proposta") or {},
        "smistamento_confermato": bool(
            (r["lavorazione"].get("smistamento") or {}).get("confermato")
        ),
        "sottofondo": True,

        "adesso": _adesso(),


        **_contesto_scope(a, r),
    }


def _contesto_scope(a, r):
    ""

    sc = _scope_di(a, r)
    if not sc:
        return {}
    return {
        "scope_di_adesso": sc,
        "scope_confermato": _confermato(sc),
        "campi_di_owner": [k for k in sc.get("campi_di_owner") or [] if k in CAMPI_DI_OWNER],
        "domande_di_owner": list(sc.get("domande_di_owner") or []),
        "strade": list(STRADE),
        "tipi": list(TIPI_SCOPE),
        "progetto_in_testa": str((r.get("destinazione") or {}).get("progetto") or ""),
    }


def _rilettura_in_sottofondo(cartella, titolo, voce):
    ""
    log = open(cartella / "processo.log", "a")  # noqa: SIM115 stays open in the child process
    p = subprocess.Popen(
        [
            str(VENV if VENV.exists() else sys.executable),
            "-I",
            str(Path(__file__)),
            "rilettura-sottofondo",
            "--cartella",
            str(cartella),
            "--titolo",
            titolo,
            "--voce",
            voce,
        ],
        stdout=log,
        stderr=log,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
        cwd=str(ROOT),
    )
    return p.pid


def _rilettura_voce(a, note, r, ultima, impronta, avvio):
    ""


    ident = r["id"]
    cl = a.cartella_lavorazione(ident, crea=True) / "rilettura"
    cl.mkdir(parents=True, exist_ok=True)
    (cl / "SESSIONE-RILETTURA.md").write_text(
        (MODELLI / "SESSIONE-RILETTURA.md").read_text(encoding="utf-8"), encoding="utf-8"
    )
    for vecchio in ("ESITO.json", "RILETTURA.json", "claude-esito.json", "processo.json"):
        with contextlib.suppress(OSError):
            (cl / vecchio).unlink()
    (cl / "CONTESTO.json").write_text(
        json.dumps(_contesto_rilettura(a, r, ultima, cl), ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8",
    )
    titolo = _titolo(r, "Re-read")
    nota = {
        "pid": None,
        "titolo": titolo,
        "aperta_quando": _adesso(),
        "chiusa_quando": "",
        "cartella": str(cl),
        "avvio": avvio,
        "impronta_parole": impronta,
        "risposta_quando": ultima["quando"],
        "risposta_domande": [d["id"] for d in ultima["domande"]],
        "modo": "confermato" if r["lavorazione"]["perche"].get("confermato") else "proposta",
        "esito": {},
    }
    sc = _scope_di(a, r)
    if sc:
        nota["scope_versione"] = int(sc.get("versione") or 0)
        nota["scope_confermato"] = _confermato(sc)
    try:
        _prestito_in_vista("rilettura")
        cosa = f"re-read started in the background with their answer from {ultima['quando'][11:16]} ({titolo})"
    except Errore as e:
        nota["chiusa_quando"] = _adesso()
        nota["esito"] = {"stato": "fermo", "motivo": str(e), "quando": _adesso()}
        cosa = f"re-read did not start, {e}"









    with _lucchetto_atteso(LUCCHETTO_SMISTA), _scrittura_archivio(a):
        if not nota["chiusa_quando"]:
            try:
                nota["pid"] = _rilettura_in_sottofondo(cl, titolo, ident)
            except (OSError, subprocess.SubprocessError) as e:



                print(f"{_adesso()} re-read did not start, {e!r}", flush=True)
                nota["chiusa_quando"] = _adesso()
                nota["esito"] = {
                    "stato": "fermo",
                    "motivo": FRASI["rilettura_non_partita"],
                    "quando": _adesso(),
                    "dettaglio": repr(e)[:160],
                }
                cosa = f"re-read stopped, {FRASI['rilettura_non_partita']}"
        note = a.carica()
        r = note[ident]
        r["lavorazione"]["rilettura"] = nota
        a._segna(r, cosa, "rilettura", "SBK")
        a.salva(note)
    return nota


def _solo_domande_di_sessione(a, r, ultima):
    ""

    ids = [str(d.get("id") or "") for d in (ultima or {}).get("domande") or []]
    if not ids:
        return False

    vere = set()
    if ((r.get("lavorazione") or {}).get("sessione") or {}).get("aperta_quando"):
        vere.add("sessione dello spunto")
    if ((r.get("attivita") or {}).get("agente") or {}).get("avviato_quando"):
        vere.add("sessione di lavoro")
    da = {str(d.get("id")): str(d.get("da") or "") for d in a.domande_di(r)}
    return all(da.get(i) in vere for i in ids)


def _rilettura_dopo_risposta(ident, forza=False):
    ""






    a = arch()
    note = a.carica()
    r = note.get(ident)
    if not r:
        return None

    def no(motivo):
        print(f"{_adesso()} re-read won't start, {motivo}", flush=True)
        return None

    fase = a.fase_di(r)


    sc = _scope_di(a, r)
    raddrizzato = bool(sc) and not _confermato(sc) and str(sc.get("da") or "") == "owner"
    if fase in ("da capire", "a parte") or (
        fase not in ("perche", "lavorazione") and not raddrizzato
    ):
        return no(f"the item is in phase {fase}, the idea's session re-reads it")
    pc = r["lavorazione"]["perche"]
    file_scheda = str((r["lavorazione"].get("scheda") or {}).get("file") or "")
    if fase == "lavorazione" and file_scheda and not raddrizzato:
        q = a._assoluto(file_scheda) if hasattr(a, "_assoluto") else Path(file_scheda)
        if q and Path(q).is_file():
            return no("the card already exists, with Work on it the session re-reads it")
    if not pc.get("testo"):
        return no("the reason isn't proposed yet")
    if pc.get("correzione_in_arrivo"):
        return no("the spoken correction to the reason is on its way")
    if a.sessione_aperta(r):
        return no("the idea's session is open and receives resume")
    if ((r.get("attivita") or {}).get("agente") or {}).get("avviato_quando") and not raddrizzato:
        return no("the job is started")
    if any(c["voce"] == ident for c in a.coda_audio(note)):
        return no("one of their audios is still to be transcribed")
    ri = r["lavorazione"].get("rilettura") or {}
    if ri.get("aperta_quando") and not ri.get("chiusa_quando"):
        if _processo_vivo(ri.get("pid")):
            return no("a re-read is already in progress, at the end it also re-reads the new words")
        _chiudi_rilettura(ident, Path(str(ri.get("cartella") or "")))
        note = a.carica()
        r = note[ident]
        ri = r["lavorazione"].get("rilettura") or {}



        if (
            ri.get("aperta_quando")
            and not ri.get("chiusa_quando")
            and _processo_vivo(ri.get("pid"))
        ):
            return no("a re-read is already in progress, at the end it also re-reads the new words")
    ultima = _ultima_risposta(a, r)
    if not ultima:
        return no("The user hasn't said anything in the app about this item yet")
    if _solo_domande_di_sessione(a, r, ultima):
        return no("the answer only covers questions from the idea's session, which reads them")
    impronta = _impronta_parole(r)
    if not forza and ri.get("impronta_parole") == impronta:
        return no("their words have already been re-read")
    cl = a.cartella_lavorazione(ident, crea=True)
    with _lucchetto(cl / ".rilettura-attesa.lock", aspetta=False) as mio:
        if not mio:
            return no("another process is already waiting for quiet to re-read")
        for _ in range(60):
            if QUIETE_RILETTURA_S <= 0:
                break
            time.sleep(QUIETE_RILETTURA_S)
            note = a.carica()
            r = note[ident]
            if any(c["voce"] == ident for c in a.coda_audio(note)):
                return no("a new audio of theirs is to be transcribed, I'll restart after transcription")
            nuova = _impronta_parole(r)
            if nuova == impronta:
                break
            impronta = nuova
            ultima = _ultima_risposta(a, r) or ultima



        file_scheda = str((r["lavorazione"].get("scheda") or {}).get("file") or "")
        q = (
            (a._assoluto(file_scheda) if hasattr(a, "_assoluto") else Path(file_scheda))
            if file_scheda
            else None
        )
        if a.fase_di(r) == "lavorazione" and q and Path(q).is_file() and not raddrizzato:
            return no("after the wait the card already exists, with Work on it the session re-reads it")
        if a.sessione_aperta(r):
            return no(
                "after the wait the idea's session is open, it already has your answer and receives resume"
            )
        if ((r.get("attivita") or {}).get("agente") or {}).get(
            "avviato_quando"
        ) and not raddrizzato:
            return no("after the wait the job is started")
        if _solo_domande_di_sessione(a, r, ultima):
            return no("the answer only covers questions from the idea's session, which reads them")
        return _rilettura_voce(
            a, note, r, ultima, impronta, avvio="a mano" if forza else "risposta"
        )


def _applica_rilettura(a, r, dati, da=DA_RILETTURA):
    ""




    out = {
        "perche_riscritto": False,
        "perche_uguale": False,
        "domande_chiuse": [],
        "domande_nuove": 0,

        "domande_trattenute": [],
    }
    pc = r["lavorazione"]["perche"]
    o = dati.get("perche") if isinstance(dati.get("perche"), dict) else None


    _forma_riletta(a, r, dati, out)
    if _applica_scope_riletto(a, r, dati, out, da):
        o = None
        dati = {k: v for k, v in dati.items() if k != "smistamento"}
    if o and pc.get("confermato"):


        nuovi = {
            k: " ".join(str(o.get(k) or "").split())
            for k in ("dove_arrivare", "progetto", "su_cosa_poggia")
        }
        nuovi = {k: v for k, v in nuovi.items() if v and v != str(pc.get(k) or "")}
        if nuovi:
            pc.setdefault("riletture_a_perche_confermato", []).append(
                {
                    "quando": _adesso(),
                    "prima": {k: pc.get(k) for k in nuovi},
                    "da": da,
                }
            )
            pc.update(nuovi)
            pc["riletto_quando"] = _adesso()
            a._segna(
                r,
                "re-read with your answer, the reason stays yours, rewritten "
                + ", ".join(
                    {
                        "dove_arrivare": "where you want to get",
                        "progetto": "the project",
                        "su_cosa_poggia": "what it rests on",
                    }[k]
                    for k in nuovi
                ),
                "perché",
                da,
            )
            out["dove_riscritto"] = "dove_arrivare" in nuovi
        else:
            out["perche_uguale"] = True
    elif o:
        fonti = [str(x) for x in (o.get("fonti") or []) if x] or [
            str(RADICE / f) for f in (pc.get("fonti") or []) if f
        ]
        ok, motivo = a.metti_perche(r, {**o, "fonti": fonti}, da)
        out["perche_riscritto"] = bool(ok)
        out["perche_uguale"] = motivo == "uguale a prima"
    dom = dati.get("domande") if isinstance(dati.get("domande"), dict) else {}
    chiudi = getattr(a, "chiudi_domanda_superata", None)
    trattenuta = getattr(a, "domanda_trattenuta", None)
    for q in dom.get("superate") or []:
        if isinstance(q, dict) and q.get("id") and chiudi:
            d = chiudi(
                r,
                str(q["id"]),
                str(q.get("perche") or "your answer superseded it"),
                da,
            )
            if d:
                out["domande_chiuse"].append(str(q["id"]))
            elif trattenuta and trattenuta(r, str(q["id"])):
                out["domande_trattenute"].append(str(q["id"]))

    metti_sm = getattr(a, "metti_smistamento", None)
    if isinstance(dati.get("smistamento"), dict) and metti_sm:
        ok, _ = metti_sm(r, dati["smistamento"], da)
        out["smistamento_riscritto"] = bool(ok)
    aggiungi = getattr(a, "aggiungi_domanda", None)
    for q in dom.get("nuove") or []:
        if isinstance(q, dict) and q.get("testo") and aggiungi:
            prima = len(r["lavorazione"]["domande"])

            altro = {}
            if q.get("passo") and _accetta(aggiungi, "passo"):
                altro["passo"] = str(q["passo"])
            if q.get("policy") and _accetta(aggiungi, "policy"):
                altro["policy"] = True

            if q.get("fonte_norma") and _accetta(aggiungi, "fonte_norma"):
                altro["fonte_norma"] = q["fonte_norma"]

            if q.get("sostituisce") and _accetta(aggiungi, "sostituisce"):
                altro["sostituisce"] = str(q["sostituisce"])
            aggiungi(r, q["testo"], q.get("serve_per") or "", "perche", da, **altro)
            out["domande_nuove"] += len(r["lavorazione"]["domande"]) - prima
    return out


def _forma_riletta(a, r, dati, out):
    ""

    forma = str(dati.get("forma_risposta_nuova") or "")
    quando = str(dati.get("_risposta_quando") or "")
    pareri = r.get("pareri") or []
    indice = next(
        (
            i
            for i in range(len(pareri) - 1, -1, -1)
            if isinstance(pareri[i], dict)
            and pareri[i].get("su") == "scope"
            and not pareri[i].get("tolto")
            and (not quando or pareri[i].get("quando") == quando)
        ),
        None,
    )
    if indice is None:
        return
    testo = " ".join(
        str(pareri[indice].get("testo") or pareri[indice].get("trascrizione") or "").split()
    )
    if not forma and testo:
        dentro = any(
            " ".join(str(q.get("testo") or "").split()).casefold() == testo.casefold()
            for q in dati.get("domande_di_owner") or []
            if isinstance(q, dict)
        )
        forma = "domanda" if dentro else ""
    if forma and _cambia_forma(a, r, indice, forma):
        out["forma_cambiata"] = forma


def _applica_scope_riletto(a, r, dati, out, da=DA_RILETTURA):
    ""



    o = dati.get("scope") if isinstance(dati.get("scope"), dict) else None
    dds = [
        {k: str(q.get(k) or "") for k in ("testo", "risposta", "quando") if q.get(k)}
        for q in (dati.get("domande_di_owner") or [])
        if isinstance(q, dict) and q.get("testo")
    ]



    for q in dds:
        indice = _parere_della_domanda(r, q["testo"])
        if indice is not None:
            q["parere"] = indice
    if not (o or dds) or not hasattr(a, "metti_scope"):
        return False
    sc = _scope_di(a, r)
    di_owner = {k for k in sc.get("campi_di_owner") or [] if k in CAMPI_DI_OWNER}
    proposta = {
        k: v
        for k, v in (o or {}).items()
        if k not in di_owner and k not in ("campi_di_owner", "domande_di_owner")
    }


    if dds:
        proposta["domande_di_owner"] = _fondi_domande_di_owner(sc.get("domande_di_owner") or [], dds)
    if not proposta:
        out["scope_uguale"] = True
        return bool(o)
    ok, motivo = _metti_scope(a, r, proposta, da)
    out["scope_riscritto"] = ok and motivo != "proposta dopo la conferma"
    if motivo:
        out["scope_motivo"] = motivo
    if ok and motivo == "proposta dopo la conferma":
        out["proposta_dopo"] = True
    if dds:
        out["domande_di_owner"] = len(dds)


    if o and o.get("progetto") and "progetto" not in di_owner:
        _allinea_destinazione(a, r, _scope_di(a, r).get("progetto"), da)
    return bool(o)


def _allinea_destinazione(a, r, progetto, da):
    ""

    progetto = str(progetto or "").strip()
    dest = r.get("destinazione")
    if not progetto or not isinstance(dest, dict) or dest.get("progetto") == progetto:
        return False
    prima = str(dest.get("progetto") or "")
    dest.setdefault("progetti_di_prima", []).append(
        {"progetto": prima, "quando": _adesso(), "da": da}
    )
    dest["progetto"] = progetto
    if isinstance(r.get("a_mano"), dict):
        r["a_mano"]["destinazione"] = True
    a._segna(
        r,
        f"lead project on the idea from «{prima or 'none'}» to «{progetto}», as in the scope",
        "destinazione",
        da,
    )
    return True


def _parere_della_domanda(r, testo):
    ""
    k = " ".join(str(testo or "").split()).casefold()
    if not k:
        return None
    pareri = r.get("pareri") or []
    for i in range(len(pareri) - 1, -1, -1):
        p = pareri[i]
        if not isinstance(p, dict) or p.get("tolto") or p.get("su") not in ("scope", "perche"):
            continue
        detto = p.get("testo") or (
            p.get("trascrizione") if p.get("audio_stato") == "trascritto" else ""
        )
        if " ".join(str(detto or "").split()).casefold() == k:
            return i
    return None


def _fondi_domande_di_owner(prima, nuove):
    ""


    out = [dict(q) for q in prima if isinstance(q, dict)]

    def norma(t):
        return " ".join(str(t or "").split()).casefold()

    for q in nuove:
        uguale = next(
            (x for x in out if q.get("parere") is not None and x.get("parere") == q.get("parere")),
            None,
        ) or next(
            (
                x
                for x in out
                if norma(x.get("testo")) and norma(x.get("testo")) == norma(q.get("testo"))
            ),
            None,
        )
        if uguale is None:
            out.append(dict(q))
            continue
        if q.get("risposta"):
            uguale["risposta"] = q["risposta"]
        if not uguale.get("testo") and q.get("testo"):
            uguale["testo"] = q["testo"]
        if uguale.get("parere") is None and q.get("parere") is not None:
            uguale["parere"] = q["parere"]
    return out



CAMPI_SCOPE_CONTROLLO = (
    "versione",
    "da",
    "strada",
    "tipo",
    "progetto",
    "area",
    "chi",
    "delicato",
    "confermato",
    "confermato_versione",
    "campi_di_owner",
    "proposta_dopo",
    "cosa_intendi",
    "dove_arrivare",
)
TENTATIVI_CHIUSURA = 3


def _impronta_scope(a, r):
    sc = _scope_di(a, r)
    return json.dumps(
        {k: sc.get(k) for k in CAMPI_SCOPE_CONTROLLO}, ensure_ascii=False, sort_keys=True
    )


def _chiudi_rilettura(voce, cartella, dal_processo=False):
    ""









    ri = None
    for tentativo in range(TENTATIVI_CHIUSURA):
        fatta = _chiudi_rilettura_una(
            voce, cartella, rifai=tentativo > 0, dal_processo=dal_processo
        )
        if fatta is None:
            return ri
        ri, scritto = fatta
        if _impronta_scope(arch(), arch().carica()[voce]) == scritto:
            break
        print(
            f"{_adesso()} re-read of {voce}, the scope changed while I was closing: I re-apply it on the new one",
            flush=True,
        )
    note = arch().carica()

    if ri and voce in note and _impronta_parole(note[voce]) != ri.get("impronta_parole"):
        _rilettura_dopo_risposta(voce)
    return ri


def _chiudi_rilettura_una(voce, cartella, rifai=False, dal_processo=False):
    ""








    a = arch()
    with _lucchetto_atteso(LUCCHETTO_SMISTA) as mio:
        if not mio:
            print(
                f"{_adesso()} re-read of {voce}, the controls are busy: I'll close it on the next pass",
                flush=True,
            )
            return None
        with _scrittura_archivio(a):
            pronto = _chiudi_rilettura_prepara(a, voce, cartella, rifai, dal_processo)
            if pronto is None:
                return None
            note, ri, scritto, cosa = pronto
            a.salva(note)
    print(f"{_adesso()} re-read of {voce} closed, {cosa}", flush=True)
    return ri, scritto


def _chiudi_rilettura_prepara(a, voce, cartella, rifai, dal_processo=False):
    ""
    note = a.carica()
    r = note.get(voce)
    if not r:
        return None
    ri = r["lavorazione"].get("rilettura") or {}
    if not ri.get("aperta_quando") or (ri.get("chiusa_quando") and not rifai):
        return None



    if not dal_processo and not rifai and _processo_vivo(ri.get("pid")):
        return None
    esito = _json_di(cartella / "ESITO.json") or {}
    dati = _json_di(cartella / "RILETTURA.json")
    fatto = esito.get("stato") == "fatto"
    applicato = {}
    if fatto and isinstance(dati, dict):
        applicato = _applica_rilettura(
            a, r, {**dati, "_risposta_quando": str(ri.get("risposta_quando") or "")}
        )
        stato, motivo = "fatto", ""
    elif fatto:
        stato, motivo = "fermo", FRASI["rilettura_senza_proposta"]
    else:
        stato = "fermo"
        motivo = str(esito.get("motivo") or FRASI["rilettura_senza_esito"])

        if esito.get("dettaglio"):
            applicato = {**applicato, "dettaglio": str(esito["dettaglio"])}
        if not esito:
            if _a_vuoto(cartella):

                motivo = FRASI["rilettura_non_partita"]
            proc = _json_di(cartella / "processo.json") or {}
            if proc.get("uscita") is not None:
                applicato = {**applicato, "dettaglio": f"uscita {proc['uscita']}"}
    ri.update(
        chiusa_quando=_adesso(),
        esito={"stato": stato, "motivo": motivo, "quando": _adesso(), **applicato},
    )
    r["lavorazione"]["rilettura"] = ri
    cosa = f"re-read {stato}"
    if motivo:
        cosa += f", {motivo}"
    if applicato.get("scope_riscritto"):
        cosa += ", the scope is rewritten with their words"
    if applicato.get("proposta_dopo"):
        cosa += ", a new scope proposal is waiting for their yes"
    if applicato.get("domande_di_owner"):
        cosa += f", {applicato['domande_di_owner']} of their questions with the answer"
    if applicato.get("perche_riscritto"):
        cosa += ", the reason is rewritten with their words"
    elif applicato.get("dove_riscritto"):
        cosa += ", rewritten where they want to get"
    elif applicato.get("perche_uguale"):
        cosa += ", the reason stays the same"
    if applicato.get("domande_chiuse"):
        cosa += f", {len(applicato['domande_chiuse'])} questions superseded"
    if applicato.get("domande_trattenute"):



        n = len(applicato["domande_trattenute"])
        cosa += (
            ", one legal question stays open"
            if n == 1
            else f", {n} legal questions stay open"
        )
    if applicato.get("domande_nuove"):
        cosa += f", {applicato['domande_nuove']} new questions"
    if rifai:
        cosa += ", re-applied after a gesture of yours that arrived in the meantime"
    a._segna(r, cosa, "rilettura", "SBK")
    return note, ri, _impronta_scope(a, r), cosa


def rilettura_sottofondo(cartella, titolo, voce):
    ""

    cartella = Path(cartella)
    uscita = _sessione_sottofondo(
        cartella, titolo, "SESSIONE-RILETTURA.md", ATTREZZI_RILETTURA, "", "rilettura", [voce]
    )
    _chiudi_rilettura(voce, cartella, dal_processo=True)
    return uscita


def _riletture_importa():
    ""

    a = arch()
    note = a.carica()
    chiuse = []
    for i, r in note.items():
        ri = (r.get("lavorazione") or {}).get("rilettura") or {}
        if not ri.get("aperta_quando") or ri.get("chiusa_quando"):
            continue
        if _processo_vivo(ri.get("pid")):
            continue
        if _chiudi_rilettura(i, Path(str(ri.get("cartella") or ""))):
            chiuse.append(i)
    return chiuse


def rileggi_risposta(ident):
    ""

    nota = _rilettura_dopo_risposta(ident, forza=True)
    if not nota:
        raise Errore(FRASI["rilettura_niente"])
    return {
        "aperta": not nota.get("chiusa_quando"),
        "pid": nota.get("pid"),
        "titolo": nota.get("titolo"),
    }


def _contesto(r):
    ""
    a = arch()
    v = a.voce_export(r)
    tieni = ("id", "titolo", "autore", "url", "tipo", "piattaforma", "cattura", "copia", "contenuto_visto", "comprensione",
             "pareri", "destinazione", "stato", "fase", "domande", "lavorazione")
    return {k: v.get(k) for k in tieni}


def _durata(valore):
    ""
    try:
        d = float(str(valore).replace(",", "."))
    except (TypeError, ValueError):
        return None
    return d if d > 0 else None





def conferma(ident, esito="", correzione="", audio="", durata=None):
    a = arch()


    with _lucchetto_atteso(LUCCHETTO_SMISTA) as mio:
        if not mio:
            raise Errore(FRASI["smista_in_corso"])
        note = a.carica()
        r = a._prendi(note, ident)
        altro = {"durata": _durata(durata)} if _accetta(a.conferma_perche, "durata") else {}
        a.conferma_perche(
            r, esito=esito, correzione=correzione, audio=audio or None, via="app", **altro
        )

        _scope_coerente(a, r)
        _salva_e_segna(a, note, ident)
    _in_sottofondo(ident)
    r = note[ident]
    return {"fase": a.fase_di(r), "tocca": a.tocca_a(r)}



TUTTE = "tutte"


def _domande_a_vista_di(ident, dove):
    ""


    v = next((x for x in _voci_export() if str(x.get("id") or "") == ident), None)
    if v is None:
        return None
    try:
        return [str(x) for x in _parole().domande_a_vista(v, dove)]
    except Exception:  # noqa: BLE001 a board that doesn't respond must not stop the user's answer
        return None


def _agente_aperto(a, r):
    ""

    f = getattr(a, "sessione_aperta", None)
    if f:
        return bool(f(r))
    s = (r.get("lavorazione") or {}).get("sessione") or {}
    return bool(s.get("aperta_quando")) and not s.get("chiusa_quando")





AUDIO_RIFIUTATI = "rifiutati"


def _metti_da_parte(a, r, audio, perche):
    ""



    if not audio:
        return ""
    f = Path(str(audio))
    cartella = a.cartella_lavorazione(str(r.get("id") or "")) / "audio"
    try:
        if not f.is_file() or f.resolve().parent != cartella.resolve():
            return ""
        dove = cartella / AUDIO_RIFIUTATI
        dove.mkdir(exist_ok=True)
        nuovo = dove / f.name
        n = 1
        while nuovo.exists() or nuovo.with_suffix(".json").exists():
            nuovo = dove / f"{f.stem}-{n}{f.suffix}"
            n += 1
        biglietto = f.with_suffix(".json")
        dati = {}
        if biglietto.is_file():
            try:
                dati = json.loads(biglietto.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                dati = {}
        if not isinstance(dati, dict):
            dati = {"biglietto": dati}
        dati.setdefault("voce", str(r.get("id") or ""))
        dati["rifiutato"] = {"quando": _adesso(), "perche": perche, "file": f.name}
        os.replace(f, nuovo)
        if biglietto.is_file():
            os.replace(biglietto, nuovo.with_suffix(".json"))
        _scrivi_json(nuovo.with_suffix(".json"), dati)
    except OSError:
        return ""
    return str(nuovo)


def _lavoro_aperto(r):
    ""

    ag = (r.get("attivita") or {}).get("agente") or {}
    return bool(
        (ag.get("avviato_quando") or ag.get("pannello"))
        and not ag.get("ritorno")
        and str(ag.get("stato") or "") != "chiuso"
    )


def _tutte(a, r, dove, audio=""):
    ""





    aperte = [
        str(d.get("id"))
        for d in a.domande_di(r)
        if not d.get("chiusa") and not d.get("in_trascrizione")
    ]
    if not aperte:
        return TUTTE, {}
    vista = _domande_a_vista_di(str(r.get("id") or ""), dove)
    if vista is None:

        return "", {}
    queste = [i for i in vista if i in aperte]
    if not queste:
        return "", {}
    if _accetta(a.rispondi, "domande"):
        return TUTTE, {"domande": queste}
    if set(queste) == set(aperte):
        return TUTTE, {}

    _metti_da_parte(a, r, audio, FRASI["tutte_una_alla_volta"])
    raise Errore(FRASI["tutte_una_alla_volta"])


def rispondi(ident, domanda="", testo="", audio="", durata=None):
    a = arch()
    note = a.carica()
    r = a._prendi(note, ident)
    altro = {"durata": _durata(durata)} if _accetta(a.rispondi, "durata") else {}
    if domanda == TUTTE:

        domanda, piu = _tutte(a, r, "adesso", audio)
        altro.update(piu)
    a.rispondi(r, domanda, testo, audio or None, via="app", **altro)
    _salva_e_segna(a, note, ident, segna=not (audio and not testo))
    _in_sottofondo(ident)
    r = note[ident]
    return {"fase": a.fase_di(r), "tocca": a.tocca_a(r)}


def risposta_giusta(ident, domanda):
    ""

    a = arch()
    if not hasattr(a, "risposta_giusta"):
        raise Errore(FRASI["archivio_vecchio"])
    note = a.carica()
    r = a._prendi(note, ident)
    a.risposta_giusta(r, domanda)
    _salva_e_segna(a, note, ident)
    _in_sottofondo(ident)
    r = note[ident]
    return {"fase": a.fase_di(r), "tocca": a.tocca_a(r)}


def togli_risposta(ident, domanda):
    ""
    a = arch()
    if not hasattr(a, "togli_risposta"):
        raise Errore(FRASI["archivio_vecchio"])
    note = a.carica()
    r = a._prendi(note, ident)
    a.togli_risposta(r, domanda)
    _salva_e_segna(a, note, ident)
    _in_sottofondo(ident)
    r = note[ident]
    return {"fase": a.fase_di(r), "tocca": a.tocca_a(r)}


def _in_sottofondo(ident):
    ""



    if _cartella_sparita_col_pannello(ident):
        cl = _posto_del_giro(arch().cartella_lavorazione(ident), crea=True)
    else:
        cl = arch().cartella_lavorazione(ident, crea=True)
    try:
        if cl is None:
            raise NotADirectoryError("no place for the log")
        log = open(cl / "dopo-risposta.log", "a")  # noqa: SIM115 stays open in the child process
    except OSError:

        log = subprocess.DEVNULL
    subprocess.Popen(
        [
            str(VENV if VENV.exists() else sys.executable),
            "-I",
            str(Path(__file__)),
            "dopo-risposta",
            ident,
        ],
        stdout=log,
        stderr=log,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
        cwd=str(CASA_ARCHIVIO),
    )


def _avviso_in_sottofondo(ident):
    ""


    cl = _posto_del_giro(arch().cartella_lavorazione(ident), crea=True)
    try:
        if cl is None:
            raise NotADirectoryError("no place for the log")
        log = open(cl / "dopo-risposta.log", "a")  # noqa: SIM115 stays open in the child process
    except OSError:

        log = subprocess.DEVNULL
    subprocess.Popen(
        [
            str(VENV if VENV.exists() else sys.executable),
            "-I",
            str(Path(__file__)),
            "dopo-risposta",
            ident,
            "--solo-avviso",
        ],
        stdout=log,
        stderr=log,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
        cwd=str(CASA_ARCHIVIO),
    )



AVVISI_SENZA_CARTELLA = CASA_ARCHIVIO / ".avvisi"


def _avvisi_della_voce(nome, crea=False):
    ""




    p = AVVISI_SENZA_CARTELLA / nome
    try:
        if (p.exists() and not p.is_dir()) or (p.parent.exists() and not p.parent.is_dir()):
            raise NotADirectoryError(str(p))
        if crea:
            p.mkdir(parents=True, exist_ok=True)
        return p
    except OSError:
        _al_registro_del_giro(f".avvisi/{nome} is not a folder, the rule always sends")
        return None


def _posto_del_giro(cl, crea=False):
    ""





    if cl.is_dir():
        return cl
    return _avvisi_della_voce(cl.name, crea)


def _cartella_sparita_col_pannello(ident, r=None):
    ""






    try:
        a = arch()
        if a.cartella_lavorazione(ident).is_dir():
            return False
        if r is None:
            r = a.carica().get(ident)
        if not r or not a.sessione_aperta(r):
            return False
        h = (r["lavorazione"].get("sessione") or {}).get("terminale")
        return (_ricordo_del_pannello(ident, "sessione", h) or {}).get("file") is True
    except Exception:  # noqa: BLE001 when in doubt don't recreate: nothing is lost
        return True


def _audio_in_coda():
    ""

    try:
        a = arch()
        return {(str(c.get("voce")), str(c.get("audio"))) for c in a.coda_audio(a.carica())}
    except Exception:  # noqa: BLE001 the download doesn't die for this
        return set()


def _scomponi():
    ""

    if os.environ.get("SB_SCOMPONI"):
        return os.environ["SB_SCOMPONI"]
    for radice in (os.environ.get("SB_ARCHIVIO_RADICE"), str(RADICE)):
        if radice and (Path(radice) / GIRO_SCOMPONI / "scomponi.py").is_file():
            return str(Path(radice) / GIRO_SCOMPONI / "scomponi.py")
    return ""


def _trascrivi(ident):
    ""
    py = str(VENV if VENV.exists() else sys.executable)
    ambiente = dict(os.environ)
    scomponi = _scomponi()
    if scomponi:
        ambiente["SB_SCOMPONI"] = scomponi
    r = subprocess.run(
        [
            py,
            "-I",
            str(CASA_ARCHIVIO / "trascrivi-audio.py"),
            "--solo",
            ident,
            "--attendi-memoria",
            str(INTERVALLO_TENTATIVI_S),
        ],
        cwd=str(CASA_ARCHIVIO),
        capture_output=True,
        text=True,
        timeout=3600,
        env=ambiente,
    )
    print(
        (r.stdout or "").strip()[-2000:],
        (r.stderr or "").strip()[-1000:],
        f"uscita {r.returncode}",
        sep="\n",
        flush=True,
    )
    return r.returncode


def _aspetta_la_quiete(risposte):
    ""
    for _ in range(60):
        try:
            fa = time.time() - risposte.stat().st_mtime
        except OSError:
            break
        if fa >= QUIETE_S:
            break
        time.sleep(QUIETE_S - fa + 1)



DA_RIDIRE = ", da ridire"


def _file_risposte_del_pannello(a, r, chi):
    ""

    if chi == "sessione":
        return a.cartella_lavorazione(r["id"]) / "RISPOSTE.json"
    c = (r.get("attivita") or {}).get("agente", {}).get("cartella")
    q = a._assoluto(c) if c and hasattr(a, "_assoluto") else (Path(c) if c else None)
    return Path(q) / "RISPOSTE.json" if q else None


def _file_del_lavoro(ident):
    ""
    a = arch()
    r = a.carica().get(ident)
    return _file_risposte_del_pannello(a, r, "lavoro") if r else None





DETTO_AI_PANNELLI = CASA_ARCHIVIO / ".detto-ai-pannelli.json"


def _ricordi_dei_pannelli():
    try:
        d = json.loads(DETTO_AI_PANNELLI.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def _intero_o_niente(v):
    ""
    return v is None or (isinstance(v, int) and not isinstance(v, bool))


def _ricordo_valido(x):
    ""




    if not isinstance(x, dict) or not isinstance(x.get("terminale"), str):
        return None
    if x.get("file") is not None and not isinstance(x.get("file"), bool):
        return None
    if x.get("owner") is not None and not (isinstance(x.get("owner"), str) and x["owner"]):
        return None
    if not (_intero_o_niente(x.get("letto_ns")) and _intero_o_niente(x.get("altre"))):
        return None
    if x.get("quando") is not None and not isinstance(x.get("quando"), str):
        return None



    if x.get("letto_ns") is not None and x["letto_ns"] > time.time_ns():
        return None

    c = x.get("conti")
    if c is not None and not (
        isinstance(c, dict)
        and all(isinstance(k, str) and _intero_o_niente(v) and v is not None for k, v in c.items())
    ):
        return None
    return x


def _ricordo_del_pannello(ident, chi, handle):
    ""

    x = _ricordo_valido(_ricordi_dei_pannelli().get(f"{ident}:{chi}"))
    return x if x is not None and handle and x.get("terminale") == handle else None


def _ricorda_il_pannello(ident, chi, handle, owner=None, letto_ns=None, altre=None, conti=None):
    ""





    if not handle:
        return False
    k = f"{ident}:{chi}"
    try:
        with _lucchetto(DETTO_AI_PANNELLI.with_suffix(".lock")):
            d = _ricordi_dei_pannelli()

            x = _ricordo_valido(d.get(k)) or {}
            x = dict(x) if x.get("terminale") == handle else {}
            nuovo = {**x, "terminale": handle, "file": True}
            if owner is not None and int(letto_ns or 0) >= int(x.get("letto_ns") or 0):
                nuovo.update(owner=owner, letto_ns=int(letto_ns or 0), altre=altre, conti=conti)
            if nuovo != x:
                d[k] = {**nuovo, "quando": _adesso()}
                _scrivi_json(DETTO_AI_PANNELLI, d)
    except Exception:  # noqa: BLE001 any error: the memory isn't written, the caller sets the placeholder
        return False
    return True






RISPOSTE_NON_DI_OWNER = ("voce", "titolo")
PERCHE_NON_DI_OWNER = ("testo", "dove_arrivare", "esito")


def _impronta_di_owner(dati):
    ""

    d = {
        k: v
        for k, v in dati.items()
        if k not in RISPOSTE_FUORI_IMPRONTA and k not in RISPOSTE_NON_DI_OWNER
    }
    if isinstance(d.get("perche"), dict):
        d["perche"] = {k: v for k, v in d["perche"].items() if k not in PERCHE_NON_DI_OWNER}
    h = hashlib.sha256(json.dumps(d, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return h[:16]





_SCRITTO_DAL_LAVORO = ("agente del lavoro", "sessione di lavoro")
_SCRITTO_DALLO_SPUNTO = ("riportata dalla sessione nel suo", "sessione dello spunto")


def _chi_ha_scritto(p):
    ""



    if not isinstance(p, dict) or p.get("via") != "terminale":
        return None
    att = str(p.get("attribuzione") or "")
    if any(x in att for x in _SCRITTO_DAL_LAVORO):
        return "lavoro"
    if any(x in att for x in _SCRITTO_DALLO_SPUNTO):
        return "spunto"
    return "?"


def _pannello_di(chi):
    return "lavoro" if chi == "lavoro" else "spunto"


def _parole_dagli_altri(r, chi):
    ""





    io = _pannello_di(chi)
    n = 0
    for p in r.get("pareri") or []:
        chi_scrive = _chi_ha_scritto(p)
        if chi_scrive is None or p.get("tolto") or p.get("su") not in ("scope", "perche"):
            continue
        if chi_scrive != io:
            n += 1
    return n




_DA_TRASCRIZIONI = ("ritrascrivi", "trascrivi-audio")


def _conti_o_niente(a, r, chi):
    ""
    try:
        return _conti_di_owner(a, r, chi)
    except Exception:  # noqa: BLE001
        return None


def _solo_un_audio_che_aspetta(p):
    ""



    return (
        isinstance(p, dict)
        and bool(p.get("audio"))
        and not str(p.get("testo") or "").strip()
        and str(p.get("audio_stato") or "da trascrivere") == "da trascrivere"
    )


def _lunghezza(x):
    return len(x) if isinstance(x, list) else 0


def _conti_di_owner(a, r, chi):
    ""






    io = _pannello_di(chi)
    pareri = [p for p in (r.get("pareri") or []) if isinstance(p, dict)]
    pc = (r.get("lavorazione") or {}).get("perche") or {}
    return {
        "pareri": sum(
            1 for p in pareri if _chi_ha_scritto(p) != io and not _solo_un_audio_che_aspetta(p)
        ),
        "tolti": sum(1 for p in pareri if p.get("tolto")),
        "sostituiti": sum(1 for p in pareri if p.get("sostituito")),
        "tolto_per": sum(_lunghezza(p.get("tolto_per")) for p in pareri),
        "sostituito_per": sum(_lunghezza(p.get("sostituito_per")) for p in pareri),
        "conferme_perche": _lunghezza(
            pc.get("conferme_di_prima") if isinstance(pc, dict) else None
        ),
        "conferme_scope": _lunghezza(_scope_di(a, r).get("conferme_di_prima")),
        "trascrizioni": sum(
            1
            for x in (r.get("storia") or [])
            if isinstance(x, dict) and x.get("da") in _DA_TRASCRIZIONI
        ),
    }





GESTO = ".gesto"


GESTI_DI_OWNER = (
    "conferma",
    "rispondi",
    "risposta-giusta",
    "togli-risposta",
    "scope",
    "riapri",
    "smista",

    "crea-task --rifai",


    "conferma-lista",
    "riapri-lista",
)


def _gesto_di(a):
    ""
    if a.verbo == "crea-task" and getattr(a, "rifai", False):
        return "crea-task --rifai"
    return a.verbo



GESTI_SU_PIU_VOCI = {"conferma-lista": "confermate", "riapri-lista": "riaperte"}


def _ids_del_gesto(a, fatto):
    ""

    campo = GESTI_SU_PIU_VOCI.get(a.verbo)
    if campo:
        return [str(i) for i in (fatto or {}).get(campo) or []]
    return [a.id]


def _solo_un_audio(a):
    ""



    return a.verbo == "rispondi" and bool(getattr(a, "audio", "")) and not getattr(a, "testo", "")


def _salva_e_segna(a, note, ident, segna=True):
    ""





    out = a.salva(note)
    if segna:
        for i in [ident] if isinstance(ident, str) else list(ident):
            _segna_gesto(i)
    return out




SALVA_DEI_GESTI = (
    "conferma",
    "rispondi",
    "risposta_giusta",
    "togli_risposta",
    "smista",
    "scope",
    "_giusto",
    "riapri",

    "rifai_task",

    "conferma_lista",
    "riapri_lista",
)
SALVA_NON_GESTI = (
    "_rilettura_voce",
    "_chiudi_rilettura_una",
    "avvisa",
    "ci_lavoriamo",
    "_segna_sessione_aperta",
    "_capisci_voci",


    "_task_dell_avvio",
    "_segna_lavoro_avviato",
    "_segna_task_nata",


    "_task_in_attivita",
    "crea_task_uscita",
    "letto",
    "vai",
    "ritorno_letto",
    "importa",
    "_importa_smistamento",
    "_comprensioni_importa",

    "_porta_arretrato",
)


def _segna_gesto(ident):
    ""





    try:
        cl = _avvisi_della_voce(arch().cartella_lavorazione(ident).name, crea=True)
        if cl is None:
            return False
        tmp = cl / f"{GESTO}.{os.getpid()}.{time.time_ns()}.tmp"
        tmp.write_text(str(time.time_ns()), encoding="utf-8")
        os.replace(tmp, cl / GESTO)
    except OSError:
        return False
    return True


def _ultimo_gesto(ident):
    ""

    cl = arch().cartella_lavorazione(ident)
    ore = [0]
    for p in (cl / GESTO, AVVISI_SENZA_CARTELLA / cl.name / GESTO):
        try:
            ore.append(int(p.read_text(encoding="utf-8").strip()))
        except (OSError, ValueError):
            pass
    return max(ore)


def _decidi_l_avviso(ident, chi, handle, scope, avvisato, firma, letto="", altre=0, conti=None):
    ""












    if scope:
        return True, "scope"
    if avvisato == SEGNAPOSTO_APERTURA:
        return True, "segnaposto"
    ricordo = _ricordo_del_pannello(ident, chi, handle) or {}
    if not ricordo.get("owner"):
        return True, "senza ricordo"
    if _ultimo_gesto(ident) >= int(ricordo.get("letto_ns") or 0):
        return True, "gesto"


    if _avvisi_della_voce(arch().cartella_lavorazione(ident).name) is None:
        return True, "segno impossibile"
    if not firma or firma.get("owner") != ricordo["owner"]:
        return True, "cose dell'utente"


    if ricordo.get("altre") != altre:
        return True, "parole dell'utente da un altro pannello"

    if ricordo.get("conti") != conti:
        if not isinstance(ricordo.get("conti"), dict) or not isinstance(conti, dict):
            return True, "conti assenti"
        mossi = sorted(
            k for k in set(ricordo["conti"]) | set(conti) if ricordo["conti"].get(k) != conti.get(k)
        )
        return True, "conti mossi: " + ", ".join(mossi)
    if letto and firma.get("impronta") != letto:
        return True, "file diverso dalla voce"
    return False, "niente dell'utente"


def _avviso_dopo_la_quiete(ident, cl):
    ""




    posto = _posto_del_giro(cl)
    lucchetto = (posto or CASA_ARCHIVIO) / ".avviso.lock"
    try:
        if posto is None:
            raise NotADirectoryError("no place for the alert lock")
        lucchetto.parent.mkdir(parents=True, exist_ok=True)
        with open(lucchetto, "a"):
            pass
    except OSError as e:


        print(
            f"{_adesso()} the alert lock can't be created ({e!r}): alerting once without the quiet wait",
            flush=True,
        )
        print(f"{_adesso()} alerts {avvisa(ident)}", flush=True)
        return True
    with _lucchetto(lucchetto, aspetta=False) as mio:
        if not mio:
            print(
                f"{_adesso()} another process is already waiting for quiet to alert",
                flush=True,
            )
            return False
        risposte = cl / "RISPOSTE.json"
        _aspetta_la_quiete(risposte)
        fatti = avvisa(ident)
        ultimi = fatti


        for _ in range(3):
            da_ridire = [x for x in ultimi if str(x).endswith(DA_RIDIRE)]
            if not da_ridire:
                break
            _aspetta_la_quiete(risposte)



            if any(str(x).startswith("lavoro") for x in da_ridire):
                f_lavoro = _file_del_lavoro(ident)
                if f_lavoro is not None:
                    _aspetta_la_quiete(f_lavoro)
            ultimi = avvisa(ident)
            fatti = [*fatti, *ultimi]



        a = arch()
        if _sa_dire_lo_scope(a) and not any(str(x).startswith("lavoro non") for x in fatti):
            r = a.carica().get(ident)
            if r and _lavoro_da_avvisare(a, r):
                fatti = [*fatti, *avvisa(ident)]
        print(f"{_adesso()} alerts {fatti}", flush=True)
        return True


def dopo_risposta(ident, solo_avviso=False):
    ""






    a = arch()

    cl = a.cartella_lavorazione(ident)
    if solo_avviso:
        _avviso_dopo_la_quiete(ident, cl)
        return 0
    codice = 0
    avvisato_al_rinvio = False
    for tentativo in range(TENTATIVI):
        if not any(c["voce"] == ident for c in a.coda_audio(a.carica())):
            break
        if tentativo:
            time.sleep(INTERVALLO_TENTATIVI_S)
        print(f"{_adesso()} transcription of {ident}, attempt {tentativo + 1}", flush=True)
        posto = _posto_del_giro(cl)

        with (
            _lucchetto(posto / ".dopo-risposta.lock")
            if posto is not None
            else contextlib.nullcontext()
        ):
            codice = _trascrivi(ident)
        if codice != 75:
            break
        if not avvisato_al_rinvio:

            avvisato_al_rinvio = True
            _avviso_dopo_la_quiete(ident, cl)
    if _avviso_dopo_la_quiete(ident, cl):

        try:
            nota = _rilettura_dopo_risposta(ident)
        except Exception as e:  # noqa: BLE001 the process must not die silently
            nota = None
            print(f"{_adesso()} re-read did not start, {e!r}", flush=True)
        if nota and nota.get("chiusa_quando"):

            motivo = (nota.get("esito") or {}).get("motivo") or ""
            print(f"{_adesso()} re-read did not start, {motivo}", flush=True)
        elif nota:
            print(f"{_adesso()} re-read started, pid {nota.get('pid')}", flush=True)
    return codice


def _sa_dire_lo_scope(a):
    ""

    return bool(getattr(a, "scope_da_dire", None) and getattr(a, "segna_scope_detto", None))


def _scope_da_dire(a, r):
    ""

    if not _sa_dire_lo_scope(a):
        return False
    try:
        return bool(a.scope_da_dire(r))
    except Exception:  # noqa: BLE001 an item that can't be read must not stop today's alerts
        return False


def _avvisi_da_mandare(a, r):
    ""





    righe = [(chi, handle, AVVISO_RIPRENDI, False) for chi, _p, handle in a.da_avvisare(r)]
    if not _sa_dire_lo_scope(a):
        return righe
    ag = (r.get("attivita") or {}).get("agente") or {}
    if _scope_da_dire(a, r) and ag.get("terminale") and not ag.get("ritorno"):
        return [
            *[x for x in righe if x[0] != "lavoro"],
            ("lavoro", ag["terminale"], AVVISO_SCOPE, True),
        ]
    return righe


def _lavoro_da_avvisare(a, r):
    ""

    if not _sa_dire_lo_scope(a):
        return False
    try:
        return any(chi == "lavoro" for chi, *_ in _avvisi_da_mandare(a, r))
    except Exception:  # noqa: BLE001 an item that can't be read must not stop the user's gesture
        return False


def avvisa(ident):
    ""






    a = arch()

    letto_ns = time.time_ns()
    note = a.carica()
    r = note.get(ident)
    if not r:
        return []




    letto = _impronta_in_memoria(r)
    da_mandare = _avvisi_da_mandare(a, r)
    file_letti = {}
    for chi, *_ in da_mandare:
        f = _file_risposte_del_pannello(a, r, chi)
        file_letti[chi] = (f, _firma_file(f) if f else None)
    fatti, saltati = [], []
    for chi, handle, frase, scope in da_mandare:
        f, firma = file_letti.get(chi, (None, None))





        if (
            f is not None
            and firma is None
            and (_ricordo_del_pannello(ident, chi, handle) or {}).get("file") is True
        ):
            saltati.append(f"{chi} non avvisata, il suo RISPOSTE.json non c'è")
            continue






        conto_rotto = None
        try:
            conti = _conti_di_owner(a, r, chi)
        except Exception as e:  # noqa: BLE001 a count that can't be computed counts as «send», below
            conti, conto_rotto = None, e
        try:
            parte, _perche = _decidi_l_avviso(
                ident,
                chi,
                handle,
                scope,
                r["lavorazione"].get("impronte", {}).get(f"avvisato:{chi}"),
                firma,
                letto,
                _parole_dagli_altri(r, chi),
                conti,
            )
        except Exception as e:  # noqa: BLE001 never a silence for a rule error
            parte, _perche = True, f"unreadable rule ({type(e).__name__})"
            print(f"{_adesso()} {chi}: the rule can't be read ({e!r}), sending", flush=True)
        if conto_rotto is not None:
            parte, _perche = True, "count that can't be computed"
            print(f"{_adesso()} {chi}: the count can't be computed ({conto_rotto!r}), sending", flush=True)
        if parte and str(_perche).startswith("conti"):

            print(f"{_adesso()} {chi}: sending, {_perche}", flush=True)
        if not parte:
            saltati.append(f"{chi} da avvisare, niente di nuovo dell'utente")
            continue
        if not terminale_vivo(handle):
            fatti.append(f"{chi} non è più aperta")
            continue
        d = _terminale(
            "terminal",
            "send",
            "--terminal",
            handle,
            "--text",
            frase,
            "--enter",
            timeout=30,
        )
        if d is None:
            fatti.append(f"{chi} non ha ricevuto l'avviso")
            continue
        if scope:
            a.segna_scope_detto(r)
        a.segna_avvisato(r, chi)

        ridire = bool(letto) and not (
            _firma_file(f) == firma and (firma is None or firma.get("impronta") == letto)
        )



        ricordato = firma is None or _ricorda_il_pannello(
            ident,
            chi,
            handle,
            **(
                {}
                if ridire
                else {
                    "owner": firma.get("owner"),
                    "letto_ns": letto_ns,
                    "altre": _parole_dagli_altri(r, chi),
                    "conti": conti,
                }
            ),
        )
        if ridire or not ricordato:
            r["lavorazione"]["impronte"][f"avvisato:{chi}"] = SEGNAPOSTO_APERTURA
        fatti.append(
            f"{chi} avvisata" + (" dello scope" if scope else "") + (DA_RIDIRE if ridire else "")
        )
    if fatti:
        a.salva(note)
    return [*fatti, *saltati]


def ci_lavoriamo(ident):
    ""

    a = arch()
    with _uno_alla_volta():

        letto_ns = time.time_ns()
        note = a.carica()
        r = a._prendi(note, ident)
        f = a.fase_di(r)
        if f not in ("perche", "lavorazione", "pronta"):
            raise Errore(FRASI["fase_sbagliata_sessione"])
        s = r["lavorazione"]["sessione"]


        stato = (
            terminale_stato(s.get("terminale"))
            if s.get("terminale") and not s.get("finita_quando")
            else "assente"
        )
        if stato == "vivo":
            if not a.sessione_aperta(r):
                _riapri_sessione_spunto(a, r)
                a.salva(note)
            _pannello_segnato(a, ident, "spunto", s["terminale"])
            _terminale("terminal", "switch", "--terminal", s["terminale"])
            return {"gia_aperta": True, "titolo": s.get("titolo") or ""}
        if stato is None:

            raise Errore(FRASI["terminale_non_risponde"])
        ri = r["lavorazione"].get("rilettura") or {}
        if (
            ri.get("aperta_quando")
            and not ri.get("chiusa_quando")
            and _processo_vivo(ri.get("pid"))
        ):

            partito = (_json_di(Path(str(ri.get("cartella") or "")) / "processo.json") or {}).get(
                "claude_partito"
            )
            raise Errore(
                FRASI[
                    "rilettura_risposta_in_corso"
                    if partito or not ri.get("cartella")
                    else "rilettura_risposta_in_fila"
                ]
            )


        sospeso = _pannello_da_segnare(a, ident, "spunto", s.get("terminale"))
        if sospeso:
            titolo = sospeso.get("titolo") or _titolo(r, "Idea")
            handle = sospeso["terminale"]
            _segna_sessione_aperta(
                a,
                ident,
                handle,
                sospeso.get("foglia") or "",
                titolo,
                sospeso.get("detto") or "",
                sospeso.get("firma"),
                int(sospeso.get("letto_ns") or 0),
            )
            _terminale("terminal", "switch", "--terminal", handle)
            return {"aperta": True, "titolo": titolo, "terminale": handle, "ritrovata": True}
        cl = a.cartella_lavorazione(ident, crea=True)
        (cl / "SESSIONE.md").write_text(
            (MODELLI / "SESSIONE-SPUNTO.md").read_text(encoding="utf-8"), encoding="utf-8"
        )
        a.scrivi_risposte(r)


        detto = _impronta_in_memoria(r)

        firma = _firma_file(cl / "RISPOSTE.json")


        rc = a.carica().get(ident) or r
        (cl / "CONTESTO.json").write_text(
            json.dumps(_contesto(rc), ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
        )
        titolo = _titolo(r, "Idea")
        handle, foglia = _apri_pannello(
            cl, titolo, ATTREZZI_SPUNTO, _primo_messaggio(cl, "SESSIONE.md")
        )
        _ricorda_pannello(
            a,
            ident,
            "spunto",
            {
                "terminale": handle,
                "foglia": foglia,
                "titolo": titolo,
                "detto": detto,
                "firma": firma,
                "letto_ns": letto_ns,
            },
        )
        _segna_sessione_aperta(a, ident, handle, foglia, titolo, detto, firma, letto_ns)
        return {"aperta": True, "titolo": titolo, "terminale": handle}


def _impronta_in_memoria(r):
    ""

    return str(((r.get("lavorazione") or {}).get("impronte") or {}).get("risposte") or "")


def _firma_file(f):
    ""



    try:
        st = Path(f).stat()
        b = Path(f).read_bytes()
        dati = json.loads(b.decode("utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(dati, dict):
        return None
    return {
        "sha": hashlib.sha256(b).hexdigest(),
        "ino": st.st_ino,
        "mtime_ns": st.st_mtime_ns,
        "impronta": _impronta_dei_dati_del_file(dati),

        "owner": _impronta_di_owner(dati),
    }


def _in_pari_dall_apertura(a, r, detto, firma, f):
    ""





    calcola = getattr(a, "impronta_risposte", None)
    if not (detto and firma and calcola):
        return False
    try:
        ora = calcola(r)
    except Exception:  # noqa: BLE001 an item that can't be read: nothing is assumed as told
        return False
    return ora == detto and firma.get("impronta") == detto and _firma_file(f) == firma


def _segna_detto_all_apertura(a, r, chi, detto, in_pari=True):
    ""








    segna = getattr(a, "segna_avvisato", None)
    if not segna:
        return
    segna(r, chi)
    if detto:
        r["lavorazione"].setdefault("impronte", {})[f"avvisato:{chi}"] = (
            detto if in_pari else SEGNAPOSTO_APERTURA
        )


def _avviso_dopo_l_apertura(a, r, ident, chi):
    ""



    try:
        resta = any(c == chi for c, *_ in _avvisi_da_mandare(a, r))
    except Exception:  # noqa: BLE001 an item that can't be read must not stop the opening
        resta = False
    if resta:
        _in_sottofondo(ident)
    return resta


def _ricorda_l_apertura(ident, chi, handle, firma, in_pari, letto_ns, altre=0, conti=None):
    ""


    if firma is None:
        return False
    ricordo = (
        {"owner": firma.get("owner"), "letto_ns": letto_ns, "altre": altre, "conti": conti}
        if in_pari and letto_ns and firma.get("owner")
        else {}
    )
    return _ricorda_il_pannello(ident, chi, handle, **ricordo)


def _segna_sessione_aperta(a, ident, handle, foglia, titolo, detto, firma=None, letto_ns=0):
    ""



    try:
        note = a.carica()
        r = note[ident]
        a.apri_sessione(r, foglia or handle, handle, titolo)

        in_pari = _in_pari_dall_apertura(
            a, r, detto, firma, a.cartella_lavorazione(ident) / "RISPOSTE.json"
        )
        _segna_detto_all_apertura(a, r, "sessione", detto, in_pari)
        a.salva(note)
    except SystemExit as e:
        raise Avviso(FRASI["agente_aperto_da_segnare"]) from e


    _ricorda_l_apertura(
        ident,
        "sessione",
        handle,
        firma,
        in_pari,
        letto_ns,
        _parole_dagli_altri(r, "sessione"),
        _conti_o_niente(a, r, "sessione"),
    )
    _pannello_segnato(a, ident, "spunto", handle)
    _avviso_dopo_l_apertura(a, note[ident], ident, "sessione")


def _file_pannello(a, ident, chi, crea=False):
    ""

    return a.cartella_lavorazione(ident, crea=crea) / f".pannello-{chi}.json"


def _ricorda_pannello(a, ident, chi, dati):
    ""


    p = _file_pannello(a, ident, chi, crea=True)
    prima = _json_di(p)
    if isinstance(prima, dict):
        prima.pop("di_prima", None)
    try:
        _scrivi_json(
            p,
            {
                "stato": "da_segnare",
                "chi": chi,
                "aperto_quando": _adesso(),
                "pid": os.getpid(),
                **dati,
                **({"di_prima": prima} if isinstance(prima, dict) else {}),
            },
        )
    except OSError:
        pass


def _pannello_segnato(a, ident, chi, handle, stato="segnato"):
    ""


    p = _file_pannello(a, ident, chi)
    d = _json_di(p)
    if not isinstance(d, dict) or d.get("stato") != "da_segnare" or d.get("terminale") != handle:
        return
    try:
        _scrivi_json(p, {**d, "stato": stato, f"{stato}_quando": _adesso()})
    except OSError:
        pass


def _pannello_da_segnare(a, ident, chi, registrato=""):
    ""









    f = _file_pannello(a, ident, chi)
    d = _json_di(f)
    if not isinstance(d, dict) or d.get("stato") != "da_segnare" or not d.get("terminale"):
        return None
    handle = d["terminale"]
    if registrato and handle == registrato:
        _pannello_segnato(a, ident, chi, handle)
        return None

    if chi == "lavoro" and not (isinstance(d.get("cartella"), str) and d["cartella"].strip()):
        _pannello_segnato(a, ident, chi, handle, "non_valido")
        return None
    stato = terminale_stato(handle)
    if stato is None:
        raise Errore(FRASI["terminale_non_risponde"])
    if stato == "vivo":
        if d.get("non_visto"):
            d.pop("non_visto", None)
            _scrivi_json(f, d)
        return d
    if stato == "assente":
        c, chiuso = _conta_non_visto(d.get("non_visto"), time.time())
        while not chiuso and time.time() - c["prima"] >= TERMINALE_ASSENTE_S:
            time.sleep(TERMINALE_ASSENTE_FRA_LETTURE_S)
            stato = terminale_stato(handle)
            if stato is None:
                _scrivi_json(f, {**d, "non_visto": c})
                raise Errore(FRASI["terminale_non_risponde"])
            if stato == "vivo":
                d.pop("non_visto", None)
                _scrivi_json(f, d)
                return d
            if stato != "assente":
                break
            c, chiuso = _conta_non_visto(c, time.time())
        if stato == "assente" and not chiuso:
            _scrivi_json(f, {**d, "non_visto": c})
            raise Avviso(FRASI["agente_non_visto_in_terminale"])
    _pannello_segnato(a, ident, chi, handle, "chiuso_prima_di_segnarlo")
    return None


def _cartella_contenuti(a, r):
    ""



    assoluto = getattr(a, "_assoluto", None)
    for c in (r.get("copia") or {}).get("cartelle") or []:
        q = assoluto(c) if assoluto else Path(c)
        if q is None or not Path(q).is_dir():
            continue
        if any(f.name != "cattura.json" and not f.name.startswith(".") for f in Path(q).iterdir()):
            return Path(q)
    return CASA_ARCHIVIO / "contenuti" / a.nome_cartella(r.get("id") or "")


def _contesto_comprensione(a, note, ids):
    ""

    giro = RADICE / GIRO_SCOMPONI
    voci = []
    for i in ids:
        r = note[i]
        voci.append(
            {
                "id": i,
                "titolo": r.get("titolo") or "",
                "url": r.get("url") or "",
                "tipo": r.get("tipo") or "",
                "cartella_contenuti": str(_cartella_contenuti(a, r)),
                "contenuto_visto": r.get("contenuto_visto") or {},
                "scarico": ""
                if (r.get("contenuto_visto") or {}).get("si")
                else _comando_scarico(r),
                "aggiorna": f"cd {shlex.quote(str(CASA_ARCHIVIO))} && python3 -I archivio.py aggiorna",
                "pareri": [
                    {
                        "quando": p.get("quando"),
                        "testo": (p.get("testo") or p.get("trascrizione") or ""),
                    }
                    for p in (r.get("pareri") or [])
                    if (p.get("testo") or p.get("trascrizione"))
                ],
                "frase_accanto_al_link": ((r.get("cattura") or {}).get("testo_di_owner") or ""),
            }
        )
    return {
        "voci": voci,
        "brief_dossier": str(giro / "21-BRIEF-AGENTI.md"),
        "brief_perche": str(CASA_ARCHIVIO / "PERCHE-BRIEF.md"),
        "verifica": str(giro / "verifica-v2.py"),
        "cartella_verifica": str(giro),
        "archivio": str(CASA_ARCHIVIO),
        "perche_prepara": str(CASA_ARCHIVIO / "perche-prepara.py"),
        "perche_verifica": str(CASA_ARCHIVIO / "perche-verifica.py"),
    }


def _da_capire_visti(note):
    ""
    out = []
    for i, r in note.items():
        ap = r.get("a_parte") or {}
        if ap.get("si") if isinstance(ap, dict) else ap:
            continue
        if r.get("stato") == "da capire":
            out.append(i)
    return out


def _comando_scarico(r):
    ""


    py = str(VENV if VENV.exists() else sys.executable)
    giro = RADICE / GIRO_SCOMPONI
    piattaforma = r.get("piattaforma") or ""
    ident = r.get("id") or ""
    if piattaforma == "instagram":
        return f"cd {shlex.quote(str(giro))} && {shlex.quote(py)} -I giro.py --continua --ore 1"
    if piattaforma == "x":
        return (
            f"cd {shlex.quote(str(giro))} && python3 -I copia-post-x.py --voci {shlex.quote(ident)}"
            f" && {shlex.quote(py)} -I giro.py --continua --ore 1"
        )
    if piattaforma == "linkedin":
        return f"cd {shlex.quote(str(giro))} && SB_SOGLIA_AMMISSIONE=65 {shlex.quote(py)} -I copia-pagina-web.py --social --voci {shlex.quote(ident)}"
    return f"cd {shlex.quote(str(giro))} && SB_SOGLIA_AMMISSIONE=65 {shlex.quote(py)} -I copia-pagina-web.py --voci {shlex.quote(ident)}"


def _ritmo_acceso():
    ""
    return bool(_leggi_cfg(CAPISCI_DA_SOLO).get("acceso"))


def _senza_accesso(r):
    ""

    return str((r.get("disponibilita") or {}).get("stato") or "") in DISPONIBILITA_DEFINITIVE


def _claude_c_e():
    ""

    p = Path(CLAUDE)
    ok = (
        (p.is_file() and os.access(p, os.X_OK))
        if p.is_absolute()
        else shutil.which(CLAUDE) is not None
    )
    if not ok:
        raise Errore(FRASI["claude_manca"])


def _pid_vivo_fra(pid, nomi):
    ""

    try:
        pid = int(str(pid).strip())
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    try:
        r = subprocess.run(
            ["ps", "-o", "command=", "-p", str(pid)], capture_output=True, text=True, timeout=10
        )
    except (OSError, subprocess.TimeoutExpired):
        return True
    return any(n in (r.stdout or "") for n in nomi)


def _scarico_al_lavoro():
    ""








    lock = RADICE / GIRO_SCOMPONI / "giro.lock"
    if lock.exists():
        try:
            pid = lock.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            pid = ""
        if pid.isdigit():
            if _pid_vivo_fra(pid, ("giro.py", "scomponi.py", "copia-pagina-web.py")):
                return True
        elif not _lucchetto_libero(lock):
            return True
    st = _leggi_cfg(SCARICHI_IN_CORSO)
    passi = [str(p) for p in st.get("passi") or []]
    passo = str(st.get("passo") or "")
    if st.get("finito") or "reels round" not in passi or passo not in passi:
        return False
    if passi.index(passo) > passi.index("reels round"):
        return False
    if st.get("pid"):
        return _pid_vivo_fra(st["pid"], ("scarichi",))
    return not _lucchetto_libero(LUCCHETTO_SCARICHI)


def _reel_da_scaricare(r):
    ""
    if r.get("piattaforma") != "instagram" or (r.get("contenuto_visto") or {}).get("si"):
        return False
    return _scende_da_solo(r)


def _scarico_prende(r, al_lavoro=None):
    ""


    if not _reel_da_scaricare(r):
        return False
    return _scarico_al_lavoro() if al_lavoro is None else al_lavoro


def _cartella_di(cartella):
    ""

    if not cartella:
        return None
    qui = CASA_ARCHIVIO / "lavorazione" / Path(str(cartella)).name
    return qui if qui.is_dir() else Path(str(cartella))


def _a_vuoto(cartella, esito=None):
    ""










    cart = Path(cartella)

    if isinstance(esito, dict) and str(esito.get("codice") or "") == "scaricatore-occupato":
        return True
    if isinstance(esito, dict) and esito.get("stato") in ("fatto", "fermo"):
        if esito.get("da") != "processo":
            return False
    if _esito_claude(cart):
        return False
    if isinstance(esito, dict) and esito.get("da") == "processo":
        return str(esito.get("codice") or "") in CODICI_A_VUOTO
    proc = _json_di(cart / "processo.json")
    return not (isinstance(proc, dict) and proc.get("claude_partito"))


def _vuoti_di_prima(r, com):
    ""



    viste, n = set(), 0
    for e in r.get("storia") or []:
        cosa = str(e.get("cosa") or "")
        if e.get("evento") != "comprensione":
            continue
        if "pressed Do it now" in cosa or cosa.startswith("understanding session opened"):
            viste, n = set(), 0
            continue
        if not cosa.startswith("understanding started in the background"):
            continue
        try:
            t = datetime.datetime.fromisoformat(str(e.get("quando") or ""))
        except ValueError:
            continue
        for d in (0, -1, -2, 1):
            q = (
                CASA_ARCHIVIO
                / "lavorazione"
                / f"comprensione-{(t + datetime.timedelta(seconds=d)).strftime('%Y%m%dT%H%M%S')}"
            )
            if q.is_dir():
                if q not in viste:
                    viste.add(q)
                    n += _a_vuoto(q, _json_di(q / "ESITO.json"))
                break
    ultima = _cartella_di(com.get("cartella"))
    if ultima is not None and ultima not in viste and ultima.is_dir():
        n += _a_vuoto(ultima, _json_di(ultima / "ESITO.json"))
    return n


def _tentativi_veri(r, com):
    ""


    tentativi = int(com.get("tentativi") or 0)
    if "tentativi_a_vuoto" in com:
        return tentativi
    return max(0, tentativi - _vuoti_di_prima(r, com)) if tentativi else 0


def _fermo_a_vuoto(r, com):
    ""


    if com.get("ripresa_a_vuoto"):

        return not com.get("chiusa_quando") or bool((com.get("esito") or {}).get("a_vuoto"))
    if "tentativi_a_vuoto" in com:
        return False
    tentativi = int(com.get("tentativi") or 0)
    return tentativi >= TENTATIVI_COMPRENSIONE and _tentativi_veri(r, com) < tentativi


def capisci(ident, pannello=False):
    ""





    a = arch()
    with _uno_alla_volta():
        note = a.carica()
        if ident == "tutte":
            ids = _da_capire_visti(note)


            vivi = [
                i
                for i in ids
                if _comprensione_viva((note[i].get("lavorazione") or {}).get("comprensione") or {})
            ]
            ids = [i for i in ids if i not in vivi]


            senza = [i for i in ids if _senza_accesso(note[i])]
            fermi_vuoto = [
                i
                for i in ids
                if _fermo_a_vuoto(
                    note[i], (note[i].get("lavorazione") or {}).get("comprensione") or {}
                )
            ]

            al_lavoro = any(_reel_da_scaricare(note[i]) for i in ids) and _scarico_al_lavoro()
            scendono = [i for i in ids if _scarico_prende(note[i], al_lavoro)]
            fuori = set(senza) | set(fermi_vuoto) | set(scendono)
            ids = [i for i in ids if i not in fuori]


            cfg = _leggi_cfg(CAPISCI_DA_SOLO)
            acceso = bool(cfg.get("acceso"))
            a_te = _aspettano_te(note, ids)
            altri = scendono
            col_si, fermi_veri = [], []
            if a_te is not None:
                altri = altri + [i for i in ids if i not in a_te]
                ids = [i for i in ids if i in a_te]


                si = set(cfg.get("si_di_owner") or []) | set(cfg.get("in_fila_col_si") or [])
                col_si = [i for i in ids if i in si]
                fermi_veri = [
                    i
                    for i in ids
                    if i not in si
                    and _fermo_vero(
                        note[i], (note[i].get("lavorazione") or {}).get("comprensione") or {}
                    )
                ]
                ids = [i for i in ids if i not in col_si and i not in fermi_veri]
            if not ids and altri:
                raise Avviso(FRASI["scendono_da_soli" if acceso else "scendono_da_soli_spento"])
            if not ids and col_si:
                raise Avviso(FRASI["col_si_da_soli"])
            if not ids and fermi_vuoto:
                riparte = (
                    cfg.get("riparti_fermi_a_vuoto") is True
                    or cfg.get("riparti_fermi_a_vuoto") == "uno"
                )
                raise Avviso(FRASI["fermi_uno_alla_volta" if riparte else "fermi_non_ripartono"])
            if not ids and fermi_veri:
                raise Errore(FRASI["fermi_uno_per_uno"])
            if not ids and senza:
                raise Errore(FRASI["senza_accesso_tutte"])
            if not ids:
                if vivi:
                    raise Avviso(FRASI["comprensione_in_corso"])
                raise Errore(FRASI["niente_da_capire"])




            da_aprire = [
                i
                for i in ids
                if not (note[i].get("contenuto_visto") or {}).get("si")
                and not _scende_da_solo(note[i])
            ]
            in_fila = da_aprire[1:]
            tenuto = False
            if in_fila:
                ids = [i for i in ids if i not in in_fila]
                tenuto = _tieni_si(in_fila)
            esito = _capisci_voci(a, note, ids, pannello=pannello, avvio="fallo_adesso")
            if in_fila and isinstance(esito, dict):

                esito["in_fila_col_si" if tenuto else "aspettano_ancora_il_si"] = list(in_fila)
                if len(in_fila) == 1:
                    chiave = "uno_parte_altro_in_fila" if tenuto else "uno_parte_altro_aspetta"
                else:
                    chiave = "uno_parte_altri_in_fila" if tenuto else "uno_parte_altri_aspettano"
                esito["messaggio"] = FRASI[chiave].format(n=len(in_fila))
            return esito
        else:
            a._prendi(note, ident)
            if ident not in _da_capire_visti(note):
                raise Errore(FRASI["niente_da_capire"])

            if not pannello and _scarico_prende(note[ident]):
                raise Avviso(FRASI["scende_gia" if _ritmo_acceso() else "scende_gia_spento"])
            ids = [ident]
        return _capisci_voci(a, note, ids, pannello=pannello, avvio="fallo_adesso")


def _capisci_voci(a, note, ids, pannello, avvio, ripresa=False):
    ""





    for i in ids:
        com = note[i].setdefault("lavorazione", {}).get("comprensione") or {}
        if com.get("aperta_quando") and not com.get("chiusa_quando"):
            if _comprensione_viva(com):
                if com.get("terminale"):
                    _terminale("terminal", "switch", "--terminal", com["terminale"])
                raise Avviso(FRASI["comprensione_in_corso"])
            com["chiusa_quando"] = _adesso()
    if not pannello:
        try:
            _claude_c_e()
            _prestito_in_vista(
                "comprensione"
            )
        except Errore as e:

            if avvio == "fallo_adesso" and _tieni_si(ids):
                if getattr(e, "promette", False):
                    raise
                raise Errore(f"{e}. {FRASI['si_tenuto']}") from None
            raise
    nome = (
        a.nome_cartella(ids[0])
        if len(ids) == 1
        else f"comprensione-{_adesso().replace(':', '').replace('-', '')[:15]}"
    )
    cl = (
        (CASA_ARCHIVIO / "lavorazione" / nome)
        if len(ids) > 1
        else a.cartella_lavorazione(ids[0], crea=True)
    )
    cl.mkdir(parents=True, exist_ok=True)
    (cl / "SESSIONE-COMPRENSIONE.md").write_text(
        (MODELLI / "SESSIONE-COMPRENSIONE.md").read_text(encoding="utf-8"), encoding="utf-8"
    )
    contesto = _contesto_comprensione(a, note, ids)
    contesto["cartella_perche"] = str(cl / "perche")
    contesto["avvio"] = avvio
    contesto["sottofondo"] = not pannello

    for vecchio in ("ESITO.json", "claude-esito.json", "processo.json"):
        with contextlib.suppress(OSError):
            (cl / vecchio).unlink()
    (cl / "CONTESTO.json").write_text(
        json.dumps(contesto, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    titolo = _titolo(note[ids[0]], "Understand") if len(ids) == 1 else f"Understand · {len(ids)} ideas"
    if pannello:
        handle, foglia = _apri_pannello(
            cl,
            titolo,
            ATTREZZI_COSTRUZIONE,
            _primo_messaggio(cl, "SESSIONE-COMPRENSIONE.md"),
            VIETATI_COSTRUZIONE,
        )
        pid = None
    else:
        handle = foglia = ""
        pid = _comprensione_in_sottofondo(cl, titolo)
    note = a.carica()
    for i in ids:
        prima = (note[i].get("lavorazione") or {}).get("comprensione") or {}
        da_solo = avvio == "da_solo"

        tentativi = _tentativi_veri(note[i], prima) if da_solo else 0
        com = {
            "pannello": foglia or handle,
            "terminale": handle,
            "pid": pid,
            "sottofondo": not pannello,
            "titolo": titolo,
            "aperta_quando": _adesso(),
            "chiusa_quando": "",
            "cartella": str(cl),
            "voci": ids,
            "avvio": avvio,
            "tentativi": tentativi + 1,
            "tentativi_a_vuoto": int(prima.get("tentativi_a_vuoto") or 0) if da_solo else 0,
            "vuoti_di_fila": int(prima.get("vuoti_di_fila") or 0) if da_solo else 0,
        }
        if ripresa:
            com["ripresa_a_vuoto"] = True
        note[i].setdefault("lavorazione", {})["comprensione"] = com
        cosa = (
            f"understanding session opened in the terminal ({titolo})"
            if pannello
            else f"understanding started in the background ({titolo}, "
            + (
                "pressed Do it now"
                if avvio == "fallo_adesso"
                else f"on its own, attempt {tentativi + 1}"
            )
            + ")"
        )
        a._segna(note[i], cosa, "comprensione", "SBK")
    a.salva(note)
    return {
        "aperta": True,
        "titolo": titolo,
        "terminale": handle,
        "pid": pid,
        "sottofondo": not pannello,
        "voci": ids,
    }


def _chiudi_sessione_spunto(a, r, perche, finita=False):
    ""


    if not a.sessione_aperta(r):
        return False
    a.apri_sessione(r, "", chiusa=True)
    s = r["lavorazione"]["sessione"]
    if finita and not s.get("finita_quando"):
        s["finita_quando"] = s.get("chiusa_quando") or _adesso()
    a._segna(r, perche, "sessione", "SBK")
    return True


def avvia(ident, task=False):
    ""




    a = arch()
    with _uno_alla_volta():

        letto_ns = time.time_ns()
        note = a.carica()
        r = a._prendi(note, ident)
        fase = a.fase_di(r)
        if fase in ("avviata", "arrivata"):
            raise Errore(FRASI["gia_partito"])

        if _scope_di(a, r).get("strada") == "studio":
            raise Avviso(FRASI["avvia_studio"])
        if fase != "pronta":
            raise Errore(FRASI["solo_pronta"])
        scheda = a._assoluto(r["lavorazione"]["scheda"]["file"])
        if not scheda or not scheda.is_file():
            raise Errore(FRASI["scheda_sparita"])
        org, progetto = DOVE_LAVORA.get(
            r["lavorazione"]["perche"].get("progetto") or r["destinazione"].get("progetto") or "",
            DOVE_LAVORA["altro"],
        )


        sospeso = _pannello_da_segnare(
            a, ident, "lavoro", (r.get("attivita") or {}).get("agente", {}).get("terminale")
        )
        if sospeso:
            cartella = Path(sospeso["cartella"])


            _scheda_e_permessi_come_allora(a, r, scheda, cartella, sospeso)
            costruzione = sospeso.get("permessi") == "costruzione"
            titolo = sospeso.get("titolo") or _titolo(r, "Work")
            handle, foglia, detto, firma = (
                sospeso["terminale"],
                sospeso.get("foglia") or "",
                sospeso.get("detto") or "",
                sospeso.get("firma"),
            )
            letto_ns = int(sospeso.get("letto_ns") or 0)
        else:
            cartella = _cartella_lavoro(org, progetto, f"inspiration-{a.nome_cartella(ident)}")
            (cartella / "SCHEDA.md").write_text(
                scheda.read_text(encoding="utf-8"), encoding="utf-8"
            )
            (cartella / "REGOLE-LAVORO.md").write_text(
                (MODELLI / "REGOLE-LAVORO.md").read_text(encoding="utf-8"), encoding="utf-8"
            )
            costruzione = r["lavorazione"]["piano"].get("permessi") == "costruzione"
            titolo = _titolo(r, "Work")

            detto = _risposte_del_lavoro_prima_del_pannello(a, r, cartella, titolo, costruzione)

            firma = _firma_file(cartella / "RISPOSTE.json") if detto else None
            handle, foglia = _apri_pannello(
                cartella,
                titolo,
                ATTREZZI_COSTRUZIONE if costruzione else ATTREZZI_RICERCA,
                _primo_messaggio(cartella, "REGOLE-LAVORO.md e poi SCHEDA.md"),
                vietati=VIETATI_COSTRUZIONE if costruzione else "",
            )
            _ricorda_pannello(
                a,
                ident,
                "lavoro",
                {"terminale": handle, "foglia": foglia, "titolo": titolo, "detto": detto, "firma": firma,
                 "cartella": str(cartella), "permessi": "costruzione" if costruzione else "ricerca", "letto_ns": letto_ns},
            )
        r = _segna_lavoro_avviato(
            a, ident, handle, foglia, cartella, titolo, costruzione, detto, firma, letto_ns
        )
        if sospeso:
            _terminale("terminal", "switch", "--terminal", handle)
        esito = {
            "avviata": True,
            "titolo": titolo,
            "terminale": handle,
            "cartella": str(cartella),
            "task": "",
            **({"ritrovata": True} if sospeso else {}),
        }
        if not task:
            return esito

        return _task_dell_avvio(a, ident, r, esito)


def _task_dell_avvio(a, ident, r, esito):
    ""






    link = r.get("link") or {}
    gia = str(link.get("task") or (r.get("attivita") or {}).get("task_url") or "")
    sc = _scope_di(a, r)
    eliminata = False
    if gia.startswith("attivita:"):


        o = _attivita("origine", "inspiration", ident)
        eliminata = bool(
            isinstance(o, dict) and o.get("ok") and o.get("c_e") and o.get("eliminata")
        )
        if not eliminata:
            viva = isinstance(o, dict) and o.get("ok") and o.get("c_e") and o.get("id")
            tid = str(o["id"]) if viva else gia.removeprefix("attivita:")
            esito["task"] = {"dove": "attivita", "id": tid, "c_era": True}
            esito["messaggio"] = FRASI["avvia_task_c_era"]
            return esito
    if re.match(r"^https?://", gia):

        esito["task"] = {"dove": "clickup", "id": gia, "c_era": True}
        esito["messaggio"] = FRASI["avvia_task_c_era_clickup"]
        return esito


    if sc.get("delicato"):
        esito["messaggio"] = FRASI["avvia_task_delicato"]
        return esito
    if not _task_accesa("owner"):
        esito["messaggio"] = FRASI["avvia_task_spenta"]
        return esito
    pi = (r.get("lavorazione") or {}).get("piano") or {}
    arrivo = " ".join(str(pi.get("punto_di_arrivo") or "").split())
    sc_avvio = {**sc, "dove_arrivare": arrivo} if arrivo else sc
    try:
        if eliminata:
            raise Eliminata(FRASI["scope_attivita_eliminata"])
        t = _task_in_attivita(
            r,
            sc_avvio,
            titolo=_titolo_attivita(r, sc_avvio),
            descrizione=_descrizione_avvio(r, sc_avvio),
        )
    except Errore as e:
        note = a.carica()
        a._segna(note[ident], f"task in your Activities not created ({e})", "avvio", "SBK")
        a.salva(note)


        frase = "avvia_task_eliminata" if isinstance(e, Eliminata) else "avvia_task_non_nata"
        esito.update(ok=False, messaggio=FRASI[frase], avviso=True)
        return esito
    valore = f"attivita:{t['id']}"
    if not t["c_era"]:
        _segna_task_nata(a, ident, t)
    note = a.carica()
    v = note[ident]
    if (v.get("link") or {}).get("task") != valore:

        v.setdefault("link", {})["task"] = valore
        v.setdefault("attivita", {})["task_url"] = valore
    a._segna(
        v,
        f"task in your Activities {t['id']}" + (", already existed" if t["c_era"] else ""),
        "avvio",
        "owner",
    )
    a.salva(note)
    esito["task"] = {k: t[k] for k in ("dove", "id", "c_era")}
    esito["messaggio"] = _con_descrizione(
        FRASI["avvia_task_c_era" if t["c_era"] else "avvia_task_nata"], t
    )
    return esito



MESI_RIPIEGO = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
                "November", "December")


def _giorno_del_lavoro(giorno=None):
    ""

    d = giorno or datetime.date.today()
    try:
        mesi = _parole().MESI
    except (ImportError, AttributeError):
        mesi = MESI_RIPIEGO
    testo = f"{d.day}{'°' if d.day == 1 else ''} {mesi[d.month - 1]}"
    return testo if d.year == datetime.date.today().year else f"{testo} {d.year}"


def _riga_del_lavoro(giorno=None):
    ""

    riga = FRASI["avvia_descrizione_lavoro"].format(quando=_giorno_del_lavoro(giorno))
    return re.sub(r"\bil (8|11) ", r"l'\1 ", riga)


def _descrizione_avvio(r, sc):
    ""


    righe = _descrizione_attivita(r, sc).split("\n\n")
    riga = _riga_del_lavoro()
    url = str(r.get("url") or "")
    if url and righe and righe[-1] == url:
        righe.insert(len(righe) - 1, riga)
    elif righe == [_titolo_voce(r)]:
        righe = [riga]
    else:
        righe.append(riga)
    return "\n\n".join(righe)


def _scheda_e_permessi_come_allora(a, r, scheda, cartella, sospeso):
    ""




    try:
        scheda_cambiata = Path(scheda).read_bytes() != (Path(cartella) / "SCHEDA.md").read_bytes()
    except OSError:
        scheda_cambiata = True
    permessi = (
        "costruzione" if r["lavorazione"]["piano"].get("permessi") == "costruzione" else "ricerca"
    )
    permessi_cambiati = permessi != str(sospeso.get("permessi") or "")
    if scheda_cambiata and permessi_cambiati:
        raise Avviso(FRASI["lavoro_aperto_scheda_e_permessi_di_prima"])
    if scheda_cambiata:
        raise Avviso(FRASI["lavoro_aperto_scheda_di_prima"])
    if permessi_cambiati:
        raise Avviso(FRASI["lavoro_aperto_permessi_di_prima"])


def _risposte_del_lavoro_prima_del_pannello(a, r, cartella, titolo, costruzione):
    ""






    if not _accetta(a.scrivi_risposte, "solo"):
        return ""
    copia = json.loads(json.dumps(r))
    a.segna_avviata(copia, "", cartella, cartella / "SCHEDA.md", "", titolo, "",
                    "costruzione" if costruzione else "ricerca")
    return _impronta_in_memoria(copia)


def _segna_lavoro_avviato(
    a, ident, handle, foglia, cartella, titolo, costruzione, detto, firma=None, letto_ns=0
):
    ""


    try:
        note = a.carica()
        r = note[ident]

        in_pari = _in_pari_dall_apertura(a, r, detto, firma, Path(cartella) / "RISPOSTE.json")
        a.segna_avviata(r, foglia or handle, cartella, cartella / "SCHEDA.md", handle, titolo, "",
                        "costruzione" if costruzione else "ricerca")


        _segna_detto_all_apertura(a, r, "lavoro", detto, in_pari)

        _chiudi_sessione_spunto(
            a,
            r,
            "the idea's session finished its task, the card has gone out",
            finita=True,
        )
        a.salva(note)
    except SystemExit as e:
        raise Avviso(FRASI["agente_aperto_da_segnare"]) from e

    _ricorda_l_apertura(
        ident,
        "lavoro",
        handle,
        firma,
        in_pari,
        letto_ns,
        _parole_dagli_altri(r, "lavoro"),
        _conti_o_niente(a, r, "lavoro"),
    )
    _pannello_segnato(a, ident, "lavoro", handle)
    _avviso_dopo_l_apertura(a, note[ident], ident, "lavoro")
    return r


def _cartella_lavoro(org, progetto, cosa):
    ""

    # Working-folder root is configurable via SB_INSPIRATION_LAVORO;
    # default is ~/.sbk-data/work. Layout: <root>/<org>/<project>/<date>-<what>.
    base = os.environ.get("SB_INSPIRATION_LAVORO") or str(Path.home() / ".sbk-data" / "work")
    p = Path(base) / org / progetto / f"{datetime.date.today():%Y-%m-%d}-{cosa}"
    p.mkdir(parents=True, exist_ok=True)
    return p




BACKLOG = "900000000000"
OWNER_CLICKUP = int(os.environ.get("SB_CLICKUP_USER_ID") or "100000000")
# suggested ClickUp destination per project; load from user config.
# Default keeps only a generic fallback.
DESTINAZIONE_SUGGERITA = {
    "altro": "Backlog",
}


def _giorno_ora(iso):
    ""
    try:
        d = datetime.datetime.fromisoformat(str(iso)[:19])
    except ValueError:
        return ""
    return f"{d:%d/%m/%Y} at {d:%H:%M}"


def task_proposta(r, cartella):
    ""

    pc = r["lavorazione"]["perche"]
    pi = r["lavorazione"]["piano"]
    progetto = pc.get("progetto") or r["destinazione"].get("progetto") or "altro"
    dove = re.sub(
        r"^\s*vuoi arrivare a\s+",
        "",
        str(pi.get("punto_di_arrivo") or pc.get("dove_arrivare") or ""),
        flags=re.I,
    )
    if dove and dove[0].islower():
        dove = dove[0].upper() + dove[1:]
    if pc.get("confermato"):
        quando = _giorno_ora(pc.get("confermato_quando"))
        conferma_frase = (
            "The user confirmed it"
            + (f" on {quando}" if quando else "")
            + (" with a correction of theirs" if pc.get("correzione") else "")
        )
    else:
        conferma_frase = "The user hasn't confirmed it yet"
    righe = [
        f"Inspiration idea started by the user in SBK on {datetime.date.today():%d/%m/%Y}.",
        f"The reason, as SBK wrote it to the user. {pc.get('testo') or ''} ({conferma_frase}.)",
    ]
    if pc.get("correzione"):
        righe.append(f"The user's correction. {pc['correzione']}")
    if dove:
        righe.append(f"Where to get to. {dove}")
    domande = []
    try:
        domande = arch().domande_di(r)
    except Exception:
        domande = [
            {"testo": d.get("testo"), "risposta": (d.get("risposta") or {}).get("testo") if isinstance(d.get("risposta"), dict) else d.get("risposta"), "chiusa": d.get("chiusa")}
            for d in r["lavorazione"].get("domande") or []
        ]
    risposte = [
        f"Question. {d.get('testo')} User's answer. {d.get('risposta')}"
        for d in domande
        if d.get("chiusa") and d.get("risposta") and not d.get("da_sistema")
    ]
    if risposte:
        righe.append("The user's answers.\n" + "\n".join(risposte))
    dettagli = [
        p.get("testo")
        for p in r["pareri"]
        if p.get("testo") and not p.get("domanda") and p.get("su") != "perche"
        and str(p.get("via") or "").startswith("app")
    ]
    if dettagli:
        righe.append("The details added by the user.\n" + "\n".join(f"«{x}»" for x in dettagli[-5:]))
    righe += [
        f"Original. {r.get('url') or ''}",
        f"Working folder. {cartella}",
        f"Archive item. {r['id']}",
        f"Suggested destination: {DESTINAZIONE_SUGGERITA.get(progetto, DESTINAZIONE_SUGGERITA['altro'])}",
    ]
    nome = re.sub(r"\s+", " ", f"Inspiration · {r.get('titolo') or r['id']}").strip()[:150]
    return {"name": nome, "description": "\n\n".join(righe), "assignees": [OWNER_CLICKUP], "priority": 3,
            "tags": ["backlog", "inspiration"]}


def crea_task(r, cartella):
    ""




    dati = task_proposta(r, cartella)
    finto = os.environ.get("SB_CLICKUP_FINTO")
    if finto:
        if finto == "fallisci":
            raise Errore(FRASI["task_non_creata_ferma"])
        Path(finto).write_text(
            json.dumps({"quando": _adesso(), **dati}, ensure_ascii=False, indent=1) + "\n"
        )
        return "https://app.clickup.com/t/finto"
    cs = _clickup()
    stato, testo = cs.api_post(f"/list/{BACKLOG}/task", dati)
    try:
        j = json.loads(testo)
    except ValueError:
        j = {}
    if stato not in (200, 201) or not j.get("id"):
        raise Errore(FRASI["task_non_creata_ferma"])
    cs.audit(
        "create_task",
        j["id"],
        dati["name"],
        {"list": BACKLOG, "da": "SBK, Inspiration Start"},
    )
    return j.get("url") or f"https://app.clickup.com/t/{j['id']}"


LUCCHETTO_SMISTA = CASA_ARCHIVIO / ".smista.lock"


def _smista_regole():
    ""
    if str(QUI) not in sys.path:
        sys.path.insert(0, str(QUI))
    import sb_inspiration_smista

    return sb_inspiration_smista


def _progetto_di(r):
    ""
    with contextlib.suppress(Exception):
        sc = _scope_di(arch(), r)
        if int(sc.get("versione") or 0) and sc.get("progetto"):
            return str(sc["progetto"])
    return (
        r["lavorazione"]["perche"].get("progetto")
        or (r.get("destinazione") or {}).get("progetto")
        or "altro"
    )


class _ClickUp:
    """Minimal ClickUp REST client: your personal API token, GET and POST, a local audit log."""

    API = "https://api.clickup.com/api/v2"

    def __init__(self):
        if str(ROOT / "tools") not in sys.path:
            sys.path.insert(0, str(ROOT / "tools"))
        from secrets_adapter import get_secret

        self.token = get_secret("sbk-clickup", "api-token") or os.environ.get("CLICKUP_API_KEY")
        if not self.token:
            raise RuntimeError(
                "ClickUp API token not found: set CLICKUP_API_KEY in .env "
                "or the Keychain item sbk-clickup / api-token."
            )
        data = Path(os.environ.get("SBK_DATA_ROOT") or Path.home() / ".sbk-data").expanduser()
        self.audit_log = data / "clickup-audit.jsonl"

    def _call(self, path, data=None, method="GET"):
        import urllib.error
        import urllib.request

        headers = {"Authorization": self.token}
        body = None
        if data is not None:
            body = json.dumps(data).encode()
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(f"{self.API}{path}", data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.status, resp.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()

    def api_get(self, path):
        _stato, testo = self._call(path)
        return json.loads(testo)

    def api_post(self, path, data):
        return self._call(path, data, "POST")

    def audit(self, op, target_id, target_name, meta=None):
        self.audit_log.parent.mkdir(parents=True, exist_ok=True)
        voce = {
            "ts": datetime.datetime.now(datetime.UTC).isoformat(),
            "op": op,
            "target_id": target_id,
            "target_name": target_name,
            "meta": meta or {},
        }
        with open(self.audit_log, "a", encoding="utf-8") as f:
            f.write(json.dumps(voce) + "\n")


def _clickup():
    return _ClickUp()


def _task_smistamento(r, d, esito, progetto):
    ""

    S = _smista_regole()
    prop = (r["lavorazione"].get("smistamento") or {}).get("proposta") or {}
    dati = task_proposta(r, arch().cartella_lavorazione(r["id"]))
    testa = [
        f"Sorted by the user in SBK on {datetime.date.today():%d/%m/%Y}, {S.ESITI_PAROLE[esito]}, project {progetto}.",
        "Who does it. " + ("the user" if prop.get("chi_esegue") == "owner" else "the project team"),
    ]
    if d.get("nota"):
        testa.append(d["nota"] + ".")
    righe = [
        x for x in dati["description"].split("\n\n") if not x.startswith("Suggested destination")
    ]
    righe[0] = righe[0].replace("started by the user", "sent to ClickUp by the user")
    if d.get("suggerita"):
        righe.append(f"Suggested destination: {d['suggerita']}")
    dati.update(
        description="\n\n".join(testa + righe),
        tags=list(d["tag"]),
        priority=2 if esito == "to do" else 3,
    )
    return dati


def _manda_task(dati, lista_id, percorso, da):
    ""

    finto = os.environ.get("SB_CLICKUP_FINTO")
    if finto:
        if finto == "sparita":
            raise Errore(FRASI["smista_lista_sparita"].format(lista=percorso))
        if finto == "fallisci":
            raise Errore(FRASI["smista_task_no"].format(lista=percorso))
        Path(finto).write_text(
            json.dumps(
                {"quando": _adesso(), "lista": lista_id, **dati}, ensure_ascii=False, indent=1
            )
            + "\n"
        )
        return "https://app.clickup.com/t/finto"
    cs = _clickup()
    try:
        lista = cs.api_get(f"/list/{lista_id}")
    except Exception:  # noqa: BLE001 - a list that doesn't respond is a list that doesn't exist, for this gesture
        lista = {}
    if (
        not isinstance(lista, dict)
        or str(lista.get("id") or "") != str(lista_id)
        or lista.get("archived")
    ):
        raise Errore(FRASI["smista_lista_sparita"].format(lista=percorso))
    stato, testo = cs.api_post(f"/list/{lista_id}/task", dati)
    try:
        j = json.loads(testo)
    except ValueError:
        j = {}
    if stato not in (200, 201) or not j.get("id"):
        raise Errore(FRASI["smista_task_no"].format(lista=percorso))
    cs.audit("create_task", j["id"], dati["name"], {"list": lista_id, "da": da})
    return j.get("url") or f"https://app.clickup.com/t/{j['id']}"


def smista(ident, esito="", progetto="", rimetti=False):
    ""



    a = arch()
    if not hasattr(a, "conferma_smistamento"):
        raise Errore(FRASI["archivio_vecchio"])
    S = _smista_regole()
    with _lucchetto_atteso(LUCCHETTO_SMISTA) as mio:
        if not mio:
            raise Errore(FRASI["smista_in_corso"])
        note = a.carica()
        r = a._prendi(note, ident)
        if rimetti:


            sc = _scope_di(a, r)
            c = dict((a.smistamento_di(r) or {}).get("confermato") or {})
            if int(sc.get("versione") or 0) and _confermato(sc) and getattr(a, "riapri", None):
                a.riapri(r, via="app")
            else:
                c = a.rimetti_smistamento(r)
            _salva_e_segna(a, note, ident)
            return {"rimesso": True, "era": c.get("esito"), "fase": a.fase_di(note[ident])}
        sm = a.smistamento_di(r)
        if sm.get("confermato"):
            raise Errore(FRASI["smista_gia"])
        prop = sm.get("proposta") or {}
        esito = esito or prop.get("esito") or ""
        if not esito:
            raise Errore(FRASI["smista_senza_proposta"])
        if esito not in S.ESITI:
            raise Errore(FRASI["smista_esito"])
        progetto = progetto or _progetto_di(r)
        d = S.destinazione(
            esito,
            progetto,
            prop.get("attivita") or "",
            prop.get("chi_esegue") or "team",
            bool(prop.get("delicato")),
        )
        percorso = " / ".join(d["percorso"])
        task = ""


        task_spenta = bool(d["crea_task"]) and not _task_accesa("team")
        if d["crea_task"] and not task_spenta:

            gia = next(
                (t["id"] for t in reversed(_task_esistenti(a, r)) if t["dove"] == "clickup"), ""
            )
            task = gia or _manda_task(
                _task_smistamento(r, d, esito, progetto),
                d["lista_id"],
                percorso,
                "SBK, smistamento di Inspiration",
            )
            if not gia:

                _segna_task_nata(a, ident, {"dove": "clickup", "id": task, "lista": percorso})
        note = a.carica()
        r = note[ident]
        a.conferma_smistamento(r, esito, progetto, percorso, task, via="app")


        _scope_coerente(a, r, esito)
        _salva_e_segna(a, note, ident)
        return {
            "esito": esito,
            "lista": percorso,
            "task": task,
            "task_spenta": task_spenta,
            "nota": d["nota"],
            "fase": a.fase_di(note[ident]),
        }





STRADE = ("riferimento", "studio", "cosa_da_fare", "sviluppo", "non_serve")
USCITE = ("riferimento", "cosa_da_fare", "non_serve")

TIPI_SCOPE = ("funzione", "strumento", "contenuto", "negozio_sito", "idea_societa", "lettura")

CAMPI_DI_OWNER = ("strada", "tipo", "progetto", "area", "chi")


ATTIVITA_MOTORE = Path(os.environ.get("SB_ATTIVITA_MOTORE") or QUI / "sb-motore.py")





CHIAVE_TASK = {"owner": "task_in_attivita", "team": "task_su_clickup"}


def _scope_di(a, r):
    ""

    f = getattr(a, "scope_di", None)
    try:
        s = f(r) if f else {}
    except Exception:  # noqa: BLE001 - a scope that can't be read must not turn off today's gesture
        s = {}
    return s if isinstance(s, dict) else {}


def _passo_di(a, r):
    ""
    f = getattr(a, "passo_di", None)
    if f:
        with contextlib.suppress(Exception):
            return str(f(r) or "")
    fase = a.fase_di(r)
    return {
        "da capire": "capire",
        "perche": "scope",
        "lavorazione": "contesto",
        "pronta": "implementazione",
        "avviata": "implementazione",
        "arrivata": "test",
        "tenuta": "riferimento",
        "scartata": "non_serve",
        "in_clickup": "cosa_da_fare",
    }.get(fase, fase)


def _confermato(sc):
    return bool(sc.get("confermato"))


def _versione_di(a, r):
    return int(_scope_di(a, r).get("versione") or 0)


def _scope_cambiato(a, r):
    ""

    return {
        "ok": False,
        "avviso": True,
        "codice": "scope_cambiato",
        "messaggio": FRASI["scope_cambiato"],
        "versione": _versione_di(a, r),
        "passo": _passo_di(a, r),
        "fase": a.fase_di(r),
        "tocca": a.tocca_a(r),
    }


def _versione_letta(versione):
    ""
    if versione in (None, ""):
        return None
    try:
        return int(str(versione).strip())
    except ValueError:
        raise Errore(FRASI["scope_valore"]) from None


def _scope_coerente(a, r, esito_smista=""):
    ""





    f = getattr(a, "conferma_scope", None)
    if not f or not _accetta(f, "solo_segna"):
        return False
    L = r.get("lavorazione") or {}
    pc = L.get("perche") or {}
    sm = (L.get("smistamento") or {}).get("confermato") or {}
    if not sm:
        return False
    esito = esito_smista or sm.get("esito") or ""
    esce = esito in ("tenuto", "scartato") or bool(sm.get("task"))
    if not (pc.get("confermato") or esce):
        return False
    sc = _scope_di(a, r)
    if not sc or not int(sc.get("versione") or 0):
        return False
    strada = STRADA_DA_ESITO.get(esito)
    if strada and strada != sc.get("strada"):
        if not (strada == "sviluppo" and sc.get("strada") == "studio"):
            with contextlib.suppress(SystemExit, Errore):
                _metti_scope(a, r, {"strada": strada}, "owner")
            sc = _scope_di(a, r)
    if _confermato(sc):
        return False
    try:
        f(r, via="app", solo_segna=True)
    except SystemExit:
        return False
    return True



STRADA_DA_ESITO = {
    "tenuto": "riferimento",
    "scartato": "non_serve",
    "to do": "cosa_da_fare",
    "backlog": "cosa_da_fare",
    "roadmap": "sviluppo",
    "in lavorazione": "sviluppo",
}


def _task_accesa(chi):
    ""
    return _leggi_cfg(CAPISCI_DA_SOLO).get(CHIAVE_TASK["owner" if chi == "owner" else "team"]) is True


def _attivita(*argomenti, tempo=120):
    ""


    py = str(VENV if VENV.exists() else sys.executable)
    ambiente = {**os.environ, "SB_ATTIVITA_DA": "inspiration"}
    try:
        p = subprocess.run(
            [py, str(ATTIVITA_MOTORE), "cose", *argomenti],
            capture_output=True,
            text=True,
            timeout=tempo,
            cwd=str(ROOT),
            env=ambiente,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    for riga in reversed((p.stdout or "").strip().splitlines()):
        try:
            d = json.loads(riga)
        except ValueError:
            continue
        if isinstance(d, dict):
            return d
    return None




TEMPO_ORIGINI_S = 5


def origini_in_attivita():
    ""


    d = _attivita("origini", "inspiration", tempo=TEMPO_ORIGINI_S)
    if not isinstance(d, dict) or d.get("ok") is not True or not isinstance(d.get("origini"), dict):
        return None
    return {str(k): x for k, x in d["origini"].items() if isinstance(x, dict) and x.get("id")}


def _origine_in_attivita(ident):
    ""

    o = _attivita("origine", "inspiration", ident)
    if not (isinstance(o, dict) and o.get("ok") and o.get("c_e") and o.get("id")):
        return None, ""
    return ("eliminata" if o.get("eliminata") else "viva"), str(o["id"])


def _descrizione_attivita(r, sc):
    ""

    righe = []
    parole = [
        str(x.get("testo") or "")
        for x in (sc.get("parole_di_owner_accanto") or _parole_di_owner(r))
        if isinstance(x, dict) and x.get("testo")
    ]
    righe += [f"«{t}»" for t in dict.fromkeys(parole)]
    if sc.get("dove_arrivare"):
        righe.append(str(sc["dove_arrivare"]))
    if r.get("url"):
        righe.append(str(r["url"]))
    return "\n\n".join(righe) or _titolo_voce(r)



TITOLO_TASK_MAX = 80
TITOLO_TASK_VIRGOLA_MIN = 40



PAROLE_VUOTE_IN_CODA = frozenset(
    "il lo la i gli le l' un uno una un' di a da in con su per tra fra e ed o od né ma che "
    "del dello della dei degli delle dell' al allo alla ai agli alle all' dal dallo dalla dai dagli dalle dall' "
    "nel nello nella nei negli nelle nell' sul sullo sulla sui sugli sulle sull' col coi".split()
)


_ARTICOLO_DOPO_A = {
    "al": "il ",
    "allo": "lo ",
    "alla": "la ",
    "ai": "i ",
    "agli": "gli ",
    "alle": "le ",
    "all'": "l'",
}
_VUOI_ARRIVARE = re.compile(
    r"^(?:[^.!?]*?,\s*)?vuoi arrivare\s+(a|ad|al|allo|alla|ai|agli|alle|all')(?:\s+|(?<='))",
    re.I,
)


def _senza_vuoi_arrivare(t):
    ""

    m = _VUOI_ARRIVARE.match(t)
    if not m:
        return t
    return _ARTICOLO_DOPO_A.get(m.group(1).casefold(), "") + t[m.end() :]


def _titolo_attivita(r, sc):
    ""

    testo = ""
    for k in ("dove_arrivare", "cosa_intendi"):
        t = " ".join(str(sc.get(k) or "").split())
        t = re.split(r"(?<=[.!?])\s", t)[0].rstrip(" .")
        t = _senza_vuoi_arrivare(t)
        t = re.sub(
            r"^(vuoi|l'hai salvato per|l'hai salvato perché)\s+",
            "",
            t,
            flags=re.I,
        )
        if t:
            testo = t
            break
    testo = testo or " ".join(_titolo_voce(r).split())
    if len(testo) > TITOLO_TASK_MAX:


        pezzo = testo[:TITOLO_TASK_MAX]
        alla_virgola = pezzo[: pezzo.rfind(",")].rstrip() if "," in pezzo else ""
        if len(alla_virgola) >= TITOLO_TASK_VIRGOLA_MIN:
            testo = alla_virgola
        else:


            parole = pezzo.rsplit(" ", 1)[0].rstrip(" ,;").split(" ")
            while len(parole) > 1 and parole[-1].strip(",;") in PAROLE_VUOTE_IN_CODA:
                parole.pop()
            testo = " ".join(parole).rstrip(" ,;") + "…"
    testo = testo[:1].upper() + testo[1:]
    progetto = _progetto_del_titolo(sc)
    if progetto:
        testo = f"{progetto} · {testo}"
    return testo[:150] or r["id"]


def _progetto_del_titolo(sc):
    ""

    progetto = str(sc.get("progetto") or "").strip()
    try:
        a_vista = _parole()._progetto_a_vista
    except (ImportError, AttributeError):
        return "" if progetto.casefold() == "altro" else progetto
    return a_vista({"scope": {**sc, "progetto": progetto}}, progetto)


def _area_attivita(progetto):
    ""

    progetto = str(progetto or "").strip()
    if not progetto:
        return ""
    d = _attivita("impostazioni")
    if not isinstance(d, dict) or not d.get("ok"):
        return ""
    for a in d.get("aree_def") or []:
        if not isinstance(a, dict) or a.get("tolta") or a.get("senza") or a.get("unita_in"):
            continue
        if str(a.get("nome") or "").strip().casefold() == progetto.casefold():
            return str(a["nome"])
    return ""


def _task_in_attivita(r, sc, titolo=None, descrizione=None, rifai=False):
    ""





    o = _attivita("origine", "inspiration", r["id"])
    if not isinstance(o, dict) or not o.get("ok"):
        raise Errore(FRASI["scope_attivita_no"])
    if o.get("c_e") and not o.get("eliminata"):
        return {"dove": "attivita", "id": str(o.get("id") or ""), "c_era": True}
    if o.get("c_e") and o.get("eliminata") and not rifai:
        raise Eliminata(FRASI["scope_attivita_eliminata"])
    if rifai and not o.get("c_e"):
        raise Errore(FRASI["rifai_niente"])
    argomenti = [
        "nuova",
        titolo or _titolo_attivita(r, sc),
        "stato=da_fare",
        "origine_fonte=inspiration",
        f"origine_id={r['id']}",
    ]
    if rifai:


        argomenti.append("se_eliminata=nuova")
    area = _area_attivita(sc.get("progetto"))
    if area:
        argomenti.append(f"area={area}")
    url = str(r.get("url") or "")
    if re.match(r"^https?://\S+$", url) and len(url) <= 2000:
        argomenti.append(f"origine_url={url}")
    n = _attivita(*argomenti)
    if not isinstance(n, dict):
        raise Errore(FRASI["scope_attivita_no"])
    if not n.get("ok"):
        if n.get("eliminata"):
            raise Eliminata(FRASI["scope_attivita_eliminata"])
        raise Errore(FRASI["scope_attivita_no"])
    tid = str(n.get("id") or "")
    if not tid:
        raise Errore(FRASI["scope_attivita_no"])
    c_era = bool(n.get("c_era"))
    out = {"dove": "attivita", "id": tid, "c_era": c_era}
    if not c_era:


        d = _attivita("descrizione", tid, descrizione or _descrizione_attivita(r, sc))
        out["descrizione_scritta"] = isinstance(d, dict) and d.get("ok") is True
        if not out["descrizione_scritta"]:
            with contextlib.suppress(Exception):
                a = arch()
                note = a.carica()
                a._segna(note[r["id"]], STORIA_DESCRIZIONE_NO, "task", "SBK")
                a.salva(note)
    return out




STORIA_DESCRIZIONE_NO = "the description of the task in Activities wasn't written"


def _con_descrizione(messaggio, task):
    ""

    if task and task.get("descrizione_scritta") is False:
        return f"{messaggio}. {FRASI['task_descrizione_no']}"
    return messaggio


def _task_al_team(a, r, sc):
    ""


    gia = next((t["id"] for t in reversed(_task_esistenti(a, r)) if t["dove"] == "clickup"), "")
    S = _smista_regole()
    prop = (r["lavorazione"].get("smistamento") or {}).get("proposta") or {}
    esito = prop.get("esito") if prop.get("esito") in S.CON_TASK else "to do"
    progetto = sc.get("progetto") or _progetto_di(r)
    d = S.destinazione(esito, progetto, sc.get("area") or prop.get("attivita") or "", "team", False)
    percorso = " / ".join(d["percorso"])
    if gia:
        return {"dove": "clickup", "id": gia, "c_era": True, "lista": percorso, "esito": esito}
    if not d["crea_task"]:
        raise Errore(FRASI["scope_delicato"])
    url = _manda_task(
        _task_smistamento(r, d, esito, progetto),
        d["lista_id"],
        percorso,
        "SBK, Inspiration scope",
    )
    return {"dove": "clickup", "id": url, "c_era": False, "lista": percorso, "esito": esito}




TASK_NATE = "TASK-NATE.json"


def _task_esistenti(a, r):
    ""

    out = []

    def metti(valore, lista=""):
        v = str(valore or "")
        if not v:
            return
        dove = "attivita" if v.startswith("attivita:") else "clickup"
        tid = v.removeprefix("attivita:")
        if any(t["dove"] == dove and t["id"] == tid for t in out):
            return
        out.append({"dove": dove, "id": tid, "lista": str(lista or "")})


    nate = []
    with contextlib.suppress(Exception):
        cl = a.cartella_lavorazione(r["id"])
        for q in (cl / TASK_NATE, AVVISI_SENZA_CARTELLA / cl.name / TASK_NATE):
            x = _json_di(q)
            nate += x if isinstance(x, list) else []
    with contextlib.suppress(Exception):
        for t in nate:
            if isinstance(t, dict) and t.get("id"):
                metti(
                    ("attivita:" if t.get("dove") == "attivita" else "") + str(t["id"]),
                    t.get("lista"),
                )
    link = r.get("link") or {}
    for v in link.get("task_di_prima") or []:
        metti(v)
    conf = ((r.get("lavorazione") or {}).get("smistamento") or {}).get("confermato") or {}
    metti(conf.get("task"), conf.get("lista"))
    metti(link.get("task"))
    metti((r.get("attivita") or {}).get("task_url"))
    return out


def _segna_task_nata(a, ident, task):
    ""


    valore = f"attivita:{task['id']}" if task["dove"] == "attivita" else str(task["id"])

    if _cartella_sparita_col_pannello(ident):
        cl = _posto_del_giro(a.cartella_lavorazione(ident), crea=True)
    else:
        cl = a.cartella_lavorazione(ident, crea=True)


    if cl is not None:
        registro = _json_di(cl / TASK_NATE)
        registro = registro if isinstance(registro, list) else []
        registro.append(
            {
                "dove": task["dove"],
                "id": str(task["id"]),
                "lista": task.get("lista") or "",
                "quando": _adesso(),
            }
        )
        _scrivi_json(cl / TASK_NATE, registro)
    note = a.carica()
    r = note[ident]
    link = r.setdefault("link", {})
    if link.get("task") and link["task"] != valore:
        link.setdefault("task_di_prima", []).append(link["task"])
    link["task"] = valore
    r.setdefault("attivita", {})["task_url"] = valore
    a._segna(r, f"task created, {valore}", "task", "SBK")
    a.salva(note)
    return valore


def _dove_frase(task):
    ""
    if task["dove"] == "attivita":
        return "in Activities"
    return f"on ClickUp in {task['lista']}" if task.get("lista") else "on ClickUp"


def _forma_di(testo):
    ""

    return "domanda" if str(testo or "").rstrip().endswith("?") else "correzione"


def _raddrizza(a, r, campi, testo, audio, durata):
    ""




    f = getattr(a, "raddrizza_scope", None)
    if not f:
        raise Errore(FRASI["archivio_vecchio"])
    altro = {}
    if durata is not None and _accetta(f, "durata"):
        altro["durata"] = _durata(durata)
    if testo and _accetta(f, "forma"):
        altro["forma"] = _forma_di(testo)
    out = f(r, campi, testo=testo, audio=audio or None, via="app", **altro)
    if isinstance(out, tuple) and not out[0] and out[1] and out[1] != "uguale a prima":

        raise Errore(FRASI["scope_valore"])
    return out


def _cambia_forma(a, r, indice, forma):
    ""



    pareri = r.get("pareri") or []
    if not (isinstance(indice, int) and 0 <= indice < len(pareri)) or forma not in (
        "domanda",
        "correzione",
    ):
        return False
    if (pareri[indice].get("forma") or "correzione") == forma:
        return False
    f = getattr(a, "riforma_parere", None) or getattr(a, "cambia_forma", None)
    if not f:
        return False
    out = f(r, indice, forma, "rilettura")
    return bool(out[0] if isinstance(out, tuple) else out)


def _metti_scope(a, r, proposta, da):
    ""

    f = getattr(a, "metti_scope", None)
    if not f:
        raise Errore(FRASI["archivio_vecchio"])
    out = f(r, proposta, da)
    if isinstance(out, tuple):
        return bool(out[0]), str(out[1] if len(out) > 1 else "")
    return bool(out), ""


def _leggi_risposte(percorso):
    ""
    if not percorso:
        return {}
    d = _json_di(percorso)
    if not isinstance(d, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in d.items()
    ):
        raise Errore(FRASI["scope_risposte_illeggibili"])
    return {k: v for k, v in d.items() if v.strip()}


def _uscito(passo):
    return passo in (*USCITE, "letto")


def scope(
    ident,
    giusto=False,
    testo="",
    audio="",
    strada="",
    tipo="",
    progetto="",
    area="",
    chi="",
    risposte="",
    tieni=False,
    rifai=False,
    durata=None,
    domanda="",
    prendi=False,
    versione=None,
):
    ""











    a = arch()
    if not hasattr(a, "scope_di"):
        raise Errore(FRASI["archivio_vecchio"])
    if tieni and rifai:
        raise Errore(FRASI["scope_tieni_o_rifai"])
    if (strada and strada not in STRADE) or (tipo and tipo not in TIPI_SCOPE):
        raise Errore(FRASI["scope_valore"])
    if chi and chi not in ("owner", "team"):
        raise Errore(FRASI["scope_valore"])
    if tipo and strada and strada not in ("studio", "sviluppo"):
        raise Errore(FRASI["scope_tipo_senza_strada"])
    dette = _leggi_risposte(risposte)
    versione = _versione_letta(versione)
    if prendi:


        if (
            giusto
            or testo
            or audio
            or strada
            or tipo
            or progetto
            or area
            or chi
            or dette
            or tieni
            or rifai
        ):
            raise Errore(FRASI["scope_prendi_da_sola"])
        note = a.carica()
        r = a._prendi(note, ident)
        if _agente_aperto(a, r):

            raise Avviso(FRASI["scope_agente_aperto"])
        sc = _scope_di(a, r)
        if not (_confermato(sc) and isinstance(sc.get("proposta_dopo"), dict)):
            raise Errore(FRASI["scope_niente_proposta"])
        if not _accetta(a.conferma_scope, "prendi_proposta_dopo"):
            raise Errore(FRASI["archivio_vecchio"])
        esito = _giusto(a, ident, atteso=versione)

        if (
            esito.get("ok") is not False
            and not esito.get("uscita")
            and not esito.get("task")
            and not esito.get("gia")
        ):
            esito["messaggio"] = FRASI["scope_proposta_presa"]
        note = a.carica()
        r = note[ident]
        _avviso_dopo_il_giusto(a, r)
        return {**esito, "passo": _passo_di(a, r), "fase": a.fase_di(r), "tocca": a.tocca_a(r)}
    with _lucchetto_atteso(LUCCHETTO_SMISTA) as mio:
        if not mio:
            raise Errore(FRASI["smista_in_corso"])
        note = a.carica()
        r = a._prendi(note, ident)

        if versione is not None and _versione_di(a, r) != versione:
            return _scope_cambiato(a, r)
        passo = _passo_di(a, r)
        if passo in ("capire", "a_parte", "a parte", "da capire", ""):
            raise Errore(FRASI["scope_non_ancora"])
        if (tieni or rifai) and _agente_aperto(a, r):

            raise Avviso(FRASI["scope_agente_aperto"])
        if rifai and _lavoro_aperto(r):


            raise Avviso(FRASI["scope_rifai_lavoro_aperto"])
        if tieni or rifai:
            scegli = getattr(a, "scegli_cambio_scope", None)
            cambio = getattr(a, "cambio_scope_di", None)
            if not (scegli and cambio):
                raise Errore(FRASI["archivio_vecchio"])
            if not cambio(r):
                raise Errore(FRASI["scope_niente_da_rifare"])
            fatto = scegli(r, "tieni" if tieni else "rifai", via="app")
            _salva_e_segna(a, note, ident)
            r = note[ident]
            return {
                "messaggio": FRASI["scope_tieni" if tieni else "scope_rifai"],
                "passo": _passo_di(a, r),
                "passi": list((fatto or {}).get("passi") or []),
                "fase": a.fase_di(r),
                "tocca": a.tocca_a(r),
            }
        campi = {
            k: v
            for k, v in (
                ("strada", strada),
                ("tipo", tipo),
                ("progetto", progetto),
                ("area", area),
                ("chi", chi),
            )
            if v
        }

        risposta = bool(domanda and (testo or audio))
        if domanda and not risposta:
            raise Errore(FRASI["scope_risposte_illeggibili"])
        raddrizza = bool(((testo or audio) and not risposta) or campi)
        if raddrizza and _agente_aperto(a, r):



            _metti_da_parte(a, r, audio, FRASI["scope_agente_aperto"])
            raise Avviso(FRASI["scope_agente_aperto"])
        prima = _scope_di(a, r)
        if tipo and not strada and prima.get("strada") not in ("studio", "sviluppo"):
            raise Errore(FRASI["scope_tipo_senza_strada"])
        if risposta:
            dette = {**dette, domanda: testo}
        if _uscito(passo) and (giusto or raddrizza or dette):
            raise Errore(FRASI["scope_uscito"])
        if (
            giusto
            and not raddrizza
            and not dette
            and _confermato(prima)
            and not prima.get("proposta_dopo")
        ):
            raise Avviso(FRASI["scope_gia"])
        ri = r["lavorazione"].get("rilettura") or {}



        rilegge = bool(
            ri.get("aperta_quando")
            and not ri.get("chiusa_quando")
            and _processo_vivo(ri.get("pid"))
            and (_json_di(Path(str(ri.get("cartella") or "")) / "processo.json") or {}).get(
                "claude_partito"
            )
        )
        if giusto and not raddrizza and rilegge:

            raise Errore(FRASI["rilettura_risposta_in_corso"])
        scritto = False


        tradotte = (
            {TUTTE: _tutte(a, r, "scope", audio if risposta and domanda == TUTTE else "")}
            if TUTTE in dette
            else {}
        )

        for dom, t in dette.items():
            dom_vera, piu = tradotte.get(dom, (dom, {}))
            if risposta and dom == domanda:
                altro = dict(piu)
                if durata is not None and _accetta(a.rispondi, "durata"):
                    altro["durata"] = _durata(durata)
                a.rispondi(r, dom_vera, testo, audio or None, via="app", **altro)
            else:
                a.rispondi(r, dom_vera, t, None, via="app", **piu)
            scritto = True


        if raddrizza:
            if risposta:
                _raddrizza(a, r, campi, "", "", None)
            else:
                _raddrizza(a, r, campi, testo, audio, durata)
            scritto = True
        if scritto:
            _salva_e_segna(a, note, ident)

            _in_sottofondo(ident)

        dopo = note[ident]
        versione_dopo = _versione_di(a, dopo)
        strada_dopo = _scope_di(a, dopo).get("strada") or ""


    parole = bool(((testo or audio) and not risposta) or dette)
    if giusto and parole and strada_dopo in USCITE:
        r = a.carica()[ident]
        return {
            "messaggio": FRASI[
                "scope_parole_prima_di_uscire_agente"
                if _agente_aperto(a, r)
                else "scope_parole_prima_di_uscire"
            ],
            "passo": _passo_di(a, r),
            "fase": a.fase_di(r),
            "tocca": a.tocca_a(r),
        }
    if not giusto:
        note = a.carica()
        r = note[ident]
        return {
            "messaggio": FRASI[
                "scope_risposte" if dette and not raddrizza else "scope_raddrizzato"
            ],
            "passo": _passo_di(a, r),
            "fase": a.fase_di(r),
            "tocca": a.tocca_a(r),
        }
    esito = _giusto(a, ident, atteso=versione_dopo if versione is not None else None)
    gia = esito.pop("gia", False)
    if gia and dette:
        esito["messaggio"] = FRASI["scope_risposte"]
    elif gia and not raddrizza:
        esito.update(ok=False, avviso=True)
    elif raddrizza and esito.get("ok") is not False and not esito.get("uscita"):
        esito["messaggio"] = FRASI["scope_raddrizzato_giusto"]
    note = a.carica()
    r = note[ident]
    _avviso_dopo_il_giusto(a, r)
    return {**esito, "passo": _passo_di(a, r), "fase": a.fase_di(r), "tocca": a.tocca_a(r)}


def _avviso_dopo_il_giusto(a, r):
    ""









    if not (_lavoro_da_avvisare(a, r) or _spunto_da_avvisare(a, r)):
        return False
    _in_sottofondo(str(r.get("id") or ""))
    return True


def _spunto_da_avvisare(a, r):
    ""
    try:
        return _agente_aperto(a, r) and any(
            chi == "sessione" for chi, *_ in _avvisi_da_mandare(a, r)
        )
    except Exception:  # noqa: BLE001 an item that can't be read must not stop the user's gesture
        return False


def _giusto(a, ident, atteso=None):
    ""



    with _lucchetto_atteso(LUCCHETTO_SMISTA) as mio:
        if not mio:
            raise Errore(FRASI["smista_in_corso"])
        note = a.carica()
        r = a._prendi(note, ident)
        if atteso is not None and _versione_di(a, r) != atteso:
            return _scope_cambiato(a, r)
        sc = _scope_di(a, r)

        dopo = sc.get("proposta_dopo") if isinstance(sc.get("proposta_dopo"), dict) else None
        prendi = bool(
            _confermato(sc) and dopo and _accetta(a.conferma_scope, "prendi_proposta_dopo")
        )
        if _confermato(sc) and not prendi:

            return {"messaggio": FRASI["scope_gia"], "gia": True}
        if prendi:
            sc = {**sc, **{k: v for k, v in dopo.items() if k in sc and k not in ("da", "quando")}}
        strada = sc.get("strada") or ""
        if strada not in STRADE:
            return {"ok": False, "messaggio": FRASI["scope_senza_strada"], "avviso": True}
        if (r["lavorazione"].get("perche") or {}).get("correzione_in_arrivo"):

            return {"ok": False, "messaggio": FRASI["scope_a_voce_in_arrivo"], "avviso": True}


        task = None
        eliminata = False
        if strada == "cosa_da_fare":
            chi = "owner" if sc.get("chi") == "owner" else "team"
            dove = "attivita" if chi == "owner" else "clickup"
            esistenti = [] if sc.get("delicato") else _task_esistenti(a, r)
            stessa = [t for t in esistenti if t["dove"] == dove]
            altrove = [t for t in esistenti if t["dove"] != dove]
            try:
                if sc.get("delicato"):

                    task = None
                elif stessa and not (dove == "attivita" and _task_accesa(chi)):
                    task = {**stessa[-1], "c_era": True}
                    if dove == "attivita":



                        stato, tid = _origine_in_attivita(ident)
                        if stato == "eliminata":
                            task, eliminata = None, True
                        elif stato == "viva":
                            task["id"] = tid
                elif altrove and not stessa:


                    task = {**altrove[-1], "c_era": True, "di_prima": True}
                elif stessa or _task_accesa(chi):


                    task = _task_in_attivita(r, sc) if chi == "owner" else _task_al_team(a, r, sc)
                    if not task["c_era"]:
                        _segna_task_nata(a, ident, task)
            except Errore as e:
                return {"ok": False, "messaggio": str(e)}
        if task:

            note = a.carica()
            r = note[ident]
            a._segna(
                r,
                (
                    f"task in your Activities, {task['id']}"
                    if task["dove"] == "attivita"
                    else f"task on ClickUp in {task.get('lista') or ''}, {task['id']}"
                )
                + (", already existed" if task["c_era"] else ""),
                "scope",
                "owner",
            )
        f = a.conferma_scope
        altro = {"prendi_proposta_dopo": True} if prendi else {}
        if task:
            valore = f"attivita:{task['id']}" if task["dove"] == "attivita" else task["id"]
            if _accetta(f, "task"):
                altro["task"] = valore
            if _accetta(f, "lista"):
                altro["lista"] = task.get("lista") or "Your Activities"
        try:
            f(r, via="app", **altro)
        except SystemExit as e:
            return {
                "ok": False,
                "messaggio": str(e.code) if isinstance(e.code, str) else FRASI["non_andata"],
            }
        _salva_e_segna(a, note, ident)

        esce = _uscito(_passo_di(a, note[ident]))
    out = {}
    if strada in USCITE and esce:
        out["uscita"] = strada
    if strada == "riferimento":
        out["messaggio"] = FRASI["scope_riferimento"]
    elif strada == "non_serve":
        out["messaggio"] = FRASI["scope_non_serve"]
    elif task and task.get("di_prima"):
        out["messaggio"] = FRASI["scope_task_di_prima"].format(dove=_dove_frase(task))
    elif task and task["dove"] == "attivita":
        out["messaggio"] = _con_descrizione(
            FRASI["scope_attivita_c_era" if task["c_era"] else "scope_attivita"], task
        )
    elif task:
        out["messaggio"] = (
            FRASI["scope_team_c_era"]
            if task["c_era"]
            else FRASI["scope_team"].format(lista=task.get("lista") or "ClickUp")
        )
    elif strada == "cosa_da_fare" and sc.get("delicato"):
        out["messaggio"] = FRASI["scope_delicato_esce"]
    elif eliminata:
        out["messaggio"] = FRASI["scope_attivita_eliminata"]
    elif strada == "cosa_da_fare":
        out["messaggio"] = FRASI["scope_senza_task"]
    elif _agente_aperto(a, note[ident]) or _lavoro_aperto(note[ident]):

        out["messaggio"] = FRASI["scope_confermato"]
    else:
        out["messaggio"] = FRASI["scope_avanti"]
    if task:
        out["task"] = {k: task[k] for k in ("dove", "id", "c_era")}
        if task.get("lista"):
            out["task"]["lista"] = task["lista"]
    return out


def _segna_task(a, r, valore, lista):
    ""


    f = getattr(a, "segna_task", None)
    if f:
        return f(r, valore, lista, via="app")
    sm = r["lavorazione"].setdefault("smistamento", {})
    conf = sm.get("confermato") or {}
    conf.update(task=valore, lista=lista or conf.get("lista") or "")
    sm["confermato"] = conf
    r.setdefault("link", {})["task"] = valore
    r.setdefault("attivita", {}).update(task_url=valore, quando=_adesso())
    r["stato"] = "attività"
    if isinstance(r.get("a_mano"), dict):
        r["a_mano"]["stato"] = True
    a._segna(r, f"task created after going out, {valore}", "scope", "owner")
    return conf


def crea_task_uscita(ident, versione=None):
    ""


    a = arch()
    with _lucchetto_atteso(LUCCHETTO_SMISTA) as mio:
        if not mio:
            raise Errore(FRASI["smista_in_corso"])
        note = a.carica()
        r = a._prendi(note, ident)
        versione = _versione_letta(versione)
        if versione is not None and _versione_di(a, r) != versione:
            return _scope_cambiato(a, r)
        sc = _scope_di(a, r)

        if not (sc.get("aspetta_task") or _passo_di(a, r) == "cosa_da_fare"):
            raise Errore(FRASI["crea_task_niente"])
        chi = "owner" if sc.get("chi") == "owner" else "team"
        dove = "attivita" if chi == "owner" else "clickup"
        esistenti = _task_esistenti(a, r)
        stessa = [t for t in esistenti if t["dove"] == dove]
        altrove = [t for t in esistenti if t["dove"] != dove]
        if stessa:
            t = dict(stessa[-1])
            if dove == "attivita":


                stato, tid = _origine_in_attivita(ident)
                if stato == "eliminata":
                    raise Eliminata(FRASI["scope_attivita_eliminata"])
                if stato == "viva":
                    t["id"] = tid
            return {
                "messaggio": FRASI[
                    "scope_attivita_c_era" if dove == "attivita" else "scope_team_c_era"
                ],
                "uscita": "cosa_da_fare",
                "passo": "cosa_da_fare",
                "task": {
                    "dove": dove,
                    "id": t["id"],
                    "c_era": True,
                    **({"lista": t["lista"]} if t["lista"] else {}),
                },
            }
        if sc.get("delicato"):
            raise Avviso(FRASI["crea_task_delicato"])
        if not _task_accesa(chi):
            raise Avviso(FRASI["scope_task_spenta"])
        task = _task_in_attivita(r, sc) if chi == "owner" else _task_al_team(a, r, sc)
        valore = f"attivita:{task['id']}" if task["dove"] == "attivita" else task["id"]
        if not task["c_era"]:
            _segna_task_nata(a, ident, task)
        note = a.carica()
        r = note[ident]
        _segna_task(a, r, valore, task.get("lista") or "Your Activities")
        a.salva(note)
        r = note[ident]
    if altrove:

        messaggio = FRASI["scope_task_due"].format(
            qui=_dove_frase(task), li=_dove_frase(altrove[-1])
        )
    elif task["dove"] == "attivita":
        messaggio = FRASI["scope_attivita_c_era" if task["c_era"] else "scope_attivita"]
    else:
        messaggio = (
            FRASI["scope_team_c_era"]
            if task["c_era"]
            else FRASI["scope_team"].format(lista=task.get("lista") or "ClickUp")
        )
    out = {
        "messaggio": _con_descrizione(messaggio, task),
        "uscita": "cosa_da_fare",
        "passo": _passo_di(a, r),
        "task": {k: task[k] for k in ("dove", "id", "c_era")},
        "fase": a.fase_di(r),
        "tocca": a.tocca_a(r),
    }
    if task.get("lista"):
        out["task"]["lista"] = task["lista"]
    return out


def rifai_task(ident, versione=None):
    ""






    a = arch()
    with _lucchetto_atteso(LUCCHETTO_SMISTA) as mio:
        if not mio:
            raise Errore(FRASI["smista_in_corso"])
        note = a.carica()
        r = a._prendi(note, ident)
        versione = _versione_letta(versione)
        if versione is not None and _versione_di(a, r) != versione:
            return _scope_cambiato(a, r)
        sc = _scope_di(a, r)
        if sc.get("delicato"):
            raise Avviso(FRASI["crea_task_delicato"])
        if not _task_accesa("owner"):
            raise Avviso(FRASI["scope_task_spenta"])
        ag = (r.get("attivita") or {}).get("agente") or {}
        pi = (r.get("lavorazione") or {}).get("piano") or {}
        arrivo = " ".join(str(pi.get("punto_di_arrivo") or "").split())
        titolo = descrizione = None
        if ag.get("avviato_quando") and arrivo:
            sc = {**sc, "dove_arrivare": arrivo}
            titolo, descrizione = _titolo_attivita(r, sc), _descrizione_avvio(r, sc)
        task = _task_in_attivita(r, sc, titolo=titolo, descrizione=descrizione, rifai=True)
        if task["c_era"]:

            return {
                "ok": False,
                "avviso": True,
                "messaggio": FRASI["scope_attivita_c_era"],
                "task": {"dove": "attivita", "id": task["id"], "c_era": True},
                "passo": _passo_di(a, r),
                "fase": a.fase_di(r),
                "tocca": a.tocca_a(r),
            }
        _segna_task_nata(a, ident, task)
        note = a.carica()
        r = note[ident]
        valore = f"attivita:{task['id']}"
        conf = ((r.get("lavorazione") or {}).get("smistamento") or {}).get("confermato") or {}
        if str(conf.get("task") or "").startswith("attivita:"):
            _segna_task(a, r, valore, conf.get("lista") or "Your Activities")
        a._segna(r, f"task recreated in your Activities {task['id']}", "task", "owner")
        _salva_e_segna(a, note, ident)
        r = note[ident]
    return {
        "messaggio": _con_descrizione(FRASI["rifai_task_nata"], task),
        "passo": _passo_di(a, r),
        "task": {"dove": "attivita", "id": task["id"], "c_era": False},
        "fase": a.fase_di(r),
        "tocca": a.tocca_a(r),
    }


def letto(ident, versione=None):
    ""

    a = arch()
    f = getattr(a, "segna_letto", None)
    if not f:
        raise Errore(FRASI["archivio_vecchio"])
    with _lucchetto_atteso(LUCCHETTO_SMISTA) as mio:
        if not mio:
            raise Errore(FRASI["smista_in_corso"])
        note = a.carica()
        r = a._prendi(note, ident)
        versione = _versione_letta(versione)
        if versione is not None and _versione_di(a, r) != versione:
            return _scope_cambiato(a, r)
        sc = _scope_di(a, r)
        if sc.get("strada") != "studio" or not _confermato(sc):
            raise Errore(FRASI["letto_niente"])
        scheda = str((r["lavorazione"].get("scheda") or {}).get("file") or "")
        q = (
            a._assoluto(scheda)
            if scheda and hasattr(a, "_assoluto")
            else (Path(scheda) if scheda else None)
        )
        if not (q and Path(q).is_file()):
            raise Avviso(FRASI["letto_aspetta_scheda"])
        try:
            f(r, via="app")
        except SystemExit:
            raise Avviso(FRASI["letto_aspetta_scheda"]) from None
        a.salva(note)
        r = note[ident]
    return {
        "uscita": "letto",
        "passo": _passo_di(a, r),
        "fase": a.fase_di(r),
        "tocca": a.tocca_a(r),
    }


def riapri(ident, versione=None):
    ""

    a = arch()
    f = getattr(a, "riapri", None)
    if not f:
        raise Errore(FRASI["archivio_vecchio"])
    with _lucchetto_atteso(LUCCHETTO_SMISTA) as mio:
        if not mio:
            raise Errore(FRASI["smista_in_corso"])
        note = a.carica()
        r = a._prendi(note, ident)
        versione = _versione_letta(versione)
        if versione is not None and _versione_di(a, r) != versione:
            return _scope_cambiato(a, r)
        uscito = _uscito(_passo_di(a, r))
        if not (uscito or _confermato(_scope_di(a, r))):
            raise Errore(FRASI["riapri_niente"])
        if not uscito and _agente_aperto(a, r):



            raise Avviso(FRASI["scope_agente_aperto"])
        task = (r.get("link") or {}).get("task") or (r.get("attivita") or {}).get("task_url") or ""
        f(r, via="app")
        _salva_e_segna(a, note, ident)
        r = note[ident]
        out = {
            "messaggio": FRASI["riapri_con_task" if task else "riapri"],
            "passo": _passo_di(a, r),
            "fase": a.fase_di(r),
            "tocca": a.tocca_a(r),
        }
        if task:
            dove = "attivita" if str(task).startswith("attivita:") else "clickup"
            out["task"] = {"dove": dove, "id": str(task).removeprefix("attivita:"), "c_era": True}
        return out










def _coppie_lista(coppie):
    ""

    out, visti = [], set()
    for c in coppie or []:
        ident, sep, ver = str(c).strip().rpartition(":")
        if not sep or not ident.strip():
            raise Errore(FRASI["lista_coppie"])
        try:
            n = int(ver)
        except ValueError:
            raise Errore(FRASI["lista_coppie"]) from None
        if n < 0:
            raise Errore(FRASI["lista_coppie"])
        if ident in visti:
            continue
        visti.add(ident)
        out.append((ident, n))
    if not out:
        raise Errore(FRASI["lista_coppie"])
    return out


def _vie_usate(a, note):
    ""
    usate = set()
    for r in note.values():
        sc = _scope_di(a, r)
        usate.add(str(sc.get("confermato_via") or ""))
        for c in sc.get("conferme_di_prima") or []:
            if isinstance(c, dict):
                usate.add(str(c.get("confermato_via") or ""))
    return usate


def _id_gruppo(a, note, strada, P):
    ""

    base = re.sub(r"[^0-9T]", "", _adesso()).replace("T", "-")
    coda = f"-{strada}" if strada else ""
    usate = _vie_usate(a, note)
    gid, n = f"{base}{coda}", 2
    while P.VIA_LISTA + gid in usate:
        gid, n = f"{base}-{n}{coda}", n + 1
    return gid


def _voce_bacheca(a, r, P):
    ""
    vx = json.loads(json.dumps(a.voce_export(r), ensure_ascii=False, default=str))
    return vx, P._voce(vx)


def _fuori_dalla_conferma(a, r, versione, strada, P):
    ""



    sc = _scope_di(a, r)
    if _versione_di(a, r) != versione:
        return "versione"
    if _confermato(sc):
        return "gia"
    if sc.get("strada") not in P.STRADE_LISTA:
        return "strada"
    if strada and sc.get("strada") != strada:
        return "strada_cambiata"
    if _passo_di(a, r) != "scope" or sc.get("aspetta_task"):
        return "passo"
    if sc.get("delicato"):
        return "delicato"
    if _agente_aperto(a, r):
        return "agente"
    if _lavoro_aperto(r):
        return "lavoro"
    L = r.get("lavorazione") or {}
    ri = L.get("rilettura") or {}
    if ri.get("aperta_quando") and not ri.get("chiusa_quando"):
        return "rilettura"
    if (L.get("perche") or {}).get("correzione_in_arrivo") or sc.get("proposta_dopo"):
        return "in_arrivo"
    if not hasattr(a, "voce_export"):
        return "non_andata"
    _vx, v = _voce_bacheca(a, r, P)
    return P.fuori_dalla_lista(v)


def _uscita_lista(ident, motivo, prefisso):
    return {
        "id": ident,
        "motivo": motivo,
        "frase": FRASI.get(prefisso + motivo, FRASI["non_andata"]),
    }


def conferma_lista(coppie, strada=""):
    ""





    a = arch()
    if not hasattr(a, "conferma_scope"):
        raise Errore(FRASI["archivio_vecchio"])
    P = _parole()
    if strada and strada not in P.STRADE_LISTA:
        raise Errore(FRASI["lista_strada"])
    voci = _coppie_lista(coppie)
    with _lucchetto_atteso(LUCCHETTO_SMISTA) as mio:
        if not mio:
            raise Errore(FRASI["smista_in_corso"])
        note = a.carica()
        fuori, dentro = [], []
        for ident, versione in voci:
            r = note.get(ident)
            motivo = "non_c_e" if r is None else _fuori_dalla_conferma(a, r, versione, strada, P)
            if motivo:
                fuori.append(_uscita_lista(ident, motivo, "lista_fuori_"))
            else:
                dentro.append(ident)
        gruppo = _id_gruppo(a, note, strada, P) if dentro else ""
        via = P.VIA_LISTA + gruppo
        confermate = []
        for ident in dentro:
            copia = json.loads(json.dumps(note[ident], ensure_ascii=False))
            try:
                a.conferma_scope(note[ident], via=via)
            except SystemExit:

                note[ident] = copia
                fuori.append(_uscita_lista(ident, "non_andata", "lista_fuori_"))
                continue
            confermate.append(ident)
        if confermate:
            _salva_e_segna(a, note, confermate)
    n, k = len(confermate), len(fuori)
    if not n:
        return {
            "ok": False,
            "avviso": True,
            "messaggio": FRASI["lista_niente"],
            "gruppo": "",
            "strada": strada,
            "n": 0,
            "confermate": [],
            "fuori": fuori,
        }
    pezzi = [FRASI["lista_confermati_uno"] if n == 1 else FRASI["lista_confermati"].format(n=n)]
    if k:
        pezzi.append(
            FRASI["lista_con_fuori_uno"] if k == 1 else FRASI["lista_con_fuori"].format(k=k)
        )
    return {
        "messaggio": ". ".join(pezzi),
        "gruppo": gruppo,
        "strada": strada,
        "n": n,
        "confermate": confermate,
        "fuori": fuori,
        "annulla": {
            "verbo": "riapri_lista",
            "riga": f"riapri-lista {gruppo}",
            "parola": P.TESTI["lista_annulla"],
            "aiuto": P.TESTI["lista_annulla_aiuto"],
        },
    }


def _resta_confermata(a, r, via, P):
    ""


    if _agente_aperto(a, r):
        return "agente"
    if _lavoro_aperto(r):
        return "lavoro"
    if not hasattr(a, "voce_export"):
        return "non_andata"
    vx, _v = _voce_bacheca(a, r, P)
    return P.fuori_dall_annullo(vx, via)


def riapri_lista(gruppo):
    ""




    a = arch()
    f = getattr(a, "riapri", None)
    if not f:
        raise Errore(FRASI["archivio_vecchio"])
    P = _parole()
    gruppo = str(gruppo or "").strip()
    if not gruppo:
        raise Errore(FRASI["lista_annulla_niente"])
    via = P.VIA_LISTA + gruppo
    with _lucchetto_atteso(LUCCHETTO_SMISTA) as mio:
        if not mio:
            raise Errore(FRASI["smista_in_corso"])
        note = a.carica()
        dentro, fuori = [], []
        for ident, r in note.items():
            sc = _scope_di(a, r)
            if _confermato(sc) and str(sc.get("confermato_via") or "") == via:
                dentro.append(ident)
            elif any(
                isinstance(c, dict) and str(c.get("confermato_via") or "") == via
                for c in sc.get("conferme_di_prima") or []
            ):
                fuori.append(
                    _uscita_lista(
                        ident, "a_mano" if _confermato(sc) else "riaperto", "lista_resta_"
                    )
                )
        if not dentro:
            raise Avviso(FRASI["lista_annulla_niente"])
        riaperte = []
        for ident in dentro:
            motivo = _resta_confermata(a, note[ident], via, P)
            if motivo:
                fuori.append(_uscita_lista(ident, motivo, "lista_resta_"))
                continue
            copia = json.loads(json.dumps(note[ident], ensure_ascii=False))
            try:
                f(note[ident], via=f"annulla {via}")
            except SystemExit:
                note[ident] = copia
                fuori.append(_uscita_lista(ident, "non_andata", "lista_resta_"))
                continue
            riaperte.append(ident)
        if riaperte:
            _salva_e_segna(a, note, riaperte)
    n = len(riaperte)
    restano = [x for x in fuori if x["motivo"] not in ("riaperto",)]
    if not n:
        return {
            "ok": False,
            "avviso": True,
            "messaggio": FRASI["lista_annulla_niente"],
            "gruppo": gruppo,
            "n": 0,
            "riaperte": [],
            "fuori": fuori,
        }
    pezzi = [FRASI["lista_riaperti_uno"] if n == 1 else FRASI["lista_riaperti"].format(n=n)]
    if restano:
        k = len(restano)
        pezzi.append(
            FRASI["lista_annulla_fuori_uno"] if k == 1 else FRASI["lista_annulla_fuori"].format(k=k)
        )
    return {
        "messaggio": ". ".join(pezzi),
        "gruppo": gruppo,
        "n": n,
        "riaperte": riaperte,
        "fuori": fuori,
    }


def _porta_davanti():
    ""
    subprocess.run(["open", "-a", "the terminal"], capture_output=True, timeout=30)


def vai(ident, lavoro=False):
    ""


    a = arch()
    note = a.carica()
    r = a._prendi(note, ident)
    ag = r["attivita"]["agente"]
    s = r["lavorazione"]["sessione"]
    handle = ag.get("terminale") if lavoro else s.get("terminale")
    stato = terminale_stato(handle)
    if stato == "vivo":
        _terminale("terminal", "switch", "--terminal", handle)
        _porta_davanti()
        return {"mostrata": True}


    if stato == "assente":
        raise Errore(FRASI["terminale_non_lo_trova"])
    if stato != "finito" and handle:
        raise Errore(FRASI["terminale_non_risponde"])
    if lavoro:
        if ag.get("ritorno"):

            raise Errore(FRASI["lavoro_finito"])
        if str(ag.get("stato") or "") != "chiuso":
            ag["stato"] = "chiuso"
            a._segna(r, "the work session is no longer open in the terminal", "lavoro", "SBK")
            a.salva(note)
        raise Errore(FRASI["lavoro_chiuso"])


    if a.sessione_aperta(r):
        a.apri_sessione(r, "", chiusa=True)
        a.salva(note)
    fase = a.fase_di(r)
    if fase in ("perche", "lavorazione"):
        quando = _parole()._quando(s.get("chiusa_quando"))
        raise Errore(_frase(FRASI["sessione_chiusa_riapri"], quando=quando))
    raise Errore(FRASI["sessione_chiusa_resta"])


def _frase(modello, **valori):
    ""
    for k, val in valori.items():
        if val in ("", None):
            modello = re.sub(r" ?\{" + k + r"\}", "", modello)
    return modello.format(**{k: ("" if x is None else x) for k, x in valori.items()}).strip()


def ritorno_letto(ident):
    a = arch()
    note = a.carica()
    r = a._prendi(note, ident)
    r["attivita"]["agente"]["ritorno_letto"] = True
    a._segna(r, "return read by the user", "ritorno", "owner")
    a.salva(note)
    return {}





def _voci_export():
    try:
        d = json.loads((CASA_ARCHIVIO / "pagina" / "inspiration.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [v for v in (d.get("voci") or []) if isinstance(v, dict)]


def da_importare(voci=None):
    ""

    if voci is None:
        voci = _voci_export()
    out = []
    for v in voci:
        L = v.get("lavorazione") or {}
        ag = (v.get("attivita") or {}).get("agente") or {}
        if not ((L.get("sessione") or {}).get("aperta") or ag.get("avviato_quando")):
            continue
        imp = L.get("impronte") or {}
        cl = Path(L.get("cartella") or "")
        prove = [("PERCHE.json", cl / "PERCHE.json"), ("DOMANDE.json", cl / "DOMANDE.json"), ("PIANO.json", cl / "PIANO.json"),
                 ("SCHEDA.md", cl / "SCHEDA.md")]


        prove += [
            ("STATO.json", cl / "STATO.json"),
            ("SCOPE.json", cl / "SCOPE.json"),
            ("PERCHE.json:terminale", cl / "PERCHE.json"),
        ]
        if ag.get("cartella"):
            prove += [
                ("DOMANDE-lavoro.json", Path(ag["cartella"]) / "DOMANDE.json"),
                ("RITORNO.md", Path(ag["cartella"]) / "RITORNO.md"),
                ("STATO-lavoro.json", Path(ag["cartella"]) / "STATO.json"),

                ("SCOPE-lavoro.json", Path(ag["cartella"]) / "SCOPE.json"),
            ]
        for chiave, p in prove:
            try:
                st = p.stat()
            except OSError:
                continue
            if imp.get(chiave) != f"{st.st_mtime_ns}-{st.st_size}":
                out.append(v["id"])
                break
    return out


AUDIO = re.compile(r"\.(m4a|mp3|aac|wav|ogg|opus|webm|caf|aiff?)$", re.I)


def voci_con_orfani(voci):
    ""


    lav = CASA_ARCHIVIO / "lavorazione"
    try:
        cartelle = [
            c
            for c in os.scandir(lav)
            if c.is_dir() and os.path.isdir(os.path.join(c.path, "audio"))
        ]
    except OSError:
        return []
    if not cartelle:
        return []
    per_cartella = {}
    for v in voci:
        c = str((v.get("lavorazione") or {}).get("cartella") or "")
        if c:
            per_cartella[os.path.basename(c.rstrip("/"))] = v
    quiete = getattr(_ARCH, "ORFANO_QUIETE_S", ORFANO_QUIETE_S) if _ARCH else ORFANO_QUIETE_S
    adesso = time.time()
    out = []
    for c in cartelle:
        v = per_cartella.get(c.name)
        if not v:
            continue
        citati = set()
        for p in v.get("pareri") or []:
            if isinstance(p, dict) and p.get("audio"):
                citati.add(os.path.basename(str(p["audio"])))
        pc = (v.get("lavorazione") or {}).get("perche") or {}
        if pc.get("correzione_audio"):
            citati.add(os.path.basename(str(pc["correzione_audio"])))
        try:
            file = [f for f in os.scandir(os.path.join(c.path, "audio")) if f.is_file()]
        except OSError:
            continue
        for f in file:
            if f.name.startswith(".") or not AUDIO.search(f.name) or f.name in citati:
                continue
            try:
                st = f.stat()
            except OSError:
                continue
            if st.st_size and adesso - st.st_mtime >= quiete:
                out.append(v["id"])
                break
    return out


def sessioni_da_controllare(voci):
    ""
    out = []
    for v in voci:
        L = v.get("lavorazione") or {}
        s = L.get("sessione") or {}
        ag = (v.get("attivita") or {}).get("agente") or {}
        if s.get("aperta") and s.get("terminale"):
            out.append((v["id"], "sessione", s["terminale"]))
        if (
            ag.get("avviato_quando")
            and ag.get("terminale")
            and not ag.get("ritorno")
            and str(ag.get("stato") or "") != "chiuso"
        ):
            out.append((v["id"], "lavoro", ag["terminale"]))
    return out


def _chiusa_alla_lettura(v, evento):
    ""


    righe = [x for x in v.get("storia") or [] if isinstance(x, dict) and x.get("evento") == evento]
    return bool(righe) and "seen when reading the board" in str(righe[-1].get("cosa") or "")


def sessioni_da_riaprire(voci):
    ""






    try:
        conti = json.loads(TERMINALI_NON_VISTI.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        conti = {}
    morti = set((conti or {}).get("_morti") or []) if isinstance(conti, dict) else set()
    out = []
    for v in voci:
        L = v.get("lavorazione") or {}
        s = L.get("sessione") or {}
        ag = (v.get("attivita") or {}).get("agente") or {}
        h = s.get("terminale") or ""
        if (
            h
            and h not in morti
            and s.get("chiusa_quando")
            and not s.get("finita_quando")
            and not ag.get("avviato_quando")
            and _chiusa_alla_lettura(v, "sessione")
        ):
            out.append((v["id"], "sessione", h))
        h = ag.get("terminale") or ""
        if (
            h
            and h not in morti
            and ag.get("avviato_quando")
            and not ag.get("ritorno")
            and str(ag.get("stato") or "") == "chiuso"
            and _chiusa_alla_lettura(v, "lavoro")
        ):
            out.append((v["id"], "lavoro", h))
    return out


def _riapri_sessione_spunto(a, r):
    ""
    s = r["lavorazione"]["sessione"]
    era = str(s.get("chiusa_quando") or "")
    s["chiusa_quando"] = ""
    a._segna(
        r,
        f"the idea's agent is open again in the terminal, it was marked closed since {era[11:16]}",
        "sessione",
        "SBK",
    )


def sessioni_morte(voci, forza=False):
    ""

    da = sessioni_da_controllare(voci)
    da_riaprire = sessioni_da_riaprire(voci)
    if not (da or da_riaprire):
        return []
    stampo = CASA_ARCHIVIO / ".sessioni-controllate"
    if not forza:
        try:
            if time.time() - stampo.stat().st_mtime < CONTROLLO_SESSIONI_S:
                return []
        except OSError:
            pass
    try:
        stampo.touch()
    except OSError:
        pass
    morte = []
    for ident, chi, handle in da:
        if _terminale_morto(handle):
            morte.append((ident, chi))

    for ident, chi, handle in da_riaprire:
        stato = terminale_stato(handle)
        if stato == "vivo":
            morte.append((ident, f"{chi}_viva"))
        else:
            _terminale_morto(
                handle, stato=stato, segna_morto=True
            )
    return morte


def _lucchetto_libero(percorso):
    ""
    if not percorso.exists():
        return True
    try:
        with open(percorso, "a+") as fh:
            try:
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return False
            fcntl.flock(fh, fcntl.LOCK_UN)
    except OSError:
        return False
    return True


def coda_da_rilanciare(voci, adesso=None):
    ""


    adesso = adesso if adesso is not None else time.time()
    out = []
    for v in voci:
        ferma = False
        for p in v.get("pareri") or []:
            if not isinstance(p, dict) or not p.get("audio"):
                continue
            if str(p.get("audio_stato") or "da trascrivere") != "da trascrivere":
                continue
            if not os.path.isfile(str(p["audio"])):
                continue
            riferimento = p.get("ultimo_tentativo") or p.get("quando")
            try:
                t = datetime.datetime.fromisoformat(str(riferimento)[:19]).timestamp()
            except (TypeError, ValueError):
                continue
            if adesso - t > INTERVALLO_TENTATIVI_S:
                ferma = True
                break
        if not ferma:
            continue
        cl = Path(str((v.get("lavorazione") or {}).get("cartella") or ""))
        if not cl.name:
            continue
        stampo = cl / ".rilancio"
        try:
            if adesso - stampo.stat().st_mtime < INTERVALLO_TENTATIVI_S:
                continue
        except OSError:
            pass
        if not _lucchetto_libero(cl / ".dopo-risposta.lock"):
            continue
        out.append(v["id"])
    return out


def rilancia_coda(voci):
    ""
    fatti = []
    for ident in coda_da_rilanciare(voci):


        if _cartella_sparita_col_pannello(ident):
            continue
        cl = arch().cartella_lavorazione(ident, crea=True)
        (cl / ".rilancio").touch()
        _in_sottofondo(ident)
        fatti.append(ident)
    return fatti


def sessioni_senza_avviso(voci):
    ""


    out = []
    for v in voci:
        L = v.get("lavorazione") or {}
        s = L.get("sessione") or {}
        imp = L.get("impronte") or {}
        if (
            s.get("aperta")
            and s.get("terminale")
            and imp.get("risposte")
            and "avvisato:sessione" not in imp
        ):
            out.append(str(v.get("id") or ""))
    return out


def _avviso_gia_dato(a, r):
    ""



    s = r["lavorazione"]["sessione"]
    imp = r["lavorazione"].get("impronte") or {}
    f = a.cartella_lavorazione(r["id"]) / "RISPOSTE.json"
    try:
        dati = json.loads(f.read_text(encoding="utf-8"))
        scritto = datetime.datetime.fromtimestamp(f.stat().st_mtime).isoformat(timespec="seconds")
    except (OSError, ValueError):
        return False
    if not isinstance(dati, dict) or not s.get("aperta_quando"):
        return False
    impronta = _impronta_dei_dati_del_file(dati)
    return impronta == imp.get("risposte") and scritto <= str(s["aperta_quando"])[:19]


def _impronta_dei_dati_del_file(dati):
    ""


    dati = {k: v for k, v in dati.items() if k not in RISPOSTE_FUORI_IMPRONTA}
    return hashlib.sha256(
        json.dumps(dati, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()[:16]


def importa(voci=None):
    ""


    if voci is None:
        voci = _voci_export()
    ids = da_importare(voci)
    orfani = voci_con_orfani(voci)
    morte = sessioni_morte(voci)
    senza_avviso = sessioni_senza_avviso(voci)
    esito = {
        "importate": [],
        "cosa": {},
        "adottati": {},
        "sessioni_chiuse": [],
        "rilanciate": [],
        "scritto": False,
    }
    if ids or orfani or morte or senza_avviso:
        a = arch()
        note = a.carica()


        segna = getattr(a, "segna_avvisato", None)
        for i in senza_avviso if segna else []:
            r = note.get(i)
            if r and _agente_aperto(a, r) and _avviso_gia_dato(a, r):
                segna(r, "sessione")
                esito.setdefault("avvisi_segnati", []).append(i)
        for i in ids:
            if i in note:
                f = a.importa_lavorazione(note[i])
                if f:
                    esito["cosa"][i] = f
        esito["importate"] = list(esito["cosa"])
        adotta = getattr(a, "adotta_audio", None)
        if adotta:
            for i in orfani:
                if i in note:
                    try:
                        f = adotta(note[i])
                    except SystemExit as e:
                        f = [f"audio not adopted ({e.code})"]
                    if f:
                        esito["adottati"][i] = f
        else:
            esito["orfani_non_adottati"] = orfani
        for i, chi in morte:
            r = note.get(i)
            if not r:
                continue
            if chi == "sessione_viva":
                if not a.sessione_aperta(r):
                    _riapri_sessione_spunto(a, r)
                    esito.setdefault("sessioni_riaperte", []).append(f"{i} session")
                continue
            if chi == "lavoro_viva":
                ag = r["attivita"]["agente"]
                if str(ag.get("stato") or "") == "chiuso" and not ag.get("ritorno"):
                    ag["stato"] = "avviato"
                    a._segna(
                        r,
                        "the job is open again in the terminal",
                        "lavoro",
                        "SBK",
                    )
                    esito.setdefault("sessioni_riaperte", []).append(f"{i} work")
                continue
            if chi == "sessione":
                if _chiudi_sessione_spunto(
                    a,
                    r,
                    "the idea's session is no longer open in the terminal, seen when reading the board",
                ):
                    esito["sessioni_chiuse"].append(f"{i} session")
            else:
                ag = r["attivita"]["agente"]
                if str(ag.get("stato") or "") != "chiuso" and not ag.get("ritorno"):
                    ag["stato"] = "chiuso"
                    a._segna(
                        r,
                        "the work session is no longer open in the terminal, seen when reading the board",
                        "lavoro",
                        "SBK",
                    )
                    esito["sessioni_chiuse"].append(f"{i} work")
        if (
            esito["cosa"]
            or esito["adottati"]
            or esito["sessioni_chiuse"]
            or esito.get("sessioni_riaperte")
            or esito.get("avvisi_segnati")
        ):
            a.salva(note)
            esito["scritto"] = True



            for i in esito["adottati"]:
                _in_sottofondo(i)
    esito["rilanciate"] = rilancia_coda(voci if not esito["scritto"] else _voci_export())
    esito["comprensioni"] = _comprensioni_importa()
    esito["riletture"] = _riletture_importa()
    esito["capiti_da_soli"] = _capisci_da_solo()

    if esito["comprensioni"] or esito["riletture"] or esito["capiti_da_soli"]:
        esito["scritto"] = True
    return esito


def _scende_da_solo(r):
    ""

    p = cosa_scaricare({str(r.get("id") or ""): r})
    return bool(p["reel"] or p["pagine"] or p["x"])


def _tieni_si(ids):
    ""

    with _lucchetto(LUCCHETTO_CFG):
        cfg = _leggi_cfg(CAPISCI_DA_SOLO)
        if not cfg.get("acceso"):
            return False
        si = list(cfg.get("si_di_owner") or [])
        si += [i for i in ids if i not in si]
        cfg["si_di_owner"] = si
        cfg["aspettano_te"] = [i for i in cfg.get("aspettano_te") or [] if i not in si]
        _scrivi_json(CAPISCI_DA_SOLO, cfg)
    return True


def _aspettano_te(note, ids):
    ""


    try:
        cfg = json.loads(CAPISCI_DA_SOLO.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(cfg, dict) or not cfg.get("acceso"):
        return None
    gia = set(cfg.get("aspettano_te") or []) | set(cfg.get("fermi") or [])


    return {
        i
        for i in ids
        if not _senza_accesso(note[i])
        and (
            i in gia
            or (
                not (note[i].get("contenuto_visto") or {}).get("si")
                and not _scende_da_solo(note[i])
            )
        )
    }




_PERCHE_NIENTE = {}


def _al_registro_del_giro(riga):
    ""
    with contextlib.suppress(OSError), open(REGISTRO_GIRO, "a", encoding="utf-8") as fh:
        fh.write(f"{_adesso()} {riga}\n")


def _comprensione_aperta(r):
    ""
    c = (r.get("lavorazione") or {}).get("comprensione") or {}
    return bool(c.get("aperta_quando")) and not c.get("chiusa_quando")


def _fondi_cfg(inizio, mio):
    ""






    with _lucchetto(LUCCHETTO_CFG):
        disco = _leggi_cfg(CAPISCI_DA_SOLO)
        out = dict(mio)
        for k in set(disco) | set(inizio) | set(mio):
            if k in CHIAVI_DI_FUORI or (
                disco.get(k) != inizio.get(k) and mio.get(k) == inizio.get(k)
            ):
                if k in disco:
                    out[k] = disco[k]
                else:
                    out.pop(k, None)
        nuovi = [
            i
            for i in disco.get("si_di_owner") or []
            if i not in (inizio.get("si_di_owner") or []) and i not in (out.get("si_di_owner") or [])
        ]
        if nuovi:
            out["si_di_owner"] = list(out.get("si_di_owner") or []) + nuovi
            out["aspettano_te"] = [i for i in out.get("aspettano_te") or [] if i not in nuovi]
        out.setdefault("riparti_fermi_a_vuoto", False)
        _scrivi_json(CAPISCI_DA_SOLO, out)
    return out


def _spegni_ripartenza(**perche):
    ""


    with _lucchetto(LUCCHETTO_CFG):
        disco = _leggi_cfg(CAPISCI_DA_SOLO)
        if (
            disco.get("riparti_fermi_a_vuoto") is True
            or disco.get("riparti_fermi_a_vuoto") == "uno"
        ):
            disco["riparti_fermi_a_vuoto"] = False
        disco.update(perche)
        _scrivi_json(CAPISCI_DA_SOLO, disco)


def _fermo_vero(r, com):
    ""

    if not com.get("chiusa_quando"):
        return False
    esito = com.get("esito") or {}
    if esito.get("stato") == "fatto":
        return False
    if com.get("ripresa_a_vuoto") and esito.get("stato") == "fermo" and not esito.get("a_vuoto"):
        return True
    if int(com.get("tentativi_a_vuoto") or 0) >= TETTO_A_VUOTO:
        return True
    if _fermo_a_vuoto(r, com):
        return False
    return _tentativi_veri(r, com) >= TENTATIVI_COMPRENSIONE


def _capisci_da_solo(da="bacheca"):
    ""



























    _PERCHE_NIENTE[da] = ""
    cfg = _leggi_cfg(CAPISCI_DA_SOLO)
    if not cfg.get("acceso"):
        return []
    inizio = json.loads(json.dumps(cfg))
    dopo = datetime.timedelta(minutes=float(cfg.get("dopo_minuti") or 0))
    riparti = cfg.get("riparti_fermi_a_vuoto") is True or cfg.get("riparti_fermi_a_vuoto") == "uno"
    a = arch()
    note = a.carica()
    adesso = datetime.datetime.now()
    in_corso, candidati, fermi, senza = [], [], [], []
    senza_accesso, fermi_a_vuoto, scendono, piu_tardi, fermate = [], [], [], [], []

    da_capire = _da_capire_visti(note)
    si = [i for i in cfg.get("si_di_owner") or [] if i in da_capire]
    for i in da_capire:
        r = note[i]
        com = (r.get("lavorazione") or {}).get("comprensione") or {}
        if com.get("aperta_quando") and not com.get("chiusa_quando"):
            in_corso.append(i)
            continue
        visto = bool((r.get("contenuto_visto") or {}).get("si"))
        if not visto and _senza_accesso(r):
            senza_accesso.append(i)
            continue
        if not visto and i not in si:


            (scendono if _scende_da_solo(r) else senza).append(i)
            continue
        if com.get("chiusa_quando"):
            esito = com.get("esito") or {}
            if esito.get("stato") == "fatto":
                continue
            if _fermo_vero(r, com):
                fermi.append(i)
                if com.get("ripresa_a_vuoto"):
                    fermate.append(i)
                continue
            if _fermo_a_vuoto(r, com):
                fermi_a_vuoto.append(i)
                if not riparti:
                    fermi.append(i)
                    continue
            try:
                chiusa = datetime.datetime.fromisoformat(str(com["chiusa_quando"]))
            except ValueError:
                chiusa = adesso
            aspetta = RIPROVA_COMPRENSIONE_S
            if esito.get("a_vuoto") and int(com.get("vuoti_di_fila") or 0) < VUOTI_DI_FILA:
                aspetta = ATTESA_A_VUOTO_S
            if (adesso - chiusa).total_seconds() < aspetta:
                piu_tardi.append(i)
                continue
        try:
            quando = datetime.datetime.fromisoformat(
                str((r.get("cattura") or {}).get("quando") or "")
            )
        except ValueError:
            quando = adesso
        if adesso - quando < dopo:
            piu_tardi.append(i)
            continue
        candidati.append(i)


    fermata = cfg.get("ripartenza_fermata") or {}
    for i in fermate:
        esito = (note[i]["lavorazione"]["comprensione"]).get("esito") or {}
        if (fermata.get("voce"), fermata.get("quando")) == (i, esito.get("quando")):
            continue
        dati = {"voce": i, "quando": esito.get("quando"), "motivo": esito.get("motivo") or ""}
        _spegni_ripartenza(ripartenza_fermata={**dati, "spento": _adesso()})
        if riparti:
            riparti = False
            candidati = [x for x in candidati if x not in fermi_a_vuoto]
            fermi += [x for x in fermi_a_vuoto if x not in fermi]
        break


    scesi = [i for i in candidati if (note[i].get("contenuto_visto") or {}).get("si")]
    da_aprire = sorted(
        (i for i in candidati if i not in scesi),
        key=lambda i: si.index(i) if i in si else len(si),
    )
    lancio = scesi or da_aprire[:1]
    in_fila = [i for i in da_aprire if i not in lancio]
    partite = []
    errore_prima = cfg.pop("ultimo_errore", None)
    motivo = ""
    if lancio and not in_corso:
        ripresa = len(lancio) == 1 and lancio[0] in fermi_a_vuoto
        try:
            with _uno_alla_volta():


                fresche = a.carica()
                if any(_comprensione_aperta(fresche[i]) for i in _da_capire_visti(fresche)):
                    lancio, motivo = [], "another pass just launched"
                lancio = [
                    i
                    for i in lancio
                    if i in fresche
                    and fresche[i].get("stato") == "da capire"
                    and not _comprensione_aperta(fresche[i])
                    and (
                        ((fresche[i].get("lavorazione") or {}).get("comprensione") or {}).get(
                            "esito"
                        )
                        or {}
                    ).get("stato")
                    != "fatto"
                ]

                uno_solo = False
                if ripresa and lancio:
                    ora = _leggi_cfg(CAPISCI_DA_SOLO).get("riparti_fermi_a_vuoto")
                    uno_solo = ora == "uno"
                    if not (ora is True or uno_solo):
                        lancio, motivo = (
                            [],
                            "the restart of empty-run stuck items was turned off in the meantime",
                        )
                if lancio:
                    partite = _capisci_voci(
                        a, fresche, lancio, pannello=False, avvio="da_solo", ripresa=ripresa
                    )["voci"]
                    in_corso = list(partite)
                    if ripresa and uno_solo:
                        _spegni_ripartenza(ripartito_uno={"voce": partite[0], "quando": _adesso()})
        except Errore as e:
            cfg["ultimo_errore"] = str(e)
            motivo = f"didn't start ({e})"
            if da != "tick" and str(e) != errore_prima:
                _al_registro_del_giro(f"understand from {da}: didn't start for {', '.join(lancio)} ({e})")
    if not partite and not motivo and da_capire:
        pezzi = []
        if in_corso:
            pezzi.append(f"an understanding is working on {len(in_corso)}")
        if lancio:
            pezzi.append(f"{len(lancio)} ready are waiting for it to finish")
        if in_fila:
            pezzi.append(f"{len(in_fila)} with the yes to open one at a time")
        if scendono:
            pezzi.append(f"{len(scendono)} are waiting for the download")
        if piu_tardi:
            pezzi.append(f"{len(piu_tardi)} will be retried later")
        if senza:
            pezzi.append(f"{len(senza)} are waiting for the user's yes")
        if senza_accesso:
            pezzi.append(f"{len(senza_accesso)} without access")
        if fermi:
            pezzi.append(f"{len(fermi)} stuck")
        if fermi_a_vuoto and not riparti:
            pezzi.append(f"{len(fermi_a_vuoto)} stuck on empty runs with riparti_fermi_a_vuoto off")
        motivo = ", ".join(pezzi) or "nothing ready"
    _PERCHE_NIENTE[da] = motivo
    piano = cosa_scaricare(note)
    try:
        ultimo_scarico = datetime.datetime.fromisoformat(str(cfg.get("ultimo_scarico") or ""))
    except ValueError:
        ultimo_scarico = None
    if any(piano.values()) and (
        ultimo_scarico is None or (adesso - ultimo_scarico).total_seconds() >= CONTROLLO_SCARICHI_S
    ):
        if _scarichi_in_sottofondo(piano):
            cfg["ultimo_scarico"] = _adesso()
            cfg["ultimo_scarico_piano"] = piano
    cfg.update(
        {
            "intervallo_minuti": INTERVALLO_CONTROLLO_MIN,
            "ultimo_controllo": _adesso(),
            "ultimo_da": da,
            "prossimo_controllo": (
                adesso + datetime.timedelta(minutes=INTERVALLO_CONTROLLO_MIN)
            ).isoformat(timespec="seconds"),
            "in_corso": in_corso,
            "fermi": fermi,
            "aspettano_te": fermi + senza,
            "si_di_owner": si,

            "senza_accesso": senza_accesso,
            "fermi_a_vuoto": [i for i in fermi_a_vuoto if i not in partite],
            "in_fila_col_si": in_fila,
            "ultimo_motivo": motivo,

            "pronti_in_fila": [i for i in candidati if i not in partite],
        }
    )
    if da == "tick":
        cfg["ultimo_tick"] = cfg["ultimo_controllo"]
    if partite:
        cfg["ultimo_avvio"] = {"quando": _adesso(), "voci": partite}
    _fondi_cfg(inizio, cfg)
    return partite


def _leggi_dm_dal_giro():
    ""







    try:
        cfg = json.loads(CAPISCI_DA_SOLO.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    if not isinstance(cfg, dict) or not cfg.get("acceso") or cfg.get("leggi_dm") is False:
        return ""
    try:
        esito = rileggi(da="giro")
    except Errore as e:
        return f"not read ({e})"
    except Exception as e:  # noqa: BLE001 - the round doesn't die for reading the DM
        return f"not read ({e!r})"
    cosa = []
    if esito.get("nuove"):
        cosa.append(f"{len(esito['nuove'])} new")
    if esito.get("parole_nuove"):
        cosa.append(f"new words on {len(esito['parole_nuove'])}")
    if esito.get("a_parte"):
        cosa.append(f"{len(esito['a_parte'])} set aside")
    return "read, " + (", ".join(cosa) if cosa else "nothing new")


def giro():
    ""





    with _lucchetto(LUCCHETTO_GIRO, aspetta=False) as mio:
        if not mio:
            print(f"{_adesso()} round: another round is working", flush=True)
            return {"giro": "occupato"}
        dm = _leggi_dm_dal_giro()
        esito = {
            "comprensioni": _comprensioni_importa(),
            "riletture": _riletture_importa(),
            "capiti_da_soli": _capisci_da_solo(da="tick"),
        }

        try:
            pi = "" if esito["capiti_da_soli"] else _passaggio_intero()
        except Exception as e:  # noqa: BLE001 - the understanding round doesn't die for the pass
            pi = f"full pass failed ({e!r})"
        if pi:
            esito["passaggio"] = [pi]
            if "stopped after" in pi:

                with _lucchetto(LUCCHETTO_CFG):
                    disco = _leggi_cfg(CAPISCI_DA_SOLO)
                    prima = str(disco.get("ultimo_motivo") or "")
                    if pi not in prima:
                        disco["ultimo_motivo"] = f"{prima}; {pi}" if prima else pi
                        _scrivi_json(CAPISCI_DA_SOLO, disco)


        perche = _PERCHE_NIENTE.get("tick") or ""
        if perche:
            esito["niente_partito"] = [perche]
        if dm:
            esito = {"dm": [dm], **esito}
        try:
            sm = smistamento_giro()
        except Exception as e:  # noqa: BLE001 - the understanding round doesn't die for sorting
            sm = f"didn't start ({e!r})"
        if sm:
            esito["smistamento"] = [sm]

        try:
            ar = arretrati_giro()
        except Exception as e:  # noqa: BLE001 - the understanding round doesn't die for the backlog
            ar = f"didn't start ({e!r})"
        if ar:
            esito["arretrati"] = [ar]
    pezzi = [
        f"nothing started ({v[0]})"
        if k == "niente_partito"
        else (", ".join(v) if k in ("passaggio", "arretrati") else f"{k} {', '.join(v)}")
        for k, v in esito.items()
        if v
    ]
    print(f"{_adesso()} round: {'; '.join(pezzi) if pezzi else 'nothing to do'}", flush=True)
    return esito


def _leggi_cfg(percorso):
    try:
        d = json.loads(Path(percorso).read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _da_smistare(a, note):
    ""

    out = []
    for i, r in note.items():
        ap = r.get("a_parte") or {}
        if ap.get("si") if isinstance(ap, dict) else ap:
            continue
        if a.fase_di(r) not in ("perche", "lavorazione", "pronta", "tenuta"):
            continue
        if not (r["lavorazione"].get("perche") or {}).get("testo"):
            continue
        sm = r["lavorazione"].get("smistamento") or {}
        if sm.get("proposta") or sm.get("confermato"):
            continue
        out.append(i)
    return out


def _contesto_smistamento(a, note, ids, cl):
    voci = []
    for i in ids:
        r = note[i]
        pc = r["lavorazione"]["perche"]
        dossier = (
            a._assoluto((r.get("link") or {}).get("dossier") or "")
            if hasattr(a, "_assoluto")
            else None
        )
        voci.append(
            {
                "id": i,
                "titolo": r.get("titolo") or "",
                "url": r.get("url") or "",
                "dossier": str(dossier or ""),
                "perche": {
                    k: pc.get(k)
                    for k in (
                        "esito",
                        "testo",
                        "dove_arrivare",
                        "progetto",
                        "correzione",
                        "confermato",
                    )
                },
                "parole_di_owner": _parole_di_owner(r),
                "domande": [
                    {
                        "testo": d.get("testo"),
                        "risposta": (d.get("risposta") or {}).get("testo")
                        if isinstance(d.get("risposta"), dict)
                        else d.get("risposta"),
                    }
                    for d in r["lavorazione"].get("domande") or []
                ],
            }
        )
    return {
        "voci": voci,
        "brief_perche": str(CASA_ARCHIVIO / "PERCHE-BRIEF.md"),
        "cartella": str(cl),
        "uscita": str(cl / "SMISTAMENTO.jsonl"),
        "adesso": _adesso(),
    }


def smistamento_giro(cosa="adesso"):
    ""



    cfg = _leggi_cfg(SMISTAMENTO_GIRO)
    if cosa in ("accendi", "spegni"):
        cfg["acceso"] = cosa == "accendi"
        cfg["interruttore"] = {"quando": _adesso(), "cosa": cosa}
        _scrivi_json(SMISTAMENTO_GIRO, cfg)
        return f"sorting {'on' if cfg['acceso'] else 'off'}"
    if cosa == "stato" or not cfg.get("acceso"):
        return "" if cosa != "stato" else json.dumps(cfg, ensure_ascii=False)
    corso = cfg.get("in_corso") or {}
    if corso.get("pid") and _processo_vivo(corso["pid"]):
        return ""
    a = arch()
    note = a.carica()
    ids = _da_smistare(a, note)[:BLOCCO_SMISTAMENTO]
    if not ids:
        if corso or not cfg.get("finito"):
            cfg.update(in_corso={}, finito=_adesso())
            _scrivi_json(SMISTAMENTO_GIRO, cfg)
        return ""
    cl = (
        CASA_ARCHIVIO / "lavorazione" / f"smistamento-{_adesso().replace(':', '').replace('-', '')}"
    )
    cl.mkdir(parents=True, exist_ok=True)
    (cl / "SESSIONE-SMISTAMENTO.md").write_text(
        (MODELLI / "SESSIONE-SMISTAMENTO.md").read_text(encoding="utf-8"), encoding="utf-8"
    )
    _scrivi_json(cl / "CONTESTO.json", _contesto_smistamento(a, note, ids, cl))
    log = open(cl / "processo.log", "a")  # noqa: SIM115 stays open in the child process
    proc = subprocess.Popen(
        [
            str(VENV if VENV.exists() else sys.executable),
            "-I",
            str(Path(__file__)),
            "smistamento-sottofondo",
            "--cartella",
            str(cl),
            "--voci",
            json.dumps(ids),
        ],
        stdout=log,
        stderr=log,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
        cwd=str(ROOT),
    )
    cfg.pop("finito", None)
    cfg["in_corso"] = {"pid": proc.pid, "cartella": str(cl), "voci": ids, "quando": _adesso()}
    _scrivi_json(SMISTAMENTO_GIRO, cfg)
    return f"sorting started for {len(ids)} ideas ({cl.name})"


def _importa_smistamento(cartella, voci):
    ""

    a = arch()
    f = Path(cartella) / "SMISTAMENTO.jsonl"
    if not f.is_file() or not hasattr(a, "metti_smistamento"):
        return 0, []
    note = a.carica()
    prese, saltate = 0, []
    for riga in f.read_text(encoding="utf-8").splitlines():
        try:
            o = json.loads(riga)
        except ValueError:
            continue
        i = o.get("id")
        if not i or i not in voci or i not in note:
            continue
        ok, motivo = a.metti_smistamento(
            note[i], o.get("smistamento") or {}, "giro dello smistamento"
        )
        if ok:
            prese += 1
        else:
            saltate.append(f"{i} {motivo}")
    a.salva(note)
    return prese, saltate


def smistamento_sottofondo(cartella, voci):
    ""

    cartella = Path(cartella)
    uscita = _sessione_sottofondo(
        cartella,
        f"Sort · {len(voci)} ideas",
        "SESSIONE-SMISTAMENTO.md",
        ATTREZZI_SMISTAMENTO,
        "",
        "smistamento",
        voci,
    )
    prese, saltate = _importa_smistamento(cartella, voci)
    print(
        f"{_adesso()} sorting: exit {uscita}, proposals taken {prese}"
        + (f", not taken {len(saltate)} ({'; '.join(saltate[:5])})" if saltate else ""),
        flush=True,
    )
    cfg = _leggi_cfg(SMISTAMENTO_GIRO)
    cfg.setdefault("blocchi", []).append(
        {
            "cartella": str(cartella),
            "voci": len(voci),
            "prese": prese,
            "uscita": uscita,
            "fine": _adesso(),
        }
    )
    cfg["in_corso"] = {}
    _scrivi_json(SMISTAMENTO_GIRO, cfg)

    if uscita == 0 and prese:
        riga = smistamento_giro()
        if riga:
            print(f"{_adesso()} {riga}", flush=True)
    return uscita












def _impostazioni_arretrati(cfg):
    ""


    imp = cfg.get("impostazioni") if isinstance(cfg.get("impostazioni"), dict) else {}
    out = {}
    for k in IMPOSTAZIONI_ARRETRATI:
        v = imp.get(k)
        if isinstance(v, bool) or not isinstance(v, int | float) or v <= 0:
            return None
        out[k] = v
    if int(out["voci_per_gruppo"]) != out["voci_per_gruppo"]:
        return None
    out["voci_per_gruppo"] = int(out["voci_per_gruppo"])
    return out


def _rilettura_aperta_voce(r):
    ri = (r.get("lavorazione") or {}).get("rilettura") or {}
    return bool(ri.get("aperta_quando")) and not ri.get("chiusa_quando")


def _agente_sulla_voce(a, r):
    ""
    aperta = getattr(a, "sessione_aperta", None)
    with contextlib.suppress(Exception):
        if aperta and aperta(r):
            return True
    return _comprensione_aperta(r) or _rilettura_aperta_voce(r)


def _arretrati_audio_in_coda(a, note):
    ""
    f = getattr(a, "coda_audio", None)
    try:
        return {str(x.get("voce")) for x in (f(note) if f else []) if isinstance(x, dict)}
    except Exception:  # noqa: BLE001 - a queue that can't be read doesn't stop the round: look at the next idea
        return set()


def _arretrato_fuori(a, r, in_coda=()):
    ""



    ap = r.get("a_parte") or {}
    if ap.get("si") if isinstance(ap, dict) else ap:
        return "set aside"
    if _passo_di(a, r) != "scope":
        return "not at the Scope"
    sc = _scope_di(a, r)
    if _confermato(sc):
        return "scope confirmed"
    if sc.get("da") == "owner" or sc.get("campi_di_owner"):
        return "scope written by the user"
    if _agente_sulla_voce(a, r):
        return "agent or re-read open"
    if sc.get("delicato"):
        return "sensitive"
    if int(sc.get("versione") or 0) >= 1 or sc.get("da") != "derivato":
        return "scope already written by a session"
    pc = (r.get("lavorazione") or {}).get("perche") or {}
    if r.get("id") in in_coda or pc.get("correzione_in_arrivo"):
        return "user's words incoming"
    assoluto = getattr(a, "_assoluto", None)
    dossier = ((r.get("link") or {}).get("dossier")) or ""
    p = assoluto(dossier) if assoluto else (Path(dossier) if dossier else None)
    if not p or not Path(p).is_file():
        return "without a dossier"
    return ""


def _arretrati_in_ordine(a, note, in_coda=()):
    ""

    dentro = []
    for i, r in note.items():
        if _arretrato_fuori(a, r, in_coda):
            continue
        sc = _scope_di(a, r)
        arrivo = str((r.get("cattura") or {}).get("quando") or "")
        dentro.append((str(sc.get("quando") or "9999"), arrivo or "9999", i))
    return [i for _q, _arr, i in sorted(dentro)]


def _impronta_arretrato(a, r):
    ""



    def impronta(x):
        testo = json.dumps(x, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(testo.encode("utf-8")).hexdigest()[:16]

    sc = _scope_di(a, r)
    L = r.get("lavorazione") or {}
    return {
        "versione": int(sc.get("versione") or 0),
        "quando": str(sc.get("quando") or ""),
        "confermato": _confermato(sc),
        "campi_di_owner": sorted(sc.get("campi_di_owner") or []),
        "domande": impronta([L.get("domande") or [], r.get("domande_owner") or []]),
        "pareri": impronta(r.get("pareri") or []),
    }


def _epoca(iso):
    ""

    try:
        d = datetime.datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return d.timestamp()


def _quota_letta():
    ""


    migliore = None
    for f in QUOTA_EFFETTIVO:
        d = _json_di(f)
        if not isinstance(d, dict) or not isinstance(d.get("accounts"), dict):
            continue
        epoca = _epoca(d.get("generatedAt"))
        if epoca is None:
            continue
        if migliore is None or epoca > migliore["epoca"]:
            migliore = {
                "generatedAt": str(d.get("generatedAt")),
                "epoca": epoca,
                "file": str(f),
                "accounts": {
                    str(k): {
                        "weeklyPct": (v or {}).get("weeklyPct"),
                        "fableWeeklyPct": (v or {}).get("fableWeeklyPct"),
                    }
                    for k, v in d["accounts"].items()
                    if isinstance(v, dict)
                },
            }
    return migliore


def _numero(x):
    return x if isinstance(x, int | float) and not isinstance(x, bool) else None


def _punti_del_gruppo(g, lettura, fresca_dopo=None):
    ""


    prestati = sorted({str(v.get("account")) for v in g.get("voci") or [] if v.get("account")})
    if not prestati:
        return {}, "letta"
    if lettura is None:
        return {}, "non letta"
    if fresca_dopo is not None and lettura["epoca"] < fresca_dopo:
        return {}, "non letta"
    prima = ((g.get("quota_prima") or {}).get("accounts")) or {}
    punti = {}
    for k in prestati:
        p0 = _numero((prima.get(k) or {}).get("weeklyPct"))
        p1 = _numero((lettura["accounts"].get(k) or {}).get("weeklyPct"))
        if p0 is None or p1 is None:
            return {}, "non letta"
        punti[k] = p1 - p0
    return punti, "letta"


def _lettura_breve(lettura):
    if lettura is None:
        return {"stato": "non letta"}
    return {k: lettura[k] for k in ("generatedAt", "file", "accounts")}


def _arretrati_quota_sopra(cfg, imp):
    ""


    g = cfg.get("gruppo") or {}
    punti, stato = _punti_del_gruppo(g, _quota_letta()) if g else ({}, "letta")
    if stato != "letta":
        punti = {}
    for k, p in sorted(punti.items()):
        if p > imp["punti_per_gruppo"]:
            return FRASI["arretrati_gruppo_sopra"].format(
                account=k, punti=p, tetto=imp["punti_per_gruppo"]
            )
    oggi = (cfg.get("punti_giorno") or {}).get(_adesso()[:10]) or {}
    for k in sorted(set(oggi) | set(punti)):
        tot = (_numero(oggi.get(k)) or 0) + (punti.get(k) or 0)
        if tot > imp["punti_al_giorno"]:
            return FRASI["arretrati_giorno_sopra"].format(
                account=k, punti=tot, tetto=imp["punti_al_giorno"]
            )
    return ""


def _arretrati_conta_giorno(cfg, punti, quando):
    giorno = str(quando or _adesso())[:10]
    tab = cfg.setdefault("punti_giorno", {}).setdefault(giorno, {})
    for k, p in punti.items():
        tab[k] = (_numero(tab.get(k)) or 0) + p


def _arretrati_chiudi_gruppo(cfg, motivo, codice):
    ""


    g = cfg.get("gruppo") or {}
    fine = max([str(v.get("fine") or "") for v in g.get("voci") or []] or [_adesso()])
    g["fine"] = fine
    lettura = _quota_letta()
    punti, stato = _punti_del_gruppo(g, lettura, fresca_dopo=_epoca(fine))
    g["quota_dopo"] = (
        _lettura_breve(lettura)
        if stato == "letta"
        else {
            "stato": "non letta",
            "ultima": (lettura or {}).get("generatedAt") or "",
        }
    )
    if stato == "letta":
        g["punti"] = punti
        _arretrati_conta_giorno(cfg, punti, fine)
    else:
        cfg["quota_in_attesa"] = True
        motivo = f"{motivo}; {FRASI['arretrati_quota_non_letta']}"
    g["chiuso"] = {"quando": _adesso(), "codice": codice}
    cfg.setdefault("gruppi", []).append(g)
    cfg["gruppo"] = {}
    cfg["acceso"] = False
    cfg["fermo"] = {"quando": _adesso(), "codice": codice, "motivo": motivo}
    return motivo


def _arretrati_rileggi_quota(cfg):
    ""

    gruppi = cfg.get("gruppi") or []
    if not cfg.get("quota_in_attesa") or not gruppi:
        return ""
    g = gruppi[-1]
    lettura = _quota_letta()
    punti, stato = _punti_del_gruppo(g, lettura, fresca_dopo=_epoca(g.get("fine")))
    if stato != "letta":
        return ""
    g["quota_dopo"] = _lettura_breve(lettura)
    g["punti"] = punti
    _arretrati_conta_giorno(cfg, punti, g.get("fine"))
    cfg.pop("quota_in_attesa", None)
    if isinstance(cfg.get("fermo"), dict):
        cfg["fermo"]["quota_letta_dopo"] = {"quando": _adesso(), "punti": punti}
    _scrivi_json(ARRETRATI_GIRO, cfg)
    return "backlog, group quota read, " + (
        ", ".join(f"{k} {p}" for k, p in sorted(punti.items())) or "no loan"
    )


def _altro_in_moto(a, note):
    ""


    if any(_comprensione_aperta(r) or _rilettura_aperta_voce(r) for r in note.values()):
        return "an understanding or a re-read is open"
    sm = (_leggi_cfg(SMISTAMENTO_GIRO).get("in_corso") or {}).get("pid")
    if sm and _processo_vivo(sm):
        return "sorting is working"
    if not _lucchetto_libero(LUCCHETTO_COMPRENSIONE) or not _lucchetto_libero(LUCCHETTO_RILETTURA):
        return "another session has the turn"
    cfg = _leggi_cfg(CAPISCI_DA_SOLO)
    if cfg.get("acceso") and (
        cfg.get("in_corso") or cfg.get("pronti_in_fila") or cfg.get("in_fila_col_si")
    ):
        return "there are ideas queued for understanding"
    if _gesto_recente_di_owner(a):
        return "The user is working on the ideas"
    return ""


def _arretrati_prossima(a, note, g, imp):
    ""

    in_coda = _arretrati_audio_in_coda(a, note)
    esiti = g.setdefault("esiti", {})
    if g.get("ids"):
        for i in g["ids"]:
            if i in esiti:
                continue
            r = note.get(i)
            motivo = "not in the archive" if r is None else _arretrato_fuori(a, r, in_coda)
            if motivo:
                esiti[i] = {"esito": "fuori", "motivo": motivo, "quando": _adesso()}
                continue
            return i
        return None
    fatte = sum(1 for e in esiti.values() if e.get("esito") != "fuori")
    if fatte >= imp["voci_per_gruppo"]:
        return None
    return next((i for i in _arretrati_in_ordine(a, note, in_coda) if i not in esiti), None)


def _arretrati_finito(g, imp):
    esiti = g.get("esiti") or {}
    if g.get("ids"):
        return all(i in esiti for i in g["ids"])
    return sum(1 for e in esiti.values() if e.get("esito") != "fuori") >= imp["voci_per_gruppo"]


def _arretrati_prepara(a, r, cl):
    ""

    (cl / "perche").mkdir(parents=True, exist_ok=True)
    (cl / "SESSIONE-ARRETRATI.md").write_text(
        (MODELLI / "SESSIONE-ARRETRATI.md").read_text(encoding="utf-8"), encoding="utf-8"
    )
    _scrivi_json(
        cl / "INGRESSO.json",
        {"voce": r["id"], "preso_quando": _adesso(), **_impronta_arretrato(a, r)},
    )
    prepara = CASA_ARCHIVIO / "perche-prepara.py"
    try:
        p = subprocess.run(
            [
                str(VENV if VENV.exists() else sys.executable),
                "-I",
                str(prepara),
                "--cartella",
                str(cl / "perche"),
                "--voci",
                r["id"],
            ],
            capture_output=True,
            text=True,
            timeout=300,
            cwd=str(CASA_ARCHIVIO),
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, repr(e)[:200]
    (cl / "preparatore.txt").write_text((p.stdout or "") + (p.stderr or ""), encoding="utf-8")
    if p.returncode != 0 or not (cl / "perche" / "input-A1.json").is_file():
        return (
            False,
            f"uscita {p.returncode}, {((p.stderr or p.stdout or '').strip().splitlines() or [''])[-1][:160]}",
        )
    _scrivi_json(
        cl / "CONTESTO.json",
        {
            "voci": [{"id": r["id"], "titolo": r.get("titolo") or ""}],
            "brief_perche": str(CASA_ARCHIVIO / "PERCHE-BRIEF.md"),
            "perche_verifica": str(CASA_ARCHIVIO / "perche-verifica.py"),
            "perche_prepara": str(prepara),
            "archivio": str(CASA_ARCHIVIO),
            "cartella_perche": str(cl / "perche"),
            "adesso": _adesso(),
        },
    )
    return True, ""


def _arretrati_lancia(cl, voce):
    log = open(cl / "processo.log", "a")  # noqa: SIM115 stays open in the child process
    proc = subprocess.Popen(
        [
            str(VENV if VENV.exists() else sys.executable),
            "-I",
            str(Path(__file__)),
            "arretrati-sottofondo",
            "--cartella",
            str(cl),
            "--voce",
            voce,
        ],
        stdout=log,
        stderr=log,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
        cwd=str(ROOT),
    )
    return proc.pid


def _arretrati_accendi(cfg):
    if cfg.get("acceso"):
        return "backlog re-read already on"
    imp = _impostazioni_arretrati(cfg)
    if imp is None:
        motivo = FRASI["arretrati_senza_impostazioni"].format(
            chiavi=", ".join(IMPOSTAZIONI_ARRETRATI)
        )
        cfg.update(
            acceso=False,
            fermo={"quando": _adesso(), "codice": "senza-impostazioni", "motivo": motivo},
        )
        _scrivi_json(ARRETRATI_GIRO, cfg)
        return motivo
    if cfg.get("quota_in_attesa"):
        _arretrati_rileggi_quota(cfg)
        if cfg.get("quota_in_attesa"):
            motivo = FRASI["arretrati_quota_di_prima"]
            cfg["fermo"] = {"quando": _adesso(), "codice": "quota-di-prima", "motivo": motivo}
            _scrivi_json(ARRETRATI_GIRO, cfg)
            return motivo
    ids = [str(i) for i in (cfg.pop("gruppo_ids", None) or []) if str(i).strip()]
    cfg["gruppo"] = {
        "inizio": _adesso(),
        "ids": ids[: imp["voci_per_gruppo"]],
        "ids_scartati": ids[imp["voci_per_gruppo"] :],
        "esiti": {},
        "voci": [],
        "quota_prima": _lettura_breve(_quota_letta()),
    }
    cfg.update(
        acceso=True,
        interruttore={"quando": _adesso(), "cosa": "accendi"},
        storte_di_fila=0,
        fermo={},
        in_corso={},
    )
    _scrivi_json(ARRETRATI_GIRO, cfg)
    return FRASI["arretrati_acceso"].format(n=len(cfg["gruppo"]["ids"]) or imp["voci_per_gruppo"])


def _arretrati_ferma(cfg, motivo, codice):
    ""
    if cfg.get("gruppo"):
        motivo = _arretrati_chiudi_gruppo(cfg, motivo, codice)
    else:
        cfg.update(acceso=False, fermo={"quando": _adesso(), "codice": codice, "motivo": motivo})
    _scrivi_json(ARRETRATI_GIRO, cfg)
    return f"backlog stopped, {motivo}"


def _arretrati_adesso(cfg):
    if not cfg.get("acceso"):
        return _arretrati_rileggi_quota(cfg)
    imp = _impostazioni_arretrati(cfg)
    if imp is None:
        return _arretrati_ferma(
            cfg,
            FRASI["arretrati_senza_impostazioni"].format(chiavi=", ".join(IMPOSTAZIONI_ARRETRATI)),
            "senza-impostazioni",
        )
    corso = cfg.get("in_corso") or {}
    if corso.get("pid") and _processo_vivo(corso["pid"]):
        return ""
    g = cfg.setdefault("gruppo", {})
    if corso:

        g.setdefault("voci", []).append(
            {
                **corso,
                "esito": "storta",
                "motivo": FRASI["arretrati_senza_esito"],
                "fine": _adesso(),
            }
        )
        g.setdefault("esiti", {})[corso.get("voce")] = {
            "esito": "storta",
            "motivo": FRASI["arretrati_senza_esito"],
            "quando": _adesso(),
        }
        cfg["in_corso"] = {}
        cfg["storte_di_fila"] = int(cfg.get("storte_di_fila") or 0) + 1
        if cfg["storte_di_fila"] >= 2:
            return _arretrati_ferma(cfg, FRASI["arretrati_storte"], "storte")
    sopra = _arretrati_quota_sopra(cfg, imp)
    if sopra:
        return _arretrati_ferma(cfg, sopra, "quota")
    seg, ok, _warn = _pressione()
    if seg >= ok:
        cfg["attesa"] = {"quando": _adesso(), "perche": f"memory at {seg * 100:.0f}%"}
        _scrivi_json(ARRETRATI_GIRO, cfg)
        return f"backlog later, memory at {seg * 100:.0f}%, they start below {ok * 100:.0f}%"
    a = arch()
    note = a.carica()
    perche = _altro_in_moto(a, note)
    if perche:
        cfg["attesa"] = {"quando": _adesso(), "perche": perche}
        _scrivi_json(ARRETRATI_GIRO, cfg)
        return f"backlog later, {perche}"
    voce = _arretrati_prossima(a, note, g, imp)
    if voce is None:
        n = sum(1 for e in (g.get("esiti") or {}).values() if e.get("esito") != "fuori")
        return _arretrati_ferma(cfg, FRASI["arretrati_gruppo_finito"].format(n=n), "gruppo-finito")
    base = f"arretrati-{_adesso().replace(':', '').replace('-', '')}-{a.nome_cartella(voce)}"
    cl = CASA_ARCHIVIO / "lavorazione" / base
    n = 1
    while cl.exists():
        n += 1
        cl = CASA_ARCHIVIO / "lavorazione" / f"{base}-{n}"
    pronto, dettaglio = _arretrati_prepara(a, note[voce], cl)
    if not pronto:
        g.setdefault("voci", []).append(
            {
                "voce": voce,
                "cartella": str(cl),
                "esito": "preparatore",
                "motivo": dettaglio,
                "fine": _adesso(),
            }
        )
        return _arretrati_ferma(cfg, FRASI["arretrati_preparatore"], "preparatore")
    pid = _arretrati_lancia(cl, voce)
    cfg.pop("attesa", None)
    cfg["in_corso"] = {"pid": pid, "cartella": str(cl), "voce": voce, "inizio": _adesso()}
    _scrivi_json(ARRETRATI_GIRO, cfg)
    return f"backlog started for {voce} ({cl.name})"


def arretrati_giro(cosa="adesso"):
    ""



    if cosa == "stato":
        return json.dumps(_leggi_cfg(ARRETRATI_GIRO), ensure_ascii=False)
    if cosa in ("accendi", "spegni"):
        with _lucchetto_atteso(LUCCHETTO_ARRETRATI) as mio:
            if not mio:
                return "another backlog round is working, try again shortly"
            cfg = _leggi_cfg(ARRETRATI_GIRO)
            if cosa == "accendi":
                return _arretrati_accendi(cfg)
            cfg.update(acceso=False, interruttore={"quando": _adesso(), "cosa": "spegni"})
            corso = cfg.get("in_corso") or {}

            if (cfg.get("gruppo") or {}).get("inizio") and not (
                corso.get("pid") and _processo_vivo(corso["pid"])
            ):
                _arretrati_chiudi_gruppo(cfg, FRASI["arretrati_spento"], "spento")
            _scrivi_json(ARRETRATI_GIRO, cfg)
            return FRASI["arretrati_spento"]
    with _lucchetto(LUCCHETTO_ARRETRATI, aspetta=False) as mio:
        if not mio:
            return ""
        return _arretrati_adesso(_leggi_cfg(ARRETRATI_GIRO))


def _verifica_arretrato(cartella):
    ""

    try:
        p = subprocess.run(
            [
                str(VENV if VENV.exists() else sys.executable),
                "-I",
                str(CASA_ARCHIVIO / "perche-verifica.py"),
                "--cartella",
                str(Path(cartella) / "perche"),
                "A1",
            ],
            capture_output=True,
            text=True,
            timeout=300,
            cwd=str(CASA_ARCHIVIO),
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        (Path(cartella) / "verifica-processo.txt").write_text(repr(e), encoding="utf-8")
        return False
    (Path(cartella) / "verifica-processo.txt").write_text(
        (p.stdout or "") + (p.stderr or ""), encoding="utf-8"
    )
    return p.returncode == 0


def _riga_arretrato(cartella, voce):
    f = Path(cartella) / "perche" / "A1.jsonl"
    with contextlib.suppress(OSError):
        for riga in f.read_text(encoding="utf-8").splitlines():
            with contextlib.suppress(ValueError):
                o = json.loads(riga)
                if isinstance(o, dict) and o.get("id") == voce:
                    return o
    return None


def _porta_arretrato(cartella, voce):
    ""




    riga = _riga_arretrato(cartella, voce)
    if not riga or not isinstance(riga.get("scope"), dict):
        return "storta", FRASI["arretrati_senza_riga"], {}
    ingresso = _json_di(Path(cartella) / "INGRESSO.json") or {}
    a = arch()
    with _lucchetto_atteso(LUCCHETTO_SMISTA) as mio:
        if not mio:
            return "rimandata", FRASI["arretrati_rimandata"], {}
        with _scrittura_archivio(a):
            note = a.carica()
            r = note.get(voce)
            if r is None:
                return (
                    "cambiata",
                    FRASI["arretrati_cambiato"].format(cosa="no longer in the archive"),
                    {},
                )
            ora = _impronta_arretrato(a, r)
            cambi = [k for k in ora if ingresso.get(k) != ora[k]]
            if _agente_sulla_voce(a, r):
                cambi.append("agent or re-read open")
            if cambi:
                return "cambiata", FRASI["arretrati_cambiato"].format(cosa=", ".join(cambi)), {}
            dati = {
                "scope": {
                    **riga["scope"],
                    "fonti": riga.get("fonti") or [],
                    "non_chieste": riga.get("non_chieste") or [],
                },
                "domande": {
                    "superate": riga.get("superate") or [],
                    "nuove": riga.get("domande") or [],
                },
            }
            applicato = _applica_rilettura(a, r, dati, da=DA_ARRETRATI)
            a.salva(note)
    motivo = str(applicato.get("scope_motivo") or "")
    if applicato.get("scope_riscritto"):
        return "scritta", FRASI["arretrati_scritto"], applicato
    if motivo == "uguale a prima":
        return "uguale", FRASI["arretrati_uguale"], applicato
    return "storta", FRASI["arretrati_non_presa"].format(motivo=motivo or "no reason"), applicato


def _numero_o_niente(x):
    return x if isinstance(x, int | float) and not isinstance(x, bool) else None


def _arretrati_cara(riga, imp):
    ""




    if riga.get("esito") in ("memoria", "prestito") or not riga.get("claude_esito"):
        return ""
    costo = riga.get("costo_usd")
    if costo is None:
        return FRASI["arretrati_costo_non_letto"].format(voce=riga.get("voce"))
    if costo > imp["equivalente_per_sessione"]:
        return FRASI["arretrati_cara"].format(
            voce=riga.get("voce"), costo=f"{costo:.2f}", tetto=imp["equivalente_per_sessione"]
        )
    return ""


def arretrati_sottofondo(cartella, voce):
    ""




    cartella = Path(cartella)
    uscita = _sessione_sottofondo(
        cartella,
        f"Backlog item · {voce}",
        "SESSIONE-ARRETRATI.md",
        ATTREZZI_ARRETRATI,
        f"{VIETATI_COSTRUZIONE} {VIETATO_ARCHIVIO}",
        "arretrati",
        [voce],
        guardia=_guardia_memoria,
    )
    esito = _json_di(cartella / "ESITO.json") or {}
    proc = _json_di(cartella / "processo.json") or {}
    codice = str(esito.get("codice") or "")
    applicato = {}
    if uscita == 75 or codice in ("memoria", "memoria-alta"):
        tipo, motivo = "memoria", str(esito.get("motivo") or FRASI["arretrati_memoria_alta"])
    elif codice.startswith("prestito-") or codice in ("senza-prestiti", "lavoro-sconosciuto"):
        tipo = "prestito"
        motivo = str(esito.get("motivo") or "") + (
            f" ({esito['dettaglio']})" if esito.get("dettaglio") else ""
        )
    elif uscita != 0:
        tipo, motivo = "storta", str(esito.get("motivo") or FRASI["arretrati_senza_esito"])
    elif not _verifica_arretrato(cartella):
        tipo, motivo = "storta", FRASI["arretrati_verifica_rossa"]
    else:
        tipo, motivo, applicato = _porta_arretrato(cartella, voce)
    riga = {
        "voce": voce,
        "cartella": str(cartella),
        "uscita": uscita,
        "account": str(proc.get("account") or ""),
        "prestito": str(proc.get("prestito") or ""),
        "inizio": str(proc.get("inizio") or ""),
        "fine": _adesso(),
        "esito": tipo,
        "motivo": motivo,
    }
    for k in ("domande_chiuse", "domande_trattenute", "domande_nuove", "scope_motivo"):
        if applicato.get(k):
            riga[k] = applicato[k]

    esito_claude = _esito_claude(cartella)
    riga["claude_esito"] = bool(esito_claude)
    riga["costo_usd"] = _numero_o_niente(esito_claude.get("total_cost_usd"))
    print(f"{_adesso()} backlog: {voce} {tipo}, {motivo}", flush=True)
    avanti = False
    with _lucchetto(LUCCHETTO_ARRETRATI):
        cfg = _leggi_cfg(ARRETRATI_GIRO)
        g = cfg.setdefault("gruppo", {})
        g.setdefault("voci", []).append(riga)
        cfg["in_corso"] = {}
        imp = _impostazioni_arretrati(cfg)
        if tipo == "prestito":
            print(
                f"{_adesso()} {_arretrati_ferma(cfg, FRASI['arretrati_prestito'] + ', ' + motivo, 'prestito')}",
                flush=True,
            )
            return uscita
        if tipo not in ("memoria", "rimandata"):
            g.setdefault("esiti", {})[voce] = {
                "esito": tipo,
                "motivo": motivo,
                "cartella": str(cartella),
                "quando": _adesso(),
            }
            cfg["storte_di_fila"] = (
                int(cfg.get("storte_di_fila") or 0) + 1 if tipo == "storta" else 0
            )
        if cfg.get("acceso") and imp is None:
            fermo = _arretrati_ferma(
                cfg,
                FRASI["arretrati_senza_impostazioni"].format(
                    chiavi=", ".join(IMPOSTAZIONI_ARRETRATI)
                ),
                "senza-impostazioni",
            )
        elif cfg.get("acceso") and int(cfg.get("storte_di_fila") or 0) >= 2:
            fermo = _arretrati_ferma(cfg, FRASI["arretrati_storte"], "storte")
        elif cfg.get("acceso") and _arretrati_cara(riga, imp):
            fermo = _arretrati_ferma(cfg, _arretrati_cara(riga, imp), "sessione-cara")
        elif cfg.get("acceso") and _arretrati_quota_sopra(cfg, imp):
            fermo = _arretrati_ferma(cfg, _arretrati_quota_sopra(cfg, imp), "quota")
        elif cfg.get("acceso") and _arretrati_finito(g, imp):
            n = sum(1 for e in (g.get("esiti") or {}).values() if e.get("esito") != "fuori")
            fermo = _arretrati_ferma(
                cfg, FRASI["arretrati_gruppo_finito"].format(n=n), "gruppo-finito"
            )
        elif not cfg.get("acceso") and g.get("inizio"):

            fermo = _arretrati_ferma(cfg, FRASI["arretrati_spento"], "spento")
        else:
            fermo = ""
            _scrivi_json(ARRETRATI_GIRO, cfg)
            avanti = bool(cfg.get("acceso")) and tipo not in ("memoria", "rimandata")
        if fermo:
            print(f"{_adesso()} {fermo}", flush=True)

    if avanti:
        dopo = arretrati_giro()
        if dopo:
            print(f"{_adesso()} {dopo}", flush=True)
    return uscita


def da_solo(cosa):
    ""

    if cosa == "stato":
        return {"acceso": bool(_leggi_cfg(CAPISCI_DA_SOLO).get("acceso"))}
    with _lucchetto(LUCCHETTO_CFG):
        cfg = _leggi_cfg(CAPISCI_DA_SOLO)
        cfg["acceso"] = cosa == "accendi"
        cfg["interruttore"] = {"quando": _adesso(), "cosa": cosa}


        _scrivi_traccia(cfg, "acceso", cfg["acceso"], "secondbrain", cfg["interruttore"]["quando"])
        _scrivi_json(CAPISCI_DA_SOLO, cfg)
    return {"acceso": cfg["acceso"]}


def _scrivi_traccia(cfg, chiave, valore, da, quando):
    ""

    nome = _parole().TRACCIA_IMPOSTAZIONI
    traccia = cfg.get(nome) if isinstance(cfg.get(nome), dict) else {}
    traccia[chiave] = {"da": da, "quando": quando, "valore": valore}
    cfg[nome] = traccia


def impostazioni(chiave="", valore="", da="secondbrain"):
    ""







    b = _parole()
    if not chiave:
        return {
            "impostazioni": b.impostazioni(
                _leggi_cfg(CAPISCI_DA_SOLO), intervallo=INTERVALLO_CONTROLLO_MIN
            )
        }
    voci = {k: (tipo, si) for k, tipo, si in b.IMPOSTAZIONI_VOCI}
    if chiave not in voci:
        raise Errore(FRASI["impostazione_sconosciuta"])
    tipo, si_cambia = voci[chiave]
    if not si_cambia:
        raise Errore(FRASI["impostazione_solo_lettura"])
    testo = str(valore or "").strip()
    if tipo == "numero":
        no = FRASI["impostazione_giorni"].format(
            minimo=b.NUOVO_GIORNI_MINIMO, massimo=b.NUOVO_GIORNI_MASSIMO
        )
        if not re.fullmatch(r"\d{1,3}", testo):
            raise Errore(no)
        nuovo = int(testo)
        if not b.NUOVO_GIORNI_MINIMO <= nuovo <= b.NUOVO_GIORNI_MASSIMO:
            raise Errore(no)
    else:
        if testo not in b.VALORI_INTERRUTTORE:
            raise Errore(FRASI["impostazione_valore"])
        nuovo = b.VALORI_INTERRUTTORE[testo]
    with _lucchetto(
        LUCCHETTO_CFG
    ):
        cfg = _leggi_cfg(CAPISCI_DA_SOLO)
        cfg[chiave] = nuovo
        _scrivi_traccia(cfg, chiave, nuovo, da, _adesso())
        _scrivi_json(CAPISCI_DA_SOLO, cfg)

    return {"impostazioni": b.impostazioni(cfg, intervallo=INTERVALLO_CONTROLLO_MIN)}




FRASI_FILTRI = {
    "filtro_cosa": "Here you save or remove a filter, I didn't change anything",
    "filtro_nome_vuoto": "Give it a name, I didn't save anything",
    "filtro_nome_lungo": "The name is too long, at most {n} letters. I didn't save anything",
    "filtro_forma": "I don't understand this filter, I didn't save anything",

    "filtro_dimensione": "This filter selects on something I don't know, I didn't save anything",
    "filtro_voce": "This filter selects an item I don't know, I didn't save anything",
    "filtro_ordine": "I don't know this ordering, I didn't save anything",
    "filtro_gruppo": "I don't know this grouping, I didn't save anything",
    "filtro_non_c_e": "There's no saved filter with this name, I didn't remove anything",
    "filtri_illeggibili": "I can't read the saved filters, I didn't change anything so I don't lose them",

    "filtro_salvato": "I saved «{nome}»",
    "filtro_sostituito": "I updated «{nome}»",
    "filtro_tolto": "I removed «{nome}»",
}
FRASI.update(FRASI_FILTRI)


def _filtri_salvati_file():
    return CASA_ARCHIVIO / _parole().FILTRI_SALVATI_NOME


def filtri_salvati(cosa="", nome="", filtro="", da="secondbrain"):
    ""






    b = _parole()
    file = _filtri_salvati_file()
    if not cosa:
        righe, si_legge = b.leggi_filtri_salvati(str(file))
        return {
            "filtri_salvati": b.filtri_salvati_a_vista(righe),
            "filtri_salvati_si_legge": si_legge,
        }
    if cosa not in ("salva", "togli"):
        raise Errore(FRASI["filtro_cosa"])
    nome = b.nome_filtro(nome)
    if not nome:
        raise Errore(FRASI["filtro_nome_vuoto"])
    if len(nome) > b.FILTRI_NOME_MAX:
        raise Errore(FRASI["filtro_nome_lungo"].format(n=b.FILTRI_NOME_MAX))
    pulito = None
    if cosa == "salva":
        try:
            grezzo = json.loads(filtro or "")
        except ValueError:
            raise Errore(FRASI["filtro_forma"]) from None
        pulito, no = b.valida_filtro(grezzo)
        if no:
            raise Errore(FRASI[f"filtro_{no}"])
    with _lucchetto(CASA_ARCHIVIO / b.FILTRI_SALVATI_LUCCHETTO):
        righe, si_legge = b.leggi_filtri_salvati(str(file))
        if not si_legge:
            raise Errore(FRASI["filtri_illeggibili"])
        chiave = nome.casefold()
        riga = next((r for r in righe if b.nome_filtro(r.get("nome")).casefold() == chiave), None)
        quando = _adesso()
        if cosa == "togli":
            if riga is None or riga.get("tolto"):
                raise Errore(FRASI["filtro_non_c_e"])
            riga["tolto"] = True
            riga["tolto_quando"] = quando
            riga.setdefault("storia", []).append({"cosa": "togli", "quando": quando, "da": da})

            messaggio = FRASI["filtro_tolto"].format(nome=b.nome_filtro(riga.get("nome")) or nome)
        elif riga is None:
            messaggio = FRASI["filtro_salvato"].format(nome=nome)
            righe.append(
                {
                    "nome": nome,
                    "filtro": pulito,
                    "quando": quando,
                    "da": da,
                    "tolto": False,
                    "storia": [{"cosa": "salva", "quando": quando, "da": da, "filtro": pulito}],
                }
            )
        else:

            messaggio = FRASI[
                "filtro_salvato" if riga.get("tolto") else "filtro_sostituito"
            ].format(nome=nome)
            riga.update(
                nome=nome, filtro=pulito, quando=quando, da=da, tolto=False, tolto_quando=""
            )
            riga.setdefault("storia", []).append(
                {"cosa": "sostituisci", "quando": quando, "da": da, "filtro": pulito}
            )
        _scrivi_json(file, {"formato": b.FILTRI_SALVATI_FORMATO, "versione": 1, "filtri": righe})

    return {
        "filtri_salvati": b.filtri_salvati_a_vista(righe),
        "filtri_salvati_si_legge": True,
        "messaggio": messaggio,
    }


def riparti_fermi(cosa):
    ""



    with _lucchetto(LUCCHETTO_CFG):
        cfg = _leggi_cfg(CAPISCI_DA_SOLO)
        if cosa in ("uno", "no"):
            cfg["riparti_fermi_a_vuoto"] = "uno" if cosa == "uno" else False
            cfg["riparti_scritto"] = {"quando": _adesso(), "cosa": cosa}
            _scrivi_json(CAPISCI_DA_SOLO, cfg)
    return {
        "riparti_fermi_a_vuoto": cfg.get("riparti_fermi_a_vuoto", False),
        "fermi_a_vuoto": cfg.get("fermi_a_vuoto") or [],
        "in_corso": cfg.get("in_corso") or [],
        "ripartito_uno": cfg.get("ripartito_uno") or {},
        "ripartenza_fermata": cfg.get("ripartenza_fermata") or {},
    }


def _ora_del_file(percorso):
    ""
    try:
        return datetime.datetime.fromtimestamp(Path(percorso).stat().st_mtime).isoformat(
            timespec="seconds"
        )
    except (OSError, ValueError, OverflowError):
        return ""


def _conta_chiusura(com, vuoto):
    ""



    if vuoto:
        com.setdefault("esito", {})["a_vuoto"] = True
    if "tentativi_a_vuoto" not in com:
        return
    if vuoto:
        com["tentativi"] = max(0, int(com.get("tentativi") or 0) - 1)
        com["tentativi_a_vuoto"] = int(com.get("tentativi_a_vuoto") or 0) + 1
        com["vuoti_di_fila"] = int(com.get("vuoti_di_fila") or 0) + 1

        if com["tentativi_a_vuoto"] >= TETTO_A_VUOTO:
            e = com.setdefault("esito", {})
            e["motivo_ultimo"] = str(e.get("motivo") or "")
            e["motivo"] = FRASI["comprensione_a_vuoto_troppe"].format(n=com["tentativi_a_vuoto"])
    else:
        com["vuoti_di_fila"] = 0


def _gia_capita(r):
    ""
    stato = str(r.get("stato") or "")
    return bool(stato) and stato not in ("da capire", "buttato dentro")


def _comprensioni_importa():
    ""


    a = arch()
    note = a.carica()
    cambiate = []
    vivi = {}
    dovuto = []
    da_owner = []
    for i, r in note.items():
        com = (r.get("lavorazione") or {}).get("comprensione") or {}
        if not com.get("aperta_quando") or com.get("chiusa_quando"):
            continue
        cart = Path(str(com.get("cartella") or ""))
        esito = None
        if cart.is_dir() and (cart / "ESITO.json").is_file():
            try:
                esito = json.loads((cart / "ESITO.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                esito = None
        stato_voce = ""
        if isinstance(esito, dict) and esito.get("stato") in ("fatto", "fermo"):
            if i in (esito.get("fatte") or []):
                stato_voce = "fatto"
            elif i in (esito.get("voci") or [i]):
                stato_voce = esito["stato"]



            if stato_voce == "fermo" and _gia_capita(r):
                stato_voce = "fatto"
        if stato_voce:


            quando = _ora_del_file(cart / "ESITO.json") or str(esito.get("quando") or _adesso())

            motivi = esito.get("motivi") if isinstance(esito.get("motivi"), dict) else {}
            motivo = (
                str(motivi.get(i) or esito.get("motivo") or "") if stato_voce == "fermo" else ""
            )
            com["esito"] = {
                "stato": stato_voce,
                "motivo": motivo,
                "quando": quando,
            }
            if esito.get("quando") and str(esito["quando"]) != quando:
                com["esito"]["quando_sessione"] = str(esito["quando"])
            if stato_voce == "fermo" and esito.get("dettaglio"):
                com["esito"]["dettaglio"] = str(esito["dettaglio"])
            _conta_chiusura(com, stato_voce == "fermo" and _a_vuoto(cart, esito))
            com["chiusa_quando"] = quando


            if (
                stato_voce == "fatto"
                or esito.get("passaggio_intero_dovuto")
                or esito.get("pagine") == "da_rifare"
            ):
                dovuto.append(i)
                if com.get("avvio") == "fallo_adesso":
                    da_owner.append(i)
            motivo = (
                com["esito"].get("motivo") or motivo
            )
            cosa = f"understanding {stato_voce}" + (f", {motivo}" if motivo else "")
            a._segna(r, cosa, "comprensione", "SBK")
            cambiate.append(i)
            continue
        if com.get("pid"):
            if _processo_vivo(com["pid"]):
                continue



            if _gia_capita(r):
                quando = _adesso()
                com["esito"] = {"stato": "fatto", "motivo": "", "quando": quando}
                _conta_chiusura(com, False)
                com["chiusa_quando"] = quando
                a._segna(r, "understanding fatto", "comprensione", "SBK")
                cambiate.append(i)
                dovuto.append(i)
                continue
            vuoto = _a_vuoto(cart) if cart.is_dir() else True
            motivo = FRASI["comprensione_non_partita" if vuoto else "comprensione_senza_esito"]
            com["esito"] = {"stato": "fermo", "motivo": motivo, "quando": _adesso()}
            with contextlib.suppress(OSError, ValueError, TypeError, AttributeError):
                proc = json.loads((cart / "processo.json").read_text(encoding="utf-8"))
                if proc.get("uscita") is not None:
                    com["esito"]["dettaglio"] = f"uscita {proc['uscita']}"
            _conta_chiusura(com, vuoto)
            com["chiusa_quando"] = com["esito"]["quando"]
            motivo = com["esito"].get("motivo") or motivo
            a._segna(r, f"understanding stopped, {motivo}", "comprensione", "SBK")
            cambiate.append(i)
            continue
        h = com.get("terminale") or ""
        if h not in vivi:
            vivi[h] = not _terminale_morto(h)
        if vivi[h] is False:
            com["chiusa_quando"] = _adesso()
            a._segna(
                r,
                "the understanding session is no longer open in the terminal, seen when reading the board",
                "comprensione",
                "SBK",
            )
            cambiate.append(i)
    if cambiate:
        a.salva(note)
    if dovuto:
        _passaggio_dovuto(dovuto)

        if da_owner and not _ritmo_acceso():
            _passaggio_staccato()
    return cambiate





PASSAGGIO_INTERO_MINUTI = 60

TETTO_PASSAGGIO_S = 1800



QUIETE_PASSAGGIO_S = float(os.environ.get("SB_QUIETE_PASSAGGIO_S") or 600)


PASSAGGI_FALLITI_DI_FILA = 3


PASSAGGIO_STACCATO_VOLTE = 20
PASSAGGIO_STACCATO_PAUSA_S = float(os.environ.get("SB_PASSAGGIO_STACCATO_PAUSA_S") or 60)


def _passaggio_dovuto(voci):
    ""


    with _lucchetto(LUCCHETTO_CFG):
        cfg = _leggi_cfg(CAPISCI_DA_SOLO)
        pi = dict(cfg.get("passaggio_intero") or {})
        if not pi.get("dovuto"):
            pi["dovuto"] = _adesso()
        nuove = [i for i in voci if i not in (pi.get("dovuto_per") or [])]
        if nuove:

            pi["falliti_di_fila"] = 0
        pi["dovuto_per"] = list(dict.fromkeys([*(pi.get("dovuto_per") or []), *voci]))[-20:]
        cfg["passaggio_intero"] = pi
        _scrivi_json(CAPISCI_DA_SOLO, cfg)


def _minuti_passaggio(cfg):
    try:
        m = float(cfg.get("passaggio_intero_minuti"))
    except (TypeError, ValueError):
        return PASSAGGIO_INTERO_MINUTI
    return m if m >= 0 else PASSAGGIO_INTERO_MINUTI


def _passaggio_intero():
    ""






    cfg = _leggi_cfg(CAPISCI_DA_SOLO)
    pi = dict(cfg.get("passaggio_intero") or {})
    if not pi.get("dovuto"):
        return ""
    adesso = datetime.datetime.now()
    try:
        ultimo = datetime.datetime.fromisoformat(str(pi.get("ultimo_inizio") or ""))
    except ValueError:
        ultimo = None
    if ultimo and (adesso - ultimo).total_seconds() < _minuti_passaggio(cfg) * 60:
        return f"full pass later, the last one started at {ultimo:%H:%M}"
    if int(pi.get("falliti_di_fila") or 0) >= PASSAGGI_FALLITI_DI_FILA:
        return (
            f"full pass stopped after {pi['falliti_di_fila']} failed exits in a row "
            f"(the last one {pi.get('ultima_uscita')}), it restarts when an understanding grasps something new"
        )
    if cfg.get("acceso") and (
        cfg.get("in_corso") or cfg.get("pronti_in_fila") or cfg.get("in_fila_col_si")
    ):
        return "full pass after the queued ideas"
    a = arch()
    if _gesto_recente_di_owner(a):
        return "full pass later, the user is working on the ideas"

    def aperte():
        note = a.carica()
        return [
            i
            for i, r in note.items()
            if _comprensione_aperta(r)
            or (
                ((r.get("lavorazione") or {}).get("rilettura") or {}).get("aperta_quando")
                and not ((r.get("lavorazione") or {}).get("rilettura") or {}).get("chiusa_quando")
            )
        ]

    if aperte():
        return "full pass after the open understanding"
    with _lucchetto(LUCCHETTO_COMPRENSIONE, aspetta=False) as mio:
        if not mio or aperte():
            return "full pass after the open understanding"
        inizio = _adesso()
        with _lucchetto(LUCCHETTO_CFG):
            disco = _leggi_cfg(CAPISCI_DA_SOLO)
            d = dict(disco.get("passaggio_intero") or {})
            d.update(ultimo_inizio=inizio, in_corso=os.getpid())
            disco["passaggio_intero"] = d
            _scrivi_json(CAPISCI_DA_SOLO, disco)

        def fai():


            try:
                p = subprocess.Popen(
                    [
                        str(VENV if VENV.exists() else sys.executable),
                        "-I",
                        str(CASA_ARCHIVIO / "archivio.py"),
                        "comprensione",
                        "--pagina",
                    ],
                    cwd=str(CASA_ARCHIVIO),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,
                    text=True,
                    start_new_session=True,
                )
            except OSError as e:
                return "lancio", repr(e)[:160]
            try:
                uscita_testo, _ = p.communicate(timeout=TETTO_PASSAGGIO_S)
            except subprocess.TimeoutExpired:
                with contextlib.suppress(ProcessLookupError, PermissionError):
                    os.killpg(p.pid, 15)
                with contextlib.suppress(subprocess.TimeoutExpired):
                    p.communicate(timeout=30)
                with contextlib.suppress(ProcessLookupError, PermissionError):
                    os.killpg(p.pid, 9)
                return "tempo", ""
            return p.returncode, (uscita_testo or "").strip()[-600:]

        fatto = _con_memoria(fai, nome="inspiration-passaggio", attesa_s=0)
        uscita, coda = fatto if fatto else ("memoria", "")
        with _lucchetto(LUCCHETTO_CFG):
            disco = _leggi_cfg(CAPISCI_DA_SOLO)
            d = dict(disco.get("passaggio_intero") or {})
            d.pop("in_corso", None)
            d.update(ultima_fine=_adesso(), ultima_uscita=uscita)
            if coda:
                d["ultime_righe"] = coda
            if uscita == 0:

                if str(d.get("dovuto") or "") <= inizio:
                    d["dovuto"] = ""
                    d["dovuto_per"] = []
                d["ultimo_fatto"] = d["ultima_fine"]
                d["falliti_di_fila"] = 0
            elif uscita == "memoria":
                d["ultimo_inizio"] = d.get("ultimo_fatto") or ""
            else:
                d["falliti_di_fila"] = int(d.get("falliti_di_fila") or 0) + 1
            disco["passaggio_intero"] = d
            _scrivi_json(CAPISCI_DA_SOLO, disco)
    if uscita == 0:
        return "full pass done"
    if uscita == "memoria":
        return "full pass later, the Mac's memory is high"
    return f"full pass failed, exit {uscita}"


def _gesto_recente_di_owner(a):
    ""


    note = a.carica()
    with contextlib.suppress(Exception):
        if a.coda_audio(note):
            return True
    soglia = (datetime.datetime.now() - datetime.timedelta(seconds=QUIETE_PASSAGGIO_S)).isoformat(
        timespec="seconds"
    )
    for r in note.values():
        for p in r.get("pareri") or []:
            if isinstance(p, dict) and str(p.get("quando") or "") > soglia:
                return True
        for x in reversed(r.get("storia") or []):
            if not isinstance(x, dict):
                continue
            if str(x.get("quando") or "") <= soglia:
                break
            if x.get("da") == "owner":
                return True
    return False


def _passaggio_staccato():
    ""

    if os.environ.get("SB_PASSAGGIO_STACCATO") == "0":
        return False
    log = open(CASA_ARCHIVIO / "passaggio-intero.log", "a")  # noqa: SIM115 stays open in the child process
    subprocess.Popen(
        [
            str(VENV if VENV.exists() else sys.executable),
            "-I",
            str(Path(__file__)),
            "passaggio-intero",
        ],
        stdout=log,
        stderr=log,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
        cwd=str(ROOT),
    )
    return True


def passaggio_intero_staccato():
    ""

    with _lucchetto(CASA_ARCHIVIO / ".passaggio-staccato.lock", aspetta=False) as mio:
        if not mio:
            return "another detached pass is already working"
        riga = ""
        for volta in range(PASSAGGIO_STACCATO_VOLTE):
            if volta:
                time.sleep(PASSAGGIO_STACCATO_PAUSA_S)
            riga = _passaggio_intero()
            print(f"{_adesso()} {riga or 'full pass not due'}", flush=True)
            if not riga or not ("after" in riga or "later" in riga):
                break
        return riga





def _foto_archivio(note):
    ""
    out = {}
    for i, r in note.items():
        ap = r.get("a_parte") or {}
        out[i] = (
            len(r.get("pareri") or []),
            bool(ap.get("si")) if isinstance(ap, dict) else bool(ap),
        )
    return out


def _titolo_voce(r):
    ""
    return (r.get("titolo") or "").strip() or (r.get("url") or r.get("id") or "").strip()


def _conta(n, uno, tanti):
    return uno if n == 1 else tanti.format(n=n)


def cosa_scaricare(note):
    ""





    piano = {"reel": 0, "pagine": 0, "audio": 0, "x": 0}
    for r in note.values():
        ap = r.get("a_parte") or {}
        if ap.get("si") if isinstance(ap, dict) else ap:
            continue
        cv = r.get("contenuto_visto") or {}
        disponibilita = r.get("disponibilita") or {}
        disp = disponibilita.get("stato") or ""
        if disp in ("vietato ai minori", "rimosso", "privato"):
            continue


        controlli = disponibilita.get("controlli") or []
        ultimo = (
            controlli[-1].get("esito") if controlli and isinstance(controlli[-1], dict) else ""
        ) or disp
        if ultimo == "non raggiungibile" and r.get("piattaforma") != "instagram":
            continue
        if r.get("piattaforma") == "instagram" and not cv.get("si"):
            piano["reel"] += 1
        elif r.get("piattaforma") == "web" and "la pagina salvata" in (cv.get("manca") or []):
            piano["pagine"] += 1
        elif (
            r.get("piattaforma") == "x"
            and not cv.get("si")
            and str(r.get("id") or "").startswith("x:")
        ):
            piano["x"] += 1
        piano["audio"] += sum(
            1
            for p in r.get("pareri") or []
            if p.get("audio") and p.get("audio_stato") == "da trascrivere"
        )
    return piano


def _scarichi_in_sottofondo(piano):
    ""

    if not any(piano.values()) or not _lucchetto_libero(LUCCHETTO_SCARICHI):
        return False
    log = open(RILEGGI_LOG, "a")  # noqa: SIM115 resta aperto nel processo figlio
    subprocess.Popen(
        [
            str(VENV if VENV.exists() else sys.executable),
            "-I",
            str(Path(__file__)),
            "scarichi",
            "--piano",
            json.dumps(piano),
        ],
        stdout=log,
        stderr=log,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
        cwd=str(CASA_ARCHIVIO),
    )
    return True


def scarichi(piano):
    ""



    py = str(VENV if VENV.exists() else sys.executable)
    giro = RADICE / GIRO_SCOMPONI
    passi = []

    if piano.get("x"):
        passi.append(("copy X posts", [py, "-I", str(giro / "copia-post-x.py")], giro))
    if piano.get("reel") or piano.get("x"):
        passi.append(
            ("reels round", [py, "-I", str(giro / "giro.py"), "--continua", "--ore", "2"], giro)
        )
    if piano.get("pagine"):
        passi.append(
            ("copy web pages", [py, "-I", str(giro / "copia-pagina-web.py")], giro)
        )
    if piano.get("audio"):
        passi.append(
            (
                "audio transcription",
                [py, "-I", str(TRASCRIVI), "--attendi-memoria", "900"],
                CASA_ARCHIVIO,
            )
        )
    passi.append(
        (
            "archive updated from files",
            [py, "-I", str(CASA_ARCHIVIO / "archivio.py"), "aggiorna"],
            CASA_ARCHIVIO,
        )
    )
    with _lucchetto(LUCCHETTO_SCARICHI, aspetta=False) as mio:
        if not mio:
            print(
                f"{_adesso()} downloads: another background is working, leaving it to them", flush=True
            )
            return 1


        env = {**os.environ, "SB_SOGLIA_AMMISSIONE": os.environ.get("SB_SOGLIA_AMMISSIONE") or "65"}

        stato = {
            "pid": os.getpid(),
            "partito": _adesso(),
            "piano": piano,
            "passi": [nome for nome, _, _ in passi],
        }


        coda_prima = _audio_in_coda() if piano.get("audio") else set()
        for nome, cmd, cwd in passi:
            _scrivi_json(SCARICHI_IN_CORSO, {**stato, "passo": nome, "aggiornato": _adesso()})
            if not Path(cmd[2]).is_file():
                print(f"{_adesso()} {nome}: {cmd[2]} doesn't exist, skipping", flush=True)
                continue
            print(f"{_adesso()} {nome}: starting", flush=True)
            try:
                r = subprocess.run(
                    cmd, cwd=str(cwd), stdin=subprocess.DEVNULL, env=env, timeout=4 * 3600
                )
                print(f"{_adesso()} {nome}: exit {r.returncode}", flush=True)
            except subprocess.TimeoutExpired:
                print(f"{_adesso()} {nome}: stopped after four hours", flush=True)
        if coda_prima:
            trascritte = sorted({v for v, _ in coda_prima - _audio_in_coda()})
            for ident in trascritte:
                try:
                    _avviso_in_sottofondo(ident)
                except OSError as e:
                    print(
                        f"{_adesso()} alert after transcription of {ident} didn't start ({e!r})",
                        flush=True,
                    )
            if trascritte:
                print(
                    f"{_adesso()} alert after transcription for {', '.join(trascritte)}",
                    flush=True,
                )


        _scrivi_json(SCARICHI_IN_CORSO, {**stato, "passo": "understanding", "aggiornato": _adesso()})
        try:
            partite = _capisci_da_solo(da="scarichi")
            if partite:
                print(
                    f"{_adesso()} background understanding started for {', '.join(partite)}",
                    flush=True,
                )
            elif _PERCHE_NIENTE.get("scarichi"):
                print(
                    f"{_adesso()} understanding on its own didn't start: {_PERCHE_NIENTE['scarichi']}",
                    flush=True,
                )
        except Exception as e:  # noqa: BLE001 - the downloads background doesn't die for this
            print(f"{_adesso()} understanding on its own didn't start: {e}", flush=True)
        _scrivi_json(SCARICHI_IN_CORSO, {**stato, "passo": "", "finito": _adesso()})
    return 0


def _frase_lettura(T, lettura, messaggi, cosa):
    ""

    u = (lettura or {}).get("ultima") or {}
    if u.get("tipo") == "furba":
        n = int(u.get("messaggi_letti") or 0)
        if not n:
            return T["rilettura_furba_zero"]
        quanti = _conta(n, T["un_messaggio"], T["n_messaggi"])
        return (T["rilettura_furba_nuove"] if cosa else T["rilettura_furba_niente"]).format(
            quanti=quanti, cosa=", ".join(cosa)
        )
    motivo = str(u.get("motivo") or "")
    if u.get("tipo") == "intera" and motivo:
        perche = (
            T["intera_chiesta"]
            if motivo == "chiesta"
            else T["intera_controllo"]
            if motivo.startswith("controllo")
            else T["intera_prima"]
            if motivo.startswith("prima")
            else motivo
        )
        return (T["rilettura_intera_nuove"] if cosa else T["rilettura_intera_niente"]).format(
            perche=perche, messaggi=messaggi, cosa=", ".join(cosa)
        )
    return (
        T["rilettura_nuove"].format(messaggi=messaggi, cosa=", ".join(cosa))
        if cosa
        else T["rilettura_niente"].format(messaggi=messaggi)
    )


def _segna_scarico(piano, partito):
    ""



    with _lucchetto(LUCCHETTO_CFG):
        cfg = _leggi_cfg(CAPISCI_DA_SOLO)
        if not cfg:
            return
        cfg["ultimo_scarico"] = _adesso() if partito else ""
        if partito:
            cfg["ultimo_scarico_piano"] = piano
        _scrivi_json(CAPISCI_DA_SOLO, cfg)


def rileggi(intera=False, da="clic"):
    ""







    if not LEGGI_DM.is_file():
        raise Errore(FRASI["lettore_assente"])
    a = arch()
    py = str(VENV if VENV.exists() else sys.executable)
    dal_giro = da == "giro"
    with _lucchetto(CASA_ARCHIVIO / ".rileggi.lock", aspetta=False) as mio:
        if not mio:
            raise Errore(FRASI["rilettura_in_corso"])
        prima = _foto_archivio(a.carica())
        via = time.monotonic()
        try:
            p = subprocess.run(
                [py, "-I", str(LEGGI_DM)] + (["--intera"] if intera else []),
                cwd=str(CASA_ARCHIVIO),
                capture_output=True,
                text=True,
                stdin=subprocess.DEVNULL,
                timeout=150,
            )
        except subprocess.TimeoutExpired:
            with open(RILEGGI_LOG, "a") as fh:
                fh.write(f"{_adesso()} rileggi: il lettore non ha finito in 150 s\n")
            raise Errore(FRASI["rilettura_non_riuscita"]) from None
        durata = time.monotonic() - via
        chi = "rileggi dal giro" if dal_giro else "rileggi"
        if p.returncode != 0:
            with open(RILEGGI_LOG, "a") as fh:
                fh.write(
                    f"{_adesso()} {chi}: uscita {p.returncode} in {durata:.1f} s\n{p.stdout}{p.stderr}"
                )
            raise Errore(FRASI["rilettura_non_riuscita"])
        note = a.carica()
    dopo = _foto_archivio(note)
    nuove = [i for i in note if i not in prima and not dopo[i][1]]
    a_parte = [i for i in note if i not in prima and dopo[i][1]]
    parole = [i for i in note if i in prima and dopo[i][0] > prima[i][0]]
    m = re.search(r"messaggi (\d+)", p.stdout)
    messaggi = int(m.group(1)) if m else 0
    if dal_giro and not (nuove or parole or a_parte):

        with open(RILEGGI_LOG, "a") as fh:
            fh.write(f"{_adesso()} {chi}: uscita 0 in {durata:.1f} s, niente di nuovo\n")
        try:
            esito = json.loads(ULTIMA_RILETTURA.read_text(encoding="utf-8"))
            esito = esito if isinstance(esito, dict) else {}
        except (OSError, ValueError):
            esito = {}
        if esito.get("quando") and not esito.get("quando_esito"):
            esito["quando_esito"] = esito["quando"]
        esito.update({"quando": _adesso(), "ultima_da": da})
        ULTIMA_RILETTURA.write_text(json.dumps(esito, ensure_ascii=False, indent=1))
        return {
            "quando": esito["quando"],
            "messaggi": messaggi,
            "nuove": [],
            "parole_nuove": [],
            "a_parte": [],
            "sottofondo": {},
            "ultima_da": da,
        }
    with open(RILEGGI_LOG, "a") as fh:
        fh.write(
            f"{_adesso()} {chi}: uscita {p.returncode} in {durata:.1f} s\n{p.stdout}{p.stderr}"
        )
    piano = cosa_scaricare(note)
    partiti = _scarichi_in_sottofondo(piano)
    if dal_giro and any(piano.values()):
        _segna_scarico(piano, partiti)
    T = _parole().TESTI
    cosa = []
    if nuove:
        cosa.append(_conta(len(nuove), T["spunto_nuovo"], T["spunti_nuovi"]))
    if parole:
        cosa.append(T["parole_nuove"].format(n=len(parole)))
    if a_parte:
        cosa.append(T["a_parte_nuove"].format(n=len(a_parte)))
    try:
        lettura = json.loads(DM_LETTURA.read_text(encoding="utf-8"))
        lettura = lettura if isinstance(lettura, dict) else {}
    except (OSError, ValueError):
        lettura = {}
    frase = _frase_lettura(T, lettura, messaggi, cosa)
    if partiti:
        pezzi = []
        if piano["reel"]:
            pezzi.append(_conta(piano["reel"], T["un_reel"], T["n_reel"]))
        if piano["pagine"]:
            pezzi.append(_conta(piano["pagine"], T["una_pagina"], T["n_pagine"]))
        if piano["x"]:
            pezzi.append(_conta(piano["x"], T["un_post_x"], T["n_post_x"]))
        if piano["audio"]:
            pezzi.append(_conta(piano["audio"], T["un_audio"], T["n_audio"]))
        frase += ". " + T["scarichi_partiti"].format(cosa=" e ".join(pezzi))
    dettaglio = [_titolo_voce(note[i]) for i in nuove] + [
        T["parole_su"].format(titolo=_titolo_voce(note[i])) for i in parole
    ]
    adesso = _adesso()
    esito = {
        "quando": adesso,
        "quando_esito": adesso,
        "ultima_da": da,
        "messaggi": messaggi,
        "lettura": (lettura.get("ultima") or {}) if isinstance(lettura, dict) else {},
        "nuove": [{"id": i, "titolo": _titolo_voce(note[i])} for i in nuove],
        "parole_nuove": parole,
        "a_parte": a_parte,
        "sottofondo": piano if partiti else {},
        "frase": frase,
        "dettaglio": dettaglio,
    }
    ULTIMA_RILETTURA.write_text(json.dumps(esito, ensure_ascii=False, indent=1))
    return esito


def parser():
    ""

    ap = argparse.ArgumentParser(prog="sb-motore.py inspiration")
    sub = ap.add_subparsers(dest="verbo", required=True)
    s = sub.add_parser("conferma")
    s.add_argument("id")
    s.add_argument("--esito", default="")
    s.add_argument("--correzione", default="")
    s.add_argument("--audio", default="")
    s.add_argument("--durata", default="")
    s = sub.add_parser("rispondi")
    s.add_argument("id")
    s.add_argument("--domanda", default="")
    s.add_argument("--testo", default="")
    s.add_argument("--audio", default="")
    s.add_argument("--durata", default="")
    for v in ("risposta-giusta", "togli-risposta"):
        s = sub.add_parser(v)
        s.add_argument("id")
        s.add_argument("--domanda", required=True)
    for v in ("ci-lavoriamo", "ritorno-letto"):
        sub.add_parser(v).add_argument("id")
    s = sub.add_parser("dopo-risposta")
    s.add_argument("id")

    s.add_argument("--solo-avviso", action="store_true", dest="solo_avviso")
    s = sub.add_parser("capisci")
    s.add_argument("id")
    s.add_argument("--pannello", action="store_true")
    s = sub.add_parser("comprensione-sottofondo")
    s.add_argument("--cartella", required=True)
    s.add_argument("--titolo", default="Understand")
    s = sub.add_parser("rilettura-sottofondo")
    s.add_argument("--cartella", required=True)
    s.add_argument("--titolo", default="Re-read")
    s.add_argument("--voce", required=True)
    sub.add_parser("rileggi-risposta").add_argument("id")
    s = sub.add_parser("avvia")
    s.add_argument("id")
    s.add_argument("--task", action="store_true")
    s = sub.add_parser("vai")
    s.add_argument("id")
    s.add_argument("--lavoro", action="store_true")
    sub.add_parser("importa")
    sub.add_parser("rileggi").add_argument("--intera", action="store_true")
    sub.add_parser("giro")
    sub.add_parser("smistamento-giro").add_argument(
        "cosa", nargs="?", default="adesso", choices=("adesso", "accendi", "spegni", "stato")
    )
    s = sub.add_parser("smistamento-sottofondo")
    s.add_argument("--cartella", required=True)
    s.add_argument("--voci", required=True)
    sub.add_parser("arretrati-giro").add_argument(
        "cosa", nargs="?", default="adesso", choices=("adesso", "accendi", "spegni", "stato")
    )
    s = sub.add_parser("arretrati-sottofondo")
    s.add_argument("--cartella", required=True)
    s.add_argument("--voce", required=True)
    s = sub.add_parser("smista")
    s.add_argument("id")
    s.add_argument("--esito", default="")
    s.add_argument("--progetto", default="")
    s.add_argument("--rimetti", action="store_true")
    s.add_argument(
        "--si", action="store_true", help="the yes on the proposal (it's the behavior without --esito)"
    )

    s = sub.add_parser("scope")
    s.add_argument("id")
    s.add_argument("--giusto", action="store_true")
    s.add_argument("--testo", default="")
    s.add_argument("--audio", default="")
    s.add_argument("--durata", default="")
    s.add_argument("--strada", default="")
    s.add_argument("--tipo", default="")
    s.add_argument("--progetto", default="")
    s.add_argument("--area", default="")
    s.add_argument("--chi", default="")
    s.add_argument("--risposte", default="")
    s.add_argument("--domanda", default="")
    s.add_argument("--prendi-proposta", action="store_true", dest="prendi")

    s.add_argument("--versione", default="")
    s.add_argument("--tieni", action="store_true")
    s.add_argument("--rifai", action="store_true")
    for v in ("riapri", "crea-task", "letto"):
        s = sub.add_parser(v)
        s.add_argument("id")
        s.add_argument("--versione", default="")
        if v == "crea-task":

            s.add_argument("--rifai", action="store_true")
    sub.add_parser("passaggio-intero")
    sub.add_parser("da-solo").add_argument("cosa", choices=("accendi", "spegni", "stato"))
    sub.add_parser("riparti-fermi").add_argument("cosa", choices=("uno", "no", "stato"))


    s = sub.add_parser("impostazioni")
    s.add_argument("chiave", nargs="?", default="")
    s.add_argument("valore", nargs="?", default="")
    s.add_argument("--da", choices=("owner", "secondbrain"), default="secondbrain")

    s = sub.add_parser("filtri-salvati")
    s.add_argument("cosa", nargs="?", default="")
    s.add_argument("nome", nargs="?", default="")
    s.add_argument("filtro", nargs="?", default="")
    s.add_argument("--da", choices=("owner", "secondbrain"), default="secondbrain")


    s = sub.add_parser("conferma-lista")
    s.add_argument("--strada", default="")
    s.add_argument("coppie", nargs="+")

    sub.add_parser("riapri-lista").add_argument("gruppo")
    sub.add_parser("scarichi").add_argument("--piano", default="{}")
    return ap



REGISTRO_APP = "registro-app.log"

VERBI_IN_SOTTOFONDO = frozenset(
    {
        "dopo-risposta",
        "scarichi",
        "comprensione-sottofondo",
        "rilettura-sottofondo",
        "giro",
        "passaggio-intero",
        "smistamento-sottofondo",
        "smistamento-giro",
        "arretrati-sottofondo",
        "arretrati-giro",
    }
)

VERBI_SENZA_VOCE = frozenset(
    {
        "importa",
        "rileggi",
        "da-solo",
        "riparti-fermi",
        "impostazioni",
        "filtri-salvati",
        "conferma-lista",
        "riapri-lista",
    }
)


def _registra_esito(argv, out=None, errore=None):
    ""


    verbo = str(argv[0]) if argv else ""
    if verbo in VERBI_IN_SOTTOFONDO:
        return
    ident = (
        str(argv[1])
        if len(argv) > 1 and verbo not in VERBI_SENZA_VOCE and not str(argv[1]).startswith("-")
        else ""
    )
    testa = f"{_adesso()} gesture {verbo or '?'}" + (f" item={ident}" if ident else "")
    if errore is not None:
        detto = " ".join(f"{type(errore).__name__}: {errore}".split())[:300]
        riga = f"{testa}, exception, {detto}, the app gets no response"
    else:
        frase = " ".join(str(out.get("messaggio") or "").split())
        riga = (
            f"{testa}, failed"
            + (", warning" if out.get("avviso") else "")
            + (f", code {out['codice']}" if out.get("codice") else "")
            + (f", «{frase}»" if frase else ", no message")
        )
    with (
        contextlib.suppress(OSError),
        open(CASA_ARCHIVIO / REGISTRO_APP, "a", encoding="utf-8") as f,
    ):
        f.write(riga + "\n")


def esegui(argv):
    ""


    ap = parser()
    try:
        a = ap.parse_args(argv)
    except SystemExit as e:
        _registra_esito(argv, errore=e)
        raise
    if a.verbo == "dopo-risposta":
        return {"ok": dopo_risposta(a.id, solo_avviso=a.solo_avviso) == 0}
    if a.verbo == "scarichi":
        return {"ok": scarichi(json.loads(a.piano)) == 0}
    if a.verbo == "comprensione-sottofondo":
        return {"ok": comprensione_sottofondo(a.cartella, a.titolo) == 0}
    if a.verbo == "rilettura-sottofondo":
        return {"ok": rilettura_sottofondo(a.cartella, a.titolo, a.voce) == 0}
    if a.verbo == "giro":
        return {"ok": True, **giro()}
    if a.verbo == "passaggio-intero":
        return {"ok": True, "passaggio": passaggio_intero_staccato()}
    if a.verbo == "smistamento-sottofondo":
        return {"ok": smistamento_sottofondo(a.cartella, json.loads(a.voci)) == 0}
    if a.verbo == "smistamento-giro":
        return {"ok": True, "giro": smistamento_giro(a.cosa)}
    if a.verbo == "arretrati-sottofondo":
        return {"ok": arretrati_sottofondo(a.cartella, a.voce) == 0}
    if a.verbo == "arretrati-giro":
        return {"ok": True, "giro": arretrati_giro(a.cosa)}
    try:
        fatto = {
            "conferma": lambda: conferma(a.id, a.esito, a.correzione, a.audio, a.durata),
            "rispondi": lambda: rispondi(a.id, a.domanda, a.testo, a.audio, a.durata),
            "risposta-giusta": lambda: risposta_giusta(a.id, a.domanda),
            "togli-risposta": lambda: togli_risposta(a.id, a.domanda),
            "ci-lavoriamo": lambda: ci_lavoriamo(a.id),
            "capisci": lambda: capisci(a.id, a.pannello),
            "avvia": lambda: avvia(a.id, a.task),
            "vai": lambda: vai(a.id, a.lavoro),
            "ritorno-letto": lambda: ritorno_letto(a.id),
            "rileggi-risposta": lambda: rileggi_risposta(a.id),
            "importa": importa,
            "rileggi": lambda: rileggi(a.intera),
            "da-solo": lambda: da_solo(a.cosa),
            "riparti-fermi": lambda: riparti_fermi(a.cosa),

            "impostazioni": lambda: impostazioni(a.chiave, a.valore, a.da),

            "filtri-salvati": lambda: filtri_salvati(a.cosa, a.nome, a.filtro, a.da),
            "smista": lambda: smista(a.id, a.esito, a.progetto, a.rimetti),
            "scope": lambda: scope(
                a.id,
                giusto=a.giusto,
                testo=a.testo,
                audio=a.audio,
                strada=a.strada,
                tipo=a.tipo,
                progetto=a.progetto,
                area=a.area,
                chi=a.chi,
                risposte=a.risposte,
                tieni=a.tieni,
                rifai=a.rifai,
                durata=a.durata or None,
                domanda=a.domanda,
                prendi=a.prendi,
                versione=a.versione,
            ),
            "riapri": lambda: riapri(a.id, a.versione),
            "crea-task": lambda: (
                rifai_task(a.id, a.versione) if a.rifai else crea_task_uscita(a.id, a.versione)
            ),
            "letto": lambda: letto(a.id, a.versione),
            "conferma-lista": lambda: conferma_lista(a.coppie, a.strada),
            "riapri-lista": lambda: riapri_lista(a.gruppo),
        }[a.verbo]()
        if _gesto_di(a) in GESTI_DI_OWNER and not _solo_un_audio(a):


            for ident in _ids_del_gesto(a, fatto):
                _segna_gesto(ident)
        out = {"ok": True, **(fatto or {})}
        if out["ok"] is False:
            _registra_esito(argv, out)
        return out
    except Errore as e:

        out = {
            "ok": False,
            "messaggio": str(e),
            **({"avviso": True} if isinstance(e, Avviso) else {}),
        }
        _registra_esito(argv, out)
        return out
    except SystemExit as e:

        out = {
            "ok": False,
            "messaggio": str(e.code) if isinstance(e.code, str) else FRASI["non_andata"],
        }
        _registra_esito(argv, out)
        return out
    except Exception as e:


        _registra_esito(argv, errore=e)
        raise


def main(argv=None):
    print(json.dumps(esegui(sys.argv[1:] if argv is None else argv), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
