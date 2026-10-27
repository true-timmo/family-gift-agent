"""Antworten des Assistenten (Markdown) für WhatsApp aufbereiten: *fett*, Links als Adresse, Tabellen als Karten."""
import re

_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")
_TABLE_SEP = re.compile(r"^\s*\|?(\s*:?-{2,}:?\s*\|)+\s*(:?-{2,}:?\s*)?\|?\s*$")
_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^\s)]+)\)")
_BOLD = re.compile(r"\*\*([^*]+)\*\*")
_HEADING = re.compile(r"^#{1,6}\s*(.+)$")
_EMPTY = ("", "–", "-")


def _inline(text: str) -> str:
    text = _LINK.sub(lambda m: f"{m.group(1)}: {m.group(2)}", text)
    return _BOLD.sub(r"*\1*", text)


def _cells(row: str) -> list[str]:
    return [c.strip() for c in row.strip().strip("|").split("|")]


def _card(head: list[str], row: list[str]) -> str:
    """Eine Tabellenzeile als kleine Karte: *Titel*, Details, dann „Spalte: Wert“."""
    lines = []
    for index, (column, value) in enumerate(zip(head, row)):
        if value in _EMPTY:
            continue
        if index == 0:
            lines.append(f"*{_inline(value).strip('*')}*")
        elif column.lower() in ("details", "beschreibung"):
            lines.append(_inline(value))
        else:
            lines.append(f"{column}: {_inline(value)}")
    return "\n".join(lines)


def to_whatsapp(markdown: str) -> str:
    lines, out, i = markdown.split("\n"), [], 0
    while i < len(lines):
        line = lines[i]
        if _TABLE_ROW.match(line) and i + 1 < len(lines) and _TABLE_SEP.match(lines[i + 1]):
            head, i = _cells(line), i + 2
            while i < len(lines) and _TABLE_ROW.match(lines[i]):
                out += [_card(head, _cells(lines[i])), ""]
                i += 1
            continue
        heading = _HEADING.match(line)
        out.append(f"*{_inline(heading.group(1))}*" if heading else _inline(line))
        i += 1
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()
