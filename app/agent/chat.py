"""Gesprächslogik: schickt den Chat an OpenRouter, führt Tool-Aufrufe aus, streamt die Antwort."""
import json
from dataclasses import dataclass, field
from typing import AsyncIterator

from openai import AsyncOpenAI

from ..config import LlmSettings
from ..domain.models import Actor
from ..storage import ChatRepository
from .prompts import SystemPrompt
from .tools import ToolRegistry

Event = dict   # {"type": "text" | "tool" | "model" | "error" | "done", …} – so geht es per SSE an die Oberfläche


@dataclass
class _ToolCall:
    id: str = ""
    name: str = ""
    arguments: str = ""

    def as_request(self) -> dict:
        return {"id": self.id, "type": "function", "function": {"name": self.name, "arguments": self.arguments}}

    def result_message(self, result: dict) -> dict:
        return {"role": "tool", "tool_call_id": self.id, "content": json.dumps(result, ensure_ascii=False)}


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
                 system_prompt: SystemPrompt):
        self._client = client
        self._settings = settings
        self._tools = tools
        self._history = history
        self._system_prompt = system_prompt

    @staticmethod
    def client_for(settings: LlmSettings) -> AsyncOpenAI:
        return AsyncOpenAI(
            base_url=settings.base_url,
            api_key=settings.api_key or "fehlt",   # ohne Key startet die App trotzdem; der Chat meldet dann einen Fehler
            max_retries=3,                          # wiederholt u.a. bei 429 (überlastete Free-Modelle)
            timeout=90,
        )

    async def reply(self, actor: Actor, text: str) -> AsyncIterator[Event]:
        """Verarbeitet eine Nachricht und liefert Ereignisse: text / tool / model / error / done."""
        messages = [{"role": "system", "content": self._system_prompt.for_actor(actor)},
                    *self._history.recent(actor.id),
                    {"role": "user", "content": text}]
        self._history.add(actor.id, "user", text)

        answer = ""
        for _ in range(self.MAX_TOOL_ROUNDS):
            round_ = _Round()
            try:
                async for delta in self._stream(messages, round_):
                    yield {"type": "text", "text": delta}
            except Exception as e:  # Netzwerk, Überlastung aller Modelle, ungültige Antwort …
                yield {"type": "error", "text": f"Der Assistent ist gerade nicht erreichbar ({type(e).__name__}). "
                                                "Bitte gleich nochmal versuchen."}
                break
            if round_.model:
                yield {"type": "model", "model": round_.model}
            answer += round_.content
            if not round_.calls:
                break

            messages.append(round_.assistant_message())
            for call in round_.calls.values():
                result = self._tools.execute(actor, call.name, call.arguments)
                yield {"type": "tool", "name": call.name}
                messages.append(call.result_message(result))
            if round_.content:
                answer += "\n\n"
                yield {"type": "text", "text": "\n\n"}

        if answer.strip():
            self._history.add(actor.id, "assistant", answer.strip())
        yield {"type": "done"}

    async def _stream(self, messages: list[dict], round_: _Round) -> AsyncIterator[str]:
        models = self._settings.fallback_models
        stream = await self._client.chat.completions.create(
            model=self._settings.model,
            messages=messages,
            tools=self._tools.schemas(),
            stream=True,
            max_tokens=self.MAX_TOKENS,
            # OpenRouter weicht bei Überlastung automatisch auf die nächsten Modelle aus
            extra_body={"models": [self._settings.model, *models]} if models else None,
        )
        async for chunk in stream:
            if delta := round_.absorb(chunk):
                yield delta
