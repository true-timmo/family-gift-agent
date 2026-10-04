"""Werkzeuge, die das Sprachmodell aufrufen darf.

Jedes Tool bekommt die angemeldete Person (Actor) vom Server – nie aus dem Chat.
Das Modell kann also nicht „als jemand anderes“ handeln.
"""
import json
from datetime import datetime
from abc import ABC, abstractmethod
from typing import ClassVar, Iterable

from ..domain.errors import DomainError
from ..domain.models import Actor, Reservation
from ..domain.values import person_name
from ..services import AdminContact, ApiKeyService, FamilyService, RelationService, WishService
from . import presenter

_WISH_ID = {"wunsch_id": {"type": "integer"}}
_PERSON = {"person": {"type": "string",
                       "description": "Name der Person – oder wie die fragende Person sie nennt (z.B. 'Mama', 'Oma')"}}
_RELATION = {
    "person": {"type": "string", "description": "Um wen es geht (Name; bei 'ich' der eigene Name)"},
    "beziehung": {"type": "string", "description": "z.B. Mutter, Vater, Schwester, Bruder, Tochter, Sohn, Partnerin, "
                                                  "Oma, Opa, Tante, Onkel, Cousine, Cousin, Schwiegermutter, Schwager"},
    "von": {"type": "string", "description": "Zu wem die Beziehung besteht (Name; bei 'meine …' der eigene Name)"},
}
_WISH_FIELDS = {
    "titel": {"type": "string", "description": "Kurzer Name des Geschenks"},
    "beschreibung": {"type": "string", "description": "Alles für den richtigen Kauf, als kurze Stichworte: Größe, "
                                                     "Farbe, Ausgabe/Auflage, Sprache, Modell, Variante, Menge"},
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


class AddPerson(Tool):
    name = "person_anlegen"
    description = ("Legt ein Familienmitglied OHNE eigenen Login an, z.B. ein Kind ohne E-Mail-Adresse – danach kann "
                   "man Wünsche für es eintragen. Vorher kurz nachfragen, ob die Person wirklich neu ist (Tippfehler?). "
                   "Wer eine E-Mail-Adresse hat, lädt der Admin besser per Mail ein.")
    parameters = {"name": {"type": "string", "description": "Vorname, so wie ihn alle in der Familie kennen"}}
    required = ("name",)

    def __init__(self, family: FamilyService):
        self._family = family

    def run(self, actor: Actor, args: dict) -> dict:
        return {"angelegt": self._family.add_without_login(person_name(args["name"])).name}


class AddWish(WishTool):
    name = "wunsch_hinzufuegen"
    description = "Trägt einen Geschenkwunsch ein. Für eigene Wünsche den eigenen Namen als 'person' verwenden."
    parameters = {"person": {"type": "string", "description": "Wer sich das wünscht: Name wie in der Personenliste "
                                                              "oder Verwandtschaftswort wie 'Mama'"},
                  **_WISH_FIELDS}
    required = ("person", "titel")

    def run(self, actor: Actor, args: dict) -> dict:
        wish = self._wishes.add(actor, args["person"], presenter.details_from_args(args))
        return {"id": wish.id, "fuer": wish.person_name, "titel": wish.title}


class AddTip(WishTool):
    name = "geheimtipp_eintragen"
    description = ("Merkt sich einen Wunsch, den eine ANDERE Person nebenbei erwähnt hat („Andrea hätte gern …“, "
                   "„hab heute erfahren, dass …“). Die Person selbst sieht ihn NIE – alle anderen sehen ihn mit "
                   "„geheimtipp_von“ und können nachfragen. Alle Details (Ort, Datum, Größe …) in die beschreibung.")
    parameters = {"person": {"type": "string", "description": "Für wen der Wunsch ist: Name oder Verwandtschaftswort"},
                  **_WISH_FIELDS}
    required = ("person", "titel")

    def run(self, actor: Actor, args: dict) -> dict:
        wish = self._wishes.add_tip(actor, args["person"], presenter.details_from_args(args))
        return {"id": wish.id, "fuer": wish.person_name, "titel": wish.title, "geheimtipp": True}


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


class RelationTool(Tool, ABC):
    parameters = _RELATION
    required = ("person", "beziehung", "von")

    def __init__(self, relations: RelationService):
        self._relations = relations


class AddRelation(RelationTool):
    name = "verwandtschaft_eintragen"
    description = ("Speichert, wie zwei Familienmitglieder verwandt sind: „<person> ist <beziehung> von <von>“. "
                   "Beispiel: „Katharina ist meine Schwester“ (Timmo schreibt) → person=Katharina, "
                   "beziehung=Schwester, von=Timmo. Weitere Beziehungen leitet die App selbst ab.")

    def run(self, actor: Actor, args: dict) -> dict:
        change = self._relations.add(actor, args["person"], args["beziehung"], args["von"])
        return {"gespeichert": change.statement, "war_schon_bekannt": change.known_before,
                "daraus_folgt": change.derived}


class RemoveRelation(RelationTool):
    name = "verwandtschaft_entfernen"
    description = "Entfernt eine falsch eingetragene Verwandtschaft („<person> ist <beziehung> von <von>“)."

    def run(self, actor: Actor, args: dict) -> dict:
        return {"entfernt": self._relations.remove(actor, args["person"], args["beziehung"], args["von"])}


class ShowRelatives(RelationTool):
    name = "verwandtschaft_anzeigen"
    description = "Zeigt alle bekannten Verwandten einer Person und wie sie zu ihr stehen."
    parameters = _PERSON
    required = ("person",)

    def run(self, actor: Actor, args: dict) -> dict:
        person = self._relations.resolve(actor, args["person"])
        return {"person": person.name, "verwandte": [{"name": r.person.name, "beziehung": " / ".join(r.names)}
                                                     for r in self._relations.relatives(person)]}


class ContactAdmin(Tool):
    name = "admin_kontaktieren"
    description = ("Schickt dem Admin eine Nachricht per E-Mail, z.B. „Bitte lade Gisela ein (gisela@…)“ oder ein "
                   "Problem. Vorher den Text kurz zeigen und bestätigen lassen.")
    parameters = {"nachricht": {"type": "string", "description": "Die Nachricht, in der Ich-Form der fragenden Person"}}
    required = ("nachricht",)

    def __init__(self, contact: AdminContact):
        self._contact = contact

    def run(self, actor: Actor, args: dict) -> dict:
        return {"gesendet_an": self._contact.send(actor, str(args["nachricht"]))}


class AboutMe(RelationTool):
    name = "ueber_mich"
    description = "Zeigt, in wessen Namen gehandelt wird (angemeldete Person), ob sie Admin ist und ihre Verwandten."
    parameters = {}
    required = ()

    def run(self, actor: Actor, args: dict) -> dict:
        return {"name": actor.name, "admin": actor.is_admin,
                "verwandte": [{"name": r.person.name, "beziehung": " / ".join(r.names)}
                              for r in self._relations.relatives(actor.person)]}


class ApiKeyTool(Tool, ABC):
    parameters = {}
    required = ()

    def __init__(self, keys: ApiKeyService):
        self._keys = keys


class RequestApiKey(ApiKeyTool):
    name = "ki_zugang_anfordern"
    description = ("NUR wenn die Person ausdrücklich danach fragt (API-Schlüssel, MCP, eigene KI wie Claude/ChatGPT "
                   "anbinden): schickt ihr per E-Mail einen persönlichen Zugang, gültig 1 Monat. Der Schlüssel "
                   "erscheint nie im Chat. Nicht von dir aus anbieten.")

    def run(self, actor: Actor, args: dict) -> dict:
        sent = self._keys.issue(actor)
        return {"verschickt_an": sent.email,
                "gueltig_bis": datetime.fromtimestamp(sent.expires_at).strftime("%d.%m.%Y")}


class RevokeApiKeys(ApiKeyTool):
    name = "ki_zugang_sperren"
    description = "Sperrt sofort alle KI-Zugänge (API-Schlüssel) der Person, z.B. wenn ein Schlüssel in falsche Hände kam."

    def run(self, actor: Actor, args: dict) -> dict:
        return {"gesperrt": self._keys.revoke_all(actor.person)}


class ToolRegistry:
    def __init__(self, tools: Iterable[Tool]):
        self._tools = {tool.name: tool for tool in tools}

    @classmethod
    def standard(cls, wishes: WishService, family: FamilyService, relations: RelationService,
                 contact: AdminContact, api_keys: ApiKeyService) -> "ToolRegistry":
        return cls([ListPersons(family), AddPerson(family), AddWish(wishes), AddTip(wishes), ShowWishes(wishes), Reserve(wishes), Unreserve(wishes),
                    MyReservations(wishes), EditWish(wishes), RemoveWish(wishes),
                    AddRelation(relations), RemoveRelation(relations), ShowRelatives(relations),
                    ContactAdmin(contact), AboutMe(relations), RequestApiKey(api_keys), RevokeApiKeys(api_keys)])

    def without(self, *names: str) -> "ToolRegistry":
        return ToolRegistry(tool for name, tool in self._tools.items() if name not in names)

    def __iter__(self):
        return iter(self._tools.values())

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
