@echo off
setlocal enabledelayedexpansion
REM Baut dist\FinanceFlow-Schuldenberatung.exe und - falls das WiX Toolset 3 installiert ist - das MSI-Paket
cd /d "%~dp0"

REM ---- Python suchen: py-Launcher, dann übliche Installationsorte, dann PATH ----
set "PY="
where py >nul 2>nul && (py -3 -c "import sys" >nul 2>nul && set "PY=py -3")
if not defined PY (
    for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*" "%ProgramFiles%\Python3*" "C:\Python3*") do (
        if exist "%%~D\python.exe" set "PY=%%~D\python.exe"
    )
    if defined PY set "PY="!PY!""
)
if not defined PY (
    python -c "import sys" >nul 2>nul && set "PY=python"
)
if not defined PY (
    echo Python wurde nicht gefunden.
    echo Bitte Python 3.12 von python.org installieren ^(Haken bei "Add python.exe to PATH"^)
    echo oder den Pfad zu python.exe unten in dieser Datei bei PY eintragen.
    goto fehler
)
echo Verwende Python: %PY%
%PY% --version

REM ---- Virtuelle Umgebung: Python der .venv direkt verwenden (nicht ueber PATH) ----
REM Eine defekte oder von einem anderen PC/Python stammende .venv wird erkannt und neu angelegt.
set "VPY=%~dp0.venv\Scripts\python.exe"
if exist "%VPY%" (
    "%VPY%" -c "import sys" >nul 2>nul || (
        echo Vorhandene virtuelle Umgebung ist defekt - wird neu angelegt ...
        rmdir /s /q "%~dp0.venv"
    )
)
if not exist "%VPY%" (
    echo [1/4] Virtuelle Umgebung anlegen ...
    if exist "%~dp0.venv" rmdir /s /q "%~dp0.venv"
    %PY% -m venv "%~dp0.venv" || goto fehler
)
if not exist "%VPY%" (
    echo Die virtuelle Umgebung konnte nicht angelegt werden: "%VPY%" fehlt.
    goto fehler
)

echo [2/4] Pakete installieren ...
"%VPY%" -m pip install --upgrade pip >nul
"%VPY%" -m pip install -r requirements.txt pyinstaller pytest lxml || goto fehler

echo [3/4] Tests ...
"%VPY%" -m pytest -q tests || goto fehler

echo [4/5] EXE bauen ...
"%VPY%" -m PyInstaller --noconfirm --clean --onefile --windowed --name FinanceFlow-Schuldenberatung --icon installer\financeflow.ico --add-data "hilfe;hilfe" --add-data "web;web" --collect-submodules app --collect-all sqlcipher3 main.py || goto fehler
copy /y hilfe\*.pdf dist\ >nul
copy /y web\FinanceFlow-Schuldner.html dist\ >nul
copy /y installer\financeflow.ico dist\ >nul

echo [5/5] MSI-Paket ...
for /f %%V in ('"%VPY%" -c "import app; print(app.APP_VERSION)"') do set "VER=%%V"
set "CANDLE="
set "LIGHT="
where candle >nul 2>nul && (set "CANDLE=candle" & set "LIGHT=light")
if not defined CANDLE if exist "%WIX%bin\candle.exe" (set "CANDLE=%WIX%bin\candle.exe" & set "LIGHT=%WIX%bin\light.exe")
if defined CANDLE (
    "%CANDLE%" -nologo -arch x64 -dVersion=%VER% -dQuelle=dist -out dist\installer.wixobj installer\FinanceFlow-Schuldenberatung.wxs || goto fehler
    "%LIGHT%" -nologo -cultures:de-de -sice:ICE57 -sice:ICE91 -out dist\FinanceFlow-Schuldenberatung-%VER%.msi dist\installer.wixobj || goto fehler
    echo MSI: %~dp0dist\FinanceFlow-Schuldenberatung-%VER%.msi
) else (
    echo WiX Toolset 3 nicht gefunden - MSI wird hier nicht gebaut.
    echo Das MSI baut GitHub Actions automatisch ^(Job "msi"^) oder unter Linux: tools\msi_bauen.sh dist
)

echo.
echo Fertig: %~dp0dist\FinanceFlow-Schuldenberatung.exe
pause
exit /b 0

:fehler
echo.
echo FEHLER - siehe Meldung oben.
pause
exit /b 1
