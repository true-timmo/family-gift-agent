"""SQLite-Datenbank: Personen, Wünsche, Reservierungen, Logins und Chatverlauf.

Die Regeln für Reservierungen und den Überraschungsschutz stehen hier im Code –
nicht im Prompt –, damit das Sprachmodell sie weder vergessen noch umgehen kann.
"""
import hashlib
import hmac
import os
import secrets
import sqlite3
import time
from contextlib import contextmanager

DB_PATH = os.environ.get("DB_PATH", "/app/data/geschenke.db")

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

CREATE TABLE IF NOT EXISTS chat_messages (
    id          INTEGER PRIMARY KEY,
    person_id   INTEGER NOT NULL REFERENCES persons(id),
    role        TEXT NOT NULL,          -- 'user' | 'assistant'
    content     TEXT NOT NULL,
    created_at  INTEGER NOT NULL
);
"""

SESSION_DAYS = 90


class WishError(Exception):
    """Fehler, dessen Text dem Nutzer (über das Modell) gezeigt werden darf."""


def connect(path: str | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(path or DB_PATH, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.executescript(SCHEMA)
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection):
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise


# --- Einmal-Codes (OTP) -------------------------------------------------------

OTP_MINUTES = 10
OTP_MAX_ATTEMPTS = 5
SEND_LIMITS = ((60, 1), (3600, 5))   # (Zeitraum in s, max. Mails) je Name


def _code_hash(name: str, code: str) -> str:
    return hashlib.sha256(f"{name.lower()}:{code}".encode()).hexdigest()


def create_otp(conn, name: str, email: str, register: bool) -> str:
    """Erzeugt einen neuen 6-stelligen Code (ersetzt einen älteren) – mit Versandlimit."""
    now = int(time.time())
    with transaction(conn):
        for period, limit in SEND_LIMITS:
            n = conn.execute("SELECT COUNT(*) FROM otp_sends WHERE name = ? AND sent_at > ?",
                             (name, now - period)).fetchone()[0]
            if n >= limit:
                raise WishError("Es wurde gerade erst ein Code verschickt. Bitte kurz warten und ins Postfach schauen.")
        code = f"{secrets.randbelow(10**6):06d}"
        conn.execute(
            "INSERT OR REPLACE INTO otp_codes (name, email, code_hash, expires_at, attempts, register) "
            "VALUES (?, ?, ?, ?, 0, ?)",
            (name, email, _code_hash(name, code), now + OTP_MINUTES * 60, int(register)),
        )
        conn.execute("INSERT INTO otp_sends (name, sent_at) VALUES (?, ?)", (name, now))
        conn.execute("DELETE FROM otp_sends WHERE sent_at < ?", (now - 86400,))
    return code


def verify_otp(conn, name: str, code: str):
    """Prüft den Code. Gibt die (ggf. neu angelegte) Person zurück oder wirft WishError."""
    wrong_code_left = None
    with transaction(conn):
        otp = conn.execute("SELECT * FROM otp_codes WHERE name = ?", (name,)).fetchone()
        if not otp or otp["expires_at"] < time.time() or otp["attempts"] >= OTP_MAX_ATTEMPTS:
            raise WishError("Der Code ist abgelaufen. Bitte einen neuen anfordern.")
        if not hmac.compare_digest(otp["code_hash"], _code_hash(name, code.strip())):
            # Fehlversuch zählen und committen – erst danach den Fehler melden
            conn.execute("UPDATE otp_codes SET attempts = attempts + 1 WHERE name = ?", (name,))
            wrong_code_left = OTP_MAX_ATTEMPTS - otp["attempts"] - 1
        else:
            conn.execute("DELETE FROM otp_codes WHERE name = ?", (name,))
            _finish_registration(conn, name, otp)
    if wrong_code_left is not None:
        raise WishError(f"Der Code stimmt nicht. Noch {wrong_code_left} Versuch(e)." if wrong_code_left
                        else "Der Code stimmt nicht. Bitte einen neuen anfordern.")
    return get_person(conn, name)


def _finish_registration(conn, name: str, otp) -> None:
    """Nach bestätigtem Code: bei einer Registrierung Person anlegen bzw. Mail-Adresse hinterlegen."""
    if not otp["register"]:
        return
    person = get_person(conn, name)
    if person and person["email"]:
        raise WishError("Diesen Namen hat inzwischen jemand anderes registriert.")
    if person:   # Person existierte schon ohne Login (z.B. Oma, von anderen eingetragen) → Mail ergänzen
        conn.execute("UPDATE persons SET email = ? WHERE id = ?", (otp["email"], person["id"]))
    else:
        add_person(conn, otp["name"], otp["email"])   # Schreibweise aus der Registrierung


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(conn, person_id: int) -> str:
    token = secrets.token_urlsafe(32)
    conn.execute(
        "INSERT INTO sessions (token_hash, person_id, expires_at) VALUES (?, ?, ?)",
        (_token_hash(token), person_id, int(time.time()) + SESSION_DAYS * 86400),
    )
    return token


def session_person(conn, token: str | None):
    if not token:
        return None
    return conn.execute(
        """SELECT p.* FROM sessions s JOIN persons p ON p.id = s.person_id
           WHERE s.token_hash = ? AND s.expires_at > ?""",
        (_token_hash(token), int(time.time())),
    ).fetchone()


def delete_session(conn, token: str) -> None:
    conn.execute("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(token),))


# --- Personen ----------------------------------------------------------------

def add_person(conn, name: str, email: str | None = None) -> int:
    cur = conn.execute(
        "INSERT INTO persons (name, email, created_at) VALUES (?, ?, ?)",
        (name.strip(), email, int(time.time())),
    )
    return cur.lastrowid


def set_email(conn, name: str, email: str | None) -> None:
    cur = conn.execute("UPDATE persons SET email = ? WHERE name = ?", (email, name.strip()))
    if cur.rowcount == 0:
        raise WishError(f"Person '{name}' gibt es nicht.")


def get_person(conn, name: str):
    return conn.execute("SELECT * FROM persons WHERE name = ?", (name.strip(),)).fetchone()


def list_persons(conn):
    return conn.execute("SELECT id, name, email FROM persons ORDER BY name").fetchall()


def find_person(conn, name: str):
    p = conn.execute("SELECT * FROM persons WHERE name = ?", (name.strip(),)).fetchone()
    if not p:
        names = ", ".join(r["name"] for r in list_persons(conn))
        raise WishError(f"Ich kenne niemanden namens '{name}'. Bekannt sind: {names}.")
    return p


# --- Wünsche -----------------------------------------------------------------

def _wish(conn, wish_id: int):
    w = conn.execute("SELECT * FROM wishes WHERE id = ?", (wish_id,)).fetchone()
    if not w:
        raise WishError(f"Wunsch Nr. {wish_id} gibt es nicht.")
    return w


def add_wish(conn, actor_id: int, person_name: str, title: str, description=None,
             shop=None, url=None, price=None) -> dict:
    person = find_person(conn, person_name)
    cur = conn.execute(
        """INSERT INTO wishes (person_id, title, description, shop, url, price, created_by, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (person["id"], title.strip(), description, shop, url, price, actor_id, int(time.time())),
    )
    return {"id": cur.lastrowid, "fuer": person["name"], "titel": title.strip()}


def _public(w, **extra) -> dict:
    d = {"id": w["id"], "titel": w["title"]}
    for key, col in (("beschreibung", "description"), ("shop", "shop"), ("link", "url"), ("preis", "price")):
        if w[col]:
            d[key] = w[col]
    d.update(extra)
    return d


def list_wishes(conn, actor_id: int, person_name: str) -> dict:
    """Wünsche einer Person – je nachdem, WER fragt:

    - Fragt die Person nach ihren eigenen Wünschen, sieht sie ALLE, ohne jeden Hinweis
      auf Reservierungen (Überraschungsschutz).
    - Andere sehen nur noch nicht reservierte Wünsche plus die, die sie selbst reserviert haben.
      Von wem etwas reserviert wurde, erfahren sie nie.
    """
    person = find_person(conn, person_name)
    rows = conn.execute(
        "SELECT * FROM wishes WHERE person_id = ? AND deleted_at IS NULL ORDER BY created_at",
        (person["id"],),
    ).fetchall()

    if person["id"] == actor_id:
        return {"person": person["name"], "eigene_liste": True, "wuensche": [_public(w) for w in rows]}

    visible = []
    for w in rows:
        if w["reserved_by"] is None:
            visible.append(_public(w, status="offen"))
        elif w["reserved_by"] == actor_id:
            visible.append(_public(w, status="von dir reserviert"))
    return {"person": person["name"], "eigene_liste": False, "wuensche": visible}


def reserve(conn, actor_id: int, wish_id: int) -> dict:
    with transaction(conn):
        w = _wish(conn, wish_id)
        # Reihenfolge wichtig: bei eigenen Wünschen NICHT verraten, ob sie reserviert sind
        if w["person_id"] == actor_id:
            raise WishError("Eigene Wünsche kann man nicht reservieren.")
        if w["deleted_at"]:
            raise WishError("Dieser Wunsch wurde entfernt.")
        if w["reserved_by"] == actor_id:
            return _public(w, status="von dir reserviert")
        cur = conn.execute(
            "UPDATE wishes SET reserved_by = ?, reserved_at = ? WHERE id = ? AND reserved_by IS NULL",
            (actor_id, int(time.time()), wish_id),
        )
        if cur.rowcount == 0:
            raise WishError("Das besorgt schon jemand anderes.")
    return _public(_wish(conn, wish_id), status="von dir reserviert")


def unreserve(conn, actor_id: int, wish_id: int) -> dict:
    with transaction(conn):
        w = _wish(conn, wish_id)
        if w["person_id"] == actor_id or w["reserved_by"] != actor_id:
            raise WishError("Diesen Wunsch hast du nicht reserviert.")
        conn.execute("UPDATE wishes SET reserved_by = NULL, reserved_at = NULL WHERE id = ?", (wish_id,))
    return _public(w, status="offen")


def my_reservations(conn, actor_id: int) -> list[dict]:
    rows = conn.execute(
        """SELECT w.*, p.name AS fuer FROM wishes w JOIN persons p ON p.id = w.person_id
           WHERE w.reserved_by = ? ORDER BY p.name, w.created_at""",
        (actor_id,),
    ).fetchall()
    return [
        _public(w, fuer=w["fuer"], **({"hinweis": "wurde von der Person von ihrer Liste entfernt"}
                                       if w["deleted_at"] else {}))
        for w in rows
    ]


def _check_editable(w, actor_id: int) -> None:
    if actor_id not in (w["person_id"], w["created_by"]) or w["deleted_at"]:
        raise WishError("Diesen Wunsch kannst du nicht ändern – nur die Person selbst oder wer ihn eingetragen hat.")


def update_wish(conn, actor_id: int, wish_id: int, **fields) -> dict:
    cols = {"titel": "title", "beschreibung": "description", "shop": "shop", "link": "url", "preis": "price"}
    changes = {cols[k]: v for k, v in fields.items() if k in cols and v is not None}
    with transaction(conn):
        _check_editable(_wish(conn, wish_id), actor_id)
        if changes:
            sets = ", ".join(f"{c} = ?" for c in changes)
            conn.execute(f"UPDATE wishes SET {sets} WHERE id = ?", (*changes.values(), wish_id))
    return _public(_wish(conn, wish_id))


def delete_wish(conn, actor_id: int, wish_id: int, outbox: list | None = None) -> dict:
    """Entfernt einen Wunsch (Soft-Delete).

    War er reserviert, landet eine Benachrichtigung für die reservierende Person in `outbox`.
    Wer reserviert hat, steht NUR dort – nie im Rückgabewert, den das Sprachmodell sieht.
    """
    with transaction(conn):
        w = _wish(conn, wish_id)
        _check_editable(w, actor_id)
        # Soft-Delete: wer ihn reserviert hat, sieht in seinen Reservierungen zusätzlich einen Hinweis
        conn.execute("UPDATE wishes SET deleted_at = ? WHERE id = ?", (int(time.time()), wish_id))
    if outbox is not None and w["reserved_by"] and w["reserved_by"] != actor_id:
        names = {r["id"]: r for r in conn.execute(
            "SELECT id, name, email FROM persons WHERE id IN (?, ?, ?)",
            (w["reserved_by"], w["person_id"], actor_id))}
        reserver = names[w["reserved_by"]]
        if reserver["email"]:
            outbox.append({
                "type": "wunsch_entfernt",
                "an": reserver["email"],
                "empfaenger": reserver["name"],
                "fuer": names[w["person_id"]]["name"],
                "entfernt_von": names[actor_id]["name"],
                "titel": w["title"],
            })
    return {"id": wish_id, "titel": w["title"], "entfernt": True}


# --- Chatverlauf -------------------------------------------------------------

def add_message(conn, person_id: int, role: str, content: str) -> None:
    conn.execute(
        "INSERT INTO chat_messages (person_id, role, content, created_at) VALUES (?, ?, ?, ?)",
        (person_id, role, content, int(time.time())),
    )


def recent_messages(conn, person_id: int, limit: int = 20) -> list[dict]:
    rows = conn.execute(
        "SELECT role, content FROM chat_messages WHERE person_id = ? ORDER BY id DESC LIMIT ?",
        (person_id, limit),
    ).fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]


def clear_messages(conn, person_id: int) -> None:
    conn.execute("DELETE FROM chat_messages WHERE person_id = ?", (person_id,))
