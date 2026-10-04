"""Geheimtipps: Wünsche, die sich jemand für eine andere Person merkt – unsichtbar für diese Person."""
import json

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
