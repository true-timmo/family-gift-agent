"""Familienliste, Einladungen und Admin-Funktionen."""
import logging

from fastapi import APIRouter, Depends

from ...container import Container
from ...domain.models import Actor
from ...domain.values import email_address, person_name
from ..dependencies import container, current_actor, current_admin, require_json
from ..mail import mail_delivery
from ..schemas import InvitationIn, NameIn

router = APIRouter(prefix="/api")
log = logging.getLogger("uvicorn.error")


@router.get("/familie")
async def family(actor: Actor = Depends(current_actor), c: Container = Depends(container)):
    # Nur Name + Status – keine Mail-Adressen, keine Wünsche
    return [{"name": m.name, "status": m.status, "du": m.id == actor.id} for m in c.family.members()]


@router.post("/einladung", dependencies=[Depends(require_json)])
async def invite(data: InvitationIn, actor: Actor = Depends(current_actor), c: Container = Depends(container)):
    email = email_address(data.email)
    issued = c.invitations.invite(actor.person, person_name(data.name), email, existing=data.bestehend)
    async with mail_delivery("Die Einladung", email):
        await c.mailer.send_invite(issued, c.invitations.VALID_DAYS)
    return {"name": issued.name, "email": email}


@router.post("/admin/person-entfernen", dependencies=[Depends(require_json)])
async def remove_person(data: NameIn, admin: Actor = Depends(current_admin), c: Container = Depends(container)):
    removal = c.removals.remove(admin.person, data.name)
    log.info("Admin %s hat %s entfernt", admin.name, removal.name)
    return {"name": removal.name, "wuensche_geloescht": removal.wishes_deleted,
            "reservierungen_freigegeben": removal.reservations_released}
