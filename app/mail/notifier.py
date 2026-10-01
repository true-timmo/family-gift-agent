import asyncio
import logging

from ..domain.notifications import Notification
from .mailer import Mailer


class BackgroundMailNotifier:
    """Verschickt Benachrichtigungen im Hintergrund – die Antwort an den Nutzer wartet nicht darauf.

    Fehler werden nur protokolliert, nie an den Chat gemeldet.
    """

    def __init__(self, mailer: Mailer, log: logging.Logger):
        self._mailer = mailer
        self._log = log
        self._tasks: set[asyncio.Task] = set()     # hält laufende Tasks am Leben

    def publish(self, notification: Notification) -> None:
        try:
            task = asyncio.get_running_loop().create_task(self._deliver(notification))
        except RuntimeError:
            self._log.warning("Benachrichtigung ohne Event-Loop verworfen: %s", type(notification).__name__)
            return
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _deliver(self, notification: Notification) -> None:
        try:
            await self._mailer.send_notification(notification)
        except Exception:
            self._log.exception("Benachrichtigung (%s) konnte nicht verschickt werden", type(notification).__name__)
