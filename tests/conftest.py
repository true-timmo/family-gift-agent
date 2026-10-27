import json

import pytest

from app.config import Settings
from app.container import Container
from app.domain.models import Actor


class RecordingNotifier:
    def __init__(self):
        self.sent = []

    def publish(self, notification):
        self.sent.append(notification)


class RecordingTransport:
    def __init__(self):
        self.messages = []

    async def deliver(self, message):
        self.messages.append(message)

    def last_text(self) -> str:
        return self.messages[-1].get_body(("plain",)).get_content()


class Family:
    """Test-Familie: Mama, Papa und Lena mit Login, Oma ohne. Mama ist Admin (falls angefordert)."""

    MEMBERS = (("Mama", "mama@example.de"), ("Papa", "papa@example.de"), ("Lena", "lena@example.de"), ("Oma", None))

    def __init__(self, path, members=MEMBERS, services: dict | None = None, **settings):
        self.notifier = RecordingNotifier()
        self.mails = RecordingTransport()
        self.c = Container(Settings(db_path=str(path), **settings), notifier=self.notifier, mail_transport=self.mails,
                           **(services or {}))
        self.db = self.c.database
        self.ids = {name: self.c.family.add(name, email).id for name, email in members}

    def person(self, name):
        return self.c.family.get(name)

    def actor(self, name, admin=False) -> Actor:
        return Actor(self.person(name), is_admin=admin)

    def call(self, who, tool, admin=False, **args):
        return self.c.tools.execute(self.actor(who, admin), tool, json.dumps(args))

    def add_wish(self, who, person, title, **args) -> int:
        return self.call(who, "wunsch_hinzufuegen", person=person, titel=title, **args)["id"]

    def titles(self, who, person):
        return [w["titel"] for w in self.call(who, "wuensche_anzeigen", person=person)["wuensche"]]

    def status_of(self, name):
        return next(m.status for m in self.c.family.members() if m.name == name)

    def reset_mail_limit(self):
        self.db.execute("DELETE FROM otp_sends")


@pytest.fixture
def fam(tmp_path):
    return Family(tmp_path / "test.db")


@pytest.fixture
def admin_fam(tmp_path):
    return Family(tmp_path / "test.db", admin_email="MAMA@example.de")   # Groß/klein egal
