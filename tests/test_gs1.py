from app import gs1


def test_prima_strekkode():
    d = gs1.tolk("0197024032300620310203630011220819152408181022081904721")
    assert d == {"gtin": "97024032300620", "netto_kg": 363.0, "prod_dato": "2022-08-19",
                 "best_for": "2024-08-18", "batch": "22081904721"}


def test_med_skilletegn_og_parenteser():
    d = gs1.tolk("0197024032300620" + "10ABC123\x1d" + "3103012345")
    assert d["batch"] == "ABC123" and d["netto_kg"] == 12.345
    d = gs1.tolk("(01)97024032300620(10)ABC(15)250100")
    assert d["batch"] == "ABC" and d["best_for"] == "2025-01-31"


def test_ikke_gs1():
    assert gs1.tolk("22081904721") == {}
    assert gs1.tolk("") == {}
