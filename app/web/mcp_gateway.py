"""MCP-Server: die Wunschliste als Werkzeugkasten für eigene KI-Assistenten (Claude, ChatGPT, Cursor …).

Es sind dieselben Tools wie im Chat – mit denselben Regeln, denn die stehen in den Services.
Wer gerade handelt, ergibt sich allein aus dem API-Schlüssel:

  POST /mcp            Header „Authorization: Bearer <Schlüssel>“ (empfohlen)
                       oder „x-access-token: <Schlüssel>“ / „x-api-key: <Schlüssel>“ (z.B. Claude-Connectoren)
  POST /mcp/<Schlüssel>  für Programme, die nur eine Adresse kennen; Schlüssel wird in Logs geschwärzt
"""
import json
import logging
import re
from contextlib import AbstractAsyncContextManager

import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import Receive, Scope, Send

from ..agent import ToolRegistry
from ..domain.models import Actor
from ..services import AdminPolicy, ApiKeyService

INSTRUCTIONS = """Geschenke-Liste einer Familie: Wünsche sammeln, Geschenke reservieren, doppelte Geschenke vermeiden.
Du handelst im Namen der Person, der der API-Schlüssel gehört – ueber_mich zeigt, wer das ist, und ihre Verwandten.
Die Regeln (z.B. dass man eigene Wünsche nicht reservieren kann) setzt der Server durch; meldet ein Tool „fehler“,
erkläre ihn. Verrate nie, ob jemand einen Wunsch dieser Person bereits besorgt – das würde die Überraschung verderben.
Personen lassen sich per Name oder Verwandtschaftswort aus Sicht der Person angeben („Mama“, „meine Schwester“).
Das Feld „shop_anzeige“ ist ein fertiger Markdown-Link auf den Shop."""

# Nur im Familien-Chat: neue Schlüssel gehen dort per Mail an die Person
_CHAT_ONLY = ("ki_zugang_anfordern",)


class McpGateway:
    """ASGI-Endpunkt: prüft den Schlüssel und reicht die Anfrage an den MCP-Server weiter."""

    def __init__(self, tools: ToolRegistry, keys: ApiKeyService, admins: AdminPolicy):
        self._tools = tools.without(*_CHAT_ONLY)
        self._keys = keys
        self._admins = admins
        self._server = self._build_server()
        self._sessions = StreamableHTTPSessionManager(
            app=self._server, stateless=True, json_response=True,
            # Schutz vor DNS-Rebinding braucht es nur für Server auf localhost – hier schützt der Schlüssel
            security_settings=TransportSecuritySettings(enable_dns_rebinding_protection=False))

    def lifespan(self) -> AbstractAsyncContextManager:
        return self._sessions.run()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        request = Request(scope)
        person = self._keys.person(_key_of(request))
        if not person:
            await JSONResponse({"error": "invalid_token", "error_description": "API-Schlüssel fehlt, ist abgelaufen "
                                "oder gesperrt."}, status_code=401,
                               headers={"WWW-Authenticate": 'Bearer realm="geschenke"'})(scope, receive, send)
            return
        scope.setdefault("state", {})["actor"] = self._admins.actor(person)
        # Kopie für den Transport (kennt nur einen Pfad) – das Zugriffslog zeigt weiter /mcp bzw. /mcp/***
        await self._sessions.handle_request(dict(scope, path="/"), receive, send)

    def _build_server(self) -> Server:
        server = Server("geschenke", instructions=INSTRUCTIONS)

        @server.list_tools()
        async def list_tools() -> list[types.Tool]:
            return [types.Tool(name=t.name, description=t.description,
                               inputSchema=t.schema()["function"]["parameters"]) for t in self._tools]

        @server.call_tool(validate_input=False)   # prüft die Registry – mit verständlichen Fehlermeldungen
        async def call_tool(name: str, arguments: dict) -> types.CallToolResult:
            actor: Actor = server.request_context.request.state.actor
            result = self._tools.execute(actor, name, json.dumps(arguments or {}))
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=json.dumps(result, ensure_ascii=False))],
                structuredContent=result, isError="fehler" in result)

        return server


_KEY_HEADERS = ("x-access-token", "x-api-key")   # für Programme, die nur bestimmte Header-Namen anbieten


def _key_of(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    for name in _KEY_HEADERS:
        if value := request.headers.get(name, "").strip():
            return value.removeprefix("Bearer ").strip()
    return request.path_params.get("key")


class RedactKeysFilter(logging.Filter):
    """Schwärzt Schlüssel in der Adresse (/mcp/<Schlüssel>) im Zugriffslog von uvicorn."""
    _KEY_IN_PATH = re.compile(r"(/mcp/)[^\s/?\"]+")

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            record.args = tuple(self._KEY_IN_PATH.sub(r"\1***", a) if isinstance(a, str) else a for a in record.args)
        return True
