"""Die Mails der Anwendung. Texte stehen in templates/ – je Mail eine .txt- und eine .html-Fassung."""
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

from jinja2 import Environment, PackageLoader, StrictUndefined, select_autoescape

from ..domain.models import IssuedInvite
from ..domain.notifications import NewRegistration, Notification, WishRemoved
from .transport import MailTransport


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
        return f"{self._app_url}/?einladung={token}"

    async def send_login_code(self, to: str, name: str, code: str, minutes: int) -> None:
        await self._send(to, f"{code} ist dein Anmeldecode für Geschenke", "login_code",
                         name=name, code=code, minutes=minutes)

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

    async def _send_wish_removed(self, n: WishRemoved) -> None:
        where = ("von der eigenen Wunschliste" if n.wished_by == n.removed_by
                 else f"von der Wunschliste für {n.wished_by}")
        await self._send(n.recipient_email, f"„{n.title}“ wurde von der Wunschliste genommen", "wish_removed",
                         recipient_name=n.recipient_name, removed_by=n.removed_by, title=n.title, where=where)

    async def _send_new_registration(self, n: NewRegistration) -> None:
        if not self._admin_email:
            return
        how = f"eingeladen von {n.invited_by}" if n.invited_by else "mit dem Familien-Code"
        await self._send(self._admin_email, f"Neu dabei: {n.name}", "new_registration", name=n.name, how=how)

    async def _send(self, to: str, subject: str, template: str, **context) -> None:
        context["app_url"] = self._app_url
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = formataddr(("Geschenke", self._sender))
        message["To"] = to
        message["Message-ID"] = make_msgid(domain=self._sender.split("@")[-1] or None)
        message.set_content(self._render(f"{template}.txt", context))
        message.add_alternative(self._render(f"{template}.html", context), subtype="html")
        await self._transport.deliver(message)

    def _render(self, name: str, context: dict) -> str:
        return self._templates.get_template(name).render(context)
