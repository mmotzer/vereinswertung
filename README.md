# Vereinswertung

Mobile Web-App für vereinsinterne Blitz- und Schnellschachwertungen auf einem NAS.
SWISS-CHESS exportiert TRF; diese App importiert die Partien und berechnet
Glicko-2 nach festgelegten Lichess-Quellen. Alle beginnen bei 1500. DWZ/Elo bleiben
unberücksichtigt. Geschützte Ranglisten, persönliche Turnierleiter-Zugänge,
Importvorschau, Rücknahme, Spielerprofile, CSV und Datenbanksicherungen.

## Lokal starten (Windows)

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe manage.py init-local
.\.venv\Scripts\python.exe app.py
```

Dann http://127.0.0.1:8080 öffnen. Über **App einrichten** einen Administrator
anlegen. Der Einrichtungsschlüssel steht in der lokalen `.env` (BOOTSTRAP_TOKEN).
Es gibt keine Standardpasswörter. `.env` nicht weitergeben. `init-local` legt
einen zufälligen Schlüssel an und deaktiviert Secure-Cookies ausschließlich
für die lokale HTTP-Vorschau. Auf dem NAS werden Secure-Cookies aktiviert.

## UGREEN NAS / Portainer

1. Projektdateien auf das NAS übertragen, z. B. in einen eigenen Ordner in Docker.
   `.env`, `.venv` und lokale `data` nicht übertragen; das Auslieferungsarchiv
   enthält diese Dateien nicht.
2. Image **auf demselben Docker-Host bauen**, den Portainer verwaltet:

   ```sh
   cd /dein/pfad/vereinswertung
   docker build -t vereinswertung:1.12 .
   ```

   Alternativ in Portainer unter **Images → Build a new image** den Projektordner
   als Build-Kontext (tar.gz) hochladen und `vereinswertung:1.12` als Namen verwenden.
   Das Image ist lokal und wird nicht in eine öffentliche Registry hochgeladen.
3. In Portainer **Stacks → Add stack**: Namen `vereinswertung`, Inhalt aus
   `compose.yaml` einfügen. Unter Environment variables `BOOTSTRAP_TOKEN` setzen.
   Einen zufälligen Schlüssel erzeugen, z. B.:

   ```sh
   python3 -c 'import secrets; print(secrets.token_urlsafe(32))'
   ```

   `PUBLIC_ORIGIN` später auf die öffentliche HTTPS-Adresse setzen.
4. Stack deployen. Das benannte Volume `vereinswertung-data` ist die zentrale
   Datenhaltung. Es wird bei einer Container-Aktualisierung nicht ersetzt.
   Netzwerk: `vereinswertung-net`; interne App-Adresse: `http://vereinswertung:8080`.
5. Vorhandenen Cloudflare-Tunnel-Container an `vereinswertung-net` anschließen.
   Alternativ den optionalen `compose.tunnel.yaml` als zweiten Stack deployen
   und dort `TUNNEL_TOKEN` setzen.
6. Im Cloudflare-Dashboard den öffentlichen Hostnamen auf den Service
   **HTTP → vereinswertung:8080** routen. Kein Router-Port muss geöffnet werden.
   Die Datenbank ist nicht über das Netzwerk veröffentlicht.
7. Öffentliche HTTPS-Adresse aufrufen, **App einrichten**, den zuvor gesetzten
   Einrichtungsschlüssel eingeben und Administratorname/Passwort wählen.
8. Unter **Zugänge** persönliche Turnierleiter-Konten erstellen. Turnierleiter
   dürfen eigene Importe zurücknehmen; Administratoren alle.

Die Einrichtung ist nur möglich, solange noch kein Konto existiert. Danach kann
BOOTSTRAP_TOKEN durch einen anderen zufälligen Wert ersetzt werden. Er wird
beim Start weiterhin benötigt, erlaubt aber keine erneute Einrichtung.
Die gesamte App erfordert eine Anmeldung. Ohne gültige Sitzung werden keine
Ranglisten, Spielerprofile, Turnierdaten oder CSV-Exporte ausgegeben, auch nicht
über direkte API-Aufrufe. Öffentlich bleiben nur Anmeldeoberfläche, statische
Dateien und der Status-Endpunkt (ohne Vereinsdaten). Die App-Konten übernehmen
den Schutz; ein zusätzlicher Cloudflare-Access-Login ist nicht erforderlich.

## Import und Zeitregel

- TRF-Datei maximal 1 MB, maximal 500 Spieler / 100 Runden.
- UTF-8 und Windows-1252; Spieler und Partien aus der festen TRF-Spielersektion.
- Kategorie bewusst auswählen; eine TRF enthält nicht zuverlässig die Bedenkzeit.
- Namen exakt normalisiert zuordnen, bei ähnlichen Namen bestehenden Spieler
  auswählen oder bewusst neu anlegen. Dauerhafte Spieler-IDs und Namensvarianten.
  Gleichnamige Teilnehmer müssen im Export eindeutig benannt sein.
- Für jede Runde ein Datum; ein eintägiges Turnier übernimmt das Datum für alle.
- Alle Partien desselben Rundentags erhalten rechnerisch 12:00 UTC. Keine erfundenen
  Minutenabstände. Runden werden nacheinander partieweise berechnet.
- Gleichzeitige Partien einer Runde haben unabhängige Spieler und werden aus
  denselben Werten vor der jeweiligen Partie berechnet.
- Mehrere Turniere gleicher Kategorie am selben Tag in tatsächlicher Reihenfolge
  importieren. Überlappende mehrtägige Turniere werden nicht unterstützt.
- Ältere Importe bewirken automatisch einen Replay sämtlicher aktiver Turniere.
- Vorschauen sind 30 Minuten gültig. Ändert ein anderer Leiter Daten, muss die
  Vorschau erneut berechnet werden. Bestätigung schreibt atomar.
- Freilose/kampflose Ergebnisse werden nicht gewertet. Fehlende oder
  widersprüchliche gespielte Ergebnisse blockieren den Import.
- Korrektur: ursprünglichen Import zurücknehmen und korrigierte TRF neu importieren.
  Bei gleichem Turniernamen, Kategorie und Startdatum behält ein korrigierter
  Import den ursprünglichen Platz in der Reihenfolge desselben Tages.
  Werden Name oder Datum verändert, wird ein neuer Platz vergeben.

## Berechnung

Siehe `NOTICE.md`, `reference/versions.json` und `docs/BERECHNUNG.md`.
Rating 1500 / RD 500 / Volatilität 0.09; tau 0.75; Farbe 11.782457;
Zeitfaktor 0.21436/Tag; keine pauschale RD-Erhöhung pro Partie.
Positive Änderungen werden wie in Lila mit 1.005 (Blitz) bzw. 1.015 (Rapid)
reguliert. Anzeige ganzer Ratings durch Abschneiden wie Lichess, intern volle Präzision.
Vorläufig ab RD 110. Die Vereinsliste zeigt auch vorläufige Wertungen; Lichess'
strengere Zulassung zur öffentlichen Bestenliste (RD ≤ 75 für Standardschach)
ist als Datenfeld vorhanden, wird aber nicht zum Verbergen eurer Spieler benutzt.

## Sicherung und Wiederherstellung

Tägliche konsistente SQLite-Sicherungen im Volume unter `/data/backups`;
die letzten 30 Dateien werden automatisch behalten. Administratoren können eine
aktuelle Sicherung herunterladen. Zusätzliche NAS-Sicherung auf ein anderes
Gerät einrichten: Ein Backup im selben Volume schützt nicht vor NAS-Ausfall.

```sh
python manage.py backup
```

Wiederherstellung **bei gestoppter App** mit dem mitgelieferten CLI:

```sh
# Stack-App in Portainer stoppen, Sicherung in das Volume kopieren.
docker run --rm -it --network none \
  -v vereinswertung-data:/data \
  -e DATABASE=/data/club.sqlite \
  vereinswertung:1.12 python manage.py restore --file /data/backups/DEINE_SICHERUNG.sqlite
```

Danach App wieder starten. Die vorhandene DB wird vorher gesichert; Sitzungen
werden entfernt, Benutzer melden sich neu an. Nicht die rohe laufende SQLite-Datei
kopieren; sie verwendet WAL. Die Backups enthalten Konten und Passwort-Hashes
und sind vertraulich.

Vergessenes Administratorpasswort: über eine NAS-/Container-Konsole
`python manage.py reset-admin --username DEIN_NAME` ausführen. Eingabe ist verdeckt.

## Prüfen

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
node --check static/app.js
docker compose -f compose.yaml config --quiet
```

Tests decken Lichess-Referenzwerte, Regulierung, Inaktivität, TRF, Replay,
Vorschau/Bestätigung, Zugriffsrechte, Doppelimporte und Sicherungen ab.
Keine Registrierung, E-Mail-Anbindung oder Passwort-Reset per E-Mail.

## Auslieferungsarchive erzeugen

`python package.py` erzeugt `artifacts/vereinswertung-nas.zip` zum Entpacken auf
dem NAS sowie `artifacts/vereinswertung-build.tar.gz` als Portainer-Build-Kontext.
Beide enthalten nur Quellcode, Dokumentation und Builddateien, keine Laufzeitdaten.

## Lizenz / Quellcode

AGPL-3.0-or-later; MIT-Hinweise der scalachess-Quellen bleiben erhalten.
Öffentlicher Quellcode-Download unter `/source.zip`. Bei Änderungen neue Quellen
mit ausliefern. Er enthält keine Datenbank oder Zugangsdaten. Für eigene zusätzliche
Quellcodedateien die Allowlist in `app.py` ergänzen.


### Lichess-Matches und Partielinks

Unter „Importieren“ zwei Lichess-Namen und den Spieltag (Europe/Berlin) eingeben und gemeinsame Partien laden. Alternativ bis zu 30 direkte Partielinks einfügen. In der Prüfung einzelne Partien auswählen und Konten bestehenden Vereinsspielern zuordnen. Der Turnierleiter bestätigt die vor der Partie vereinbarte Zustimmung beider Spieler für alle ausgewählten Partien. Vorschau und gemeinsames Speichern erfolgen atomar; ein Fehler speichert keine der Partien.

Nur abgeschlossene Standard-Blitz- und Schnellschachpartien menschlicher Konten werden gewertet, unabhängig vom Lichess-Rated-Modus. Die externen Ratings werden ignoriert. Lichess-Konten werden als eigene Aliase gespeichert; der Name des Vereinsspielers bleibt erhalten. Jede Partie erscheint als eigener zurücknehmbarer Import. Doppelte aktive Partie-IDs werden abgewiesen. Zurückgenommene Partien können erneut importiert werden.

Chronologie: Lichess-Partien verwenden `lastMoveAt` (Zeitpunkt des letzten Zuges, nicht zwingend Aufgabezeitpunkt). Die gesamte Wertung wird nach diesen Zeiten neu berechnet, einschließlich bereits gespeicherter Folgepartien. TRF-Partien verwenden weiterhin den angenommenen Zeitpunkt 12:00 UTC je Rundentag. Mehrtägige überlappende TRF-Turniere werden weiterhin abgewiesen. Die Zustimmung wird vom Turnierleiter bestätigt; eine eigenständige digitale Zustimmung der Spieler ist nicht implementiert.


### Smartphone und PWA

Die App kann auf Android und iPhone zum Startbildschirm hinzugefügt werden („App installieren“). HTTPS auf der produktiven Domain ist erforderlich. Auf dem Smartphone sitzt die Hauptnavigation unten; Formulare und Dialoge passen sich an kleine Bildschirme und Bildschirmränder an. Auf iOS erfolgt die Installation über Safari → Teilen → Zum Home-Bildschirm.

Der Service Worker speichert ausschließlich die allgemeine Offline-Seite und App-Symbole. Ranglisten, Spielernamen, Sitzungen, Importe und API-Antworten werden nicht für Offline-Zugriffe gespeichert. Die App benötigt für die Nutzung eine Internetverbindung. Neue Seiten und Skripte werden über das Netzwerk geladen; es gibt keinen dauerhaften Cache für App-Code oder Benutzerdaten.

Lichess-Importfelder und importierte Lichess-Partien (Übersicht, Details und Profilhistorie) sind ausschließlich für Turnierleiter und Administratoren sichtbar. Die Vereinswertung enthält weiterhin alle bestätigten Ergebnisse. Bestehende Lichess-Importe werden bei der Datenbankmigration automatisch erkannt.


### Mitgliederzugänge und Einreichungen

Administratoren erzeugen unter „Zugänge → Mitglied einladen“ einen persönlichen Registrierungscode. Er ist sieben Tage gültig, einmalig nutzbar und wird nur als Hash gespeichert. Mitglieder lösen ihn auf der Anmeldeseite ein, wählen Benutzername und Passwort selbst und erhalten ausschließlich die Rolle „Vereinsmitglied“. Alternativ kann ein Administrator einen Mitgliederzugang direkt anlegen. Eine optionale Empfängeradresse für Login-Anfragen lässt sich unter „Zugänge“ hinterlegen; der Mail-Link öffnet das Mailprogramm und versendet nicht automatisch.

Turnierleiter und Administratoren hinterlegen unter „Einreichungen“ die Lichess-Namen der Vereinsspieler. Bereits bekannte Zuordnungen aus früheren Importen werden übernommen. Mitglieder wählen beim Einreichen nur Spieltag und zwei Vereinsspieler und bestätigen die vorherige Zustimmung beider Spieler. Sie sehen ausschließlich ihre eigenen Einreichungen und deren Status. Eine Einreichung verändert keine Wertung.

Die Turnierleitung wählt „Partien prüfen“, lädt die gemeinsamen Partien vom angegebenen Tag und führt Spielerzuordnung, Partieauswahl und Vorschau durch. Erst „Import bestätigen“ speichert die ausgewählten Partien und genehmigt die Einreichung atomar. Ablehnungen erhalten eine Begründung. Mitglieder können keine direkten TRF- oder Lichess-Importe ausführen und keine fremden Lichess-Partiedetails abrufen. Vor Erweiterung der bestehenden Kontotabelle wird automatisch eine Datenbanksicherung erstellt; IDs und bestehende Zugänge bleiben erhalten.

### Vorbereitete Vereinskonten

Eine private `club-roster.json` im Deployment enthält nur `name` und vierstellige `club_number`. Sie wird nicht im öffentlichen Quellarchiv veröffentlicht. Beim ersten Start werden vorhandene Spieler samt Wertungen zugeordnet und gesperrte Mitgliedskonten angelegt; vorher wird eine Datenbanksicherung erstellt. Wiederholte Starts legen keine weiteren Konten an. Unter **Zugänge** wählt der Administrator einen Spieler und erstellt dessen persönlichen, sieben Tage gültigen Einmalcode. Das Mitglied übernimmt damit seinen vorbereiteten Zugang und wählt Benutzername und Passwort selbst. Ein neuer Code ersetzt einen noch offenen alten Code. DWZ und Elo werden nicht übernommen.
