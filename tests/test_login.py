"""Anmeldung per Einmal-Code, Registrierung per Familien-Code und Sitzungen."""
import pytest

from app.domain.errors import AuthenticationError, ConflictError, DomainError, RateLimitError
from app.domain.notifications import NewRegistration
from tests.conftest import Family


def wrong(code):
    return "000000" if code != "000000" else "111111"


def test_code_login_bekannte_person(fam):
    codes = fam.c.login_codes
    code = codes.issue("Mama", "mama@example.de", register=False)
    assert len(code) == 6 and code.isdigit()
    with pytest.raises(AuthenticationError, match="Noch 4"):
        codes.verify("Mama", wrong(code))
    assert codes.verify("mama", code).name == "Mama"                    # Groß/klein egal
    with pytest.raises(AuthenticationError, match="abgelaufen"):        # Code nur einmal gültig
        codes.verify("Mama", code)


def test_code_nach_5_fehlversuchen_gesperrt(fam):
    codes = fam.c.login_codes
    code = codes.issue("Papa", "papa@example.de", register=False)
    for _ in range(5):
        with pytest.raises(AuthenticationError):
            codes.verify("Papa", wrong(code))
    with pytest.raises(AuthenticationError, match="abgelaufen"):
        codes.verify("Papa", code)                                       # auch der richtige nicht mehr


def test_abgelaufener_code(fam):
    code = fam.c.login_codes.issue("Lena", "lena@example.de", register=False)
    fam.db.execute("UPDATE otp_codes SET expires_at = 0")
    with pytest.raises(AuthenticationError, match="abgelaufen"):
        fam.c.login_codes.verify("Lena", code)


def test_versandlimit(fam):
    fam.c.login_codes.issue("Mama", "mama@example.de", register=False)
    with pytest.raises(RateLimitError, match="warten"):
        fam.c.login_codes.issue("Mama", "mama@example.de", register=False)


def test_registrierung_legt_person_erst_nach_code_an(fam):
    code = fam.c.login_codes.issue("Tante Uschi", "uschi@example.de", register=True)
    assert fam.person("Tante Uschi") is None                             # vor Bestätigung: noch nichts
    p = fam.c.login_codes.verify("tante uschi", code)                    # klein getippt beim Code
    assert (p.name, p.email) == ("Tante Uschi", "uschi@example.de")
    assert fam.notifier.sent == [NewRegistration("Tante Uschi")]


def test_registrierung_uebernimmt_person_ohne_login(fam):
    fam.add_wish("Mama", "Oma", "Wolldecke")
    code = fam.c.login_codes.issue("Oma", "oma@example.de", register=True)
    oma = fam.c.login_codes.verify("Oma", code)
    assert oma.id == fam.ids["Oma"] and oma.email == "oma@example.de"
    assert fam.titles("Mama", "Oma") == ["Wolldecke"]


def test_registrierung_kann_bestehenden_login_nicht_kapern(fam):
    code = fam.c.login_codes.issue("Oma", "fremder@example.de", register=True)
    fam.c.family.set_email("Oma", "oma@example.de")                      # Oma war schneller
    with pytest.raises(ConflictError, match="jemand anderes"):
        fam.c.login_codes.verify("Oma", code)
    assert fam.person("Oma").email == "oma@example.de"


def test_registrierung_mit_vergebener_mail_scheitert(fam):
    code = fam.c.login_codes.issue("Tante Uschi", "lena@example.de", register=True)
    with pytest.raises(ConflictError, match="schon verwendet"):
        fam.c.login_codes.verify("Tante Uschi", code)
    assert fam.person("Tante Uschi") is None


def test_registrierung_braucht_familien_code(tmp_path):
    ohne = Family(tmp_path / "a.db")
    with pytest.raises(DomainError, match="Neu dabei"):
        ohne.c.login_codes.check_registration("Gisela", "g@example.de", "")

    mit = Family(tmp_path / "b.db", family_code="Tannenbaum")
    with pytest.raises(AuthenticationError):
        mit.c.login_codes.check_registration("Gisela", "g@example.de", "falsch")
    assert mit.c.login_codes.check_registration("Gisela", "g@example.de", " Tannenbaum ") == "Gisela"
    with pytest.raises(ConflictError, match="gibt es schon"):
        mit.c.login_codes.check_registration("mama", "neu@example.de", "tannenbaum")
    with pytest.raises(ConflictError, match="schon verwendet"):
        mit.c.login_codes.check_registration("Gisela", "LENA@example.de", "tannenbaum")


def test_session(fam):
    sessions = fam.c.sessions
    token = sessions.start(fam.person("Mama"))
    assert sessions.person(token).name == "Mama"
    assert sessions.person("falsch") is None
    sessions.end(token)
    assert sessions.person(token) is None
