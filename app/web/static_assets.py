"""Auslieferung der Oberfläche so, dass nach einem Update sofort die neue Version im Browser ist.

Ohne Cache-Angaben heben Browser Dateien nach Gutdünken stundenlang auf – dann läuft nach einem Deploy noch
das alte JavaScript. Deshalb: Startseite und statische Dateien immer beim Server nachfragen („no-cache“, per
ETag meist nur ein kurzes „unverändert“), und Skript/Stylesheet tragen zusätzlich ihren Inhalts-Hash in der
Adresse (?v=…), damit auch eigenwillige Zwischenspeicher eine neue Version als neue Datei sehen.
"""
import hashlib
import re
from pathlib import Path

from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

NO_CACHE = {"Cache-Control": "no-cache"}
_ASSET = re.compile(r'(?P<attr>(?:src|href)=")/static/(?P<path>[^"?]+)"')


def _fingerprint(file: Path) -> str | None:
    return hashlib.sha256(file.read_bytes()).hexdigest()[:12] if file.is_file() else None


class IndexPage:
    """Die Startseite mit versionierten Adressen für alle Dateien unter /static (beim Start berechnet)."""

    def __init__(self, static_dir: Path):
        def versioned(m: re.Match) -> str:
            version = _fingerprint(static_dir / m["path"])
            suffix = f"?v={version}" if version else ""
            return f'{m["attr"]}/static/{m["path"]}{suffix}"'

        self._html = _ASSET.sub(versioned, (static_dir / "index.html").read_text(encoding="utf-8"))

    def response(self) -> HTMLResponse:
        return HTMLResponse(self._html, headers=NO_CACHE)


class RevalidatedStaticFiles(StaticFiles):
    """Statische Dateien, bei denen der Browser jedes Mal kurz nachfragt, ob es eine neue Version gibt."""

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers.update(NO_CACHE)
        return response
