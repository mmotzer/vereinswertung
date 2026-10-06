# Quellen und Lizenzen

Die Anwendung wird unter GNU AGPL-3.0-or-later bereitgestellt. LICENSE enthält
die vollständige Lizenz. Der öffentliche Link `/source.zip` liefert den
entsprechenden Quellcode einschließlich der Build- und Betriebsdateien.
Laufzeitdaten, Datenbanken, Einrichtungsschlüssel und Passwörter sind ausgeschlossen.

`vereinswertung/rating.py` ist eine Python-Übertragung der nachstehenden Scala-Implementierungen.
Es handelt sich nicht um einen Betrieb des vollständigen Lichess-Servers.

## scalachess (MIT)

Copyright (c) 2012–2014 Thibault Duplessis; weitere Autoren siehe Originalprojekt.
Commit: `13e024a8dc510382031611c0e043ed787ecaa98e`
Quelle: https://github.com/lichess-org/scalachess/tree/13e024a8dc510382031611c0e043ed787ecaa98e

Übernommen/übertragen: RatingCalculator, GlickoCalculator, Modell, Farbe,
Konvergenzalgorithmus. Originalquellen und Tests in `reference/scalachess`;
die vollständige MIT-Lizenz steht in `reference/scalachess/LICENSE`.

## lila (AGPL-3.0-or-later)

Copyright Lichess contributors.
Commit: `a4c426af40e48b5cdbe5333ada6c8d687953d41d`
Quelle: https://github.com/lichess-org/lila/tree/a4c426af40e48b5cdbe5333ada6c8d687953d41d

Übertragen: Startwerte und Grenzen, Zeitfaktor aus Glicko.scala, skipDeviationIncrease
aus PerfsUpdater.scala, RatingRegulator (Gewinnfaktoren Blitz 1.005 / Rapid 1.015),
addOrReset/cap aus Perf.scala. Originalquellen und Lizenz in `reference/lila`.

Lichess-Marken, Logos, Oberfläche und vollständige Benutzer-/Betrugsverwaltung
sind nicht Bestandteil der Anwendung. Die eigene Oberfläche und der TRF-Import
sind neu erstellt.

## Technische Grenzen

TRF06/16-Spielersektion wie im bereitgestellten SWISS-CHESS-9.64-Export.
Unbekannte Ergebniskennzeichen werden abgewiesen. Andere TRF-Varianten können
Anpassungen benötigen. Keine Bot-Konten, Betrugsprüfung oder Rating-Erstattungen.
Alle Spieler werden als menschliche Spieler behandelt.

Da keine Partiezeiten exportiert werden, gilt pro Rundendatum 12:00 UTC.
Partien werden einzeln und Runden chronologisch verarbeitet. Innerhalb einer
Runde spielt jeder höchstens eine Partie; die Tabellenreihenfolge ist daher ohne
Einfluss auf Ratings. Turniere am selben Tag werden nach Importreihenfolge
verarbeitet; ein korrigierter Reimport mit gleichem Namen, Kategorie und Startdatum
behält seinen ursprünglichen Platz. Mehrtägige überlappende Turniere derselben Kategorie werden abgewiesen.
Diese Zeitregel ist eine Anpassung gegenüber realen Online-Abschlusszeiten.
