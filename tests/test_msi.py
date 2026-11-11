"""MSI-Beschreibung: gültiges XML, Version aus app/__init__.py; Probebau mit wixl, falls installiert (Linux)."""
import os
import shutil
import subprocess
import xml.dom.minidom

import pytest

BASIS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WXS = os.path.join(BASIS, "installer", "FinanceFlow-Schuldenberatung.wxs")


def test_wxs_gueltig_und_vollstaendig():
    dom = xml.dom.minidom.parse(WXS)
    dateien = [f.getAttribute("Name") for f in dom.getElementsByTagName("File")]
    assert set(dateien) == {"FinanceFlow-Schuldenberatung.exe", "financeflow.ico", "FinanceFlow-Anleitung-Schuldner.pdf",
                            "FinanceFlow-Handbuch-Schuldenberatung.pdf", "FinanceFlow-Schuldner.html"}
    produkt = dom.getElementsByTagName("Product")[0]
    assert produkt.getAttribute("UpgradeCode") == "D168DF2E-517A-489C-9891-7CE3F8C5A766"   # nie ändern (Updates)
    assert dom.getElementsByTagName("MajorUpgrade")
    assert os.path.exists(os.path.join(BASIS, "installer", "financeflow.ico"))


@pytest.mark.skipif(not shutil.which("wixl"), reason="wixl nicht installiert")
def test_msi_probebau(tmp_path):
    from app import APP_VERSION
    (tmp_path / "FinanceFlow-Schuldenberatung.exe").write_bytes(b"MZ" + b"\0" * 1000)
    for f in os.listdir(os.path.join(BASIS, "hilfe")):
        shutil.copy(os.path.join(BASIS, "hilfe", f), tmp_path)
    shutil.copy(os.path.join(BASIS, "installer", "financeflow.ico"), tmp_path)
    shutil.copy(os.path.join(BASIS, "web", "FinanceFlow-Schuldner.html"), tmp_path)
    ziel = tmp_path / "test.msi"
    subprocess.run(["wixl", "-a", "x64", "-D", f"Version={APP_VERSION}", "-D", f"Quelle={tmp_path}", "-o", str(ziel), WXS],
                   check=True, capture_output=True)
    assert ziel.stat().st_size > 50_000
    if shutil.which("msiinfo"):
        p = subprocess.run(["msiinfo", "export", str(ziel), "Property"], capture_output=True, text=True).stdout
        assert f"ProductVersion\t{APP_VERSION}" in p and "ALLUSERS\t1" in p
