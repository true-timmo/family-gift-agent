import asyncio

from app.domain.notifications import ComeBackReminder
from app.mail import Mailer
from app.storage.database import DAY, Database
from tests.conftest import RecordingTransport


def days_ago(fam, name, days, column="last_seen_at"):
    fam.db.execute(f"UPDATE persons SET {column} = strftime('%s','now') - ? WHERE name = ?", (int(days * DAY), name))


def away(fam, days, *names):
    for name in names or ("Mama", "Papa", "Lena"):
        days_ago(fam, name, days)


def reminded(fam):
    return sorted(n.recipient_name for n in fam.notifier.sent if isinstance(n, ComeBackReminder))


def test_erinnerung_nach_einem_monat_dann_monatlich(fam):
    fam.c.presence._hour = lambda: 10
    away(fam, 10)
    assert fam.c.presence.send_reminders() == 0
    away(fam, 31, "Papa")
    assert fam.c.presence.send_reminders() == 1 and reminded(fam) == ["Papa"]   # Oma hat keine Mail
    assert fam.c.presence.send_reminders() == 0                                 # nicht gleich nochmal
    days_ago(fam, "Papa", 29, "nudged_at")
    assert fam.c.presence.send_reminders() == 0
    days_ago(fam, "Papa", 31, "nudged_at")
    assert fam.c.presence.send_reminders() == 1                                 # ein Monat später wieder


def test_besuch_setzt_zurueck(fam):
    fam.c.presence._hour = lambda: 10
    away(fam, 40)
    token = fam.c.sessions.start(fam.person("Lena"))                            # Anmeldung zählt als Besuch
    away(fam, 40, "Mama")
    fam.c.sessions.person(token)                                                # Lena: schon gezählt
    assert fam.c.presence.send_reminders() == 2 and reminded(fam) == ["Mama", "Papa"]


def test_app_oeffnen_und_ki_zugang_zaehlen_als_besuch(fam):
    fam.c.presence._hour = lambda: 10
    token = fam.c.sessions.start(fam.person("Mama"))
    fam.c.api_keys.issue(fam.actor("Papa"))
    key = fam.notifier.sent[-1].key
    away(fam, 40)
    fam.c.sessions.person(token)
    fam.c.api_keys.person(key)
    assert reminded(fam) == [] and fam.c.presence.send_reminders() == 1 and reminded(fam) == ["Lena"]


def test_nachts_keine_mails(fam):
    away(fam, 40)
    fam.c.presence._hour = lambda: 3
    assert fam.c.presence.send_reminders() == 0
    fam.c.presence._hour = lambda: 9
    assert fam.c.presence.send_reminders() == 3


def test_neue_wuensche_der_anderen_ohne_eigene_und_geheimtipps(fam):
    fam.c.presence._hour = lambda: 10
    away(fam, 40, "Mama", "Papa", "Lena")
    fam.add_wish("Papa", "Papa", "Bohrmaschine")
    fam.add_wish("Papa", "Oma", "Schal")
    fam.add_wish("Papa", "Oma", "Tee")
    fam.add_wish("Lena", "Lena", "Buch")
    fam.call("Papa", "geheimtipp_eintragen", person="Lena", titel="Konzertkarten")   # Tipp über Lena
    old_id = fam.add_wish("Mama", "Papa", "Alter Wunsch")
    fam.db.execute("UPDATE wishes SET created_at = strftime('%s','now') - 50 * 86400 WHERE id = ?", (old_id,))
    away(fam, 40, "Mama")
    fam.c.presence.send_reminders()
    sent = {n.recipient_name: n.new_wishes for n in fam.notifier.sent if isinstance(n, ComeBackReminder)}
    assert sent["Lena"] == (("Oma", 2), ("Papa", 1))                            # Geheimtipp über Lena zählt nicht
    assert sent["Mama"] == (("Lena", 2), ("Oma", 2), ("Papa", 1))


def test_bestehende_datenbank_gilt_beim_update_als_gesehen(tmp_path):
    path = tmp_path / "alt.db"
    db = Database(str(path))
    db.execute("INSERT INTO persons (name, email, created_at) VALUES ('Mama', 'm@example.de', 1)")
    db.execute("ALTER TABLE persons DROP COLUMN nudged_at")
    db.execute("ALTER TABLE persons DROP COLUMN last_seen_at")
    db = Database(str(path))                                                    # Migration
    assert db.scalar("SELECT last_seen_at FROM persons") > 1


def test_erinnerungs_mail():
    transport = RecordingTransport()
    mailer = Mailer(transport, "absender@example.de", "https://geschenke.example.de")
    asyncio.run(mailer.send_notification(ComeBackReminder("p@example.de", "Papa", (("Oma", 2), ("Lena", 1)))))
    assert transport.messages[0]["Subject"] == "3 neue Wünsche auf der Geschenke-Liste"
    text = transport.last_text()
    assert "- Oma: 2 neue Wünsche" in text and "- Lena: 1 neuer Wunsch" in text and "https://geschenke.example.de" in text
    asyncio.run(mailer.send_notification(ComeBackReminder("p@example.de", "Papa", ())))
    assert transport.messages[1]["Subject"] == "Schau mal wieder auf die Geschenke-Liste"
    assert "dazugekommen" not in transport.last_text()
