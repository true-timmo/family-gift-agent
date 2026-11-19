"""Face ID (Passkey) einrichten – nur angemeldet. Anmelden damit: routes/auth.py."""
from fastapi import APIRouter, Depends

from ...container import Container
from ...domain.models import Actor
from ..dependencies import container, current_actor, require_json
from ..schemas import PasskeyIn

router = APIRouter(prefix="/api/passkey", dependencies=[Depends(require_json)])


@router.post("/options")
async def options(actor: Actor = Depends(current_actor), c: Container = Depends(container)):
    return c.passkeys.registration_options(actor.person)


@router.post("")
async def register(data: PasskeyIn, actor: Actor = Depends(current_actor), c: Container = Depends(container)):
    c.passkeys.register(actor.person, data.credential, data.device)
    return {"ok": True}
