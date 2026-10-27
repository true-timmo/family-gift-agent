"""WhatsApp-Bot: dieselbe Familienliste und derselbe Assistent wie im Web – nur per WhatsApp.

Wer zum ersten Mal schreibt, wird zugeordnet: Name nennen → 6-stelliger Code per E-Mail → Code hier eintippen.
Danach gehört der Chat dieser Person (eine Person = ein Chat). Gegen Sperren durch WhatsApp antwortet der Bot
nur auf Nachrichten und schreibt nie von sich aus.
"""
import asyncio
import logging
import re
from collections import OrderedDict

from ..agent import ChatAgent
from ..domain.errors import DomainError
from ..domain.models import Person
from ..domain.values import person_name
from ..mail import Mailer
from ..services import AdminPolicy, FamilyService, LoginCodeService
from ..storage import WhatsAppChatRepository
from .formatting import to_whatsapp
from .waha import WahaClient

log = logging.getLogger("uvicorn.error")

WELCOME = ("Hallo! 👋 Ich bin der Geschenke-Helfer der Familie.\n\n"
           "Damit ich weiß, wer du bist: Wie heißt du? Schreib mir deinen Namen so, wie er in der Geschenke-Liste steht.")
CODE_SENT = ("Danke! Falls es dich in der Geschenke-Liste gibt, habe ich dir gerade einen *Code mit 6 Ziffern* "
             "per E-Mail geschickt. Schick mir die Ziffern hier.\n\n"
             "Falscher Name? Schreib ihn einfach nochmal.")
CODE_FAILED = ("Das hat leider nicht geklappt. Prüf die Ziffern aus der neuesten E-Mail – oder schreib deinen Namen "
               "nochmal, dann bekommst du einen neuen Code.")
LINKED = ("Super, {name} – wir sind verbunden! 🎁\n\n"
          "Schreib mir einfach, z.B. „Ich wünsche mir …“ oder „Was wünscht sich Mama?“.\n"
          "Mit „abmelden“ trennst du die Verbindung wieder.")
UNLINKED = "Erledigt – dieser Chat ist nicht mehr mit der Geschenke-Liste verbunden. Schreib mir, um dich neu anzumelden."
TEXT_ONLY = "Ich kann leider nur Textnachrichten lesen – Bilder und Sprachnachrichten noch nicht. Schreib es mir bitte."
FAILED = "Da ist gerade etwas schiefgegangen. Bitte versuch es gleich nochmal."

_CODE = re.compile(r"^\s*(\d[\d ]{4,8}\d)\s*$")
_UNLINK_WORDS = ("abmelden", "/abmelden", "stop", "/stop")


class WhatsAppBot:
    def __init__(self, waha: WahaClient, chats: WhatsAppChatRepository, family: FamilyService,
                 login_codes: LoginCodeService, mailer: Mailer, admins: AdminPolicy, agent: ChatAgent):
        self._waha = waha
        self._chats = chats
        self._family = family
        self._login_codes = login_codes
        self._mailer = mailer
        self._admins = admins
        self._agent = agent
        self._locks: dict[str, asyncio.Lock] = {}
        self._seen: OrderedDict[str, None] = OrderedDict()     # WAHA kann Webhooks wiederholen

    async def handle_event(self, event: dict) -> None:
        """Eingang eines Webhooks von WAHA. Fehler landen im Log, der Absender bekommt eine kurze Meldung."""
        if event.get("event") != "message":
            return
        message = event.get("payload") or {}
        chat_id, message_id = message.get("from") or "", message.get("id") or ""
        # Nur Einzelchats von anderen – keine Gruppen, Status-Meldungen oder eigenen Nachrichten
        if message.get("fromMe") or not chat_id or chat_id.endswith(("@g.us", "@broadcast", "@newsletter")):
            return
        if self._already_seen(message_id):
            return
        async with self._locks.setdefault(chat_id, asyncio.Lock()):
            try:
                await self._quietly(self._waha.mark_seen(chat_id))
                text = (message.get("body") or "").strip()
                await self._reply(chat_id, await self._answer(chat_id, text) if text else TEXT_ONLY)
            except Exception:
                log.exception("WhatsApp-Nachricht konnte nicht verarbeitet werden")
                await self._reply(chat_id, FAILED)

    async def _answer(self, chat_id: str, text: str) -> str:
        chat = self._chats.get(chat_id)
        person = self._family.by_id(chat.person_id) if chat and chat.person_id else None
        if chat and chat.person_id and not (person and person.email):   # Person gelöscht oder Login entzogen
            self._chats.unlink(chat_id)
            chat = None
        if not chat:
            self._chats.start(chat_id)
            return WELCOME
        if person:
            if text.lower() in _UNLINK_WORDS:
                self._chats.unlink(chat_id)
                return UNLINKED
            return await self._ask_assistant(chat_id, person, text)
        if chat.pending_name and (code := _CODE.match(text)):
            return self._verify(chat_id, chat.pending_name, code.group(1))
        return await self._send_code(chat_id, text)

    async def _send_code(self, chat_id: str, text: str) -> str:
        """Name → Code per Mail. Die Antwort ist immer gleich – sie verrät nicht, ob es den Namen gibt."""
        try:
            name = person_name(text)
        except DomainError as e:
            return str(e)
        self._chats.await_code(chat_id, name)
        person = self._family.get(name)
        if person and person.email:
            try:
                code = self._login_codes.issue(person.name, person.email, register=False)
                await self._mailer.send_login_code(person.email, person.name, code, self._login_codes.VALID_MINUTES)
            except DomainError as e:              # z.B. Versandlimit
                return str(e)
        return CODE_SENT

    def _verify(self, chat_id: str, name: str, code: str) -> str:
        try:
            person = self._login_codes.verify(name, code.replace(" ", ""))
        except DomainError:
            return CODE_FAILED
        self._chats.link(chat_id, person.id)
        log.info("WhatsApp-Chat mit %s verbunden", person.name)
        return LINKED.format(name=person.name)

    async def _ask_assistant(self, chat_id: str, person: Person, text: str) -> str:
        await self._quietly(self._waha.typing(chat_id, True))
        answer, error = "", None
        try:
            async for event in self._agent.reply(self._admins.actor(person), text, channel="whatsapp"):
                if event["type"] == "text":
                    answer += event["text"]
                elif event["type"] == "error":
                    error = event["text"]
        finally:
            await self._quietly(self._waha.typing(chat_id, False))
        return error or to_whatsapp(answer) or "(keine Antwort)"

    @staticmethod
    async def _quietly(action) -> None:
        """„Gelesen“ und „schreibt …“ sind nur Komfort – ein Fehler dabei soll die Antwort nicht verhindern."""
        try:
            await action
        except Exception:
            log.warning("WhatsApp-Statusmeldung fehlgeschlagen", exc_info=True)

    async def _reply(self, chat_id: str, text: str) -> None:
        await self._waha.send_text(chat_id, text)

    def _already_seen(self, message_id: str) -> bool:
        if not message_id:
            return False
        if message_id in self._seen:
            return True
        self._seen[message_id] = None
        if len(self._seen) > 500:
            self._seen.popitem(last=False)
        return False
