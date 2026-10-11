@echo off
chcp 65001 >nul
cd /d "%~dp0"
if "%~1"=="" (
  echo Dra Excel-filen Prosess.xlsm og slipp den oppa denne filen.
  pause
  exit /b
)
if not exist .venv (
  py -m venv .venv 2>nul || python -m venv .venv
)
call .venv\Scripts\activate.bat
pip install -q -r requirements.txt
flask --app app importer-excel "%~1"
echo.
echo Se importrapport.txt for liste over feil i de gamle dataene.
pause
