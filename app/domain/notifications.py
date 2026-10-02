"""Benachrichtigungen, die Fachlogik auslöst – wie sie zugestellt werden, entscheidet ein Notifier."""
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class WishRemoved:
    """Ein reservierter Wunsch wurde entfernt – die reservierende Person soll es erfahren."""
    recipient_email: str
    recipient_name: str
    wished_by: str
    removed_by: str
    title: str


@dataclass(frozen=True)
class NewRegistration:
    """Jemand ist neu dabei – Info an den Admin."""
    name: str
    invited_by: str | None = None    # None = per Familien-Code registriert


@dataclass(frozen=True)
class AdminMessage:
    """Nachricht eines Familienmitglieds an den Admin (aus dem Chat)."""
    sender: str
    sender_email: str | None     # für „Antworten“ in der Mail; None = Person ohne eigene Adresse
    text: str


Notification = WishRemoved | NewRegistration | AdminMessage


class Notifier(Protocol):
    def publish(self, notification: Notification) -> None:
        """Nimmt eine Benachrichtigung an. Darf nicht blockieren und keine Fehler werfen."""


class NullNotifier:
    """Verwirft alles – z.B. für die Kommandozeile."""

    def publish(self, notification: Notification) -> None:
        pass
