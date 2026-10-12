# Vigrestad lot-sporing

En app som erstatter Excel-arket `Prosess.xlsm`. Den holder styr på hvert lot fra mottak
til salg: hvilke steg det har vært gjennom, hvor mye det veide, hvor mye det har lettet,
og hvor mye som ligger på lager akkurat nå.

## Hvordan appen er bygget (forklart enkelt)

Tenk på appen som en **kokebok med tre deler**:

| Del | Hva det er | Hvor det ligger |
|---|---|---|
| **Databasen** | «Arkene» der alle tall lagres. Erstatter Database Lot / Operasjon / Svinn / Korrigering. | Én fil: `instance/vigrestad.db` |
| **Reglene** | Det som regner ut letning, delvis flytting, beholdning osv. | `app/lager.py` |
| **Skjermbildene** | Det du ser i nettleseren. Erstatter Input 1–4. | `app/templates/` |

Appen kjører på **én PC** (f.eks. kontor-PC-en). Alle andre – PC-er, nettbrett og mobiler
på samme nettverk – åpner den i **nettleseren**. Ingen trenger å installere noe annet enn
på den ene PC-en.

## Kom i gang (Windows)

1. **Installer Python** (gratis) fra <https://www.python.org/downloads/>.
   Viktig: kryss av for **«Add python.exe to PATH»** nederst i installasjonsvinduet.
2. **Last ned appen** fra GitHub (grønn «Code»-knapp → «Download ZIP») og pakk ut mappen,
   f.eks. til `C:\Vigrestad-app`.
3. **Flytt over de gamle dataene** (bare første gang): Dra `Prosess.xlsm` og slipp den
   oppå filen `importer.bat`. Etterpå finner du `importrapport.txt` med liste over feil som
   ble funnet i de gamle dataene.
   (Vil du starte helt tomt, hopper du over dette steget.)
4. **Start appen**: dobbeltklikk `start.bat`. Nettleseren åpnes av seg selv.
   Det svarte vinduet må stå åpent – lukker du det, stopper appen.
5. **Logg inn** med brukernavn `admin` og passord `admin`. Klikk på navnet ditt øverst til
   høyre og **bytt passord med en gang**. Gå til *Admin → Brukere* og lag en bruker til hver
   som skal registrere.

Fra andre maskiner skriver du `http://NAVN-PÅ-PC-EN:8000` i nettleseren
(navnet står i det svarte vinduet). Hvis det ikke virker, må Windows-brannmuren slippe
gjennom port 8000 – spør den som har ansvar for IT.

### Strekkodeskanner
En vanlig USB- eller Bluetooth-skanner fungerer som et tastatur: klikk i feltet og skann.
I «Nytt lot» tolkes Prima-strekkoden (GS1) automatisk: GTIN, nettovekt, produksjonsdato,
best før og batch vises under feltet, og nettovekten fylles inn som startvekt.

### Sikkerhetskopi
Hver gang appen startes, lagres en kopi av databasen i mappen `backup` (én per dag, de siste
60 dagene). Kopier gjerne `backup`-mappen til OneDrive/server av og til.

## Skjermbildene

| I Excel | I appen | Hva den gjør |
|---|---|---|
| Input 1 | **Nytt lot** | Mottak: Prima lotnr (skann), råvare/lotkode, internt lotnr (fylles ut automatisk), spesifikasjon, ferdigprodukt, startvekt (blir «Label kg»). Stopper hvis lotnummeret finnes fra før. |
| Input 2 | **Operasjon** | Skann lot → velg operasjon → kg. Viser historikk og utbytte. Stopper hvis lotet ikke finnes. |
| Input 3 | **Svinn** | Trekker svinn fra beholdningen i steget lotet ligger i. |
| Input 4 | **Omlotting** | Flytter kg fra ett lot til et annet og registrerer neste operasjon på til-lotet. |
| – | **Beholdning** | Telling/lageroversikt per steg og per ferdigprodukt. Kan lastes ned til Excel. |
| – | **Åpne rester** | Lot der en del ble liggende igjen i et tidligere steg. |
| – | **Lot** | Søk, og full historikk per lot med utbytte, letning og sporing bakover/fremover. |
| – | **Registreringer** | Alt som er registrert i en periode, med hvem og når. Kan lastes ned til Excel. |
| Lister | **Admin** | Operasjoner, produkter, spesifikasjoner, råvarer og brukere. |

## Slik regnes beholdningen

- Hvert lot ligger i ett **steg** (f.eks. «In dry 1») med et antall kg.
- Når lotet registreres i et nytt steg, **tømmes forrige steg**. Forskjellen mellom kg som ble
  flyttet og kg som ble veid i det nye steget lagres som **letning**.
- Er det bare **en del** av lotet som flyttes, krysser du av for **«Delvis flytting»** og
  skriver hvor mye som blir igjen (kg eller stk). Resten blir liggende **åpen** i forrige steg
  og telles med i beholdningen til den flyttes videre eller avsluttes.
- **Sold** og **Kassert** betyr at varen forlater lageret.
- En rest som ikke finnes fysisk lenger, avsluttes med knappen «Avslutt» (årsak: letning,
  svinn eller telleavvik).
- Har du registrert feil, kan du trykke **«Angre»** på registreringen i lotets historikk
  (den siste først). Angrede registreringer blir ikke slettet, bare skjult, så sporbarheten
  er intakt.

## Internt lotnummer
Dataene viser at lotnummeret (f.eks. `0106230103`) er bygget slik:

| 01 | 06 | 23 | 01 | 03 |
|---|---|---|---|---|
| ukedag (mandag = 01) | ukenummer | år | løpenummer den dagen | lotkode (råvare) |

De to siste sifrene er **lotkoden**, og den bestemmer råvaren (flere koder kan høre til samme
råvare, f.eks. 01, 11, 21 og 31 = pinnekjøtt). I «Nytt lot» velger du råvare/lotkode, og appen
fyller ut hele lotnummeret med neste ledige løpenummer for dagen. Lotkoder som ikke er avklart
ennå, kobles til riktig råvare under *Admin → Lotkoder* – da får også gamle lot med den koden
riktig råvare.

## For den som skal videreutvikle
```
pip install -r requirements-dev.txt
pytest                     # kjører testene
flask --app app run --debug  # starter i utviklingsmodus
```
