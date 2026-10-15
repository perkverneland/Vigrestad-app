@echo off
chcp 65001 >nul
cd /d "%~dp0"
if "%~1"=="" (
  echo Dra Excel-filen Prosess.xlsm og slipp den oppa denne filen.
  pause
  exit /b
)
echo Sjekker at det appen trenger er installert ...
py -m pip install --user --disable-pip-version-check -q -r requirements.txt
if errorlevel 1 (
  echo.
  echo FEIL: Klarte ikke installere det appen trenger. Ta bilde av dette vinduet og send det.
  pause
  exit /b 1
)
py -m flask --app app importer-excel "%~1"
echo.
echo Se importrapport.txt for liste over feil i de gamle dataene.
pause
