"""Wie eine fertige Mail das Haus verlässt."""
import asyncio
import smtplib
from email.message import EmailMessage
from typing import Protocol

from ..config import SmtpSettings


class MailTransport(Protocol):
    async def deliver(self, message: EmailMessage) -> None: ...


class SmtpTransport:
    """SMTP mit STARTTLS (Standard: Microsoft 365)."""

    def __init__(self, settings: SmtpSettings):
        self._settings = settings

    async def deliver(self, message: EmailMessage) -> None:
        if not self._settings.configured:
            raise RuntimeError("SMTP ist nicht konfiguriert (SMTP_USER/SMTP_PASSWORD in .env)")
        # smtplib blockiert – im Thread ausführen, damit der Server weiter antwortet
        await asyncio.to_thread(self._send, message)

    def _send(self, message: EmailMessage) -> None:
        s = self._settings
        with smtplib.SMTP(s.host, s.port, timeout=30) as smtp:
            smtp.starttls()
            smtp.login(s.user, s.password)
            smtp.send_message(message)


class ConsoleTransport:
    """Nur für lokale Tests (MAIL_DEBUG=1): Mail ins Log statt verschicken."""

    async def deliver(self, message: EmailMessage) -> None:
        text = message.get_body(("plain",)).get_content()
        print(f"[MAIL_DEBUG] An {message['To']}: {message['Subject']}\n{text}", flush=True)
