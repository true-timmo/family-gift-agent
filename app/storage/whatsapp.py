from dataclasses import dataclass

from .database import Database, now


@dataclass(frozen=True)
class WhatsAppChat:
    chat_id: str
    person_id: int | None
    pending_name: str | None


class WhatsAppChatRepository:
    def __init__(self, db: Database):
        self._db = db

    def get(self, chat_id: str) -> WhatsAppChat | None:
        row = self._db.one("SELECT * FROM whatsapp_chats WHERE chat_id = ?", (chat_id,))
        return WhatsAppChat(row["chat_id"], row["person_id"], row["pending_name"]) if row else None

    def _upsert(self, chat_id: str, person_id: int | None, pending_name: str | None) -> None:
        self._db.execute(
            """INSERT INTO whatsapp_chats (chat_id, person_id, pending_name, updated_at) VALUES (?, ?, ?, ?)
               ON CONFLICT(chat_id) DO UPDATE SET person_id = excluded.person_id,
                 pending_name = excluded.pending_name, updated_at = excluded.updated_at""",
            (chat_id, person_id, pending_name, now()))

    def start(self, chat_id: str) -> None:
        self._upsert(chat_id, None, None)

    def await_code(self, chat_id: str, name: str) -> None:
        self._upsert(chat_id, None, name)

    def link(self, chat_id: str, person_id: int) -> None:
        self._db.execute("DELETE FROM whatsapp_chats WHERE person_id = ? AND chat_id != ?", (person_id, chat_id))
        self._upsert(chat_id, person_id, None)

    def unlink(self, chat_id: str) -> None:
        self._db.execute("DELETE FROM whatsapp_chats WHERE chat_id = ?", (chat_id,))

    def delete_all_for(self, person_id: int) -> int:
        return self._db.execute("DELETE FROM whatsapp_chats WHERE person_id = ?", (person_id,)).rowcount
