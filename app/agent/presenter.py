"""Wie das Sprachmodell Wünsche zu sehen bekommt: deutsche Feldnamen, nur ausgefüllte Felder.

Hier entscheidet sich auch, was das Modell NICHT erfährt – z.B. wer einen eigenen Wunsch besorgt.
"""
from ..domain.models import ListedWish, Reservation, Wish, WishDetails, WishList

# Feldname im Chat → Attribut von WishDetails (gilt für Tool-Argumente und Ergebnisse)
WISH_FIELDS = {"titel": "title", "beschreibung": "description", "shop": "shop", "link": "url", "preis": "price"}


def details_from_args(args: dict) -> WishDetails:
    return WishDetails(**{attr: args.get(key) for key, attr in WISH_FIELDS.items()})


def shop_markdown(shop: str | None, url: str | None) -> str | None:
    """Shop als fertiger Markdown-Link zur Anzeige: [Manufactum](https://…) – spart eine Link-Spalte.

    Ohne Shop-Namen heißt der Link „Zum Shop“; ohne Link bleibt es der reine Name.
    """
    if url and url.startswith(("http://", "https://")):
        text = (shop or "Zum Shop").replace("[", "(").replace("]", ")")
        return f"[{text}]({url.replace(' ', '%20').replace(')', '%29')})"
    return shop


def wish(w: Wish, **extra) -> dict:
    result = {"id": w.id}
    result |= {key: value for key, attr in WISH_FIELDS.items() if (value := getattr(w.details, attr))}
    if display := shop_markdown(w.details.shop, w.details.url):
        result["shop_anzeige"] = display
        result.pop("link", None)     # steckt schon im Link – sonst baut das Modell gern eine Link-Spalte
    if w.secret:                     # nur andere bekommen Geheimtipps zu sehen (siehe Wish.hidden_from)
        result["geheimtipp_von"] = w.creator_name
    return result | extra


def wish_list(wl: WishList) -> dict:
    return {"person": wl.person.name, "eigene_liste": wl.is_own, "wuensche": [_listed(e) for e in wl.entries]}


def _listed(entry: ListedWish) -> dict:
    match entry.reservation:
        case None:
            return wish(entry.wish)
        case Reservation.TAKEN:
            by = entry.wish.reserver_name
            return wish(entry.wish, status=f"besorgt {by}", besorgt_von=by)
        case status:
            return wish(entry.wish, status=str(status))


def reservation(w: Wish) -> dict:
    hint = {"hinweis": "wurde von der Person von ihrer Liste entfernt"} if w.is_deleted else {}
    return wish(w, fuer=w.person_name, **hint)
