-- Databasestruktur for Vigrestad lot-sporing.
-- Tabellene tilsvarer arkene i Prosess.xlsm, men med faste ID-er i stedet for fritekst.

CREATE TABLE brukere (
    id            INTEGER PRIMARY KEY,
    brukernavn    TEXT NOT NULL UNIQUE COLLATE NOCASE,
    navn          TEXT NOT NULL,
    passord_hash  TEXT NOT NULL,
    rolle         TEXT NOT NULL DEFAULT 'operator' CHECK (rolle IN ('admin', 'operator')),
    aktiv         INTEGER NOT NULL DEFAULT 1
);

-- Stamdata (arket «Lister»)
CREATE TABLE operasjoner (
    id          INTEGER PRIMARY KEY,
    kode        TEXT NOT NULL UNIQUE,
    navn        TEXT NOT NULL UNIQUE COLLATE NOCASE,
    -- 'normal': varen ligger på lager i dette steget. 'ut': varen forlater lageret (solgt, kassert).
    type        TEXT NOT NULL DEFAULT 'normal' CHECK (type IN ('normal', 'ut')),
    rekkefolge  INTEGER NOT NULL DEFAULT 0,
    aktiv       INTEGER NOT NULL DEFAULT 1
);

-- Alternative skrivemåter brukt i gamle data (f.eks. «i salt» = «In salt»)
CREATE TABLE operasjon_alias (
    alias         TEXT PRIMARY KEY COLLATE NOCASE,
    operasjon_id  INTEGER NOT NULL REFERENCES operasjoner(id)
);

CREATE TABLE spesifikasjoner (
    id     INTEGER PRIMARY KEY,
    navn   TEXT NOT NULL UNIQUE COLLATE NOCASE,
    aktiv  INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE raavarer (
    id       INTEGER PRIMARY KEY,
    navn     TEXT NOT NULL UNIQUE COLLATE NOCASE,
    lotkode  TEXT,              -- de to siste sifrene i internt lotnr, hvis det er fast per råvare
    aktiv    INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE produkter (
    id      INTEGER PRIMARY KEY,
    navn    TEXT NOT NULL UNIQUE COLLATE NOCASE,
    varenr  TEXT,
    aktiv   INTEGER NOT NULL DEFAULT 1
);

-- Ett lot = én råvareenhet med internt lotnummer (arket «Database Lot»)
CREATE TABLE lots (
    id                INTEGER PRIMARY KEY,
    lotnr             TEXT NOT NULL UNIQUE,
    mottatt_dato      TEXT,
    prima_lotnr       TEXT,
    gtin              TEXT,
    gs1_netto_kg      REAL,
    gs1_prod_dato     TEXT,
    gs1_best_for      TEXT,
    gs1_batch         TEXT,
    spesifikasjon_id  INTEGER REFERENCES spesifikasjoner(id),
    produkt_id        INTEGER REFERENCES produkter(id),
    raavare_id        INTEGER REFERENCES raavarer(id),
    start_kg          REAL,
    start_stk         INTEGER,
    kommentar         TEXT,
    -- 1 = lotet dukket opp i operasjonsloggen uten mottaksregistrering (gamle data / omlotting)
    mangler_mottak    INTEGER NOT NULL DEFAULT 0,
    registrert_av     INTEGER REFERENCES brukere(id),
    registrert_tid    TEXT
);

-- En posisjon er «så mange kg av lot X som ligger i steg Y akkurat nå».
-- Åpne posisjoner er beholdningen. Et lot har normalt én åpen posisjon,
-- men ved delvis flytting blir det liggende en åpen rest i forrige steg.
CREATE TABLE posisjoner (
    id            INTEGER PRIMARY KEY,
    lot_id        INTEGER NOT NULL REFERENCES lots(id),
    operasjon_id  INTEGER NOT NULL REFERENCES operasjoner(id),
    kg            REAL NOT NULL,
    stk           INTEGER,
    apen          INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX posisjoner_lot ON posisjoner(lot_id);
CREATE INDEX posisjoner_apen ON posisjoner(apen);

-- Alt som skjer med et lot (arkene «Database Operasjon», «Database Svinn», «Database Korrigering»).
CREATE TABLE hendelser (
    id                 INTEGER PRIMARY KEY,
    lot_id             INTEGER NOT NULL REFERENCES lots(id),
    type               TEXT NOT NULL CHECK (type IN ('operasjon', 'omlotting', 'svinn', 'avslutt')),
    operasjon_id       INTEGER REFERENCES operasjoner(id),
    dato               TEXT NOT NULL,
    kg                 REAL NOT NULL,
    stk                INTEGER,
    -- Ved omlotting: lotet kg-ene kom fra
    fra_lot_id         INTEGER REFERENCES lots(id),
    -- Posisjonen kg-ene ble tatt fra, og hvordan den så ut før
    kilde_posisjon_id  INTEGER REFERENCES posisjoner(id),
    kilde_for_kg       REAL,
    kilde_for_stk      INTEGER,
    kilde_for_apen     INTEGER,
    rest_kg            REAL,
    rest_stk           INTEGER,
    delvis             INTEGER NOT NULL DEFAULT 0,
    letning_kg         REAL,
    -- Posisjonen kg-ene havnet i (ny eller slått sammen med eksisterende)
    ny_posisjon_id     INTEGER REFERENCES posisjoner(id),
    ny_posisjon_opprettet INTEGER NOT NULL DEFAULT 0,
    aarsak             TEXT,
    kommentar          TEXT,
    kilde              TEXT NOT NULL DEFAULT 'app' CHECK (kilde IN ('app', 'import')),
    registrert_av      INTEGER REFERENCES brukere(id),
    registrert_tid     TEXT,
    slettet            INTEGER NOT NULL DEFAULT 0,
    slettet_av         INTEGER REFERENCES brukere(id),
    slettet_tid        TEXT
);
CREATE INDEX hendelser_lot ON hendelser(lot_id);
CREATE INDEX hendelser_fra_lot ON hendelser(fra_lot_id);
CREATE INDEX hendelser_dato ON hendelser(dato);
