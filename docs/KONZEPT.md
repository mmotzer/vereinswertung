# Gesamtkonzept und Umsetzung – 6. Oktober 2026

## Produktentscheidung

Vereinswertung macht gemeinsame Schachaktivität sichtbar: interne Spielstärke je Disziplin, nachvollziehbare Ergebnisse und persönlicher Fortschritt. DWZ und FIDE-Elo bleiben unberührt. Der Nutzen muss vor dem Abo sichtbar werden. Ob andere Vereine dafür bezahlen, ist mit echten Pilotvereinen zu prüfen; Begeisterung eines Vereins ersetzt diesen Nachweis nicht.

Die empfohlene Reihenfolge ist: anonymes Beispiel oder eigener TRF-Probeimport → Ergebnis ansehen → eigenen Vereinsbereich anlegen → Monats- oder Jahresabo → Mitglieder vorbereiten → Turnierleitung einrichten → erstes Turnier → persönliche Zugänge verteilen. Preise bleiben offen, bis der Betreiber sie festlegt. Der Probeimport wird nicht automatisch in ein späteres Vereinskonto übertragen.

## Umgesetzte Verbesserungen

- Die Produktseite erklärt den Nutzen vor der Registrierung. Ein Probeimport verwendet die echte Berechnung in einer isolierten temporären Datenbank; Startwert 1500, keine bestehenden Vereinsdaten. Danach wird die temporäre Datenbank entfernt. Dateigröße, Spieler, Runden, Partien, parallele Berechnungen und Anfragen pro Zeitfenster sind begrenzt. Mehrtägige Turniere benötigen passende Rundendaten.
- Mobile Testergebnisse erscheinen als lesbare Spielerkarten. Ergebnisse erhalten Fokus und werden automatisch sichtbar. Beispielnamen sind fiktiv.
- Vereinsadministratoren sehen eine einklappbare Einrichtungshilfe mit Mitgliedern, Turnierleitung, erstem Import und übernommenen Konten. Mitglieder ohne ausdrücklichen Seitenlink starten bei ihrem persönlichen Fortschritt. Rechte bleiben mit Rollenvorlagen einfach; individuelle Vorgaben stehen in einer optionalen Detailansicht.
- Alle Berechtigungen werden serverseitig geprüft. Mitglieder können Partien vorschlagen; eine berechtigte Turnierleitung genehmigt sie. Externe Kontonamen und Partie-Links bleiben für gewöhnliche Mitglieder verborgen.
- Zahlungsereignisse werden signaturgeprüft und dedupliziert. Die Verarbeitung ist innerhalb des einzelnen Plattformprozesses serialisiert. Ein stündlicher Abgleich des aktuellen Stripe-Abos korrigiert verpasste Ereignisse. Unbekannte Abos werden nicht als Vereinsabos übernommen. Grundlage für die Ereignisbehandlung: [Stripe-Webhooks](https://docs.stripe.com/webhooks).
- Sicherungen gelten erst mit vollständigem Manifest als abgeschlossen. Prüfsummen, SQLite-Integrität, Fremdschlüssel und Vereinsregister werden vor der Wiederherstellung geprüft. Wiederherstellung erfolgt ausschließlich in einen neuen Datenordner; alte Sitzungen und Vorschauen werden ungültig. Bezahlte Vereine bleiben bis zum aktuellen Stripe-Abgleich pausiert.
- Optional kann jeder Verein eine eigene HTTPS-Subdomain erhalten. Datenbanken und Sitzungen bleiben getrennt; zusätzlich trennt der Browser die Ursprünge. Der bisherige Pfadbetrieb bleibt verfügbar. DNS und TLS werden durch diese Codeänderung nicht eingerichtet.

## Motivation und Wertung

Die Glicko-Zahl beschreibt geschätzte Spielstärke, das Level beschreibt Aktivität. XP erhöhen niemals die Wertungszahl. Vorläufige Zahlen bleiben gekennzeichnet. Persönliche Entwicklung und Teilnahme stehen für Mitglieder im Vordergrund; Ranglisten bleiben erreichbar. Keine täglichen Pflichtserien, Kaufboni oder garantierten Motivationsversprechen. Trainer sollten Wertungen als ergänzenden Hinweis nutzen; wenige Partien und unterschiedlich starke Gegner begrenzen die Aussagekraft. TRF enthält Rundenreihenfolge, aber nicht zwingend genaue Partiezeiten: vollständige zeitliche Gleichheit mit Lichess darf nicht versprochen werden.

## Technische Grenze des Piloten

Pro Verein gibt es eine SQLite-Datenbank; das zentrale Register enthält Zuordnung und Zahlungsstatus. Der Pfadbetrieb teilt einen Browser-Ursprung und ist keine vollständige Ursprungstrennung. Für den öffentlichen bezahlten Betrieb wird die optionale Subdomain-Trennung empfohlen. Der aktuelle Betrieb besteht aus einem Prozess mit mehreren Threads. Der Zahlungs-Lock ist nicht zwischen mehreren Prozessen wirksam. Vor mehreren Instanzen wären zentrale Verarbeitung und verteilte Koordination notwendig; derzeit ist kein umfassender Infrastrukturwechsel begründet.

Die Sicherungen sind je Datenbank konsistent. Für einen zeitlich gemeinsamen Gesamtstand müssen Registrierung, Zahlungsänderungen und Importe während der Sicherung pausieren. NAS-Sicherungen allein schützen nicht vor dem Verlust des NAS; externe Kopien, Aufbewahrung und regelmäßige Wiederherstellungsproben sind Betreiberaufgaben.

## Noch vor dem bezahlten Start erforderlich

Preise und Betreiberadresse festlegen, Stripe-Testschlüssel und Preise konfigurieren, Zahlungsablauf einschließlich Kündigung, Zahlungsfehler und Wiederaufnahme end-to-end testen. Tatsächliche Rechtstexte bereitstellen und erst dann Registrierung freigeben. Wildcard-DNS/TLS und Tunnel für getrennte Vereinsadressen konfigurieren. Einen zweiten Verein mit eigenen Mitgliedern und Importen durch den vollständigen Ablauf führen. Last, Fehlerprotokolle und externe Sicherungen im vorgesehenen Betrieb prüfen. Selbstbedienungs-Passwortwiederherstellung und E-Mail-Verifikation sind noch nicht Teil dieses Piloten; das bestehende administrative Verfahren muss vor Verkauf konkret organisiert oder ergänzt werden.

## Validierung und Auslieferung

86 automatisierte Tests erfolgreich, darunter Probeimport, Datenisolation, Rechte, getrennte Browser-Ursprünge, Zahlungsabgleich und Wiederherstellung. Die mobile Produktseite und das Beispielergebnis wurden in Chrome geprüft, einschließlich fehlendem horizontalem Überlauf. Echte Zahlungen wurden nicht ausgeführt. Die bestehende Produktion wurde bei dieser Überarbeitung nicht verändert.
