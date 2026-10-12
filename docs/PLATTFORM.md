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

Es wird eine Kopie erstellt. Bestehende Spieler, Wertungen und Zugänge bleiben erhalten; Sitzungen und offene Importvorschauen der Kopie werden entfernt. Integrität und Fremdschlüssel der Quelle werden vor dem Kopieren geprüft. Der importierte Verein erhält vorerst einen vom Betreiber verwalteten Altbestandszugang ohne Zahlungsabo. Die Quelldatenbank bleibt unverändert. Vor Umleitung der bestehenden Adresse zuerst die Kopie prüfen und während des endgültigen Umzugs Importe pausieren.

## Betrieb und Sicherungen

`compose.platform.yaml` ist eine separate Docker-Konfiguration ohne offenen Host-Port. Den freigegebenen Cloudflare-Tunnel mit dem Plattformnetz verbinden und auf Port 8080 routen. Die Landingpage-Route ist seit dem 12. Oktober 2026 öffentlich eingerichtet; Vereins-Wildcard-Routing und HTTPS müssen vor der Aufnahme von Vereinen separat eingerichtet und getestet werden. Bestehendes Vereinsvolume nicht durch das Plattformvolume ersetzen.

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

Vor der Wiederherstellung werden auch Manifesttypen, eindeutige Vereinskennungen, Prüfsummenformat sowie benötigte Tabellen und Spalten geprüft. Eine strukturell unvollständige Sicherung wird vor dem Anlegen von Vereinsdateien im Ziel abgewiesen.

Das Ziel der Wiederherstellung muss neu und leer sein. Alte Anmeldesitzungen werden verworfen. Bezahlte Vereine bleiben bis zum aktuellen Abo-Abgleich pausiert; dieser benötigt die gültige Stripe-Konfiguration. Automatische tägliche Backups zählen nur vollständig abgeschlossene Snapshots mit `complete.json`. Die Abschlussmarkierung wird erst nach erfolgreicher Prüfung von Prüfsummen, Datenbankintegrität und Struktur veröffentlicht. Quellen werden ausschließlich lesend geöffnet; fehlende Quelldatenbanken werden nicht neu angelegt. Der laufende Plattformprozess gleicht Abos stündlich ab. Dieser Prozess ist für eine Instanz ausgelegt.

Die ausführliche Bewertung und verbleibenden Startbedingungen stehen in [KONZEPT.md](KONZEPT.md).

## Betriebsdiagnose

```powershell
python platform_manage.py --data data/platform doctor
```

Liest vorhandene Datenbanken, ohne Vereine anzulegen oder Wertungen zu ändern.
Der JSON-Bericht enthält keine Schlüssel, E-Mail-Adressen oder Spielernamen.
Exit-Code 1 bedeutet einen erkannten Fehler, Exit-Code 0 bedeutet keine
erkannten Fehler; Warnungen bleiben im Bericht sichtbar.

Geprüft werden HTTPS-Konfiguration, vorhandene Zahlungsvariablen und
Rechtstextdateien, Vereinsregister, Integrität und Fremdschlüssel der
provisionierten Vereinsdatenbanken sowie aktive Administratoren mit gültigen Berechtigungen zur Zugangsverwaltung. Die jüngste
abgeschlossene lokale Sicherung wird einschließlich Prüfsummen geprüft; ab
48 Stunden Alter erscheint eine Warnung. Fehlende Sicherungen und fehlende
Subdomain-/Proxy-Konfiguration werden ebenfalls ausgewiesen.

Der Befehl validiert keine Stripe-Schlüssel beim Anbieter und prüft weder
DNS/TLS noch die rechtliche Qualität der Texte. Externe Sicherungskopien,
Wiederherstellungsproben und echte Zahlungsabläufe müssen separat nachgewiesen
werden. Ein grüner Bericht ist keine allgemeine Freigabe zum Verkauf. Die
Konfiguration muss wie beim Plattformprozess über Umgebungsvariablen gesetzt
sein; der Befehl liest keine separate env-Datei automatisch.

Der öffentliche `/api/health`-Endpunkt prüft einen lesenden Zugriff auf das
Vereinsregister. Bei fehlender oder unlesbarer Datenbank liefert er HTTP 503
ohne Dateipfade oder Vereinsdaten und ohne eine Ersatzdatenbank anzulegen.
Er ersetzt weder die vollständige Integritätsprüfung durch `doctor` noch eine
externe Alarmierung. Der Einzelvereins-Healthcheck prüft entsprechend die
Kontotabelle seiner Datenbank.

## Öffentliche Vorschau – 12. Oktober 2026

Landingpage und TRF-Probeimport sind unter
https://vereinswertung.marcmotzer.com erreichbar. Separater Portainer-Stack
`vereinsplattform` (73), Image `vereinswertung:1.24`, Einstieg
`python club_platform.py`, eigenes Volume `vereinsplattform-data`, eigenes
Netz `vereinsplattform-net` und bestehendes Tunnelnetz `robin5_tunnel-net`.
Die Cloudflare-Route im Tunnel `robin` zeigt auf
`http://vereinsplattform-platform-1:8080`. Der Container ist healthy.

`LEGAL_READY=false`; Zahlungsvariablen sind nicht gesetzt. Die öffentliche
Beispielberechnung und der deaktivierte Zahlungsbutton wurden im Browser
geprüft. Keine Vereinskonten oder Abos wurden dabei angelegt. Die bestehende
SK1912-App unter wertung.marcmotzer.com bleibt getrennt.

`TENANT_DOMAIN=vereinswertung.marcmotzer.com` bereitet eigene Vereinsadressen
vor. Die Wildcard-Route, DNS und ein gültiges Zertifikat für diese zusätzlichen
Unterdomains sind noch nicht eingerichtet oder geprüft. Zusammen mit
Rechtstexten und Zahlungs-Testlauf ist das Voraussetzung für die Freigabe
der Vereinsregistrierung. Der aktuelle öffentliche Dienst ist eine Vorschau.

## Anwendungshärtung – 12. Oktober 2026

Bei konfigurierter öffentlicher Adresse werden fremde Hostnamen abgewiesen;
localhost und 127.0.0.1 bleiben für interne Healthchecks erlaubt. Schreibende
Anfragen werden auch für PUT, PATCH und DELETE auf ihren Ursprung geprüft.
Browserheader sperren fremde Fensterverknüpfungen und Ressourcen-Einbettung
sowie Kamera, Mikrofon und Standortzugriff. CSP und Anmeldung bleiben aktiv.

Die festgelegten Laufzeitpakete wurden mit pip-audit 2.10.1 geprüft: zum
Prüfzeitpunkt keine bekannten gemeldeten Sicherheitslücken. GitHub CI prüft
diese Pakete bei Änderungen und täglich. Der Prüfbericht ist lokal unter
.runtime/security-audit.json gespeichert und nicht veröffentlicht. Das ist
keine Garantie gegen unbekannte Schwachstellen.

MFA bei Betreiberkonten, externe Sicherungskopien, Alarmierung und ein
unabhängiger Sicherheitstest bleiben separat nachzuweisen. Die öffentliche
Registrierung und Abos bleiben weiterhin deaktiviert.
