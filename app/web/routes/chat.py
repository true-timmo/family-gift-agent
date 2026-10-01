import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from ...container import Container
from ...domain.models import Actor
from ..dependencies import container, current_actor, require_json
from ..schemas import ChatIn

router = APIRouter(prefix="/api/chat")


@router.post("", dependencies=[Depends(require_json)])
async def chat(data: ChatIn, actor: Actor = Depends(current_actor), c: Container = Depends(container)):
    """Antwort als Server-Sent Events – Text erscheint schon, während das Modell noch schreibt."""
    async def events():
        async for event in c.agent.reply(actor, data.message.strip()):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/clear")
async def clear(actor: Actor = Depends(current_actor), c: Container = Depends(container)):
    c.chat_history.clear(actor.id)
    return {"ok": True}
