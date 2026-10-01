from .database import Database, now


class ChatRepository:
    """Chatverlauf je Person – Rollen 'user' und 'assistant' im Format der Chat-API."""

    def __init__(self, db: Database):
        self._db = db

    def add(self, person_id: int, role: str, content: str) -> None:
        self._db.execute("INSERT INTO chat_messages (person_id, role, content, created_at) VALUES (?, ?, ?, ?)",
                         (person_id, role, content, now()))

    def recent(self, person_id: int, limit: int = 20) -> list[dict[str, str]]:
        rows = self._db.all("SELECT role, content FROM chat_messages WHERE person_id = ? ORDER BY id DESC LIMIT ?",
                            (person_id, limit))
        return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]

    def clear(self, person_id: int) -> None:
        self._db.execute("DELETE FROM chat_messages WHERE person_id = ?", (person_id,))
