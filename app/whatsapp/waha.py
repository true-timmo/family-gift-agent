"""Schnittstelle zu WAHA (WhatsApp HTTP API) im Nachbar-Container."""
import httpx

from ..config import WhatsAppSettings


class WahaClient:
    def __init__(self, settings: WhatsAppSettings, http: httpx.AsyncClient | None = None):
        self._session = settings.session
        self._http = http or httpx.AsyncClient(base_url=settings.url, timeout=30,
                                               headers={"X-Api-Key": settings.api_key})

    async def send_text(self, chat_id: str, text: str) -> None:
        await self._post("/api/sendText", chatId=chat_id, text=text, linkPreview=False)

    async def mark_seen(self, chat_id: str) -> None:
        await self._post("/api/sendSeen", chatId=chat_id)

    async def typing(self, chat_id: str, active: bool) -> None:
        await self._post("/api/startTyping" if active else "/api/stopTyping", chatId=chat_id)

    async def _post(self, path: str, **body) -> None:
        response = await self._http.post(path, json={"session": self._session, **body})
        response.raise_for_status()
