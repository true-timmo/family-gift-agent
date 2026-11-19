"""Anmeldung.

  1. /api/login/start     Name eingeben → bekannte Person mit Mail: Code wird verschickt
                                           (jeder Code gilt 10 Minuten, auch wenn neuere kommen)
                                         → offene Einladung: Hinweis aufs Postfach
                                         → sonst: Registrierung nötig
  2. /api/login/register  Name + Mail + Familien-Code → Code wird an die neue Mail verschickt
  3. /api/login/verify    Name + Code → angemeldet (bei Registrierung: Konto wird jetzt angelegt)
     – oder Knopf in der Mail (#anmelden=…)
  Face ID (Passkey): /api/login/start antwortet mit step „passkey“, wenn eingerichtet;
     /api/login/passkey/options + /api/login/passkey melden ohne Mail an (Einrichten: routes/passkeys.py)
: /api/login/link zeigt den Namen, /api/login/link/accept meldet an

Einladung per Mail (empfohlen): Der Link aus der Mail (#einladung=…) beweist die Adresse –
/api/login/invite/accept meldet direkt an, ohne Code. Der Familien-Code ist nur ein optionaler Ausweg.
"""
from fastapi import APIRouter, Depends, Request, Response

from ...container import Container
from ...domain.errors import AuthenticationError, NotFoundError
from ...domain.models import Actor, Person
from ...domain.values import email_address, masked_email, person_name
from ...storage.database import now
from ..dependencies import container, current_actor, login_attempts, require_json, session_cookie
from ..mail import mail_delivery
from ..schemas import LoginStartIn, NameIn, OptionalNameIn, PasskeyIn, RegisterIn, TokenIn, VerifyIn
from ..security import AttemptGuard, SessionCookie

router = APIRouter(prefix="/api")
login = APIRouter(prefix="/api/login", dependencies=[Depends(require_json), Depends(login_attempts)])


def _code_step(c: Container, name: str, email: str, valid_until: int, already_sent: bool = False) -> dict:
    return {"step": "code", "name": name, "email": masked_email(email), "gueltig_bis": valid_until,
            "schon_verschickt": already_sent, "neuer_code_ab": c.login_codes.resend_allowed_at(name)}


async def _send_code(c: Container, name: str, email: str, register: bool) -> dict:
    issued = c.login_codes.issue(name, email, register)
    async with mail_delivery("Die Mail", email):
        await c.mailer.send_login_code(email, name, issued.code, c.login_codes.VALID_MINUTES, issued.link_token)
    return _code_step(c, name, email, issued.expires_at)


def _sign_in(c: Container, cookie: SessionCookie, response: Response, person: Person) -> dict:
    cookie.set(response, c.sessions.start(person))
    return {"name": person.name}


@login.post("/start")
async def start(data: LoginStartIn, c: Container = Depends(container)):
    name = person_name(data.name)
    person = c.family.get(name)
    if person and person.email and not data.resend and not data.code and c.passkeys.has_passkey(person):
        return {"step": "passkey", "name": person.name}       # Face ID statt Mail; Code bleibt als Ausweg
    if person and person.email:
        # Gerade erst eine Mail verschickt (Versandlimit) und deren Code gilt noch → einfach dabei bleiben,
        # statt mit „bitte warten“ zu antworten. Sonst kommt eine neue Mail; ältere Codes gelten trotzdem weiter.
        until = c.login_codes.valid_until(person.name, person.email)
        if until and not data.resend and c.login_codes.resend_allowed_at(person.name) > now():
            return _code_step(c, person.name, person.email, until, already_sent=True)
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


@login.post("/link")
async def show_login_link(data: TokenIn, c: Container = Depends(container),
                          attempts: AttemptGuard = Depends(login_attempts)):
    """Knopf aus der Anmelde-Mail: zeigt, für wen er gilt – angemeldet wird erst per Knopfdruck (siehe /invite)."""
    with attempts.counting():
        name = c.login_codes.link_owner(data.token)
        if not name:
            raise NotFoundError("Dieser Anmelde-Link ist abgelaufen oder wurde schon benutzt. Bitte melde dich neu an.")
    return {"name": name}


@login.post("/link/accept")
async def accept_login_link(data: TokenIn, response: Response, c: Container = Depends(container),
                            cookie: SessionCookie = Depends(session_cookie),
                            attempts: AttemptGuard = Depends(login_attempts)):
    with attempts.counting():
        person = c.login_codes.verify_link(data.token)
    return _sign_in(c, cookie, response, person)


@login.post("/passkey/options")
async def passkey_options(data: OptionalNameIn, c: Container = Depends(container)):
    return c.passkeys.login_options(person_name(data.name) if data.name else None)


@login.post("/passkey")
async def passkey_login(data: PasskeyIn, response: Response, c: Container = Depends(container),
                        cookie: SessionCookie = Depends(session_cookie),
                        attempts: AttemptGuard = Depends(login_attempts)):
    with attempts.counting():
        person = c.passkeys.login(data.credential)
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
