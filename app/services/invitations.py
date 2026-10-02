"""Einladungen per Mail – der empfohlene Weg in die Familienliste.

Name und Adresse legt der Einladende fest. Der Klick auf den Link beweist die Adresse,
deshalb braucht das Annehmen keinen Code.
"""
from ..domain.errors import ConflictError, NotFoundError, RateLimitError
from ..domain.models import Invite, IssuedInvite, Person
from ..domain.notifications import NewRegistration, Notifier
from ..storage import Database, InviteRepository, PersonRepository
from ..storage.database import DAY, now
from .directory import EmailDirectory, MailRateLimiter
from .security import hash_token, new_token


class InvitationService:
    VALID_DAYS = 7
    MAX_PER_DAY = 20      # je einladender Person

    def __init__(self, db: Database, persons: PersonRepository, invites: InviteRepository,
                 mail_limit: MailRateLimiter, emails: EmailDirectory, notifier: Notifier):
        self._db = db
        self._persons = persons
        self._invites = invites
        self._mail_limit = mail_limit
        self._emails = emails
        self._notifier = notifier

    def invite(self, inviter: Person, name: str, email: str) -> IssuedInvite:
        """Lädt `name` mit `email` ein (nur der Admin – das prüft der Aufrufer).

        Gibt es die Person schon ohne Login (z.B. ein Kind, für das andere Wünsche eintragen), wird genau sie
        eingeladen und übernimmt später ihre Liste. Eine offene Einladung wird ersetzt – so lässt sich eine
        falsch getippte Adresse korrigieren.
        """
        with self._db.transaction():
            person = self._persons.by_name(name)
            if person and person.email:
                raise ConflictError(f"{person.name} ist schon registriert und kann sich direkt mit dem Namen anmelden.")
            if owner := self._emails.owner(email, person.id if person else None):
                raise ConflictError(f"Diese E-Mail-Adresse gehört schon zu {owner}.")
            if self._invites.count_sent_by(inviter.id, now() - DAY) >= self.MAX_PER_DAY:
                raise RateLimitError("Heute wurden schon sehr viele Einladungen verschickt. Bitte morgen wieder.")
            if not person:
                person = Person(self._persons.add(name), name.strip())
            self._mail_limit.register_send(person.name)
            self._invites.delete_open_for(person.id)
            return self._issue(person, email, inviter)

    def resend(self, name: str) -> IssuedInvite | None:
        """Neuer Link für eine offene Einladung (z.B. Mail gelöscht). None, wenn es keine gibt."""
        pending = self._invites.pending_for(name)
        if not pending:
            return None
        with self._db.transaction():
            self._mail_limit.register_send(pending.name)
            self._invites.delete(pending.token_hash)
            return self._issue(Person(pending.person_id, pending.name), pending.email,
                               Person(pending.invited_by, pending.inviter))

    def _issue(self, person: Person, email: str, inviter: Person) -> IssuedInvite:
        token = new_token(18)
        self._invites.add(hash_token(token), person.id, email, inviter.id, now() + self.VALID_DAYS * DAY)
        return IssuedInvite(token=token, name=person.name, email=email, inviter=inviter.name)

    def lookup(self, token: str) -> Invite | None:
        """Gültige Einladung zum Link oder None."""
        return self._invites.valid(hash_token(token or ""))

    def pending_for(self, name: str) -> Invite | None:
        return self._invites.pending_for(name)

    def accept(self, token: str) -> Person:
        """Hinterlegt die Mail-Adresse aus der Einladung und gibt die Person zurück."""
        with self._db.transaction():
            invite = self.lookup(token)
            if not invite:
                raise NotFoundError("Diese Einladung ist abgelaufen oder wurde schon benutzt. Bitte um eine neue.")
            person = self._persons.by_id(invite.person_id)
            if person.email:
                raise ConflictError(f"{person.name} ist schon registriert. Bitte einfach mit dem Namen anmelden.")
            if self._emails.taken_by_other(invite.email, invite.person_id):
                raise ConflictError("Diese E-Mail-Adresse wird inzwischen von jemand anderem genutzt. "
                                    "Bitte um eine neue Einladung.")
            self._persons.set_email(invite.person_id, invite.email)
            self._invites.mark_used(invite.token_hash)
        self._notifier.publish(NewRegistration(invite.name, invited_by=invite.inviter))
        return self._persons.by_id(invite.person_id)
