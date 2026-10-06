# Gemeinsam entwickeln

Die Konventionen orientieren sich an Googles
[Python Style Guide](https://google.github.io/styleguide/pyguide.html) und
[kleinen, fokussierten Änderungen](https://google.github.io/eng-practices/review/developer/small-cls.html).
Ruff setzt unsere konkrete Auswahl automatisch um; dies ist keine vollständige
Durchsetzung aller Google-Regeln.

## Arbeitsablauf

1. `main` aktualisieren: `git switch main`, anschließend `git pull --ff-only`.
2. Marc hat direkte Pushes auf `main` autorisiert. Für seine Änderungen ist kein Pull Request erforderlich. Optionale Arbeitsbranches von Codex verwenden `codex/`.
3. Umfang vorab miteinander abstimmen, besonders bei Änderungen an `app.py`.
4. Kleine Commits schreiben. Verschieben/Formatieren und Verhaltensänderungen trennen.
5. `python tools/check.py` mit dem eingerichteten Entwicklungsinterpreter ausführen.
6. Geprüfte Änderungen direkt auf `main` pushen. Zuvor den Remote-Stand prüfen; keine Änderungen anderer Personen überschreiben.
7. Für größere gemeinsame Arbeiten können beide Entwickler freiwillig einen Pull Request mit gegenseitigem Review verwenden.

Keine fremde Branch überschreiben und kein Force-Push auf `main`.
Ein Review ist optional; eine technische GitHub-Branchsperre wird nicht durch
diese Dokumentation aktiviert. Produktionsdeployment ist ein separater Schritt
nach Prüfung und Sicherung.

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
