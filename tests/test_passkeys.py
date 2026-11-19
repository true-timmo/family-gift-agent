"""Anmeldung mit Face ID (Passkeys)."""
import pytest
from fastapi.testclient import TestClient

from app.domain.errors import AuthenticationError, NotFoundError, PermissionDeniedError
from app.web import create_app
from tests.conftest import Family
from tests.soft_authenticator import SoftAuthenticator


@pytest.fixture
def phone():
    return SoftAuthenticator()


def set_up(fam, phone, name="Mama"):
    person = fam.person(name)
    options = fam.c.passkeys.registration_options(person)
    fam.c.passkeys.register(person, phone.create(options), "iPhone")


def test_einrichten_und_anmelden(fam, phone):
    set_up(fam, phone)
    options = fam.c.passkeys.login_options(None)                       # Knopf ohne Namen
    assert options["userVerification"] == "required" and not options.get("allowCredentials")
    assert fam.c.passkeys.login(phone.get(options)).name == "Mama"
    options = fam.c.passkeys.login_options("mama")                     # nach Namenseingabe
    assert len(options["allowCredentials"]) == 1
    assert fam.c.passkeys.login(phone.get(options)).name == "Mama"


def test_einrichten_verlangt_face_id_und_eigene_mail(fam, phone):
    options = fam.c.passkeys.registration_options(fam.person("Mama"))
    assert options["authenticatorSelection"]["userVerification"] == "required"
    assert options["authenticatorSelection"]["residentKey"] == "required"
    with pytest.raises(PermissionDeniedError):
        fam.c.passkeys.registration_options(fam.person("Oma"))         # ohne Mail kein Login


def test_unterschrift_nur_einmal_gueltig(fam, phone):
    set_up(fam, phone)
    answer = phone.get(fam.c.passkeys.login_options(None))
    fam.c.passkeys.login(answer)
    with pytest.raises(AuthenticationError):
        fam.c.passkeys.login(answer)                                   # Wiederholung abgelehnt


def test_fremde_seite_oder_falsche_person(fam, phone):
    set_up(fam, phone)
    phishing = SoftAuthenticator(origin="https://geschenke-login.example")
    phishing.keys = phone.keys
    with pytest.raises(AuthenticationError):
        fam.c.passkeys.login(phishing.get(fam.c.passkeys.login_options(None)))
    set_up(fam, other := SoftAuthenticator(), "Papa")
    papa_answer_for_mama = other.get(fam.c.passkeys.login_options("Mama") | {"allowCredentials": []})
    with pytest.raises(AuthenticationError):
        fam.c.passkeys.login(papa_answer_for_mama)                     # Anfrage galt Mama


def test_einrichten_mit_fremder_anfrage_scheitert(fam, phone):
    options = fam.c.passkeys.registration_options(fam.person("Mama"))
    with pytest.raises(AuthenticationError):
        fam.c.passkeys.register(fam.person("Papa"), phone.create(options), "iPhone")


def test_ohne_passkey_kein_face_id_schritt(fam):
    with pytest.raises(NotFoundError):
        fam.c.passkeys.login_options("Mama")


def test_gesperrter_login_und_loeschen(tmp_path, phone):
    fam = Family(tmp_path / "t.db", admin_email="papa@example.de")
    set_up(fam, phone, "Lena")
    fam.c.family.set_email("Lena", None)                                # Login gesperrt
    with pytest.raises(AuthenticationError):
        fam.c.passkeys.login(phone.get(fam.c.passkeys.login_options(None)))
    fam.c.removals.remove(fam.person("Papa"), "Lena")
    assert fam.db.scalar("SELECT COUNT(*) FROM passkeys") == 0


# --- Web ------------------------------------------------------------------------------------

@pytest.fixture
def web(tmp_path):
    fam = Family(tmp_path / "web.db", cookie_secure=False)
    return fam, TestClient(create_app(fam.c))


def test_web_ablauf(web, phone):
    fam, client = web
    assert client.post("/api/passkey/options", json={}).status_code == 401           # nur angemeldet
    client.cookies.set("geschenke_session", fam.c.sessions.start(fam.person("Lena")))
    options = client.post("/api/passkey/options", json={}).json()
    assert client.post("/api/passkey", json={"credential": phone.create(options), "device": "iPhone"}).json() == {"ok": True}
    client.cookies.clear()

    assert client.post("/api/login/start", json={"name": "lena"}).json() == {"step": "passkey", "name": "Lena"}
    assert not fam.mails.messages                                                     # keine Mail
    options = client.post("/api/login/passkey/options", json={"name": "Lena"}).json()
    assert client.post("/api/login/passkey", json={"credential": phone.get(options)}).json() == {"name": "Lena"}
    assert client.get("/api/me").json()["name"] == "Lena"

    r = client.post("/api/login/start", json={"name": "Lena", "code": True}).json()   # lieber Code per Mail
    assert r["step"] == "code" and len(fam.mails.messages) == 1
