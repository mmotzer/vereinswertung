# Vereinsplattform – Pilot

Die Einzelvereins-App bleibt mit `python app.py` unverändert nutzbar. Der neue Einstieg ist `python club_platform.py` (Port 8082). Die Plattform ist ein Pilot und wird getrennt vom bestehenden Produktionsstack betrieben.

Jeder Verein liegt unter `/v/<vereinskürzel>/`, hat eine eigene SQLite-Datenbank, eigene Administratoren, Mitglieder und Wertungen. Anmeldesitzungen und PWA-Speicher verwenden den Vereinsbereich. Ein Login gilt nur für diesen Verein. Daten liegen in `PLATFORM_DATA/tenants/<zufallskennung>/club.sqlite`; die zentrale Registrierung in `platform.sqlite`. Neue Vereine bekommen keine Ludwigshafener Mitgliederliste. Administratoren können im Bereich „Zugänge“ eigene Mitglieder vorbereiten: pro Zeile `0001; Nachname, Vorname`, anschließend persönliche Übernahmecodes erzeugen.

## Monats- und Jahresabos

Es sind noch keine Preise festgelegt. Ohne vollständige Konfiguration bleibt der Zahlungsbutton deaktiviert. Für einen Testlauf zuerst Stripe-Testschlüssel und zwei wiederkehrende Testpreise in EUR einrichten. Eine sichere Konfigurationsvorlage liegt in `platform.env.example`. Vor Livebetrieb den Ablauf inklusive Kündigung, fehlgeschlagener Zahlung und Wiederaufnahme in Stripe testen.

Umgebungsvariablen: `PUBLIC_ORIGIN` (HTTPS-Adresse), `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_PRICE_MONTH`, `STRIPE_PRICE_YEAR`, `PLATFORM_DATA`, `TRUSTED_PROXY_IPS` (ausschließlich tatsächliche Tunnel-IP). Schlüssel auf dem Host speichern, nicht in Git oder Chat. `LEGAL_DIR` enthält die vom Betreiber bereitgestellten HTML-Dateien `terms.html`, `privacy.html`, `imprint.html`. Erst wenn diese fertig sind, `LEGAL_READY=true` setzen. Keine Rechtsvorlagen werden automatisch erstellt.

Stripe Checkout übernimmt die Zahlung, die Preisübersicht liest die konfigurierten Stripe-Preise. Der Webhook `/api/platform/webhook` verarbeitet `checkout.session.completed`, `checkout.session.async_payment_succeeded`, `customer.subscription.updated` und `customer.subscription.deleted`. Signierte Ereignisse werden geprüft und dedupliziert. Ein Verein wird erst nach bestätigter Zahlung freigeschaltet. Der aktuelle Abostatus wird bei Stripe abgerufen, damit verspätet gelieferte Ereignisse nicht den alten Zustand wiederherstellen. Pausierte Abos behalten Lese- und Exportzugriff; schreibende Aktionen sind gesperrt. Administratoren öffnen „Abo verwalten“ im Kontodialog. Das Stripe-Kundenportal muss zuvor mit Kündigung und Zahlungsverwaltung konfiguriert werden.

## Bestehenden Verein übernehmen

Zuerst eine aktuelle Datenbank-Sicherung herunterladen. Dann lokal oder im separaten Plattformcontainer:

```powershell
python platform_manage.py --data data/platform import-club --file backup.sqlite --slug sk1912 --name "SK1912 Ludwigshafen" --email "betreiber@example.org" --admin marc
```

Es wird eine Kopie erstellt. Bestehende Spieler, Wertungen und Zugänge bleiben erhalten; Sitzungen der Kopie werden abgemeldet. Der importierte Verein erhält vorerst einen vom Betreiber verwalteten Altbestandszugang ohne Zahlungsabo. Die Quelldatenbank bleibt unverändert. Vor Umleitung der bestehenden Adresse zuerst die Kopie prüfen und während des endgültigen Umzugs Importe pausieren.

## Betrieb und Sicherungen

`compose.platform.yaml` ist eine separate Docker-Konfiguration ohne offenen Host-Port. Den freigegebenen Cloudflare-Tunnel mit dem Plattformnetz verbinden und auf Port 8080 routen. Noch keine neue öffentliche Route wurde eingerichtet. Bestehendes Vereinsvolume nicht durch das Plattformvolume ersetzen.

```powershell
python platform_manage.py --data data/platform backup
```

Sichert Registry und alle provisionierten Vereinsdatenbanken unter `data/platform/backups/`. Snapshots sind pro Datenbank konsistent; für einen gemeinsamen Wiederherstellungspunkt Neuregistrierung und Zahlungs-Webhooks kurz pausieren. Sicherungen regelmäßig zusätzlich außerhalb des NAS speichern und Wiederherstellung testen. Beim Start über `python club_platform.py` werden täglich automatische Gesamtsicherungen erstellt. Die Aufbewahrung und zusätzliche externe Kopien verwaltet der Betreiber; der Pilot löscht keine alten Plattform-Sicherungen automatisch.

## Vor dem bezahlten Livebetrieb

Preise, Betreiberangaben und neue Plattformadresse festlegen. Stripe-Testlauf einschließlich Webhooks und Kundenportal durchführen. Backupjob und Wiederherstellung prüfen. Ein zusätzlicher Verein muss mit unabhängigen Mitgliedern und Importen end-to-end getestet werden. Erst danach die öffentliche Registrierung und Livezahlungen freischalten. Die bisherige SK1912-Produktion wird durch den lokalen Umbau nicht verändert.

## Rollen und individuelle Rechte

Unter „Zugänge → Rolle und Rechte“ können Berechtigungen einzeln erlaubt, verweigert oder aus der Rollenvorlage übernommen werden. Individuelle Vorgaben bleiben bei einem Rollenwechsel bestehen. „Zugänge, Rollen und Rechte verwalten“ erlaubt das Vergeben aller Rechte und sollte nur vertrauten Personen gegeben werden. Mindestens ein aktiver Administrator mit diesem Recht bleibt zwingend erhalten. Nicht beanspruchte Mitgliedskonten werden erst nach ihrer Übernahme bearbeitet.

Rechte umfassen Lesen, Einreichen, direkte Importe, Genehmigung, Rücknahme eigener Importe, Mitglieder und Codes, Zugänge, Einstellungen, Export/Druck, Sicherungen, Protokoll und Abos. Administratoren mit Rücknahmerecht dürfen auch fremde Importe zurücknehmen. Rechte werden in der jeweiligen Vereinsdatenbank gespeichert und bei jeder Anfrage serverseitig geprüft. Änderungen an Zugängen werden protokolliert und beenden deren bestehende Anmeldesitzungen.

## Probeimport und Einrichtung

Die öffentliche Startseite bietet unter „Ohne Anmeldung ausprobieren“ ein fiktives Turnier oder eine eigene TRF-Datei. Es werden keine Konten angelegt und keine realen Vereinsdaten verändert. Grenzen: 1 MB, 200 Spieler, 2000 Partien, 30 Runden; zwei Berechnungen gleichzeitig und zehn Versuche je 15 Minuten pro erfasster Quelladresse. Hinter einem Tunnel muss TRUSTED_PROXY_IPS korrekt gesetzt sein, sonst teilen Besucher dessen Limit. Die temporäre Datenbank wird nach der Berechnung entfernt. Registrierung ist unter `/start` getrennt; Testergebnisse werden nicht übernommen.

## Getrennte Vereinsadressen

Optional `TENANT_DOMAIN=clubs.example.org` setzen. Vereine liegen dann unter `https://<kürzel>.clubs.example.org/`. Zuvor Wildcard-DNS, gültiges TLS und Tunnel-Routing für diese Hosts zum selben Plattformdienst einrichten. PUBLIC_ORIGIN bleibt die Plattformadresse; sie darf keine Vereins-Subdomain unter TENANT_DOMAIN sein. Sitzungs-Cookies bleiben hostgebunden, POST-Anfragen müssen vom passenden Ursprung kommen. Alte `/v/`-GET-Adressen werden weitergeleitet; Schreibanfragen dort verlangen eine neue Anmeldung. Ohne TENANT_DOMAIN bleibt der Pfadbetrieb bestehen und teilt einen Browser-Ursprung.

## Sicherungen prüfen und wiederherstellen

```powershell
python platform_manage.py --data data/platform verify-backup --snapshot data/platform/backups/<snapshot>
python platform_manage.py --data data/platform-restored restore --snapshot data/platform/backups/<snapshot>
python platform_manage.py --data data/platform-restored sync-billing
```

Das Ziel der Wiederherstellung muss neu und leer sein. Alte Anmeldesitzungen werden verworfen. Bezahlte Vereine bleiben bis zum aktuellen Abo-Abgleich pausiert; dieser benötigt die gültige Stripe-Konfiguration. Automatische tägliche Backups zählen nur vollständig abgeschlossene Snapshots mit `complete.json`. Der laufende Plattformprozess gleicht Abos stündlich ab. Dieser Prozess ist für eine Instanz ausgelegt.

Die ausführliche Bewertung und verbleibenden Startbedingungen stehen in [KONZEPT.md](KONZEPT.md).
