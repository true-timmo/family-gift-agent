"""Werkzeuge, die das Sprachmodell aufrufen darf.

Jedes Tool bekommt die angemeldete Person (Actor) vom Server – nie aus dem Chat.
Das Modell kann also nicht „als jemand anderes“ handeln.
"""
import json
from abc import ABC, abstractmethod
from typing import ClassVar, Iterable

from ..domain.errors import DomainError
from ..domain.models import Actor, Reservation
from ..services import FamilyService, WishService
from . import presenter

_WISH_ID = {"wunsch_id": {"type": "integer"}}
_PERSON = {"person": {"type": "string", "description": "Name der Person"}}
_WISH_FIELDS = {
    "titel": {"type": "string", "description": "Kurzer Name des Geschenks"},
    "beschreibung": {"type": "string", "description": "Details wie Größe, Farbe, Modell"},
    "shop": {"type": "string", "description": "Wo es das zu kaufen gibt (Geschäft oder Online-Shop)"},
    "link": {"type": "string", "description": "Direkter Link zum Produkt"},
    "preis": {"type": "string", "description": "Ungefährer Preis, z.B. '39 €'"},
}


class Tool(ABC):
    name: ClassVar[str]
    description: ClassVar[str]
    parameters: ClassVar[dict[str, dict]] = {}
    required: ClassVar[tuple[str, ...]] = ()

    def schema(self) -> dict:
        """Beschreibung im OpenAI-Format (OpenRouter ist dazu kompatibel)."""
        return {"type": "function", "function": {
            "name": self.name,
            "description": self.description,
            "parameters": {"type": "object", "properties": self.parameters, "required": list(self.required)},
        }}

    @abstractmethod
    def run(self, actor: Actor, args: dict) -> dict:
        """Führt das Tool aus. Darf DomainError, KeyError, TypeError und ValueError werfen."""


class WishTool(Tool, ABC):
    def __init__(self, wishes: WishService):
        self._wishes = wishes

    @staticmethod
    def _wish_id(args: dict) -> int:
        return int(args["wunsch_id"])


class ListPersons(Tool):
    name = "personen_auflisten"
    description = "Listet alle Familienmitglieder mit Status: registriert, eingeladen oder offen."

    def __init__(self, family: FamilyService):
        self._family = family

    def run(self, actor: Actor, args: dict) -> dict:
        return {"personen": [{"name": m.name, "status": str(m.status)} for m in self._family.members()]}


class AddWish(WishTool):
    name = "wunsch_hinzufuegen"
    description = "Trägt einen Geschenkwunsch ein. Für eigene Wünsche den eigenen Namen als 'person' verwenden."
    parameters = {"person": {"type": "string", "description": "Wer sich das wünscht (Name wie in der Personenliste)"},
                  **_WISH_FIELDS}
    required = ("person", "titel")

    def run(self, actor: Actor, args: dict) -> dict:
        wish = self._wishes.add(actor, args["person"], presenter.details_from_args(args))
        return {"id": wish.id, "fuer": wish.person_name, "titel": wish.title}


class ShowWishes(WishTool):
    name = "wuensche_anzeigen"
    description = "Zeigt die Wunschliste einer Person mit Status (offen / von dir reserviert / besorgt <Name>)."
    parameters = _PERSON
    required = ("person",)

    def run(self, actor: Actor, args: dict) -> dict:
        return presenter.wish_list(self._wishes.list_for(actor, args["person"]))


class Reserve(WishTool):
    name = "reservieren"
    description = ("Markiert, dass die anfragende Person dieses Geschenk besorgt. Andere sehen es dann als "
                   "„besorgt <Name>“ und können es nicht mehr reservieren.")
    parameters = _WISH_ID
    required = ("wunsch_id",)

    def run(self, actor: Actor, args: dict) -> dict:
        return presenter.wish(self._wishes.reserve(actor, self._wish_id(args)), status=str(Reservation.MINE))


class Unreserve(WishTool):
    name = "reservierung_aufheben"
    description = "Gibt ein reserviertes Geschenk wieder frei, z.B. wenn man es doch nicht besorgt."
    parameters = _WISH_ID
    required = ("wunsch_id",)

    def run(self, actor: Actor, args: dict) -> dict:
        return presenter.wish(self._wishes.unreserve(actor, self._wish_id(args)), status=str(Reservation.OPEN))


class MyReservations(WishTool):
    name = "meine_reservierungen"
    description = "Listet alle Geschenke, die die anfragende Person besorgen will."

    def run(self, actor: Actor, args: dict) -> dict:
        return {"reservierungen": [presenter.reservation(w) for w in self._wishes.reservations(actor)]}


class EditWish(WishTool):
    name = "wunsch_bearbeiten"
    description = "Ändert Angaben eines Wunsches (nur eigene oder selbst eingetragene)."
    parameters = {**_WISH_ID, **_WISH_FIELDS}
    required = ("wunsch_id",)

    def run(self, actor: Actor, args: dict) -> dict:
        wish = self._wishes.update(actor, self._wish_id(args), presenter.details_from_args(args))
        return presenter.wish(wish)


class RemoveWish(WishTool):
    name = "wunsch_entfernen"
    description = "Entfernt einen Wunsch (nur eigene oder selbst eingetragene), z.B. wenn er sich erledigt hat."
    parameters = _WISH_ID
    required = ("wunsch_id",)

    def run(self, actor: Actor, args: dict) -> dict:
        wish = self._wishes.remove(actor, self._wish_id(args))
        return {"id": wish.id, "titel": wish.title, "entfernt": True}   # bewusst ohne „wer hatte reserviert“


class ToolRegistry:
    def __init__(self, tools: Iterable[Tool]):
        self._tools = {tool.name: tool for tool in tools}

    @classmethod
    def standard(cls, wishes: WishService, family: FamilyService) -> "ToolRegistry":
        return cls([ListPersons(family), AddWish(wishes), ShowWishes(wishes), Reserve(wishes), Unreserve(wishes),
                    MyReservations(wishes), EditWish(wishes), RemoveWish(wishes)])

    def schemas(self) -> list[dict]:
        return [tool.schema() for tool in self._tools.values()]

    def execute(self, actor: Actor, name: str, raw_args: str) -> dict:
        """Gibt immer ein JSON-fähiges Ergebnis zurück – Fehler als {"fehler": …}, damit das Modell sie erklärt."""
        tool = self._tools.get(name)
        if not tool:
            return {"fehler": f"Unbekanntes Tool '{name}'."}
        try:
            args = json.loads(raw_args or "{}")
        except ValueError:
            args = None
        if not isinstance(args, dict):
            return {"fehler": "Ungültige Argumente (kein JSON-Objekt)."}
        if missing := [key for key in tool.required if args.get(key) is None]:
            return {"fehler": f"Fehlende oder ungültige Angabe: {missing[0]!r}"}
        try:
            return tool.run(actor, args)
        except DomainError as e:
            return {"fehler": str(e)}
        except (KeyError, TypeError, ValueError) as e:
            return {"fehler": f"Fehlende oder ungültige Angabe: {e}"}
