"""Personen der Familienliste verwalten."""
from ..domain.errors import ConflictError, PermissionDeniedError
from ..domain.models import FamilyMember, Person, PersonRemoval
from ..storage import (ApiKeyRepository, ChatRepository, WhatsAppChatRepository, Database, InviteRepository, LoginCodeRepository, MailLog, PersonRepository,
                       RelationRepository, SessionRepository, WishRepository)
from .directory import EmailDirectory, RemovalNotices


class FamilyService:
    def __init__(self, persons: PersonRepository, emails: EmailDirectory):
        self._persons = persons
        self._emails = emails

    def members(self) -> list[FamilyMember]:
        return self._persons.members()

    def persons(self) -> list[Person]:
        return self._persons.all()

    def get(self, name: str) -> Person | None:
        return self._persons.by_name(name)

    def by_id(self, person_id: int) -> Person | None:
        return self._persons.by_id(person_id)

    def require(self, name: str) -> Person:
        return self._persons.require(name)

    def add(self, name: str, email: str | None = None) -> Person:
        return self._persons.by_id(self._persons.add(name, email))

    def add_without_login(self, name: str) -> Person:
        """Person ohne eigenen Login, z.B. Kinder ohne Mail-Adresse – andere tragen ihre Wünsche ein.

        Später lässt sie sich in der Familienliste einladen und übernimmt dann ihre Liste.
        """
        if existing := self._persons.by_name(name):
            raise ConflictError(f"{existing.name} gibt es schon in der Familienliste.")
        return self.add(name)

    def set_email(self, name: str, email: str | None) -> None:
        """Mail-Adresse ändern; None entfernt sie (dann ist kein Login mehr möglich)."""
        person = self._persons.require(name)
        if email and (owner := self._emails.owner(email, person.id)):
            raise ConflictError(f"Diese E-Mail-Adresse gehört schon zu {owner}.")
        self._persons.set_email(person.id, email)


class PersonRemovalService:
    """Löscht eine Person endgültig – nur der Admin (das prüft der Aufrufer).

    - Ihre Wünsche werden gelöscht; wer davon etwas reserviert hatte, wird benachrichtigt.
    - Ihre eigenen Reservierungen werden freigegeben (Geschenke sind wieder offen).
    - Wünsche und Einladungen, die sie für andere angelegt hat, bleiben – sie gelten dann als vom Admin.
    - Sitzungen, KI-Zugänge, WhatsApp-Verknüpfung, Chatverlauf, Codes und Verwandtschaftsangaben verschwinden.
    """

    def __init__(self, db: Database, persons: PersonRepository, wishes: WishRepository, invites: InviteRepository,
                 codes: LoginCodeRepository, mail_log: MailLog, sessions: SessionRepository, chat: ChatRepository,
                 relations: RelationRepository, api_keys: ApiKeyRepository, whatsapp: WhatsAppChatRepository,
                 notices: RemovalNotices):
        self._db = db
        self._persons = persons
        self._wishes = wishes
        self._invites = invites
        self._codes = codes
        self._mail_log = mail_log
        self._sessions = sessions
        self._chat = chat
        self._relations = relations
        self._api_keys = api_keys
        self._whatsapp = whatsapp
        self._notices = notices

    def remove(self, admin: Person, name: str) -> PersonRemoval:
        with self._db.transaction():
            person = self._persons.require(name)
            if person.id == admin.id:
                raise PermissionDeniedError("Du kannst dich nicht selbst entfernen.")
            wishes = self._wishes.active_of(person.id)
            released = self._wishes.release_all_reserved_by(person.id)
            self._delete_traces(person, successor=admin)
        for wish in wishes:
            if wish.reserved_by not in (None, person.id):
                self._notices.wish_removed(wish, removed_by=admin.name)
        return PersonRemoval(person.name, wishes_deleted=len(wishes), reservations_released=released)

    def _delete_traces(self, person: Person, successor: Person) -> None:
        self._wishes.delete_all_of(person.id)
        self._wishes.transfer_created_by(person.id, successor.id)
        self._invites.delete_all_for(person.id)
        self._invites.transfer_inviter(person.id, successor.id)
        self._sessions.delete_all_for(person.id)
        self._chat.clear(person.id)
        self._codes.delete(person.name)
        self._mail_log.delete_for(person.name)
        self._relations.delete_all_for(person.id)
        self._api_keys.delete_all_for(person.id)
        self._whatsapp.delete_all_for(person.id)
        self._persons.delete(person.id)
