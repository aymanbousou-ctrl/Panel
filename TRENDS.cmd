@echo off
setlocal
set "folder=%LOCALAPPDATA%\FlipRadarV21"
if defined FLIPRADAR_DATA set "folder=%FLIPRADAR_DATA%"
if exist "%folder%\Trends.csv" (
  start "" "%folder%\Trends.csv"
) else (
  echo Bitte zuerst START.cmd oeffnen und einen Suchdurchlauf abwarten.
  pause
)
