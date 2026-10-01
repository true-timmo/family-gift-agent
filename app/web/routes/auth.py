"""Anmeldung.

  1. /api/login/start     Name eingeben → bekannte Person mit Mail: Code wird verschickt
                                         → offene Einladung: Hinweis aufs Postfach
                                         → sonst: Registrierung nötig
  2. /api/login/register  Name + Mail + Familien-Code → Code wird an die neue Mail verschickt
  3. /api/login/verify    Name + Code → angemeldet (bei Registrierung: Konto wird jetzt angelegt)

Einladung per Mail (empfohlen): Der Link aus der Mail (?einladung=…) beweist die Adresse –
/api/login/invite/accept meldet direkt an, ohne Code. Der Familien-Code ist nur ein optionaler Ausweg.
"""
from fastapi import APIRouter, Depends, Request, Response

from ...container import Container
from ...domain.errors import AuthenticationError, NotFoundError
from ...domain.models import Actor, Person
from ...domain.values import email_address, masked_email, person_name
from ..dependencies import container, current_actor, login_attempts, require_json, session_cookie
from ..mail import mail_delivery
from ..schemas import NameIn, RegisterIn, TokenIn, VerifyIn
from ..security import AttemptGuard, SessionCookie

router = APIRouter(prefix="/api")
login = APIRouter(prefix="/api/login", dependencies=[Depends(require_json), Depends(login_attempts)])


async def _send_code(c: Container, name: str, email: str, register: bool) -> dict:
    code = c.login_codes.issue(name, email, register)
    async with mail_delivery("Die Mail", email):
        await c.mailer.send_login_code(email, name, code, c.login_codes.VALID_MINUTES)
    return {"step": "code", "email": masked_email(email)}


def _sign_in(c: Container, cookie: SessionCookie, response: Response, person: Person) -> dict:
    cookie.set(response, c.sessions.start(person))
    return {"name": person.name}


@login.post("/start")
async def start(data: NameIn, c: Container = Depends(container)):
    name = person_name(data.name)
    person = c.family.get(name)
    if person and person.email:
        return await _send_code(c, person.name, person.email, register=False)
    if invite := c.invitations.pending_for(name):
        return {"step": "invited", "name": invite.name, "email": masked_email(invite.email)}
    return {"step": "register", "name": person.name if person else name}


@login.post("/register")
async def register(data: RegisterIn, c: Container = Depends(container),
                   attempts: AttemptGuard = Depends(login_attempts)):
    name, email = person_name(data.name), email_address(data.email)
    with attempts.counting(AuthenticationError):        # nur ein falscher Familien-Code zählt
        name = c.login_codes.check_registration(name, email, data.family_code)
    return await _send_code(c, name, email, register=True)


@login.post("/verify")
async def verify(data: VerifyIn, response: Response, c: Container = Depends(container),
                 cookie: SessionCookie = Depends(session_cookie), attempts: AttemptGuard = Depends(login_attempts)):
    with attempts.counting():
        person = c.login_codes.verify(person_name(data.name), data.code)
    return _sign_in(c, cookie, response, person)


@login.post("/invite")
async def show_invite(data: TokenIn, c: Container = Depends(container),
                      attempts: AttemptGuard = Depends(login_attempts)):
    """Zeigt, wer eingeladen ist – nimmt die Einladung aber noch NICHT an.

    (Mail-Programme rufen Links teils automatisch auf; angenommen wird erst per Knopfdruck.)
    """
    with attempts.counting():
        invite = c.invitations.lookup(data.token)
        if not invite:
            raise NotFoundError("Diese Einladung ist abgelaufen oder wurde schon benutzt.")
    return {"name": invite.name, "eingeladen_von": invite.inviter}


@login.post("/invite/accept")
async def accept_invite(data: TokenIn, response: Response, c: Container = Depends(container),
                        cookie: SessionCookie = Depends(session_cookie),
                        attempts: AttemptGuard = Depends(login_attempts)):
    with attempts.counting():
        person = c.invitations.accept(data.token)
    return _sign_in(c, cookie, response, person)


@login.post("/invite/resend")
async def resend_invite(data: NameIn, c: Container = Depends(container)):
    invite = c.invitations.resend(person_name(data.name))
    if not invite:
        raise NotFoundError("Für diesen Namen gibt es keine offene Einladung.")
    async with mail_delivery("Die Einladung", invite.email):
        await c.mailer.send_invite(invite, c.invitations.VALID_DAYS)
    return {"email": masked_email(invite.email)}


@router.post("/logout")
async def logout(request: Request, response: Response, c: Container = Depends(container),
                 cookie: SessionCookie = Depends(session_cookie)):
    if token := cookie.read(request):
        c.sessions.end(token)
    cookie.clear(response)
    return {"ok": True}


@router.get("/me")
async def me(actor: Actor = Depends(current_actor), c: Container = Depends(container)):
    return {"name": actor.name, "admin": actor.is_admin, "verlauf": c.chat_history.recent(actor.id, limit=50)}
