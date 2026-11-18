from dataclasses import dataclass

from ..domain.models import Person
from .database import Database, now
from .persons import person_from_row

_VALID = "k.revoked_at IS NULL AND k.expires_at > ?"


@dataclass(frozen=True)
class ExpiringKey:
    token_hash: str
    person: Person
    expires_at: int


class ApiKeyRepository:
    def __init__(self, db: Database):
        self._db = db

    def add(self, token_hash: str, person_id: int, expires_at: int) -> None:
        self._db.execute("INSERT INTO api_keys (token_hash, person_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
                         (token_hash, person_id, now(), expires_at))

    def person(self, token_hash: str) -> Person | None:
        """Besitzer eines gültigen Schlüssels – nur, solange die Person registriert ist."""
        return person_from_row(self._db.one(
            f"""SELECT p.* FROM api_keys k JOIN persons p ON p.id = k.person_id
                WHERE k.token_hash = ? AND {_VALID} AND p.email IS NOT NULL""", (token_hash, now())))

    def touch(self, token_hash: str) -> None:
        self._db.execute("UPDATE api_keys SET last_used_at = ? WHERE token_hash = ?", (now(), token_hash))

    def count_valid(self, person_id: int) -> int:
        return self._db.scalar(f"SELECT COUNT(*) FROM api_keys k WHERE k.person_id = ? AND {_VALID}",
                               (person_id, now()))

    def revoke_all(self, person_id: int) -> int:
        return self._db.execute(f"UPDATE api_keys AS k SET revoked_at = ? WHERE k.person_id = ? AND {_VALID}",
                                (now(), person_id, now())).rowcount

    def delete_all_for(self, person_id: int) -> None:
        self._db.execute("DELETE FROM api_keys WHERE person_id = ?", (person_id,))

    def expiring(self, before: int) -> list[ExpiringKey]:
        """Benutzte, gültige Schlüssel, die bis `before` ablaufen und noch keine Erinnerung bekamen –
        ohne die, für die es schon einen neueren gültigen Schlüssel derselben Person gibt."""
        rows = self._db.all(
            f"""SELECT k.token_hash, k.expires_at, p.* FROM api_keys k JOIN persons p ON p.id = k.person_id
                WHERE {_VALID} AND k.expires_at <= ? AND k.last_used_at IS NOT NULL AND k.reminded_at IS NULL
                  AND p.email IS NOT NULL
                  AND NOT EXISTS (SELECT 1 FROM api_keys n WHERE n.person_id = k.person_id AND n.revoked_at IS NULL
                                  AND n.expires_at > k.expires_at)""", (now(), before))
        return [ExpiringKey(r["token_hash"], person_from_row(r), r["expires_at"]) for r in rows]

    def mark_reminded(self, token_hash: str) -> None:
        self._db.execute("UPDATE api_keys SET reminded_at = ? WHERE token_hash = ?", (now(), token_hash))
