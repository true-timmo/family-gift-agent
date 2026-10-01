"""Regeln für Wünsche und Reservierungen.

Sie stehen hier im Code – nicht im Prompt –, damit das Sprachmodell sie weder vergessen noch umgehen kann.
"""
from dataclasses import replace

from ..domain.errors import ConflictError, PermissionDeniedError
from ..domain.models import Actor, ListedWish, Reservation, Wish, WishDetails, WishList
from ..storage import Database, WishRepository
from .directory import RemovalNotices
from .relations import PersonResolver


class WishService:
    def __init__(self, db: Database, resolver: PersonResolver, wishes: WishRepository, notices: RemovalNotices):
        self._db = db
        self._resolver = resolver
        self._wishes = wishes
        self._notices = notices

    def add(self, actor: Actor, person_name: str, details: WishDetails) -> Wish:
        person = self._resolver.resolve(actor.person, person_name)
        wish_id = self._wishes.add(person.id, replace(details, title=details.title.strip()), created_by=actor.id)
        return self._wishes.require(wish_id)

    def list_for(self, actor: Actor, person_name: str) -> WishList:
        """Wünsche einer Person – je nachdem, WER fragt:

        - Die Person selbst sieht ALLE, ohne jeden Hinweis auf Reservierungen (Überraschungsschutz).
        - Andere sehen den Status: offen, von dir reserviert oder besorgt (von jemand anderem).
          Von anderen reservierte Wünsche stehen am Ende.
        """
        person = self._resolver.resolve(actor.person, person_name)
        wishes = self._wishes.active_of(person.id)
        if person.id == actor.id:
            return WishList(person, is_own=True, entries=[ListedWish(w) for w in wishes])
        entries = [ListedWish(w, self._reservation(w, actor)) for w in wishes]
        entries.sort(key=lambda e: e.reservation == Reservation.TAKEN)   # stabil: sonst bleibt die Reihenfolge
        return WishList(person, is_own=False, entries=entries)

    @staticmethod
    def _reservation(wish: Wish, actor: Actor) -> Reservation:
        if wish.reserved_by is None:
            return Reservation.OPEN
        return Reservation.MINE if wish.reserved_by == actor.id else Reservation.TAKEN

    def reserve(self, actor: Actor, wish_id: int) -> Wish:
        with self._db.transaction():
            wish = self._wishes.require(wish_id)
            # Reihenfolge wichtig: bei eigenen Wünschen NICHT verraten, ob sie reserviert sind
            if wish.person_id == actor.id:
                raise PermissionDeniedError("Eigene Wünsche kann man nicht reservieren.")
            if wish.is_deleted:
                raise ConflictError("Dieser Wunsch wurde entfernt.")
            if wish.reserved_by == actor.id:
                return wish
            if not self._wishes.try_reserve(wish_id, actor.id):
                by = self._wishes.require(wish_id).reserver_name
                raise ConflictError(f"Das besorgt schon {by}." if by else "Das besorgt schon jemand anderes.")
        return self._wishes.require(wish_id)

    def unreserve(self, actor: Actor, wish_id: int) -> Wish:
        with self._db.transaction():
            wish = self._wishes.require(wish_id)
            if wish.person_id == actor.id or wish.reserved_by != actor.id:
                raise PermissionDeniedError("Diesen Wunsch hast du nicht reserviert.")
            self._wishes.release(wish_id)
        return wish

    def reservations(self, actor: Actor) -> list[Wish]:
        return self._wishes.reserved_by(actor.id)

    def update(self, actor: Actor, wish_id: int, details: WishDetails) -> Wish:
        with self._db.transaction():
            self._check_editable(self._wishes.require(wish_id), actor)
            self._wishes.update(wish_id, details)
        return self._wishes.require(wish_id)

    def remove(self, actor: Actor, wish_id: int) -> Wish:
        """Soft-Delete: wer den Wunsch reserviert hat, sieht in seinen Reservierungen einen Hinweis
        und bekommt eine Mail. Wer das ist, erfährt die entfernende Person nicht."""
        with self._db.transaction():
            wish = self._wishes.require(wish_id)
            self._check_editable(wish, actor)
            self._wishes.soft_delete(wish_id)
        if wish.reserved_by not in (None, actor.id):
            self._notices.wish_removed(wish, removed_by=actor.name)
        return wish

    @staticmethod
    def _check_editable(wish: Wish, actor: Actor) -> None:
        if wish.is_deleted:
            raise ConflictError("Dieser Wunsch wurde schon entfernt.")
        if not wish.editable_by(actor):
            raise PermissionDeniedError(
                "Diesen Wunsch kannst du nicht ändern – nur die Person selbst oder wer ihn eingetragen hat.")
