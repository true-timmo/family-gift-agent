from ..domain.kinship import Fact, Kin
from .database import Database, now


class RelationRepository:
    """Gespeicherte Verwandtschaftsangaben (immer in normalisierter Richtung, siehe Fact.normalized)."""

    def __init__(self, db: Database):
        self._db = db

    def all(self) -> list[Fact]:
        return [Fact(r["person_id"], r["relative_id"], Kin(r["kind"]))
                for r in self._db.all("SELECT person_id, relative_id, kind FROM relations")]

    def add(self, fact: Fact, created_by: int) -> None:
        f = fact.normalized()
        self._db.execute("INSERT OR IGNORE INTO relations (person_id, relative_id, kind, created_by, created_at) "
                         "VALUES (?, ?, ?, ?, ?)", (f.person, f.relative, f.kin.value, created_by, now()))

    def delete(self, fact: Fact) -> bool:
        f = fact.normalized()
        return self._db.execute("DELETE FROM relations WHERE person_id = ? AND relative_id = ? AND kind = ?",
                                (f.person, f.relative, f.kin.value)).rowcount > 0

    def delete_all_for(self, person_id: int) -> None:
        self._db.execute("DELETE FROM relations WHERE person_id = ? OR relative_id = ?", (person_id, person_id))
        self._db.execute("UPDATE relations SET created_by = NULL WHERE created_by = ?", (person_id,))
