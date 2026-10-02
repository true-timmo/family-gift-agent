"""Persönliche KI-Zugänge: mit einem API-Schlüssel binden Familienmitglieder die Wunschliste als MCP-Server
in ihren eigenen KI-Assistenten ein (Claude, ChatGPT …). Der Schlüssel handelt im Namen seiner Besitzerin –
mit genau ihren Rechten, Überraschungsschutz inklusive.
"""
from dataclasses import dataclass

from ..domain.errors import PermissionDeniedError, RateLimitError
from ..domain.models import Actor, Person
from ..domain.notifications import ApiKeyIssued, Notifier
from ..domain.values import masked_email
from ..storage import ApiKeyRepository
from ..storage.database import DAY, now
from .directory import MailRateLimiter
from .security import hash_token, new_token

KEY_PREFIX = "gsk_"


@dataclass(frozen=True)
class KeySent:
    email: str          # maskiert
    expires_at: int


class ApiKeyService:
    MAX_VALID = 5       # je Person, z.B. für mehrere Geräte/Programme

    def __init__(self, keys: ApiKeyRepository, mail_limit: MailRateLimiter, notifier: Notifier, valid_days: int):
        self._keys = keys
        self._mail_limit = mail_limit
        self._notifier = notifier
        self._valid_days = valid_days

    def issue(self, actor: Actor) -> KeySent:
        """Erzeugt einen Schlüssel und schickt ihn per Mail – zurück kommt nur, wohin und wie lange gültig."""
        person = actor.person
        if not person.email:
            raise PermissionDeniedError("Einen KI-Zugang gibt es nur mit eigener E-Mail-Adresse.")
        if self._keys.count_valid(person.id) >= self.MAX_VALID:
            raise RateLimitError(f"Du hast schon {self.MAX_VALID} gültige Zugänge. Sperre sie zuerst "
                                 "(„Sperre meine KI-Zugänge“) und fordere dann einen neuen an.")
        self._mail_limit.register_send(f"ki:{person.name}")
        key = KEY_PREFIX + new_token()
        expires_at = now() + self._valid_days * DAY
        self._keys.add(hash_token(key), person.id, expires_at)
        self._notifier.publish(ApiKeyIssued(person.email, person.name, key, expires_at))
        return KeySent(masked_email(person.email), expires_at)

    def person(self, key: str | None) -> Person | None:
        if not key or not key.startswith(KEY_PREFIX):
            return None
        token_hash = hash_token(key)
        if person := self._keys.person(token_hash):
            self._keys.touch(token_hash)
        return person

    def revoke_all(self, person: Person) -> int:
        return self._keys.revoke_all(person.id)
