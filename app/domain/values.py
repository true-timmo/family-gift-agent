"""Prüfung und Aufbereitung von Eingaben (Namen, Mail-Adressen)."""
import re

from .errors import DomainError

_NAME_RE = re.compile(r"^[^\W\d_](?:[\w .'-]{0,28}[^\W_])?$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def person_name(raw: str) -> str:
    """Name aus Buchstaben (Leerzeichen zusammengefasst), z.B. „Oma Gisela“."""
    name = " ".join(raw.split())
    if not _NAME_RE.match(name):
        raise DomainError("Bitte einen Namen aus Buchstaben angeben, z.B. „Mama“ oder „Oma Gisela“.")
    return name


def email_address(raw: str) -> str:
    email = raw.strip()
    if not _EMAIL_RE.match(email):
        raise DomainError("Bitte eine gültige Mail-Adresse angeben.")
    return email


def masked_email(email: str) -> str:
    """m***@example.de – zeigt, wohin die Mail ging, ohne die Adresse preiszugeben."""
    user, domain = email.split("@", 1)
    return f"{user[0]}***@{domain}"
