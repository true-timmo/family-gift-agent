"""Web-Server: Login, Chat (Server-Sent Events) und die statische Oberfläche."""
import asyncio
import hmac
import json
import logging
import os
import re
import time
from collections import defaultdict
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import agent, db, mailer

COOKIE = "geschenke_session"
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "true").lower() != "false"
STATIC = Path(__file__).parent / "static"

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
conn = db.connect()


async def current_person(request: Request):
    person = db.session_person(conn, request.cookies.get(COOKIE))
    if not person:
        raise HTTPException(401, "Nicht angemeldet")
    return person


async def require_json(request: Request) -> None:
    # Schutz gegen CSRF: Formulare fremder Seiten können kein application/json senden
    if request.headers.get("content-type", "").split(";")[0] != "application/json":
        raise HTTPException(415, "JSON erwartet")


# --- Login per Einmal-Code (OTP) -----------------------------------------------
#
#  1. /api/login/start     Name eingeben → bekannte Person mit Mail: Code wird verschickt
#                                         → sonst: Registrierung nötig
#  2. /api/login/register  Name + Mail + Familien-Code → Code wird an die neue Mail verschickt
#  3. /api/login/verify    Name + Code → angemeldet (bei Registrierung: Konto wird jetzt angelegt)
#
#  Einladung per Mail (empfohlen): Eingeloggte laden mit Name + Mail ein (/api/einladung).
#  Der Link aus der Mail (?einladung=…) beweist die Mail-Adresse – /api/login/invite/accept
#  meldet direkt an, ohne Code. Der Familien-Code ist nur noch ein optionaler Ausweg.

FAMILY_CODE = os.environ.get("FAMILY_CODE", "").strip()
NAME_RE = re.compile(r"^[^\W\d_](?:[\w .'-]{0,28}[^\W_])?$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
log = logging.getLogger("uvicorn.error")

_failed: dict[str, list[float]] = defaultdict(list)
_background: set[asyncio.Task] = set()


def _notify(outbox: list[dict]) -> None:
    """Benachrichtigungen im Hintergrund verschicken – die Antwort wartet nicht darauf."""
    if outbox:
        task = asyncio.create_task(mailer.send_notifications(outbox, log))
        _background.add(task)
        task.add_done_callback(_background.discard)


def _check_ip(request: Request) -> str:
    ip = request.headers.get("x-real-ip") or request.client.host
    now = time.time()
    _failed[ip] = [t for t in _failed[ip] if now - t < 900]
    if len(_failed[ip]) >= 10:
        raise HTTPException(429, "Zu viele Fehlversuche. Bitte in 15 Minuten nochmal.")
    return ip


def _clean_name(name: str) -> str:
    name = " ".join(name.split())
    if not NAME_RE.match(name):
        raise HTTPException(400, "Bitte einen Namen aus Buchstaben angeben, z.B. „Mama“ oder „Oma Gisela“.")
    return name


def _mask(email: str) -> str:
    user, domain = email.split("@", 1)
    return f"{user[0]}***@{domain}"


async def _send_code(name: str, email: str, register: bool) -> dict:
    try:
        code = db.create_otp(conn, name, email, register)
    except db.WishError as e:
        raise HTTPException(429, str(e))
    try:
        await mailer.send_code(email, name, code, db.OTP_MINUTES)
    except Exception:
        log.exception("Mailversand an %s fehlgeschlagen", _mask(email))
        raise HTTPException(502, "Die Mail konnte nicht verschickt werden. Bitte später nochmal versuchen.")
    return {"step": "code", "email": _mask(email)}


class StartIn(BaseModel):
    name: str = Field(max_length=60)


class RegisterIn(StartIn):
    email: str = Field(max_length=200)
    family_code: str = Field(max_length=100)


class InviteIn(BaseModel):
    token: str = Field(max_length=100)


class VerifyIn(StartIn):
    code: str = Field(max_length=10)


@app.post("/api/login/start", dependencies=[Depends(require_json)])
async def login_start(data: StartIn, request: Request):
    _check_ip(request)
    name = _clean_name(data.name)
    person = db.get_person(conn, name)
    if person and person["email"]:
        return await _send_code(person["name"], person["email"], register=False)
    if inv := db.pending_invite(conn, name):
        return {"step": "invited", "name": inv["name"], "email": _mask(inv["email"])}
    return {"step": "register", "name": person["name"] if person else name}


@app.post("/api/login/register", dependencies=[Depends(require_json)])
async def login_register(data: RegisterIn, request: Request):
    ip = _check_ip(request)
    name, email = _clean_name(data.name), data.email.strip()
    if not FAMILY_CODE:
        raise HTTPException(403, "Neu dabei? Dann bitte jemanden aus der Familie, dich einzuladen.")
    if not hmac.compare_digest(data.family_code.strip().lower().encode(), FAMILY_CODE.lower().encode()):
        _failed[ip].append(time.time())
        raise HTTPException(403, "Der Familien-Code stimmt nicht.")
    if not EMAIL_RE.match(email):
        raise HTTPException(400, "Bitte eine gültige Mail-Adresse angeben.")
    person = db.get_person(conn, name)
    if person and person["email"]:
        raise HTTPException(409, "Diesen Namen gibt es schon. Bitte zurück und nur den Namen eingeben.")
    if db.email_owner(conn, email, person["id"] if person else None):
        raise HTTPException(409, "Diese E-Mail-Adresse wird schon verwendet.")   # bewusst ohne Namen (öffentlich)
    return await _send_code(person["name"] if person else name, email, register=True)


# --- Einladungen ---------------------------------------------------------------

def _invite_link(token: str) -> str:
    return f"{mailer.APP_URL}/?einladung={token}"


async def _send_invite(email: str, name: str, inviter: str, token: str) -> None:
    try:
        await mailer.send_invite(email, name, inviter, _invite_link(token), db.INVITE_DAYS)
    except Exception:
        log.exception("Einladung an %s konnte nicht verschickt werden", _mask(email))
        raise HTTPException(502, "Die Einladung konnte nicht verschickt werden. Bitte später nochmal versuchen.")


class TokenIn(BaseModel):
    token: str = Field(max_length=100)


@app.post("/api/login/invite", dependencies=[Depends(require_json)])
async def login_invite(data: TokenIn, request: Request):
    """Zeigt, wer eingeladen ist – nimmt die Einladung aber noch NICHT an.

    (Mail-Programme rufen Links teils automatisch auf; angenommen wird erst per Knopfdruck.)
    """
    ip = _check_ip(request)
    inv = db.get_invite(conn, data.token)
    if not inv:
        _failed[ip].append(time.time())
        raise HTTPException(404, "Diese Einladung ist abgelaufen oder wurde schon benutzt.")
    return {"name": inv["name"], "eingeladen_von": inv["inviter"]}


@app.post("/api/login/invite/accept", dependencies=[Depends(require_json)])
async def login_invite_accept(data: TokenIn, request: Request, response: Response):
    ip = _check_ip(request)
    outbox: list[dict] = []
    try:
        person = db.accept_invite(conn, data.token, outbox)
    except db.WishError as e:
        _failed[ip].append(time.time())
        raise HTTPException(404, str(e))
    _notify(outbox)
    token = db.create_session(conn, person["id"])
    response.set_cookie(COOKIE, token, max_age=db.SESSION_DAYS * 86400, httponly=True,
                        secure=COOKIE_SECURE, samesite="strict")
    return {"name": person["name"]}


@app.post("/api/login/invite/resend", dependencies=[Depends(require_json)])
async def login_invite_resend(data: StartIn, request: Request):
    _check_ip(request)
    try:
        res = db.resend_invite(conn, _clean_name(data.name))
    except db.WishError as e:
        raise HTTPException(429, str(e))
    if not res:
        raise HTTPException(404, "Für diesen Namen gibt es keine offene Einladung.")
    token, inv = res
    await _send_invite(inv["email"], inv["name"], inv["inviter"], token)
    return {"email": _mask(inv["email"])}


@app.post("/api/login/verify", dependencies=[Depends(require_json)])
async def login_verify(data: VerifyIn, request: Request, response: Response):
    ip = _check_ip(request)
    outbox: list[dict] = []
    try:
        person = db.verify_otp(conn, _clean_name(data.name), data.code, outbox)
    except db.WishError as e:
        _failed[ip].append(time.time())
        raise HTTPException(401, str(e))
    _notify(outbox)
    token = db.create_session(conn, person["id"])
    response.set_cookie(COOKIE, token, max_age=db.SESSION_DAYS * 86400, httponly=True,
                        secure=COOKIE_SECURE, samesite="strict")
    return {"name": person["name"]}


@app.post("/api/logout")
async def logout(request: Request, response: Response):
    if token := request.cookies.get(COOKIE):
        db.delete_session(conn, token)
    response.delete_cookie(COOKIE)
    return {"ok": True}


@app.get("/api/me")
async def me(person=Depends(current_person)):
    return {"name": person["name"], "admin": db.is_admin(person),
            "verlauf": db.recent_messages(conn, person["id"], limit=50)}


@app.get("/api/familie")
async def familie(person=Depends(current_person)):
    # Nur Name + Status (registriert/eingeladen/offen) – keine Mail-Adressen, keine Wünsche
    return [{"name": p["name"], "status": p["status"], "du": p["id"] == person["id"]}
            for p in db.family_status(conn)]


class EinladungIn(BaseModel):
    name: str = Field(max_length=60)
    email: str = Field(max_length=200)
    bestehend: bool = False      # True = „Einladen“/„Erneut“ bei einer vorhandenen Person in der Liste


@app.post("/api/einladung", dependencies=[Depends(require_json)])
async def einladung(data: EinladungIn, person=Depends(current_person)):
    email = data.email.strip()
    if not EMAIL_RE.match(email):
        raise HTTPException(400, "Bitte eine gültige Mail-Adresse angeben.")
    try:
        token, name = db.create_invite(conn, person["id"], _clean_name(data.name), email, existing=data.bestehend)
    except db.WishError as e:
        raise HTTPException(409, str(e))
    await _send_invite(email, name, person["name"], token)
    return {"name": name, "email": email}


# --- Admin --------------------------------------------------------------------

async def current_admin(person=Depends(current_person)):
    if not db.is_admin(person):
        raise HTTPException(403, "Das darf nur der Admin.")
    return person


class PersonIn(BaseModel):
    name: str = Field(max_length=60)


@app.post("/api/admin/person-entfernen", dependencies=[Depends(require_json)])
async def person_entfernen(data: PersonIn, admin=Depends(current_admin)):
    outbox: list[dict] = []
    try:
        result = db.delete_person(conn, admin["id"], data.name, outbox)
    except db.WishError as e:
        raise HTTPException(409, str(e))
    log.info("Admin %s hat %s entfernt", admin["name"], result["name"])
    _notify(outbox)
    return result


# --- Chat --------------------------------------------------------------------

class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


@app.post("/api/chat", dependencies=[Depends(require_json)])
async def chat(data: ChatIn, person=Depends(current_person)):
    async def events():
        async for ev in agent.chat(conn, person, data.message.strip()):
            yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/chat/clear")
async def clear(person=Depends(current_person)):
    db.clear_messages(conn, person["id"])
    return {"ok": True}


@app.get("/healthz")
async def health():
    return {"ok": True}


# --- Oberfläche --------------------------------------------------------------

@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
