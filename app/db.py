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


def _check_send_limit(conn, name: str, now: int) -> None:
    """Höchstens 1 Mail pro Minute und 5 pro Stunde je Name (Codes und Einladungen zusammen)."""
    for period, limit in SEND_LIMITS:
        n = conn.execute("SELECT COUNT(*) FROM otp_sends WHERE name = ? AND sent_at > ?",
                         (name, now - period)).fetchone()[0]
        if n >= limit:
            raise WishError("Es wurde gerade erst eine Mail verschickt. Bitte kurz warten und ins Postfach schauen.")
    conn.execute("INSERT INTO otp_sends (name, sent_at) VALUES (?, ?)", (name, now))


def create_otp(conn, name: str, email: str, register: bool) -> str:
    """Erzeugt einen neuen 6-stelligen Code (ersetzt einen älteren) – mit Versandlimit."""
    now = int(time.time())
    with transaction(conn):
        _check_send_limit(conn, name, now)
        code = f"{secrets.randbelow(10**6):06d}"
        conn.execute(
            "INSERT OR REPLACE INTO otp_codes (name, email, code_hash, expires_at, attempts, register) "
            "VALUES (?, ?, ?, ?, 0, ?)",
            (name, email, _code_hash(name, code), now + OTP_MINUTES * 60, int(register)),
        )
        conn.execute("DELETE FROM otp_sends WHERE sent_at < ?", (now - 86400,))
    return code


def verify_otp(conn, name: str, code: str, outbox: list | None = None):
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
            _finish_registration(conn, name, otp, outbox)
    if wrong_code_left is not None:
        raise WishError(f"Der Code stimmt nicht. Noch {wrong_code_left} Versuch(e)." if wrong_code_left
                        else "Der Code stimmt nicht. Bitte einen neuen anfordern.")
    return get_person(conn, name)


def _finish_registration(conn, name: str, otp, outbox: list | None) -> None:
    """Nach bestätigtem Code: bei einer Registrierung Person anlegen bzw. Mail-Adresse hinterlegen."""
    if not otp["register"]:
        return
    person = get_person(conn, name)
    if person and person["email"]:
        raise WishError("Diesen Namen hat inzwischen jemand anderes registriert.")
    if conn.execute("SELECT 1 FROM persons WHERE lower(email) = lower(?) AND id IS NOT ?",
                    (otp["email"], person["id"] if person else None)).fetchone():
        raise WishError("Diese E-Mail-Adresse wird schon verwendet.")
    if person:   # Person existierte schon ohne Login (z.B. Oma, von anderen eingetragen) → Mail ergänzen
        conn.execute("UPDATE persons SET email = ? WHERE id = ?", (otp["email"], person["id"]))
    else:
        add_person(conn, otp["name"], otp["email"])   # Schreibweise aus der Registrierung
    if outbox is not None:
        outbox.append({"type": "neu_registriert", "name": otp["name"], "eingeladen_von": None})


# --- Einladungen per Mail -------------------------------------------------------

INVITE_DAYS = 7
INVITES_PER_DAY = 20


def email_owner(conn, email: str, except_person_id: int | None = None) -> str | None:
    """Name der Person, die diese Mail-Adresse schon nutzt oder dafür offen eingeladen ist (sonst None).

    Groß-/Kleinschreibung wird ignoriert. `except_person_id` nimmt eine Person von der Prüfung aus.
    """
    row = conn.execute(
        """SELECT name FROM persons WHERE lower(email) = lower(?) AND id IS NOT ?
           UNION ALL
           SELECT p.name FROM invites i JOIN persons p ON p.id = i.person_id
           WHERE lower(i.email) = lower(?) AND i.used_at IS NULL AND i.expires_at > ? AND p.id IS NOT ?
           LIMIT 1""",
        (email.strip(), except_person_id, email.strip(), int(time.time()), except_person_id),
    ).fetchone()
    return row["name"] if row else None


def create_invite(conn, inviter_id: int, name: str, email: str, existing: bool = False) -> tuple[str, str]:
    """Lädt `name` mit `email` ein und gibt (Token für den Link, Name in gültiger Schreibweise) zurück.

    - existing=False („Jemanden einladen“): nur für NEUE Namen – ein vorhandener Name ist ein Fehler.
    - existing=True („Einladen“/„Erneut“ in der Liste): für vorhandene, noch nicht registrierte Personen.
      Eine offene Einladung wird dabei ersetzt – so lässt sich eine falsch getippte Adresse korrigieren.
    Eine Mail-Adresse darf nur zu einer Person gehören.
    """
    now = int(time.time())
    with transaction(conn):
        person = get_person(conn, name)
        if person and person["email"]:
            raise WishError(f"{person['name']} ist schon registriert und kann sich direkt mit dem Namen anmelden.")
        if person and not existing:
            hint = ("ist schon eingeladen. Zum erneuten Einladen in der Liste auf „Erneut“ tippen."
                    if pending_invite(conn, person["name"]) else
                    "gibt es schon. Zum Einladen in der Liste auf „Einladen“ tippen – "
                    "oder einen anderen Namen wählen, falls es jemand anderes ist.")
            raise WishError(f"{person['name']} {hint}")
        if existing and not person:
            raise WishError(f"{name} gibt es nicht.")
        if owner := email_owner(conn, email, person["id"] if person else None):
            raise WishError(f"Diese E-Mail-Adresse gehört schon zu {owner}.")
        n = conn.execute("SELECT COUNT(*) FROM invites WHERE invited_by = ? AND created_at > ?",
                         (inviter_id, now - 86400)).fetchone()[0]
        if n >= INVITES_PER_DAY:
            raise WishError("Heute wurden schon sehr viele Einladungen verschickt. Bitte morgen wieder.")
        person_id = person["id"] if person else add_person(conn, name)
        name = person["name"] if person else name.strip()
        _check_send_limit(conn, name, now)
        conn.execute("DELETE FROM invites WHERE person_id = ? AND used_at IS NULL", (person_id,))
        token = secrets.token_urlsafe(18)
        conn.execute(
            "INSERT INTO invites (token_hash, person_id, email, invited_by, created_at, expires_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (_token_hash(token), person_id, email, inviter_id, now, now + INVITE_DAYS * 86400),
        )
    return token, name


def resend_invite(conn, name: str) -> tuple[str, dict] | None:
    """Neuer Link für eine offene Einladung (z.B. Mail gelöscht). None, wenn es keine gibt."""
    inv = pending_invite(conn, name)
    if not inv:
        return None
    now = int(time.time())
    with transaction(conn):
        _check_send_limit(conn, inv["name"], now)
        conn.execute("DELETE FROM invites WHERE token_hash = ?", (inv["token_hash"],))
        token = secrets.token_urlsafe(18)
        conn.execute(
            "INSERT INTO invites (token_hash, person_id, email, invited_by, created_at, expires_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (_token_hash(token), inv["person_id"], inv["email"], inv["invited_by"], now, now + INVITE_DAYS * 86400),
        )
    return token, dict(inv)


_INVITE_SELECT = """SELECT i.*, p.name AS name, inv.name AS inviter FROM invites i
    JOIN persons p ON p.id = i.person_id JOIN persons inv ON inv.id = i.invited_by"""


def get_invite(conn, token: str):
    """Gültige (unbenutzte, nicht abgelaufene) Einladung zum Link oder None."""
    return conn.execute(f"{_INVITE_SELECT} WHERE i.token_hash = ? AND i.used_at IS NULL AND i.expires_at > ?",
                        (_token_hash(token or ""), int(time.time()))).fetchone()


def pending_invite(conn, name: str):
    """Offene, noch gültige Einladung für eine Person oder None."""
    return conn.execute(f"{_INVITE_SELECT} WHERE p.name = ? AND p.email IS NULL "
                        "AND i.used_at IS NULL AND i.expires_at > ?",
                        (name.strip(), int(time.time()))).fetchone()


def accept_invite(conn, token: str, outbox: list | None = None):
    """Nimmt eine Einladung an: hinterlegt die Mail-Adresse und gibt die Person zurück.

    Der Klick auf den Link aus der Mail beweist, dass die Adresse stimmt – ein Code ist nicht nötig.
    """
    with transaction(conn):
        inv = get_invite(conn, token)
        if not inv:
            raise WishError("Diese Einladung ist abgelaufen oder wurde schon benutzt. Bitte um eine neue.")
        person = conn.execute("SELECT * FROM persons WHERE id = ?", (inv["person_id"],)).fetchone()
        if person["email"]:
            raise WishError(f"{person['name']} ist schon registriert. Bitte einfach mit dem Namen anmelden.")
        if conn.execute("SELECT 1 FROM persons WHERE lower(email) = lower(?) AND id != ?",
                        (inv["email"], inv["person_id"])).fetchone():
            raise WishError("Diese E-Mail-Adresse wird inzwischen von jemand anderem genutzt. Bitte um eine neue Einladung.")
        conn.execute("UPDATE persons SET email = ? WHERE id = ?", (inv["email"], inv["person_id"]))
        conn.execute("UPDATE invites SET used_at = ? WHERE token_hash = ?", (int(time.time()), inv["token_hash"]))
    if outbox is not None:
        outbox.append({"type": "neu_registriert", "name": inv["name"], "eingeladen_von": inv["inviter"]})
    return get_person(conn, inv["name"])


def family_status(conn) -> list[dict]:
    """Alle Personen mit Status: registriert / eingeladen / offen (ohne Mail-Adressen)."""
    now = int(time.time())
    rows = conn.execute(
        """SELECT p.id, p.name, p.email IS NOT NULL AS registriert,
                  EXISTS(SELECT 1 FROM invites i WHERE i.person_id = p.id AND i.used_at IS NULL
                         AND i.expires_at > ?) AS eingeladen
           FROM persons p ORDER BY p.name""", (now,)).fetchall()
    return [{"id": r["id"], "name": r["name"],
             "status": "registriert" if r["registriert"] else "eingeladen" if r["eingeladen"] else "offen"}
            for r in rows]


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
    person = find_person(conn, name)
    if email and (owner := email_owner(conn, email, person["id"])):
        raise WishError(f"Diese E-Mail-Adresse gehört schon zu {owner}.")
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


def shop_markdown(shop: str | None, url: str | None) -> str | None:
    """Shop als fertiger Markdown-Link zur Anzeige: [Manufactum](https://…) – spart eine Link-Spalte.

    Ohne Shop-Namen heißt der Link „Zum Shop“; ohne Link bleibt es der reine Name.
    """
    if url and url.startswith(("http://", "https://")):
        text = (shop or "Zum Shop").replace("[", "(").replace("]", ")")
        return f"[{text}]({url.replace(' ', '%20').replace(')', '%29')})"
    return shop


def _public(w, **extra) -> dict:
    d = {"id": w["id"], "titel": w["title"]}
    for key, col in (("beschreibung", "description"), ("shop", "shop"), ("link", "url"), ("preis", "price")):
        if w[col]:
            d[key] = w[col]
    if anzeige := shop_markdown(w["shop"], w["url"]):
        d["shop_anzeige"] = anzeige
        d.pop("link", None)          # steckt schon im Link – sonst baut das Modell gern eine Link-Spalte
    d.update(extra)
    return d


def list_wishes(conn, actor_id: int, person_name: str) -> dict:
    """Wünsche einer Person – je nachdem, WER fragt:

    - Fragt die Person nach ihren eigenen Wünschen, sieht sie ALLE, ohne jeden Hinweis
      auf Reservierungen (Überraschungsschutz).
    - Andere sehen alle Wünsche mit Status: „offen“, „von dir reserviert“ oder „besorgt <Name>“.
      Von anderen reservierte Wünsche stehen am Ende und lassen sich nicht reservieren.
    """
    person = find_person(conn, person_name)
    rows = conn.execute(
        """SELECT w.*, r.name AS reserved_name FROM wishes w LEFT JOIN persons r ON r.id = w.reserved_by
           WHERE w.person_id = ? AND w.deleted_at IS NULL ORDER BY w.created_at""",
        (person["id"],),
    ).fetchall()

    if person["id"] == actor_id:
        return {"person": person["name"], "eigene_liste": True, "wuensche": [_public(w) for w in rows]}

    visible, taken = [], []
    for w in rows:
        if w["reserved_by"] is None:
            visible.append(_public(w, status="offen"))
        elif w["reserved_by"] == actor_id:
            visible.append(_public(w, status="von dir reserviert"))
        else:
            taken.append(_public(w, status=f"besorgt {w['reserved_name']}", besorgt_von=w["reserved_name"]))
    return {"person": person["name"], "eigene_liste": False, "wuensche": visible + taken}


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
            by = conn.execute("SELECT p.name FROM wishes w JOIN persons p ON p.id = w.reserved_by "
                              "WHERE w.id = ?", (wish_id,)).fetchone()
            raise WishError(f"Das besorgt schon {by['name']}." if by else "Das besorgt schon jemand anderes.")
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


def _check_editable(w, actor_id: int, admin: bool = False) -> None:
    if w["deleted_at"]:
        raise WishError("Dieser Wunsch wurde schon entfernt.")
    if not admin and actor_id not in (w["person_id"], w["created_by"]):
        raise WishError("Diesen Wunsch kannst du nicht ändern – nur die Person selbst oder wer ihn eingetragen hat.")


def update_wish(conn, actor_id: int, wish_id: int, admin: bool = False, **fields) -> dict:
    cols = {"titel": "title", "beschreibung": "description", "shop": "shop", "link": "url", "preis": "price"}
    changes = {cols[k]: v for k, v in fields.items() if k in cols and v is not None}
    with transaction(conn):
        _check_editable(_wish(conn, wish_id), actor_id, admin)
        if changes:
            sets = ", ".join(f"{c} = ?" for c in changes)
            conn.execute(f"UPDATE wishes SET {sets} WHERE id = ?", (*changes.values(), wish_id))
    return _public(_wish(conn, wish_id))


def delete_wish(conn, actor_id: int, wish_id: int, outbox: list | None = None, admin: bool = False) -> dict:
    """Entfernt einen Wunsch (Soft-Delete).

    War er reserviert, landet eine Benachrichtigung für die reservierende Person in `outbox`.
    Wer reserviert hat, steht NUR dort – nie im Rückgabewert, den das Sprachmodell sieht.
    """
    with transaction(conn):
        w = _wish(conn, wish_id)
        _check_editable(w, actor_id, admin)
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


# --- Admin ----------------------------------------------------------------------

def is_admin(person) -> bool:
    """Admin ist, wessen Mail-Adresse in ADMIN_EMAIL steht (Groß/klein egal)."""
    admin = os.environ.get("ADMIN_EMAIL", "").strip().lower()
    return bool(admin and person and person["email"] and person["email"].strip().lower() == admin)


def admin_person(conn):
    admin = os.environ.get("ADMIN_EMAIL", "").strip()
    return conn.execute("SELECT * FROM persons WHERE lower(email) = lower(?)", (admin,)).fetchone() if admin else None


def delete_person(conn, admin_id: int, name: str, outbox: list | None = None) -> dict:
    """Löscht eine Person endgültig (nur Admin – das prüft der Aufrufer).

    - Ihre Wünsche werden gelöscht; wer davon etwas reserviert hatte, wird benachrichtigt.
    - Ihre eigenen Reservierungen werden freigegeben (Geschenke sind wieder offen).
    - Wünsche, die sie für andere eingetragen hat, bleiben – eingetragen gilt dann der Admin.
    - Sessions, Chatverlauf, Codes und offene Einladungen verschwinden.
    """
    with transaction(conn):
        p = find_person(conn, name)
        if p["id"] == admin_id:
            raise WishError("Du kannst dich nicht selbst entfernen.")
        admin_name = conn.execute("SELECT name FROM persons WHERE id = ?", (admin_id,)).fetchone()["name"]
        notify = conn.execute(
            """SELECT w.title, r.name, r.email FROM wishes w JOIN persons r ON r.id = w.reserved_by
               WHERE w.person_id = ? AND w.deleted_at IS NULL AND w.reserved_by != ?""",
            (p["id"], p["id"])).fetchall()
        wishes = conn.execute("SELECT COUNT(*) FROM wishes WHERE person_id = ? AND deleted_at IS NULL",
                              (p["id"],)).fetchone()[0]
        released = conn.execute("UPDATE wishes SET reserved_by = NULL, reserved_at = NULL "
                                "WHERE reserved_by = ? AND person_id != ?", (p["id"], p["id"])).rowcount
        conn.execute("DELETE FROM wishes WHERE person_id = ?", (p["id"],))
        conn.execute("UPDATE wishes SET created_by = ? WHERE created_by = ?", (admin_id, p["id"]))
        conn.execute("DELETE FROM invites WHERE person_id = ?", (p["id"],))
        conn.execute("UPDATE invites SET invited_by = ? WHERE invited_by = ?", (admin_id, p["id"]))
        for table in ("sessions", "chat_messages"):
            conn.execute(f"DELETE FROM {table} WHERE person_id = ?", (p["id"],))
        for table in ("otp_codes", "otp_sends"):
            conn.execute(f"DELETE FROM {table} WHERE name = ?", (p["name"],))
        conn.execute("DELETE FROM persons WHERE id = ?", (p["id"],))
    if outbox is not None:
        for n in notify:
            if n["email"]:
                outbox.append({"type": "wunsch_entfernt", "an": n["email"], "empfaenger": n["name"],
                               "fuer": p["name"], "entfernt_von": admin_name, "titel": n["title"]})
    return {"name": p["name"], "wuensche_geloescht": wishes, "reservierungen_freigegeben": released}


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
