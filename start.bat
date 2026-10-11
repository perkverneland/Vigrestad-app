@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist .venv (
  echo Forste gang: installerer det appen trenger. Dette tar et minutt...
  py -m venv .venv 2>nul || python -m venv .venv
)
call .venv\Scripts\activate.bat
pip install -q -r requirements.txt
if not exist instance\vigrestad.db (
  flask --app app init-db
)
flask --app app backup
echo.
echo  Appen kjorer. Apne nettleseren og ga til:  http://localhost:8000
echo  Fra andre PC-er/nettbrett: http://%COMPUTERNAME%:8000
echo  IKKE lukk dette vinduet - da stopper appen.
echo.
start "" http://localhost:8000
waitress-serve --port=8000 --call app:create_app
pause
