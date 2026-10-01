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

    def invite(self, inviter: Person, name: str, email: str, existing: bool = False) -> IssuedInvite:
        """Lädt `name` mit `email` ein.

        - existing=False („Jemanden einladen“): nur für NEUE Namen – ein vorhandener Name ist ein Fehler.
        - existing=True („Einladen“/„Erneut“ in der Liste): für vorhandene, noch nicht registrierte Personen.
          Eine offene Einladung wird dabei ersetzt – so lässt sich eine falsch getippte Adresse korrigieren.
        """
        with self._db.transaction():
            person = self._persons.by_name(name)
            self._check_invitable(person, name, existing)
            if owner := self._emails.owner(email, person.id if person else None):
                raise ConflictError(f"Diese E-Mail-Adresse gehört schon zu {owner}.")
            if self._invites.count_sent_by(inviter.id, now() - DAY) >= self.MAX_PER_DAY:
                raise RateLimitError("Heute wurden schon sehr viele Einladungen verschickt. Bitte morgen wieder.")
            if not person:
                person = Person(self._persons.add(name), name.strip())
            self._mail_limit.register_send(person.name)
            self._invites.delete_open_for(person.id)
            return self._issue(person, email, inviter)

    def _check_invitable(self, person: Person | None, name: str, existing: bool) -> None:
        if person and person.email:
            raise ConflictError(f"{person.name} ist schon registriert und kann sich direkt mit dem Namen anmelden.")
        if person and not existing:
            hint = ("ist schon eingeladen. Zum erneuten Einladen in der Liste auf „Erneut“ tippen."
                    if self._invites.pending_for(person.name) else
                    "gibt es schon. Zum Einladen in der Liste auf „Einladen“ tippen – "
                    "oder einen anderen Namen wählen, falls es jemand anderes ist.")
            raise ConflictError(f"{person.name} {hint}")
        if existing and not person:
            raise NotFoundError(f"{name} gibt es nicht.")

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
