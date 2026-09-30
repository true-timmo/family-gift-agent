"""Verwaltung auf der Kommandozeile (im Container):

  docker compose exec agent python -m app.cli personen
  docker compose exec agent python -m app.cli person-neu "Oma"                           # ohne Login
  docker compose exec agent python -m app.cli person-neu "Mama" --email mama@example.de  # mit Login
  docker compose exec agent python -m app.cli email-setzen "Mama" neu@example.de
  docker compose exec agent python -m app.cli email-setzen "Mama" --entfernen            # Login sperren
  docker compose exec agent python -m app.cli abmelden "Mama"                            # alle Geräte abmelden
  docker compose exec agent python -m app.cli mail-test du@example.de                    # Mailversand prüfen
  docker compose exec agent python -m app.cli person-loeschen "Julian"                   # endgültig (als Admin)

Normalerweise registrieren sich Familienmitglieder selbst (Name + Mail + Familien-Code).
"""
import argparse
import asyncio
import sqlite3

from . import db, mailer


def main() -> None:
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
    a = sub.add_parser("abmelden", help="Person auf allen Geräten abmelden")
    a.add_argument("name")
    d = sub.add_parser("person-loeschen", help="Person endgültig löschen (im Namen des Admins)")
    d.add_argument("name")
    m = sub.add_parser("mail-test", help="Test-Mail mit Beispielcode verschicken")
    m.add_argument("an")
    args = p.parse_args()

    if args.cmd == "mail-test":
        try:
            asyncio.run(mailer.send_code(args.an, "Test", "123456", db.OTP_MINUTES))
        except Exception as e:
            raise SystemExit(f"Versand fehlgeschlagen: {type(e).__name__}: {e}")
        print(f"Test-Mail an {args.an} verschickt.")
        return

    conn = db.connect()
    try:
        if args.cmd == "personen":
            for r in db.list_persons(conn):
                print(f"{r['name']:<25} {r['email'] or '– (kein Login)'}")
        elif args.cmd == "person-neu":
            db.add_person(conn, args.name, args.email)
            print(f"'{args.name}' angelegt.")
        elif args.cmd == "email-setzen":
            db.set_email(conn, args.name, None if args.entfernen else args.email)
            print(f"Mail-Adresse für '{args.name}' {'entfernt' if args.entfernen else 'gesetzt'}.")
        elif args.cmd == "person-loeschen":
            admin = db.admin_person(conn)
            if not admin:
                raise SystemExit("Fehler: ADMIN_EMAIL gehört zu keiner Person – ohne Admin kein Löschen.")
            if input(f"'{args.name}' endgültig löschen? (ja/nein) ").strip().lower() != "ja":
                raise SystemExit("Abgebrochen.")
            r = db.delete_person(conn, admin["id"], args.name)   # CLI: ohne Mail-Benachrichtigungen
            print(f"'{r['name']}' gelöscht: {r['wuensche_geloescht']} Wünsche, "
                  f"{r['reservierungen_freigegeben']} Reservierungen freigegeben.")
        elif args.cmd == "abmelden":
            person = db.get_person(conn, args.name) or db.find_person(conn, args.name)
            n = conn.execute("DELETE FROM sessions WHERE person_id = ?", (person["id"],)).rowcount
            print(f"{n} Sitzung(en) von '{person['name']}' beendet.")
    except (db.WishError, sqlite3.IntegrityError) as e:
        raise SystemExit(f"Fehler: {e}")


if __name__ == "__main__":
    main()
