"""WhatsApp-Bot: Zuordnung per E-Mail-Code, Antworten des Assistenten, Webhook-Signatur."""
import asyncio
import hashlib
import hmac
import json
import re

import pytest
from fastapi.testclient import TestClient

from app.config import WhatsAppSettings
from app.web import create_app
from app.whatsapp.formatting import to_whatsapp
from tests.conftest import Family
from tests.test_agent import FakeLlm, chunk

CHAT = "4915112345678@c.us"


class FakeWaha:
    def __init__(self):
        self.sent, self.seen, self.typing_calls = [], [], []

    async def send_text(self, chat_id, text):
        self.sent.append((chat_id, text))

    async def mark_seen(self, chat_id):
        self.seen.append(chat_id)

    async def typing(self, chat_id, active):
        self.typing_calls.append(active)


@pytest.fixture
def wa(tmp_path):
    waha, llm = FakeWaha(), FakeLlm()
    f = Family(tmp_path / "wa.db", services={"whatsapp_client": waha, "llm_client": llm},
               whatsapp=WhatsAppSettings(api_key="k", hmac_key="geheim"))
    f.waha, f.llm = waha, llm
    return f


def message(text="", chat=CHAT, **extra):
    message.counter = getattr(message, "counter", 0) + 1
    return {"event": "message", "session": "default",
            "payload": {"id": f"msg-{message.counter}", "from": chat, "fromMe": False, "body": text, **extra}}


def say(f, text, **extra) -> str:
    asyncio.run(f.c.whatsapp.handle_event(message(text, **extra)))
    return f.waha.sent[-1][1]


def link(f, name="Papa"):
    say(f, "Hallo")
    say(f, name)
    code = re.search(r"lautet:\s+(\d{6})", f.mails.last_text()).group(1)
    return say(f, code)


def test_zuordnung_per_email_code(wa):
    assert "Wie heißt du?" in say(wa, "Hallo")
    assert "Code mit 6 Ziffern" in say(wa, "papa")
    assert wa.mails.messages[-1]["To"] == "papa@example.de"
    code = re.search(r"lautet:\s+(\d{6})", wa.mails.last_text()).group(1)
    assert "nicht geklappt" in say(wa, "000000" if code != "000000" else "111111")
    assert "Papa – wir sind verbunden" in say(wa, code[:3] + " " + code[3:])
    assert wa.c.whatsapp_chats.get(CHAT).person_id == wa.ids["Papa"]


def test_unbekannter_name_verraet_nichts(wa):
    say(wa, "Hallo")
    mails = len(wa.mails.messages)
    unbekannt = say(wa, "Onkel Bob")
    assert len(wa.mails.messages) == mails                          # keine Mail …
    assert unbekannt == say(wa, "Oma")                              # … und dieselbe Antwort wie für Oma (ohne Mail)
    assert "nicht geklappt" in say(wa, "123456")


def test_verbunden_antwortet_der_assistent(wa):
    link(wa)
    papa = f"Person{wa.ids['Papa']}"
    wa.llm.rounds.append([chunk(f"Hallo {papa}! Hier:\n\n| Wunsch | Details | Shop | Preis |\n|---|---|---|---|\n"
                                "| **Pfanne** | Gusseisen, 28 cm | [Manufactum](https://example.com/p) | – |")])
    answer = say(wa, "Was wünsche ich mir?")
    assert answer == "Hallo Papa! Hier:\n\n*Pfanne*\nGusseisen, 28 cm\nShop: Manufactum: https://example.com/p"
    assert wa.waha.typing_calls[-2:] == [True, False] and CHAT in wa.waha.seen
    system = wa.llm.requests[-1]["messages"][0]["content"]
    assert "per WhatsApp" in system and "Papa" not in system         # WhatsApp-Hinweis, Namen pseudonymisiert


def test_abmelden_und_entzogener_login(wa):
    link(wa)
    assert "nicht mehr" in say(wa, "Abmelden")
    assert wa.c.whatsapp_chats.get(CHAT) is None
    wa.reset_mail_limit()                                            # 1 Mail pro Minute
    assert "verbunden" in link(wa)
    wa.c.family.set_email("Papa", None)                             # Login gesperrt → Chat wird neu begrüßt
    assert "Wie heißt du?" in say(wa, "Hallo?")


def test_person_entfernen_trennt_whatsapp(tmp_path):
    f = Family(tmp_path / "a.db", admin_email="mama@example.de", services={"whatsapp_client": FakeWaha()},
               whatsapp=WhatsAppSettings(api_key="k", hmac_key="h"))
    f.c.whatsapp_chats.link(CHAT, f.ids["Papa"])
    f.c.removals.remove(f.person("Mama"), "Papa")
    assert f.c.whatsapp_chats.get(CHAT) is None


def test_ignoriert_gruppen_eigenes_und_doppeltes(wa):
    for event in (message("Hi", chat="123@g.us"), message("Hi", fromMe=True), {"event": "message.ack"}):
        asyncio.run(wa.c.whatsapp.handle_event(event))
    assert wa.waha.sent == []
    event = message("Hallo")
    asyncio.run(wa.c.whatsapp.handle_event(event))
    asyncio.run(wa.c.whatsapp.handle_event(event))                  # Wiederholung desselben Webhooks
    assert len(wa.waha.sent) == 1


def test_statusmeldungen_duerfen_scheitern(wa):
    async def broken(*_):
        raise ConnectionError
    wa.waha.mark_seen = wa.waha.typing = broken
    assert "Wie heißt du?" in say(wa, "Hallo")


def test_nur_text(wa):
    assert "nur Textnachrichten" in say(wa, "", hasMedia=True)


def test_formatierung():
    assert to_whatsapp("## Liste\n**fett** und [Shop](https://x.de/a)") == "*Liste*\n*fett* und Shop: https://x.de/a"
    table = "| Wunsch | Status |\n|---|---|\n| Buch | offen |\n| Rad | – |"
    assert to_whatsapp(table) == "*Buch*\nStatus: offen\n\n*Rad*"


def test_webhook_braucht_signatur(wa):
    body = json.dumps(message("Hallo")).encode()
    with TestClient(create_app(wa.c)) as client:
        assert client.post("/api/whatsapp/webhook", content=body).status_code == 401
        bad = {"X-Webhook-Hmac": "00", "Content-Type": "application/json"}
        assert client.post("/api/whatsapp/webhook", content=body, headers=bad).status_code == 401
        good = {"X-Webhook-Hmac": hmac.new(b"geheim", body, hashlib.sha512).hexdigest(),
                "Content-Type": "application/json"}
        assert client.post("/api/whatsapp/webhook", content=body, headers=good).status_code == 200
    assert "Wie heißt du?" in wa.waha.sent[-1][1]


def test_ohne_einrichtung_kein_webhook(fam):
    with TestClient(create_app(fam.c)) as client:
        assert client.post("/api/whatsapp/webhook", content=b"{}").status_code == 404
