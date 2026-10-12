"""Forretningsreglene: registrering av lot, operasjoner, svinn, omlotting og beholdning.

Grunnidé: hvert lot har «posisjoner». En posisjon sier hvor mange kg av lotet som
ligger i et bestemt steg. Når lotet registreres i et nytt steg, tømmes forrige
posisjon (som standard helt), og differansen mellom kg som ble flyttet og kg som
ble veid i det nye steget bokføres som letning. Ved delvis flytting blir en rest
liggende åpen i forrige steg, og den telles med i beholdningen til den flyttes
videre eller avsluttes.
"""
from datetime import date

from . import gs1
from .db import naa


class Feil(Exception):
    """Feil som skal vises til brukeren (f.eks. «lotet finnes ikke»)."""


def normaliser(tekst):
    return " ".join(str(tekst).split()).casefold() if tekst is not None else ""


def _dato(verdi):
    if isinstance(verdi, date):
        return verdi.isoformat()
    if not verdi:
        return date.today().isoformat()
    try:
        return date.fromisoformat(str(verdi)[:10]).isoformat()
    except ValueError:
        raise Feil(f"Ugyldig dato: {verdi}")


def _tall(verdi, navn, heltall=False, tillat_tom=True):
    if verdi is None or (isinstance(verdi, str) and not verdi.strip()):
        if tillat_tom:
            return None
        raise Feil(f"{navn} må fylles ut.")
    try:
        tall = float(str(verdi).replace(",", ".").replace(" ", ""))
    except ValueError:
        raise Feil(f"{navn} må være et tall (fikk «{verdi}»).")
    if tall < 0:
        raise Feil(f"{navn} kan ikke være negativ.")
    if heltall:
        if tall != int(tall):
            raise Feil(f"{navn} må være et helt tall.")
        return int(tall)
    return round(tall, 3)


# ---------------------------------------------------------------- oppslag

def finn_lot(db, lotnr):
    if not lotnr:
        return None
    return db.execute("SELECT * FROM lots WHERE lotnr = ?", (str(lotnr).strip(),)).fetchone()


def hent_lot(db, lotnr):
    lot = finn_lot(db, lotnr)
    if lot is None:
        raise Feil(f"Lotnummer «{lotnr}» finnes ikke. Sjekk nummeret, eller registrer det som nytt lot først.")
    return lot


def finn_operasjon(db, navn_eller_id):
    if isinstance(navn_eller_id, int) or str(navn_eller_id).isdigit():
        return db.execute("SELECT * FROM operasjoner WHERE id = ?", (int(navn_eller_id),)).fetchone()
    navn = " ".join(str(navn_eller_id).split())
    rad = db.execute("SELECT * FROM operasjoner WHERE navn = ? OR kode = ?", (navn, navn)).fetchone()
    if rad is None:
        rad = db.execute("SELECT o.* FROM operasjon_alias a JOIN operasjoner o ON o.id = a.operasjon_id "
                         "WHERE a.alias = ?", (navn,)).fetchone()
    return rad


def apne_posisjoner(db, lot_id):
    return db.execute(
        "SELECT p.*, o.navn AS operasjon FROM posisjoner p JOIN operasjoner o ON o.id = p.operasjon_id "
        "WHERE p.lot_id = ? AND p.apen = 1 ORDER BY p.id DESC", (lot_id,)).fetchall()


def _posisjon(db, posisjon_id):
    return db.execute("SELECT * FROM posisjoner WHERE id = ?", (posisjon_id,)).fetchone()


# ---------------------------------------------------------------- registrering

def foresla_lotnr(db, dato=None, kode=""):
    """Internt lotnr er: ukedag(2) + uke(2) + år(2) + løpenr(2) + lotkode(2). Lotkoden bestemmer råvaren.

    F.eks. 0106230103 = mandag (01), uke 06, 2023, løpenr 01, lotkode 03.
    """
    d = date.fromisoformat(_dato(dato))
    aar, uke, ukedag = d.isocalendar()
    prefiks = f"{ukedag:02d}{uke:02d}{aar % 100:02d}"
    rader = db.execute("SELECT lotnr FROM lots WHERE lotnr LIKE ?", (prefiks + "%",)).fetchall()
    lopenr = [int(r["lotnr"][6:8]) for r in rader if r["lotnr"][6:8].isdigit()]
    neste = max(lopenr, default=0) + 1
    return f"{prefiks}{neste:02d}{kode or ''}"


def lotkode(db, lotnr):
    """Lotkoden (2 siste siffer) med tilhørende råvare, eller None hvis koden ikke er kjent."""
    if not lotnr or len(lotnr.strip()) < 2:
        return None
    return db.execute("SELECT k.*, r.navn AS raavare FROM lotkoder k LEFT JOIN raavarer r ON r.id = k.raavare_id "
                      "WHERE k.kode = ?", (lotnr.strip()[-2:],)).fetchone()


def opprett_lot(db, *, lotnr, dato=None, prima_lotnr=None, spesifikasjon_id=None, produkt_id=None,
                raavare_id=None, start_kg=None, start_stk=None, kommentar=None, bruker_id=None,
                mangler_mottak=False, kilde="app", krev_felt=True, valgt_lotkode=None):
    lotnr = (lotnr or "").strip()
    if not lotnr:
        raise Feil("Internt lotnr må fylles ut.")
    if any(c.isspace() for c in lotnr):
        raise Feil("Internt lotnr kan ikke inneholde mellomrom.")
    if finn_lot(db, lotnr):
        raise Feil(f"Lotnummer «{lotnr}» er allerede registrert. Et lot kan bare registreres én gang.")
    if valgt_lotkode and not lotnr.endswith(valgt_lotkode):
        raise Feil(f"Lotnummeret må slutte på {valgt_lotkode} (valgt lotkode/råvare).")
    kode = lotkode(db, lotnr)
    if krev_felt:
        if len(lotnr) != 10 or not lotnr.isdigit():
            raise Feil("Internt lotnr skal være 10 siffer (ukedag, uke, år, løpenr, lotkode).")
        if kode is None or not kode["aktiv"]:
            raise Feil(f"Lotkoden «{lotnr[-2:]}» (de to siste sifrene) er ukjent. Admin kan legge den til "
                       "under Admin → Lotkoder.")
    if kode is not None and kode["raavare_id"]:
        # Råvaren bestemmes av lotkoden
        if krev_felt and raavare_id and int(raavare_id) != kode["raavare_id"]:
            raise Feil(f"Lotkode {kode['kode']} hører til råvaren {kode['raavare']}, ikke valgt råvare.")
        raavare_id = kode["raavare_id"]
    dato = _dato(dato)
    start_kg = _tall(start_kg, "Startvekt (kg)")
    start_stk = _tall(start_stk, "Antall stk", heltall=True)
    if krev_felt:
        mangler = [navn for navn, verdi in (("Prima lotnr", prima_lotnr), ("Produktspesifikasjon", spesifikasjon_id),
                                            ("Ferdigprodukt", produkt_id), ("Startvekt (kg)", start_kg))
                   if verdi in (None, "")]
        if mangler:
            raise Feil("Fyll ut: " + ", ".join(mangler) + ".")
        if start_kg <= 0:
            raise Feil("Startvekt må være større enn 0.")
    info = gs1.tolk(prima_lotnr)
    cur = db.execute(
        "INSERT INTO lots (lotnr, mottatt_dato, prima_lotnr, gtin, gs1_netto_kg, gs1_prod_dato, gs1_best_for, "
        "gs1_batch, spesifikasjon_id, produkt_id, raavare_id, start_kg, start_stk, kommentar, mangler_mottak, "
        "registrert_av, registrert_tid) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (lotnr, dato, (prima_lotnr or "").strip() or None, info.get("gtin"), info.get("netto_kg"),
         info.get("prod_dato"), info.get("best_for"), info.get("batch"), spesifikasjon_id or None,
         produkt_id or None, raavare_id or None, start_kg, start_stk, kommentar or None,
         1 if mangler_mottak else 0, bruker_id, naa() if kilde == "app" else None))
    lot_id = cur.lastrowid
    if start_kg:
        label = finn_operasjon(db, "Label kg")
        registrer_operasjon(db, lot_id=lot_id, operasjon_id=label["id"], dato=dato, kg=start_kg,
                            stk=start_stk, bruker_id=bruker_id, kilde=kilde)
    return lot_id


def registrer_operasjon(db, *, lot_id, operasjon_id, dato=None, kg, stk=None, kilde_posisjon_id=None,
                        fra_lot_id=None, uten_kilde=False, delvis=False, rest_kg=None, rest_stk=None, kommentar=None,
                        bruker_id=None, kilde="app", tillat_null=False):
    """Registrer at (en del av) et lot er kommet til et nytt steg.

    - Uten fra_lot_id flyttes kg fra lotets egen nyeste åpne posisjon (eller valgt kilde_posisjon_id).
    - Med fra_lot_id er det en omlotting: kg tas fra et annet lot og legges inn i dette lotet.
    - delvis=True betyr at noe blir liggende igjen i kildeposisjonen (rest_kg eller rest_stk).
    """
    op = finn_operasjon(db, operasjon_id)
    if op is None:
        raise Feil("Velg en operasjon.")
    dato = _dato(dato)
    kg = _tall(kg, "Kg", tillat_tom=False)
    if kg == 0 and not tillat_null:
        raise Feil("Kg må være større enn 0.")
    stk = _tall(stk, "Antall stk", heltall=True)
    rest_kg = _tall(rest_kg, "Rest kg")
    rest_stk = _tall(rest_stk, "Rest stk", heltall=True)

    # Finn posisjonen kg-ene kommer fra
    kildelot_id = fra_lot_id or lot_id
    if fra_lot_id == lot_id:
        raise Feil("Fra-lot og til-lot kan ikke være det samme.")
    kildepos = None
    if kilde_posisjon_id:
        kildepos = _posisjon(db, kilde_posisjon_id)
        if kildepos is None or kildepos["lot_id"] != kildelot_id or not kildepos["apen"]:
            raise Feil("Valgt beholdning å flytte fra er ikke åpen lenger. Last siden på nytt.")
    elif not uten_kilde:
        apne = apne_posisjoner(db, kildelot_id)
        kildepos = apne[0] if apne else None
        if fra_lot_id and kildepos is None:
            raise Feil("Fra-lotet har ingen åpen beholdning å flytte fra.")
    if delvis and kildepos is None:
        raise Feil("Delvis flytting krever at lotet har en åpen beholdning å flytte fra.")

    letning = None
    kilde_for = (None, None, None)
    if kildepos is not None:
        for_kg, for_stk = kildepos["kg"], kildepos["stk"]
        kilde_for = (for_kg, for_stk, kildepos["apen"])
        if delvis:
            if rest_kg is None and rest_stk is not None:
                if not for_stk:
                    raise Feil("Kan ikke regne om stk til kg fordi antall stk i forrige steg ikke er registrert. "
                               "Oppgi rest i kg i stedet.")
                if rest_stk >= for_stk:
                    raise Feil(f"Rest stk ({rest_stk}) må være mindre enn antall i forrige steg ({for_stk}).")
                rest_kg = round(for_kg * rest_stk / for_stk, 3)
            if rest_kg is None:
                raise Feil("Ved delvis flytting må du oppgi hvor mye som blir igjen (kg eller stk).")
            if not 0 < rest_kg < for_kg:
                raise Feil(f"Rest må være mellom 0 og {for_kg:g} kg (det som ligger i forrige steg).")
            if rest_stk is None and for_stk and stk is not None:
                rest_stk = max(for_stk - stk, 0)
        else:
            rest_kg, rest_stk = 0.0, (0 if for_stk is not None else None)
        flyttet = round(for_kg - rest_kg, 3)
        letning = round(flyttet - kg, 3)
        db.execute("UPDATE posisjoner SET kg = ?, stk = ?, apen = ? WHERE id = ?",
                   (rest_kg, rest_stk, 1 if rest_kg > 0 else 0, kildepos["id"]))
    else:
        rest_kg = rest_stk = None

    # Legg kg-ene inn i det nye steget
    ny_pos = None
    opprettet = 0
    if op["type"] == "normal":
        ny_pos = db.execute("SELECT * FROM posisjoner WHERE lot_id = ? AND operasjon_id = ? AND apen = 1 "
                            "AND id IS NOT ? ORDER BY id DESC LIMIT 1",
                            (lot_id, op["id"], kildepos["id"] if kildepos else None)).fetchone()
    if ny_pos is not None:
        ny_stk = ny_pos["stk"] + stk if ny_pos["stk"] is not None and stk is not None else None
        db.execute("UPDATE posisjoner SET kg = kg + ?, stk = ? WHERE id = ?", (kg, ny_stk, ny_pos["id"]))
        ny_pos_id = ny_pos["id"]
    else:
        apen = 1 if op["type"] == "normal" and kg > 0 else 0
        ny_pos_id = db.execute("INSERT INTO posisjoner (lot_id, operasjon_id, kg, stk, apen) VALUES (?,?,?,?,?)",
                               (lot_id, op["id"], kg, stk, apen)).lastrowid
        opprettet = 1

    return db.execute(
        "INSERT INTO hendelser (lot_id, type, operasjon_id, dato, kg, stk, fra_lot_id, kilde_posisjon_id, "
        "kilde_for_kg, kilde_for_stk, kilde_for_apen, rest_kg, rest_stk, delvis, letning_kg, ny_posisjon_id, "
        "ny_posisjon_opprettet, kommentar, kilde, registrert_av, registrert_tid) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (lot_id, "omlotting" if fra_lot_id else "operasjon", op["id"], dato, kg, stk, fra_lot_id,
         kildepos["id"] if kildepos else None, *kilde_for, rest_kg, rest_stk, 1 if delvis else 0, letning,
         ny_pos_id, opprettet, kommentar or None, kilde, bruker_id, naa())).lastrowid


def registrer_svinn(db, *, lot_id, kg, dato=None, posisjon_id=None, stk=None, aarsak=None, kommentar=None,
                    bruker_id=None, kilde="app"):
    """Svinn trekkes fra beholdningen i steget lotet ligger i nå (eller valgt posisjon)."""
    dato = _dato(dato)
    kg = _tall(kg, "Kg", tillat_tom=False)
    stk = _tall(stk, "Antall stk", heltall=True)
    if kg == 0:
        raise Feil("Kg må være større enn 0.")
    if posisjon_id:
        pos = _posisjon(db, posisjon_id)
        if pos is None or pos["lot_id"] != lot_id or not pos["apen"]:
            raise Feil("Valgt beholdning er ikke åpen lenger. Last siden på nytt.")
    else:
        apne = apne_posisjoner(db, lot_id)
        if not apne:
            raise Feil("Lotet har ingen åpen beholdning å trekke svinn fra.")
        pos = apne[0]
    if kg > pos["kg"] + 1e-9:
        raise Feil(f"Svinn ({kg:g} kg) er større enn det som ligger i steget ({pos['kg']:g} kg).")
    ny_kg = round(pos["kg"] - kg, 3)
    ny_stk = pos["stk"] - stk if pos["stk"] is not None and stk is not None else pos["stk"]
    db.execute("UPDATE posisjoner SET kg = ?, stk = ?, apen = ? WHERE id = ?",
               (ny_kg, ny_stk, 1 if ny_kg > 0 else 0, pos["id"]))
    return db.execute(
        "INSERT INTO hendelser (lot_id, type, operasjon_id, dato, kg, stk, kilde_posisjon_id, kilde_for_kg, "
        "kilde_for_stk, kilde_for_apen, rest_kg, rest_stk, aarsak, kommentar, kilde, registrert_av, registrert_tid) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (lot_id, "svinn", pos["operasjon_id"], dato, kg, stk, pos["id"], pos["kg"], pos["stk"], pos["apen"],
         ny_kg, ny_stk, aarsak or None, kommentar or None, kilde, bruker_id, naa())).lastrowid


AVSLUTT_AARSAKER = {"letning": "Letning (vekttap)", "svinn": "Svinn", "telling": "Telleavvik / finnes ikke"}


def avslutt_posisjon(db, *, posisjon_id, dato=None, aarsak="letning", kommentar=None, bruker_id=None):
    """Lukk en åpen rest som ikke finnes fysisk lenger."""
    pos = _posisjon(db, posisjon_id)
    if pos is None or not pos["apen"]:
        raise Feil("Denne beholdningen er allerede avsluttet.")
    if aarsak not in AVSLUTT_AARSAKER:
        raise Feil("Velg årsak.")
    db.execute("UPDATE posisjoner SET kg = 0, stk = ?, apen = 0 WHERE id = ?",
               (0 if pos["stk"] is not None else None, pos["id"]))
    return db.execute(
        "INSERT INTO hendelser (lot_id, type, operasjon_id, dato, kg, stk, kilde_posisjon_id, kilde_for_kg, "
        "kilde_for_stk, kilde_for_apen, rest_kg, aarsak, kommentar, registrert_av, registrert_tid) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (pos["lot_id"], "avslutt", pos["operasjon_id"], _dato(dato), pos["kg"], pos["stk"], pos["id"],
         pos["kg"], pos["stk"], 1, 0, aarsak, kommentar or None, bruker_id, naa())).lastrowid


def angre_hendelse(db, hendelse_id, bruker_id=None):
    """Angre en registrering. Bare mulig hvis ingenting senere har brukt de samme posisjonene."""
    h = db.execute("SELECT * FROM hendelser WHERE id = ?", (hendelse_id,)).fetchone()
    if h is None or h["slettet"]:
        raise Feil("Registreringen finnes ikke eller er allerede angret.")
    berorte = [p for p in (h["kilde_posisjon_id"], h["ny_posisjon_id"]) if p]
    if berorte:
        senere = db.execute(
            f"SELECT COUNT(*) FROM hendelser WHERE id > ? AND slettet = 0 AND "
            f"(kilde_posisjon_id IN ({','.join('?' * len(berorte))}) OR ny_posisjon_id IN ({','.join('?' * len(berorte))}))",
            (h["id"], *berorte, *berorte)).fetchone()[0]
        if senere:
            raise Feil("Kan ikke angre: det er gjort nyere registreringer på samme lot/steg. Angre dem først.")
    if h["kilde_posisjon_id"]:
        db.execute("UPDATE posisjoner SET kg = ?, stk = ?, apen = ? WHERE id = ?",
                   (h["kilde_for_kg"], h["kilde_for_stk"], h["kilde_for_apen"], h["kilde_posisjon_id"]))
    if h["ny_posisjon_id"]:
        if h["ny_posisjon_opprettet"]:
            # Tidligere angrede registreringer kan fortsatt peke på posisjonen
            db.execute("UPDATE hendelser SET ny_posisjon_id = NULL WHERE ny_posisjon_id = ?", (h["ny_posisjon_id"],))
            db.execute("UPDATE hendelser SET kilde_posisjon_id = NULL WHERE kilde_posisjon_id = ?",
                       (h["ny_posisjon_id"],))
            db.execute("DELETE FROM posisjoner WHERE id = ?", (h["ny_posisjon_id"],))
        else:
            pos = _posisjon(db, h["ny_posisjon_id"])
            ny_stk = pos["stk"] - h["stk"] if pos["stk"] is not None and h["stk"] is not None else pos["stk"]
            db.execute("UPDATE posisjoner SET kg = kg - ?, stk = ? WHERE id = ?", (h["kg"], ny_stk, pos["id"]))
    db.execute("UPDATE hendelser SET slettet = 1, slettet_av = ?, slettet_tid = ? WHERE id = ?",
               (bruker_id, naa(), h["id"]))


# ---------------------------------------------------------------- oversikter

HENDELSE_SQL = """
SELECT h.*, o.navn AS operasjon, l.lotnr, fl.lotnr AS fra_lotnr, b.navn AS bruker
FROM hendelser h
JOIN lots l ON l.id = h.lot_id
LEFT JOIN operasjoner o ON o.id = h.operasjon_id
LEFT JOIN lots fl ON fl.id = h.fra_lot_id
LEFT JOIN brukere b ON b.id = h.registrert_av
"""


def historikk(db, lot_id):
    """Alle hendelser der lotet er med (også omlotting ut av lotet), eldste først."""
    return db.execute(HENDELSE_SQL + " WHERE (h.lot_id = ? OR h.fra_lot_id = ?) AND h.slettet = 0 "
                      "ORDER BY h.dato, h.id", (lot_id, lot_id)).fetchall()


def stegoversikt(db, lot):
    """Per operasjon: første dato, sum kg, utbytte mot startvekt og letning (som «Tidligere prosesser» i Excel)."""
    rader = db.execute(
        "SELECT o.navn AS operasjon, o.rekkefolge, MIN(h.dato) AS forste_dato, SUM(h.kg) AS kg, "
        "SUM(h.letning_kg) AS letning, SUM(h.stk) AS stk, COUNT(*) AS antall "
        "FROM hendelser h JOIN operasjoner o ON o.id = h.operasjon_id "
        "WHERE h.lot_id = ? AND h.type IN ('operasjon', 'omlotting') AND h.slettet = 0 "
        "GROUP BY o.id ORDER BY MIN(h.dato), MIN(h.id)", (lot["id"],)).fetchall()
    start = lot["start_kg"] or (rader[0]["kg"] if rader else None)
    ut = []
    for r in rader:
        d = dict(r)
        d["utbytte_start"] = (r["kg"] / start * 100) if start else None
        # Utbytte i steget = kg veid nå / kg som ble flyttet inn (= veid + letning).
        # Da blir det riktig også når bare en del av lotet ble flyttet.
        flyttet = (r["kg"] or 0) + (r["letning"] or 0)
        d["utbytte_steg"] = (r["kg"] / flyttet * 100) if r["letning"] is not None and flyttet else None
        ut.append(d)
    return ut


def sporing(db, lot_id, retning):
    """Følg omlottinger bakover (hvor kom kg fra) eller fremover (hvor gikk kg). Returnerer liste av (nivå, rad)."""
    sett = {lot_id}
    resultat = []

    def besok(lid, niva):
        if retning == "bakover":
            sql = ("SELECT h.dato, h.kg, l.id, l.lotnr FROM hendelser h JOIN lots l ON l.id = h.fra_lot_id "
                   "WHERE h.lot_id = ? AND h.fra_lot_id IS NOT NULL AND h.slettet = 0 ORDER BY h.dato")
        else:
            sql = ("SELECT h.dato, h.kg, l.id, l.lotnr FROM hendelser h JOIN lots l ON l.id = h.lot_id "
                   "WHERE h.fra_lot_id = ? AND h.slettet = 0 ORDER BY h.dato")
        for r in db.execute(sql, (lid,)).fetchall():
            resultat.append((niva, r))
            if r["id"] not in sett:
                sett.add(r["id"])
                besok(r["id"], niva + 1)

    besok(lot_id, 0)
    return resultat


BEHOLDNING_SQL = """
SELECT p.id, p.kg, p.stk, p.operasjon_id, o.navn AS operasjon, o.rekkefolge, l.id AS lot_id, l.lotnr,
       pr.navn AS produkt, pr.varenr, s.navn AS spesifikasjon,
       (SELECT MAX(h.dato) FROM hendelser h WHERE h.ny_posisjon_id = p.id AND h.slettet = 0) AS inn_dato,
       (p.id <> (SELECT MAX(p2.id) FROM posisjoner p2 WHERE p2.lot_id = p.lot_id)) AS er_rest
FROM posisjoner p
JOIN lots l ON l.id = p.lot_id
JOIN operasjoner o ON o.id = p.operasjon_id
LEFT JOIN produkter pr ON pr.id = l.produkt_id
LEFT JOIN spesifikasjoner s ON s.id = l.spesifikasjon_id
WHERE p.apen = 1 AND p.kg > 0
"""


def beholdning(db, kun_rester=False, operasjon_id=None, produkt_id=None):
    sql = "SELECT * FROM (" + BEHOLDNING_SQL + ") WHERE 1=1"
    param = []
    if kun_rester:
        sql += " AND er_rest = 1"
    if operasjon_id:
        sql += " AND operasjon_id = ?"
        param.append(operasjon_id)
    if produkt_id:
        sql += " AND lot_id IN (SELECT id FROM lots WHERE produkt_id = ?)"
        param.append(produkt_id)
    return db.execute(sql + " ORDER BY rekkefolge, produkt, lotnr", param).fetchall()
