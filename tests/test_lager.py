import pytest

from app import lager
from app.lager import Feil


def op(db, navn):
    return lager.finn_operasjon(db, navn)["id"]


def nytt(db, lotnr="0106230103", kg=360, stk=None):
    return lager.opprett_lot(db, lotnr=lotnr, dato="2023-02-06", prima_lotnr="x", spesifikasjon_id=1,
                             produkt_id=1, start_kg=kg, start_stk=stk)


def beholdning(db):
    return sorted((r["lotnr"], r["operasjon"], r["kg"], bool(r["er_rest"])) for r in lager.beholdning(db))


def test_nytt_lot_gir_label_kg(db):
    nytt(db)
    assert beholdning(db) == [("0106230103", "Label kg", 360, False)]


def test_samme_lot_kan_ikke_registreres_to_ganger(db):
    nytt(db)
    with pytest.raises(Feil, match="allerede registrert"):
        nytt(db)


def test_operasjon_krever_eksisterende_lot(db):
    with pytest.raises(Feil, match="finnes ikke"):
        lager.hent_lot(db, "9999999999")


def test_hel_flytting_nuller_forrige_steg_og_bokforer_letning(db):
    lid = nytt(db)
    h = lager.registrer_operasjon(db, lot_id=lid, operasjon_id=op(db, "Control kg"), kg=331)
    assert beholdning(db) == [("0106230103", "Control kg", 331, False)]
    assert db.execute("SELECT letning_kg FROM hendelser WHERE id = ?", (h,)).fetchone()[0] == 29


def test_delvis_flytting_i_kg_holder_rest_apen(db):
    lid = nytt(db, kg=300)
    lager.registrer_operasjon(db, lot_id=lid, operasjon_id=op(db, "Salt after kg"), kg=280)
    h = lager.registrer_operasjon(db, lot_id=lid, operasjon_id=op(db, "In dry 1"), kg=180, delvis=True, rest_kg=100)
    assert beholdning(db) == [("0106230103", "In dry 1", 180, False), ("0106230103", "Salt after kg", 100, True)]
    assert db.execute("SELECT letning_kg FROM hendelser WHERE id = ?", (h,)).fetchone()[0] == 0
    assert [r["lotnr"] for r in lager.beholdning(db, kun_rester=True)] == ["0106230103"]

    # Resten flyttes senere til samme steg: legges sammen med det som allerede er der
    rest = [p for p in lager.apne_posisjoner(db, lid) if p["operasjon"] == "Salt after kg"][0]
    lager.registrer_operasjon(db, lot_id=lid, operasjon_id=op(db, "In dry 1"), kg=95, kilde_posisjon_id=rest["id"])
    assert beholdning(db) == [("0106230103", "In dry 1", 275, False)]


def test_delvis_flytting_i_stk_regnes_om_til_kg(db):
    lid = nytt(db, kg=300, stk=30)
    lager.registrer_operasjon(db, lot_id=lid, operasjon_id=op(db, "In dry 1"), kg=190, stk=20,
                              delvis=True, rest_stk=10)
    assert beholdning(db) == [("0106230103", "In dry 1", 190, False), ("0106230103", "Label kg", 100, True)]
    rest = lager.apne_posisjoner(db, lid)[1]
    assert rest["stk"] == 10


def test_delvis_uten_rest_gir_feil(db):
    lid = nytt(db)
    with pytest.raises(Feil):
        lager.registrer_operasjon(db, lot_id=lid, operasjon_id=op(db, "In salt"), kg=100, delvis=True)
    with pytest.raises(Feil):
        lager.registrer_operasjon(db, lot_id=lid, operasjon_id=op(db, "In salt"), kg=100, delvis=True, rest_kg=500)


def test_solgt_forlater_lageret(db):
    lid = nytt(db)
    lager.registrer_operasjon(db, lot_id=lid, operasjon_id=op(db, "Sold"), kg=250)
    assert beholdning(db) == []


def test_svinn_trekkes_fra(db):
    lid = nytt(db)
    lager.registrer_svinn(db, lot_id=lid, kg=10)
    assert beholdning(db) == [("0106230103", "Label kg", 350, False)]
    with pytest.raises(Feil, match="større enn"):
        lager.registrer_svinn(db, lot_id=lid, kg=1000)


def test_omlotting_og_sporing(db):
    a = nytt(db, "0106230103", kg=100)
    b = nytt(db, "0106230203", kg=200)
    c = lager.opprett_lot(db, lotnr="0524230107", krev_felt=False)
    lager.registrer_operasjon(db, lot_id=c, fra_lot_id=a, operasjon_id=op(db, "Packed for sales"), kg=60,
                              delvis=True, rest_kg=40)
    lager.registrer_operasjon(db, lot_id=c, fra_lot_id=b, operasjon_id=op(db, "Packed for sales"), kg=200)
    assert beholdning(db) == [("0106230103", "Label kg", 40, False), ("0524230107", "Packed for sales", 260, False)]
    assert {r["lotnr"] for _, r in lager.sporing(db, c, "bakover")} == {"0106230103", "0106230203"}
    assert [r["lotnr"] for _, r in lager.sporing(db, a, "fremover")] == ["0524230107"]


def test_avslutt_rest(db):
    lid = nytt(db, kg=300)
    lager.registrer_operasjon(db, lot_id=lid, operasjon_id=op(db, "In dry 1"), kg=200, delvis=True, rest_kg=100)
    rest = lager.beholdning(db, kun_rester=True)[0]
    lager.avslutt_posisjon(db, posisjon_id=rest["id"], aarsak="telling")
    assert beholdning(db) == [("0106230103", "In dry 1", 200, False)]


def test_angre_gjenoppretter(db):
    lid = nytt(db, kg=300)
    h1 = lager.registrer_operasjon(db, lot_id=lid, operasjon_id=op(db, "In dry 1"), kg=200, delvis=True, rest_kg=100)
    h2 = lager.registrer_operasjon(db, lot_id=lid, operasjon_id=op(db, "Dried after kg"), kg=150)
    with pytest.raises(Feil, match="nyere"):
        lager.angre_hendelse(db, h1)
    lager.angre_hendelse(db, h2)
    lager.angre_hendelse(db, h1)
    assert beholdning(db) == [("0106230103", "Label kg", 300, False)]


def test_lotnr_forslag(db):
    assert lager.foresla_lotnr(db, "2023-02-06") == "01062301"
    nytt(db, "0106230103")
    nytt(db, "0106231104")
    assert lager.foresla_lotnr(db, "2023-02-06", "03") == "0106231203"


def test_operasjon_finnes_uavhengig_av_skrivemate(db):
    assert lager.finn_operasjon(db, "maturing Started ")["navn"] == "Maturing started"
    assert lager.finn_operasjon(db, "i salt")["navn"] == "In salt"
