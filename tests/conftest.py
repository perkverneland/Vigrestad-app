import pytest

from app import create_app
from app.db import koble_til, opprett_tabeller


@pytest.fixture
def app(tmp_path):
    sti = str(tmp_path / "test.db")
    opprett_tabeller(koble_til(sti))
    return create_app({"DATABASE": sti, "TESTING": True})


@pytest.fixture
def db(tmp_path):
    db = koble_til(str(tmp_path / "logikk.db"))
    opprett_tabeller(db)
    return db
