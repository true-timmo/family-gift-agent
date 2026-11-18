"""Wiederkehrende Aufgaben im Hintergrund, solange der Server läuft."""
import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator, Callable

log = logging.getLogger("uvicorn.error")


async def _every(seconds: float, job: Callable[[], object], name: str) -> None:
    while True:
        try:
            job()
        except Exception:
            log.exception("Hintergrundaufgabe „%s“ fehlgeschlagen", name)
        await asyncio.sleep(seconds)


@asynccontextmanager
async def periodic(seconds: float, job: Callable[[], object], name: str) -> AsyncIterator[None]:
    """Führt `job` sofort und dann alle `seconds` Sekunden aus – bis der Kontext endet."""
    task = asyncio.create_task(_every(seconds, job, name))
    try:
        yield
    finally:
        task.cancel()
