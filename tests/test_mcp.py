"""KI-Zugänge (API-Schlüssel) und MCP-Server."""
import asyncio
import json
import logging

import mcp.types as types
import pytest
from fastapi.testclient import TestClient

from app.domain.errors import PermissionDeniedError, RateLimitError
from app.domain.notifications import ApiKeyIssued
from app.mail import Mailer
from app.web import create_app
from app.web.mcp_gateway import RedactKeysFilter
from tests.conftest import Family, RecordingTransport


@pytest.fixture
def fam(tmp_path):
    return Family(tmp_path / "mcp.db", admin_email="mama@example.de", cookie_secure=False)


def issue_key(fam, who) -> str:
    fam.c.api_keys.issue(fam.actor(who))
    return fam.notifier.sent[-1].key


# --- Schlüssel ---------------------------------------------------------------

def test_schluessel_nur_per_mail(fam):
    r = fam.call("Papa", "ki_zugang_anfordern")
    assert r["verschickt_an"] == "p***@example.de" and r["gueltig_bis"]
    sent = fam.notifier.sent[-1]
    assert isinstance(sent, ApiKeyIssued) and sent.recipient_email == "papa@example.de"
    assert sent.key.startswith("gsk_") and sent.key not in json.dumps(r)    # nie im Chat
    assert sent.key not in repr(sent)                                        # nie im Log
    assert fam.c.api_keys.person(sent.key).name == "Papa"
    assert fam.c.api_keys.person("gsk_falsch") is None and fam.c.api_keys.person(None) is None


def test_schluessel_gilt_einen_monat(fam):
    key = issue_key(fam, "Papa")
    days = (fam.notifier.sent[-1].expires_at - fam.db.scalar("SELECT created_at FROM api_keys")) / 86400
    assert days == 30
    fam.db.execute("UPDATE api_keys SET expires_at = 0")
    assert fam.c.api_keys.person(key) is None


def test_sperren(fam):
    key = issue_key(fam, "Papa")
    assert fam.call("Papa", "ki_zugang_sperren") == {"gesperrt": 1}
    assert fam.c.api_keys.person(key) is None


def test_nur_registrierte_und_mit_grenzen(fam):
    with pytest.raises(PermissionDeniedError):
        fam.c.api_keys.issue(fam.actor("Oma"))                   # ohne E-Mail-Adresse
    issue_key(fam, "Papa")
    with pytest.raises(RateLimitError, match="warten"):          # Versandlimit
        fam.c.api_keys.issue(fam.actor("Papa"))
    for _ in range(4):
        fam.reset_mail_limit()
        issue_key(fam, "Papa")
    fam.reset_mail_limit()
    with pytest.raises(RateLimitError, match="schon 5"):
        fam.c.api_keys.issue(fam.actor("Papa"))


def test_ohne_login_kein_zugang_mehr(fam):
    key = issue_key(fam, "Papa")
    fam.c.family.set_email("Papa", None)                         # Login gesperrt → Schlüssel wirkungslos
    assert fam.c.api_keys.person(key) is None


def test_person_entfernen_loescht_schluessel(fam):
    issue_key(fam, "Papa")
    fam.c.removals.remove(fam.person("Mama"), "Papa")
    assert fam.db.scalar("SELECT COUNT(*) FROM api_keys") == 0


def test_mail_mit_anleitung():
    transport = RecordingTransport()
    mailer = Mailer(transport, "absender@example.de", "https://geschenke.example.de")
    asyncio.run(mailer.send_notification(ApiKeyIssued("p@example.de", "Papa", "gsk_abc", 1_900_000_000)))
    text = transport.last_text()
    assert transport.messages[0]["Subject"] == "Dein KI-Zugang zur Geschenke-Liste"
    assert "MCP-Adresse:   https://geschenke.example.de/mcp" in text and "API-Schlüssel: gsk_abc" in text
    assert "Gültig bis:    17.03.2030" in text
    assert 'claude mcp add --transport http geschenke https://geschenke.example.de/mcp ' \
           '--header "Authorization: Bearer gsk_abc"' in text
    assert "https://geschenke.example.de/mcp/gsk_abc" in text


# --- MCP über HTTP ---------------------------------------------------------------

class McpClient:
    def __init__(self, http: TestClient, key: str | None, in_path: bool = False):
        self.http, self.key, self.in_path, self.next_id = http, key, in_path, 0

    def rpc(self, method: str, params: dict | None = None):
        self.next_id += 1
        headers = {"Accept": "application/json, text/event-stream"}
        path = "/mcp"
        if self.key and self.in_path:
            path += f"/{self.key}"
        elif self.key:
            headers["Authorization"] = f"Bearer {self.key}"
        return self.http.post(path, headers=headers, json={"jsonrpc": "2.0", "id": self.next_id, "method": method,
                                                           "params": params or {}})

    def call(self, tool: str, **args) -> dict:
        r = self.rpc("tools/call", {"name": tool, "arguments": args}).json()["result"]
        return r["structuredContent"]


@pytest.fixture
def http(fam):
    with TestClient(create_app(fam.c)) as client:
        yield client


def test_ohne_gueltigen_schluessel_401(fam, http):
    assert McpClient(http, None).rpc("tools/list").status_code == 401
    r = McpClient(http, "gsk_falsch").rpc("tools/list")
    assert r.status_code == 401 and r.headers["www-authenticate"].startswith("Bearer")


def test_mcp_ablauf(fam, http):
    client = McpClient(http, issue_key(fam, "Lena"))
    init = client.rpc("initialize", {"protocolVersion": types.LATEST_PROTOCOL_VERSION, "capabilities": {},
                                     "clientInfo": {"name": "test", "version": "1"}})
    assert init.status_code == 200 and "Überraschung" in init.json()["result"]["instructions"]

    names = {t["name"] for t in client.rpc("tools/list").json()["result"]["tools"]}
    assert {"wunsch_hinzufuegen", "geheimtipp_eintragen", "reservieren", "ueber_mich", "ki_zugang_sperren"} <= names
    assert "ki_zugang_anfordern" not in names                     # neue Schlüssel nur im Familien-Chat

    assert client.call("ueber_mich")["name"] == "Lena"
    w = client.call("wunsch_hinzufuegen", person="Papa", titel="Pfanne")["id"]
    assert client.call("reservieren", wunsch_id=w)["status"] == "von dir reserviert"
    # Papa (per Schlüssel) sieht auch über MCP nicht, dass Lena die Pfanne besorgt
    papa = McpClient(http, issue_key(fam, "Papa"), in_path=True)
    client.call("geheimtipp_eintragen", person="Papa", titel="Messerblock")   # Lena merkt sich einen Tipp
    own = json.dumps(papa.call("wuensche_anzeigen", person="Papa"))
    assert "Pfanne" in own and "Lena" not in own and "reserv" not in own and "Messerblock" not in own


def test_fehler_als_tool_fehler(fam, http):
    client = McpClient(http, issue_key(fam, "Lena"))
    result = client.rpc("tools/call", {"name": "reservieren", "arguments": {"wunsch_id": 999}}).json()["result"]
    assert result["isError"] is True and "gibt es nicht" in result["structuredContent"]["fehler"]


def test_gesperrter_schluessel_sofort_ungueltig(fam, http):
    key = issue_key(fam, "Lena")
    fam.c.api_keys.revoke_all(fam.person("Lena"))
    assert McpClient(http, key).rpc("tools/list").status_code == 401


def test_schluessel_im_log_geschwaerzt():
    record = logging.LogRecord("uvicorn.access", logging.INFO, "", 0, '%s - "%s %s HTTP/%s" %d',
                               ("1.2.3.4", "POST", "/mcp/gsk_geheim123", "1.1", 200), None)
    RedactKeysFilter().filter(record)
    assert "gsk_geheim123" not in record.getMessage() and "/mcp/***" in record.getMessage()


@pytest.mark.parametrize("header,value", [("x-access-token", "{key}"), ("X-API-Key", "{key}"),
                                          ("x-access-token", "Bearer {key}")])
def test_schluessel_in_anderen_headern(fam, http, header, value):
    key = issue_key(fam, "Lena")
    r = http.post("/mcp", headers={header: value.format(key=key), "Accept": "application/json, text/event-stream"},
                  json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
    assert r.status_code == 200 and r.json()["result"]["tools"]
