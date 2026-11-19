"""Die Mails der Anwendung. Texte stehen in templates/ – je Mail eine .txt- und eine .html-Fassung."""
from datetime import datetime
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

from jinja2 import Environment, PackageLoader, StrictUndefined, select_autoescape

from ..domain.models import IssuedInvite
from ..domain.notifications import (AdminMessage, ApiKeyExpiring, ApiKeyIssued, ComeBackReminder, NewRegistration,
                                    Notification, WishRemoved)
from .transport import MailTransport


def _date(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp).strftime("%d.%m.%Y")


class Mailer:
    def __init__(self, transport: MailTransport, sender: str, app_url: str, admin_email: str = ""):
        self._transport = transport
        self._sender = sender
        self._app_url = app_url
        self._admin_email = admin_email
        self._templates = Environment(loader=PackageLoader("app.mail", "templates"),
                                      autoescape=select_autoescape(["html"]), undefined=StrictUndefined,
                                      trim_blocks=True, lstrip_blocks=True)

    def invite_link(self, token: str) -> str:
        return f"{self._app_url}/#einladung={token}"   # hinter „#“: landet nie in Server-Logs

    def login_link(self, token: str) -> str:
        return f"{self._app_url}/#anmelden={token}"

    async def send_login_code(self, to: str, name: str, code: str, minutes: int, link_token: str) -> None:
        await self._send(to, f"{code} ist dein Anmeldecode für Geschenke", "login_code",
                         name=name, code=code, minutes=minutes, link=self.login_link(link_token))

    async def send_invite(self, invite: IssuedInvite, valid_days: int) -> None:
        """Einladung mit Link – bewusst einfach formuliert."""
        await self._send(invite.email, f"{invite.inviter} lädt dich zur Geschenke-Liste ein", "invite",
                         name=invite.name, inviter=invite.inviter, link=self.invite_link(invite.token),
                         days=valid_days)

    async def send_notification(self, notification: Notification) -> None:
        match notification:
            case WishRemoved():
                await self._send_wish_removed(notification)
            case NewRegistration():
                await self._send_new_registration(notification)
            case AdminMessage():
                await self._send_admin_message(notification)
            case ApiKeyIssued():
                await self._send_api_key(notification)
            case ApiKeyExpiring():
                await self._send(notification.recipient_email, "Dein KI-Zugang zur Geschenke-Liste läuft bald ab",
                                 "api_key_expiring", name=notification.recipient_name,
                                 valid_until=_date(notification.expires_at))
            case ComeBackReminder():
                await self._send_come_back(notification)

    async def _send_wish_removed(self, n: WishRemoved) -> None:
        where = ("von der eigenen Wunschliste" if n.wished_by == n.removed_by
                 else f"von der Wunschliste für {n.wished_by}")
        subject = (f"„{n.title}“ hat sich erledigt" if n.bought_by_wisher
                   else f"„{n.title}“ wurde von der Wunschliste genommen")
        await self._send(n.recipient_email, subject, "wish_removed", recipient_name=n.recipient_name,
                         removed_by=n.removed_by, wished_by=n.wished_by, title=n.title, where=where,
                         bought_by_wisher=n.bought_by_wisher)

    async def _send_new_registration(self, n: NewRegistration) -> None:
        if not self._admin_email:
            return
        how = f"eingeladen von {n.invited_by}" if n.invited_by else "mit dem Familien-Code"
        await self._send(self._admin_email, f"Neu dabei: {n.name}", "new_registration", name=n.name, how=how)

    async def _send_admin_message(self, n: AdminMessage) -> None:
        if self._admin_email:
            await self._send(self._admin_email, f"Nachricht von {n.sender}", "admin_message", reply_to=n.sender_email,
                             sender=n.sender, text=n.text)

    async def _send_come_back(self, n: ComeBackReminder) -> None:
        total = sum(count for _, count in n.new_wishes)
        what = "1 neuer Wunsch" if total == 1 else f"{total} neue Wünsche"
        subject = f"{what} auf der Geschenke-Liste" if total else "Schau mal wieder auf die Geschenke-Liste"
        await self._send(n.recipient_email, subject, "come_back", name=n.recipient_name, new_wishes=n.new_wishes,
                         total=total)

    async def _send_api_key(self, n: ApiKeyIssued) -> None:
        endpoint = f"{self._app_url}/mcp"
        await self._send(n.recipient_email, "Dein KI-Zugang zur Geschenke-Liste", "api_key", name=n.recipient_name,
                         key=n.key, endpoint=endpoint, secret_url=f"{endpoint}/{n.key}",
                         valid_until=_date(n.expires_at))

    async def _send(self, to: str, subject: str, template: str, reply_to: str | None = None, **context) -> None:
        context |= {"app_url": self._app_url, "reply_to": reply_to}
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = formataddr(("Geschenke", self._sender))
        message["To"] = to
        if reply_to:
            message["Reply-To"] = reply_to
        message["Message-ID"] = make_msgid(domain=self._sender.split("@")[-1] or None)
        message.set_content(self._render(f"{template}.txt", context))
        message.add_alternative(self._render(f"{template}.html", context), subtype="html")
        await self._transport.deliver(message)

    def _render(self, name: str, context: dict) -> str:
        return self._templates.get_template(name).render(context)
