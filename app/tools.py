"""Werkzeuge, die das Sprachmodell aufrufen darf.

Jedes Tool bekommt die angemeldete Person (actor) vom Server – nie aus dem Chat.
Das Modell kann also nicht "als jemand anderes" handeln.
"""
import json

from . import db

# Schema im OpenAI-Format (OpenRouter ist dazu kompatibel)
def _tool(name, description, properties=None, required=()):
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties or {},
                "required": list(required),
            },
        },
    }


_WISH_FIELDS = {
    "titel": {"type": "string", "description": "Kurzer Name des Geschenks"},
    "beschreibung": {"type": "string", "description": "Details wie Größe, Farbe, Modell"},
    "shop": {"type": "string", "description": "Wo es das zu kaufen gibt (Geschäft oder Online-Shop)"},
    "link": {"type": "string", "description": "Direkter Link zum Produkt"},
    "preis": {"type": "string", "description": "Ungefährer Preis, z.B. '39 €'"},
}

TOOLS = [
    _tool("personen_auflisten", "Listet alle Familienmitglieder mit Status: registriert, eingeladen oder offen."),
    _tool(
        "wunsch_hinzufuegen",
        "Trägt einen Geschenkwunsch ein. Für eigene Wünsche den eigenen Namen als 'person' verwenden.",
        {"person": {"type": "string", "description": "Wer sich das wünscht (Name wie in der Personenliste)"},
         **_WISH_FIELDS},
        required=("person", "titel"),
    ),
    _tool(
        "wuensche_anzeigen",
        "Zeigt die Wunschliste einer Person. Bereits von anderen besorgte Geschenke sind ausgeblendet.",
        {"person": {"type": "string", "description": "Name der Person"}},
        required=("person",),
    ),
    _tool(
        "reservieren",
        "Markiert, dass die anfragende Person dieses Geschenk besorgt. Danach sehen andere es nicht mehr.",
        {"wunsch_id": {"type": "integer"}},
        required=("wunsch_id",),
    ),
    _tool(
        "reservierung_aufheben",
        "Gibt ein reserviertes Geschenk wieder frei, z.B. wenn man es doch nicht besorgt.",
        {"wunsch_id": {"type": "integer"}},
        required=("wunsch_id",),
    ),
    _tool("meine_reservierungen", "Listet alle Geschenke, die die anfragende Person besorgen will."),
    _tool(
        "wunsch_bearbeiten",
        "Ändert Angaben eines Wunsches (nur eigene oder selbst eingetragene).",
        {"wunsch_id": {"type": "integer"}, **_WISH_FIELDS},
        required=("wunsch_id",),
    ),
    _tool(
        "wunsch_entfernen",
        "Entfernt einen Wunsch (nur eigene oder selbst eingetragene), z.B. wenn er sich erledigt hat.",
        {"wunsch_id": {"type": "integer"}},
        required=("wunsch_id",),
    ),
]


def execute(conn, actor_id: int, name: str, raw_args: str, outbox: list | None = None) -> dict:
    """Führt ein Tool aus und gibt immer ein JSON-fähiges Ergebnis zurück – auch bei Fehlern.

    Benachrichtigungen (z.B. Mails) werden in `outbox` gesammelt statt an das Modell zurückgegeben.
    """
    try:
        args = json.loads(raw_args or "{}")
        if not isinstance(args, dict):
            raise ValueError
    except ValueError:
        return {"fehler": "Ungültige Argumente (kein JSON-Objekt)."}

    try:
        match name:
            case "personen_auflisten":
                return {"personen": [{"name": p["name"], "status": p["status"]} for p in db.family_status(conn)]}
            case "wunsch_hinzufuegen":
                return db.add_wish(conn, actor_id, args["person"], args["titel"],
                                   args.get("beschreibung"), args.get("shop"),
                                   args.get("link"), args.get("preis"))
            case "wuensche_anzeigen":
                return db.list_wishes(conn, actor_id, args["person"])
            case "reservieren":
                return db.reserve(conn, actor_id, int(args["wunsch_id"]))
            case "reservierung_aufheben":
                return db.unreserve(conn, actor_id, int(args["wunsch_id"]))
            case "meine_reservierungen":
                return {"reservierungen": db.my_reservations(conn, actor_id)}
            case "wunsch_bearbeiten":
                wid = int(args.pop("wunsch_id"))
                return db.update_wish(conn, actor_id, wid, **args)
            case "wunsch_entfernen":
                return db.delete_wish(conn, actor_id, int(args["wunsch_id"]), outbox)
            case _:
                return {"fehler": f"Unbekanntes Tool '{name}'."}
    except db.WishError as e:
        return {"fehler": str(e)}
    except (KeyError, TypeError, ValueError) as e:
        return {"fehler": f"Fehlende oder ungültige Angabe: {e}"}
