"""Regeln für Wünsche und Reservierungen.

Sie stehen hier im Code – nicht im Prompt –, damit das Sprachmodell sie weder vergessen noch umgehen kann.
"""
from dataclasses import replace

from ..domain.matching import matches
from ..domain.errors import ConflictError, DomainError, NotFoundError, PermissionDeniedError
from ..domain.models import Actor, ListedWish, Reservation, Wish, WishDetails, WishList
from ..storage import Database, WishRepository
from .directory import RemovalNotices
from .relations import Guardianship, PersonResolver


class WishService:
    def __init__(self, db: Database, resolver: PersonResolver, wishes: WishRepository, notices: RemovalNotices,
                 guardians: Guardianship):
        self._db = db
        self._resolver = resolver
        self._guardians = guardians
        self._wishes = wishes
        self._notices = notices

    def add(self, actor: Actor, person_name: str, details: WishDetails) -> Wish:
        person = self._resolver.resolve(actor.person, person_name)
        wish_id = self._wishes.add(person.id, replace(details, title=details.title.strip()), created_by=actor.id)
        return self._wishes.require(wish_id)

    def add_tip(self, actor: Actor, person_name: str, details: WishDetails) -> Wish:
        """Geheimtipp: ein Wunsch, den jemand nebenbei erwähnt hat. Die Person selbst erfährt nie davon;
        alle anderen sehen ihn mit dem Hinweis, wer ihn sich gemerkt hat."""
        person = self._resolver.resolve(actor.person, person_name)
        if person.id == actor.id:
            raise DomainError("Eigene Wünsche trägst du ganz normal ein – ein Geheimtipp ist für andere.")
        wish_id = self._wishes.add(person.id, replace(details, title=details.title.strip()), created_by=actor.id,
                                   secret=True)
        return self._wishes.require(wish_id)

    def list_for(self, actor: Actor, person_name: str) -> WishList:
        """Wünsche einer Person – je nachdem, WER fragt:

        - Die Person selbst sieht ihre Wünsche ohne jeden Hinweis auf Reservierungen und ohne Geheimtipps
          (Überraschungsschutz).
        - Andere sehen den Status: offen, von dir reserviert oder besorgt (von jemand anderem).
          Von anderen reservierte Wünsche stehen am Ende.
        """
        person = self._resolver.resolve(actor.person, person_name)
        wishes = self._wishes.active_of(person.id)
        if person.id == actor.id:
            return WishList(person, is_own=True, entries=[ListedWish(w) for w in wishes if not w.hidden_from(actor)])
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
            wish = self._require(actor, wish_id)
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
            wish = self._require(actor, wish_id)
            if wish.person_id == actor.id or wish.reserved_by != actor.id:
                raise PermissionDeniedError("Diesen Wunsch hast du nicht reserviert.")
            self._wishes.release(wish_id)
        return wish

    def reservations(self, actor: Actor) -> list[Wish]:
        return self._wishes.reserved_by(actor.id)

    def update(self, actor: Actor, wish_id: int, details: WishDetails) -> Wish:
        with self._db.transaction():
            self._check_editable(self._require(actor, wish_id), actor)
            self._wishes.update(wish_id, details)
        return self._wishes.require(wish_id)

    def remove(self, actor: Actor, wish_id: int) -> Wish:
        """Soft-Delete: wer den Wunsch reserviert hat, sieht in seinen Reservierungen einen Hinweis
        und bekommt eine Mail. Wer das ist, erfährt die entfernende Person nicht."""
        with self._db.transaction():
            wish = self._require(actor, wish_id)
            self._check_editable(wish, actor)
            self._wishes.soft_delete(wish_id)
        if wish.reserved_by not in (None, actor.id):
            self._notices.wish_removed(wish, removed_by=actor.name)
        return wish

    def bought_myself(self, actor: Actor, description: str, wish_id: int | None = None) -> list[Wish]:
        """Die Person hat sich etwas selbst besorgt.

        - Mit `wish_id`: dieser eigene Wunsch ist erledigt.
        - Passende Geheimtipps für die Person werden still entfernt.
        Wer davon etwas reserviert hatte, bekommt eine Mail. Zurück kommen NUR die sichtbaren eigenen Wünsche –
        ob es Geheimtipps gab, darf die Antwort nicht verraten.
        """
        visible: list[Wish] = []
        with self._db.transaction():
            if wish_id is not None:
                wish = self._require(actor, wish_id)
                if wish.person_id != actor.id:
                    raise PermissionDeniedError("Das ist nicht dein Wunsch.")
                if not wish.is_deleted:
                    visible.append(wish)
            tips = [w for w in self._wishes.active_of(actor.id)
                    if w.hidden_from(actor) and matches(description, w.title, w.details.description)]
            for wish in visible + tips:
                self._wishes.soft_delete(wish.id)
        for wish in visible + tips:
            if wish.reserved_by not in (None, actor.id):
                self._notices.wish_removed(wish, removed_by=actor.name, bought_by_wisher=True)
        return visible

    def _require(self, actor: Actor, wish_id: int) -> Wish:
        """Wunsch per Nummer – ein Geheimtipp für die fragende Person verhält sich, als gäbe es ihn nicht."""
        wish = self._wishes.require(wish_id)
        if wish.hidden_from(actor):
            raise NotFoundError(f"Wunsch Nr. {wish_id} gibt es nicht.")
        return wish

    def _check_editable(self, wish: Wish, actor: Actor) -> None:
        if wish.is_deleted:
            raise ConflictError("Dieser Wunsch wurde schon entfernt.")
        if not (wish.editable_by(actor) or self._guardians.is_guardian(actor.id, wish.person_id)):
            raise PermissionDeniedError(
                "Diesen Wunsch kannst du nicht ändern – nur die Person selbst, wer ihn eingetragen hat "
                "oder bei Kindern ohne eigenen Login die Eltern.")
