"""Wünsche und Reservierungen über die Tools des Sprachmodells."""
import json
import threading

from app.agent.presenter import shop_markdown
from app.config import Settings
from app.container import Container
from app.domain.models import Actor, WishDetails
from app.domain.notifications import WishRemoved


def test_wunsch_eintragen_und_anzeigen(fam):
    r = fam.call("Papa", "wunsch_hinzufuegen", person="Papa", titel="Gusseisenpfanne",
                 shop="Manufactum", link="https://example.com/pfanne", preis="69 €")
    assert r["fuer"] == "Papa"
    liste = fam.call("Mama", "wuensche_anzeigen", person="papa")   # Groß/klein egal
    assert liste["wuensche"][0] == {"id": r["id"], "titel": "Gusseisenpfanne", "shop": "Manufactum",
                                    "shop_anzeige": "[Manufactum](https://example.com/pfanne)",
                                    "preis": "69 €", "status": "offen"}


def test_reserviertes_sehen_andere_mit_namen(fam):
    w = fam.add_wish("Papa", "Papa", "Pfanne")
    fam.add_wish("Papa", "Papa", "Buch")
    assert fam.call("Mama", "reservieren", wunsch_id=w)["status"] == "von dir reserviert"

    # Mama sieht ihre Reservierung, Lena sieht die Pfanne als „besorgt Mama“ – am Ende der Liste
    assert fam.call("Mama", "wuensche_anzeigen", person="Papa")["wuensche"][0]["status"] == "von dir reserviert"
    lena = fam.call("Lena", "wuensche_anzeigen", person="Papa")["wuensche"]
    assert [(w["titel"], w["status"]) for w in lena] == [("Buch", "offen"), ("Pfanne", "besorgt Mama")]
    assert lena[1]["besorgt_von"] == "Mama"


def test_doppelte_reservierung_wird_verhindert(fam):
    w = fam.add_wish("Papa", "Papa", "Pfanne")
    fam.call("Mama", "reservieren", wunsch_id=w)
    assert fam.call("Lena", "reservieren", wunsch_id=w) == {"fehler": "Das besorgt schon Mama."}


def test_ueberraschungsschutz(fam):
    w = fam.add_wish("Papa", "Papa", "Pfanne")
    fam.call("Mama", "reservieren", wunsch_id=w)

    eigene = fam.call("Papa", "wuensche_anzeigen", person="Papa")
    assert [x["titel"] for x in eigene["wuensche"]] == ["Pfanne"]
    dump = json.dumps(eigene)
    assert "status" not in dump and "reserv" not in dump and "besorgt" not in dump and "Mama" not in dump

    # Auch über Umwege nichts verraten: eigenen Wunsch reservieren liefert immer dieselbe Meldung
    assert fam.call("Papa", "reservieren", wunsch_id=w) == {"fehler": "Eigene Wünsche kann man nicht reservieren."}
    assert fam.call("Papa", "meine_reservierungen") == {"reservierungen": []}


def test_reservierung_aufheben(fam):
    w = fam.add_wish("Papa", "Papa", "Pfanne")
    fam.call("Mama", "reservieren", wunsch_id=w)
    assert "fehler" in fam.call("Lena", "reservierung_aufheben", wunsch_id=w)   # nur wer reserviert hat
    assert fam.call("Mama", "reservierung_aufheben", wunsch_id=w)["status"] == "offen"
    assert fam.call("Lena", "wuensche_anzeigen", person="Papa")["wuensche"][0]["status"] == "offen"


def test_wuensche_fuer_personen_ohne_login(fam):
    w = fam.add_wish("Mama", "Oma", "Wolldecke")
    assert fam.titles("Papa", "Oma") == ["Wolldecke"]
    fam.call("Papa", "reservieren", wunsch_id=w)
    assert fam.call("Papa", "meine_reservierungen")["reservierungen"][0]["fuer"] == "Oma"


def test_bearbeiten_und_entfernen_nur_berechtigt(fam):
    w = fam.add_wish("Papa", "Papa", "Pfanne")
    assert "fehler" in fam.call("Lena", "wunsch_bearbeiten", wunsch_id=w, titel="Topf")
    assert fam.call("Papa", "wunsch_bearbeiten", wunsch_id=w, preis="59 €")["preis"] == "59 €"

    fam.call("Mama", "reservieren", wunsch_id=w)
    assert "fehler" in fam.call("Lena", "wunsch_entfernen", wunsch_id=w)
    assert fam.call("Papa", "wunsch_entfernen", wunsch_id=w)["entfernt"]
    # Mama bekommt einen Hinweis, dass der reservierte Wunsch entfernt wurde
    assert "hinweis" in fam.call("Mama", "meine_reservierungen")["reservierungen"][0]


def test_unbekannte_person_und_kaputte_argumente(fam):
    assert "Bekannt sind" in fam.call("Mama", "wuensche_anzeigen", person="Onkel Bob")["fehler"]
    mama = fam.actor("Mama")
    assert "fehler" in fam.c.tools.execute(mama, "reservieren", "kein json")
    assert "fehler" in fam.c.tools.execute(mama, "gibts_nicht", "{}")
    assert fam.call("Mama", "wunsch_hinzufuegen", person="Mama") == {"fehler": "Fehlende oder ungültige Angabe: 'titel'"}


def test_gleichzeitiges_reservieren(tmp_path):
    path = str(tmp_path / "race.db")
    c = Container(Settings(db_path=path))
    papa = c.family.add("Papa")
    others = [c.family.add(f"P{i}") for i in range(8)]
    w = c.wishes.add(Actor(papa), "Papa", WishDetails(title="Pfanne")).id
    results = []

    def grab(person):   # jeder Thread mit eigener Verbindung – wie getrennte Anfragen
        results.append(Container(Settings(db_path=path)).tools.execute(Actor(person), "reservieren",
                                                                        json.dumps({"wunsch_id": w})))

    threads = [threading.Thread(target=grab, args=(p,)) for p in others]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sum("fehler" not in r for r in results) == 1


def test_entfernen_benachrichtigt_wer_reserviert_hat(fam):
    w = fam.add_wish("Papa", "Papa", "Pfanne")
    fam.call("Mama", "reservieren", wunsch_id=w)
    result = fam.call("Papa", "wunsch_entfernen", wunsch_id=w)
    assert fam.notifier.sent == [WishRemoved(recipient_email="mama@example.de", recipient_name="Mama",
                                             wished_by="Papa", removed_by="Papa", title="Pfanne")]
    assert "Mama" not in json.dumps(result)          # das Modell (und damit Papa) erfährt nicht, wer


def test_entfernen_ohne_reservierung_keine_mail(fam):
    fam.call("Papa", "wunsch_entfernen", wunsch_id=fam.add_wish("Papa", "Papa", "Buch"))
    assert fam.notifier.sent == []


def test_eigene_reservierung_selbst_entfernt_keine_mail(fam):
    w = fam.add_wish("Lena", "Oma", "Wärmflasche")
    fam.call("Lena", "reservieren", wunsch_id=w)
    fam.call("Lena", "wunsch_entfernen", wunsch_id=w)
    assert fam.notifier.sent == []


def test_personenliste_mit_registrierungsstatus(fam):
    r = fam.call("Mama", "personen_auflisten")
    assert {"name": "Oma", "status": "offen"} in r["personen"]
    assert {"name": "Mama", "status": "registriert"} in r["personen"]
    assert "@" not in json.dumps(r)                  # keine Mail-Adressen ans Modell


def test_shop_als_link():
    assert shop_markdown("Manufactum", "https://example.com/p") == "[Manufactum](https://example.com/p)"
    assert shop_markdown(None, "https://example.com/p") == "[Zum Shop](https://example.com/p)"
    assert shop_markdown("Thalia", None) == "Thalia"
    assert shop_markdown(None, None) is None
    assert shop_markdown("Laden", "javascript:alert(1)") == "Laden"          # nur http(s)-Links
    assert shop_markdown("A [B]", "https://x.de/a b(c)") == "[A (B)](https://x.de/a%20b(c%29)"
