"""Anmeldung per Einmal-Code aus der Mail (oder Knopf in derselben Mail) und Sitzungen."""
from dataclasses import dataclass

from ..domain.errors import AuthenticationError, ConflictError, PermissionDeniedError
from ..domain.models import Person
from ..domain.notifications import NewRegistration, Notifier
from ..storage import Database, LoginCodeRepository, PersonRepository, SessionRepository
from ..storage.database import DAY, now
from ..storage.logins import LoginCode
from .directory import EmailDirectory, MailRateLimiter
from .presence import Presence
from .security import hash_code, hash_token, new_code, new_token, same_secret


@dataclass(frozen=True)
class IssuedCode:
    code: str           # zum Abtippen
    link_token: str     # für den Anmelde-Knopf in der Mail
    expires_at: int


class LoginCodeService:
    """6-stelliger Code per Mail: jeder 10 Minuten gültig (auch mehrere gleichzeitig), 5 Fehlversuche.

    Bei einer Registrierung (Familien-Code) entsteht die Person erst, wenn der Code bestätigt ist.
    """

    VALID_MINUTES = 10
    MAX_ATTEMPTS = 5

    def __init__(self, db: Database, persons: PersonRepository, codes: LoginCodeRepository,
                 mail_limit: MailRateLimiter, emails: EmailDirectory, notifier: Notifier, family_code: str = ""):
        self._db = db
        self._family_code = family_code.strip().lower()
        self._persons = persons
        self._codes = codes
        self._mail_limit = mail_limit
        self._emails = emails
        self._notifier = notifier

    def check_registration(self, name: str, email: str, family_code: str) -> str:
        """Prüft eine Selbst-Registrierung per Familien-Code (optionaler Ausweg neben Einladungen).

        Gibt den Namen in gültiger Schreibweise zurück. Ein falscher Familien-Code ist ein AuthenticationError.
        """
        if not self._family_code:
            raise PermissionDeniedError("Neu dabei? Dann bitte jemanden aus der Familie, dich einzuladen.")
        if not same_secret(family_code.strip().lower(), self._family_code):
            raise AuthenticationError("Der Familien-Code stimmt nicht.")
        person = self._persons.by_name(name)
        if person and person.email:
            raise ConflictError("Diesen Namen gibt es schon. Bitte zurück und nur den Namen eingeben.")
        if self._emails.owner(email, person.id if person else None):
            raise ConflictError("Diese E-Mail-Adresse wird schon verwendet.")   # bewusst ohne Namen (öffentlich)
        return person.name if person else name

    def issue(self, name: str, email: str, register: bool) -> IssuedCode:
        """Neuer Code samt Anmelde-Link – mit Versandlimit. Ältere Codes bleiben bis zu ihrem Ablauf gültig."""
        with self._db.transaction():
            self._mail_limit.register_send(name)
            issued = IssuedCode(new_code(), new_token(), now() + self.VALID_MINUTES * 60)
            self._codes.add(name, email, hash_code(name, issued.code), hash_token(issued.link_token),
                            issued.expires_at, register)
        return issued

    def valid_until(self, name: str, email: str) -> int | None:
        """Ablaufzeit des neuesten noch benutzbaren Anmelde-Codes an diese Adresse – None, wenn es keinen gibt."""
        return next((p.expires_at for p in self._codes.usable(name, self.MAX_ATTEMPTS)
                     if not p.register and p.email.lower() == email.lower()), None)

    def resend_allowed_at(self, name: str) -> int:
        """Ab wann „Neuen Code schicken“ wieder geht (Versandlimit)."""
        return self._mail_limit.next_allowed(name)

    def link_owner(self, link_token: str) -> str | None:
        """Für wen der Anmelde-Link gilt – meldet aber noch NICHT an (Mail-Programme öffnen Links teils selbst)."""
        pending = self._usable_link(link_token)
        return pending.name if pending else None

    def verify_link(self, link_token: str) -> Person:
        """Anmeldung per Knopf aus der Mail: gleichwertig zum Code, ebenfalls nur einmal benutzbar."""
        with self._db.transaction():
            pending = self._usable_link(link_token)
            if not pending:
                raise AuthenticationError("Dieser Anmelde-Link ist abgelaufen oder wurde schon benutzt. "
                                          "Bitte melde dich neu an.")
            self._codes.delete(pending.name)
            registered = self._complete_registration(pending)
        if registered:
            self._notifier.publish(NewRegistration(pending.name))
        return self._persons.by_name(pending.name)

    def _usable_link(self, link_token: str) -> LoginCode | None:
        pending = self._codes.by_link(hash_token(link_token)) if link_token else None
        if pending and pending.expires_at > now() and pending.attempts < self.MAX_ATTEMPTS:
            return pending
        return None

    def verify(self, name: str, code: str) -> Person:
        """Gibt die (ggf. neu angelegte) Person zurück oder wirft einen Fehler."""
        attempts_left = None
        registered = False
        with self._db.transaction():
            usable = self._codes.usable(name, self.MAX_ATTEMPTS)
            if not usable:
                raise AuthenticationError("Der Code ist abgelaufen. Bitte einen neuen anfordern.")
            entered = hash_code(name, code.strip())
            pending = next((p for p in usable if same_secret(p.code_hash, entered)), None)
            if pending:
                self._codes.delete(name)    # angemeldet → alle Codes des Namens erledigt
                registered = self._complete_registration(pending)
            else:
                # Fehlversuch zählen und committen – erst danach den Fehler melden
                self._codes.count_failure(name)
                attempts_left = max(self.MAX_ATTEMPTS - p.attempts - 1 for p in usable)
        if attempts_left is not None:
            raise AuthenticationError(f"Der Code stimmt nicht. Noch {attempts_left} Versuch(e)." if attempts_left
                                      else "Der Code stimmt nicht. Bitte einen neuen anfordern.")
        if registered:
            self._notifier.publish(NewRegistration(pending.name))
        return self._persons.by_name(pending.name)

    def _complete_registration(self, pending: LoginCode) -> bool:
        """Legt nach einer Registrierung die Person an bzw. hinterlegt ihre Mail-Adresse."""
        if not pending.register:
            return False
        person = self._persons.by_name(pending.name)
        if person and person.email:
            raise ConflictError("Diesen Namen hat inzwischen jemand anderes registriert.")
        if self._emails.taken_by_other(pending.email, person.id if person else None):
            raise ConflictError("Diese E-Mail-Adresse wird schon verwendet.")
        if person:   # existierte schon ohne Login (z.B. Oma, von anderen eingetragen) → Mail ergänzen
            self._persons.set_email(person.id, pending.email)
        else:
            self._persons.add(pending.name, pending.email)   # Schreibweise aus der Registrierung
        return True


class SessionService:
    VALID_DAYS = 90

    def __init__(self, sessions: SessionRepository, presence: Presence):
        self._sessions = sessions
        self._presence = presence

    def start(self, person: Person) -> str:
        self._presence.seen(person)
        token = new_token()
        self._sessions.add(hash_token(token), person.id, now() + self.VALID_DAYS * DAY)
        return token

    def person(self, token: str | None) -> Person | None:
        person = self._sessions.person(hash_token(token)) if token else None
        if person:
            self._presence.seen(person)
        return person

    def end(self, token: str) -> None:
        self._sessions.delete(hash_token(token))

    def end_all(self, person: Person) -> int:
        """Meldet die Person auf allen Geräten ab."""
        return self._sessions.delete_all_for(person.id)
