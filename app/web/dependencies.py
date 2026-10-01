"""FastAPI-Abhängigkeiten: Zugriff auf die Anwendung, angemeldete Person, Schutzmaßnahmen."""
from fastapi import Depends, HTTPException, Request

from ..container import Container
from ..domain.errors import PermissionDeniedError
from ..domain.models import Actor
from .security import AttemptGuard, FailedAttempts, SessionCookie


def container(request: Request) -> Container:
    return request.app.state.container


def session_cookie(request: Request) -> SessionCookie:
    return request.app.state.session_cookie


def login_attempts(request: Request) -> AttemptGuard:
    attempts: FailedAttempts = request.app.state.failed_attempts
    return attempts.guard(request)


async def require_json(request: Request) -> None:
    # Schutz gegen CSRF: Formulare fremder Seiten können kein application/json senden
    if request.headers.get("content-type", "").split(";")[0] != "application/json":
        raise HTTPException(415, "JSON erwartet")


async def current_actor(request: Request, c: Container = Depends(container),
                        cookie: SessionCookie = Depends(session_cookie)) -> Actor:
    person = c.sessions.person(cookie.read(request))
    if not person:
        raise HTTPException(401, "Nicht angemeldet")
    return c.admins.actor(person)


async def current_admin(actor: Actor = Depends(current_actor)) -> Actor:
    if not actor.is_admin:
        raise PermissionDeniedError("Das darf nur der Admin.")
    return actor
