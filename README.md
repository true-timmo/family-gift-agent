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

Die Regeln (Reservierung, Überraschungsschutz, Berechtigungen) stehen im Code (`app/services/`),
nicht im Prompt – das Modell ruft nur Tools auf und kann sie nicht umgehen.

## Eigene KI anbinden (MCP)

Registrierte Familienmitglieder können die Wunschliste als **MCP-Server** in ihren eigenen KI-Assistenten
einbinden (Claude, ChatGPT, Cursor …). Den Zugang gibt es auf Nachfrage im Chat („Ich möchte einen MCP-Zugang“):
Der API-Schlüssel kommt **nur per E-Mail** (nie in den Chat), gilt 30 Tage (`API_KEY_DAYS`) und handelt mit
genau den Rechten seiner Besitzerin – Überraschungsschutz inklusive. Sperren: im Chat „Sperre meine KI-Zugänge“
oder `app.cli abmelden "<Name>"`.

- `POST /mcp` mit Header `Authorization: Bearer <Schlüssel>` (empfohlen)
- `POST /mcp/<Schlüssel>` für Programme, die nur eine Adresse kennen; der Schlüssel wird im Log geschwärzt,
  der Traefik-Router für `/mcp` schreibt kein Zugriffslog

## Aufbau

```
app/
  domain/      Fachbegriffe: Datenobjekte, Fehler, Benachrichtigungen, Eingabeprüfung (ohne Technik)
  storage/     SQLite: Database (Transaktionen) und je Tabelle ein Repository – nur SQL, keine Regeln
  services/    Die Regeln: Wünsche & Reservierungen, Login-Codes, Sitzungen, Einladungen, Familie
  agent/       Chat mit OpenRouter: Tool-Klassen, Presenter (was das Modell sieht), System-Prompt
  mail/        Mailer mit Jinja2-Vorlagen (templates/: je Mail .txt + .html), SMTP oder Log
  web/         FastAPI: Router, Abhängigkeiten, Cookie, IP-Sperre, Fehler → HTTP-Status
  container.py Setzt alles zusammen – hier entsteht jedes Objekt (Composition Root)
  main.py      Einstieg für uvicorn
  cli.py       Verwaltung auf der Kommandozeile
  static/      index.html, CSS, Icons; dist/ = gebündeltes Frontend (wird gebaut, nicht eingecheckt)
frontend/      Oberfläche in TypeScript mit lit-html-Templates, gebündelt mit esbuild
  src/views/   Login, Chat, Familie – je View eine Klasse (Logik) und eine *.templates.ts (Markup)
tests/         pytest: Regeln, Login, Einladungen, Admin, Mails, Web-API, Agent-Schleife
```

Abhängigkeiten zeigen nur nach innen: `web`/`agent`/`cli` → `services` → `storage` → `domain`.
Services bekommen alles, was sie brauchen, im Konstruktor – Tests tauschen so Datenbank,
Mailversand und Benachrichtigungen aus.

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
# Backend
docker compose build
docker run --rm -u 1000:1000 -v "$PWD":/src -w /src -e HOME=/tmp agent-agent \
  sh -c "pip install -q --user pytest httpx && python -m pytest -q tests"

# Frontend (Typprüfung, Tests, Build) – läuft auch automatisch bei docker compose build
docker run --rm -u 1000:1000 -v "$PWD":/src -w /src/frontend -e HOME=/tmp node:24-alpine \
  sh -c "npm ci && npm run check && npm test && npm run build"
```

Für lokale Tests ohne Mailversand: `MAIL_DEBUG=1` schreibt Codes und Mails ins Log.
