import sqlite3

from ..domain.errors import NotFoundError
from ..domain.models import FamilyMember, MemberStatus, Person
from .database import Database, now


def _person(row: sqlite3.Row | None) -> Person | None:
    return Person(row["id"], row["name"], row["email"]) if row else None


class PersonRepository:
    """Namen sind eindeutig, Groß-/Kleinschreibung zählt dabei nicht (COLLATE NOCASE)."""

    def __init__(self, db: Database):
        self._db = db

    def add(self, name: str, email: str | None = None) -> int:
        return self._db.execute("INSERT INTO persons (name, email, created_at) VALUES (?, ?, ?)",
                                (name.strip(), email, now())).lastrowid

    def by_id(self, person_id: int) -> Person | None:
        return _person(self._db.one("SELECT * FROM persons WHERE id = ?", (person_id,)))

    def by_name(self, name: str) -> Person | None:
        return _person(self._db.one("SELECT * FROM persons WHERE name = ?", (name.strip(),)))

    def by_email(self, email: str) -> Person | None:
        return _person(self._db.one("SELECT * FROM persons WHERE lower(email) = lower(?)", (email.strip(),)))

    def require(self, name: str) -> Person:
        """Wie by_name, aber mit einer Fehlermeldung, die dem Modell beim Korrigieren hilft."""
        if person := self.by_name(name):
            return person
        known = ", ".join(p.name for p in self.all())
        raise NotFoundError(f"Ich kenne niemanden namens '{name}'. Bekannt sind: {known}.")

    def all(self) -> list[Person]:
        return [_person(r) for r in self._db.all("SELECT * FROM persons ORDER BY name")]

    def members(self) -> list[FamilyMember]:
        """Alle Personen mit Status registriert / eingeladen / offen."""
        rows = self._db.all(
            """SELECT p.id, p.name, p.email IS NOT NULL AS registered,
                      EXISTS(SELECT 1 FROM invites i WHERE i.person_id = p.id AND i.used_at IS NULL
                             AND i.expires_at > ?) AS invited
               FROM persons p ORDER BY p.name""", (now(),))
        return [FamilyMember(r["id"], r["name"],
                             MemberStatus.REGISTERED if r["registered"]
                             else MemberStatus.INVITED if r["invited"] else MemberStatus.OPEN)
                for r in rows]

    def set_email(self, person_id: int, email: str | None) -> None:
        self._db.execute("UPDATE persons SET email = ? WHERE id = ?", (email, person_id))

    def delete(self, person_id: int) -> None:
        self._db.execute("DELETE FROM persons WHERE id = ?", (person_id,))
