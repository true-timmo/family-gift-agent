"""Geheimtipps: Wünsche, die sich jemand für eine andere Person merkt – unsichtbar für diese Person."""
import asyncio
import json

from app.domain.matching import matches
from app.domain.notifications import WishRemoved
from app.storage import Database


def tip(fam, who, person, title, **args):
    return fam.call(who, "geheimtipp_eintragen", person=person, titel=title, **args)


def test_geheimtipp_eintragen_und_fuer_andere_sichtbar(fam):
    r = tip(fam, "Papa", "Mama", "Konzertkarten Backstreet Boys",
            beschreibung="Düsseldorf, Mai 2027")
    assert r["fuer"] == "Mama" and r["geheimtipp"] is True
    lena = fam.call("Lena", "wuensche_anzeigen", person="Mama")["wuensche"]
    assert lena == [{"id": r["id"], "titel": "Konzertkarten Backstreet Boys", "beschreibung": "Düsseldorf, Mai 2027",
                     "geheimtipp_von": "Papa", "status": "offen"}]


def test_person_selbst_erfaehrt_nie_davon(fam):
    w = tip(fam, "Papa", "Mama", "Schal")["id"]
    fam.add_wish("Mama", "Mama", "Buch")
    own = fam.call("Mama", "wuensche_anzeigen", person="Mama")
    assert [x["titel"] for x in own["wuensche"]] == ["Buch"]
    assert "Schal" not in json.dumps(own) and "geheim" not in json.dumps(own)
    unbekannt = fam.call("Mama", "reservieren", wunsch_id=999)["fehler"]
    # Jeder Zugriff per Nummer klingt wie bei einem Wunsch, den es nicht gibt – auch für Admins
    for tool, args in (("reservieren", {}), ("reservierung_aufheben", {}), ("wunsch_entfernen", {}),
                       ("wunsch_bearbeiten", {"preis": "1 €"})):
        r = fam.call("Mama", tool, admin=True, wunsch_id=w, **args)
        assert r == {"fehler": unbekannt.replace("999", str(w))}
    assert fam.call("Mama", "meine_reservierungen") == {"reservierungen": []}


def test_reservieren_und_verwalten(fam):
    w = tip(fam, "Papa", "Mama", "Schal")["id"]
    assert fam.call("Lena", "reservieren", wunsch_id=w)["status"] == "von dir reserviert"
    assert "fehler" in fam.call("Lena", "wunsch_bearbeiten", wunsch_id=w, preis="30 €")     # nicht eingetragen
    assert fam.call("Papa", "wunsch_bearbeiten", wunsch_id=w, preis="30 €")["preis"] == "30 €"
    assert fam.call("Papa", "wunsch_entfernen", wunsch_id=w)["entfernt"]
    assert fam.notifier.sent[-1].recipient_name == "Lena"               # Lena hatte reserviert


def test_kein_geheimtipp_fuer_sich_selbst(fam):
    assert "ganz normal" in tip(fam, "Papa", "Papa", "Uhr")["fehler"]


def test_alte_datenbank_bekommt_spalte(tmp_path):
    path = tmp_path / "alt.db"
    db = Database(str(path))
    db.execute("ALTER TABLE wishes DROP COLUMN secret")                  # Stand vor diesem Feature
    assert Database(str(path)).one("SELECT COUNT(*) AS n FROM pragma_table_info('wishes') WHERE name = 'secret'")["n"] == 1


# --- Selbst besorgt -------------------------------------------------------------

def test_textvergleich():
    assert matches("Konzertkarten Backstreet Boys", "Karten für das Backstreet Boys Konzert", "Düsseldorf, Mai 2027")
    assert matches("die Sony Kopfhörer", "Kopfhörer WH-1000XM5", "Sony, schwarz")
    assert not matches("Buch", "Kochbuch Simplissime")             # zu wenig Gemeinsames
    assert not matches("Schal", "Mütze", "rot")
    assert not matches("gekauft", "Schal")                          # nur Füllwörter


def test_selbst_besorgt_entfernt_passenden_geheimtipp_und_benachrichtigt(fam):
    konzert = tip(fam, "Papa", "Mama", "Karten Backstreet Boys Konzert", beschreibung="Düsseldorf, Mai 2027")["id"]
    tip(fam, "Lena", "Mama", "Schal")
    fam.call("Lena", "reservieren", wunsch_id=konzert)
    r = fam.call("Mama", "selbst_besorgt", was="Konzertkarten für die Backstreet Boys")
    assert r["von_deiner_liste_entfernt"] == []
    titles = [w["titel"] for w in fam.call("Papa", "wuensche_anzeigen", person="Mama")["wuensche"]]
    assert titles == ["Schal"]                                          # nur der passende Tipp ist weg
    assert fam.notifier.sent == [WishRemoved("lena@example.de", "Lena", wished_by="Mama", removed_by="Mama",
                                             title="Karten Backstreet Boys Konzert", bought_by_wisher=True)]


def test_antwort_verraet_keine_geheimtipps(fam):
    ohne = fam.call("Mama", "selbst_besorgt", was="Schal")
    tip(fam, "Papa", "Mama", "Schal")
    mit = fam.call("Mama", "selbst_besorgt", was="Schal")
    assert ohne == mit


def test_selbst_besorgt_eigener_wunsch(fam):
    w = fam.add_wish("Mama", "Mama", "Gartenschere")
    fam.call("Papa", "reservieren", wunsch_id=w)
    r = fam.call("Mama", "selbst_besorgt", was="Gartenschere", wunsch_id=w)
    assert r["von_deiner_liste_entfernt"] == ["Gartenschere"]
    assert fam.call("Mama", "wuensche_anzeigen", person="Mama")["wuensche"] == []
    assert fam.notifier.sent[-1].bought_by_wisher and fam.notifier.sent[-1].recipient_name == "Papa"
    fremd = fam.add_wish("Papa", "Papa", "Pfanne")
    assert "nicht dein Wunsch" in fam.call("Mama", "selbst_besorgt", was="Pfanne", wunsch_id=fremd)["fehler"]


def test_mail_selbst_besorgt(fam):
    asyncio.run(fam.c.mailer.send_notification(WishRemoved("l@example.de", "Lena", "Andrea", "Andrea",
                                                           "Konzertkarten", bought_by_wisher=True)))
    msg = fam.mails.messages[-1]
    assert msg["Subject"] == "„Konzertkarten“ hat sich erledigt"
    assert "Andrea hat sich „Konzertkarten“ inzwischen selbst besorgt." in fam.mails.last_text()
