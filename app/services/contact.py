"""Familienmitglieder schreiben dem Admin – z.B. um jemanden einladen zu lassen oder ein Problem zu melden."""
from ..domain.errors import ConflictError, DomainError, NotFoundError
from ..domain.models import Actor
from ..domain.notifications import AdminMessage, Notifier
from .directory import AdminPolicy, MailRateLimiter


class AdminContact:
    MAX_LENGTH = 2000

    def __init__(self, admins: AdminPolicy, mail_limit: MailRateLimiter, notifier: Notifier):
        self._admins = admins
        self._mail_limit = mail_limit
        self._notifier = notifier

    def send(self, actor: Actor, text: str) -> str:
        """Schickt die Nachricht per Mail an den Admin und gibt seinen Namen zurück."""
        admin = self._admins.admin()
        if not admin:
            raise NotFoundError("Es ist kein Admin eingerichtet.")
        if admin.id == actor.id:
            raise ConflictError("Du bist selbst der Admin.")
        text = text.strip()
        if not text or len(text) > self.MAX_LENGTH:
            raise DomainError(f"Die Nachricht muss zwischen 1 und {self.MAX_LENGTH} Zeichen lang sein.")
        self._mail_limit.register_send(f"kontakt:{actor.name}")   # gegen versehentliche Mehrfachnachrichten
        self._notifier.publish(AdminMessage(actor.name, actor.person.email, text))
        return admin.name
