"""Gesprächslogik: schickt den Chat an OpenRouter, führt Tool-Aufrufe aus, streamt die Antwort."""
import json
import logging
from dataclasses import dataclass, field
from typing import AsyncIterator, Callable

from openai import AsyncOpenAI

from ..config import LlmSettings
from ..domain.models import Actor
from ..storage import ChatRepository
from .privacy import Pseudonymizer
from .prompts import SystemPrompt
from .tools import ToolRegistry

log = logging.getLogger("uvicorn.error")

Event = dict   # {"type": "text" | "tool" | "model" | "error" | "done", …} – so geht es per SSE an die Oberfläche


@dataclass
class _ToolCall:
    id: str = ""
    name: str = ""
    arguments: str = ""

    def as_request(self) -> dict:
        return {"id": self.id, "type": "function", "function": {"name": self.name, "arguments": self.arguments}}

    def result_message(self, result: dict, privacy: Pseudonymizer) -> dict:
        return {"role": "tool", "tool_call_id": self.id,
                "content": privacy.mask(json.dumps(result, ensure_ascii=False))}


@dataclass
class _Round:
    """Eine Antwort des Modells – Text und Tool-Aufrufe kommen stückweise im Stream."""
    content: str = ""
    model: str | None = None
    calls: dict[int, _ToolCall] = field(default_factory=dict)

    def absorb(self, chunk) -> str:
        """Übernimmt ein Stück aus dem Stream und gibt den neuen Text zurück."""
        self.model = chunk.model or self.model
        if not chunk.choices:
            return ""
        delta = chunk.choices[0].delta
        for tc in delta.tool_calls or []:
            call = self.calls.setdefault(tc.index, _ToolCall())
            call.id = tc.id or call.id
            if tc.function:
                call.name += tc.function.name or ""
                call.arguments += tc.function.arguments or ""
        self.content += delta.content or ""
        return delta.content or ""

    def assistant_message(self) -> dict:
        return {"role": "assistant", "content": self.content or None,
                "tool_calls": [call.as_request() for call in self.calls.values()]}


class ChatAgent:
    MAX_TOOL_ROUNDS = 6
    MAX_TOKENS = 2000

    def __init__(self, client: AsyncOpenAI, settings: LlmSettings, tools: ToolRegistry, history: ChatRepository,
                 system_prompt: SystemPrompt, privacy: Callable[[], Pseudonymizer]):
        self._client = client
        self._settings = settings
        self._tools = tools
        self._history = history
        self._system_prompt = system_prompt
        self._privacy = privacy      # je Nachricht neu – kennt alle aktuellen Familiennamen

    @staticmethod
    def client_for(settings: LlmSettings) -> AsyncOpenAI:
        return AsyncOpenAI(
            base_url=settings.base_url,
            api_key=settings.api_key or "fehlt",   # ohne Key startet die App trotzdem; der Chat meldet dann einen Fehler
            max_retries=3,                          # wiederholt u.a. bei 429 (überlastete Free-Modelle)
            timeout=90,
        )

    async def reply(self, actor: Actor, text: str) -> AsyncIterator[Event]:
        """Verarbeitet eine Nachricht und liefert Ereignisse: text / tool / model / error / done.

        Ans Modell geht alles pseudonymisiert (siehe privacy.py); Nutzer und Verlauf sehen Klartext.
        """
        privacy = self._privacy()
        system = f"{self._system_prompt.for_actor(actor)}\n\n{privacy.instructions}"
        messages = [{"role": "system", "content": privacy.mask(system)},
                    *({"role": m["role"], "content": privacy.mask(m["content"])} for m in self._history.recent(actor.id)),
                    {"role": "user", "content": privacy.mask(text)}]
        self._history.add(actor.id, "user", text)

        answer = ""
        for _ in range(self.MAX_TOOL_ROUNDS):
            round_, unmasker = _Round(), privacy.stream()
            try:
                async for delta in self._stream(messages, round_):
                    if shown := unmasker.feed(delta):
                        answer += shown
                        yield {"type": "text", "text": shown}
            except Exception as e:  # Netzwerk, Überlastung aller Modelle, ungültige Antwort …
                log.warning("Sprachmodell nicht erreichbar (%s): %s", type(e).__name__, str(e)[:300])
                yield {"type": "error", "text": f"Der Assistent ist gerade nicht erreichbar ({type(e).__name__}). "
                                                "Bitte gleich nochmal versuchen."}
                break
            if rest := unmasker.flush():
                answer += rest
                yield {"type": "text", "text": rest}
            if round_.model:
                yield {"type": "model", "model": round_.model}
            if not round_.calls:
                break

            messages.append(round_.assistant_message())
            for call in round_.calls.values():
                result = self._tools.execute(actor, call.name, privacy.unmask(call.arguments))
                yield {"type": "tool", "name": call.name}
                messages.append(call.result_message(result, privacy))
            if round_.content:
                answer += "\n\n"
                yield {"type": "text", "text": "\n\n"}

        if answer.strip():
            self._history.add(actor.id, "assistant", answer.strip())
        yield {"type": "done"}

    def _routing(self) -> dict:
        """OpenRouter-Optionen: nur Anbieter, die Anfragen weder speichern noch zum Training nutzen;
        bei Überlastung oder Wegfall eines Modells automatisch auf die Ausweichmodelle."""
        routing: dict = {"provider": {"data_collection": "deny"}}
        if self._settings.fallback_models:
            routing["models"] = [self._settings.model, *self._settings.fallback_models]
        return routing

    async def _stream(self, messages: list[dict], round_: _Round) -> AsyncIterator[str]:
        stream = await self._client.chat.completions.create(
            model=self._settings.model,
            messages=messages,
            tools=self._tools.schemas(),
            stream=True,
            max_tokens=self.MAX_TOKENS,
            extra_body=self._routing(),
        )
        async for chunk in stream:
            if delta := round_.absorb(chunk):
                yield delta
