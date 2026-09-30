# Geschenke-Agent 🎁

Ein KI-Assistent für die Familie, der Geschenkwünsche sammelt und doppelte Geschenke verhindert.
Familienmitglieder schreiben ihm im Web-Chat, was sie sich wünschen („Ich wünsche mir …“),
fragen nach den Wünschen anderer („Was wünscht sich Mama?“) und reservieren Geschenke
(„Ich besorge Papa die Pfanne“) – die anderen sehen dann „besorgt Mama“ und können es nicht mehr auswählen.

## Funktionen

- **Chat** mit einem Sprachmodell über [OpenRouter](https://openrouter.ai) (Tool-Calling, Streaming, Ausweichmodelle bei Überlastung)
- **Wunschlisten** mit Shop, Link und Preis; eintragen, ändern, entfernen – auch für Personen ohne eigenen Zugang
- **Reservierungen**: doppelte Reservierung ausgeschlossen, auch bei gleichzeitigen Anfragen;
  in den Listen anderer steht, wer was besorgt
- **Überraschungsschutz**: Wer sich etwas wünscht, erfährt nie, ob es schon jemand besorgt
- **Benachrichtigung per Mail**, wenn ein bereits reservierter Wunsch entfernt wird
- **Einladungen per Mail**: Name und Adresse legt der Einladende fest, ein Klick auf den Link genügt
- **Anmeldung per Einmal-Code (OTP)** per Mail, keine Passwörter; Familien-Code als optionaler Ausweg
- **Familienübersicht** mit Status (registriert / eingeladen / noch nicht dabei), Info-Mail bei Neuregistrierung
- **Hilfeseiten** in einfacher Sprache, Handy-tauglich, als App auf dem Startbildschirm speicherbar

Die Regeln (Reservierung, Überraschungsschutz, Berechtigungen) stehen im Code (`app/db.py`),
nicht im Prompt – das Modell ruft nur Tools auf und kann sie nicht umgehen.

## Aufbau

```
app/
  main.py      Web-Server (FastAPI): Login, Chat (Server-Sent Events), Familienliste
  agent.py     Gespräch mit OpenRouter, Tool-Aufrufe, Streaming
  tools.py     Tools, die das Modell aufrufen darf
  db.py        SQLite: Personen, Wünsche, Reservierungen, Codes, Sessions
  mailer.py    Mailversand per SMTP
  cli.py       Verwaltung auf der Kommandozeile
  static/      Oberfläche (HTML/CSS/JS, ohne Build-Schritt)
tests/         pytest-Tests für die Regeln
```

## Einrichtung

Voraussetzungen: Docker mit Compose, ein Reverse Proxy mit TLS (hier: Traefik über Docker-Labels).

```bash
cp .env.example .env && chmod 600 .env   # Werte eintragen
# in compose.yaml die Domain im Traefik-Label anpassen
docker compose up -d --build
```

Die Datenbank liegt in `./data/` und bleibt bei Updates erhalten.

## Betrieb

```bash
docker compose logs -f                                         # Logs
docker compose exec agent python -m app.cli personen            # Personen anzeigen
docker compose exec agent python -m app.cli person-neu "Oma"    # Person ohne Zugang anlegen
docker compose exec agent python -m app.cli mail-test du@example.de
docker compose exec agent python -m app.cli --help              # alle Befehle
```

## Tests

```bash
docker compose build
docker run --rm -v "$PWD":/src -w /src -e HOME=/tmp agent-agent \
  sh -c "pip install -q --user pytest && python -m pytest -q tests"
```

Für lokale Tests ohne Mailversand: `MAIL_DEBUG=1` schreibt Codes und Mails ins Log.
