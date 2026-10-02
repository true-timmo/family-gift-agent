"""SQLite-Verbindung, Schema und Transaktionen."""
import sqlite3
import time
from contextlib import contextmanager
from typing import Any, Iterator

DAY = 86400

SCHEMA = """
CREATE TABLE IF NOT EXISTS persons (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE COLLATE NOCASE,   -- zugleich der Login-Name
    email       TEXT,                                  -- NULL = kein eigener Login (z.B. Kinder)
    created_at  INTEGER NOT NULL
);

-- Einmal-Codes für die Anmeldung; pro Name höchstens einer aktiv
CREATE TABLE IF NOT EXISTS otp_codes (
    name        TEXT PRIMARY KEY COLLATE NOCASE,
    email       TEXT NOT NULL,
    code_hash   TEXT NOT NULL,
    expires_at  INTEGER NOT NULL,
    attempts    INTEGER NOT NULL DEFAULT 0,
    register    INTEGER NOT NULL DEFAULT 0            -- 1 = legt nach Bestätigung Person/Mail an
);

-- Einladungen per Mail: einmal verwendbar, befristet. Name und Mail legt der Einladende fest.
-- Pro Person gibt es höchstens eine offene Einladung.
CREATE TABLE IF NOT EXISTS invites (
    token_hash  TEXT PRIMARY KEY,
    person_id   INTEGER NOT NULL REFERENCES persons(id),
    email       TEXT NOT NULL,
    invited_by  INTEGER NOT NULL REFERENCES persons(id),
    created_at  INTEGER NOT NULL,
    expires_at  INTEGER NOT NULL,
    used_at     INTEGER
);

-- Versandprotokoll für das Mail-Limit
CREATE TABLE IF NOT EXISTS otp_sends (
    name        TEXT NOT NULL COLLATE NOCASE,
    sent_at     INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS wishes (
    id           INTEGER PRIMARY KEY,
    person_id    INTEGER NOT NULL REFERENCES persons(id),  -- wer sich das wünscht
    title        TEXT NOT NULL,
    description  TEXT,
    shop         TEXT,
    url          TEXT,
    price        TEXT,
    created_by   INTEGER NOT NULL REFERENCES persons(id),
    created_at   INTEGER NOT NULL,
    reserved_by  INTEGER REFERENCES persons(id),           -- wer es besorgt
    reserved_at  INTEGER,
    deleted_at   INTEGER                                    -- vom Wünschenden entfernt
);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash  TEXT PRIMARY KEY,
    person_id   INTEGER NOT NULL REFERENCES persons(id),
    expires_at  INTEGER NOT NULL
);

-- Verwandtschaft: person ist <kind> von relative (siehe domain/kinship.py). Nur gespeicherte Angaben,
-- alles Weitere wird abgeleitet.
CREATE TABLE IF NOT EXISTS relations (
    person_id    INTEGER NOT NULL REFERENCES persons(id),
    relative_id  INTEGER NOT NULL REFERENCES persons(id),
    kind         TEXT NOT NULL,
    created_by   INTEGER REFERENCES persons(id),
    created_at   INTEGER NOT NULL,
    PRIMARY KEY (person_id, relative_id, kind)
);

-- Persönliche API-Schlüssel für eigene KI-Assistenten (MCP). Gespeichert wird nur der Hash.
CREATE TABLE IF NOT EXISTS api_keys (
    token_hash    TEXT PRIMARY KEY,
    person_id     INTEGER NOT NULL REFERENCES persons(id),
    created_at    INTEGER NOT NULL,
    expires_at    INTEGER NOT NULL,
    last_used_at  INTEGER,
    revoked_at    INTEGER
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id          INTEGER PRIMARY KEY,
    person_id   INTEGER NOT NULL REFERENCES persons(id),
    role        TEXT NOT NULL,          -- 'user' | 'assistant'
    content     TEXT NOT NULL,
    created_at  INTEGER NOT NULL
);
"""


def now() -> int:
    return int(time.time())


class Database:
    """Eine SQLite-Verbindung im Autocommit-Modus; mehrere Schritte bündelt `transaction()`."""

    def __init__(self, path: str):
        self._conn = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.executescript(SCHEMA)
        self._migrate()
        self._depth = 0

    def _migrate(self) -> None:
        """Ergänzt Spalten, die es in älteren Datenbanken noch nicht gibt."""
        columns = {row["name"] for row in self._conn.execute("PRAGMA table_info(persons)")}
        if "gender" not in columns:
            self._conn.execute("ALTER TABLE persons ADD COLUMN gender TEXT")   # "w" / "m" / NULL

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        return self._conn.execute(sql, params)

    def one(self, sql: str, params: tuple = ()) -> sqlite3.Row | None:
        return self._conn.execute(sql, params).fetchone()

    def all(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        return self._conn.execute(sql, params).fetchall()

    def scalar(self, sql: str, params: tuple = ()) -> Any:
        return self._conn.execute(sql, params).fetchone()[0]

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Alles oder nichts. BEGIN IMMEDIATE sperrt sofort – so kann niemand dazwischen reservieren.

        Verschachtelte Aufrufe laufen in der äußeren Transaktion mit.
        """
        if self._depth:
            self._depth += 1
            try:
                yield
            finally:
                self._depth -= 1
            return
        self._conn.execute("BEGIN IMMEDIATE")
        self._depth = 1
        try:
            yield
            self._conn.execute("COMMIT")
        except BaseException:
            self._conn.execute("ROLLBACK")
            raise
        finally:
            self._depth = 0
