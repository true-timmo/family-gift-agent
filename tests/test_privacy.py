"""Datenschutz: Namen und E-Mail-Adressen gehen nie im Klartext an das Sprachmodell."""
import json

from app.agent.privacy import Pseudonymizer
from app.domain.models import Person
from tests.test_agent import FakeLlm, agent_for, chunk, run, tool_call

FAMILY = [Person(1, "Andrea", "andrea@example.de"), Person(2, "Oma Gisela"), Person(3, "Oma"), Person(4, "Uli")]


def test_namen_und_adressen_maskieren():
    p = Pseudonymizer(FAMILY)
    masked = p.mask("andrea und Oma Gisela, dann Oma und Ulis Rad. Mail: andrea@example.de, Ulrike bleibt.")
    assert masked == ("Person1 und Person2, dann Person3 und Person4s Rad. Mail: Mailadresse1, Ulrike bleibt.")
    assert p.unmask(masked) == "Andrea und Oma Gisela, dann Oma und Ulis Rad. Mail: andrea@example.de, Ulrike bleibt."


def test_links_bleiben_heil():
    p = Pseudonymizer(FAMILY)
    assert p.mask("Siehe https://shop.de/uli-rad und frag Uli") == "Siehe https://shop.de/uli-rad und frag Person4"


def test_gleiche_adresse_gleicher_platzhalter():
    p = Pseudonymizer(FAMILY)
    assert p.mask("a@b.de, A@B.de, c@d.de") == "Mailadresse1, Mailadresse1, Mailadresse2"


def test_stream_mit_geteilten_platzhaltern():
    p = Pseudonymizer(FAMILY)
    stream = p.stream()
    pieces = ["Hallo Pers", "on1! Dein", "e Liste und Person", "4s Rad. Die Personen", " sind P", "erson12."]
    shown = "".join(stream.feed(x) for x in pieces) + stream.flush()
    assert shown == "Hallo Andrea! Deine Liste und Ulis Rad. Die Personen sind Person12."


def test_modell_sieht_weder_namen_noch_adressen(fam):
    fam.add_wish("Papa", "Papa", "Pfanne")
    fam.c.chat_history.add(fam.ids["Lena"], "user", "Was wünscht sich Papa? Schreib an papa@example.de")
    papa = f"Person{fam.ids['Papa']}"
    llm = FakeLlm(
        [chunk(tool_calls=[tool_call("wuensche_anzeigen", {"person": papa})])],
        [chunk(f"{papa} wüns"), chunk(f"cht sich eine Pfanne. Frag {papa[:4]}"), chunk(f"{papa[4:]}!")],
    )
    events = run(agent_for(fam, llm), fam.actor("Lena"), "Und Mama? Ihre Adresse ist mama@example.de")

    sent = json.dumps([r["messages"] for r in llm.requests], ensure_ascii=False)
    for secret in ("Papa", "Mama", "Lena", "Oma", "@example.de"):
        assert secret not in sent, secret
    assert papa in sent and "Mailadresse1" in sent
    shown = "".join(e["text"] for e in events if e["type"] == "text")
    assert shown == "Papa wünscht sich eine Pfanne. Frag Papa!"                     # Nutzer sieht Klartext
    assert fam.c.chat_history.recent(fam.ids["Lena"])[-1]["content"] == shown      # Verlauf im Klartext
    tool_result = llm.requests[1]["messages"][-1]["content"]
    assert "Pfanne" in tool_result and "Papa" not in tool_result                   # Tool-Ergebnis maskiert
