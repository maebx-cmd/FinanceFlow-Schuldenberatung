"""PDF-Grundgerüst (ReportLab) – Optik 1:1 wie Lohnverrechnung und Buchhaltung.

Vermessen an deren PDFs (Kontoblatt, Bilanz/GuV, Lohnzettel, Abgabenübersicht, Lohnjournal):
Helvetica; Kopf links Name fett + Adresse 8,5 pt, rechts Titel 13 pt fett + Untertitel 8,5 pt grau,
Akzentlinie 1,2 pt #0A6ED1; Abschnittstitel 9,5 pt fett blau; Tabellen 8,3 pt, Kopf fett grau mit Linie 0,8,
Zeilenlinien 0,25 #D9D9D9, Zeilenhöhe 15 pt; Summenzeile fett auf #F5F6F7, Endsumme auf #EBF5EB;
Infokasten #F5F6F7 mit Rahmen 0,4; Beträge ohne Währungszeichen (1.234,56), schwarz;
Fußzeile 7 pt grau „Erstellt am TT.MM.JJJJ HH:MM“ links, „Seite n“ rechts; A4, Ränder 15 mm.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT  # noqa: F401
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

FONT, FONT_B = "Helvetica", "Helvetica-Bold"

BLAU = colors.HexColor("#0A6ED1")
DUNKEL = colors.HexColor("#32363A")
GRAU = colors.HexColor("#6A6D70")
LINIE = colors.HexColor("#D9D9D9")
HELL = colors.HexColor("#F5F6F7")
GRUEN = colors.HexColor("#EBF5EB")
# Wie in Lohnverrechnung/Buchhaltung: Beträge nicht eingefärbt (Töne aus den Web-Reports neutralisiert)
TONE = {"red": DUNKEL, "green": DUNKEL, "gray": GRAU, "amber": DUNKEL, None: DUNKEL}

FS = 8.3
ST_CELL = ParagraphStyle("cell", fontName=FONT, fontSize=FS, leading=10, textColor=DUNKEL)
ST_NUM = ParagraphStyle("num", parent=ST_CELL, alignment=TA_RIGHT)
ST_HEAD = ParagraphStyle("head", parent=ST_CELL, fontName=FONT_B, fontSize=7.8, textColor=GRAU)
ST_HEAD_R = ParagraphStyle("headr", parent=ST_HEAD, alignment=TA_RIGHT)
ST_SECTION = ParagraphStyle("sec", fontName=FONT_B, fontSize=9.5, leading=12, textColor=BLAU, spaceBefore=8, spaceAfter=5)
ST_SMALL = ParagraphStyle("small", fontName=FONT, fontSize=7.5, leading=9.5, textColor=GRAU)
ST_TEXT = ParagraphStyle("text", fontName=FONT, fontSize=8.5, leading=11, textColor=DUNKEL)
ST_LAB = ParagraphStyle("lab", fontName=FONT, fontSize=7.6, leading=11.1, textColor=GRAU)
ST_VAL = ParagraphStyle("val", fontName=FONT_B, fontSize=8.3, leading=11.1, textColor=DUNKEL, alignment=TA_RIGHT)


def eur(v) -> str:
    """Betrag wie in Lohnverrechnung/Buchhaltung: '1.234,56' bzw. '-1.234,56' (ohne Währungszeichen)."""
    if v is None or v == "":
        return "0,00"
    try:
        x = Decimal(str(v)).quantize(Decimal("0.01"))
    except Exception:
        return "0,00"
    s = f"{abs(x):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"-{s}" if x < 0 else s


def eurw(v) -> str:
    """Betrag mit Währung für Fließtext und Infokasten: '1.234,56 €'."""
    return f"{eur(v)} €"


def pct(v) -> str:
    if not v:
        return "0,00 %"
    return f"{Decimal(str(v)) * 100:.2f}".replace(".", ",") + " %"


def datum(v) -> str:
    if not v:
        return "–"
    s = str(v)[:10]
    return f"{s[8:10]}.{s[5:7]}.{s[0:4]}"


_ERSATZ = {"⚠": "(!)", "⚖": "§", "↳": "›", "✓": "+", "✗": "x", "−": "-", "→": "->", "←": "<-", "≤": "<=",
           "≥": ">=", "✈": "", "…": "...", "\u202f": " ", "\u2009": " "}


def esc(s) -> str:
    t = ("" if s is None else str(s))
    for a, b in _ERSATZ.items():
        t = t.replace(a, b)
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class Cell:
    def __init__(self, text, tone=None, bold=False, num=False, klein=None):
        self.text, self.tone, self.bold, self.num, self.klein = text, tone, bold, num, klein


def C(text, tone=None, bold=False, klein=None):
    return Cell(text, tone, bold, klein=klein)


def N(text, tone=None, bold=False, klein=None):
    """klein: zweite, kleine graue Zeile in der Zelle (z. B. „letzte 59,45“)."""
    return Cell(text, tone, bold, num=True, klein=klein)


class Report:
    def __init__(self, titel: str, inhaber: str = "", untertitel: str = "", quer: bool = False, adresse=None):
        self.titel, self.inhaber, self.untertitel, self.quer = titel, inhaber, untertitel, quer
        self.adresse = [a for a in (adresse or []) if a]
        self.story = []
        self.size = landscape(A4) if quer else A4
        self.width = self.size[0] - 30 * mm

    # Bausteine
    def kopf(self):
        """Links Name fett + Adresszeilen (8,5 pt), rechts Titel 13 pt fett + Untertitel grau; Linie 1,2 pt blau."""
        zeilen = [f"<b>{esc(self.inhaber)}</b>"] + [esc(a) for a in self.adresse]
        left = Paragraph("<br/>".join(zeilen), ParagraphStyle("k", fontName=FONT, fontSize=8.5, leading=11, textColor=DUNKEL))
        right = [Paragraph(esc(self.titel), ParagraphStyle("t", fontName=FONT_B, fontSize=13, leading=15,
                                                           alignment=TA_RIGHT, textColor=DUNKEL))]
        if self.untertitel:
            right.append(Paragraph(esc(self.untertitel), ParagraphStyle("tu", fontName=FONT, fontSize=8.5, leading=11, spaceBefore=1,
                                                                       alignment=TA_RIGHT, textColor=GRAU)))
        t = Table([[left, right]], colWidths=[self.width * 0.42, self.width * 0.58])
        t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, 0), 1.2, BLAU),
                               ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                               ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
        self.story += [t, Spacer(1, 9)]

    def kpis(self, items, spalten=2):
        """Kennzahlen als Infokasten wie „Bemessungsgrundlagen“ im Lohnzettel:
        hellgrau, Rahmen 0,4; je Zeile `spalten` Paare aus Bezeichnung (grau) und Wert (fett, rechtsbündig)."""
        items = [i for i in items if i]
        if not items:
            return
        paare = [(Paragraph(esc(lab), ST_LAB), Paragraph(esc(val), ST_VAL)) for lab, val, *_ in items]
        spalten = min(spalten, len(paare))
        rows = []
        for k in range(0, len(paare), spalten):
            row = []
            for a, b in paare[k:k + spalten]:
                row += [a, b, ""]
            row += ["", "", ""] * (spalten - len(paare[k:k + spalten]))
            rows.append(row[:-1])
        teil = self.width / spalten
        cw = []
        for n in range(spalten):
            cw += [teil * 0.58, teil * 0.34] + ([teil * 0.08] if n < spalten - 1 else [])
        cw[-1] += teil * 0.08
        t = Table(rows, colWidths=cw)
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), HELL), ("BOX", (0, 0), (-1, -1), 0.4, LINIE),
                               ("VALIGN", (0, 0), (-1, -1), "TOP"),
                               ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                               ("TOPPADDING", (0, 0), (-1, 0), 6), ("BOTTOMPADDING", (0, -1), (-1, -1), 6),
                               ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8)]))
        self.story += [t, Spacer(1, 10)]

    def text(self, html, klein=True):
        self.story.append(Paragraph(html, ST_SMALL if klein else ST_TEXT))
        self.story.append(Spacer(1, 4))

    def box(self, titel, zeilen):
        """Adressblock wie im Lohnzettel: Überschrift grau klein, Zeilen fett 8,5 pt."""
        p = Paragraph(f"<font size='7.5' color='#6A6D70'>{esc(titel)}</font><br/>" +
                      "<br/>".join(f"<b>{z}</b>" if k == 0 else z for k, z in enumerate(zeilen)), ST_TEXT)
        t = Table([[p]], colWidths=[self.width * 0.55])
        t.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 0),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
        t.hAlign = "LEFT"
        self.story += [t, Spacer(1, 10)]

    def abschnitt(self, text):
        self.story.append(Paragraph(esc(text), ST_SECTION))

    def tabelle(self, kopf, zeilen, breiten=None, fuss=None, gesamt=None, zebra_rows=None, keep=False, kopf_ohne=False):
        """kopf: Liste Spaltentitel (Präfix '>' = rechtsbündig). zeilen: Listen aus str|Cell.
        fuss: Summenzeile (fett auf Hellgrau); gesamt: Endsumme (fett auf Grün)."""
        ncol = len(kopf)
        right = [h.startswith(">") for h in kopf]
        head = [Paragraph(esc(h.lstrip(">")), ST_HEAD_R if r else ST_HEAD) for h, r in zip(kopf, right)]

        def conv(row, bold=False):
            out = []
            for i, c in enumerate(row):
                if not isinstance(c, Cell):
                    c = Cell(c, num=right[i] if i < ncol else False)
                st = ST_NUM if (c.num or (i < ncol and right[i])) else ST_CELL
                col = TONE.get(c.tone, DUNKEL).hexval()[2:]
                txt = esc(c.text)
                if c.bold or bold:
                    txt = f"<b>{txt}</b>"
                zusatz = (f"<br/><font size='6.5' color='#{GRAU.hexval()[2:]}'>{esc(c.klein)}</font>"
                          if getattr(c, "klein", None) else "")
                out.append(Paragraph(f"<font color='#{col}'>{txt}</font>{zusatz}", st))
            return out

        data = ([] if kopf_ohne else [head]) + [conv(z) for z in zeilen]
        if fuss:
            data.append(conv(fuss, True))
        if gesamt:
            data.append(conv(gesamt, True))
        if breiten:
            tot = sum(breiten)
            cw = [self.width * b / tot for b in breiten]
        else:
            cw = [self.width / ncol] * ncol
        cw = _ohne_wortbruch(cw, kopf, zeilen + [z for z in (fuss, gesamt) if z], bool(fuss or gesamt))
        t = Table(data, colWidths=cw, repeatRows=0 if kopf_ohne else 1)
        style = [("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 2.5),
                 ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5), ("LEFTPADDING", (0, 0), (-1, -1), 3),
                 ("RIGHTPADDING", (0, 0), (-1, -1), 3), ("LINEBELOW", (0, 1 if not kopf_ohne else 0), (-1, -1), 0.25, LINIE)]
        if not kopf_ohne:
            style.append(("LINEBELOW", (0, 0), (-1, 0), 0.8, GRAU))
        n = len(data)
        if gesamt:
            style.append(("BACKGROUND", (0, n - 1), (-1, n - 1), GRUEN))
            if fuss:
                style.append(("BACKGROUND", (0, n - 2), (-1, n - 2), HELL))
        elif fuss:
            style.append(("BACKGROUND", (0, n - 1), (-1, n - 1), HELL))
        for r in zebra_rows or []:
            style.append(("BACKGROUND", (0, r + (0 if kopf_ohne else 1)), (-1, r + (0 if kopf_ohne else 1)), r_bg(r)))
        t.setStyle(TableStyle(style))
        self.story += [KeepTogether([t]) if keep else t, Spacer(1, 8)]
        return t

    def styled_rows(self, t, rows_bg: dict):
        """Zusatz-Hintergründe {zeilenindex (ohne Kopf): farbe}."""
        t.setStyle(TableStyle([("BACKGROUND", (0, r + 1), (-1, r + 1), c) for r, c in rows_bg.items()]))

    def leer(self, text):
        self.story.append(Paragraph(esc(text), ST_SMALL))
        self.story.append(Spacer(1, 8))

    def speichern(self, pfad: str) -> str:
        story = []
        self.story, body = [], self.story
        self.kopf()
        story = self.story + body

        erstellt = datetime.now()

        def fuss(c, doc):
            c.saveState()
            c.setFont(FONT, 7)
            c.setFillColor(GRAU)
            c.drawString(15 * mm, 9 * mm, f"Erstellt am {erstellt:%d.%m.%Y %H:%M}")
            c.drawRightString(self.size[0] - 15 * mm, 9 * mm, f"Seite {doc.page}")
            c.restoreState()

        doc = SimpleDocTemplate(pfad, pagesize=self.size, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=15 * mm,
                                bottomMargin=17 * mm, title=self.titel, author=self.inhaber)
        doc.build(story, onFirstPage=fuss, onLaterPages=fuss)
        return pfad


def _ohne_wortbruch(cw, kopf, zeilen, fett_unten):
    """Spalten so verbreitern, dass kein Wort mitten im Wort umbricht (z. B. „ZAHLUNGSPLAN“);
    der Platz wird Spalten mit Reserve anteilig abgezogen. Gesamtbreite bleibt gleich."""
    from reportlab.pdfbase.pdfmetrics import stringWidth
    pad = 6.5
    mins = []
    for i, h in enumerate(kopf):
        w = max((stringWidth(x, FONT_B, 7.8) for x in esc_plain(h.lstrip(">")).split()), default=0)
        for n, z in enumerate(zeilen):
            if i >= len(z):
                continue
            c = z[i]
            txt = c.text if isinstance(c, Cell) else c
            bold = (isinstance(c, Cell) and c.bold) or (fett_unten and n >= len(zeilen) - 2)
            teile = esc_plain(txt).split()
            if bold and (fett_unten and n >= len(zeilen) - 2) and len(esc_plain(txt)) <= 28:
                teile = [esc_plain(txt)]  # Summenbezeichnung („Gesamt bezahlt“) in einer Zeile
            for wort in teile:
                w = max(w, stringWidth(wort, FONT_B if bold else FONT, FS))
        mins.append(w + pad)
    cw = list(cw)
    fehlt = sum(max(0, m - c) for m, c in zip(mins, cw))
    if fehlt <= 0:
        return cw
    reserve = [max(0, c - m) for m, c in zip(mins, cw)]
    if sum(reserve) <= 0:
        return cw
    anteil = min(1, fehlt / sum(reserve))
    return [max(m, c) if c < m else c - r * anteil for m, c, r in zip(mins, cw, reserve)]


def esc_plain(s) -> str:
    t = "" if s is None else str(s)
    for a, b in _ERSATZ.items():
        t = t.replace(a, b)
    return t


def r_bg(_r):
    return HELL
