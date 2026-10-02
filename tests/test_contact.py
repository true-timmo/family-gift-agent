"""Nachricht an den Admin über den Chat."""
import asyncio

from app.domain.notifications import AdminMessage
from app.mail import Mailer
from tests.conftest import Family, RecordingTransport


def test_nachricht_an_admin(admin_fam):
    r = admin_fam.call("Papa", "admin_kontaktieren", nachricht="  Bitte lade Gisela ein: g@example.de ")
    assert r == {"gesendet_an": "Mama"}
    assert admin_fam.notifier.sent == [AdminMessage("Papa", "papa@example.de", "Bitte lade Gisela ein: g@example.de")]


def test_nachricht_grenzen(admin_fam, tmp_path):
    assert admin_fam.call("Mama", "admin_kontaktieren", nachricht="Hallo") == {"fehler": "Du bist selbst der Admin."}
    assert "fehler" in admin_fam.call("Papa", "admin_kontaktieren", nachricht="x" * 2001)
    admin_fam.call("Papa", "admin_kontaktieren", nachricht="Eins")
    assert "warten" in admin_fam.call("Papa", "admin_kontaktieren", nachricht="Zwei")["fehler"]   # Versandlimit
    ohne_admin = Family(tmp_path / "b.db")
    assert ohne_admin.call("Papa", "admin_kontaktieren", nachricht="Hallo") == {"fehler": "Es ist kein Admin eingerichtet."}


def test_mail_an_admin_mit_antwortadresse():
    transport = RecordingTransport()
    mailer = Mailer(transport, "absender@example.de", "https://geschenke.example.de", "admin@example.de")
    asyncio.run(mailer.send_notification(AdminMessage("Papa", "papa@example.de", "Bitte <b>Gisela</b> einladen")))
    msg = transport.messages[0]
    assert (msg["To"], msg["Reply-To"], msg["Subject"]) == ("admin@example.de", "papa@example.de", "Nachricht von Papa")
    assert "Bitte <b>Gisela</b> einladen" in transport.last_text()
    assert "&lt;b&gt;Gisela&lt;/b&gt;" in msg.get_body(("html",)).get_content()

    asyncio.run(mailer.send_notification(AdminMessage("Paul", None, "Hallo")))
    assert transport.messages[1]["Reply-To"] is None and "keine eigene E-Mail-Adresse" in transport.last_text()
