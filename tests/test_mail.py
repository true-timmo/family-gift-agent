"""Mail-Vorlagen: Text- und HTML-Fassung, Escaping."""
import asyncio

from app.domain.models import IssuedInvite
from app.domain.notifications import NewRegistration, WishRemoved
from app.mail import Mailer
from tests.conftest import RecordingTransport


def mailer(admin_email=""):
    transport = RecordingTransport()
    return Mailer(transport, "absender@example.de", "https://geschenke.example.de", admin_email), transport


def html_of(message):
    return message.get_body(("html",)).get_content()


def test_benachrichtigungsmail():
    m, t = mailer()
    asyncio.run(m.send_notification(WishRemoved("mama@example.de", "Mama", wished_by="Oma", removed_by="Lena",
                                                title="Wärmflasche")))
    assert t.messages[0]["To"] == "mama@example.de"
    assert "Lena hat „Wärmflasche“ von der Wunschliste für Oma genommen" in t.last_text()
    assert t.last_text().endswith("https://geschenke.example.de\n")


def test_benachrichtigung_eigene_liste():
    m, t = mailer()
    asyncio.run(m.send_notification(WishRemoved("m@example.de", "Mama", "Lena", "Lena", "Rad")))
    assert "von der eigenen Wunschliste" in t.last_text()


def test_einladungsmail():
    m, t = mailer()
    asyncio.run(m.send_invite(IssuedInvite("abc", "Gisela", "g@example.de", "Timmo"), 7))
    msg = t.messages[0]
    assert msg["Subject"] == "Timmo lädt dich zur Geschenke-Liste ein"
    assert "Dein Name zum Anmelden: Gisela" in t.last_text()
    assert "https://geschenke.example.de/?einladung=abc" in html_of(msg)


def test_html_wird_escaped():
    m, t = mailer()
    asyncio.run(m.send_login_code("x@example.de", "<b>Eve</b>", "123456", 10))
    assert "&lt;b&gt;Eve&lt;/b&gt;" in html_of(t.messages[0])
    assert "Hallo <b>Eve</b>," in t.last_text()                 # Text-Fassung unverändert


def test_neuregistrierung_nur_mit_admin_adresse():
    m, t = mailer()
    asyncio.run(m.send_notification(NewRegistration("Gisela", invited_by="Timmo")))
    assert t.messages == []
    m, t = mailer(admin_email="admin@example.de")
    asyncio.run(m.send_notification(NewRegistration("Gisela", invited_by="Timmo")))
    assert t.messages[0]["Subject"] == "Neu dabei: Gisela" and "eingeladen von Timmo" in t.last_text()
