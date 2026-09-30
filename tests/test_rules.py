"""Tests für die Geschenk-Regeln (ohne Sprachmodell).

Ausführen:
  docker run --rm -v /opt/agent:/src -w /src agent-agent \
    sh -c "pip install -q pytest && python -m pytest -q tests"
"""
import json
import threading

import pytest

from app import db, tools

IDS: dict[str, int] = {}   # Name -> Personen-ID der Test-Familie


@pytest.fixture
def conn(tmp_path):
    c = db.connect(str(tmp_path / "test.db"))
    IDS.clear()
    IDS.update({
        "Mama": db.add_person(c, "Mama", "mama@example.de"),
        "Papa": db.add_person(c, "Papa", "papa@example.de"),
        "Lena": db.add_person(c, "Lena", "lena@example.de"),
        "Oma":  db.add_person(c, "Oma"),                       # ohne Login
    })
    return c


def call(conn, who, tool, **args):
    return tools.execute(conn, IDS[who], tool, json.dumps(args))


def titles(result):
    return [w["titel"] for w in result["wuensche"]]


def test_wunsch_eintragen_und_anzeigen(conn):
    r = call(conn, "Papa", "wunsch_hinzufuegen", person="Papa", titel="Gusseisenpfanne",
             shop="Manufactum", link="https://example.com/pfanne", preis="69 €")
    assert r["fuer"] == "Papa"
    liste = call(conn, "Mama", "wuensche_anzeigen", person="papa")   # Groß/klein egal
    assert liste["wuensche"][0] == {"id": r["id"], "titel": "Gusseisenpfanne", "shop": "Manufactum",
                                    "link": "https://example.com/pfanne", "preis": "69 €", "status": "offen"}


def test_reserviertes_ist_fuer_andere_unsichtbar(conn):
    w = call(conn, "Papa", "wunsch_hinzufuegen", person="Papa", titel="Pfanne")["id"]
    call(conn, "Papa", "wunsch_hinzufuegen", person="Papa", titel="Buch")
    assert call(conn, "Mama", "reservieren", wunsch_id=w)["status"] == "von dir reserviert"

    # Mama sieht ihre Reservierung, Lena sieht die Pfanne gar nicht mehr
    assert call(conn, "Mama", "wuensche_anzeigen", person="Papa")["wuensche"][0]["status"] == "von dir reserviert"
    assert titles(call(conn, "Lena", "wuensche_anzeigen", person="Papa")) == ["Buch"]


def test_doppelte_reservierung_wird_verhindert(conn):
    w = call(conn, "Papa", "wunsch_hinzufuegen", person="Papa", titel="Pfanne")["id"]
    call(conn, "Mama", "reservieren", wunsch_id=w)
    r = call(conn, "Lena", "reservieren", wunsch_id=w)
    assert "fehler" in r and "jemand anderes" in r["fehler"]
    assert "Mama" not in json.dumps(r)                     # verrät nicht, WER es besorgt


def test_ueberraschungsschutz(conn):
    w = call(conn, "Papa", "wunsch_hinzufuegen", person="Papa", titel="Pfanne")["id"]
    call(conn, "Mama", "reservieren", wunsch_id=w)

    eigene = call(conn, "Papa", "wuensche_anzeigen", person="Papa")
    assert titles(eigene) == ["Pfanne"]
    assert "status" not in json.dumps(eigene) and "reserv" not in json.dumps(eigene)

    # Auch über Umwege nichts verraten: eigenen Wunsch reservieren liefert immer dieselbe Meldung
    r = call(conn, "Papa", "reservieren", wunsch_id=w)
    assert r == {"fehler": "Eigene Wünsche kann man nicht reservieren."}
    assert call(conn, "Papa", "meine_reservierungen") == {"reservierungen": []}


def test_reservierung_aufheben(conn):
    w = call(conn, "Papa", "wunsch_hinzufuegen", person="Papa", titel="Pfanne")["id"]
    call(conn, "Mama", "reservieren", wunsch_id=w)
    assert "fehler" in call(conn, "Lena", "reservierung_aufheben", wunsch_id=w)   # nur wer reserviert hat
    assert call(conn, "Mama", "reservierung_aufheben", wunsch_id=w)["status"] == "offen"
    assert titles(call(conn, "Lena", "wuensche_anzeigen", person="Papa")) == ["Pfanne"]


def test_wuensche_fuer_personen_ohne_login(conn):
    w = call(conn, "Mama", "wunsch_hinzufuegen", person="Oma", titel="Wolldecke")["id"]
    assert titles(call(conn, "Papa", "wuensche_anzeigen", person="Oma")) == ["Wolldecke"]
    call(conn, "Papa", "reservieren", wunsch_id=w)
    assert call(conn, "Papa", "meine_reservierungen")["reservierungen"][0]["fuer"] == "Oma"


def test_bearbeiten_und_entfernen_nur_berechtigt(conn):
    w = call(conn, "Papa", "wunsch_hinzufuegen", person="Papa", titel="Pfanne")["id"]
    assert "fehler" in call(conn, "Lena", "wunsch_bearbeiten", wunsch_id=w, titel="Topf")
    assert call(conn, "Papa", "wunsch_bearbeiten", wunsch_id=w, preis="59 €")["preis"] == "59 €"

    call(conn, "Mama", "reservieren", wunsch_id=w)
    assert "fehler" in call(conn, "Lena", "wunsch_entfernen", wunsch_id=w)
    assert call(conn, "Papa", "wunsch_entfernen", wunsch_id=w)["entfernt"]
    # Mama bekommt einen Hinweis, dass der reservierte Wunsch entfernt wurde
    assert "hinweis" in call(conn, "Mama", "meine_reservierungen")["reservierungen"][0]


def test_unbekannte_person_und_kaputte_argumente(conn):
    assert "Bekannt sind" in call(conn, "Mama", "wuensche_anzeigen", person="Onkel Bob")["fehler"]
    assert "fehler" in tools.execute(conn, IDS["Mama"], "reservieren", "kein json")
    assert "fehler" in tools.execute(conn, IDS["Mama"], "gibts_nicht", "{}")


def test_gleichzeitiges_reservieren(tmp_path):
    path = str(tmp_path / "race.db")
    c = db.connect(path)
    papa = db.add_person(c, "Papa")
    others = [db.add_person(c, f"P{i}") for i in range(8)]
    w = db.add_wish(c, papa, "Papa", "Pfanne")["id"]
    results = []

    def grab(pid):
        results.append(tools.execute(db.connect(path), pid, "reservieren", json.dumps({"wunsch_id": w})))

    threads = [threading.Thread(target=grab, args=(p,)) for p in others]
    [t.start() for t in threads]; [t.join() for t in threads]
    assert sum("fehler" not in r for r in results) == 1


def test_code_login_bekannte_person(conn):
    code = db.create_otp(conn, "Mama", "mama@example.de", register=False)
    assert len(code) == 6 and code.isdigit()
    with pytest.raises(db.WishError, match="Noch 4"):
        db.verify_otp(conn, "Mama", "000000" if code != "000000" else "111111")
    assert db.verify_otp(conn, "mama", code)["name"] == "Mama"          # Groß/klein egal
    with pytest.raises(db.WishError, match="abgelaufen"):                # Code nur einmal gültig
        db.verify_otp(conn, "Mama", code)


def test_code_nach_5_fehlversuchen_gesperrt(conn):
    code = db.create_otp(conn, "Papa", "papa@example.de", register=False)
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(5):
        with pytest.raises(db.WishError):
            db.verify_otp(conn, "Papa", wrong)
    with pytest.raises(db.WishError, match="abgelaufen"):
        db.verify_otp(conn, "Papa", code)                                # auch der richtige nicht mehr


def test_abgelaufener_code(conn):
    code = db.create_otp(conn, "Lena", "lena@example.de", register=False)
    conn.execute("UPDATE otp_codes SET expires_at = 0")
    with pytest.raises(db.WishError, match="abgelaufen"):
        db.verify_otp(conn, "Lena", code)


def test_versandlimit(conn):
    db.create_otp(conn, "Mama", "mama@example.de", register=False)
    with pytest.raises(db.WishError, match="warten"):
        db.create_otp(conn, "Mama", "mama@example.de", register=False)


def test_registrierung_legt_person_erst_nach_code_an(conn):
    code = db.create_otp(conn, "Tante Uschi", "uschi@example.de", register=True)
    assert db.get_person(conn, "Tante Uschi") is None                    # vor Bestätigung: noch nichts
    p = db.verify_otp(conn, "tante uschi", code)                         # klein getippt beim Code
    assert (p["name"], p["email"]) == ("Tante Uschi", "uschi@example.de")


def test_registrierung_uebernimmt_person_ohne_login(conn):
    call(conn, "Mama", "wunsch_hinzufuegen", person="Oma", titel="Wolldecke")
    code = db.create_otp(conn, "Oma", "oma@example.de", register=True)
    oma = db.verify_otp(conn, "Oma", code)
    assert oma["id"] == IDS["Oma"] and oma["email"] == "oma@example.de"
    assert titles(call(conn, "Mama", "wuensche_anzeigen", person="Oma")) == ["Wolldecke"]


def test_registrierung_kann_bestehenden_login_nicht_kapern(conn):
    code = db.create_otp(conn, "Oma", "fremder@example.de", register=True)
    db.set_email(conn, "Oma", "oma@example.de")                          # Oma war schneller
    with pytest.raises(db.WishError, match="jemand anderes"):
        db.verify_otp(conn, "Oma", code)
    assert db.get_person(conn, "Oma")["email"] == "oma@example.de"


def test_session(conn):
    token = db.create_session(conn, IDS["Mama"])
    assert db.session_person(conn, token)["name"] == "Mama"
    assert db.session_person(conn, "falsch") is None
    db.delete_session(conn, token)
    assert db.session_person(conn, token) is None


def test_entfernen_benachrichtigt_wer_reserviert_hat(conn):
    w = call(conn, "Papa", "wunsch_hinzufuegen", person="Papa", titel="Pfanne")["id"]
    call(conn, "Mama", "reservieren", wunsch_id=w)
    outbox = []
    result = tools.execute(conn, IDS["Papa"], "wunsch_entfernen", json.dumps({"wunsch_id": w}), outbox)
    assert outbox == [{"type": "wunsch_entfernt", "an": "mama@example.de", "empfaenger": "Mama",
                       "fuer": "Papa", "entfernt_von": "Papa", "titel": "Pfanne"}]
    assert "Mama" not in json.dumps(result)          # das Modell (und damit Papa) erfährt nicht, wer


def test_entfernen_ohne_reservierung_keine_mail(conn):
    w = call(conn, "Papa", "wunsch_hinzufuegen", person="Papa", titel="Buch")["id"]
    outbox = []
    tools.execute(conn, IDS["Papa"], "wunsch_entfernen", json.dumps({"wunsch_id": w}), outbox)
    assert outbox == []


def test_eigene_reservierung_selbst_entfernt_keine_mail(conn):
    w = call(conn, "Lena", "wunsch_hinzufuegen", person="Oma", titel="Wärmflasche")["id"]
    call(conn, "Lena", "reservieren", wunsch_id=w)
    outbox = []
    tools.execute(conn, IDS["Lena"], "wunsch_entfernen", json.dumps({"wunsch_id": w}), outbox)
    assert outbox == []


def test_benachrichtigungsmail(monkeypatch, capsys):
    import asyncio
    from app import mailer
    monkeypatch.setenv("MAIL_DEBUG", "1")
    asyncio.run(mailer.send_wish_removed({"an": "mama@example.de", "empfaenger": "Mama", "fuer": "Oma",
                                          "entfernt_von": "Lena", "titel": "Wärmflasche"}))
    out = capsys.readouterr().out
    assert "An mama@example.de" in out and "Lena hat „Wärmflasche“ von der Wunschliste für Oma genommen" in out


def test_personenliste_mit_registrierungsstatus(conn):
    r = call(conn, "Mama", "personen_auflisten")
    assert {"name": "Oma", "registriert": False} in r["personen"]
    assert {"name": "Mama", "registriert": True} in r["personen"]
    assert "@" not in json.dumps(r)                  # keine Mail-Adressen ans Modell
