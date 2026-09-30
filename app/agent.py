"""Gesprächslogik: schickt den Chat an OpenRouter, führt Tool-Aufrufe aus, streamt die Antwort."""
import asyncio
import json
import logging
import os
from datetime import date
from typing import AsyncIterator

from openai import AsyncOpenAI

from . import db, mailer
from .tools import TOOLS, execute

MODEL = os.environ.get("MODEL", "").strip()
FALLBACK_MODELS = [m.strip() for m in os.environ.get("FALLBACK_MODELS", "").split(",") if m.strip()]
MAX_TOOL_ROUNDS = 6
log = logging.getLogger("uvicorn.error")
_background: set[asyncio.Task] = set()   # hält laufende Mail-Tasks am Leben

client = AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.environ.get("OPENROUTER_API_KEY") or "fehlt",   # ohne Key startet die App trotzdem; der Chat meldet dann einen Fehler
    max_retries=3,          # wiederholt u.a. bei 429 (überlastete Free-Modelle)
    timeout=90,
)

SYSTEM_PROMPT = """Du bist der Geschenke-Assistent der Familie. Du hilfst dabei, Geschenkwünsche zu sammeln
und doppelte Geschenke zu vermeiden. Antworte kurz, freundlich und auf Deutsch.

Du sprichst gerade mit: {name}
Heute ist der {today}.
Bekannte Familienmitglieder: {persons}

So arbeitest du:
- Alle Wünsche und Reservierungen stehen in einer Datenbank. Nutze IMMER die Tools, um etwas nachzusehen
  oder zu speichern – verlasse dich nie auf dein Gedächtnis aus früheren Nachrichten.
- Sagt {name}, dass sie/er sich etwas wünscht, trage es mit dem eigenen Namen als Person ein.
  Frag nach, wo es das zu kaufen gibt, falls Shop oder Link fehlen – aber nur einmal, es ist optional.
- Sagt {name}, dass sie/er ein Geschenk besorgt, reserviere den passenden Wunsch. Ist unklar, welcher
  gemeint ist, zeig zuerst die Liste und frag nach.
- Die Tools setzen die Regeln durch (z.B. dass man eigene Wünsche nicht reservieren kann).
  Meldet ein Tool einen Fehler, erkläre ihn in einfachen Worten.
- Verrate niemals, ob jemand einen Wunsch von {name} bereits besorgt. Das würde die Überraschung verderben.
- Nenne die internen Wunsch-Nummern (id) nicht, außer es hilft bei einer Rückfrage.
- Gib Links vollständig aus, damit man sie anklicken kann.
- Möchte jemand eine Tabelle oder Übersicht, antworte mit einer Markdown-Tabelle
  (Spalten z.B. Wunsch | Shop | Preis | Link; leere Felder mit „–“). Sonst sind kurze Listen besser.
- „Registriert“ heißt: Die Person kann sich selbst anmelden. Personen ohne Registrierung können
  trotzdem Wünsche haben – andere tragen sie für sie ein."""


def _system_prompt(conn, person) -> str:
    persons = ", ".join(p["name"] for p in db.list_persons(conn))
    return SYSTEM_PROMPT.format(name=person["name"], today=date.today().strftime("%d.%m.%Y"), persons=persons)


async def chat(conn, person, user_text: str) -> AsyncIterator[dict]:
    """Verarbeitet eine Nachricht. Liefert Ereignisse: text / tool / model / error / done."""
    messages = [{"role": "system", "content": _system_prompt(conn, person)}]
    messages += db.recent_messages(conn, person["id"])
    messages.append({"role": "user", "content": user_text})
    db.add_message(conn, person["id"], "user", user_text)

    answer = ""
    for _ in range(MAX_TOOL_ROUNDS):
        try:
            stream = await client.chat.completions.create(
                model=MODEL,
                messages=messages,
                tools=TOOLS,
                stream=True,
                max_tokens=2000,
                # OpenRouter weicht bei Überlastung automatisch auf die nächsten Modelle aus
                extra_body={"models": [MODEL, *FALLBACK_MODELS]} if FALLBACK_MODELS else None,
            )
            content, calls, used_model = "", {}, None
            async for chunk in stream:
                used_model = chunk.model or used_model
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if delta.content:
                    content += delta.content
                    yield {"type": "text", "text": delta.content}
                for tc in delta.tool_calls or []:
                    c = calls.setdefault(tc.index, {"id": "", "name": "", "arguments": ""})
                    c["id"] = tc.id or c["id"]
                    if tc.function:
                        c["name"] += tc.function.name or ""
                        c["arguments"] += tc.function.arguments or ""
        except Exception as e:  # Netzwerk, Überlastung aller Modelle, ungültige Antwort …
            yield {"type": "error", "text": f"Der Assistent ist gerade nicht erreichbar ({type(e).__name__}). Bitte gleich nochmal versuchen."}
            break

        if used_model:
            yield {"type": "model", "model": used_model}
        answer += content

        if not calls:
            break

        messages.append({
            "role": "assistant",
            "content": content or None,
            "tool_calls": [
                {"id": c["id"], "type": "function", "function": {"name": c["name"], "arguments": c["arguments"]}}
                for c in calls.values()
            ],
        })
        for c in calls.values():
            outbox: list[dict] = []
            result = execute(conn, person["id"], c["name"], c["arguments"], outbox)
            if outbox:   # Mails im Hintergrund – die Antwort im Chat wartet nicht darauf
                task = asyncio.create_task(mailer.send_notifications(outbox, log))
                _background.add(task)
                task.add_done_callback(_background.discard)
            yield {"type": "tool", "name": c["name"]}
            messages.append({"role": "tool", "tool_call_id": c["id"],
                             "content": json.dumps(result, ensure_ascii=False)})
        if content:
            answer += "\n\n"
            yield {"type": "text", "text": "\n\n"}

    if answer.strip():
        db.add_message(conn, person["id"], "assistant", answer.strip())
    yield {"type": "done"}
