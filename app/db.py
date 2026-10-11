"""Tilkobling til databasen (én SQLite-fil) og startdata."""
import re
import sqlite3
from datetime import datetime

import click
from flask import current_app, g
from werkzeug.security import generate_password_hash

# Operasjonene fra arket «Lister», i normal produksjonsrekkefølge.
OPERASJONER = [
    "Label kg", "Control kg", "In salt", "Salt after kg", "Frozen saltet material",
    "Defrost raw kg", "Deboned after kg", "Maturing started", "Water fenalår kg",
    "In smoke", "In dry 1", "In dry 2", "In dry 3", "In dry 4", "In dry hangingroom",
    "Toma dry", "Smoked after kg", "Dried after kg", "Dried after smoked kg",
    "Cut after kg", "Water after kg", "Frozen", "Defrost kg", "Packed for sales",
    "Sold", "Kassert",
]
UT_AV_LAGER = {"Sold", "Kassert"}
OPERASJON_ALIAS = {"i salt": "In salt"}

SPESIFIKASJONER = ["Premium", "Norsk", "Cats", "Standard", "Jæren smak",
                   "Lam side m/bein", "FjellLam", "Bog u/nitritt", "ASK"]
RAAVARER = ["Pinnekjøtt", "Lammelår", "Bryst/nakke", "Bog", "Forpart", "Avkapp"]
PRODUKTER = [
    ("Røkt pinnekjøtt", "14327"), ("Tørket pinnekjøtt", "14320"), ("Unil fenalår", "1171"),
    ("Folkets Gryteklar", "1173"), ("First Price", "1172"), ("Saltet pinnekjøtt", "14000"),
    ("Finsbråten tørket pinnekjøtt", "14346"), ("Fenalår", "32015"), ("Toma røkt", "14361"),
    ("Saltet pinnebog", "14001"), ("Tørket pinnebog", "14322"),
    ("Jacobs pinnekjøtt urøkt", "1145"), ("Jacobs pinnekjøtt røkt", "1146"),
    ("Jacobs pinnebog", "1168"), ("Jacobs helt pinnekjøtt urøkt", "1174"),
    ("Jacobs helt pinnekjøtt røkt", "1175"), ("Finsbråten røkt pinnekjøtt", "14352"),
    ("Toma fenalår", "32016"), ("Saltet fenalår", "14003"), ("Pinnekjøtt uten nitritt", "14348"),
    ("Pinnesteik", "14364"), ("Utvannet bryst/nakke", "14368"), ("Bog u/nitritt", "14370"),
    ("Ask pinnekjøtt med bog", "14367"),
]


def lag_kode(navn):
    kode = navn.upper().replace("Æ", "AE").replace("Ø", "O").replace("Å", "AA")
    return re.sub(r"[^A-Z0-9]+", "_", kode).strip("_")


def get_db():
    if "db" not in g:
        g.db = koble_til(current_app.config["DATABASE"])
    return g.db


def koble_til(sti):
    db = sqlite3.connect(sti, detect_types=0)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.execute("PRAGMA journal_mode = WAL")
    return db


def close_db(e=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def opprett_tabeller(db, admin_passord="admin"):
    from importlib.resources import files
    db.executescript(files("app").joinpath("schema.sql").read_text(encoding="utf-8"))
    for i, navn in enumerate(OPERASJONER):
        db.execute(
            "INSERT INTO operasjoner (kode, navn, type, rekkefolge) VALUES (?, ?, ?, ?)",
            (lag_kode(navn), navn, "ut" if navn in UT_AV_LAGER else "normal", (i + 1) * 10),
        )
    for alias, navn in OPERASJON_ALIAS.items():
        db.execute("INSERT INTO operasjon_alias (alias, operasjon_id) "
                   "SELECT ?, id FROM operasjoner WHERE navn = ?", (alias, navn))
    db.executemany("INSERT INTO spesifikasjoner (navn) VALUES (?)", [(s,) for s in SPESIFIKASJONER])
    db.executemany("INSERT INTO raavarer (navn) VALUES (?)", [(r,) for r in RAAVARER])
    db.executemany("INSERT INTO produkter (navn, varenr) VALUES (?, ?)", PRODUKTER)
    db.execute(
        "INSERT INTO brukere (brukernavn, navn, passord_hash, rolle) VALUES (?, ?, ?, 'admin')",
        ("admin", "Administrator", generate_password_hash(admin_passord)),
    )
    db.commit()


def naa():
    return datetime.now().isoformat(timespec="seconds")


@click.command("init-db")
def init_db_command():
    """Lag en ny, tom database (sletter ikke en eksisterende)."""
    import os
    sti = current_app.config["DATABASE"]
    if os.path.exists(sti):
        raise click.ClickException(f"Databasen finnes allerede: {sti}")
    db = koble_til(sti)
    opprett_tabeller(db)
    click.echo(f"Ny database laget: {sti}")
    click.echo("Logg inn med brukernavn «admin» og passord «admin», og bytt passordet med en gang.")


@click.command("importer-excel")
@click.argument("excelfil")
@click.option("--rapport", default="importrapport.txt", help="Fil som får liste over avvik i dataene.")
def importer_excel_command(excelfil, rapport):
    """Lag ny database fra Prosess.xlsm (gamle data)."""
    import os
    from .importer import importer
    sti = current_app.config["DATABASE"]
    if os.path.exists(sti):
        raise click.ClickException(f"Databasen finnes allerede: {sti}. Flytt eller slett den først.")
    db = koble_til(sti)
    opprett_tabeller(db)
    linjer = importer(db, excelfil, logg=click.echo)
    with open(rapport, "w", encoding="utf-8") as f:
        f.write("\n".join(linjer) + "\n")
    click.echo(f"Ferdig. Avviksrapport skrevet til {rapport}")


@click.command("backup")
def backup_command():
    """Ta en sikkerhetskopi av databasen til mappen «backup» (én per dag, beholder de siste 60)."""
    import os
    from datetime import date
    sti = current_app.config["DATABASE"]
    if not os.path.exists(sti):
        return
    mappe = os.path.join(os.path.dirname(current_app.instance_path), "backup")
    os.makedirs(mappe, exist_ok=True)
    maal = os.path.join(mappe, f"vigrestad_{date.today().isoformat()}.db")
    if not os.path.exists(maal):
        kilde, kopi = koble_til(sti), sqlite3.connect(maal)
        kilde.backup(kopi)
        kopi.close()
        kilde.close()
        click.echo(f"Sikkerhetskopi lagret: {maal}")
    gamle = sorted(f for f in os.listdir(mappe) if f.startswith("vigrestad_") and f.endswith(".db"))
    for f in gamle[:-60]:
        os.remove(os.path.join(mappe, f))


def init_app(app):
    app.teardown_appcontext(close_db)
    app.cli.add_command(init_db_command)
    app.cli.add_command(importer_excel_command)
    app.cli.add_command(backup_command)
