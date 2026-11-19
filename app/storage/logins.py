"""Anmeldung: Einmal-Codes, Mail-Versandprotokoll und Sitzungen."""
from dataclasses import dataclass

from ..domain.models import Person
from .database import Database, now
from .persons import person_from_row


@dataclass(frozen=True)
class LoginCode:
    name: str
    email: str
    code_hash: str
    expires_at: int
    attempts: int
    register: bool       # True = legt nach Bestätigung Person bzw. Mail-Adresse an
    link_hash: str | None = None


def _login_code(row) -> LoginCode | None:
    if not row:
        return None
    return LoginCode(row["name"], row["email"], row["code_hash"], row["expires_at"], row["attempts"],
                     bool(row["register"]), row["link_hash"])


class LoginCodeRepository:
    """Mehrere Codes je Name; „benutzbar“ = nicht abgelaufen und noch Versuche übrig."""

    def __init__(self, db: Database):
        self._db = db

    def add(self, name: str, email: str, code_hash: str, link_hash: str, expires_at: int, register: bool) -> None:
        self._db.execute(
            "INSERT INTO login_codes (name, email, code_hash, link_hash, expires_at, register) VALUES (?, ?, ?, ?, ?, ?)",
            (name, email, code_hash, link_hash, expires_at, int(register)))
        self._db.execute("DELETE FROM login_codes WHERE expires_at < ?", (now() - 86400,))   # Altlasten

    def usable(self, name: str, max_attempts: int) -> list[LoginCode]:
        """Benutzbare Codes, neueste zuerst."""
        rows = self._db.all("SELECT * FROM login_codes WHERE name = ? AND expires_at > ? AND attempts < ? "
                            "ORDER BY expires_at DESC", (name, now(), max_attempts))
        return [_login_code(r) for r in rows]

    def by_link(self, link_hash: str) -> LoginCode | None:
        return _login_code(self._db.one("SELECT * FROM login_codes WHERE link_hash = ?", (link_hash,)))

    def count_failure(self, name: str) -> None:
        """Ein Fehlversuch zählt für alle noch gültigen Codes des Namens."""
        self._db.execute("UPDATE login_codes SET attempts = attempts + 1 WHERE name = ? AND expires_at > ?",
                         (name, now()))

    def delete(self, name: str) -> None:
        self._db.execute("DELETE FROM login_codes WHERE name = ?", (name,))


class MailLog:
    """Wann an welchen Namen eine Mail ging (Codes und Einladungen) – Grundlage für das Versandlimit."""

    def __init__(self, db: Database):
        self._db = db

    def times_since(self, name: str, since: int) -> list[int]:
        """Versandzeitpunkte seit `since`, älteste zuerst."""
        return [r[0] for r in self._db.all("SELECT sent_at FROM otp_sends WHERE name = ? AND sent_at > ? "
                                           "ORDER BY sent_at", (name, since))]

    def record(self, name: str, at: int) -> None:
        self._db.execute("INSERT INTO otp_sends (name, sent_at) VALUES (?, ?)", (name, at))

    def prune(self, before: int) -> None:
        self._db.execute("DELETE FROM otp_sends WHERE sent_at < ?", (before,))

    def delete_for(self, name: str) -> None:
        self._db.execute("DELETE FROM otp_sends WHERE name = ?", (name,))


class SessionRepository:
    def __init__(self, db: Database):
        self._db = db

    def add(self, token_hash: str, person_id: int, expires_at: int) -> None:
        self._db.execute("INSERT INTO sessions (token_hash, person_id, expires_at) VALUES (?, ?, ?)",
                         (token_hash, person_id, expires_at))

    def person(self, token_hash: str) -> Person | None:
        row = self._db.one("""SELECT p.* FROM sessions s JOIN persons p ON p.id = s.person_id
                              WHERE s.token_hash = ? AND s.expires_at > ?""", (token_hash, now()))
        return person_from_row(row)

    def delete(self, token_hash: str) -> None:
        self._db.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))

    def delete_all_for(self, person_id: int) -> int:
        return self._db.execute("DELETE FROM sessions WHERE person_id = ?", (person_id,)).rowcount
