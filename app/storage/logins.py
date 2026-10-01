"""Anmeldung: Einmal-Codes, Mail-Versandprotokoll und Sitzungen."""
from dataclasses import dataclass

from ..domain.models import Person
from .database import Database, now


@dataclass(frozen=True)
class LoginCode:
    name: str
    email: str
    code_hash: str
    expires_at: int
    attempts: int
    register: bool       # True = legt nach Bestätigung Person bzw. Mail-Adresse an


class LoginCodeRepository:
    """Pro Name höchstens ein aktiver Code."""

    def __init__(self, db: Database):
        self._db = db

    def replace(self, name: str, email: str, code_hash: str, expires_at: int, register: bool) -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO otp_codes (name, email, code_hash, expires_at, attempts, register) "
            "VALUES (?, ?, ?, ?, 0, ?)", (name, email, code_hash, expires_at, int(register)))

    def get(self, name: str) -> LoginCode | None:
        row = self._db.one("SELECT * FROM otp_codes WHERE name = ?", (name,))
        if not row:
            return None
        return LoginCode(row["name"], row["email"], row["code_hash"], row["expires_at"], row["attempts"],
                         bool(row["register"]))

    def count_failure(self, name: str) -> None:
        self._db.execute("UPDATE otp_codes SET attempts = attempts + 1 WHERE name = ?", (name,))

    def delete(self, name: str) -> None:
        self._db.execute("DELETE FROM otp_codes WHERE name = ?", (name,))


class MailLog:
    """Wann an welchen Namen eine Mail ging (Codes und Einladungen) – Grundlage für das Versandlimit."""

    def __init__(self, db: Database):
        self._db = db

    def count_since(self, name: str, since: int) -> int:
        return self._db.scalar("SELECT COUNT(*) FROM otp_sends WHERE name = ? AND sent_at > ?", (name, since))

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
        return Person(row["id"], row["name"], row["email"]) if row else None

    def delete(self, token_hash: str) -> None:
        self._db.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))

    def delete_all_for(self, person_id: int) -> int:
        return self._db.execute("DELETE FROM sessions WHERE person_id = ?", (person_id,)).rowcount
