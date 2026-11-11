#!/bin/sh
# MSI-Paket unter Linux bauen (z. B. Raspberry Pi, VPS, GitHub Actions) – aus einer fertig gebauten EXE.
#   sudo apt-get install wixl          (Paket msitools/wixl)
#   tools/msi_bauen.sh <Ordner mit FinanceFlow-Schuldenberatung.exe> [Version]
# Die PDFs (hilfe/), die Smartphone-Version (web/) und das Symbol (installer/financeflow.ico) werden aus dem Quellcode dazugelegt.
set -e
cd "$(dirname "$0")/.."
QUELLE="${1:-dist}"
VERSION="${2:-$(python3 -c 'import app; print(app.APP_VERSION)')}"
test -f "$QUELLE/FinanceFlow-Schuldenberatung.exe" || { echo "Fehlt: $QUELLE/FinanceFlow-Schuldenberatung.exe"; exit 1; }
cp hilfe/*.pdf web/FinanceFlow-Schuldner.html installer/financeflow.ico "$QUELLE/"
wixl -a x64 -D Version="$VERSION" -D Quelle="$QUELLE" -o "$QUELLE/FinanceFlow-Schuldenberatung-$VERSION.msi" \
     installer/FinanceFlow-Schuldenberatung.wxs
echo "MSI: $QUELLE/FinanceFlow-Schuldenberatung-$VERSION.msi"
