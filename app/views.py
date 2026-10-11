"""Skjermbildene i appen."""
import csv
import functools
import io
import secrets
from datetime import date

from flask import (Blueprint, Response, abort, flash, g, jsonify, redirect, render_template, request, session,
                   url_for)
from werkzeug.security import check_password_hash, generate_password_hash

from . import gs1, lager
from .db import get_db, lag_kode
from .lager import Feil

bp = Blueprint("app", __name__)


# ---------------------------------------------------------------- innlogging og sikkerhet

@bp.before_app_request
def last_bruker():
    bruker_id = session.get("bruker_id")
    g.bruker = None
    if bruker_id:
        g.bruker = get_db().execute("SELECT * FROM brukere WHERE id = ? AND aktiv = 1", (bruker_id,)).fetchone()
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    if request.method == "POST" and request.form.get("csrf") != session["csrf"]:
        abort(400, "Skjemaet er utløpt. Gå tilbake og last siden på nytt.")


@bp.app_context_processor
def felles():
    return {"csrf": session.get("csrf"), "i_dag": date.today().isoformat()}


@bp.app_template_filter("kg")
def kg_filter(verdi):
    if verdi is None:
        return ""
    return f"{verdi:,.1f}".replace(",", " ").replace(".", ",")


@bp.app_template_filter("pst")
def pst_filter(verdi):
    return "" if verdi is None else f"{verdi:.1f} %".replace(".", ",")


@bp.app_template_filter("dato")
def dato_filter(verdi):
    if not verdi:
        return ""
    s = str(verdi)
    return f"{s[8:10]}.{s[5:7]}.{s[0:4]}" + (f" {s[11:16]}" if len(s) > 10 else "")


def innlogget(view):
    @functools.wraps(view)
    def wrapped(**kwargs):
        if g.bruker is None:
            return redirect(url_for("app.logg_inn", neste=request.full_path))
        return view(**kwargs)
    return wrapped


def admin(view):
    @functools.wraps(view)
    def wrapped(**kwargs):
        if g.bruker is None:
            return redirect(url_for("app.logg_inn"))
        if g.bruker["rolle"] != "admin":
            abort(403)
        return view(**kwargs)
    return wrapped


@bp.route("/logg-inn", methods=["GET", "POST"])
def logg_inn():
    if request.method == "POST":
        bruker = get_db().execute("SELECT * FROM brukere WHERE brukernavn = ? AND aktiv = 1",
                                  (request.form.get("brukernavn", "").strip(),)).fetchone()
        if bruker and check_password_hash(bruker["passord_hash"], request.form.get("passord", "")):
            csrf = session.get("csrf")
            session.clear()
            session["csrf"] = csrf
            session["bruker_id"] = bruker["id"]
            session.permanent = True
            neste = request.args.get("neste", "")
            return redirect(neste if neste.startswith("/") and not neste.startswith("//") else url_for("app.hjem"))
        flash("Feil brukernavn eller passord.", "feil")
    return render_template("logg_inn.html")


@bp.route("/logg-ut", methods=["POST"])
def logg_ut():
    session.clear()
    return redirect(url_for("app.logg_inn"))


@bp.route("/passord", methods=["GET", "POST"])
@innlogget
def bytt_passord():
    if request.method == "POST":
        if not check_password_hash(g.bruker["passord_hash"], request.form.get("gammelt", "")):
            flash("Nåværende passord er feil.", "feil")
        elif len(request.form.get("nytt", "")) < 4:
            flash("Nytt passord må ha minst 4 tegn.", "feil")
        elif request.form["nytt"] != request.form.get("nytt2"):
            flash("De to nye passordene er ikke like.", "feil")
        else:
            db = get_db()
            db.execute("UPDATE brukere SET passord_hash = ? WHERE id = ?",
                       (generate_password_hash(request.form["nytt"]), g.bruker["id"]))
            db.commit()
            flash("Passordet er byttet.", "ok")
            return redirect(url_for("app.hjem"))
    return render_template("passord.html")


# ---------------------------------------------------------------- hjelpere

def stamdata(db):
    return {
        "operasjoner": db.execute("SELECT * FROM operasjoner WHERE aktiv = 1 ORDER BY rekkefolge").fetchall(),
        "spesifikasjoner": db.execute("SELECT * FROM spesifikasjoner WHERE aktiv = 1 ORDER BY navn").fetchall(),
        "produkter": db.execute("SELECT * FROM produkter WHERE aktiv = 1 ORDER BY navn").fetchall(),
        "raavarer": db.execute("SELECT * FROM raavarer WHERE aktiv = 1 ORDER BY navn").fetchall(),
    }


def lotinfo(db, lotnr):
    """Lot med åpne posisjoner og kort historikk, til visning ved registrering."""
    lot = lager.finn_lot(db, lotnr)
    if lot is None:
        return None
    return {
        "lot": lot,
        "detaljer": lot_detaljer(db, lot["id"]),
        "apne": lager.apne_posisjoner(db, lot["id"]),
        "steg": lager.stegoversikt(db, lot),
    }


def lot_detaljer(db, lot_id):
    return db.execute(
        "SELECT l.*, s.navn AS spesifikasjon, p.navn AS produkt, p.varenr, r.navn AS raavare, b.navn AS bruker "
        "FROM lots l LEFT JOIN spesifikasjoner s ON s.id = l.spesifikasjon_id "
        "LEFT JOIN produkter p ON p.id = l.produkt_id LEFT JOIN raavarer r ON r.id = l.raavare_id "
        "LEFT JOIN brukere b ON b.id = l.registrert_av WHERE l.id = ?", (lot_id,)).fetchone()


def lagre(handling, suksess):
    """Kjør en registrering. Ved feil vises meldingen og ingenting lagres."""
    db = get_db()
    try:
        resultat = handling(db)
        db.commit()
        flash(suksess, "ok")
        return resultat, True
    except Feil as e:
        db.rollback()
        flash(str(e), "feil")
        return None, False


# ---------------------------------------------------------------- forside

@bp.route("/")
@innlogget
def hjem():
    db = get_db()
    siste = db.execute(lager.HENDELSE_SQL + " WHERE h.slettet = 0 AND h.kilde = 'app' "
                       "ORDER BY h.id DESC LIMIT 15").fetchall()
    antall_rester = db.execute("SELECT COUNT(*) FROM (" + lager.BEHOLDNING_SQL + ") WHERE er_rest = 1").fetchone()[0]
    return render_template("hjem.html", siste=siste, antall_rester=antall_rester)


@bp.route("/sok")
@innlogget
def sok():
    q = request.args.get("q", "").strip()
    db = get_db()
    if q and lager.finn_lot(db, q):
        return redirect(url_for("app.lot", lotnr=q))
    info = gs1.tolk(q)
    if info.get("batch"):
        treff = db.execute("SELECT lotnr FROM lots WHERE prima_lotnr = ? OR gs1_batch = ?", (q, info["batch"])).fetchall()
    else:
        treff = db.execute("SELECT lotnr FROM lots WHERE lotnr LIKE ? OR prima_lotnr LIKE ? ORDER BY lotnr DESC "
                           "LIMIT 200", (f"%{q}%", f"%{q}%")).fetchall() if q else []
    if len(treff) == 1:
        return redirect(url_for("app.lot", lotnr=treff[0]["lotnr"]))
    return redirect(url_for("app.lots", q=q))


# ---------------------------------------------------------------- Input 1: nytt lot

@bp.route("/lot/ny", methods=["GET", "POST"])
@innlogget
def nytt_lot():
    db = get_db()
    skjema = request.form if request.method == "POST" else {}
    if request.method == "POST":
        lot_id, ok = lagre(lambda db: lager.opprett_lot(
            db, lotnr=skjema.get("lotnr"), dato=skjema.get("dato"), prima_lotnr=skjema.get("prima_lotnr"),
            spesifikasjon_id=skjema.get("spesifikasjon_id"), produkt_id=skjema.get("produkt_id"),
            raavare_id=skjema.get("raavare_id"), start_kg=skjema.get("start_kg"), start_stk=skjema.get("start_stk"),
            kommentar=skjema.get("kommentar"), bruker_id=g.bruker["id"]),
            f"Lot {skjema.get('lotnr', '').strip()} er registrert.")
        if ok:
            # Behold dato, spesifikasjon og produkt så neste lot fra samme leveranse går fort
            return redirect(url_for("app.nytt_lot", dato=skjema.get("dato"),
                                    spesifikasjon_id=skjema.get("spesifikasjon_id"),
                                    produkt_id=skjema.get("produkt_id"), raavare_id=skjema.get("raavare_id"),
                                    prima_lotnr=skjema.get("prima_lotnr")))
    else:
        skjema = request.args
    forslag = lager.foresla_lotnr(db, skjema.get("dato") or None)
    return render_template("nytt_lot.html", skjema=skjema, forslag=forslag, **stamdata(db))


@bp.route("/api/gs1")
@innlogget
def api_gs1():
    return jsonify(gs1.tolk(request.args.get("kode", "")))


@bp.route("/api/lotnr-forslag")
@innlogget
def api_lotnr_forslag():
    db = get_db()
    raavare = db.execute("SELECT lotkode FROM raavarer WHERE id = ?", (request.args.get("raavare_id") or 0,)).fetchone()
    try:
        return jsonify(forslag=lager.foresla_lotnr(db, request.args.get("dato") or None,
                                                   raavare["lotkode"] if raavare else ""))
    except Feil:
        return jsonify(forslag="")


# ---------------------------------------------------------------- Input 2: operasjon

@bp.route("/operasjon", methods=["GET", "POST"])
@innlogget
def operasjon():
    db = get_db()
    skjema = request.form if request.method == "POST" else request.args
    lotnr = skjema.get("lotnr", "").strip()
    if request.method == "POST" and "lagre" in skjema:
        lot = lager.finn_lot(db, lotnr)

        def handling(db):
            if lot is None:
                lager.hent_lot(db, lotnr)
            return lager.registrer_operasjon(
                db, lot_id=lot["id"], operasjon_id=skjema.get("operasjon_id"), dato=skjema.get("dato"),
                kg=skjema.get("kg"), stk=skjema.get("stk"), kilde_posisjon_id=skjema.get("kilde_posisjon_id"),
                delvis=bool(skjema.get("delvis")), rest_kg=skjema.get("rest_kg"), rest_stk=skjema.get("rest_stk"),
                kommentar=skjema.get("kommentar"), bruker_id=g.bruker["id"])
        hid, ok = lagre(handling, f"Registrert på lot {lotnr}.")
        if ok:
            return redirect(url_for("app.operasjon", dato=skjema.get("dato"), operasjon_id=skjema.get("operasjon_id"),
                                    sist=hid))
    info = lotinfo(db, lotnr) if lotnr else None
    if lotnr and info is None:
        flash(f"Lotnummer «{lotnr}» finnes ikke.", "feil")
    sist = None
    if request.args.get("sist"):
        sist = db.execute(lager.HENDELSE_SQL + " WHERE h.id = ?", (request.args["sist"],)).fetchone()
    return render_template("operasjon.html", skjema=skjema, info=info, sist=sist, **stamdata(db))


# ---------------------------------------------------------------- Input 3: svinn

@bp.route("/svinn", methods=["GET", "POST"])
@innlogget
def svinn():
    db = get_db()
    skjema = request.form if request.method == "POST" else request.args
    lotnr = skjema.get("lotnr", "").strip()
    if request.method == "POST" and "lagre" in skjema:
        def handling(db):
            lot = lager.hent_lot(db, lotnr)
            return lager.registrer_svinn(db, lot_id=lot["id"], kg=skjema.get("kg"), stk=skjema.get("stk"),
                                         dato=skjema.get("dato"), posisjon_id=skjema.get("kilde_posisjon_id"),
                                         aarsak=skjema.get("aarsak"), kommentar=skjema.get("kommentar"),
                                         bruker_id=g.bruker["id"])
        _, ok = lagre(handling, f"Svinn registrert på lot {lotnr}.")
        if ok:
            return redirect(url_for("app.svinn", dato=skjema.get("dato"), lotnr=lotnr))
    info = lotinfo(db, lotnr) if lotnr else None
    if lotnr and info is None:
        flash(f"Lotnummer «{lotnr}» finnes ikke.", "feil")
    return render_template("svinn.html", skjema=skjema, info=info)


# ---------------------------------------------------------------- Input 4: omlotting

@bp.route("/omlotting", methods=["GET", "POST"])
@innlogget
def omlotting():
    db = get_db()
    skjema = request.form if request.method == "POST" else request.args
    fra_lotnr = skjema.get("fra_lotnr", "").strip()
    til_lotnr = skjema.get("til_lotnr", "").strip()
    if request.method == "POST" and "lagre" in skjema:
        def handling(db):
            fra = lager.hent_lot(db, fra_lotnr)
            til = lager.finn_lot(db, til_lotnr)
            if til is None:
                if not skjema.get("opprett_til"):
                    raise Feil(f"Til-lot «{til_lotnr}» finnes ikke. Kryss av for «Opprett nytt lot» "
                               "hvis det skal lages nå.")
                til_id = lager.opprett_lot(db, lotnr=til_lotnr, dato=skjema.get("dato"),
                                           spesifikasjon_id=fra["spesifikasjon_id"], produkt_id=fra["produkt_id"],
                                           raavare_id=fra["raavare_id"], bruker_id=g.bruker["id"],
                                           kommentar=f"Opprettet ved omlotting fra {fra_lotnr}", krev_felt=False)
            else:
                til_id = til["id"]
            return lager.registrer_operasjon(
                db, lot_id=til_id, fra_lot_id=fra["id"], operasjon_id=skjema.get("operasjon_id"),
                dato=skjema.get("dato"), kg=skjema.get("kg"), stk=skjema.get("stk"),
                kilde_posisjon_id=skjema.get("kilde_posisjon_id"), delvis=bool(skjema.get("delvis")),
                rest_kg=skjema.get("rest_kg"), rest_stk=skjema.get("rest_stk"),
                kommentar=skjema.get("kommentar"), bruker_id=g.bruker["id"])
        _, ok = lagre(handling, f"Omlottet fra {fra_lotnr} til {til_lotnr}.")
        if ok:
            return redirect(url_for("app.omlotting", dato=skjema.get("dato"), til_lotnr=til_lotnr,
                                    operasjon_id=skjema.get("operasjon_id")))
    info = lotinfo(db, fra_lotnr) if fra_lotnr else None
    if fra_lotnr and info is None:
        flash(f"Lotnummer «{fra_lotnr}» finnes ikke.", "feil")
    til_finnes = bool(lager.finn_lot(db, til_lotnr)) if til_lotnr else None
    return render_template("omlotting.html", skjema=skjema, info=info, til_finnes=til_finnes, **stamdata(db))


# ---------------------------------------------------------------- lotvisning

@bp.route("/lot/<lotnr>")
@innlogget
def lot(lotnr):
    db = get_db()
    info = lotinfo(db, lotnr)
    if info is None:
        abort(404)
    lot_id = info["lot"]["id"]
    return render_template("lot.html", **info, historikk=lager.historikk(db, lot_id),
                           bakover=lager.sporing(db, lot_id, "bakover"),
                           fremover=lager.sporing(db, lot_id, "fremover"),
                           aarsaker=lager.AVSLUTT_AARSAKER, gs1=gs1.tolk(info["lot"]["prima_lotnr"]))


@bp.route("/posisjon/<int:posisjon_id>/avslutt", methods=["POST"])
@innlogget
def avslutt(posisjon_id):
    db = get_db()
    pos = db.execute("SELECT l.lotnr FROM posisjoner p JOIN lots l ON l.id = p.lot_id WHERE p.id = ?",
                     (posisjon_id,)).fetchone()
    if pos is None:
        abort(404)
    lagre(lambda db: lager.avslutt_posisjon(db, posisjon_id=posisjon_id, dato=request.form.get("dato"),
                                            aarsak=request.form.get("aarsak"), kommentar=request.form.get("kommentar"),
                                            bruker_id=g.bruker["id"]), "Resten er avsluttet.")
    return redirect(request.form.get("tilbake") or url_for("app.lot", lotnr=pos["lotnr"]))


@bp.route("/hendelse/<int:hendelse_id>/angre", methods=["POST"])
@innlogget
def angre(hendelse_id):
    db = get_db()
    h = db.execute("SELECT h.*, l.lotnr FROM hendelser h JOIN lots l ON l.id = h.lot_id WHERE h.id = ?",
                   (hendelse_id,)).fetchone()
    if h is None:
        abort(404)
    if g.bruker["rolle"] != "admin" and h["registrert_av"] != g.bruker["id"]:
        flash("Du kan bare angre dine egne registreringer.", "feil")
    else:
        lagre(lambda db: lager.angre_hendelse(db, hendelse_id, g.bruker["id"]), "Registreringen er angret.")
    return redirect(request.form.get("tilbake") or url_for("app.lot", lotnr=h["lotnr"]))


@bp.route("/lots")
@innlogget
def lots():
    db = get_db()
    q = request.args.get("q", "").strip()
    sql = ("SELECT l.*, p.navn AS produkt, s.navn AS spesifikasjon, "
           "(SELECT o.navn FROM posisjoner po JOIN operasjoner o ON o.id = po.operasjon_id "
           " WHERE po.lot_id = l.id ORDER BY po.id DESC LIMIT 1) AS siste_steg, "
           "(SELECT SUM(kg) FROM posisjoner po WHERE po.lot_id = l.id AND po.apen = 1) AS beholdning "
           "FROM lots l LEFT JOIN produkter p ON p.id = l.produkt_id "
           "LEFT JOIN spesifikasjoner s ON s.id = l.spesifikasjon_id ")
    if q:
        rader = db.execute(sql + "WHERE l.lotnr LIKE ? OR l.prima_lotnr LIKE ? OR p.navn LIKE ? "
                           "ORDER BY l.mottatt_dato DESC, l.lotnr DESC LIMIT 300", (f"%{q}%",) * 3).fetchall()
    else:
        rader = db.execute(sql + "ORDER BY l.mottatt_dato DESC, l.lotnr DESC LIMIT 100").fetchall()
    return render_template("lots.html", rader=rader, q=q)


# ---------------------------------------------------------------- beholdning og telling

@bp.route("/beholdning")
@innlogget
def beholdning():
    db = get_db()
    kun_rester = request.args.get("vis") == "rester"
    rader = lager.beholdning(db, kun_rester=kun_rester, operasjon_id=request.args.get("operasjon_id") or None,
                             produkt_id=request.args.get("produkt_id") or None)
    if request.args.get("format") == "csv":
        ut = io.StringIO()
        w = csv.writer(ut, delimiter=";")
        w.writerow(["Lotnr", "Steg", "Produkt", "Varenr", "Spesifikasjon", "Kg", "Stk", "Inn i steget", "Åpen rest"])
        for r in rader:
            w.writerow([r["lotnr"], r["operasjon"], r["produkt"], r["varenr"], r["spesifikasjon"],
                        str(r["kg"]).replace(".", ","), r["stk"] or "", r["inn_dato"], "ja" if r["er_rest"] else ""])
        return Response("﻿" + ut.getvalue(), mimetype="text/csv",
                        headers={"Content-Disposition": f"attachment; filename=beholdning_{date.today()}.csv"})
    sum_steg = {}
    for r in rader:
        s = sum_steg.setdefault(r["operasjon"], {"kg": 0, "stk": 0, "lot": set(), "rest_kg": 0})
        s["kg"] += r["kg"]
        s["stk"] += r["stk"] or 0
        s["lot"].add(r["lotnr"])
        if r["er_rest"]:
            s["rest_kg"] += r["kg"]
    sum_produkt = {}
    for r in rader:
        nokkel = (r["produkt"] or "(uten produkt)", r["varenr"] or "")
        sum_produkt[nokkel] = sum_produkt.get(nokkel, 0) + r["kg"]
    return render_template("beholdning.html", rader=rader, sum_steg=sum_steg, sum_produkt=sum_produkt,
                           kun_rester=kun_rester, aarsaker=lager.AVSLUTT_AARSAKER, **stamdata(db))


@bp.route("/registreringer")
@innlogget
def registreringer():
    db = get_db()
    fra = request.args.get("fra") or date.today().replace(day=1).isoformat()
    til = request.args.get("til") or date.today().isoformat()
    rader = db.execute(lager.HENDELSE_SQL + " WHERE h.dato BETWEEN ? AND ? AND h.slettet = 0 "
                       "ORDER BY h.dato DESC, h.id DESC LIMIT 2000", (fra, til)).fetchall()
    if request.args.get("format") == "csv":
        ut = io.StringIO()
        w = csv.writer(ut, delimiter=";")
        w.writerow(["Dato", "Lotnr", "Type", "Operasjon", "Kg", "Stk", "Fra lot", "Delvis", "Rest kg", "Letning kg",
                    "Kommentar", "Registrert av", "Registrert tid"])
        for r in rader:
            w.writerow([r["dato"], r["lotnr"], r["type"], r["operasjon"], str(r["kg"]).replace(".", ","),
                        r["stk"] or "", r["fra_lotnr"] or "", "ja" if r["delvis"] else "",
                        "" if r["rest_kg"] is None else str(r["rest_kg"]).replace(".", ","),
                        "" if r["letning_kg"] is None else str(r["letning_kg"]).replace(".", ","),
                        r["kommentar"] or "", r["bruker"] or "", r["registrert_tid"] or ""])
        return Response("﻿" + ut.getvalue(), mimetype="text/csv",
                        headers={"Content-Disposition": f"attachment; filename=registreringer_{fra}_{til}.csv"})
    return render_template("registreringer.html", rader=rader, fra=fra, til=til)


# ---------------------------------------------------------------- admin: stamdata og brukere

STAMDATA = {
    "operasjoner": {"tittel": "Operasjoner", "felt": [("navn", "Navn"), ("type", "Type"), ("rekkefolge", "Rekkefølge")],
                    "sortering": "rekkefolge"},
    "produkter": {"tittel": "Ferdigprodukter", "felt": [("navn", "Navn"), ("varenr", "Varenr")], "sortering": "navn"},
    "spesifikasjoner": {"tittel": "Produktspesifikasjoner", "felt": [("navn", "Navn")], "sortering": "navn"},
    "raavarer": {"tittel": "Råvaretyper", "felt": [("navn", "Navn"), ("lotkode", "Lotkode (2 siste siffer)")],
                 "sortering": "navn"},
}


@bp.route("/admin/<tabell>", methods=["GET", "POST"])
@admin
def stamdata_admin(tabell):
    if tabell not in STAMDATA:
        abort(404)
    oppsett = STAMDATA[tabell]
    db = get_db()
    if request.method == "POST":
        felt = [f for f, _ in oppsett["felt"]]
        verdier = [(request.form.get(f) or "").strip() or None for f in felt]
        aktiv = 1 if request.form.get("aktiv") else 0
        rad_id = request.form.get("id")
        if not verdier[0]:
            flash("Navn må fylles ut.", "feil")
        elif tabell == "operasjoner" and verdier[1] not in ("normal", "ut"):
            flash("Type må være «normal» eller «ut».", "feil")
        else:
            try:
                if rad_id:
                    db.execute(f"UPDATE {tabell} SET {', '.join(f + ' = ?' for f in felt)}, aktiv = ? WHERE id = ?",
                               (*verdier, aktiv, rad_id))
                else:
                    ekstra_kol, ekstra_verdi = ([", kode"], [lag_kode(verdier[0])]) \
                        if tabell == "operasjoner" else ([], [])
                    db.execute(f"INSERT INTO {tabell} ({', '.join(felt)}{''.join(ekstra_kol)}) "
                               f"VALUES ({', '.join('?' * (len(felt) + len(ekstra_verdi)))})", (*verdier, *ekstra_verdi))
                db.commit()
                flash("Lagret.", "ok")
            except Exception as e:  # typisk: navnet finnes fra før
                db.rollback()
                flash(f"Kunne ikke lagre: {e}", "feil")
        return redirect(url_for("app.stamdata_admin", tabell=tabell))
    rader = db.execute(f"SELECT * FROM {tabell} ORDER BY aktiv DESC, {oppsett['sortering']}").fetchall()
    return render_template("stamdata.html", tabell=tabell, oppsett=oppsett, rader=rader, alle=STAMDATA)


@bp.route("/admin/brukere", methods=["GET", "POST"])
@admin
def brukere():
    db = get_db()
    if request.method == "POST":
        f = request.form
        try:
            if f.get("id"):
                db.execute("UPDATE brukere SET navn = ?, rolle = ?, aktiv = ? WHERE id = ?",
                           (f["navn"], f["rolle"], 1 if f.get("aktiv") else 0, f["id"]))
                if f.get("passord"):
                    db.execute("UPDATE brukere SET passord_hash = ? WHERE id = ?",
                               (generate_password_hash(f["passord"]), f["id"]))
            else:
                if not (f.get("brukernavn") and f.get("navn") and f.get("passord")):
                    raise Feil("Fyll ut brukernavn, navn og passord.")
                db.execute("INSERT INTO brukere (brukernavn, navn, passord_hash, rolle) VALUES (?, ?, ?, ?)",
                           (f["brukernavn"].strip(), f["navn"].strip(), generate_password_hash(f["passord"]),
                            f.get("rolle", "operator")))
            db.commit()
            flash("Lagret.", "ok")
        except Exception as e:
            db.rollback()
            flash(f"Kunne ikke lagre: {e}", "feil")
        return redirect(url_for("app.brukere"))
    return render_template("brukere.html", rader=db.execute("SELECT * FROM brukere ORDER BY navn").fetchall(),
                           alle=STAMDATA)
