"""Gesprächsschleife mit einem simulierten Sprachmodell (ohne Netzwerk)."""
import asyncio
import json
from types import SimpleNamespace as NS

from app.agent import ChatAgent, SystemPrompt
from app.config import LlmSettings


def chunk(content=None, tool_calls=None, model="test/model"):
    return NS(model=model, choices=[NS(delta=NS(content=content, tool_calls=tool_calls))])


def tool_call(name, args, index=0, id="call-1"):
    return NS(index=index, id=id, function=NS(name=name, arguments=json.dumps(args)))


class FakeLlm:
    """Liefert je Aufruf die nächste vorbereitete Antwort und merkt sich die gesendeten Nachrichten."""

    def __init__(self, *rounds):
        self.rounds = list(rounds)
        self.requests = []
        self.chat = NS(completions=NS(create=self.create))

    async def create(self, **kwargs):
        self.requests.append(kwargs)
        chunks = self.rounds.pop(0)

        async def stream():
            for c in chunks:
                yield c
        return stream()


def run(agent, actor, text):
    async def collect():
        return [e async for e in agent.reply(actor, text)]
    return asyncio.run(collect())


def agent_for(fam, llm, fallback=()):
    settings = LlmSettings(model="test/model", fallback_models=fallback)
    return ChatAgent(llm, settings, fam.c.tools, fam.c.chat_history, SystemPrompt(fam.c.family, fam.c.relations, fam.c.admins))


def test_tool_aufruf_und_antwort(fam):
    llm = FakeLlm(
        [chunk(tool_calls=[tool_call("wunsch_hinzufuegen", {"person": "Papa", "titel": "Pfanne"})])],
        [chunk("Ist "), chunk("notiert!")],
    )
    events = run(agent_for(fam, llm), fam.actor("Papa"), "Ich wünsche mir eine Pfanne")

    assert {"type": "tool", "name": "wunsch_hinzufuegen"} in events
    assert "".join(e["text"] for e in events if e["type"] == "text") == "Ist notiert!"
    assert events[-1] == {"type": "done"}
    assert fam.titles("Mama", "Papa") == ["Pfanne"]
    # Das Tool-Ergebnis geht in der zweiten Runde ans Modell zurück
    assert llm.requests[1]["messages"][-1]["role"] == "tool"
    assert fam.c.chat_history.recent(fam.ids["Papa"]) == [
        {"role": "user", "content": "Ich wünsche mir eine Pfanne"},
        {"role": "assistant", "content": "Ist notiert!"}]


def test_system_prompt_und_ausweichmodelle(fam):
    llm = FakeLlm([chunk("Hallo")])
    run(agent_for(fam, llm, fallback=("b/model",)), fam.actor("Mama", admin=True), "Hi")
    request = llm.requests[0]
    assert request["extra_body"] == {"models": ["test/model", "b/model"]}
    system = request["messages"][0]["content"]
    assert "Du sprichst gerade mit: Mama" in system and "ist Admin" in system
    assert "Wunsch | Details | Shop | Preis" in system and "Größe, Farbe" in system


def test_fehler_des_modells(fam):
    class Broken(FakeLlm):
        async def create(self, **kwargs):
            raise ConnectionError
    events = run(agent_for(fam, Broken()), fam.actor("Lena"), "Hallo?")
    assert events[0]["type"] == "error" and "ConnectionError" in events[0]["text"]
    assert events[-1] == {"type": "done"}
