#!/usr/bin/python3
""















import json
import re
from datetime import datetime, timedelta, timezone

UTC0 = timezone(timedelta(0))

FINESTRA_ATTIVA = (
    30 * 60
)
CODA_BYTE = 6_000_000

# Default re-read prompt used after an unexpected restart. Override via user config.
PROMPT_RILETTURA = """The machine restarted at {quando} and this session was reopened after an unexpected reset.

Re-read the session history and the details of what was happening, in depth.
Re-read the instructions you were given, what you were doing, and what you were working on.
Re-read the files you were editing: which are complete, which are partial, and where it stopped.

Take the time to analyze in detail, nothing superficial, do not take anything for granted; dig in before resuming.

Once you understand what you were doing and have the full context, structure a restart the same way, to reach the same objectives you were working on."""

_LANCIO = [
    (re.compile(r"Command running in background with ID: ([A-Za-z0-9_-]+)"), "bash"),
    (re.compile(r"Task ID: ([A-Za-z0-9_-]+)"), "workflow"),
    (re.compile(r"agent_id: ([A-Za-z0-9_-]+)"), "agente"),
    (re.compile(r"Monitor started \(task ([A-Za-z0-9_-]+)"), "monitor"),
]
_FINE = re.compile(
    r"<task-id>([A-Za-z0-9_-]+)</task-id>.{0,400}?<status>(completed|failed|killed|stopped|cancelled)</status>",
    re.S,
)
_MONITOR_FINITO = re.compile(
    r"<task-id>([A-Za-z0-9_-]+)</task-id>.{0,200}?Monitor (expired|ended|stopped)", re.S
)
_TASKSTOP = re.compile(r"Successfully stopped task: ([A-Za-z0-9_-]+)")
_SVEGLIA = re.compile(r"Next wakeup scheduled for (\d{1,2}):(\d{2})")


def _ts(rec):
    t = rec.get("timestamp")
    if not t:
        return None
    try:
        return datetime.strptime(t[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=UTC0).timestamp()
    except ValueError:
        return None


def _coda(path):
    try:
        with open(path, "rb") as fh:
            fh.seek(0, 2)
            n = fh.tell()
            fh.seek(max(0, n - CODA_BYTE))
            dati = fh.read()
    except OSError:
        return []
    righe = dati.split(b"\n")
    if n > CODA_BYTE:
        righe = righe[1:]
    out = []
    for r in righe:
        if not r.strip():
            continue
        try:
            out.append(json.loads(r))
        except ValueError:
            continue
    return out


def _testo(rec):
    ""
    m = rec.get("message")
    parti = []
    if isinstance(m, dict):
        c = m.get("content")
        if isinstance(c, str):
            parti.append(c)
        elif isinstance(c, list):
            for x in c:
                if not isinstance(x, dict):
                    continue
                if x.get("type") == "text":
                    parti.append(x.get("text") or "")
                elif x.get("type") == "tool_result":
                    cc = x.get("content")
                    if isinstance(cc, str):
                        parti.append(cc)
                    elif isinstance(cc, list):
                        parti += [y.get("text") or "" for y in cc if isinstance(y, dict)]
    for k in ("content", "toolUseResult", "attachment"):
        v = rec.get(k)
        if isinstance(v, str):
            parti.append(v)
        elif isinstance(v, (dict, list)):  # noqa: UP038 system python 3.9
            parti.append(json.dumps(v, ensure_ascii=False))
    return "\n".join(parti)


def _conversazione(rec):
    ""

    t = rec.get("type")
    if t in ("assistant", "user"):
        return True
    if t == "queue-operation":
        return True
    return False


def analizza(path, fino_a):
    ""

    recs = [r for r in _coda(path) if (_ts(r) or 0) <= fino_a]
    aperti = {}
    finiti = set()
    sveglia = None
    ultimo = None
    ultimo_tipo = None
    ultimo_testo_assistente = None
    tool_aperti = set()
    for r in recs:
        ts = _ts(r)
        if ts and _conversazione(r):
            ultimo = ts
            ultimo_tipo = r.get("type")
        testo = _testo(r)
        for rx, tipo in _LANCIO:
            for m in rx.finditer(testo):
                aperti.setdefault(m.group(1), {"tipo": tipo, "ts": ts})
        for m in _FINE.finditer(testo):
            finiti.add(m.group(1))
        for m in _MONITOR_FINITO.finditer(testo):
            finiti.add(m.group(1))
        for m in _TASKSTOP.finditer(testo):
            finiti.add(m.group(1))


        if "idle_notification" in testo or "teammate-message" in testo:
            for k, v in aperti.items():
                if v["tipo"] == "agente" and k not in finiti:
                    nome = k[1:].rsplit("-", 1)[0] if k.startswith("a") else k
                    if nome and (
                        f'"from":"{nome}"' in testo
                        or f'teammate_id="{nome}"' in testo
                        or f'"from": "{nome}"' in testo
                        or f'from="{nome}"' in testo
                    ):
                        finiti.add(k)
        s = _SVEGLIA.search(testo)
        if s and ts:
            sveglia = ts
        msg = r.get("message") if isinstance(r.get("message"), dict) else {}
        cont = msg.get("content") if isinstance(msg.get("content"), list) else []
        if r.get("type") == "assistant":
            for x in cont:
                if isinstance(x, dict) and x.get("type") == "tool_use":
                    tool_aperti.add(x.get("id"))
                if isinstance(x, dict) and x.get("type") == "text":
                    ultimo_testo_assistente = ts
        if r.get("type") == "user":
            for x in cont:
                if isinstance(x, dict) and x.get("type") == "tool_result":
                    tool_aperti.discard(x.get("tool_use_id"))


    in_sottofondo = []
    for k, v in aperti.items():
        if k in finiti:
            continue
        if v["tipo"] == "monitor":
            continue
        in_sottofondo.append({"id": k, **v})
    return {
        "ultimo": ultimo,
        "in_sottofondo": in_sottofondo,
        "turno_aperto": bool(tool_aperti),
        "sveglia_programmata": sveglia,
        "ultimo_testo_assistente": ultimo_testo_assistente,
        "tipo_ultimo": ultimo_tipo,
    }


def stava_lavorando(path, fino_a, spegnimento=None):
    ""

    spegnimento = spegnimento or fino_a
    a = analizza(path, fino_a)
    if a["ultimo"] is None:
        return False, "empty transcript before the restart"
    recente = spegnimento - a["ultimo"] <= FINESTRA_ATTIVA
    if a["turno_aperto"] and recente:
        return True, "turn open at shutdown"
    if recente:
        return True, f"work in the last {int((spegnimento - a['ultimo']) // 60)} minutes"
    recenti_bg = [
        x for x in a["in_sottofondo"] if x.get("ts") and spegnimento - x["ts"] <= 24 * 3600
    ]
    if recenti_bg:
        return True, "in the background without a finish notification: " + ", ".join(
            f"{x['tipo']} {x['id']}" for x in recenti_bg[:5]
        )
    return False, f"idle for {int((spegnimento - a['ultimo']) // 60)} minutes"


def ora_spegnimento(transcripts, prima_di):
    ""

    meglio = 0
    for p in transcripts:
        for r in reversed(_coda(p)[-400:]):
            ts = _ts(r)
            if ts and ts <= prima_di:
                meglio = max(meglio, ts)
                break
    return meglio or None


def ordina(foto, primi):
    ""


    pos = {n.lower(): i for i, n in enumerate(primi)}
    testa = sorted(
        [s for s in foto if (s.get("titolo") or "").lower() in pos],
        key=lambda s: pos[s["titolo"].lower()],
    )
    resto = [s for s in foto if (s.get("titolo") or "").lower() not in pos]
    code = {}
    for s in sorted(resto, key=lambda s: (s.get("titolo") or "").lower()):
        code.setdefault(s.get("account") or "?", []).append(s)
    ordine_conti = sorted(code, key=lambda k: (-len(code[k]), k))
    coda = []
    while any(code.values()):
        for k in ordine_conti:
            if code[k]:
                coda.append(code[k].pop(0))
    return testa + coda


def quando_testo(spegnimento):
    if not spegnimento:
        return "for a restart"
    t = datetime.fromtimestamp(spegnimento)
    return f"around {t:%H:%M} on {t:%d/%m}"
