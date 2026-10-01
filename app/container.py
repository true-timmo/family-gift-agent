"""Setzt die Anwendung zusammen (Composition Root): hier – und nur hier – entsteht jedes Objekt.

Alle anderen Klassen bekommen ihre Abhängigkeiten übergeben; Tests tauschen so z.B. Datenbank,
Mailversand oder Benachrichtigungen aus.
"""
import logging

from openai import AsyncOpenAI

from .agent import ChatAgent, SystemPrompt, ToolRegistry
from .config import Settings
from .domain.notifications import Notifier
from .mail import BackgroundMailNotifier, ConsoleTransport, Mailer, MailTransport, SmtpTransport
from .services import (AdminPolicy, EmailDirectory, FamilyService, InvitationService, LoginCodeService,
                       MailRateLimiter, Guardianship, PersonRemovalService, PersonResolver, RelationService, RemovalNotices,
                       SessionService, WishService)
from .storage import (ChatRepository, Database, InviteRepository, LoginCodeRepository, MailLog, PersonRepository,
                      RelationRepository, SessionRepository, WishRepository)

log = logging.getLogger("uvicorn.error")


class Container:
    def __init__(self, settings: Settings, *, database: Database | None = None, notifier: Notifier | None = None,
                 mail_transport: MailTransport | None = None, llm_client: AsyncOpenAI | None = None):
        self.settings = settings
        db = self.database = database or Database(settings.db_path)

        persons = PersonRepository(db)
        wishes = WishRepository(db)
        invites = InviteRepository(db)
        codes = LoginCodeRepository(db)
        mail_log = MailLog(db)
        sessions = SessionRepository(db)
        relations = RelationRepository(db)
        self.chat_history = ChatRepository(db)

        transport = mail_transport or (ConsoleTransport() if settings.smtp.debug else SmtpTransport(settings.smtp))
        self.mailer = Mailer(transport, settings.smtp.sender, settings.app_url, settings.admin_email)
        self.notifier = notifier or BackgroundMailNotifier(self.mailer, log)

        emails = EmailDirectory(persons, invites)
        mail_limit = MailRateLimiter(mail_log)
        notices = RemovalNotices(persons, self.notifier)
        self.admins = AdminPolicy(settings.admin_email, persons)
        self.family = FamilyService(persons, emails)
        resolver = PersonResolver(persons, relations)
        self.relations = RelationService(db, persons, relations, resolver)
        self.wishes = WishService(db, resolver, wishes, notices, Guardianship(persons, relations))
        self.login_codes = LoginCodeService(db, persons, codes, mail_limit, emails, self.notifier,
                                            settings.family_code)
        self.sessions = SessionService(sessions)
        self.invitations = InvitationService(db, persons, invites, mail_limit, emails, self.notifier)
        self.removals = PersonRemovalService(db, persons, wishes, invites, codes, mail_log, sessions,
                                             self.chat_history, relations, notices)

        self.tools = ToolRegistry.standard(self.wishes, self.family, self.relations)
        self.agent = ChatAgent(llm_client or ChatAgent.client_for(settings.llm), settings.llm, self.tools,
                               self.chat_history, SystemPrompt(self.family, self.relations))
