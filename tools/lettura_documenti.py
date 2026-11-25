""






















from __future__ import annotations

import base64
import email
import email.policy
import io
import json
import re
import shutil
import struct
import subprocess
import tempfile
import threading
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET


MAX_CHARS = 100_000
TIMEOUT_S = 120
MAX_ZIP_MEMBER = 200 * 2**20
MAX_STREAM = 64 * 2**20
OLE_MAGIC = bytes.fromhex("d0cf11e0a1b11ae1")

TEXTUTIL = "/usr/bin/textutil"
MDIMPORT = "/usr/bin/mdimport"
PLUTIL = "/usr/bin/plutil"

PDFTOTEXT = shutil.which("pdftotext") or "/opt/homebrew/bin/pdftotext"


VERSIONI = {
    "pdf": "pdftotext-1" if Path(PDFTOTEXT).exists() else "pdfplumber-1",
    "docx": "textutil-1",
    "xlsx": "openpyxl-1",
    "pptx": "stdlib-1",
    "doc": "textutil-1",
    "xls": "xlrd-1",
    "ppt": "mdimport-1",
    "odt": "stdlib-1",
    "ods": "stdlib-1",
    "rtf": "textutil-1",
    "eml": "stdlib-1",
    "msg": "stdlib-1",
    "p7m": "stdlib-1",
    "xml": "stdlib-1",
    "html": "bs4-1",
    "testo": "utf8-1",
}


_MDIMPORT = threading.Lock()


@dataclass
class Lettura:
    ""

    testo: str
    tipo: str
    lettore: str
    esito: str
    secondi: float
    motivo: str = ""

    @property
    def versione(self) -> str:
        return VERSIONI.get(self.tipo, "1")


class NonSupportato(ValueError):
    ""





def riconosci(testa: bytes, nome: str = "") -> str:
    ""
    if testa.startswith(OLE_MAGIC):
        return "ole2"
    if testa.startswith(b"PK\x03\x04"):
        return "zip"
    if testa.startswith(b"{\\rtf"):
        return "rtf"
    if testa.startswith(b"%PDF"):
        return "pdf"
    if testa[:1] == b"\x30" and testa[1:2] in (b"\x80", b"\x81", b"\x82", b"\x83", b"\x84"):
        return "der"
    s = testa.lstrip(b"\xef\xbb\xbf \t\r\n")
    if s[:5].lower() == b"<?xml":
        return "xml"
    if s[:1] == b"<":
        return "html"
    if re.match(rb"^MI[A-Za-z0-9+/]{20}", s):
        return "b64"
    if nome.lower().endswith((".eml", ".mbox")) or re.match(
        rb"^(Received|Return-Path|From|Delivered-To|MIME-Version|Message-ID):", s
    ):
        return "eml"
    return "testo"


def _sapore_zip(z: zipfile.ZipFile) -> str:
    ""
    nomi = set(z.namelist())
    if "mimetype" in nomi:
        mt = z.read("mimetype")[:100].decode("ascii", "replace").strip()
        return {
            "application/vnd.oasis.opendocument.text": "odt",
            "application/vnd.oasis.opendocument.spreadsheet": "ods",
            "application/vnd.oasis.opendocument.presentation": "odp",
        }.get(mt, "zip")
    if "word/document.xml" in nomi:
        return "docx"
    if "xl/workbook.xml" in nomi:
        return "xlsx"
    if "ppt/presentation.xml" in nomi:
        return "pptx"
    return "zip"


def _taglia(t: str, max_caratteri: int) -> str:
    return t[:max_caratteri].strip()


def _esegui(cmd: list[str], dati: bytes | None = None) -> bytes:
    r = subprocess.run(cmd, input=dati, capture_output=True, timeout=TIMEOUT_S)
    if r.returncode != 0:
        raise RuntimeError(f"{Path(cmd[0]).name} exited {r.returncode}: {r.stderr[:160]!r}")
    return r.stdout


def _html(html: str | bytes) -> str:
    from bs4 import BeautifulSoup

    zuppa = BeautifulSoup(html, "lxml")
    for tag in zuppa(["script", "style", "head"]):
        tag.decompose()
    return re.sub(r"\n\s*\n+", "\n", zuppa.get_text("\n"))





def _textutil(dati: bytes, formato: str) -> str:
    ""
    return _esegui(
        [TEXTUTIL, "-stdin", "-format", formato, "-convert", "txt", "-stdout"], dati
    ).decode("utf-8", "replace")


def _mdimport(dati: bytes, suffisso: str) -> str:
    ""
    with _MDIMPORT, tempfile.TemporaryDirectory() as d:
        p = Path(d) / f"documento{suffisso}"
        p.write_bytes(dati)
        r = subprocess.run([MDIMPORT, "-t", "-d3", str(p)], capture_output=True, timeout=TIMEOUT_S)
        uscita = r.stdout or r.stderr
        i = uscita.find(b"\n{")
        if i < 0:
            raise RuntimeError("mdimport returned no attributes")
        d_json = json.loads(_esegui([PLUTIL, "-convert", "json", "-o", "-", "-"], uscita[i + 1 :]))
    testo = d_json.get("kMDItemTextContent")
    if testo is None:
        return ""
    return testo


def _pdf(dati: bytes, max_caratteri: int) -> tuple[str, str]:
    if Path(PDFTOTEXT).exists():
        return _esegui([PDFTOTEXT, "-enc", "UTF-8", "-", "-"], dati).decode(
            "utf-8", "replace"
        ), "pdftotext"
    import pdfplumber

    parti, tot = [], 0
    with pdfplumber.open(io.BytesIO(dati)) as pdf:
        for pagina in pdf.pages:
            t = pagina.extract_text() or ""
            parti.append(t)
            tot += len(t)
            if tot >= max_caratteri:
                break
    return "\n".join(parti), "pdfplumber"




NS_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
NS_P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
NS_R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
NS_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"
_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/"
REL_NOTE, REL_DIAGRAMMA, REL_GRAFICO = _REL + "notesSlide", _REL + "diagramData", _REL + "chart"


def _xml_zip(z: zipfile.ZipFile, nome: str) -> ET.Element | None:
    try:
        info = z.getinfo(nome)
    except KeyError:
        return None
    if info.file_size > MAX_ZIP_MEMBER:
        raise ValueError(f"zip member too large: {info.file_size}")
    return ET.fromstring(z.read(nome))


def _relazioni(z: zipfile.ZipFile, parte: str) -> list[tuple[str, str]]:
    cartella, _, file = parte.rpartition("/")
    radice = _xml_zip(z, f"{cartella}/_rels/{file}.rels")
    if radice is None:
        return []
    fuori = []
    for r in radice.iter(NS_REL + "Relationship"):
        if r.get("TargetMode") == "External":
            continue
        meta = r.get("Target", "")
        pezzi = (
            (cartella + "/" + meta).split("/")
            if not meta.startswith("/")
            else meta.lstrip("/").split("/")
        )
        norm: list[str] = []
        for p in pezzi:
            if p == "..":
                if norm:
                    norm.pop()
            elif p and p != ".":
                norm.append(p)
        fuori.append((r.get("Type", ""), "/".join(norm)))
    return fuori


def _paragrafi(radice: ET.Element) -> list[str]:
    fuori = []
    for p in radice.iter(NS_A + "p"):
        t = "".join(x.text or "" for x in p.iter(NS_A + "t")).strip()
        if t:
            fuori.append(t)
    return fuori


def _pptx(z: zipfile.ZipFile, max_caratteri: int) -> str:
    ""



    pres = _xml_zip(z, "ppt/presentation.xml")
    rel = _xml_zip(z, "ppt/_rels/presentation.xml.rels")
    per_id = {}
    for r in rel.iter(NS_REL + "Relationship") if rel is not None else []:
        per_id[r.get("Id")] = "ppt/" + r.get("Target", "").lstrip("/").removeprefix("ppt/")
    ordine = (
        [per_id.get(s.get(NS_R + "id")) for s in pres.iter(NS_P + "sldId")]
        if pres is not None
        else []
    )
    parti, totale = [], 0
    for n, slide in enumerate([o for o in ordine if o], 1):
        radice = _xml_zip(z, slide)
        if radice is None:
            continue
        righe = _paragrafi(radice)
        for tipo, meta in _relazioni(z, slide):
            if tipo == REL_NOTE:
                nr = _xml_zip(z, meta)
                if nr is not None and (note := _paragrafi(nr)):
                    righe.append("[Notes] " + " / ".join(note))
            elif tipo in (REL_DIAGRAMMA, REL_GRAFICO):
                dr = _xml_zip(z, meta)
                if dr is not None:
                    righe.extend(_paragrafi(dr))
        if righe:
            blocco = f"[Slide {n}]\n" + "\n".join(righe)
            parti.append(blocco)
            totale += len(blocco)
            if totale >= max_caratteri:
                break
    return "\n\n".join(parti)





def _xlsx(dati: bytes, max_caratteri: int) -> str:
    ""
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(dati), read_only=True, data_only=True)
    parti, tot = [], 0
    try:
        for nome in wb.sheetnames:
            parti.append(f"[Sheet: {nome}]")
            for riga in wb[nome].iter_rows(values_only=True):
                celle = ["" if c is None else str(c) for c in riga]
                while celle and not celle[-1]:
                    celle.pop()
                if celle:
                    r = " | ".join(celle)
                    parti.append(r)
                    tot += len(r) + 1
                    if tot >= max_caratteri:
                        return "\n".join(parti)
    finally:
        wb.close()
    return "\n".join(parti)


def _xls(dati: bytes, max_caratteri: int) -> str:
    ""
    import xlrd

    wb = xlrd.open_workbook(file_contents=dati, on_demand=True)
    parti, tot = [], 0
    try:
        for i in range(wb.nsheets):
            foglio = wb.sheet_by_index(i)
            parti.append(f"[Sheet: {foglio.name}]")
            for r in range(foglio.nrows):
                celle = []
                for c in foglio.row(r):
                    if c.ctype in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK, xlrd.XL_CELL_ERROR):
                        celle.append("")
                    elif c.ctype == xlrd.XL_CELL_NUMBER:
                        celle.append(
                            str(int(c.value)) if float(c.value).is_integer() else str(c.value)
                        )
                    elif c.ctype == xlrd.XL_CELL_DATE:
                        try:
                            celle.append(
                                xlrd.xldate.xldate_as_datetime(c.value, wb.datemode).isoformat()
                            )
                        except (ValueError, OverflowError, xlrd.xldate.XLDateError):
                            celle.append(str(c.value))
                    elif c.ctype == xlrd.XL_CELL_BOOLEAN:
                        celle.append("TRUE" if c.value else "FALSE")
                    else:
                        celle.append(str(c.value))
                while celle and not celle[-1]:
                    celle.pop()
                if celle:
                    riga = " | ".join(celle)
                    parti.append(riga)
                    tot += len(riga) + 1
                    if tot >= max_caratteri:
                        return "\n".join(parti)
            wb.unload_sheet(i)
    finally:
        wb.release_resources()
    return "\n".join(parti)


NS_T = "{urn:oasis:names:tc:opendocument:xmlns:table:1.0}"
NS_X = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"


def _odf_testo(el: ET.Element) -> str:
    ""
    fuori = [el.text or ""]
    for c in el:
        if c.tag == NS_X + "s":
            fuori.append(" " * min(int(c.get(NS_X + "c", "1") or 1), 1000))
        elif c.tag == NS_X + "tab":
            fuori.append("\t")
        elif c.tag == NS_X + "line-break":
            fuori.append("\n")
        else:
            fuori.append(_odf_testo(c))
        fuori.append(c.tail or "")
    return "".join(fuori)


def _ods(z: zipfile.ZipFile, max_caratteri: int) -> str:
    ""
    if z.getinfo("content.xml").file_size > MAX_ZIP_MEMBER:
        raise ValueError("content.xml too large")
    parti: list[str] = []
    tot = 0
    riga: list[str] = []
    with z.open("content.xml") as f:
        for evento, el in ET.iterparse(f, events=("start", "end")):
            if evento == "start":
                if el.tag == NS_T + "table":
                    parti.append(f"[Sheet: {el.get(NS_T + 'name', '')}]")
                continue
            if el.tag in (NS_T + "table-cell", NS_T + "covered-table-cell"):
                t = "\n".join(_odf_testo(p) for p in el.findall(NS_X + "p")).strip()
                ripetute = int(el.get(NS_T + "number-columns-repeated", "1") or 1)
                riga.extend([t] * (min(ripetute, 64) if t else 1))
                el.clear()
            elif el.tag == NS_T + "table-row":
                while riga and not riga[-1]:
                    riga.pop()
                if riga:
                    r = " | ".join(riga)
                    parti.append(r)
                    tot += len(r) + 1
                riga = []
                el.clear()
                if tot >= max_caratteri:
                    break
    return "\n".join(parti)


def _odt(z: zipfile.ZipFile) -> str:
    if z.getinfo("content.xml").file_size > MAX_ZIP_MEMBER:
        raise ValueError("content.xml too large")
    radice = ET.fromstring(z.read("content.xml"))
    return "\n".join(
        t
        for el in radice.iter()
        if el.tag in (NS_X + "p", NS_X + "h") and (t := _odf_testo(el).strip())
    )




_FINE_CATENA, _LIBERO = 0xFFFFFFFE, 0xFFFFFFFF


class CFB:
    ""

    def __init__(self, dati: bytes):
        if dati[:8] != OLE_MAGIC:
            raise ValueError("not an OLE2 container")
        self.d = dati
        self.ss = 1 << struct.unpack_from("<H", dati, 0x1E)[0]
        self.mss = 1 << struct.unpack_from("<H", dati, 0x20)[0]
        if self.ss not in (512, 4096) or self.mss != 64:
            raise ValueError("invalid sectors")
        n_fat, prima_dir = struct.unpack_from("<II", dati, 0x2C)
        self.taglio = struct.unpack_from("<I", dati, 0x38)[0]
        prima_minifat, n_minifat, prima_difat, _ = struct.unpack_from("<IIII", dati, 0x3C)
        nsett = max(0, (len(dati) - self.ss) // self.ss)
        difat = list(struct.unpack_from("<109I", dati, 0x4C))
        s, giri = prima_difat, 0
        while s < nsett:
            valori = struct.unpack_from(f"<{self.ss // 4}I", dati, (s + 1) * self.ss)
            difat.extend(valori[:-1])
            s = valori[-1]
            giri += 1
            if giri > nsett:
                raise ValueError("DIFAT loop")
        fat: list[int] = []
        for fs in [x for x in difat if x < nsett][:n_fat]:
            fat.extend(struct.unpack_from(f"<{self.ss // 4}I", dati, (fs + 1) * self.ss))
        self.fat = fat
        cartella = self._catena(prima_dir)
        self.voci = []
        for i in range(len(cartella) // 128):
            e = cartella[i * 128 : (i + 1) * 128]
            lung = struct.unpack_from("<H", e, 0x40)[0]
            nome = e[: max(0, min(lung, 64) - 2)].decode("utf-16-le", "replace")
            tipo = e[0x42]
            sx, dx, figlio = struct.unpack_from("<III", e, 0x44)
            inizio = struct.unpack_from("<I", e, 0x74)[0]
            dim = struct.unpack_from("<Q", e, 0x78)[0]
            if self.ss == 512:
                dim &= 0xFFFFFFFF
            self.voci.append((nome, tipo, sx, dx, figlio, inizio, dim))
        if not self.voci:
            raise ValueError("container with no entries")
        radice = self.voci[0]
        self.ministream = self._catena(radice[5], radice[6]) if radice[6] else b""
        self.minifat: list[int] = []
        if n_minifat and prima_minifat < nsett:
            mf = self._catena(prima_minifat)
            self.minifat = list(struct.unpack_from(f"<{len(mf) // 4}I", mf, 0))
        self.percorsi: dict[str, int] = {}
        self._cammina(radice[4])

    def _catena(self, s: int, dim: int | None = None) -> bytes:
        fuori = bytearray()
        n = 0
        while s not in (_FINE_CATENA, _LIBERO) and s < len(self.fat):
            o = (s + 1) * self.ss
            fuori += self.d[o : o + self.ss]
            s = self.fat[s]
            n += 1
            if n > len(self.fat):
                raise ValueError("FAT loop")
            if dim is not None and len(fuori) >= dim:
                break
        return bytes(fuori[:dim] if dim is not None else fuori)

    def _mini(self, s: int, dim: int) -> bytes:
        fuori = bytearray()
        n = 0
        while s not in (_FINE_CATENA, _LIBERO) and s < len(self.minifat):
            o = s * self.mss
            fuori += self.ministream[o : o + self.mss]
            s = self.minifat[s]
            n += 1
            if n > len(self.minifat):
                raise ValueError("miniFAT loop")
            if len(fuori) >= dim:
                break
        return bytes(fuori[:dim])

    def _cammina(self, indice: int) -> None:
        pila, visti = [(indice, "")], set()
        while pila:
            i, prefisso = pila.pop()
            if i >= len(self.voci) or i in visti:
                continue
            visti.add(i)
            nome, tipo, sx, dx, figlio, _, _ = self.voci[i]
            pila += [(sx, prefisso), (dx, prefisso)]
            if tipo == 2:
                self.percorsi[prefisso + nome] = i
            elif tipo == 1:
                self.percorsi[prefisso + nome + "/"] = i
                pila.append((figlio, prefisso + nome + "/"))

    def stream(self, percorso: str) -> bytes | None:
        i = self.percorsi.get(percorso)
        if i is None:
            return None
        _, _, _, _, _, inizio, dim = self.voci[i]
        if dim > MAX_STREAM:
            raise ValueError("stream too large")
        return self._mini(inizio, dim) if dim < self.taglio else self._catena(inizio, dim)

    def tipo(self) -> str:

        nomi = {p.rstrip("/").split("/")[-1].lower() for p in self.percorsi}
        if nomi & {"encryptedpackage", "encryptioninfo", "encryptedsummary"}:
            return "cifrato"
        if "worddocument" in nomi:
            return "doc"
        if "workbook" in nomi or "book" in nomi:
            return "xls"
        if "powerpoint document" in nomi:
            return "ppt"
        if any(n.startswith("__substg1.0_") for n in nomi):
            return "msg"
        return "ole2"




_RTF_PREBUF = (
    b"{\\rtf1\\ansi\\mac\\deff0\\deftab720{\\fonttbl;}{\\f0\\fnil \\froman \\fswiss \\fmodern \\fscript "
    b"\\fdecor MS Sans SerifSymbolArialTimes New RomanCourier{\\colortbl\\red0\\green0\\blue0\r\n\\par "
    b"\\pard\\plain\\f0\\fs20\\b\\i\\u\\tab\\tx"
)


def rtf_decomprimi(dati: bytes) -> bytes:
    ""
    compresso, grezzo, magia, _ = struct.unpack_from("<IIII", dati, 0)
    if magia == 0x414C454D:
        return dati[16 : 16 + grezzo]
    if magia != 0x75465A4C:
        raise ValueError("unknown compressed RTF")
    diz = bytearray(4096)
    diz[: len(_RTF_PREBUF)] = _RTF_PREBUF
    w = len(_RTF_PREBUF)
    fuori = bytearray()
    i, fine = 16, min(len(dati), compresso + 4)
    while i < fine:
        flag = dati[i]
        i += 1
        for b in range(8):
            if i >= fine:
                break
            if flag & (1 << b):
                if i + 1 >= fine:
                    break
                ref = (dati[i] << 8) | dati[i + 1]
                i += 2
                pos, n = ref >> 4, (ref & 0xF) + 2
                if pos == w:
                    return bytes(fuori)
                for k in range(n):
                    c = diz[(pos + k) % 4096]
                    fuori.append(c)
                    diz[w] = c
                    w = (w + 1) % 4096
            else:
                c = dati[i]
                i += 1
                fuori.append(c)
                diz[w] = c
                w = (w + 1) % 4096
        if len(fuori) > MAX_STREAM:
            break
    return bytes(fuori)


def _msg_stringa(cfb: CFB, prefisso: str, tag: str) -> str:
    for tipo, codifica in (("001F", "utf-16-le"), ("001E", "cp1252")):
        b = cfb.stream(f"{prefisso}__substg1.0_{tag}{tipo}")
        if b is not None:
            return b.decode(codifica, "replace").rstrip("\x00").strip()
    return ""


def _msg(cfb: CFB, prefisso: str, profondita: int, max_caratteri: int) -> str:
    righe = []
    for etichetta, tag in (
        ("From", "0C1A"),
        ("Sender", "0C1F"),
        ("To", "0E04"),
        ("Cc", "0E03"),
        ("Subject", "0037"),
    ):
        if v := _msg_stringa(cfb, prefisso, tag):
            righe.append(f"{etichetta}: {v}")
    corpo = _msg_stringa(cfb, prefisso, "1000")
    if not corpo and (h := cfb.stream(f"{prefisso}__substg1.0_10130102")):
        corpo = _html(h)
    if not corpo and (r := cfb.stream(f"{prefisso}__substg1.0_10090102")):
        corpo = _textutil(rtf_decomprimi(r), "rtf")
    righe.append(corpo)
    allegati = sorted(
        p
        for p in cfb.percorsi
        if p.startswith(prefisso + "__attach_version1.0_#")
        and p.endswith("/")
        and p.count("/") == prefisso.count("/") + 1
    )
    for a in allegati:
        nome = _msg_stringa(cfb, a, "3707") or _msg_stringa(cfb, a, "3704") or "unnamed"
        righe.append(f"[Attachment] {nome}")
        if f"{a}__substg1.0_3701000D/" in cfb.percorsi and profondita < 3:
            righe.append(_msg(cfb, f"{a}__substg1.0_3701000D/", profondita + 1, max_caratteri))
        elif dati := cfb.stream(f"{a}__substg1.0_37010102"):
            righe.append(leggi_bytes(nome, dati, profondita + 1, max_caratteri).testo)
    return "\n".join(r for r in righe if r)




_OID_SIGNED_DATA = bytes.fromhex("2a864886f70d010702")


def _tlv(d: bytes, pos: int, fine: int, prof: int = 0):
    if prof > 64 or pos + 2 > fine:
        raise ValueError("DER truncated or too deep")
    tag = d[pos]
    costruito = bool(tag & 0x20)
    pos += 1
    if tag & 0x1F == 0x1F:
        while pos < fine and d[pos] & 0x80:
            pos += 1
        pos += 1
    lb = d[pos]
    pos += 1
    if lb == 0x80:
        if not costruito:
            raise ValueError("indefinite length on a primitive")
        p = pos
        while True:
            if p + 2 > fine:
                raise ValueError("missing end of content")
            if d[p] == 0 and d[p + 1] == 0:
                return tag, costruito, pos, p, p + 2
            p = _tlv(d, p, fine, prof + 1)[4]
    if lb & 0x80:
        n = lb & 0x7F
        if n > 8:
            raise ValueError("invalid length")
        lung = int.from_bytes(d[pos : pos + n], "big")
        pos += n
    else:
        lung = lb
    if pos + lung > fine:
        raise ValueError("length beyond file")
    return tag, costruito, pos, pos + lung, pos + lung


def _figli(d: bytes, a: int, b: int, prof: int = 0):
    p = a
    while p < b:
        if d[p] == 0 and p + 1 < b and d[p + 1] == 0:
            break
        t = _tlv(d, p, b, prof + 1)
        yield t
        p = t[4]


def _ottetti(d: bytes, t, prof: int = 0) -> bytes:
    _, costruito, a, b, _ = t
    if not costruito:
        return d[a:b]
    return b"".join(_ottetti(d, c, prof + 1) for c in _figli(d, a, b, prof))


def apri_busta(dati: bytes) -> bytes:
    ""

    s = dati.lstrip()
    if s[:2] == b"MI" and re.match(rb"^[A-Za-z0-9+/=\r\n]+$", s[:4096]):
        dati = base64.b64decode(s)
    elif s.startswith(b"-----BEGIN"):
        dati = base64.b64decode(
            b"".join(x for x in s.splitlines() if x and not x.startswith(b"-----"))
        )
    ci = _tlv(dati, 0, len(dati))
    figli = list(_figli(dati, ci[2], ci[3]))
    if len(figli) < 2 or dati[figli[0][2] : figli[0][3]] != _OID_SIGNED_DATA:
        raise ValueError("not a signed envelope")
    sd = next(_figli(dati, figli[1][2], figli[1][3]))
    eci = list(_figli(dati, *[x for x in list(_figli(dati, sd[2], sd[3]))[2][2:4]]))
    if len(eci) < 2:
        raise NonSupportato("detached signature, content is absent")
    return _ottetti(dati, next(_figli(dati, eci[1][2], eci[1][3])))


def _xml_schema(dati: bytes) -> str:
    ""

    radice = ET.fromstring(dati)
    righe: list[str] = []

    def nome(t) -> str:
        return t.rsplit("}", 1)[-1] if isinstance(t, str) else ""

    def giro(el: ET.Element, prof: int) -> None:
        n = nome(el.tag)
        rientro = "  " * prof
        if n == "Attachment":
            righe.append(
                f"{rientro}{n}: [base64 attachment, {len((el.text or '').strip())} characters]"
            )
            return
        if n == "Signature":
            righe.append(f"{rientro}[XML signature]")
            return
        t = (el.text or "").strip()
        if len(el) == 0:
            if t:
                righe.append(f"{rientro}{n}: {t}")
            return
        righe.append(f"{rientro}{n}")
        for c in el:
            giro(c, prof + 1)

    giro(radice, 0)
    return "\n".join(righe)





def _parte_testo(parte) -> str:
    try:
        c = parte.get_content()
    except Exception:  # noqa: BLE001 - a part with the wrong encoding: decode it by hand
        c = (parte.get_payload(decode=True) or b"").decode(
            parte.get_content_charset() or "utf-8", "replace"
        )
    if isinstance(c, bytes):
        c = c.decode("utf-8", "replace")
    return _html(c) if parte.get_content_type() == "text/html" else c


def _foglie(msg):
    ""
    coda = [msg]
    while coda:
        p = coda.pop(0)
        if p is not msg and p.get_content_type() == "message/rfc822":
            yield p
            continue
        if p.is_multipart():
            coda[0:0] = list(p.iter_parts())
            continue
        yield p


def _mail(msg, profondita: int, max_caratteri: int) -> str:
    righe = []
    for h in ("From", "To", "Cc", "Date", "Subject"):
        try:
            if v := msg.get(h):
                righe.append(f"{h}: {v}")
        except Exception:  # noqa: BLE001 - a broken header does not stop the mail
            continue
    try:
        corpo = msg.get_body(preferencelist=("plain", "html"))
    except Exception:  # noqa: BLE001
        corpo = None
    if corpo is None:
        corpo = next(
            (
                p
                for p in msg.walk()
                if p.get_content_type() in ("text/plain", "text/html") and not p.is_attachment()
            ),
            None,
        )
    if corpo is not None:
        righe.append(_parte_testo(corpo))
    for parte in _foglie(msg):
        if parte is corpo:
            continue
        ct = parte.get_content_type()
        nome = parte.get_filename() or ""
        if ct == "message/rfc822":
            righe.append(f"[Mail attachment] {nome}")
            if profondita < 3:
                interna = parte.get_payload()
                interna = interna[0] if isinstance(interna, list) and interna else interna
                if interna is not None and hasattr(interna, "walk"):
                    righe.append(_mail(interna, profondita + 1, max_caratteri))
            continue
        if ct in ("application/pkcs7-signature", "application/x-pkcs7-signature"):
            righe.append(f"[Signature] {nome}")
            continue
        if not (parte.is_attachment() or nome):
            continue
        dati = parte.get_payload(decode=True) or b""
        righe.append(f"[Attachment] {nome} ({ct}, {len(dati)} bytes)")

        if ct.startswith(("image/", "video/", "audio/")):
            continue
        righe.append(leggi_bytes(nome, dati, profondita + 1, max_caratteri).testo)
    return "\n".join(r for r in righe if r)





def _leggi(nome: str, dati: bytes, profondita: int, max_caratteri: int) -> tuple[str, str, str]:
    ""
    if profondita > 3:
        raise NonSupportato("too deeply nested")
    base = riconosci(dati[:64], nome)
    if base == "pdf":
        testo, lettore = _pdf(dati, max_caratteri)
        return testo, "pdf", lettore
    if base == "zip":
        with zipfile.ZipFile(io.BytesIO(dati)) as z:
            sapore = _sapore_zip(z)
            if sapore == "pptx":
                return _pptx(z, max_caratteri), "pptx", "stdlib"
            if sapore == "ods":
                return _ods(z, max_caratteri), "ods", "stdlib"
            if sapore == "odt":
                return _odt(z), "odt", "stdlib"
        if sapore == "docx":


            return _textutil(dati, "docx"), "docx", "textutil"
        if sapore == "xlsx":
            return _xlsx(dati, max_caratteri), "xlsx", "openpyxl"
        raise NonSupportato(f"archive {sapore}")
    if base == "ole2":
        cfb = CFB(dati)
        tipo = cfb.tipo()
        if tipo == "cifrato":
            raise PermissionError("password protected")
        if tipo == "doc":
            return _textutil(dati, "doc"), "doc", "textutil"
        if tipo == "xls":
            return _xls(dati, max_caratteri), "xls", "xlrd"
        if tipo == "ppt":
            return _mdimport(dati, ".ppt"), "ppt", "mdimport"
        if tipo == "msg":
            return _msg(cfb, "", profondita, max_caratteri), "msg", "stdlib"
        raise NonSupportato(f"ole2 {tipo}")
    if base == "rtf":
        return _textutil(dati, "rtf"), "rtf", "textutil"
    if base in ("der", "b64"):
        interno = apri_busta(dati)

        for _ in range(4):
            if riconosci(interno[:64]) not in ("der", "b64"):
                break
            interno = apri_busta(interno)

        nome_interno = nome
        while nome_interno.lower().endswith((".p7m", ".p7s")):
            nome_interno = nome_interno[:-4]
        testo, tipo_interno, lettore = _leggi(nome_interno, interno, profondita + 1, max_caratteri)
        return testo, "p7m", f"busta+{tipo_interno}:{lettore}"
    if base == "eml":
        msg = email.message_from_bytes(dati, policy=email.policy.default)
        return _mail(msg, profondita, max_caratteri), "eml", "stdlib"
    if base == "xml":
        try:
            return _xml_schema(dati), "xml", "stdlib"
        except ET.ParseError:
            return dati.decode("utf-8", "replace"), "xml", "grezzo"
    if base == "html":
        return _html(dati), "html", "bs4"
    estensione = nome.lower().rsplit(".", 1)[-1] if "." in nome else ""
    if estensione in ("txt", "csv", "md", "ics", "json", "tsv", "log", "") or not estensione:
        return dati.decode("utf-8", "replace"), "testo", "utf8"
    raise NonSupportato(f"type not read: {estensione}")


def leggi_bytes(
    nome: str, dati: bytes, profondita: int = 0, max_caratteri: int = MAX_CHARS
) -> Lettura:
    ""
    t0 = time.time()
    tipo = lettore = ""
    try:
        testo, tipo, lettore = _leggi(nome, dati, profondita, max_caratteri)
        testo = _taglia(testo or "", max_caratteri)
        esito = "letto" if testo else "vuoto"
        return Lettura(testo, tipo, lettore, esito, time.time() - t0)
    except PermissionError as e:
        return Lettura("", tipo or "cifrato", lettore, "protetto", time.time() - t0, str(e))
    except NonSupportato as e:
        return Lettura("", tipo, lettore, "non_supportato", time.time() - t0, str(e))
    except subprocess.TimeoutExpired:
        return Lettura("", tipo, lettore, "errore", time.time() - t0, f"time exceeded {TIMEOUT_S} s")
    except Exception as e:  # noqa: BLE001 - a broken file does not stop reading: it is counted with the reason
        return Lettura(
            "", tipo, lettore, "errore", time.time() - t0, f"{type(e).__name__}: {str(e)[:160]}"
        )


def leggi(percorso: Path, max_caratteri: int = MAX_CHARS) -> Lettura:
    ""
    percorso = Path(percorso)
    try:
        dati = percorso.read_bytes()
    except OSError as e:
        return Lettura("", "", "", "errore", 0.0, f"cannot open: {e}")
    return leggi_bytes(percorso.name, dati, 0, max_caratteri)
