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
