"""Grober Textvergleich: Passt „Konzertkarten für die Backstreet Boys“ zu einem gespeicherten Wunsch?

Gebraucht für Geheimtipps – die kennt das Sprachmodell aus Sicht der Person nicht, es kann also keine Nummer
nennen. Lieber einen Treffer verpassen als einen fremden Wunsch entfernen: Es müssen mindestens die Hälfte
der aussagekräftigen Wörter der Beschreibung passen.
"""
import re

_STOPWORDS = frozenset("""
    der die das den dem des ein eine einen einem einer eines und oder für von vom mit im in am an zum zur auf aus bei
    ich mir mich mein meine meinen habe hab hat hatte haben gerne gern sehr paar neue neuen neues neuer ganz noch
    schon jetzt heute selbst selber gekauft besorgt bestellt the and for
""".split())


def keywords(text: str) -> set[str]:
    words = re.findall(r"[^\W_]+", text.lower())
    return {w for w in words if len(w) >= 3 and w not in _STOPWORDS}


def _same(a: str, b: str) -> bool:
    """Gleiches Wort – oder Teil eines zusammengesetzten Worts („karten“ in „konzertkarten“)."""
    return a == b or (min(len(a), len(b)) >= 5 and (a in b or b in a))


def matches(query: str, *candidate_texts: str | None) -> bool:
    wanted = keywords(query)
    available = keywords(" ".join(t for t in candidate_texts if t))
    if not wanted or not available:
        return False
    found = {w for w in wanted if any(_same(w, a) for a in available)}
    return len(found) * 2 >= len(wanted)
