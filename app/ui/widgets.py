"""Wiederverwendbare Fiori-artige Bausteine."""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QFrame, QGridLayout, QHBoxLayout, QHeaderView,
                               QLabel, QLineEdit, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QSizePolicy, QWidget)

MONATE = ["Jänner", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September",
          "Oktober", "November", "Dezember"]


def eur(x, waehrung=True) -> str:
    if x is None or x == "":
        return ""
    d = Decimal(str(x)).quantize(Decimal("0.01"))
    s = f"{d:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{s} €" if waehrung else s


def parse_num(s):
    s = (s or "").strip().replace("€", "").replace(" ", "")
    if not s:
        return None
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    return float(s)


def fmt_num(x, nk=2) -> str:
    if x is None or x == "":
        return ""
    return f"{float(x):,.{nk}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def iso_to_de(s):
    if not s:
        return ""
    try:
        return date.fromisoformat(s).strftime("%d.%m.%Y")
    except ValueError:
        return s


def de_to_iso(s):
    s = (s or "").strip()
    if not s:
        return None
    for sep in (".", "-", "/"):
        parts = s.split(sep)
        if len(parts) == 3:
            try:
                if len(parts[0]) == 4:
                    return date(int(parts[0]), int(parts[1]), int(parts[2])).isoformat()
                return date(int(parts[2]), int(parts[1]), int(parts[0])).isoformat()
            except ValueError:
                pass
    raise ValueError(f"Ungültiges Datum: {s} (Format TT.MM.JJJJ)")


def button(text, emph=False, flat=False, neg=False, cb=None) -> QPushButton:
    b = QPushButton(text)
    if emph:
        b.setProperty("emph", True)
    if flat:
        b.setProperty("flat", True)
    if neg:
        b.setProperty("neg", True)
    b.setCursor(Qt.PointingHandCursor)
    if cb:
        b.clicked.connect(cb)
    return b


def label(text, name=None, wrap=False) -> QLabel:
    l = QLabel()
    l.setText(text)
    if name:
        l.setObjectName(name)
    l.setWordWrap(wrap)
    return l


def strip(text, art="info") -> QLabel:
    l = QLabel(text)
    l.setProperty("strip", art)
    l.setWordWrap(True)
    return l


def set_strip(l: QLabel, text, art="info"):
    l.setText(text)
    l.setProperty("strip", art)
    l.style().unpolish(l)
    l.style().polish(l)
    l.setVisible(bool(text))


class Card(QFrame):
    def __init__(self, titel=None, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(16, 14, 16, 16)
        self.lay.setSpacing(10)
        if titel:
            t = label(titel, "h2")
            t.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
            self.lay.addWidget(t)

    def _ausrichten(self):
        # Kann kein Inhalt vertikal wachsen (feste Felder, Tabellen mit fixer Höhe), bleibt der Inhalt
        # oben kompakt, statt dass Qt die Resthöhe als Lücken zwischen Titel und Feldern verteilt.
        def kann_wachsen(it):
            if not (it.expandingDirections() & Qt.Vertical):
                return False
            w = it.widget()
            return w is None or w.maximumHeight() > w.minimumHeight()
        waechst = any(kann_wachsen(self.lay.itemAt(i)) for i in range(self.lay.count()))
        ziel = Qt.AlignmentFlag(0) if waechst else Qt.AlignTop
        if self.lay.alignment() != ziel:
            self.lay.setAlignment(ziel)

    def event(self, e):
        if e.type() in (e.Type.LayoutRequest, e.Type.Show):
            self._ausrichten()
        return super().event(e)


class Tile(QFrame):
    clicked = Signal()

    def __init__(self, titel, sub="", kpi="", parent=None):
        super().__init__(parent)
        self.setObjectName("tile")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(190, 176)
        l = QVBoxLayout(self)
        l.setContentsMargins(16, 14, 16, 14)
        self.t = label(titel, "tiletitle", True)
        self.s = label(sub, "tilesub", True)
        self.k = label(kpi, "tilekpi")
        l.addWidget(self.t)
        l.addWidget(self.s)
        l.addStretch()
        l.addWidget(self.k)

    def mouseReleaseEvent(self, e):
        self.clicked.emit()

    def set(self, sub=None, kpi=None):
        if sub is not None:
            self.s.setText(sub)
        if kpi is not None:
            self.k.setText(kpi)


class Kpi(QWidget):
    def __init__(self, titel, parent=None):
        super().__init__(parent)
        l = QVBoxLayout(self)
        l.setContentsMargins(0, 0, 0, 0)
        l.setSpacing(2)
        self.lab = label(titel, "kpilabel")
        self.val = label("–", "kpi")
        l.addWidget(self.lab)
        l.addWidget(self.val)

    def set(self, v, farbe=None):
        self.val.setText(v)
        self.val.setStyleSheet(f"color: {farbe};" if farbe else "")


class Form(QWidget):
    """Formular mit Fiori-Labels oberhalb der Felder."""

    def __init__(self, spalten=2, parent=None):
        super().__init__(parent)
        self.g = QGridLayout(self)
        self.g.setContentsMargins(0, 0, 0, 0)
        self.g.setHorizontalSpacing(24)
        self.g.setVerticalSpacing(4)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.spalten = spalten
        self.n = 0
        self.felder = {}
        self.labels = {}

    def verbergen(self, key, verborgen=True):
        self.felder[key].setVisible(not verborgen)
        self.labels[key].setVisible(not verborgen)

    def add(self, key, text, widget, span=1, hilfe=None):
        row = (self.n // self.spalten) * 2
        col = self.n % self.spalten
        lab = label(text, "formlabel")
        if hilfe:
            lab.setToolTip(hilfe)
            widget.setToolTip(hilfe)
        self.g.addWidget(lab, row, col, 1, span)
        self.g.addWidget(widget, row + 1, col, 1, span)
        self.n += span
        self.felder[key] = widget
        self.labels[key] = lab
        return widget

    def leer(self):
        self.n += 1


def combo(items, editable=False) -> QComboBox:
    from . import diskret
    c = QComboBox()
    c.setEditable(editable)
    for it in items:
        if isinstance(it, tuple):
            c.addItem(it[1], it[0])
        else:
            c.addItem(str(it), it)
        if not editable:
            diskret.combo_text(c, c.count() - 1)
    return c


def combo_set(c: QComboBox, value):
    i = c.findData(value)
    if i < 0:
        i = c.findText(str(value)) if value is not None else -1
    c.setCurrentIndex(max(i, 0))


def zahlfeld(platzhalter="") -> QLineEdit:
    e = QLineEdit()
    e.setPlaceholderText(platzhalter)
    e.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    return e


def frage(parent, titel, text) -> bool:
    return QMessageBox.question(parent, titel, text, QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes


def fehler(parent, text):
    QMessageBox.warning(parent, "Hinweis", str(text))


def hbox(*ws, stretch_vor=False, stretch_nach=False, spacing=8) -> QHBoxLayout:
    h = QHBoxLayout()
    h.setSpacing(spacing)
    if stretch_vor:
        h.addStretch()
    for w in ws:
        if w is None:
            h.addStretch()
        elif isinstance(w, QWidget):
            h.addWidget(w)
        else:
            h.addLayout(w)
    if stretch_nach:
        h.addStretch()
    return h


def page_widget() -> QWidget:
    w = QWidget()
    w.setObjectName("page")
    return w


class TabelleEditor(QWidget):
    """Kleine editierbare Tabelle für Listen von Dicts."""

    def __init__(self, spalten, breiten=None, parent=None):
        super().__init__(parent)
        self.spalten = spalten  # [(key, titel, typ)] typ: text|num|date|bool|list|combo:<a,b>
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        self.t = QTableWidget(0, len(spalten))
        self.t.setHorizontalHeaderLabels([s[1] for s in spalten])
        self.t.verticalHeader().setVisible(False)
        self.t.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.t.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.t.setMinimumHeight(140)
        if breiten:
            self.t.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
            self.t.horizontalHeader().setStretchLastSection(False)
            for i, b in enumerate(breiten):
                if b:
                    self.t.setColumnWidth(i, b)
                else:
                    self.t.horizontalHeader().setSectionResizeMode(i, QHeaderView.Stretch)
        v.addWidget(self.t)
        v.addLayout(hbox(button("Zeile hinzufügen", cb=self.add_row),
                         button("Zeile entfernen", flat=True, neg=True, cb=self.del_row), stretch_nach=True))
        self.ids = []

    def add_row(self, data=None):
        data = data or {}
        r = self.t.rowCount()
        self.t.insertRow(r)
        self.ids.append(data.get("id") or uuid.uuid4().hex[:8])
        for c, (key, _, typ) in enumerate(self.spalten):
            val = data.get(key)
            if typ == "bool":
                cb = QCheckBox()
                cb.setChecked(bool(val) if val is not None else True)
                w = QWidget(); l = QHBoxLayout(w); l.setContentsMargins(8, 0, 0, 0); l.addWidget(cb)
                self.t.setCellWidget(r, c, w)
            elif typ.startswith("combo:"):
                opts = typ.split(":", 1)[1].split(",")
                cmb = combo(opts)
                combo_set(cmb, val or opts[0])
                self.t.setCellWidget(r, c, cmb)
            else:
                if typ == "num":
                    txt = fmt_num(val) if val not in (None, "") else ""
                elif typ == "date":
                    txt = iso_to_de(val)
                elif typ == "list":
                    txt = ", ".join(val or [])
                else:
                    txt = str(val or "")
                self.t.setItem(r, c, QTableWidgetItem(txt))

    def del_row(self):
        for r in sorted({i.row() for i in self.t.selectedIndexes()}, reverse=True):
            self.t.removeRow(r)
            del self.ids[r]

    def set_data(self, rows):
        self.t.setRowCount(0)
        self.ids = []
        for d in rows or []:
            self.add_row(d)

    def data(self):
        out = []
        for r in range(self.t.rowCount()):
            d = {"id": self.ids[r]}
            for c, (key, _, typ) in enumerate(self.spalten):
                if typ == "bool":
                    d[key] = self.t.cellWidget(r, c).findChild(QCheckBox).isChecked()
                elif typ.startswith("combo:"):
                    d[key] = self.t.cellWidget(r, c).currentData()
                else:
                    it = self.t.item(r, c)
                    txt = it.text() if it else ""
                    if typ == "num":
                        d[key] = parse_num(txt)
                    elif typ == "date":
                        d[key] = de_to_iso(txt)
                    elif typ == "list":
                        d[key] = [x.strip() for x in txt.split(",") if x.strip()]
                    else:
                        d[key] = txt
            out.append(d)
        return out
