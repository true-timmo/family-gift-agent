"""Einladungen per Mail."""
import pytest

from app.domain.errors import ConflictError, NotFoundError, RateLimitError
from app.domain.notifications import NewRegistration


def invite(fam, inviter, name, email, existing=False):
    return fam.c.invitations.invite(fam.person(inviter), name, email, existing=existing)


def test_einladung_neue_person(fam):
    issued = invite(fam, "Mama", "Gisela", "gisela@example.de")
    assert issued.name == "Gisela" and fam.status_of("Gisela") == "eingeladen"
    # Schon vor dem Annehmen können andere Wünsche für Gisela eintragen
    assert "fehler" not in fam.call("Papa", "wunsch_hinzufuegen", person="Gisela", titel="Schal")
    info = fam.c.invitations.lookup(issued.token)
    assert (info.name, info.inviter) == ("Gisela", "Mama")
    p = fam.c.invitations.accept(issued.token)
    assert (p.name, p.email) == ("Gisela", "gisela@example.de")
    assert fam.status_of("Gisela") == "registriert"
    assert fam.notifier.sent == [NewRegistration("Gisela", invited_by="Mama")]


def test_einladung_nur_einmal_gueltig(fam):
    token = invite(fam, "Mama", "Gisela", "gisela@example.de").token
    fam.c.invitations.accept(token)
    assert fam.c.invitations.lookup(token) is None
    with pytest.raises(NotFoundError, match="abgelaufen oder wurde schon benutzt"):
        fam.c.invitations.accept(token)


def test_einladung_abgelaufen(fam):
    token = invite(fam, "Mama", "Gisela", "gisela@example.de").token
    fam.db.execute("UPDATE invites SET expires_at = 0")
    assert fam.status_of("Gisela") == "offen"
    with pytest.raises(NotFoundError, match="abgelaufen"):
        fam.c.invitations.accept(token)


def test_einladung_korrigiert_falsche_adresse(fam):
    alt = invite(fam, "Mama", "Oma", "oma@tippfehler.de", existing=True).token
    fam.reset_mail_limit()
    neu = invite(fam, "Mama", "oma", "oma@example.de", existing=True).token
    assert fam.c.invitations.lookup(alt) is None                       # alter Link ungültig
    oma = fam.c.invitations.accept(neu)
    assert oma.id == fam.ids["Oma"] and oma.email == "oma@example.de"  # bestehende Person übernommen


def test_registrierte_person_nicht_einladbar(fam):
    with pytest.raises(ConflictError, match="schon registriert"):
        invite(fam, "Mama", "Papa", "papa2@example.de")


def test_einladung_nochmal_schicken(fam):
    alt = invite(fam, "Mama", "Gisela", "gisela@example.de").token
    with pytest.raises(RateLimitError, match="warten"):                # Versandlimit greift auch hier
        fam.c.invitations.resend("Gisela")
    fam.reset_mail_limit()
    neu = fam.c.invitations.resend("gisela")
    assert neu.email == "gisela@example.de" and neu.inviter == "Mama"
    assert fam.c.invitations.lookup(alt) is None and fam.c.invitations.lookup(neu.token).name == "Gisela"
    assert fam.c.invitations.resend("Lena") is None                    # registriert → keine offene Einladung


def test_neue_einladung_mit_vorhandenem_namen_abgelehnt(fam):
    with pytest.raises(ConflictError, match="Oma gibt es schon"):            # offen, ohne Login
        invite(fam, "Mama", "oma", "oma@example.de")
    invite(fam, "Mama", "Gisela", "gisela@example.de")
    with pytest.raises(ConflictError, match="schon eingeladen"):              # offene Einladung
        invite(fam, "Papa", "Gisela", "gisela2@example.de")
    with pytest.raises(NotFoundError, match="gibt es nicht"):                 # „Erneut“ für Unbekannte
        invite(fam, "Papa", "Unbekannt", "u@example.de", existing=True)


def test_mailadresse_nur_einmal(fam):
    with pytest.raises(ConflictError, match="gehört schon zu Mama"):         # registrierte Person
        invite(fam, "Papa", "Gisela", "MAMA@Example.de")                      # Groß/klein egal
    invite(fam, "Papa", "Gisela", "gisela@example.de")
    with pytest.raises(ConflictError, match="gehört schon zu Gisela"):       # offene Einladung
        invite(fam, "Papa", "Oma", "gisela@example.de", existing=True)
    fam.reset_mail_limit()
    invite(fam, "Papa", "Gisela", "gisela@example.de", existing=True)        # gleiche Person: ok
    with pytest.raises(ConflictError, match="gehört schon zu Papa"):
        fam.c.family.set_email("Oma", "papa@example.de")


def test_annehmen_wenn_mail_inzwischen_vergeben(fam):
    token = invite(fam, "Mama", "Gisela", "gisela@example.de").token
    fam.db.execute("UPDATE persons SET email = 'gisela@example.de' WHERE name = 'Oma'")   # Sonderfall
    with pytest.raises(ConflictError, match="inzwischen von jemand anderem"):
        fam.c.invitations.accept(token)
