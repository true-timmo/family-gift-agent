"""Verwandtschaft: eintragen, ableiten, „Mama“ auflösen."""
import sqlite3

import pytest

from app.agent import SystemPrompt
from app.domain.errors import ConflictError, DomainError, NotFoundError, PermissionDeniedError
from app.domain.kinship import Fact, FamilyTree, Gender, Kin, KinTerm, parse_term
from app.domain.models import Actor
from app.storage import Database
from tests.conftest import Family


@pytest.fixture
def sippe(tmp_path):
    # „Oma“ heißt wirklich so (z.B. ohne eigenen Login eingetragen) – ein Name hat Vorrang vor dem Wort
    return Family(tmp_path / "sippe.db", members=[(n, f"{n.lower()}@example.de") for n in
                                                  ("Timmo", "Katharina", "Ulrike", "Uli", "Gisela", "Lisa")]
                  + [("Oma", None)])


def say(f, who, person, term, of):
    return f.c.relations.add(f.actor(who), person, term, of)


def names(f, who):
    return {r.person.name: r.names for r in f.c.relations.relatives(f.person(who))}


def resolve(f, who, word):
    return f.c.relations.resolve(f.actor(who), word).name


def test_begriffe():
    assert parse_term("Mama") == KinTerm(Kin.PARENT, Gender.FEMALE)
    assert parse_term("meine  Schwester") == KinTerm(Kin.SIBLING, Gender.FEMALE)
    assert parse_term("Schwiegermutter") == KinTerm(Kin.PARENT_IN_LAW, Gender.FEMALE)
    assert parse_term("mein Opa") == KinTerm(Kin.GRANDPARENT, Gender.MALE)
    assert parse_term("Nachbarin") is None


def test_schwester_und_mutter(sippe):
    """Das Beispiel aus der Anfrage: Katharina ist meine Schwester, Ulrike meine Mutter."""
    say(sippe, "Timmo", "Katharina", "Schwester", "Timmo")
    change = say(sippe, "Timmo", "Ulrike", "meine Mutter", "Timmo")
    assert change.statement == "Ulrike ist Mutter von Timmo"
    assert "Ulrike ist Mutter von Katharina" in change.derived

    assert resolve(sippe, "Katharina", "Mama") == "Ulrike"
    assert resolve(sippe, "Timmo", "Mama") == "Ulrike"
    assert resolve(sippe, "Timmo", "meine Schwester") == "Katharina"
    assert names(sippe, "Ulrike") == {"Katharina": ["Tochter"], "Timmo": ["Kind"]}   # Timmos Geschlecht unbekannt


def test_cousine_spricht_ihre_mutter_an(sippe):
    """Meine Cousine sagt „Mama“ zu ihrer Mutter, die meine Tante ist."""
    say(sippe, "Timmo", "Ulrike", "Mutter", "Timmo")
    say(sippe, "Timmo", "Gisela", "Schwester", "Ulrike")
    say(sippe, "Timmo", "Lisa", "Tochter", "Gisela")

    assert names(sippe, "Timmo") == {"Ulrike": ["Mutter"], "Gisela": ["Tante"], "Lisa": ["Cousine"]}
    assert resolve(sippe, "Lisa", "Mama") == "Gisela"
    assert resolve(sippe, "Lisa", "Tante") == "Ulrike"
    assert resolve(sippe, "Lisa", "Cousin") == "Timmo"          # Geschlecht unbekannt → passt trotzdem


def test_partner_und_angeheiratete(sippe):
    say(sippe, "Timmo", "Ulrike", "Mutter", "Timmo")
    say(sippe, "Timmo", "Uli", "Mann", "Ulrike")
    say(sippe, "Timmo", "Lisa", "Frau", "Timmo")
    assert resolve(sippe, "Ulrike", "Mann") == "Uli"
    assert resolve(sippe, "Lisa", "Schwiegermutter") == "Ulrike"
    assert names(sippe, "Ulrike")["Lisa"] == ["Schwiegertochter"]
    assert "Uli" not in names(sippe, "Timmo")                 # Partner der Mutter ist nicht automatisch Vater


def test_genannte_tante_ohne_weg_wird_wörtlich_gespeichert(sippe):
    say(sippe, "Timmo", "Gisela", "meine Tante", "Timmo")
    assert resolve(sippe, "Timmo", "Tante") == "Gisela"
    assert names(sippe, "Gisela") == {"Timmo": ["Nichte/Neffe"]}


def test_widersprueche_werden_abgelehnt(sippe):
    say(sippe, "Timmo", "Ulrike", "Mutter", "Timmo")
    say(sippe, "Timmo", "Katharina", "Schwester", "Timmo")
    with pytest.raises(ConflictError, match="schon Kind von Ulrike"):
        say(sippe, "Timmo", "Timmo", "Vater", "Ulrike")
    with pytest.raises(ConflictError, match="schon Schwester"):
        say(sippe, "Timmo", "Katharina", "Mutter", "Timmo")
    with pytest.raises(ConflictError, match="schon Enkelkind"):  # Uli wäre Ulrikes Vater und Enkel zugleich
        say(sippe, "Timmo", "Timmo", "Vater", "Uli") and say(sippe, "Timmo", "Uli", "Vater", "Ulrike")
    with pytest.raises(ConflictError, match="weiblich"):
        say(sippe, "Timmo", "Katharina", "Bruder", "Lisa")
    with pytest.raises(DomainError, match="sich selbst"):
        say(sippe, "Timmo", "Timmo", "Bruder", "Timmo")
    with pytest.raises(DomainError, match="kenne ich nicht"):
        say(sippe, "Timmo", "Uli", "Nachbar", "Timmo")


def test_zirkel_ueber_mehrere_generationen(sippe):
    for parent, child in (("Lisa", "Gisela"), ("Gisela", "Uli"), ("Uli", "Katharina")):
        say(sippe, "Timmo", parent, "Elternteil", child)
    with pytest.raises(ConflictError, match="widerspricht"):   # Lisa wäre ihre eigene Ur-Urenkelin
        say(sippe, "Timmo", "Katharina", "Mutter", "Lisa")


def test_doppelte_angabe_ist_ok(sippe):
    say(sippe, "Timmo", "Katharina", "Schwester", "Timmo")
    say(sippe, "Timmo", "Ulrike", "Mutter", "Timmo")
    assert say(sippe, "Katharina", "Ulrike", "Mama", "Katharina").known_before


def test_mehrdeutig_oder_unbekannt(sippe):
    say(sippe, "Timmo", "Katharina", "Schwester", "Timmo")
    say(sippe, "Timmo", "Lisa", "Schwester", "Timmo")
    with pytest.raises(ConflictError, match="Katharina, Lisa"):
        resolve(sippe, "Timmo", "Schwester")
    with pytest.raises(NotFoundError, match="Ich weiß noch nicht, wer „Papa“"):
        resolve(sippe, "Timmo", "Papa")
    assert resolve(sippe, "Timmo", "Oma") == "Oma"              # gibt es als Namen → Name gewinnt


def test_wuensche_mit_verwandtschaftswort(sippe):
    say(sippe, "Timmo", "Katharina", "Schwester", "Timmo")
    say(sippe, "Timmo", "Ulrike", "Mutter", "Timmo")
    r = sippe.call("Katharina", "wunsch_hinzufuegen", person="Mama", titel="Gartenschere")
    assert r["fuer"] == "Ulrike"
    assert sippe.titles("Timmo", "Mama") == ["Gartenschere"]
    assert "fehler" in sippe.call("Timmo", "wuensche_anzeigen", person="Papa")


def test_tools(sippe):
    r = sippe.call("Timmo", "verwandtschaft_eintragen", person="Ulrike", beziehung="Mutter", von="Timmo")
    assert r == {"gespeichert": "Ulrike ist Mutter von Timmo", "war_schon_bekannt": False, "daraus_folgt": []}
    r = sippe.call("Timmo", "verwandtschaft_eintragen", person="Katharina", beziehung="Schwester", von="Timmo")
    assert r["daraus_folgt"] == ["Ulrike ist Mutter von Katharina"]
    assert sippe.call("Katharina", "verwandtschaft_anzeigen", person="Mama") == \
        {"person": "Ulrike", "verwandte": [{"name": "Katharina", "beziehung": "Tochter"},
                                           {"name": "Timmo", "beziehung": "Kind"}]}


def test_entfernen(sippe):
    say(sippe, "Timmo", "Katharina", "Schwester", "Timmo")
    say(sippe, "Timmo", "Ulrike", "Mutter", "Timmo")
    with pytest.raises(ConflictError, match="ergibt sich aus anderen Angaben"):
        sippe.c.relations.remove(sippe.actor("Katharina"), "Ulrike", "Mutter", "Katharina")
    with pytest.raises(PermissionDeniedError):
        sippe.c.relations.remove(sippe.actor("Lisa"), "Ulrike", "Mutter", "Timmo")
    assert sippe.c.relations.remove(sippe.actor("Timmo"), "Ulrike", "Mutter", "Timmo") == "Ulrike ist Mutter von Timmo"
    assert "Ulrike" not in names(sippe, "Katharina")
    with pytest.raises(NotFoundError):
        sippe.c.relations.remove(sippe.actor("Timmo"), "Ulrike", "Mutter", "Timmo")


def test_person_loeschen_entfernt_verwandtschaft(tmp_path):
    f = Family(tmp_path / "a.db", admin_email="mama@example.de")
    say(f, "Mama", "Lena", "Tochter", "Papa")
    f.c.removals.remove(f.person("Mama"), "Lena")
    assert f.db.scalar("SELECT COUNT(*) FROM relations") == 0


def test_prompt_nennt_verwandte(sippe):
    say(sippe, "Timmo", "Ulrike", "Mutter", "Timmo")
    prompt = SystemPrompt(sippe.c.family, sippe.c.relations, sippe.c.admins).for_actor(Actor(sippe.person("Timmo")))
    assert "Verwandte von Timmo: Ulrike = Mutter" in prompt


def test_alte_datenbank_bekommt_geschlecht(tmp_path):
    path = tmp_path / "alt.db"
    old = sqlite3.connect(path)
    old.execute("CREATE TABLE persons (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE COLLATE NOCASE, "
                "email TEXT, created_at INTEGER NOT NULL)")
    old.execute("INSERT INTO persons (name, created_at) VALUES ('Oma', 0)")
    old.commit()
    old.close()
    db = Database(str(path))
    assert db.one("SELECT name, gender FROM persons")["gender"] is None


def test_stammbaum_rein():
    # 1=Oma, 2=Mutter, 3=Tante, 4=ich, 5=Cousine
    tree = FamilyTree([Fact(1, 2, Kin.PARENT), Fact(3, 2, Kin.SIBLING), Fact(4, 2, Kin.CHILD),
                       Fact(5, 3, Kin.CHILD)])
    assert tree.kins(1, 4) == {Kin.GRANDPARENT}
    assert tree.kins(1, 3) == {Kin.PARENT}         # Geschwister teilen die Eltern
    assert tree.kins(3, 4) == {Kin.AUNT_UNCLE}
    assert tree.kins(5, 4) == {Kin.COUSIN}
    assert tree.kins(4, 1) == {Kin.GRANDCHILD}


# --- Kinder ohne Login ---------------------------------------------------------

def test_kind_ohne_login_anlegen_und_wuensche_eintragen(sippe):
    r = sippe.call("Timmo", "person_anlegen", name="  Paul ")
    assert r == {"angelegt": "Paul"}
    assert sippe.person("Paul").email is None and sippe.status_of("Paul") == "offen"
    assert sippe.call("Timmo", "person_anlegen", name="paul") == {"fehler": "Paul gibt es schon in der Familienliste."}
    assert "fehler" in sippe.call("Timmo", "person_anlegen", name="123")
    sippe.add_wish("Timmo", "Paul", "Feuerwehrauto")
    assert sippe.titles("Katharina", "Paul") == ["Feuerwehrauto"]


def test_eltern_verwalten_wuensche_ihrer_kinder(sippe):
    sippe.c.family.add_without_login("Paul")
    w = sippe.add_wish("Timmo", "Paul", "Feuerwehrauto")             # Onkel trägt ein
    assert "fehler" in sippe.call("Uli", "wunsch_bearbeiten", wunsch_id=w, preis="20 €")   # noch nicht Vater
    say(sippe, "Timmo", "Uli", "Vater", "Paul")
    assert sippe.call("Uli", "wunsch_bearbeiten", wunsch_id=w, preis="20 €")["preis"] == "20 €"
    assert "fehler" in sippe.call("Lisa", "wunsch_bearbeiten", wunsch_id=w, preis="1 €")   # andere weiterhin nicht
    assert sippe.call("Uli", "wunsch_entfernen", wunsch_id=w)["entfernt"]


def test_eltern_haben_keine_rechte_bei_registrierten_kindern(sippe):
    say(sippe, "Timmo", "Ulrike", "Mutter", "Timmo")
    w = sippe.add_wish("Timmo", "Timmo", "Buch")
    assert "fehler" in sippe.call("Ulrike", "wunsch_entfernen", wunsch_id=w)
