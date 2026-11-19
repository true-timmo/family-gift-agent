"""Kleine Bausteine, die mehrere Services teilen."""
from ..domain.errors import RateLimitError
from ..domain.models import Actor, Person, Wish
from ..domain.notifications import Notifier, WishRemoved
from ..storage import InviteRepository, MailLog, PersonRepository
from ..storage.database import DAY, now


class AdminPolicy:
    """Admin ist, wessen Mail-Adresse in ADMIN_EMAIL steht (Groß/klein egal)."""

    def __init__(self, admin_email: str, persons: PersonRepository):
        self._email = admin_email.strip().lower()
        self._persons = persons

    def is_admin(self, person: Person | None) -> bool:
        return bool(self._email and person and person.email and person.email.strip().lower() == self._email)

    def actor(self, person: Person) -> Actor:
        return Actor(person, is_admin=self.is_admin(person))

    def admin(self) -> Person | None:
        return self._persons.by_email(self._email) if self._email else None


class EmailDirectory:
    """Eine Mail-Adresse gehört höchstens einer Person – registriert oder offen eingeladen."""

    def __init__(self, persons: PersonRepository, invites: InviteRepository):
        self._persons = persons
        self._invites = invites

    def owner(self, email: str, except_person_id: int | None = None) -> str | None:
        """Name der Person, die diese Adresse nutzt oder dafür eingeladen ist (Groß/klein egal)."""
        person = self._persons.by_email(email)
        if person and person.id != except_person_id:
            return person.name
        return self._invites.pending_name_for_email(email, except_person_id)

    def taken_by_other(self, email: str, person_id: int | None) -> bool:
        """Nur registrierte Personen – für den Moment, in dem eine Adresse endgültig vergeben wird."""
        person = self._persons.by_email(email)
        return bool(person and person.id != person_id)


def _duration(seconds: int) -> str:
    return f"{seconds} Sekunden" if seconds < 90 else f"{-(-seconds // 60)} Minuten"


class MailRateLimiter:
    """Höchstens 1 Mail pro Minute und 5 pro Stunde je Name (Codes und Einladungen zusammen)."""

    LIMITS = ((60, 1), (3600, 5))   # (Zeitraum in s, max. Mails)

    def __init__(self, log: MailLog):
        self._log = log

    def register_send(self, name: str) -> None:
        at = now()
        if (wait := self.next_allowed(name) - at) > 0:
            raise RateLimitError("Es wurde gerade erst eine Mail verschickt. Bitte ins Postfach schauen "
                                 f"oder noch {_duration(wait)} warten.")
        self._log.record(name, at)
        self._log.prune(at - DAY)

    def next_allowed(self, name: str) -> int:
        """Ab wann wieder eine Mail an diesen Namen gehen darf (Unix-Zeit; liegt sie zurück: sofort)."""
        at, earliest = now(), 0
        for period, limit in self.LIMITS:
            sent = self._log.times_since(name, at - period)
            if len(sent) >= limit:
                earliest = max(earliest, sent[-limit] + period)
        return earliest


class RemovalNotices:
    """Sagt der reservierenden Person Bescheid, wenn ihr Geschenk von der Liste verschwindet."""

    def __init__(self, persons: PersonRepository, notifier: Notifier):
        self._persons = persons
        self._notifier = notifier

    def wish_removed(self, wish: Wish, removed_by: str, bought_by_wisher: bool = False) -> None:
        reserver = self._persons.by_id(wish.reserved_by) if wish.reserved_by else None
        if reserver and reserver.email:
            self._notifier.publish(WishRemoved(recipient_email=reserver.email, recipient_name=reserver.name,
                                               wished_by=wish.person_name, removed_by=removed_by,
                                               title=wish.title, bought_by_wisher=bought_by_wisher))
