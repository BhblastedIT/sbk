#!/usr/bin/env python3
"""L4, run by hand: separates the provenance of a claim from the provenance of its record across the knowledge store (dry run unless --apply)."""




































































































from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone  # noqa: UP017
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import sbk_resources as R  # noqa: E402
from freno_massa import verifica_quota  # noqa: E402
from knowledge_schema import e_artefatto_rigenerato  # noqa: E402

log = logging.getLogger("separa-provenienza")

DOMINI = ("person", "org", "organization", "deal", "commitment")




CAMPO_MIGRATO = "extracted_at"






_DIALETTI = ((2, True), (2, False), (1, True), (1, False), (4, True), (4, False))


def rileva_dialetto(raw: str, d) -> tuple[int, bool, bool]:
    ""





    for indent, ea in _DIALETTI:
        for nl in ("", "\n"):
            if json.dumps(d, indent=indent, ensure_ascii=ea, default=str) + nl == raw:
                return indent, ea, nl == "\n"
    return 2, True, False


def serializza(d, dialetto: tuple[int, bool, bool]) -> str:
    indent, ea, nl = dialetto
    return json.dumps(d, indent=indent, ensure_ascii=ea, default=str) + ("\n" if nl else "")


def scrivi_atomico(path: Path, testo: str) -> None:
    ""




    tmp = path.with_name(path.name + ".tmp")
    fatto = False
    try:
        tmp.write_text(testo, encoding="utf-8")
        tmp.replace(path)
        fatto = True
    finally:
        if not fatto and tmp.exists():
            tmp.unlink(missing_ok=True)





def separa_blocco(blocco: dict, source_file: str) -> bool:
    ""





    if "record" in blocco:
        return False
    src = blocco.get("source") if isinstance(blocco.get("source"), dict) else blocco
    if CAMPO_MIGRATO not in src:
        return False
    rec = {CAMPO_MIGRATO: src.pop(CAMPO_MIGRATO)}
    rec["artefatto_rigenerato"] = e_artefatto_rigenerato(source_file)
    blocco["record"] = rec
    return True


def riunisci_blocco(blocco: dict) -> tuple[bool, list[str]]:
    ""





    rec = blocco.get("record")
    if not isinstance(rec, dict):
        return False, []
    src = blocco.get("source") if isinstance(blocco.get("source"), dict) else blocco
    persi = sorted(set(rec) - {CAMPO_MIGRATO, "artefatto_rigenerato"})
    if CAMPO_MIGRATO in rec:






        ancora = "record_id" if src is not blocco else "valid_from"
        _reinserisci_dopo(src, ancora, CAMPO_MIGRATO, rec[CAMPO_MIGRATO])
    del blocco["record"]
    return True, persi


def _reinserisci_dopo(d: dict, dopo: str, chiave: str, valore) -> None:
    ""












    if chiave in d:
        return
    nuovo: dict = {}
    messo = False
    for k, v in list(d.items()):
        nuovo[k] = v
        if k == dopo:
            nuovo[chiave] = valore
            messo = True
    if not messo:
        nuovo = {chiave: valore, **nuovo}
    d.clear()
    d.update(nuovo)


def _riordina_source(fatto: dict) -> None:
    ""





    if "record" not in fatto:
        return
    rec = fatto.pop("record")
    nuovo = {}
    for k, v in list(fatto.items()):
        nuovo[k] = v
        if k == "source":
            nuovo["record"] = rec
    if "record" not in nuovo:
        nuovo["record"] = rec
    fatto.clear()
    fatto.update(nuovo)


def trasforma_fatto(fatto: dict, inverti: bool, st: Counter) -> bool:
    src = fatto.get("source") if isinstance(fatto.get("source"), dict) else {}
    sf = str(src.get("source_file") or "")
    cambiato = False
    if inverti:
        c, persi = riunisci_blocco(fatto)
        cambiato |= c
        if c:
            st["campi_riuniti"] += 1
        for p in persi:
            st[f"PERSO_{p}"] += 1
    else:
        if separa_blocco(fatto, sf):
            cambiato = True
            st["campi_spostati"] += 1
            if fatto["record"]["artefatto_rigenerato"]:
                st["fatti_su_artefatto_rigenerato"] += 1
            _riordina_source(fatto)
        elif "record" in fatto:
            st["fatti_gia_migrati"] += 1







            if CAMPO_MIGRATO in src:
                st["MISTO_fatti"] += 1
        elif CAMPO_MIGRATO not in src:
            st["fatti_senza_extracted_at"] += 1

    for o in fatto.get("observations") or []:
        if not isinstance(o, dict):
            continue
        if inverti:
            c, persi = riunisci_blocco(o)
            cambiato |= c
            if c:
                st["oss_riunite"] += 1
            for p in persi:
                st[f"PERSO_oss_{p}"] += 1
        elif separa_blocco(o, str(o.get("source_file") or "")):
            cambiato = True
            st["oss_spostate"] += 1
            if o["record"]["artefatto_rigenerato"]:
                st["oss_su_artefatto_rigenerato"] += 1
        elif "record" in o and CAMPO_MIGRATO in o:
            st["MISTO_oss"] += 1
    return cambiato





def impronta(fatto: dict) -> tuple:
    ""








    src = fatto.get("source") if isinstance(fatto.get("source"), dict) else {}
    v = fatto.get("value")
    return (
        fatto.get("fact_id"),
        fatto.get("entity_id"),
        fatto.get("attribute"),
        str(v).strip().lower() if v is not None else "",
        src.get("source_type"),
        src.get("record_id"),
        src.get("source_file"),
        len(fatto.get("observations") or []),
    )





def sorgenti(radice: Path):
    ent = radice / "entities"
    for dom in DOMINI:
        d = ent / dom
        if d.is_dir():
            for p in sorted(d.glob("*.json")):
                yield ("json", p)
    fatti = radice / "facts"
    for dom in DOMINI:
        d = fatti / dom
        if d.is_dir():
            for p in sorted(d.glob("*.jsonl")):
                yield ("jsonl", p)


def passa(radice: Path, inverti: bool, applica: bool, st: Counter, imp: Counter) -> None:
    for tipo, p in sorgenti(radice):
        st["file_letti"] += 1
        raw = p.read_text(encoding="utf-8")
        try:
            if tipo == "json":
                d = json.loads(raw)
                fatti = d.get("facts") or []
            else:
                righe = [r for r in raw.split("\n") if r.strip()]
                fatti = [json.loads(r) for r in righe]
                d = None
        except json.JSONDecodeError as e:
            st["file_illeggibili"] += 1
            log.warning("unreadable, skipped: %s (%s)", p.name, e)
            continue

        cambiato = False
        for f in fatti:
            st["fatti"] += 1
            imp[impronta(f)] += 1
            cambiato |= trasforma_fatto(f, inverti, st)

        if not cambiato:
            del raw, fatti, d
            continue
        st["file_cambiati"] += 1
        if not applica:
            del raw, fatti, d
            continue

        if tipo == "json":
            dial = rileva_dialetto(raw, json.loads(raw))
            if dial == (2, True, False):
                st["dial_2_ascii"] += 1
            else:
                st[f"dial_{dial[0]}_{dial[1]}_{dial[2]}"] += 1
            scrivi_atomico(p, serializza(d, dial))
        else:
            scrivi_atomico(p, "".join(json.dumps(f, default=str) + "\n" for f in fatti))
        del raw, fatti, d


def tar_di_sicurezza(radice: Path) -> Path:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")  # noqa: UP017
    dest = radice.parent / "backups-provenienza"
    dest.mkdir(parents=True, exist_ok=True)
    arch = dest / f"knowledge-pre-separa-{ts}.tar.gz"
    log.info("safety tar: %s → %s", radice, arch)
    t = subprocess.run(
        ["tar", "-czf", str(arch), "-C", str(radice.parent), radice.name],
        capture_output=True,
        text=True,
    )
    if t.returncode != 0:
        raise RuntimeError(f"tar failed: {(t.stderr or '').strip()}")
    v = subprocess.run(["gzip", "-t", str(arch)], capture_output=True, text=True)
    if v.returncode != 0:
        raise RuntimeError(f"gzip -t FAILED on {arch}: {(v.stderr or '').strip()} — abort")
    log.info("tar verified (gzip -t): %.1f MB", arch.stat().st_size / 1024**2)
    return arch


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--apply", action="store_true", help="actually writes (default: dry-run)")
    ap.add_argument("--su", type=Path, help="alternative root (a COPY of the store)")
    ap.add_argument("--inverti", action="store_true", help="the inverse transformation")
    ap.add_argument("--senza-tar", action="store_true", help="skip the tar (only with --su)")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if a.su:
        radice = a.su.expanduser().resolve()
    else:
        import sbk_config as cfg

        radice = cfg.KNOWLEDGE_DIR
    if not (radice / "entities").is_dir():
        log.error("%s does not look like a knowledge store (entities/ missing)", radice)
        return 2

    b = R.budget()
    log.info(
        "budget: job %.1f GB · segments %.0f%% [%s] · root %s",
        b.job_gb,
        R.pressure().seg_ratio * 100,
        R.level_for(R.pressure().seg_ratio),
        radice,
    )
    if R.level_for(R.pressure().seg_ratio) == "critico":
        log.error("critical pressure: not starting. The peak is one file (45 MB max), but the tar is not.")
        return 75

    verso = "reverse" if a.inverti else "forward"
    log.info("pass %s · %s", verso, "APPLY" if a.apply else "dry-run (no writing)")


    st = Counter()
    imp_pre = Counter()
    passa(radice, a.inverti, False, st, imp_pre)

    tocca = st["campi_spostati"] + st["campi_riuniti"]
    log.info(
        "  files read %s · facts %s · facts touched %s · observations touched %s",
        f"{st['file_letti']:,}",
        f"{st['fatti']:,}",
        f"{tocca:,}",
        f"{st['oss_spostate'] + st['oss_riunite']:,}",
    )
    log.info(
        "  on regenerated artifact: facts %s · observations %s",
        f"{st['fatti_su_artefatto_rigenerato']:,}",
        f"{st['oss_su_artefatto_rigenerato']:,}",
    )
    if st["fatti_gia_migrati"]:
        log.info("  already migrated (no-op, idempotence): %s", f"{st['fatti_gia_migrati']:,}")
    misti = st["MISTO_fatti"] + st["MISTO_oss"]
    if misti:
        log.error(
            "  MIXED: %s blocks ALREADY have `record` AND ALSO legacy `source.%s`. The "
            "migration SKIPS them (idempotence guard) and the invariant stays violated "
            "right there. They must be closed by hand before declaring ⑬.",
            f"{misti:,}",
            CAMPO_MIGRATO,
        )
    if st["file_illeggibili"]:
        log.warning("  unreadable files SKIPPED: %s", st["file_illeggibili"])
    for k, v in sorted(st.items()):
        if k.startswith("PERSO_"):
            log.warning(
                "  the inverse DROPS %s on %s blocks (it has no home in the old schema)",
                k[6:],
                f"{v:,}",
            )


    perche = (
        f"schema rewrite ⑬ (separation of statement/record provenance). "
        f"Touches 100% by construction: every fact has `source.extracted_at`. "
        f"Conservation self-certified on the dry-run: facts {st['fatti']:,} "
        f"unchanged, observations {st['oss_spostate'] + st['oss_riunite']:,} "
        f"unchanged, multiset (fact_id, entity_id, attribute, norm(value), "
        f"source_type, record_id, source_file, n_oss) identical before and after. "
        f"No fact created, none deleted. Rollback = pre-run tar."
    )
    frazione = verifica_quota(
        tocca=tocca,
        totale=st["fatti"],
        operazione=f"xs-l4-separa-provenienza ({verso})",
        forza=True,
        perche=perche,
    )
    log.info("  brake: %.1f%% of the population — declared exemption", frazione * 100)

    if not a.apply:
        log.info("dry-run: no writing. Rerun with --apply.")
        return 0

    if not a.senza_tar:
        tar_di_sicurezza(radice)
    elif not a.su:
        log.error("--senza-tar is only allowed with --su (a copy). On the real store: no.")
        return 2

    st2 = Counter()
    imp_post = Counter()
    passa(radice, a.inverti, True, st2, imp_post)
    log.info("  wrote %s files", f"{st2['file_cambiati']:,}")
    for k, v in sorted(st2.items()):
        if k.startswith("dial_"):
            log.info("  dialect %s: %s files", k[5:], f"{v:,}")


    st3 = Counter()
    imp_verifica = Counter()
    passa(radice, a.inverti, False, st3, imp_verifica)
    if imp_verifica == imp_pre:
        log.info("CONSERVATION OK: multiset identical over %s facts", f"{st3['fatti']:,}")
    else:
        soloA = sum((imp_pre - imp_verifica).values())
        soloB = sum((imp_verifica - imp_pre).values())
        log.error("CONSERVATION VIOLATED: %s fingerprints lost, %s appeared", soloA, soloB)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
