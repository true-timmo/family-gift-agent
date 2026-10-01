"""Unveränderliche Datenobjekte, wie sie aus der Datenbank kommen."""
from dataclasses import dataclass, fields
from enum import StrEnum


@dataclass(frozen=True)
class Person:
    id: int
    name: str
    email: str | None = None      # None = kein eigener Login (z.B. Kinder, Oma ohne Handy)
    gender: str | None = None     # "w" / "m" – für Bezeichnungen wie Mutter/Vater; None = unbekannt

    @property
    def is_registered(self) -> bool:
        return bool(self.email)


@dataclass(frozen=True)
class Actor:
    """Die angemeldete Person, in deren Namen gehandelt wird – kommt immer vom Server, nie aus dem Chat."""
    person: Person
    is_admin: bool = False

    @property
    def id(self) -> int:
        return self.person.id

    @property
    def name(self) -> str:
        return self.person.name


class MemberStatus(StrEnum):
    REGISTERED = "registriert"     # kann sich selbst anmelden
    INVITED = "eingeladen"         # hat eine offene Einladung per Mail
    OPEN = "offen"                 # noch nicht dabei


@dataclass(frozen=True)
class FamilyMember:
    id: int
    name: str
    status: MemberStatus


@dataclass(frozen=True)
class WishDetails:
    """Angaben zu einem Wunsch. None = nicht angegeben bzw. beim Bearbeiten: unverändert lassen."""
    title: str | None = None
    description: str | None = None
    shop: str | None = None
    url: str | None = None
    price: str | None = None

    def given(self) -> dict[str, str]:
        """Nur die angegebenen Felder, als {Spaltenname: Wert}."""
        return {f.name: v for f in fields(self) if (v := getattr(self, f.name)) is not None}


@dataclass(frozen=True)
class Wish:
    id: int
    person_id: int                  # wer sich das wünscht
    created_by: int
    details: WishDetails
    reserved_by: int | None = None  # wer es besorgt
    deleted_at: int | None = None   # vom Wünschenden entfernt
    person_name: str | None = None  # aus Abfragen mit Join
    reserver_name: str | None = None

    @property
    def title(self) -> str:
        return self.details.title or ""

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    def editable_by(self, actor: Actor) -> bool:
        return actor.is_admin or actor.id in (self.person_id, self.created_by)


class Reservation(StrEnum):
    """Status eines Wunsches aus Sicht einer ANDEREN Person als der Wünschenden."""
    OPEN = "offen"
    MINE = "von dir reserviert"
    TAKEN = "besorgt"              # von jemand anderem


@dataclass(frozen=True)
class ListedWish:
    wish: Wish
    reservation: Reservation | None = None   # None auf der eigenen Liste (Überraschungsschutz)


@dataclass(frozen=True)
class WishList:
    person: Person
    is_own: bool
    entries: list[ListedWish]


@dataclass(frozen=True)
class Invite:
    token_hash: str
    person_id: int
    name: str
    email: str
    invited_by: int
    inviter: str


@dataclass(frozen=True)
class IssuedInvite:
    """Frisch erzeugte Einladung: der Token steht nur im Link der Mail, gespeichert wird sein Hash."""
    token: str
    name: str
    email: str
    inviter: str


@dataclass(frozen=True)
class PersonRemoval:
    name: str
    wishes_deleted: int
    reservations_released: int
