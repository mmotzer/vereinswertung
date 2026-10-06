# Vereinswertung

Vereinsinterne Schachwertung für Bullet, Blitz und Schnellschach. Die mobile
Web-App verwendet Glicko-2 auf Grundlage festgehaltener Lichess-Quellen;
DWZ und Elo werden nicht übernommen. Ergebnisse kommen aus TRF-Dateien,
Lichess, Chess.com oder manuellen Einträgen. Mitglieder reichen Partien ein,
die Turnierleitung genehmigt sie. Vereinsdaten erfordern eine Anmeldung.

Die Einzelvereins-App läuft mit Flask, Waitress und SQLite auf einem NAS.
Eine getrennte Vereinsplattform mit eigenen Vereinsdatenbanken und
Abonnement-Anbindung ist als Pilot vorhanden.

## Entwickeln

Python 3.13 und Node.js 22 verwenden. Node wird für JavaScript-Syntaxprüfungen benötigt.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe manage.py init-local
.\.venv\Scripts\python.exe app.py
```

Anschließend http://127.0.0.1:8080 öffnen. Der Einrichtungsschlüssel steht in
`.env`; keine Standardpasswörter. Linux/macOS verwenden `.venv/bin/python`.

```powershell
.\.venv\Scripts\python.exe tools/check.py
```

Der gemeinsame Check prüft Python-Stil, JavaScript-Syntax, Tests und die
Importierbarkeit des ausgelieferten Quellarchivs. Er verwendet Testdaten und
schreibt Archive ausschließlich nach `artifacts/`.

## Orientierung

- [Zusammenarbeiten und Reviews](CONTRIBUTING.md)
- [Architektur und Verzeichnisstruktur](docs/ARCHITEKTUR.md)
- [Installation, NAS, Backups und Bedienung](docs/BETRIEB.md)
- [Berechnungsregeln](docs/BERECHNUNG.md)
- [Vereinsplattform betreiben](docs/PLATTFORM.md)
- [Dokumentationsübersicht](docs/README.md)

## Lizenz

AGPL-3.0-or-later; zusätzliche MIT-Hinweise stehen in [NOTICE.md](NOTICE.md).
`python package.py` erstellt Quell- und NAS-Archive anhand einer expliziten
Allowlist. Datenbanken, persönliche Mitgliederlisten und Zugangsdaten gehören
weder in Git noch in öffentliche Archive.
