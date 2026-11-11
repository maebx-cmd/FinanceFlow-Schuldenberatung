from datetime import date

from app import pdf
from tests.demo_data import befuellen


def test_alle_reports(db, tmp_path):
    ids = befuellen(db)
    y, m = date.today().year, date.today().month
    sc = [s["id"] for s in db.rows("SELECT id FROM bankruptcy_scenario")]
    jobs = [
        ("verbindlichkeiten", pdf.verbindlichkeiten, ()), ("tilgungsplan", pdf.tilgungsplan, (ids["l1"],)),
        ("lohn", pdf.lohn, (db.soll_lohn()["id"],)),
        ("konkurs", pdf.konkurs, (sc[0],)), ("vergleich", pdf.szenario_vergleich, (sc,)),
        ("bm", pdf.buchungsmitteilung, (ids["l1"],)), ("haushalt", pdf.haushalt, ()),
        ("forderungen", pdf.forderungen, ()), ("forderung", pdf.forderung, (ids["claim"],)),
        ("gv", pdf.glaeubigerverzeichnis, ("all",)),
        ("zp", pdf.zahlungsplan_uebersicht, ()), ("v12", pdf.vorschau12, ()), ("or", pdf.offene_raten, ()),
        ("post", pdf.postbuch, (f"{y}-{m:02d}",)),
        ("lv", pdf.lohn_vorschau, (db.lohn_vorschau({"monthlyBase": "2500"}),)),
    ]
    for name, fn, args in jobs:
        p = tmp_path / f"{name}.pdf"
        fn(db, str(p), *args)
        assert p.stat().st_size > 1500, name
