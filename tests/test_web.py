"""Web-API: Fehlerbehandlung, Anmeldung per Einladung, Rechte."""
import pytest
from fastapi.testclient import TestClient

from app.web import create_app
from tests.conftest import Family


@pytest.fixture
def fam(tmp_path):
    return Family(tmp_path / "web.db", admin_email="mama@example.de", cookie_secure=False)   # Testclient: http


@pytest.fixture
def client(fam):
    return TestClient(create_app(fam.c))


def post(client, path, **body):
    return client.post(path, json=body)


def sign_in(fam, client, name):
    client.cookies.set("geschenke_session", fam.c.sessions.start(fam.person(name)))


def test_nur_json(client):
    assert client.post("/api/login/start", data={"name": "Mama"}).status_code == 415


def test_ungueltiger_name_ist_400(client):
    r = post(client, "/api/login/start", name="123")
    assert r.status_code == 400 and "Buchstaben" in r.json()["detail"]


def test_login_start_schritte(fam, client):
    assert post(client, "/api/login/start", name="Oma").json() == {"step": "register", "name": "Oma"}
    r = post(client, "/api/login/start", name="mama").json()
    assert r == {"step": "code", "email": "m***@example.de"}
    assert fam.mails.messages[-1]["To"] == "mama@example.de"


def test_einladung_annehmen_meldet_an(fam, client):
    sign_in(fam, client, "Mama")
    assert post(client, "/api/einladung", name="Gisela", email="g@example.de").json() == \
        {"name": "Gisela", "email": "g@example.de"}
    link = fam.mails.last_text()
    token = link.split("?einladung=")[1].split()[0]

    client.cookies.clear()
    assert post(client, "/api/login/invite", token=token).json() == {"name": "Gisela", "eingeladen_von": "Mama"}
    assert post(client, "/api/login/invite/accept", token=token).json() == {"name": "Gisela"}
    assert client.get("/api/me").json()["name"] == "Gisela"
    assert post(client, "/api/login/invite/accept", token=token).status_code == 404


def test_fehlversuche_sperren_ip(client):
    for _ in range(10):
        assert post(client, "/api/login/invite", token="falsch").status_code == 404
    assert post(client, "/api/login/invite", token="falsch").status_code == 429


def test_familie_und_admin_rechte(fam, client):
    assert client.get("/api/familie").status_code == 401
    sign_in(fam, client, "Papa")
    family = client.get("/api/familie").json()
    assert {"name": "Papa", "status": "registriert", "du": True, "beziehung": None} in family
    assert post(client, "/api/admin/person-entfernen", name="Oma").status_code == 403

    sign_in(fam, client, "Mama")
    assert client.get("/api/me").json()["admin"] is True
    r = post(client, "/api/admin/person-entfernen", name="Oma")
    assert r.json() == {"name": "Oma", "wuensche_geloescht": 0, "reservierungen_freigegeben": 0}
    assert post(client, "/api/admin/person-entfernen", name="Mama").status_code == 403


def test_person_ohne_login_anlegen(fam, client):
    assert post(client, "/api/person", name="Paul").status_code == 401
    sign_in(fam, client, "Lena")
    assert post(client, "/api/person", name="Paul").json() == {"name": "Paul"}
    assert post(client, "/api/person", name="paul").status_code == 409
    assert post(client, "/api/person", name="!").status_code == 400
    assert {"name": "Paul", "status": "offen", "du": False, "beziehung": None} in client.get("/api/familie").json()


def test_einladen_nur_admin(fam, client):
    sign_in(fam, client, "Papa")
    assert post(client, "/api/einladung", name="Gisela", email="g@example.de").status_code == 403
    sign_in(fam, client, "Mama")
    assert post(client, "/api/einladung", name="Oma", email="oma@example.de").json() == \
        {"name": "Oma", "email": "oma@example.de"}
