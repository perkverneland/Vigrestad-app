@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Sjekker at det appen trenger er installert ...
py -m pip install --user --disable-pip-version-check --no-warn-script-location -q -r requirements.txt
if errorlevel 1 (
  echo.
  echo FEIL: Klarte ikke installere det appen trenger. Ta bilde av dette vinduet og send det.
  pause
  exit /b 1
)
if not exist instance\vigrestad.db (
  py -m flask --app app init-db
)
py -m flask --app app backup
echo.
echo  Appen kjorer. Apne nettleseren og ga til:  http://localhost:8000
echo  Fra andre PC-er/nettbrett: http://%COMPUTERNAME%:8000
echo  IKKE lukk dette vinduet - da stopper appen.
echo.
start "" http://localhost:8000
py -m waitress --port=8000 --call app:create_app
echo.
echo Appen stoppet. Ta bilde av dette vinduet hvis det star en feilmelding over.
pause
