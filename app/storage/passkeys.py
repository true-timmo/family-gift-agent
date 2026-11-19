"""Passkeys (Face ID, Touch ID, Fingerabdruck): öffentliche Schlüssel der Geräte und laufende Anfragen."""
from dataclasses import dataclass

from ..domain.models import Person
from .database import Database, now
from .persons import person_from_row


@dataclass(frozen=True)
class StoredPasskey:
    credential_id: str      # base64url
    person: Person
    public_key: bytes
    sign_count: int


class PasskeyRepository:
    def __init__(self, db: Database):
        self._db = db

    def add(self, credential_id: str, person_id: int, public_key: bytes, sign_count: int, device: str) -> None:
        self._db.execute(
            "INSERT INTO passkeys (credential_id, person_id, public_key, sign_count, device, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)", (credential_id, person_id, public_key, sign_count, device, now()))

    def get(self, credential_id: str) -> StoredPasskey | None:
        """Nur, solange die Person registriert ist (Login nicht gesperrt)."""
        row = self._db.one("""SELECT k.credential_id, k.public_key, k.sign_count, p.* FROM passkeys k
                              JOIN persons p ON p.id = k.person_id
                              WHERE k.credential_id = ? AND p.email IS NOT NULL""", (credential_id,))
        return StoredPasskey(row["credential_id"], person_from_row(row), row["public_key"], row["sign_count"]) \
            if row else None

    def ids_of(self, person_id: int) -> list[str]:
        return [r[0] for r in self._db.all("SELECT credential_id FROM passkeys WHERE person_id = ?", (person_id,))]

    def used(self, credential_id: str, sign_count: int) -> None:
        self._db.execute("UPDATE passkeys SET sign_count = ?, last_used_at = ? WHERE credential_id = ?",
                         (sign_count, now(), credential_id))

    def delete_all_for(self, person_id: int) -> int:
        return self._db.execute("DELETE FROM passkeys WHERE person_id = ?", (person_id,)).rowcount


class PasskeyChallengeRepository:
    """Einmalige Zufallswerte für Einrichten und Anmelden – kurz gültig, nur einmal verwendbar."""

    def __init__(self, db: Database):
        self._db = db

    def add(self, challenge: str, purpose: str, person_id: int | None, expires_at: int) -> None:
        self._db.execute("DELETE FROM passkey_challenges WHERE expires_at < ?", (now(),))
        self._db.execute("INSERT INTO passkey_challenges (challenge, purpose, person_id, expires_at) "
                         "VALUES (?, ?, ?, ?)", (challenge, purpose, person_id, expires_at))

    def take(self, challenge: str, purpose: str) -> tuple[bool, int | None]:
        """Verbraucht den Wert. Gibt (gültig, Person) zurück."""
        row = self._db.one("SELECT person_id FROM passkey_challenges WHERE challenge = ? AND purpose = ? "
                           "AND expires_at > ?", (challenge, purpose, now()))
        self._db.execute("DELETE FROM passkey_challenges WHERE challenge = ?", (challenge,))
        return (True, row["person_id"]) if row else (False, None)
