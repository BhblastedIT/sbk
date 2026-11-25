#!/usr/bin/env python3
"""Turn a Markdown dossier into a PDF.

Usage: uv run python tools/util/gen-dossier-pdf.py <input.md> [output.pdf]  (default output: dossier.pdf)
Needs the optional reportlab package: `uv add reportlab`.
"""

import re
import sys
from pathlib import Path

_TOOLS = Path(__file__).resolve().parents[1]
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

if __name__ == "__main__" and (len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help")):
    print(__doc__)
    sys.exit(0 if len(sys.argv) > 1 else 2)

try:
    from reportlab.lib.colors import HexColor
    from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import (
        HRFlowable,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )
except ImportError:  # optional dependency, not installed by default
    sys.exit("gen-dossier-pdf needs reportlab, which is optional: run `uv add reportlab` first.")

from sbk_config import OWNER_NAME  # noqa: E402

INPUT = Path(sys.argv[1]) if len(sys.argv) > 1 else None
OUTPUT = Path(
    sys.argv[2]
    if len(sys.argv) > 2
    else "dossier.pdf"
)

text_primary = HexColor("#18181B")
text_secondary = HexColor("#52525B")
text_muted = HexColor("#71717A")
accent = HexColor("#18181B")
line_color = HexColor("#E4E4E7")
bg_zebra = HexColor("#FAFAFA")
bg_header = HexColor("#F4F4F5")

styles = {
    "title": ParagraphStyle(
        "title",
        fontName="Helvetica-Bold",
        fontSize=18,
        leading=23,
        alignment=TA_CENTER,
        textColor=text_primary,
        spaceAfter=4,
    ),
    "subtitle": ParagraphStyle(
        "subtitle",
        fontName="Helvetica",
        fontSize=11,
        leading=15,
        alignment=TA_CENTER,
        textColor=text_secondary,
        spaceAfter=18,
    ),
    "h1": ParagraphStyle(
        "h1",
        fontName="Helvetica-Bold",
        fontSize=14,
        leading=18,
        textColor=text_primary,
        spaceBefore=14,
        spaceAfter=8,
    ),
    "h2": ParagraphStyle(
        "h2",
        fontName="Helvetica-Bold",
        fontSize=11,
        leading=15,
        textColor=text_primary,
        spaceBefore=10,
        spaceAfter=4,
    ),
    "h3": ParagraphStyle(
        "h3",
        fontName="Helvetica-Bold",
        fontSize=10,
        leading=14,
        textColor=text_secondary,
        spaceBefore=8,
        spaceAfter=3,
    ),
    "body": ParagraphStyle(
        "body",
        fontName="Helvetica",
        fontSize=9.5,
        leading=13.5,
        alignment=TA_JUSTIFY,
        textColor=text_primary,
        spaceAfter=6,
    ),
    "list": ParagraphStyle(
        "list",
        fontName="Helvetica",
        fontSize=9.5,
        leading=13.5,
        textColor=text_primary,
        leftIndent=14,
        bulletIndent=4,
        spaceAfter=2,
    ),
    "meta": ParagraphStyle(
        "meta",
        fontName="Helvetica",
        fontSize=9,
        leading=12,
        textColor=text_muted,
        alignment=TA_LEFT,
        spaceAfter=2,
    ),
    "tableCell": ParagraphStyle(
        "tableCell",
        fontName="Helvetica",
        fontSize=8.5,
        leading=11,
        textColor=text_primary,
        alignment=TA_LEFT,
    ),
    "tableCellBold": ParagraphStyle(
        "tableCellBold",
        fontName="Helvetica-Bold",
        fontSize=8.5,
        leading=11,
        textColor=text_primary,
        alignment=TA_LEFT,
    ),
    "tableHeader": ParagraphStyle(
        "tableHeader",
        fontName="Helvetica-Bold",
        fontSize=8.5,
        leading=11,
        textColor=text_primary,
        alignment=TA_LEFT,
    ),
    "footer": ParagraphStyle(
        "footer",
        fontName="Helvetica",
        fontSize=8,
        leading=10,
        textColor=text_muted,
        alignment=TA_CENTER,
    ),
}


def convert_inline(text: str) -> str:
    ""

    text = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", text)

    text = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<i>\1</i>", text)

    text = re.sub(r"`([^`]+)`", r"<font name='Courier' size='8'>\1</font>", text)

    text = re.sub(
        r"\[([^\]]+)\]\(([^)]+)\)",
        r"\1 <font color='#52525B'>(\2)</font>",
        text,
    )

    return text


def parse_table(lines: list[str], idx: int) -> tuple[Table, int]:
    ""
    header_line = lines[idx]
    sep_line = lines[idx + 1]
    if not re.match(r"^\s*\|[-: |]+\|\s*$", sep_line):
        return None, idx
    headers = [c.strip() for c in header_line.strip().strip("|").split("|")]
    rows = []
    j = idx + 2
    while j < len(lines) and lines[j].strip().startswith("|"):
        cells = [c.strip() for c in lines[j].strip().strip("|").split("|")]
        if len(cells) == len(headers):
            rows.append(cells)
        j += 1

    data = [[Paragraph(convert_inline(h), styles["tableHeader"]) for h in headers]]
    for r in rows:
        data.append([Paragraph(convert_inline(c), styles["tableCell"]) for c in r])

    avail = A4[0] - 2 * 50
    n = len(headers)
    if n <= 2:
        widths = [avail * 0.35, avail * 0.65]
    elif n == 3:
        widths = [avail * 0.25, avail * 0.5, avail * 0.25]
    elif n == 4:
        widths = [avail * 0.22, avail * 0.36, avail * 0.18, avail * 0.24]
    elif n == 5:
        widths = [avail * 0.06, avail * 0.32, avail * 0.27, avail * 0.13, avail * 0.22]
    else:
        widths = [avail / n] * n
    table = Table(data, colWidths=widths, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), bg_header),
                ("TEXTCOLOR", (0, 0), (-1, 0), text_primary),
                ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LINEABOVE", (0, 0), (-1, 0), 0.6, line_color),
                ("LINEBELOW", (0, 0), (-1, 0), 0.6, line_color),
                ("LINEBELOW", (0, -1), (-1, -1), 0.6, line_color),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [None, bg_zebra]),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return table, j


def parse_markdown(md: str) -> list:
    ""
    flowables = []

    md = re.sub(r"^---\s*\n.*?\n---\s*\n", "", md, count=1, flags=re.DOTALL)
    lines = md.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            i += 1
            continue

        if stripped == "---":
            flowables.append(Spacer(1, 4))
            flowables.append(
                HRFlowable(
                    width="100%", thickness=0.6, color=line_color, spaceBefore=2, spaceAfter=8
                )
            )
            i += 1
            continue

        if stripped.startswith("# "):
            flowables.append(Paragraph(convert_inline(stripped[2:]), styles["title"]))
            i += 1
            continue
        if stripped.startswith("## "):
            flowables.append(Paragraph(convert_inline(stripped[3:]), styles["h1"]))
            i += 1
            continue
        if stripped.startswith("### "):
            flowables.append(Paragraph(convert_inline(stripped[4:]), styles["h2"]))
            i += 1
            continue
        if stripped.startswith("#### "):
            flowables.append(Paragraph(convert_inline(stripped[5:]), styles["h3"]))
            i += 1
            continue

        if (
            stripped.startswith("|")
            and i + 1 < len(lines)
            and re.match(r"^\s*\|[-: |]+\|\s*$", lines[i + 1])
        ):
            table, next_idx = parse_table(lines, i)
            if table is not None:
                flowables.append(Spacer(1, 4))
                flowables.append(table)
                flowables.append(Spacer(1, 6))
                i = next_idx
                continue

        m = re.match(r"^\s*(\d+)\.\s+(.*)", line)
        if m:
            num, content = m.group(1), m.group(2)
            flowables.append(Paragraph(f"<b>{num}.</b> {convert_inline(content)}", styles["list"]))
            i += 1
            continue

        if stripped.startswith("- ") or stripped.startswith("* "):
            content = stripped[2:]
            flowables.append(Paragraph(f"• {convert_inline(content)}", styles["list"]))
            i += 1
            continue

        para_lines = [stripped]
        i += 1
        while (
            i < len(lines)
            and lines[i].strip()
            and not lines[i].strip().startswith(("#", "|", "- ", "* ", "---"))
            and not re.match(r"^\s*\d+\.\s+", lines[i])
        ):
            para_lines.append(lines[i].strip())
            i += 1
        para_text = " ".join(para_lines)
        flowables.append(Paragraph(convert_inline(para_text), styles["body"]))
    return flowables


def main():
    if INPUT is None or INPUT.name in ("-h", "--help"):
        sys.exit("usage: gen-dossier-pdf.py <input.md> [output.pdf]")
    if not INPUT.exists():
        sys.exit(f"Input not found: {INPUT}")
    md = INPUT.read_text(encoding="utf-8")
    flowables = parse_markdown(md)
    doc = SimpleDocTemplate(
        str(OUTPUT),
        pagesize=A4,
        leftMargin=50,
        rightMargin=50,
        topMargin=50,
        bottomMargin=42,
        title="Dossier",
        author=OWNER_NAME,
    )

    def on_page(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(text_muted)
        canvas.drawCentredString(A4[0] / 2, 24, f"Page {doc.page} — confidential")
        canvas.restoreState()

    doc.build(flowables, onFirstPage=on_page, onLaterPages=on_page)
    print(f"PDF written: {OUTPUT}")


if __name__ == "__main__":
    main()
