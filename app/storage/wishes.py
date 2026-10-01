import sqlite3

from ..domain.errors import NotFoundError
from ..domain.models import Wish, WishDetails
from .database import Database, now

_SELECT = """SELECT w.*, p.name AS person_name, r.name AS reserver_name FROM wishes w
             JOIN persons p ON p.id = w.person_id LEFT JOIN persons r ON r.id = w.reserved_by"""


def _wish(row: sqlite3.Row) -> Wish:
    details = WishDetails(row["title"], row["description"], row["shop"], row["url"], row["price"])
    return Wish(id=row["id"], person_id=row["person_id"], created_by=row["created_by"], details=details,
                reserved_by=row["reserved_by"], deleted_at=row["deleted_at"],
                person_name=row["person_name"], reserver_name=row["reserver_name"])


class WishRepository:
    def __init__(self, db: Database):
        self._db = db

    def add(self, person_id: int, details: WishDetails, created_by: int) -> int:
        return self._db.execute(
            """INSERT INTO wishes (person_id, title, description, shop, url, price, created_by, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (person_id, details.title, details.description, details.shop, details.url, details.price,
             created_by, now())).lastrowid

    def require(self, wish_id: int) -> Wish:
        row = self._db.one(f"{_SELECT} WHERE w.id = ?", (wish_id,))
        if not row:
            raise NotFoundError(f"Wunsch Nr. {wish_id} gibt es nicht.")
        return _wish(row)

    def active_of(self, person_id: int) -> list[Wish]:
        """Nicht entfernte Wünsche einer Person, älteste zuerst."""
        return [_wish(r) for r in self._db.all(
            f"{_SELECT} WHERE w.person_id = ? AND w.deleted_at IS NULL ORDER BY w.created_at", (person_id,))]

    def reserved_by(self, person_id: int) -> list[Wish]:
        """Was jemand besorgt – auch inzwischen entfernte Wünsche (für den Hinweis)."""
        return [_wish(r) for r in self._db.all(
            f"{_SELECT} WHERE w.reserved_by = ? ORDER BY p.name, w.created_at", (person_id,))]

    def try_reserve(self, wish_id: int, person_id: int) -> bool:
        """Reserviert nur, wenn noch frei – so gewinnt bei gleichzeitigen Anfragen genau eine."""
        return self._db.execute(
            "UPDATE wishes SET reserved_by = ?, reserved_at = ? WHERE id = ? AND reserved_by IS NULL",
            (person_id, now(), wish_id)).rowcount == 1

    def release(self, wish_id: int) -> None:
        self._db.execute("UPDATE wishes SET reserved_by = NULL, reserved_at = NULL WHERE id = ?", (wish_id,))

    def update(self, wish_id: int, details: WishDetails) -> None:
        if changes := details.given():
            sets = ", ".join(f"{column} = ?" for column in changes)
            self._db.execute(f"UPDATE wishes SET {sets} WHERE id = ?", (*changes.values(), wish_id))

    def soft_delete(self, wish_id: int) -> None:
        self._db.execute("UPDATE wishes SET deleted_at = ? WHERE id = ?", (now(), wish_id))

    # --- beim Entfernen einer Person ---

    def release_all_reserved_by(self, person_id: int) -> int:
        return self._db.execute("UPDATE wishes SET reserved_by = NULL, reserved_at = NULL "
                                "WHERE reserved_by = ? AND person_id != ?", (person_id, person_id)).rowcount

    def delete_all_of(self, person_id: int) -> None:
        self._db.execute("DELETE FROM wishes WHERE person_id = ?", (person_id,))

    def transfer_created_by(self, from_id: int, to_id: int) -> None:
        self._db.execute("UPDATE wishes SET created_by = ? WHERE created_by = ?", (to_id, from_id))
