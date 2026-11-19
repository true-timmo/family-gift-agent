"""Wer war wann zuletzt da – und wer lange nicht vorbeigeschaut hat, bekommt einmal im Monat eine Erinnerung."""
from datetime import datetime
from typing import Callable
from zoneinfo import ZoneInfo

from ..domain.models import Person
from ..domain.notifications import ComeBackReminder, Notifier
from ..storage import PersonRepository, WishRepository
from ..storage.database import DAY, now

_BERLIN = ZoneInfo("Europe/Berlin")


def _berlin_hour() -> int:
    return datetime.now(_BERLIN).hour


class Presence:
    AWAY_DAYS = 30                  # so lange weg → Erinnerung; danach wieder frühestens nach so vielen Tagen
    SEND_HOURS = range(9, 20)       # Mails nur tagsüber (deutsche Zeit)
    _SEEN_EVERY = 3600              # Besuch höchstens einmal pro Stunde speichern

    def __init__(self, persons: PersonRepository, wishes: WishRepository, notifier: Notifier,
                 hour: Callable[[], int] = _berlin_hour):
        self._persons = persons
        self._wishes = wishes
        self._notifier = notifier
        self._hour = hour

    def seen(self, person: Person) -> None:
        t = now()
        self._persons.mark_seen(person.id, t, unless_since=t - self._SEEN_EVERY)

    def send_reminders(self) -> int:
        if self._hour() not in self.SEND_HOURS:
            return 0
        t = now()
        due = self._persons.absent(since=t - self.AWAY_DAYS * DAY)
        for away in due:
            self._persons.mark_nudged(away.person.id, t)
            new = tuple(self._wishes.new_for_others_since(away.person.id, away.last_seen_at))
            self._notifier.publish(ComeBackReminder(away.person.email, away.person.name, new))
        return len(due)
