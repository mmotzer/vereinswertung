# Berechnung für Turnierleiter

Jeder Spieler startet mit 1500 Blitz- und 1500 Schnellschachpunkten. DWZ, Elo und
Lichess-Werte bleiben unberücksichtigt. Die hohe anfängliche Unsicherheit (RD 500)
erlaubt anfangs große Änderungen. Mit weiteren Partien wird die Wertung verlässlicher.

Nach Turnierende wird die TRF hochgeladen. Die App wertet jede gespielte Partie
in Rundenreihenfolge aus. Beide Spieler werden mit den Werten vor dieser Partie
berechnet. Die neuen Werte gelten für ihre nächste Partie.

Es gibt keine feste Punktzahl pro Sieg. Gegnerstärke, RD, Volatilität und Farbe
bestimmen die Änderung. Ein Remis kann Punkte gewinnen oder kosten. Gewinner
und Verlierer müssen nicht dieselbe Anzahl an Punkten gewinnen/verlieren.

Spielpausen verändern die Wertungszahl nicht. Sie erhöhen die Unsicherheit und
damit die mögliche Änderung nach der Rückkehr. Das gilt pro Kategorie separat.
Das Turnierdatum zählt, nicht der Tag des Uploads.

Freilose und kampflose Ergebnisse zählen nicht als Partien. Ergebnisse und
Spielerzuordnungen sind vor der Bestätigung zu prüfen. Erst die Bestätigung
speichert den Import. Neue Spieler werden dann automatisch angelegt.

Die verbindliche Quelle ist die Datenbank auf dem NAS. Eine Korrektur erfolgt
durch Rücknahme und erneuten Import; nachfolgende Wertungen werden neu berechnet.

Die Rating-Implementierung wurde aus festen Lichess-Quellen übertragen, samt
Startwerten, Zeitfaktor, Farbe und Regulierung. TRF-Dateien enthalten keine
Abschlusszeiten: je Rundentag verwenden wir 12:00 UTC. Das ist eine feste
Zeitannahme und keine Rekonstruktion realer Lichess-Partiezeiten.

Eine Vereinswertung von 1800 ist nicht mit 1800 auf Lichess gleichzusetzen:
Die Spielergruppe ist eine andere.
