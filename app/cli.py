"""Verwaltung auf der Kommandozeile (im Container):

  docker compose exec agent python -m app.cli personen
  docker compose exec agent python -m app.cli person-neu "Oma"                           # ohne Login
  docker compose exec agent python -m app.cli person-neu "Mama" --email mama@example.de  # mit Login
  docker compose exec agent python -m app.cli email-setzen "Mama" neu@example.de
  docker compose exec agent python -m app.cli email-setzen "Mama" --entfernen            # Login sperren
  docker compose exec agent python -m app.cli abmelden "Mama"                            # alle Geräte abmelden
  docker compose exec agent python -m app.cli mail-test du@example.de                    # Mailversand prüfen
  docker compose exec agent python -m app.cli person-loeschen "Julian"                   # endgültig (als Admin)

Normalerweise kommen Familienmitglieder per Einladung dazu (Familie → Jemanden einladen).
"""
import argparse
import asyncio
import sqlite3

from .config import Settings
from .container import Container
from .domain.errors import DomainError
from .domain.notifications import NullNotifier
from .services import LoginCodeService


class AdminCli:
    """Ein Befehl = eine Methode `cmd_<befehl>` (Bindestriche als Unterstriche)."""

    def __init__(self, c: Container):
        self._c = c

    def run(self, args: argparse.Namespace) -> None:
        getattr(self, "cmd_" + args.cmd.replace("-", "_"))(args)

    def cmd_personen(self, args) -> None:
        for person in self._c.family.persons():
            print(f"{person.name:<25} {person.email or '– (kein Login)'}")

    def cmd_person_neu(self, args) -> None:
        self._c.family.add(args.name, args.email)
        print(f"'{args.name}' angelegt.")

    def cmd_email_setzen(self, args) -> None:
        self._c.family.set_email(args.name, None if args.entfernen else args.email)
        print(f"Mail-Adresse für '{args.name}' {'entfernt' if args.entfernen else 'gesetzt'}.")

    def cmd_abmelden(self, args) -> None:
        person = self._c.family.require(args.name)
        print(f"{self._c.sessions.end_all(person)} Sitzung(en) von '{person.name}' beendet.")

    def cmd_person_loeschen(self, args) -> None:
        admin = self._c.admins.admin()
        if not admin:
            raise SystemExit("Fehler: ADMIN_EMAIL gehört zu keiner Person – ohne Admin kein Löschen.")
        if input(f"'{args.name}' endgültig löschen? (ja/nein) ").strip().lower() != "ja":
            raise SystemExit("Abgebrochen.")
        r = self._c.removals.remove(admin, args.name)
        print(f"'{r.name}' gelöscht: {r.wishes_deleted} Wünsche, {r.reservations_released} Reservierungen freigegeben.")

    def cmd_mail_test(self, args) -> None:
        try:
            asyncio.run(self._c.mailer.send_login_code(args.an, "Test", "123456", LoginCodeService.VALID_MINUTES))
        except Exception as e:
            raise SystemExit(f"Versand fehlgeschlagen: {type(e).__name__}: {e}")
        print(f"Test-Mail an {args.an} verschickt.")


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m app.cli")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("personen", help="Alle Personen anzeigen")
    n = sub.add_parser("person-neu", help="Person anlegen")
    n.add_argument("name")
    n.add_argument("--email", help="Mail-Adresse für die Anmeldung per Code")
    e = sub.add_parser("email-setzen", help="Mail-Adresse ändern oder entfernen")
    e.add_argument("name")
    g = e.add_mutually_exclusive_group(required=True)
    g.add_argument("email", nargs="?")
    g.add_argument("--entfernen", action="store_true", help="Mail entfernen (kein Login mehr möglich)")
    sub.add_parser("abmelden", help="Person auf allen Geräten abmelden").add_argument("name")
    sub.add_parser("person-loeschen", help="Person endgültig löschen (im Namen des Admins)").add_argument("name")
    sub.add_parser("mail-test", help="Test-Mail mit Beispielcode verschicken").add_argument("an")
    return p


def main() -> None:
    args = parser().parse_args()
    # Kommandozeile: ohne Mail-Benachrichtigungen (z.B. beim Löschen einer Person)
    cli = AdminCli(Container(Settings.from_env(), notifier=NullNotifier()))
    try:
        cli.run(args)
    except (DomainError, sqlite3.IntegrityError) as e:
        raise SystemExit(f"Fehler: {e}")


if __name__ == "__main__":
    main()
