"""Anmeldung per Einmal-Code, Registrierung per Familien-Code und Sitzungen."""
import time

import pytest

from app.domain.errors import AuthenticationError, ConflictError, DomainError, RateLimitError
from app.domain.notifications import NewRegistration
from tests.conftest import Family


def wrong(code):
    return "000000" if code != "000000" else "111111"


def test_code_login_bekannte_person(fam):
    codes = fam.c.login_codes
    code = codes.issue("Mama", "mama@example.de", register=False).code
    assert len(code) == 6 and code.isdigit()
    with pytest.raises(AuthenticationError, match="Noch 4"):
        codes.verify("Mama", wrong(code))
    assert codes.verify("mama", code).name == "Mama"                    # Groß/klein egal
    with pytest.raises(AuthenticationError, match="abgelaufen"):        # Code nur einmal gültig
        codes.verify("Mama", code)


def test_code_nach_5_fehlversuchen_gesperrt(fam):
    codes = fam.c.login_codes
    code = codes.issue("Papa", "papa@example.de", register=False).code
    for _ in range(5):
        with pytest.raises(AuthenticationError):
            codes.verify("Papa", wrong(code))
    with pytest.raises(AuthenticationError, match="abgelaufen"):
        codes.verify("Papa", code)                                       # auch der richtige nicht mehr


def test_abgelaufener_code(fam):
    code = fam.c.login_codes.issue("Lena", "lena@example.de", register=False).code
    fam.db.execute("UPDATE login_codes SET expires_at = 0")
    with pytest.raises(AuthenticationError, match="abgelaufen"):
        fam.c.login_codes.verify("Lena", code)


def test_versandlimit(fam):
    fam.c.login_codes.issue("Mama", "mama@example.de", register=False)
    with pytest.raises(RateLimitError, match="warten"):
        fam.c.login_codes.issue("Mama", "mama@example.de", register=False)


def test_registrierung_legt_person_erst_nach_code_an(fam):
    code = fam.c.login_codes.issue("Tante Uschi", "uschi@example.de", register=True).code
    assert fam.person("Tante Uschi") is None                             # vor Bestätigung: noch nichts
    p = fam.c.login_codes.verify("tante uschi", code)                    # klein getippt beim Code
    assert (p.name, p.email) == ("Tante Uschi", "uschi@example.de")
    assert fam.notifier.sent == [NewRegistration("Tante Uschi")]


def test_registrierung_uebernimmt_person_ohne_login(fam):
    fam.add_wish("Mama", "Oma", "Wolldecke")
    code = fam.c.login_codes.issue("Oma", "oma@example.de", register=True).code
    oma = fam.c.login_codes.verify("Oma", code)
    assert oma.id == fam.ids["Oma"] and oma.email == "oma@example.de"
    assert fam.titles("Mama", "Oma") == ["Wolldecke"]


def test_registrierung_kann_bestehenden_login_nicht_kapern(fam):
    code = fam.c.login_codes.issue("Oma", "fremder@example.de", register=True).code
    fam.c.family.set_email("Oma", "oma@example.de")                      # Oma war schneller
    with pytest.raises(ConflictError, match="jemand anderes"):
        fam.c.login_codes.verify("Oma", code)
    assert fam.person("Oma").email == "oma@example.de"


def test_registrierung_mit_vergebener_mail_scheitert(fam):
    code = fam.c.login_codes.issue("Tante Uschi", "lena@example.de", register=True).code
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


# --- Anmelde-Knopf in der Mail ----------------------------------------------------------

def test_anmelde_link_meldet_einmal_an(fam):
    codes = fam.c.login_codes
    issued = codes.issue("Mama", "mama@example.de", register=False)
    assert codes.link_owner(issued.link_token) == "Mama"           # nur anzeigen, noch nicht verbraucht
    assert codes.link_owner(issued.link_token) == "Mama"
    assert codes.verify_link(issued.link_token).name == "Mama"
    assert codes.link_owner(issued.link_token) is None
    with pytest.raises(AuthenticationError, match="abgelaufen"):
        codes.verify_link(issued.link_token)
    with pytest.raises(AuthenticationError):                       # Code ist damit auch verbraucht
        codes.verify("Mama", issued.code)


def test_anmelde_link_abgelaufen_oder_falsch(fam):
    codes = fam.c.login_codes
    first = codes.issue("Lena", "lena@example.de", register=False)
    fam.reset_mail_limit()
    second = codes.issue("Lena", "lena@example.de", register=False)
    assert codes.link_owner(first.link_token) == "Lena"             # neuer Code ersetzt den alten nicht
    assert codes.link_owner("quatsch") is None and codes.link_owner("") is None
    fam.db.execute("UPDATE login_codes SET expires_at = 0")
    assert codes.link_owner(second.link_token) is None and codes.link_owner(first.link_token) is None


def test_anmelde_link_schliesst_registrierung_ab(fam):
    issued = fam.c.login_codes.issue("Tante Uschi", "uschi@example.de", register=True)
    assert fam.c.login_codes.verify_link(issued.link_token).email == "uschi@example.de"
    assert isinstance(fam.notifier.sent[-1], NewRegistration)


def test_versandlimit_sagt_wann_es_wieder_geht(fam):
    limiter = fam.c.login_codes
    assert limiter.resend_allowed_at("Mama") == 0
    fam.c.login_codes.issue("Mama", "mama@example.de", register=False)
    wait = limiter.resend_allowed_at("Mama") - int(time.time())
    assert 58 <= wait <= 60
    with pytest.raises(RateLimitError, match="noch [0-9]+ Sekunden warten"):
        fam.c.login_codes.issue("Mama", "mama@example.de", register=False)
    for minutes in (2, 3, 4, 5):    # 5 pro Stunde: danach bis zum Ablauf der ältesten warten
        fam.db.execute("UPDATE otp_sends SET sent_at = sent_at - 61")
        fam.c.login_codes.issue("Mama", "mama@example.de", register=False)
    fam.db.execute("UPDATE otp_sends SET sent_at = sent_at - 61")
    with pytest.raises(RateLimitError, match="Minuten"):
        fam.c.login_codes.issue("Mama", "mama@example.de", register=False)


# --- Mehrere Codes gleichzeitig -----------------------------------------------------------

def three_codes(fam, name="Mama", email="mama@example.de"):
    codes = []
    for _ in range(3):
        fam.reset_mail_limit()
        codes.append(fam.c.login_codes.issue(name, email, register=False))
    return codes


@pytest.mark.parametrize("which", [0, 1, 2])
def test_jeder_von_drei_codes_funktioniert(fam, which):
    issued = three_codes(fam)
    assert fam.c.login_codes.verify("Mama", issued[which].code).name == "Mama"
    for other in issued:                                              # danach sind alle erledigt
        with pytest.raises(AuthenticationError, match="abgelaufen"):
            fam.c.login_codes.verify("Mama", other.code)


def test_jeder_code_laeuft_nach_seinen_10_minuten_ab(fam):
    first, second, _ = three_codes(fam)
    fam.db.execute("UPDATE login_codes SET expires_at = 0 WHERE code_hash = (SELECT code_hash FROM login_codes "
                   "ORDER BY id LIMIT 1)")
    with pytest.raises(AuthenticationError, match="stimmt nicht"):
        fam.c.login_codes.verify("Mama", first.code)                  # abgelaufen → zählt wie falsch
    assert fam.c.login_codes.verify("Mama", second.code).name == "Mama"


def test_fehlversuche_gelten_fuer_alle_codes(fam):
    issued = three_codes(fam)
    taken = {i.code for i in issued}
    wrong_code = next(c for c in (f"{n:06d}" for n in range(1000)) if c not in taken)
    for left in (4, 3, 2, 1):
        with pytest.raises(AuthenticationError, match=f"Noch {left}"):
            fam.c.login_codes.verify("Mama", wrong_code)
    with pytest.raises(AuthenticationError, match="neuen anfordern"):
        fam.c.login_codes.verify("Mama", wrong_code)
    with pytest.raises(AuthenticationError, match="abgelaufen"):
        fam.c.login_codes.verify("Mama", issued[0].code)              # 5 Fehlversuche: alle gesperrt
    fam.reset_mail_limit()
    fresh = fam.c.login_codes.issue("Mama", "mama@example.de", register=False)
    assert fam.c.login_codes.verify("Mama", fresh.code).name == "Mama"   # neuer Code: neue Versuche


def test_alte_code_tabelle_wird_abgeloest(tmp_path):
    from app.storage.database import Database
    db = Database(str(tmp_path / "alt.db"))
    db.execute("CREATE TABLE otp_codes (name TEXT PRIMARY KEY)")
    db = Database(str(tmp_path / "alt.db"))
    tables = {r[0] for r in db.all("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert "otp_codes" not in tables and "login_codes" in tables
