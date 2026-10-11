#!/bin/sh
# Start appen på Mac/Linux. Bruk start.bat på Windows.
cd "$(dirname "$0")"
[ -d .venv ] || python3 -m venv .venv
. .venv/bin/activate
pip install -q -r requirements.txt
[ -f instance/vigrestad.db ] || flask --app app init-db
flask --app app backup
echo "Appen kjører på http://localhost:8000 (Ctrl+C stopper den)"
exec waitress-serve --port=8000 --call app:create_app
