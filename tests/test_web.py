"""Web-API: Fehlerbehandlung, Anmeldung per Einladung, Rechte."""
import time

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
    assert r["step"] == "code" and r["name"] == "Mama" and r["email"] == "m***@example.de"
    assert not r["schon_verschickt"] and r["gueltig_bis"] > time.time() + 9 * 60
    assert fam.mails.messages[-1]["To"] == "mama@example.de"


def test_einladung_annehmen_meldet_an(fam, client):
    sign_in(fam, client, "Mama")
    assert post(client, "/api/einladung", name="Gisela", email="g@example.de").json() == \
        {"name": "Gisela", "email": "g@example.de"}
    link = fam.mails.last_text()
    token = link.split("#einladung=")[1].split()[0]

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


def test_gueltiger_code_wird_nicht_ersetzt(fam, client):
    """Fenster zu, Name nochmal eingegeben: der Code aus der ersten Mail gilt weiter."""
    first = post(client, "/api/login/start", name="Papa").json()
    code = next(w for w in fam.mails.last_text().split() if w.isdigit() and len(w) == 6)
    again = post(client, "/api/login/start", name="papa").json()
    assert again["schon_verschickt"] and again["gueltig_bis"] == first["gueltig_bis"] and len(fam.mails.messages) == 1
    assert post(client, "/api/login/verify", name="Papa", code=code).json() == {"name": "Papa"}


def test_neuer_code_auf_wunsch(fam, client):
    post(client, "/api/login/start", name="Papa")
    fam.reset_mail_limit()
    r = post(client, "/api/login/start", name="Papa", resend=True).json()
    assert r["step"] == "code" and not r["schon_verschickt"] and len(fam.mails.messages) == 2


def test_abgelaufener_code_wird_neu_verschickt(fam, client):
    post(client, "/api/login/start", name="Papa")
    fam.db.execute("UPDATE otp_codes SET expires_at = 0")
    fam.reset_mail_limit()
    assert not post(client, "/api/login/start", name="Papa").json()["schon_verschickt"]
    assert len(fam.mails.messages) == 2


def test_anmelde_knopf_in_der_mail(fam, client):
    post(client, "/api/login/start", name="Lena")
    text = fam.mails.last_text()
    token = text.split("#anmelden=")[1].split()[0]
    assert "anmelden=" in fam.mails.messages[-1].get_body(("html",)).get_content()
    assert post(client, "/api/login/link", token=token).json() == {"name": "Lena"}    # Vorschau, kein Login
    assert client.get("/api/me").status_code == 401
    assert post(client, "/api/login/link/accept", token=token).json() == {"name": "Lena"}
    assert client.get("/api/me").json()["name"] == "Lena"
    assert post(client, "/api/login/link", token=token).status_code == 404


def test_neue_version_kommt_sofort_im_browser_an(tmp_path, client):
    """Startseite und Dateien werden immer nachgefragt; Skript/Stylesheet tragen ihren Inhalts-Hash."""
    from app.web.static_assets import IndexPage
    (tmp_path / "dist").mkdir()
    (tmp_path / "dist" / "app.js").write_text("console.log(1)")
    (tmp_path / "index.html").write_text('<link href="/static/style.css"><script src="/static/dist/app.js"></script>')
    html = IndexPage(tmp_path).response().body.decode()
    assert '<script src="/static/dist/app.js?v=' in html and 'href="/static/style.css"' in html  # fehlt → ohne v
    (tmp_path / "dist" / "app.js").write_text("console.log(2)")
    assert IndexPage(tmp_path).response().body.decode() != html

    r = client.get("/")
    assert r.headers["cache-control"] == "no-cache" and 'href="/static/style.css?v=' in r.text
    assert client.get("/static/style.css").headers["cache-control"] == "no-cache"
