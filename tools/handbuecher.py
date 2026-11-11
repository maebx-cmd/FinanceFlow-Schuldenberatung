"""Anleitung (Schuldner) und Handbuch (Schuldenberatung) aus docs/*.md als PDF in den Ordner hilfe/ erzeugen.

Aufruf:  python tools/handbuecher.py
Optik wie die PDF-Berichte des Programms (Helvetica, Akzentblau #0A6ED1, A4). Unterstützt das Markdown, das in den
beiden Dateien vorkommt: # / ## / ###, Absätze, Listen (- / 1.), Tabellen, > Hinweis, ![Bildtext](bild.png),
**fett** und `Code`. Die Anleitung für Schuldner wird in größerer Schrift gesetzt (leichter lesbar).
"""
from __future__ import annotations

import os
import re
import sys
from datetime import date

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (Image, KeepTogether, ListFlowable, ListItem, PageBreak, Paragraph, Spacer, Table,
                                TableStyle)
from reportlab.platypus.doctemplate import BaseDocTemplate, Frame, PageTemplate
from reportlab.platypus.tableofcontents import TableOfContents

BASIS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASIS)
from app import APP_VERSION  # noqa: E402

BLAU = colors.HexColor("#0A6ED1")
DUNKEL = colors.HexColor("#32363A")
GRAU = colors.HexColor("#6A6D70")
LINIE = colors.HexColor("#D9D9D9")
HELL = colors.HexColor("#F5F6F7")
HINWEIS = colors.HexColor("#EAF3FC")

DOKUMENTE = [
    ("ANLEITUNG-SCHULDNER.md", "FinanceFlow-Anleitung-Schuldner.pdf", "Anleitung für Schuldnerinnen und Schuldner", 11.0, False),
    ("HANDBUCH-SCHULDENBERATUNG.md", "FinanceFlow-Handbuch-Schuldenberatung.pdf", "Handbuch für die Schuldenberatung", 9.2, True),
]


def stile(gr: float) -> dict:
    return {
        "titel": ParagraphStyle("titel", fontName="Helvetica-Bold", fontSize=24, leading=30, textColor=DUNKEL, spaceAfter=6),
        "untertitel": ParagraphStyle("ut", fontName="Helvetica", fontSize=13, leading=18, textColor=GRAU),
        "h1": ParagraphStyle("h1", fontName="Helvetica-Bold", fontSize=gr + 6, leading=gr + 10, textColor=BLAU,
                             spaceBefore=6, spaceAfter=8, keepWithNext=1),
        "h2": ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=gr + 2.5, leading=gr + 6, textColor=DUNKEL,
                             spaceBefore=10, spaceAfter=5, keepWithNext=1),
        "p": ParagraphStyle("p", fontName="Helvetica", fontSize=gr, leading=gr * 1.42, textColor=DUNKEL, spaceAfter=gr * 0.55),
        "li": ParagraphStyle("li", fontName="Helvetica", fontSize=gr, leading=gr * 1.38, textColor=DUNKEL),
        "zelle": ParagraphStyle("z", fontName="Helvetica", fontSize=gr - 1.2, leading=(gr - 1.2) * 1.3, textColor=DUNKEL),
        "kopf": ParagraphStyle("k", fontName="Helvetica-Bold", fontSize=gr - 1.4, leading=(gr - 1.4) * 1.3, textColor=GRAU),
        "bild": ParagraphStyle("b", fontName="Helvetica-Oblique", fontSize=gr - 1.5, leading=gr, textColor=GRAU,
                               alignment=TA_CENTER, spaceAfter=gr),
        "toc1": ParagraphStyle("toc1", fontName="Helvetica", fontSize=gr, leading=gr * 1.6, textColor=DUNKEL),
    }


def inline(t: str) -> str:
    t = t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    t = re.sub(r"`([^`]+)`", r'<font name="Courier" color="#1D2D3E">\1</font>', t)
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    return t.replace("▾", "").replace("‹", "&lt;").replace("…", "...")


class Dokument(BaseDocTemplate):
    def __init__(self, pfad, titel, mit_toc):
        super().__init__(pfad, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm, topMargin=22 * mm, bottomMargin=18 * mm,
                         title=f"FinanceFlow Schuldenberatung – {titel}", author="FinanceFlow", subject=titel)
        self.kurz = titel
        rahmen = Frame(self.leftMargin, self.bottomMargin, self.width, self.height, id="f")
        self.addPageTemplates([PageTemplate("titel", [rahmen], onPage=self._titelseite),
                               PageTemplate("inhalt", [rahmen], onPage=self._seite)])
        self.mit_toc = mit_toc

    def _seite(self, c, doc):
        c.saveState()
        c.setStrokeColor(BLAU)
        c.setLineWidth(1.2)
        c.line(20 * mm, A4[1] - 15 * mm, A4[0] - 20 * mm, A4[1] - 15 * mm)
        c.setFont("Helvetica-Bold", 8.5)
        c.setFillColor(DUNKEL)
        c.drawString(20 * mm, A4[1] - 13 * mm, "FinanceFlow Schuldenberatung")
        c.setFont("Helvetica", 8.5)
        c.setFillColor(GRAU)
        c.drawRightString(A4[0] - 20 * mm, A4[1] - 13 * mm, self.kurz)
        c.setFont("Helvetica", 7)
        c.drawString(20 * mm, 10 * mm, f"Version {APP_VERSION} · Stand {date.today():%m/%Y}")
        c.drawRightString(A4[0] - 20 * mm, 10 * mm, f"Seite {doc.page}")
        c.restoreState()

    def _titelseite(self, c, doc):
        c.saveState()
        x, y, r = 20 * mm + 14, A4[1] - 40 * mm, 14
        c.setFillColor(colors.HexColor("#0064D9"))
        p = c.beginPath()
        p.moveTo(x, y + r)
        p.lineTo(x + r, y)
        p.lineTo(x, y - r)
        p.lineTo(x - r, y)
        p.close()
        c.drawPath(p, fill=1, stroke=0)
        c.setFillColor(DUNKEL)
        c.setFont("Helvetica-Bold", 20)
        c.drawString(20 * mm + 36, y - 7, "FinanceFlow")
        c.setFont("Helvetica", 12)
        c.setFillColor(GRAU)
        c.drawString(20 * mm + 36 + c.stringWidth("FinanceFlow", "Helvetica-Bold", 20) + 8, y - 6, "Schuldenberatung")
        c.setFont("Helvetica", 8)
        c.drawString(20 * mm, 12 * mm, f"Version {APP_VERSION} · Stand {date.today():%d.%m.%Y}")
        c.restoreState()

    def afterFlowable(self, f):
        if isinstance(f, Paragraph) and f.style.name == "h1" and getattr(f, "_toc", False):
            self.notify("TOCEntry", (0, f.getPlainText(), self.page))


def bild(pfad, text, st, breite):
    from reportlab.lib.utils import ImageReader
    w, h = ImageReader(pfad).getSize()
    b = min(breite, w * 0.75)
    hoehe = b * h / w
    if hoehe > 120 * mm:
        hoehe = 120 * mm
        b = hoehe * w / h
    img = Image(pfad, width=b, height=hoehe)
    rahmen = Table([[img]], colWidths=[b + 2])
    rahmen.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.6, LINIE), ("LEFTPADDING", (0, 0), (-1, -1), 1),
                                ("RIGHTPADDING", (0, 0), (-1, -1), 1), ("TOPPADDING", (0, 0), (-1, -1), 1),
                                ("BOTTOMPADDING", (0, 0), (-1, -1), 1)]))
    return KeepTogether([Spacer(1, 4), rahmen, Spacer(1, 3), Paragraph(inline(text), st["bild"])])


def tabelle(zeilen, st, breite):
    kopf = [c.strip() for c in zeilen[0].strip().strip("|").split("|")]
    daten = [[c.strip() for c in z.strip().strip("|").split("|")] for z in zeilen[2:]]
    n = len(kopf)
    laengen = [max(len(r[i]) if i < len(r) else 0 for r in [kopf] + daten) for i in range(n)]
    gesamt = sum(min(x, 60) + 8 for x in laengen)
    breiten = [breite * (min(x, 60) + 8) / gesamt for x in laengen]
    rows = [[Paragraph(inline(c), st["kopf"]) for c in kopf]]
    rows += [[Paragraph(inline(r[i] if i < len(r) else ""), st["zelle"]) for i in range(n)] for r in daten]
    t = Table(rows, colWidths=breiten, repeatRows=1)
    t.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, 0), 0.8, GRAU), ("LINEBELOW", (0, 1), (-1, -1), 0.25, LINIE),
                           ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 3),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 4), ("LEFTPADDING", (0, 0), (-1, -1), 3),
                           ("BACKGROUND", (0, 0), (-1, 0), HELL)]))
    return [Spacer(1, 3), t, Spacer(1, 8)]


def hinweis(text, st, breite):
    p = Paragraph(inline(text), ParagraphStyle("hw", parent=st["p"], spaceAfter=0))
    t = Table([[p]], colWidths=[breite])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), HINWEIS), ("LINEBEFORE", (0, 0), (0, -1), 3, BLAU),
                           ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                           ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7)]))
    return [Spacer(1, 2), t, Spacer(1, 8)]


def liste(punkte, nummeriert, st):
    items = [ListItem(Paragraph(inline(p), st["li"]), leftIndent=14) for p in punkte]
    kw = dict(bulletType="1", bulletFormat="%s.") if nummeriert else dict(bulletType="bullet", start="•")
    return [ListFlowable(items, leftIndent=14, bulletFontName="Helvetica-Bold" if nummeriert else "Helvetica",
                         bulletFontSize=st["li"].fontSize, bulletColor=BLAU, spaceBefore=0, spaceAfter=6, **kw)]


def bauen(md_name, pdf_name, kurz, gr, mit_toc):
    st = stile(gr)
    md = open(os.path.join(BASIS, "docs", md_name), encoding="utf-8").read().splitlines()
    ziel = os.path.join(BASIS, "hilfe", pdf_name)
    os.makedirs(os.path.dirname(ziel), exist_ok=True)
    doc = Dokument(ziel, kurz, mit_toc)
    breite = doc.width
    story = []
    i = 0
    titel = md[0].lstrip("# ").strip()
    i = 1
    story += [Spacer(1, 45 * mm), Paragraph(inline(titel.split("–")[-1].strip()), st["titel"]),
              Paragraph(f"FinanceFlow Schuldenberatung · Version {APP_VERSION}", st["untertitel"]), Spacer(1, 14 * mm)]
    # Vorspann (Absätze bis zur ersten Überschrift) auf die Titelseite
    vorspann = []
    while i < len(md) and not md[i].startswith("## "):
        if md[i].strip():
            vorspann.append(md[i].strip())
        i += 1
    for v in vorspann:
        story.append(Paragraph(inline(v), ParagraphStyle("vs", parent=st["p"], fontSize=gr + 1, leading=(gr + 1) * 1.45)))
    if mit_toc:
        from reportlab.platypus import NextPageTemplate
        story += [NextPageTemplate("inhalt"), PageBreak(), Paragraph("Inhalt", st["h1"])]
        toc = TableOfContents()
        toc.levelStyles = [st["toc1"]]
        toc.dotsMinLevel = 0
        story.append(toc)
        story.append(PageBreak())
    else:
        from reportlab.platypus import NextPageTemplate
        story += [NextPageTemplate("inhalt"), PageBreak()]
    erste = True
    while i < len(md):
        z = md[i]
        s = z.strip()
        if not s:
            i += 1
            continue
        if s.startswith("## "):
            if not erste and not mit_toc:
                story.append(Spacer(1, 6))
            p = Paragraph(inline(s[3:]), st["h1"])
            p._toc = True
            if mit_toc and not erste:
                story.append(PageBreak())
            story.append(p)
            erste = False
            i += 1
        elif s.startswith("### "):
            story.append(Paragraph(inline(s[4:]), st["h2"]))
            i += 1
        elif s.startswith("!["):
            m = re.match(r"!\[(.*)\]\((.+)\)", s)
            story.append(bild(os.path.join(BASIS, "docs", m.group(2)), m.group(1), st, breite))
            i += 1
        elif s.startswith("|"):
            zeilen = []
            while i < len(md) and md[i].strip().startswith("|"):
                zeilen.append(md[i])
                i += 1
            story += tabelle(zeilen, st, breite)
        elif s.startswith("> "):
            text = []
            while i < len(md) and md[i].strip().startswith(">"):
                text.append(md[i].strip()[1:].strip())
                i += 1
            story += hinweis(" ".join(text), st, breite)
        elif re.match(r"^(- |\d+\. )", s):
            num = bool(re.match(r"^\d+\. ", s))
            punkte = []
            while i < len(md) and re.match(r"^(- |\d+\. )", md[i].strip()):
                punkte.append(re.sub(r"^(- |\d+\. )", "", md[i].strip()))
                i += 1
            story += liste(punkte, num, st)
        else:
            text = [s]
            i += 1
            while i < len(md) and md[i].strip() and not re.match(r"^(#|!\[|\||> |- |\d+\. )", md[i].strip()):
                text.append(md[i].strip())
                i += 1
            story.append(Paragraph(inline(" ".join(text)), st["p"]))
    if mit_toc:
        doc.multiBuild(story)
    else:
        doc.build(story)
    return ziel


if __name__ == "__main__":
    for d in DOKUMENTE:
        p = bauen(*d)
        print(f"{p}  ({os.path.getsize(p) // 1024} KB)")
