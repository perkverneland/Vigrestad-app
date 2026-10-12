import re


def logg_inn(klient):
    side = klient.get("/logg-inn").get_data(as_text=True)
    csrf = re.search(r'name="csrf" value="([^"]+)"', side).group(1)
    klient.post("/logg-inn", data={"brukernavn": "admin", "passord": "admin", "csrf": csrf})
    return csrf


def test_hele_flyten(app):
    k = app.test_client()
    assert k.get("/").status_code == 302
    csrf = logg_inn(k)
    for side in ["/", "/lot/ny", "/operasjon", "/svinn", "/omlotting", "/beholdning", "/beholdning?vis=rester",
                 "/lots", "/registreringer", "/admin/operasjoner", "/admin/produkter", "/admin/lotkoder", "/admin/brukere"]:
        assert k.get(side).status_code == 200, side

    r = k.post("/lot/ny", data={"csrf": csrf, "dato": "2026-10-12", "lotnr": "0142260101",
                                "prima_lotnr": "0197024032300620310203630011220819152408181022081904721",
                                "spesifikasjon_id": "1", "produkt_id": "1", "start_kg": "363", "lotkode": "01"},
               follow_redirects=True)
    assert "er registrert" in r.get_data(as_text=True)
    r = k.post("/lot/ny", data={"csrf": csrf, "dato": "2026-10-12", "lotnr": "0142260101", "prima_lotnr": "x",
                                "spesifikasjon_id": "1", "produkt_id": "1", "start_kg": "363"}, follow_redirects=True)
    assert "allerede registrert" in r.get_data(as_text=True)

    assert "0142260101" in k.get("/operasjon?lotnr=0142260101").get_data(as_text=True)
    r = k.post("/operasjon", data={"csrf": csrf, "lagre": "1", "lotnr": "0142260101", "dato": "2026-10-12",
                                   "operasjon_id": "2", "kg": "350,5", "delvis": "1", "rest_kg": "10"},
               follow_redirects=True)
    assert "Registrert på lot" in r.get_data(as_text=True)
    side = k.get("/beholdning?vis=rester").get_data(as_text=True)
    assert "0142260101" in side and "åpen rest" in side
    assert k.get("/lot/0142260101").status_code == 200
    assert k.get("/beholdning?format=csv").status_code == 200

    r = k.post("/omlotting", data={"csrf": csrf, "lagre": "1", "fra_lotnr": "0142260101", "til_lotnr": "0142269907",
                                   "operasjon_id": "24", "kg": "300", "opprett_til": "1"}, follow_redirects=True)
    assert "Omlottet" in r.get_data(as_text=True)
    assert "0142260101" in k.get("/lot/0142269907").get_data(as_text=True)


def test_post_uten_csrf_avvises(app):
    k = app.test_client()
    logg_inn(k)
    assert k.post("/lot/ny", data={"lotnr": "1"}).status_code == 400


def test_lotkode_koblet_til_raavare_oppdaterer_gamle_lot(app):
    from app.db import koble_til
    from app import lager
    db = koble_til(app.config["DATABASE"])
    lager.opprett_lot(db, lotnr="0106230199", krev_felt=False)
    db.commit()
    k = app.test_client()
    csrf = logg_inn(k)
    kode = db.execute("SELECT id FROM lotkoder WHERE kode = '99'").fetchone()[0]
    k.post("/admin/lotkoder", data={"csrf": csrf, "id": kode, "kode": "99", "raavare_id": "1", "aktiv": "1"})
    assert db.execute("SELECT raavare_id FROM lots WHERE lotnr = '0106230199'").fetchone()[0] == 1
