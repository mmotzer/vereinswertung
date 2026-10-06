# Gemeinsam entwickeln

Die Konventionen orientieren sich an Googles
[Python Style Guide](https://google.github.io/styleguide/pyguide.html) und
[kleinen, fokussierten Änderungen](https://google.github.io/eng-practices/review/developer/small-cls.html).
Ruff setzt unsere konkrete Auswahl automatisch um; dies ist keine vollständige
Durchsetzung aller Google-Regeln.

## Arbeitsablauf

1. `main` aktualisieren: `git switch main`, anschließend `git pull --ff-only`.
2. Eine eigene Branch für genau eine Aufgabe erstellen. Codex verwendet `codex/`.
3. Umfang vorab miteinander abstimmen, besonders bei Änderungen an `app.py`.
4. Kleine Commits schreiben. Verschieben/Formatieren und Verhaltensänderungen trennen.
5. `python tools/check.py` mit dem eingerichteten Entwicklungsinterpreter ausführen.
6. Pull Request gegen `main` öffnen: Problem, Ergebnis und Prüfung beschreiben.
7. Die andere Person prüft die Änderung; anschließend zusammenführen.

Keine fremde Branch überschreiben und kein Force-Push auf `main`.
Ein Review ist unser Arbeitsablauf; eine technische GitHub-Branchsperre wird
nicht durch diese Dokumentation aktiviert. Produktionsdeployment ist ein
separater Schritt nach Review und Sicherung.

## Stil und Prüfungen

Vier Leerzeichen in Python, 80 Zeichen Zielbreite, UTF-8 und LF.
Automatisch formatieren und Imports ordnen:

```sh
python -m ruff check --fix app.py club_platform.py manage.py platform_manage.py package.py vereinswertung tests tools
python -m ruff format app.py club_platform.py manage.py platform_manage.py package.py vereinswertung tests tools
python tools/check.py
```

Neue Funktionen brauchen aussagekräftige Tests für Verhalten und Fehlerfälle.
Reine Formatierung benötigt keine neuen Tests. Netzwerkdienste in Tests mocken;
keine Produktionskonten oder echten Vereinsdaten verwenden.

## Daten und Auslieferung

Schemaänderungen müssen bestehende IDs und Daten erhalten. Migration und
Wiederherstellung mit Testdaten prüfen und Betriebsanleitung aktualisieren.
Neue auszuliefernde Dateien in `app.py` zur Quellcode-Allowlist hinzufügen.
Keine `.env`, SQLite-Dateien, Schlüssel oder privaten Mitgliederlisten committen.
Lizenzhinweise und unveränderte Referenzquellen erhalten.
