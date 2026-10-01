"""Mailversand: Vorlagen (Jinja2), Zustellung (SMTP oder Log) und Hintergrund-Benachrichtigungen."""
from .mailer import Mailer
from .notifier import BackgroundMailNotifier
from .transport import ConsoleTransport, MailTransport, SmtpTransport

__all__ = ["BackgroundMailNotifier", "ConsoleTransport", "Mailer", "MailTransport", "SmtpTransport"]
