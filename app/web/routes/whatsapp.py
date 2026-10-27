"""Webhook für WAHA: neue WhatsApp-Nachrichten. Nur mit gültiger HMAC-Signatur (gemeinsamer Schlüssel)."""
import hashlib
import hmac
import json

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request

from ...container import Container
from ..dependencies import container

router = APIRouter(prefix="/api/whatsapp")


@router.post("/webhook")
async def webhook(request: Request, background: BackgroundTasks, c: Container = Depends(container)):
    if not c.whatsapp:
        raise HTTPException(404)
    body = await request.body()
    expected = hmac.new(c.settings.whatsapp.hmac_key.encode(), body, hashlib.sha512).hexdigest()
    if not hmac.compare_digest(expected, request.headers.get("x-webhook-hmac", "")):
        raise HTTPException(401, "Signatur ungültig")
    background.add_task(c.whatsapp.handle_event, json.loads(body))   # WAHA bekommt sofort 200
    return {"ok": True}
