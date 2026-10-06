# Architektur

## Verzeichnisse

| Pfad | Aufgabe |
| --- | --- |
| `app.py` | Flask-App, HTTP-Routen, Anmeldung und Quellarchiv-Allowlist |
| `club_platform.py` | Plattform-App und Vereinsrouting |
| `manage.py`, `platform_manage.py` | Administrationsbefehle |
| `package.py` | Auslieferungsarchive |
| `vereinswertung/` | Fachlogik und Datenhaltung |
| `static/` | Browseroberfläche, PWA und Druckansicht |
| `tests/` | automatisierte Verhaltenstests und Browser-Testfixture |
| `tools/` | gemeinsame Entwicklungsprüfungen |
| `docs/` | Architektur, Berechnung und Betrieb |
| `reference/` | festgehaltene unveränderte upstream Quellen |
| `.github/` | CI und Pull-Request-Vorlage |
| `data/`, `.runtime/`, `artifacts/`, `.venv/` | lokale, nicht versionierte Laufzeitdateien |

## Fachmodule

`rating` berechnet Glicko-2; `trf`, `lichess_import` und `chesscom_import`
lesen und validieren Ergebnisse. `storage` hält Daten und verarbeitet Replay.
`permissions` definiert Rechte, `member_features` Einladungen und Einreichungen,
`club_roster` Mitgliederzuordnung und `progression` den persönlichen Vereinsweg.
`billing` verarbeitet Abos, `trial` den isolierten Testimport.

HTTP-Einstiegspunkte setzen diese Module zusammen. Neue Fachlogik gehört ins
Paket und wird über `from vereinswertung ...` importiert. Die root Startskripte
bleiben für Docker und bestehende Betriebsbefehle erhalten.

SQLite bleibt die zentrale Datenquelle; bestätigte Importe werden atomar
verarbeitet. Die Plattform nutzt getrennte Vereinsdatenbanken. Rechte werden
serverseitig geprüft, nicht allein durch ausgeblendete UI-Elemente.

## Grenzen und Änderungen

`app.py` und `static/app.js` sind noch große Dateien. Eine weitere Zerlegung
soll in eigenen, kleinen Änderungen mit Verhaltenstests erfolgen.
Diese Aufräumung verändert keine Wertungsregeln oder Datenbankschemata.
Neue auszuliefernde Dateien müssen explizit in `public_source_files()` in
`app.py` aufgenommen werden. Niemals ganze Laufzeitordner veröffentlichen.
