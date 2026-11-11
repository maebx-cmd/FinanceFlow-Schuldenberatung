"""Gemeinsame UI-Bausteine für alle Seiten (aufbauend auf widgets.py)."""
from __future__ import annotations

import os
import sys
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from PySide6.QtCore import QStandardPaths, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFrame, QGridLayout,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPlainTextEdit, QScrollArea, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from ..db_base import FachFehler
from . import diskret
from .widgets import (Card, Form, Kpi, button, combo, combo_set, de_to_iso, fehler, frage, hbox, iso_to_de, label,
                      set_strip, strip)

ROT, GRUEN, ORANGE, GRAU, BLAU = "#AA0808", "#256F3A", "#E76500", "#556B82", "#0064D9"
TONES = {"red": ROT, "green": GRUEN, "amber": ORANGE, "gray": GRAU, "blue": BLAU}


def eur(x, sign=False) -> str:
    if x is None or x == "":
        return "–"
    try:
        v = Decimal(str(x)).quantize(Decimal("0.01"))
    except InvalidOperation:
        return str(x)
    s = f"{abs(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    pre = "−" if v < 0 else ("+" if sign and v > 0 else "")
    return f"{pre}{s} €"


def pct(x, nk=2) -> str:
    if x in (None, ""):
        return "–"
    return f"{Decimal(str(x)) * 100:.{nk}f}".replace(".", ",") + " %"


def num_de(x, nk=2) -> str:
    if x in (None, ""):
        return ""
    return f"{Decimal(str(x)):,.{nk}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def dat(x) -> str:
    if not x:
        return "–"
    return iso_to_de(str(x)[:10])


def parse_dec(s, pflicht=False, feld="Betrag") -> str | None:
    """Deutsche Eingabe '1.234,56' -> '1234.56' (Text, exakt)."""
    t = (s or "").strip().replace("€", "").replace(" ", "")
    if not t:
        if pflicht:
            raise FachFehler(f"{feld} fehlt.")
        return None
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    try:
        return str(Decimal(t))
    except InvalidOperation:
        raise FachFehler(f"{feld}: „{s}“ ist keine gültige Zahl.")


def tone_of(v) -> str | None:
    try:
        return "red" if Decimal(str(v)) < 0 else "green"
    except Exception:
        return None


class Tabelle(QTableWidget):
    """Nur-Lese-Tabelle: Spalten mit '>' sind rechtsbündig. Zellen: str oder (text, tone[, bold])."""
    aktiviert = Signal(object)

    def __init__(self, spalten, breiten=None, parent=None, mehrfach=False):
        super().__init__(0, len(spalten), parent)
        self.right = [s.startswith(">") for s in spalten]
        self.setHorizontalHeaderLabels([s.lstrip(">") for s in spalten])
        self.verticalHeader().setVisible(False)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection if mehrfach else QAbstractItemView.SingleSelection)
        self.setAlternatingRowColors(False)
        self.setShowGrid(False)
        self.verticalHeader().setDefaultSectionSize(30)
        h = self.horizontalHeader()
        h.setHighlightSections(False)
        for i, r in enumerate(self.right):
            it = self.horizontalHeaderItem(i)
            it.setTextAlignment((Qt.AlignRight if r else Qt.AlignLeft) | Qt.AlignVCenter)
        if breiten:
            h.setSectionResizeMode(QHeaderView.Interactive)
            for i, b in enumerate(breiten):
                if b:
                    self.setColumnWidth(i, b)
                else:
                    h.setSectionResizeMode(i, QHeaderView.Stretch)
        else:
            h.setSectionResizeMode(QHeaderView.Stretch)
        self.ids = []
        self.doubleClicked.connect(lambda idx: self.aktiviert.emit(self.ids[idx.row()] if idx.row() < len(self.ids) else None))

    def set_rows(self, rows, ids=None, hoehe_auto=False, max_rows=None):
        self.setRowCount(0)
        self.setRowCount(len(rows))
        self.ids = list(ids) if ids is not None else list(range(len(rows)))
        for r, row in enumerate(rows):
            for c, cell in enumerate(row):
                if isinstance(cell, tuple):
                    text = cell[0]
                    tone = cell[1] if len(cell) > 1 else None
                    bold = bool(cell[2]) if len(cell) > 2 else False
                    bg = cell[3] if len(cell) > 3 else None
                else:
                    text, tone, bold, bg = cell, None, False, None
                it = diskret.listen_text(QTableWidgetItem("" if text is None else str(text)))
                it.setTextAlignment(((Qt.AlignRight if c < len(self.right) and self.right[c] else Qt.AlignLeft) | Qt.AlignVCenter))
                if tone:
                    it.setForeground(QColor(TONES.get(tone, tone)))
                if bold:
                    f = it.font()
                    f.setBold(True)
                    it.setFont(f)
                if bg:
                    it.setBackground(QColor(bg))
                self.setItem(r, c, it)
        if hoehe_auto:
            n = len(rows) if max_rows is None else min(len(rows), max_rows)
            self.setFixedHeight(36 + 30 * max(n, 1))
            sp = self.sizePolicy()
            sp.setVerticalPolicy(sp.Policy.Fixed)
            self.setSizePolicy(sp)

    def sel_id(self):
        r = self.currentRow()
        return self.ids[r] if 0 <= r < len(self.ids) and self.selectedItems() else None

    def sel_ids(self):
        return [self.ids[r] for r in sorted({i.row() for i in self.selectedIndexes()}) if r < len(self.ids)]


class KpiReihe(QWidget):
    def __init__(self, titel: list[str], parent=None):
        super().__init__(parent)
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(16)
        self.k = {}
        for t in titel:
            c = Card()
            kp = Kpi(t)
            c.lay.addWidget(kp)
            h.addWidget(c, 1)
            self.k[t] = kp

    def set(self, titel, wert, tone=None):
        self.k[titel].set(wert, TONES.get(tone, tone) if tone else None)


def badge(text, art="none") -> QLabel:
    l = QLabel(text)
    l.setObjectName({"ok": "badge_ok", "draft": "badge_draft"}.get(art, "badge_none"))
    return l


def set_badge(l: QLabel, text, art="none"):
    l.setText(text)
    l.setObjectName({"ok": "badge_ok", "draft": "badge_draft"}.get(art, "badge_none"))
    l.style().unpolish(l)
    l.style().polish(l)


def scroll(w):
    s = QScrollArea()
    s.setWidgetResizable(True)
    s.setFrameShape(QFrame.NoFrame)
    s.setWidget(w)
    return s


def berichte_ordner(db) -> str:
    d = os.path.join(os.path.dirname(os.path.abspath(db.path)), "Berichte")
    os.makedirs(d, exist_ok=True)
    return d


def pdf_oeffnen(seite, fn, name, *args):
    """Erzeugt ein PDF im Ordner 'Berichte' neben der Datenbank und öffnet es."""
    try:
        pfad = os.path.join(berichte_ordner(seite.db), f"{name}_{datetime.now():%Y-%m-%d_%H%M%S}.pdf")
        fn(seite.db, pfad, *args)
    except (FachFehler, ValueError) as e:
        seite.meldung(str(e), "error")
        return
    if os.environ.get("QT_QPA_PLATFORM") != "offscreen":
        QDesktopServices.openUrl(QUrl.fromLocalFile(pfad))
    seite.meldung(f"PDF erstellt: {pfad}", "ok")


# ── Formular-Dialog ───────────────────────────────────────────────────────────
class FeldDialog(QDialog):
    """Generischer Erfassungsdialog.

    felder: [(key, label, typ, extra)] – typ: text | multi | dec | int | date | bool | combo | time
    extra bei combo: Liste von (wert, text). Werte: dict für Vorbelegung.
    """

    def __init__(self, parent, titel, felder, werte=None, spalten=2, pruefung=None, breite=640):
        super().__init__(parent)
        self.setWindowTitle(titel)
        self.setMinimumWidth(breite)
        self.felder = felder
        self.pruefung = pruefung
        v = QVBoxLayout(self)
        v.setContentsMargins(24, 20, 24, 16)
        v.addWidget(label(titel, "h2"))
        self.msg = strip("")
        self.msg.setVisible(False)
        v.addWidget(self.msg)
        self.form = Form(spalten)
        werte = werte or {}
        self.w = {}
        for key, text, typ, *extra in felder:
            ex = extra[0] if extra else None
            if typ == "combo":
                w = combo(ex or [])
                combo_set(w, werte.get(key))
            elif typ == "bool":
                w = QCheckBox(ex or "")
                w.setChecked(bool(werte.get(key, False)))
            elif typ == "multi":
                w = QPlainTextEdit(werte.get(key) or "")
                w.setFixedHeight(70)
            else:
                w = QLineEdit()
                val = werte.get(key)
                if typ == "date":
                    w.setPlaceholderText("TT.MM.JJJJ")
                    w.setText(iso_to_de(val) if val else "")
                elif typ == "dec":
                    w.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    w.setText(num_de(val, ex if isinstance(ex, int) else 2) if val not in (None, "") else "")
                    if isinstance(ex, str):
                        w.setPlaceholderText(ex)
                elif typ == "int":
                    w.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    w.setText("" if val in (None, "") else str(val))
                elif typ == "time":
                    w.setPlaceholderText("HH:MM")
                    w.setText(val or "")
                else:
                    w.setText("" if val is None else str(val))
                    if isinstance(ex, str):
                        w.setPlaceholderText(ex)
            span = 2 if typ == "multi" and spalten >= 2 else 1
            self.form.add(key, text, w, span=span)
            self.w[key] = (w, typ)
        v.addWidget(self.form)
        v.addStretch()
        bb = QDialogButtonBox()
        ok = button("Speichern", emph=True, cb=self._ok)
        bb.addButton(ok, QDialogButtonBox.AcceptRole)
        bb.addButton(button("Abbrechen", cb=self.reject), QDialogButtonBox.RejectRole)
        v.addWidget(bb)
        self.ergebnis = None

    def werte(self) -> dict:
        out = {}
        for key, (w, typ) in self.w.items():
            lab = next(f[1] for f in self.felder if f[0] == key)
            if typ == "combo":
                out[key] = w.currentData()
            elif typ == "bool":
                out[key] = w.isChecked()
            elif typ == "multi":
                out[key] = w.toPlainText().strip()
            else:
                t = w.text().strip()
                if typ == "date":
                    try:
                        out[key] = de_to_iso(t)
                    except ValueError as e:
                        raise FachFehler(f"{lab}: {e}")
                elif typ == "dec":
                    out[key] = parse_dec(t, feld=lab)
                elif typ == "int":
                    if t and not t.lstrip("-").isdigit():
                        raise FachFehler(f"{lab}: ganze Zahl erwartet.")
                    out[key] = int(t) if t else None
                else:
                    out[key] = t
        return out

    def _ok(self):
        try:
            w = self.werte()
            if self.pruefung:
                self.pruefung(w)
        except FachFehler as e:
            set_strip(self.msg, str(e), "error")
            return
        self.ergebnis = w
        self.accept()


def dialog(parent, titel, felder, werte=None, spalten=2, pruefung=None, breite=640):
    d = FeldDialog(parent, titel, felder, werte, spalten, pruefung, breite)
    return d.ergebnis if d.exec() == QDialog.Accepted else None


# ── Seiten-Basis ──────────────────────────────────────────────────────────────
class Seite(QWidget):
    """Arbeitsseite: weißer Objektkopf (h1, Untertitel, Aktionen, Strip) + scrollbarer Inhalt."""
    TITEL = ""
    UNTERTITEL = ""

    def __init__(self, state, mit_scroll=True):
        super().__init__()
        self.setObjectName("page")
        self.state, self.db = state, state.db
        self._dirty = True
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        head = QFrame()
        head.setObjectName("objheader")
        hv = QVBoxLayout(head)
        hv.setContentsMargins(24, 16, 24, 10)
        self.h_titel = label(self.TITEL, "h1")
        self.h_sub = label(self.UNTERTITEL, "sub")
        self.aktionen = QHBoxLayout()
        self.aktionen.setSpacing(8)
        top = QHBoxLayout()
        top.addWidget(self.h_titel)
        top.addStretch()
        top.addLayout(self.aktionen)
        hv.addLayout(top)
        hv.addWidget(self.h_sub)
        self.msg = strip("")
        self.msg.setVisible(False)
        self.msg.setTextInteractionFlags(Qt.TextSelectableByMouse)
        hv.addWidget(self.msg)
        root.addWidget(head)
        inner = QWidget()
        inner.setObjectName("page")
        self.body = QVBoxLayout(inner)
        self.body.setContentsMargins(24, 16, 24, 24)
        self.body.setSpacing(16)
        root.addWidget(scroll(inner) if mit_scroll else inner, 1)
        state.daten_geaendert.connect(self._markieren)

    def aktion(self, text, cb, emph=False, neg=False, flat=False):
        b = button(text, emph=emph, neg=neg, flat=flat, cb=cb)
        self.aktionen.addWidget(b)
        return b

    def _markieren(self):
        self._dirty = True
        if self.isVisible():
            self._refresh()

    def showEvent(self, e):
        super().showEvent(e)
        if self._dirty:
            self._refresh()

    def _refresh(self):
        self._dirty = False
        try:
            self.refresh()
        except Exception as e:  # noqa: BLE001
            self.meldung(f"Fehler beim Laden: {e}", "error")

    def refresh(self):
        pass

    def meldung(self, text, art="info"):
        set_strip(self.msg, text, art)

    def tu(self, fn, *args, ok=None, **kw):
        """Fachoperation ausführen: Fehler als Strip, Erfolg -> Strip + daten_geaendert."""
        try:
            res = fn(*args, **kw)
        except (FachFehler, ValueError) as e:
            self.meldung(str(e), "error")
            return None
        if ok:
            self.meldung(ok if isinstance(ok, str) else ok(res), "ok")
        self.state.daten_geaendert.emit()
        return res if res is not None else True

    def pdf(self, fn, name, *args):
        pdf_oeffnen(self, fn, name, *args)


def kontakt_items(db, leer=False):
    items = [(k["id"], k["name"]) for k in db.kontakte()]
    return ([(None, "– bitte wählen –")] if leer else []) + items


# ── List-Detail-Basis ─────────────────────────────────────────────────────────
from PySide6.QtWidgets import QListWidget, QListWidgetItem, QSplitter, QTabWidget  # noqa: E402


class ListeDetail(QWidget):
    """Splitter 300 | Rest. Master: h1, Suche, Filter + „+ Anlegen“, #masterlist zweizeilig.
    Detail: Objektkopf (h1, Untertitel, Aktionen, Strip) + QTabWidget."""
    TITEL = ""
    NEU_TEXT = "+ Anlegen"
    FILTER: list = []          # [(wert, text)]

    def __init__(self, state):
        super().__init__()
        self.setObjectName("page")
        self.state, self.db = state, state.db
        self.obj = None
        self._dirty = True
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        split = QSplitter()
        root.addWidget(split)
        left = QWidget()
        left.setObjectName("page")
        lv = QVBoxLayout(left)
        lv.setContentsMargins(16, 16, 8, 16)
        lv.addWidget(label(self.TITEL, "h1"))
        self.suche = QLineEdit()
        self.suche.setPlaceholderText("Suchen")
        self.suche.textChanged.connect(self.refresh_liste)
        lv.addWidget(self.suche)
        self.filter = combo(self.FILTER) if self.FILTER else None
        if self.filter:
            self.filter.currentIndexChanged.connect(self.refresh_liste)
        lv.addLayout(hbox(self.filter, None, button(self.NEU_TEXT, emph=True, cb=self.neu)) if self.filter
                     else hbox(None, button(self.NEU_TEXT, emph=True, cb=self.neu)))
        self.liste = QListWidget()
        self.liste.setObjectName("masterlist")
        self.liste.currentItemChanged.connect(self._auswahl)
        lv.addWidget(self.liste, 1)
        self.summe = label("", "sub")
        lv.addWidget(self.summe)
        split.addWidget(left)

        right = QWidget()
        right.setObjectName("page")
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(0)
        head = QFrame()
        head.setObjectName("objheader")
        hv = QVBoxLayout(head)
        hv.setContentsMargins(24, 16, 24, 10)
        self.h_name = label("Nichts ausgewählt", "h1")
        self.h_badge = badge("")
        self.h_badge.setVisible(False)
        self.h_sub = label("", "sub")
        self.aktionen = QHBoxLayout()
        self.aktionen.setSpacing(8)
        top = QHBoxLayout()
        top.addWidget(self.h_name)
        top.addWidget(self.h_badge)
        top.addStretch()
        top.addLayout(self.aktionen)
        hv.addLayout(top)
        hv.addWidget(self.h_sub)
        self.msg = strip("")
        self.msg.setVisible(False)
        self.msg.setTextInteractionFlags(Qt.TextSelectableByMouse)
        hv.addWidget(self.msg)
        rv.addWidget(head)
        self.tabs = QTabWidget()
        rv.addWidget(self.tabs, 1)
        split.addWidget(right)
        split.setSizes([300, 1000])
        split.setStretchFactor(1, 1)
        self.tabs.setEnabled(False)
        self.aufbauen()
        state.daten_geaendert.connect(self._markieren)

    # Hooks
    def aufbauen(self):
        pass

    def eintraege(self) -> list:
        """[(id, zeile1, zeile2)]"""
        return []

    def laden(self, oid) -> dict:
        return {}

    def fuellen(self):
        pass

    def neu_obj(self) -> dict:
        return {}

    # Gemeinsames
    def tab(self, titel) -> QVBoxLayout:
        w = QWidget()
        w.setObjectName("page")
        v = QVBoxLayout(w)
        v.setContentsMargins(24, 16, 24, 16)
        v.setSpacing(16)
        self.tabs.addTab(scroll(w), titel)
        return v

    def aktion(self, text, cb, emph=False, neg=False, flat=False):
        b = button(text, emph=emph, neg=neg, flat=flat, cb=cb)
        self.aktionen.addWidget(b)
        return b

    def meldung(self, text, art="info"):
        set_strip(self.msg, text, art)

    def tu(self, fn, *args, ok=None, **kw):
        return Seite.tu(self, fn, *args, ok=ok, **kw)

    def pdf(self, fn, name, *args):
        pdf_oeffnen(self, fn, name, *args)

    def _markieren(self):
        self._dirty = True
        if self.isVisible():
            self.refresh()

    def showEvent(self, e):
        super().showEvent(e)
        if self._dirty:
            self.refresh()

    def refresh(self):
        self._dirty = False
        self.refresh_liste()
        if self.obj and self.obj.get("id"):
            try:
                self.obj = self.laden(self.obj["id"])
                self._fill()
            except FachFehler:
                self.obj = None

    def refresh_liste(self):
        q = self.suche.text().lower().strip()
        cur = self.obj.get("id") if self.obj else None
        self.liste.blockSignals(True)
        self.liste.clear()
        try:
            for oid, z1, z2 in self.eintraege():
                if q and q not in f"{z1} {z2}".lower():
                    continue
                it = QListWidgetItem(f"{z1}\n{z2}")
                it.setData(Qt.UserRole, oid)
                self.liste.addItem(diskret.listen_text(it))
                if oid == cur:
                    self.liste.setCurrentItem(it)
        except Exception as e:  # noqa: BLE001 – Fehler sichtbar machen statt stiller leerer Liste
            import traceback
            ort = traceback.extract_tb(e.__traceback__)[-1]
            self.meldung(f"Liste konnte nicht geladen werden: {type(e).__name__}: {e} "
                         f"({os.path.basename(ort.filename)}, Zeile {ort.lineno})", "error")
        finally:
            self.liste.blockSignals(False)

    def _auswahl(self, it, _p=None):
        if it:
            try:
                self.obj = self.laden(it.data(Qt.UserRole))
            except FachFehler as e:
                self.meldung(str(e), "error")
                return
            self.meldung("")
            self._fill()

    def neu(self):
        self.obj = self.neu_obj()
        self.liste.clearSelection()
        self.meldung("")
        self._fill()

    def _fill(self):
        self.tabs.setEnabled(True)
        self.fuellen()

    def waehle(self, oid):
        self.obj = self.laden(oid)
        self.refresh_liste()
        self._fill()


class Felder(Form):
    """Formular aus Spezifikation [(key, label, typ, extra)] mit set()/get() – gleiche Typen wie FeldDialog."""

    def __init__(self, spec, spalten=3):
        super().__init__(spalten)
        self.spec = spec
        self.typ = {}
        for key, text, typ, *extra in spec:
            ex = extra[0] if extra else None
            if typ == "combo":
                w = combo(ex or [])
            elif typ == "bool":
                w = QCheckBox(ex or "")
            elif typ == "multi":
                w = QPlainTextEdit()
                w.setFixedHeight(64)
            else:
                w = QLineEdit()
                if typ in ("dec", "int"):
                    w.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if typ == "date":
                    w.setPlaceholderText("TT.MM.JJJJ")
                if typ == "time":
                    w.setPlaceholderText("HH:MM")
                if isinstance(ex, str):
                    w.setPlaceholderText(ex)
            self.add(key, text, w, span=(2 if typ == "multi" and spalten > 1 else 1))
            self.typ[key] = (typ, ex)
        from PySide6.QtWidgets import QSizePolicy
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

    def showEvent(self, e):
        # Erst nach dem Stylesheet-Polish ist die echte Feldhöhe bekannt → Höhe fixieren (verhindert Überlappung)
        super().showEvent(e)
        self.setFixedHeight(self.layout().sizeHint().height())

    def set(self, obj: dict):
        for key, w in self.felder.items():
            typ, ex = self.typ[key]
            v = obj.get(key)
            if typ == "combo":
                combo_set(w, v)
            elif typ == "bool":
                w.setChecked(bool(v))
            elif typ == "multi":
                w.setPlainText(v or "")
            elif typ == "date":
                w.setText(iso_to_de(str(v)[:10]) if v else "")
            elif typ == "dec":
                w.setText(num_de(v, ex if isinstance(ex, int) else 2) if v not in (None, "") else "")
            else:
                w.setText("" if v is None else str(v))

    def get(self) -> dict:
        out = {}
        lab = {s[0]: s[1] for s in self.spec}
        for key, w in self.felder.items():
            typ, _ex = self.typ[key]
            if typ == "combo":
                out[key] = w.currentData()
            elif typ == "bool":
                out[key] = w.isChecked()
            elif typ == "multi":
                out[key] = w.toPlainText().strip()
            else:
                t = w.text().strip()
                if typ == "date":
                    try:
                        out[key] = de_to_iso(t)
                    except ValueError as e:
                        raise FachFehler(f"{lab[key]}: {e}")
                elif typ == "dec":
                    out[key] = parse_dec(t, feld=lab[key])
                elif typ == "int":
                    if t and not t.lstrip("-").isdigit():
                        raise FachFehler(f"{lab[key]}: ganze Zahl erwartet.")
                    out[key] = int(t) if t else None
                else:
                    out[key] = t
        return out

    def enable(self, key, on: bool):
        self.felder[key].setEnabled(on)
