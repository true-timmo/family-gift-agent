"""Datenschutz: Namen und E-Mail-Adressen gehen nie im Klartext an das Sprachmodell.

Vor dem Senden werden alle bekannten Familiennamen durch Platzhalter ersetzt („Andrea“ → „Person7“, auch im
Genitiv „Andreas“ → „Person7s“), E-Mail-Adressen durch „Mailadresse1“ usw. Was das Modell zurückgibt – Text und
Tool-Argumente –, wird wieder in Klartext übersetzt. Die Platzhalter je Person sind stabil (Personen-Nummer),
damit das Modell über mehrere Nachrichten hinweg dieselbe Person wiedererkennt.

Grenze: Namen, die die App noch nicht kennt (z.B. jemand, der gerade erst angelegt werden soll), bleiben stehen.
"""
import re
from typing import Iterable

from ..domain.models import Person

_EMAIL = re.compile(r"[^@\s<>()\[\]\"',;:]+@[^@\s<>()\[\]\"',;:]+\.[A-Za-z]{2,}")
_URL = re.compile(r"https?://\S+")
_TOKEN = re.compile(r"(Person|Mailadresse)(\d+)")
_TOKEN_PREFIXES = ("Person", "Mailadresse")


class Pseudonymizer:
    def __init__(self, persons: Iterable[Person]):
        self._to_token: dict[str, str] = {}      # Kleinschreibung des Namens → Platzhalter
        self._to_text: dict[str, str] = {}       # Platzhalter → Klartext
        for p in persons:
            token = f"Person{p.id}"
            self._to_token[p.name.lower()] = token
            self._to_text[token] = p.name
        names = sorted(self._to_token, key=len, reverse=True)          # „Oma Gisela“ vor „Oma“
        # Name als ganzes Wort, gern mit Genitiv-s („Andreas Liste“) – das s bleibt stehen
        self._names = re.compile(r"(?<!\w)(" + "|".join(map(re.escape, names)) + r")(?=s?(?!\w))",
                                 re.IGNORECASE) if names else None
        self._emails: dict[str, str] = {}        # Adresse (klein) → Platzhalter

    @property
    def instructions(self) -> str:
        return ("Datenschutz: Namen und E-Mail-Adressen sind durch Platzhalter wie Person3 oder Mailadresse1 "
                "ersetzt. Verwende sie genau so – auch in Antworten und Tool-Aufrufen, im Genitiv z.B. „Person3s“. "
                "Die App zeigt den Nutzern automatisch die echten Namen.")

    def mask(self, text: str) -> str:
        """Klartext → Platzhalter (Links bleiben unverändert, nur Adressen darin werden ersetzt)."""
        parts, last = [], 0
        for url in _URL.finditer(text):
            parts += [self._mask_plain(text[last:url.start()]), url.group()]
            last = url.end()
        return "".join(parts + [self._mask_plain(text[last:])])

    def _mask_plain(self, text: str) -> str:
        text = _EMAIL.sub(self._email_token, text)
        return self._names.sub(lambda m: self._to_token[m.group(1).lower()], text) if self._names else text

    def _email_token(self, m: re.Match) -> str:
        address = m.group()
        if address.lower() not in self._emails:
            token = f"Mailadresse{len(self._emails) + 1}"
            self._emails[address.lower()] = token
            self._to_text[token] = address
        return self._emails[address.lower()]

    def unmask(self, text: str) -> str:
        """Platzhalter → Klartext. Unbekannte Platzhalter bleiben stehen."""
        return _TOKEN.sub(lambda m: self._to_text.get(m.group(), m.group()), text)

    def stream(self) -> "StreamUnmasker":
        return StreamUnmasker(self)


class StreamUnmasker:
    """Übersetzt gestreamten Text zurück. Ein Platzhalter kann auf zwei Stücke verteilt ankommen („Pers“+„on3“) –
    das mögliche Anfangsstück wird zurückgehalten, bis klar ist, was es ist."""

    def __init__(self, privacy: Pseudonymizer):
        self._privacy = privacy
        self._pending = ""

    def feed(self, delta: str) -> str:
        text = self._pending + delta
        cut = _unfinished_token_start(text)
        self._pending = text[cut:]
        return self._privacy.unmask(text[:cut])

    def flush(self) -> str:
        text, self._pending = self._pending, ""
        return self._privacy.unmask(text)


def _unfinished_token_start(text: str) -> int:
    """Position, ab der das Ende von `text` noch ein (wachsender) Platzhalter sein könnte."""
    tail = re.search(r"[A-Za-z]+\d*$", text)
    if not tail:
        return len(text)
    word = tail.group()
    letters = word.rstrip("0123456789")
    for prefix in _TOKEN_PREFIXES:
        # „Pers“ (Anfang des Präfixes) oder „Person12“ (vielleicht folgen noch Ziffern)
        if (letters == word and prefix.startswith(letters)) or letters.endswith(prefix):
            return tail.start() + (len(letters) - len(prefix) if letters.endswith(prefix) else 0)
    return len(text)
