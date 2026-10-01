"""Anmeldung per Einmal-Code aus der Mail und Sitzungen."""
from ..domain.errors import AuthenticationError, ConflictError, PermissionDeniedError
from ..domain.models import Person
from ..domain.notifications import NewRegistration, Notifier
from ..storage import Database, LoginCodeRepository, PersonRepository, SessionRepository
from ..storage.database import DAY, now
from ..storage.logins import LoginCode
from .directory import EmailDirectory, MailRateLimiter
from .security import hash_code, hash_token, new_code, new_token, same_secret


class LoginCodeService:
    """6-stelliger Code per Mail: 10 Minuten gültig, 5 Versuche.

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

    def issue(self, name: str, email: str, register: bool) -> str:
        """Neuer Code (ersetzt einen älteren) – mit Versandlimit."""
        with self._db.transaction():
            self._mail_limit.register_send(name)
            code = new_code()
            self._codes.replace(name, email, hash_code(name, code), now() + self.VALID_MINUTES * 60, register)
        return code

    def verify(self, name: str, code: str) -> Person:
        """Gibt die (ggf. neu angelegte) Person zurück oder wirft einen Fehler."""
        attempts_left = None
        registered = False
        with self._db.transaction():
            pending = self._codes.get(name)
            if not pending or pending.expires_at < now() or pending.attempts >= self.MAX_ATTEMPTS:
                raise AuthenticationError("Der Code ist abgelaufen. Bitte einen neuen anfordern.")
            if same_secret(pending.code_hash, hash_code(name, code.strip())):
                self._codes.delete(name)
                registered = self._complete_registration(pending)
            else:
                # Fehlversuch zählen und committen – erst danach den Fehler melden
                self._codes.count_failure(name)
                attempts_left = self.MAX_ATTEMPTS - pending.attempts - 1
        if attempts_left is not None:
            raise AuthenticationError(f"Der Code stimmt nicht. Noch {attempts_left} Versuch(e)." if attempts_left
                                      else "Der Code stimmt nicht. Bitte einen neuen anfordern.")
        if registered:
            self._notifier.publish(NewRegistration(pending.name))
        return self._persons.by_name(name)

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

    def __init__(self, sessions: SessionRepository):
        self._sessions = sessions

    def start(self, person: Person) -> str:
        token = new_token()
        self._sessions.add(hash_token(token), person.id, now() + self.VALID_DAYS * DAY)
        return token

    def person(self, token: str | None) -> Person | None:
        return self._sessions.person(hash_token(token)) if token else None

    def end(self, token: str) -> None:
        self._sessions.delete(hash_token(token))

    def end_all(self, person: Person) -> int:
        """Meldet die Person auf allen Geräten ab."""
        return self._sessions.delete_all_for(person.id)
