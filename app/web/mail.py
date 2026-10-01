import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import HTTPException

from ..domain.values import masked_email

log = logging.getLogger("uvicorn.error")


@asynccontextmanager
async def mail_delivery(what: str, email: str) -> AsyncIterator[None]:
    """Macht aus einem fehlgeschlagenen Versand eine verständliche Meldung (502) – Details nur ins Log."""
    try:
        yield
    except Exception:
        log.exception("Versand (%s) an %s fehlgeschlagen", what, masked_email(email))
        raise HTTPException(502, f"{what} konnte nicht verschickt werden. Bitte später nochmal versuchen.")
