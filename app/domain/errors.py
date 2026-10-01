"""Fehler, deren Text Nutzer sehen dürfen – in der Oberfläche oder (über das Modell) im Chat.

Die Unterklassen sagen, WAS schiefging; die Web-Schicht macht daraus den passenden HTTP-Status.
"""


class DomainError(Exception):
    """Regel verletzt oder Eingabe ungültig."""


class NotFoundError(DomainError):
    """Person, Wunsch oder Einladung gibt es nicht (mehr)."""


class ConflictError(DomainError):
    """Widerspricht dem aktuellen Stand, z.B. Name oder Mail-Adresse schon vergeben."""


class PermissionDeniedError(DomainError):
    """Die angemeldete Person darf das nicht."""


class AuthenticationError(DomainError):
    """Anmeldung fehlgeschlagen, z.B. falscher oder abgelaufener Code."""


class RateLimitError(DomainError):
    """Zu viele Versuche oder Mails in kurzer Zeit."""
