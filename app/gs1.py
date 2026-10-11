"""Tolking av GS1-128-strekkoder fra leverandøren (Prima lotnr).

Eksempel: 0197024032300620310203630011220819152408181022081904721
  (01) 97024032300620   GTIN
  (3102) 036300         nettovekt 363,00 kg
  (11) 220819           produksjonsdato 19.08.2022
  (15) 240818           best før 18.08.2024
  (10) 22081904721      batch/lot
"""
import calendar
import re
from datetime import date

GS = "\x1d"  # skilletegn (FNC1) som noen skannere sender etter felt med variabel lengde

# AI -> (navn, fast lengde eller None for variabel, makslengde)
FASTE = {
    "00": ("sscc", 18), "01": ("gtin", 14), "02": ("innhold_gtin", 14),
    "11": ("prod_dato", 6), "12": ("forfall_dato", 6), "13": ("pakket_dato", 6),
    "15": ("best_for", 6), "16": ("salg_innen", 6), "17": ("utlop", 6),
}
VARIABLE = {"10": ("batch", 20), "21": ("serienr", 20), "37": ("antall", 8), "30": ("antall_var", 8)}

DATOFELT = {"prod_dato", "forfall_dato", "pakket_dato", "best_for", "salg_innen", "utlop"}


def _dato(yymmdd):
    yy, mm, dd = int(yymmdd[:2]), int(yymmdd[2:4]), int(yymmdd[4:6])
    if not 1 <= mm <= 12:
        return None
    aar = 2000 + yy if yy < 50 else 1900 + yy
    if dd == 0:  # GS1: dag 00 betyr siste dag i måneden
        dd = calendar.monthrange(aar, mm)[1]
    try:
        return date(aar, mm, dd).isoformat()
    except ValueError:
        return None


def tolk(kode):
    """Returnerer dict med felt som ble funnet. Tom dict hvis koden ikke er GS1."""
    if not kode:
        return {}
    s = kode.strip()
    # Støtt også lesbar form «(01)123...(10)ABC»
    if s.startswith("("):
        deler = re.findall(r"\((\d{2,4})\)([^(]*)", s)
        s = "".join(ai + verdi + (GS if ai[:2] in VARIABLE else "") for ai, verdi in deler)
    s = s.replace("]C1", "")  # symbol-ID som enkelte skannere legger først
    resultat = {}
    i = 0
    while i < len(s):
        if s[i] == GS:
            i += 1
            continue
        ai2 = s[i:i + 2]
        ai4 = s[i:i + 4]
        if ai2 in FASTE:
            navn, lengde = FASTE[ai2]
            verdi = s[i + 2:i + 2 + lengde]
            if len(verdi) != lengde or not verdi.isdigit():
                return resultat if resultat else {}
            resultat[navn] = _dato(verdi) if navn in DATOFELT else verdi
            i += 2 + lengde
        elif re.fullmatch(r"31[0-6]\d|33[0-6]\d", ai4 or ""):
            verdi = s[i + 4:i + 10]
            if len(verdi) != 6 or not verdi.isdigit():
                return resultat if resultat else {}
            desimaler = int(ai4[3])
            kg = int(verdi) / (10 ** desimaler)
            # 310n = nettovekt kg, 330n = bruttovekt kg
            resultat["netto_kg" if ai4.startswith("310") else
                     "brutto_kg" if ai4.startswith("330") else "maal_" + ai4] = kg
            i += 10
        elif ai2 in VARIABLE:
            navn, maks = VARIABLE[ai2]
            slutt = s.find(GS, i + 2)
            if slutt == -1:
                slutt = len(s)
            verdi = s[i + 2:min(slutt, i + 2 + maks)]
            resultat[navn] = int(verdi) if navn.startswith("antall") and verdi.isdigit() else verdi
            i = i + 2 + len(verdi)
        else:
            # Ukjent AI: vi kan ikke vite hvor feltet slutter, så vi stopper her.
            break
    if "gtin" not in resultat and "sscc" not in resultat:
        return {}
    return resultat
