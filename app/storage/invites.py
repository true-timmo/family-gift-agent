import sqlite3

from ..domain.models import Invite
from .database import Database, now

_SELECT = """SELECT i.*, p.name AS name, inv.name AS inviter FROM invites i
             JOIN persons p ON p.id = i.person_id JOIN persons inv ON inv.id = i.invited_by"""
_VALID = "i.used_at IS NULL AND i.expires_at > ?"


def _invite(row: sqlite3.Row | None) -> Invite | None:
    if not row:
        return None
    return Invite(row["token_hash"], row["person_id"], row["name"], row["email"], row["invited_by"], row["inviter"])


class InviteRepository:
    def __init__(self, db: Database):
        self._db = db

    def add(self, token_hash: str, person_id: int, email: str, invited_by: int, expires_at: int) -> None:
        self._db.execute(
            "INSERT INTO invites (token_hash, person_id, email, invited_by, created_at, expires_at) "
            "VALUES (?, ?, ?, ?, ?, ?)", (token_hash, person_id, email, invited_by, now(), expires_at))

    def valid(self, token_hash: str) -> Invite | None:
        """Unbenutzte, nicht abgelaufene Einladung zum Link."""
        return _invite(self._db.one(f"{_SELECT} WHERE i.token_hash = ? AND {_VALID}", (token_hash, now())))

    def pending_for(self, name: str) -> Invite | None:
        """Offene Einladung einer Person, die noch nicht registriert ist."""
        return _invite(self._db.one(f"{_SELECT} WHERE p.name = ? AND p.email IS NULL AND {_VALID}",
                                    (name.strip(), now())))

    def pending_name_for_email(self, email: str, except_person_id: int | None) -> str | None:
        row = self._db.one(f"{_SELECT} WHERE lower(i.email) = lower(?) AND {_VALID} AND p.id IS NOT ?",
                           (email.strip(), now(), except_person_id))
        return row["name"] if row else None

    def count_sent_by(self, inviter_id: int, since: int) -> int:
        return self._db.scalar("SELECT COUNT(*) FROM invites WHERE invited_by = ? AND created_at > ?",
                               (inviter_id, since))

    def mark_used(self, token_hash: str) -> None:
        self._db.execute("UPDATE invites SET used_at = ? WHERE token_hash = ?", (now(), token_hash))

    def delete(self, token_hash: str) -> None:
        self._db.execute("DELETE FROM invites WHERE token_hash = ?", (token_hash,))

    def delete_open_for(self, person_id: int) -> None:
        self._db.execute("DELETE FROM invites WHERE person_id = ? AND used_at IS NULL", (person_id,))

    def delete_all_for(self, person_id: int) -> None:
        self._db.execute("DELETE FROM invites WHERE person_id = ?", (person_id,))

    def transfer_inviter(self, from_id: int, to_id: int) -> None:
        self._db.execute("UPDATE invites SET invited_by = ? WHERE invited_by = ?", (to_id, from_id))
