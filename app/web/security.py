"""Schutz der Anmeldung: Sitzungs-Cookie und Sperre nach zu vielen Fehlversuchen je IP-Adresse."""
import time
from collections import defaultdict
from contextlib import contextmanager
from typing import Iterator

from fastapi import Request, Response

from ..domain.errors import DomainError, RateLimitError
from ..services import SessionService


class SessionCookie:
    NAME = "geschenke_session"

    def __init__(self, secure: bool):
        self._secure = secure

    def read(self, request: Request) -> str | None:
        return request.cookies.get(self.NAME)

    def set(self, response: Response, token: str) -> None:
        response.set_cookie(self.NAME, token, max_age=SessionService.VALID_DAYS * 86400, httponly=True,
                            secure=self._secure, samesite="strict")

    def clear(self, response: Response) -> None:
        response.delete_cookie(self.NAME)


class FailedAttempts:
    """Nach 10 Fehlversuchen (falscher Code, ungültige Einladung …) ist eine IP 15 Minuten gesperrt."""

    def __init__(self, limit: int = 10, window_seconds: int = 900):
        self._limit = limit
        self._window = window_seconds
        self._failures: dict[str, list[float]] = defaultdict(list)

    def guard(self, request: Request) -> "AttemptGuard":
        """Prüft die Sperre sofort und liefert einen Wächter, der weitere Fehlversuche zählt."""
        ip = request.headers.get("x-real-ip") or request.client.host
        now = time.time()
        self._failures[ip] = [t for t in self._failures[ip] if now - t < self._window]
        if len(self._failures[ip]) >= self._limit:
            raise RateLimitError("Zu viele Fehlversuche. Bitte in 15 Minuten nochmal.")
        return AttemptGuard(self, ip)

    def record(self, ip: str) -> None:
        self._failures[ip].append(time.time())


class AttemptGuard:
    def __init__(self, attempts: FailedAttempts, ip: str):
        self._attempts = attempts
        self._ip = ip

    @contextmanager
    def counting(self, *errors: type[DomainError]) -> Iterator[None]:
        """Zählt die angegebenen Fehler (Standard: alle fachlichen) als Fehlversuch."""
        try:
            yield
        except errors or DomainError:
            self._attempts.record(self._ip)
            raise
