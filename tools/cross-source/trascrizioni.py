""




































from __future__ import annotations

import re




_RIGA = re.compile(r"^\s*([^:\n]{1,60}?)\s*:\s*(.*)$")



SOGLIA_PAROLA_PER_RIGA = 1.6


def e_parola_per_riga(testo: str, campione: int = 200) -> bool:
    ""




    righe = [r for r in testo.split("\n") if r.strip()][:campione]
    if len(righe) < 10:
        return False
    parole = []
    for r in righe:
        m = _RIGA.match(r)
        parole.append(len((m.group(2) if m else r).split()))
    return sum(parole) / max(1, len(parole)) < SOGLIA_PAROLA_PER_RIGA


def turni(testo: str) -> list[tuple[str, str]]:
    ""




    fuori: list[tuple[str, list[str]]] = []
    for riga in testo.split("\n"):
        if not riga.strip():
            continue
        m = _RIGA.match(riga)
        if m:
            chi, parola = m.group(1).strip(), m.group(2).strip()
        else:
            chi, parola = "", riga.strip()
        if not parola:
            continue
        if fuori and (chi == fuori[-1][0] or not chi):
            fuori[-1][1].append(parola)
        else:
            fuori.append((chi, [parola]))
    return [(chi, " ".join(pezzi)) for chi, pezzi in fuori]


def testo_leggibile(dati: dict | str) -> str:
    ""





    if isinstance(dati, str):
        testo = dati
    else:
        seg = dati.get("segments")
        if isinstance(seg, list) and seg:
            pezzi = []


            lunghezze = [len(str(s.get("text", ""))) for s in seg[:40] if isinstance(s, dict)]
            if lunghezze and sum(lunghezze) / len(lunghezze) > 25:
                for s in seg:
                    if not isinstance(s, dict):
                        continue
                    t = str(s.get("text") or "").strip()
                    if t:
                        chi = str(s.get("speaker") or "").strip()
                        pezzi.append(f"{chi}: {t}" if chi else t)
                return "\n".join(pezzi)
        testo = str(dati.get("raw_transcript") or dati.get("text") or dati.get("transcript") or "")
    if not testo:
        return ""
    if not e_parola_per_riga(testo):
        return testo
    return "\n".join(f"{chi}: {frase}" if chi else frase for chi, frase in turni(testo))
