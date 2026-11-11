"""DB = Basis + alle fachlichen Zugriffe (als Mixins in app/services/*)."""
from __future__ import annotations

from .db_base import DBHelfer, FachFehler, VersionsFehler  # noqa: F401
from .services.finance import FinanceMixin
from .services.kontoblatt import KontoblattMixin
from .services.module import ModuleMixin
from .services.seed import seed_defaults
from .services.sepa import SepaMixin


class DB(FinanceMixin, ModuleMixin, SepaMixin, KontoblattMixin, DBHelfer):
    def __init__(self, path: str, backup_behalten: int = 30, key: bytes | None = None):
        super().__init__(path, backup_behalten, key=key)
        seed_defaults(self)
        from .abgleich.abgleich import finanz_merker_einrichten
        finanz_merker_einrichten(self)
        self.benutzer = None
        self.mandant = None          # Schuldenberater: geöffneter Mandant (dict), sonst None
        self.modus = None            # "SCHULDNER" / "BERATER" (setzt main.py)
        self.mandanten_verwaltung = None

    # Geräte-Einstellungen (nicht Teil des Abgleichs): Tabelle meta der daten.db
    def geraet_einstellung(self, key, default=""):
        v = self._meta("geraet." + key)
        return default if v is None else v

    def set_geraet_einstellung(self, key, value):
        with self.con:
            self._set_meta("geraet." + key, value)
