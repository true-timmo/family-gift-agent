"""Admin-Rechte: fremde Wünsche bearbeiten, Personen entfernen."""
import json

import pytest

from app.domain.errors import PermissionDeniedError
from app.domain.notifications import WishRemoved


def test_admin_erkennung(admin_fam):
    admins = admin_fam.c.admins
    assert admins.is_admin(admin_fam.person("Mama"))
    assert not admins.is_admin(admin_fam.person("Papa"))
    assert not admins.is_admin(admin_fam.person("Oma"))            # ohne Mail nie Admin
    assert admins.admin().name == "Mama"
    assert admins.actor(admin_fam.person("Mama")).is_admin


def test_admin_bearbeitet_und_entfernt_fremde_wuensche(admin_fam):
    f = admin_fam
    w = f.add_wish("Papa", "Papa", "Pfanne")
    assert "fehler" in f.call("Lena", "wunsch_bearbeiten", wunsch_id=w, link="https://x.de/p")   # kein Admin
    assert f.call("Mama", "wunsch_bearbeiten", admin=True, wunsch_id=w, link="https://x.de/p")["shop_anzeige"] == \
        "[Zum Shop](https://x.de/p)"
    f.call("Lena", "reservieren", wunsch_id=w)
    assert f.call("Mama", "wunsch_entfernen", admin=True, wunsch_id=w)["entfernt"]
    assert f.notifier.sent[0].recipient_name == "Lena" and f.notifier.sent[0].removed_by == "Mama"


def test_admin_ohne_admin_flag_hat_keine_sonderrechte(admin_fam):
    w = admin_fam.add_wish("Papa", "Papa", "Pfanne")
    assert "fehler" in admin_fam.call("Mama", "wunsch_entfernen", wunsch_id=w)   # Flag kommt nur vom Server


def test_ueberraschungsschutz_gilt_auch_fuer_admin(admin_fam):
    w = admin_fam.add_wish("Mama", "Mama", "Kette")
    admin_fam.call("Papa", "reservieren", wunsch_id=w)
    dump = json.dumps(admin_fam.call("Mama", "wuensche_anzeigen", admin=True, person="Mama"))
    assert "Papa" not in dump and "besorgt" not in dump and "reserv" not in dump


def test_person_loeschen(admin_fam):
    f = admin_fam
    papa_wunsch = f.add_wish("Papa", "Papa", "Pfanne")
    f.add_wish("Papa", "Papa", "Buch")
    oma_wunsch = f.add_wish("Papa", "Oma", "Wärmflasche")           # für andere eingetragen
    lena_wunsch = f.add_wish("Lena", "Lena", "Rad")
    f.call("Lena", "reservieren", wunsch_id=papa_wunsch)            # Lena besorgt Papas Pfanne
    f.call("Papa", "reservieren", wunsch_id=lena_wunsch)            # Papa besorgt Lenas Rad
    f.c.sessions.start(f.person("Papa"))

    r = f.c.removals.remove(f.person("Mama"), "papa")
    assert (r.name, r.wishes_deleted, r.reservations_released) == ("Papa", 2, 1)
    assert f.person("Papa") is None
    # Lena bekommt Bescheid, dass Papas Pfanne weg ist
    assert f.notifier.sent == [WishRemoved(recipient_email="lena@example.de", recipient_name="Lena",
                                           wished_by="Papa", removed_by="Mama", title="Pfanne")]
    # Papas Reservierung ist freigegeben, Omas Wunsch bleibt (jetzt „eingetragen von“ Mama)
    assert f.call("Mama", "wuensche_anzeigen", person="Lena")["wuensche"][0]["status"] == "offen"
    assert f.titles("Lena", "Oma") == ["Wärmflasche"]
    assert f.db.scalar("SELECT created_by FROM wishes WHERE id = ?", (oma_wunsch,)) == f.ids["Mama"]
    assert f.db.scalar("SELECT COUNT(*) FROM sessions WHERE person_id = ?", (f.ids["Papa"],)) == 0


def test_person_loeschen_mit_einladungen(admin_fam):
    f = admin_fam
    f.c.invitations.invite(f.person("Papa"), "Gisela", "gisela@example.de")   # Papa hat Gisela eingeladen
    f.c.removals.remove(f.person("Mama"), "Papa")
    assert f.c.invitations.pending_for("Gisela").inviter == "Mama"          # Einladung bleibt gültig
    f.reset_mail_limit()
    token = f.c.invitations.invite(f.person("Mama"), "Tante Uschi", "u@example.de").token
    f.c.removals.remove(f.person("Mama"), "Tante Uschi")                     # eingeladen, noch nicht dabei
    assert f.c.invitations.lookup(token) is None


def test_admin_kann_sich_nicht_selbst_loeschen(admin_fam):
    with pytest.raises(PermissionDeniedError, match="nicht selbst"):
        admin_fam.c.removals.remove(admin_fam.person("Mama"), "Mama")
