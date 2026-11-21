@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
title FlipRadar 2.1
if not exist radar.py (
  echo Bitte die ZIP-Datei zuerst mit Alle extrahieren vollstaendig entpacken.
  pause
  exit /b 1
)
if "%~1"=="bestand" (
  set "mode=bestand"
  goto start
)
if "%~1"=="settings" (
  set "mode=settings"
  goto start
)
echo FlipRadar 2.1 - S: Suche, E: Einstellungen, D: Diagnose mit Telegram-Test
choice /C SED /T 5 /D S /N /M "Die Suche startet nach 5 Sekunden automatisch. "
set "mode=run"
if errorlevel 3 (set "mode=diagnose") else if errorlevel 2 (set "mode=settings")
:start
py -3.15 -V >nul 2>&1
if errorlevel 1 goto fallback
py -3.15 radar.py %mode%
goto ende
:fallback
python -V >nul 2>&1
if errorlevel 1 goto fehlt
python radar.py %mode%
goto ende
:fehlt
echo Python wurde nicht gefunden. Installiere Python 3.15 fuer Windows.
:ende
pause
