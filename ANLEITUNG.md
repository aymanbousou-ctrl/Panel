# FlipRadar 2.2 für Windows und Python 3.15

## Start und Umstieg

1. Beende das alte FlipRadar-Fenster. Rechtsklick auf die neue ZIP-Datei → **Alle extrahieren**.
2. Öffne im entpackten Ordner **START.cmd** per Doppelklick. FlipRadar nutzt bevorzugt deinen installierten Python 3.15 und enthält die benötigten Bibliotheken. Beim Start entfällt die Paketinstallation.
3. Beim ersten Start übernimmt FlipRadar die Einstellungen, Watchlist und eine Kopie der Datenbank aus **%LOCALAPPDATA%\FlipRadarV2**, andernfalls aus der erkannten V1.2 unter Dokumente oder Downloads. Die neue Version hat einen eigenen Datenordner **%LOCALAPPDATA%\FlipRadarV21**. Eigene Watchlist-Einträge bleiben erhalten, auch deaktivierte Einträge. Bei einer frischen Installation richtest du Telegram mit **EINSTELLUNGEN.cmd** ein.

| Doppelklick | Funktion |
|---|---|
| **START.cmd** | Startet die Suche. Im geöffneten Fenster siehst du Suchfortschritt, Ausfälle, die nächste Runde und den Versand. Beenden mit Strg+C. |
| **EINSTELLUNGEN.cmd** | Öffnet die Einstellungen für Einzelkauf, Los, Gesamtkapital, Rabatt, B-Ware, Marge, Telegram und eBay. Schließe dazu zuerst das Suchfenster. Nach dem Speichern startet die Suche. |
| **BESTAND.cmd** | Erfasst Einkauf und Verkauf in einem eigenen Fenster, auch während der Suche. Die Zahlen gelten ab dem nächsten Durchlauf. |
| **TRENDS.cmd** | Öffnet die nach jeder Runde aktualisierte Tabelle in deiner Standardanwendung für CSV. Schließe die Tabelle nach dem Lesen, wenn Excel die Datei für Änderungen sperrt. |

## Was FlipRadar sucht

Die Standardliste startet mit **138 Modell-Suchen**, darunter 105 neue. Dazu gehören u. a. Makita DDF484, Bosch-Werkzeuge, Fluke-Messgeräte, Switch Lite, Xbox Series S, iPhone 13 mini, Pixel 9 Pro, VW Polo, Toyota Corolla, Sony A6400, GoPro, Dyson und Garmin. Du kannst im Datenordner weitere Modelle in **watchlist.yaml** ergänzen oder mit **enabled: false** ausschalten.

Je Runde sind bis zu **30 Modell-Suchen** vorgesehen. Bei größerem Katalog rotieren 15 Plätze durch die gesamte Liste. Die übrigen Plätze bevorzugen Modelle mit steigenden eigenen Verkäufen und positivem mittlerem Gewinn, steigenden importierten Verkäufen, schnellen eigenen Verkäufen oder wiederkehrenden Kaufgelegenheiten. Preisalarme können eintreffen, sobald das jeweilige Produkt erneut geprüft wird. Bei den 138 Standardmodellen kommt jedes innerhalb von höchstens zehn abgeschlossenen Runden an die Reihe. Eine Runde hat zunächst fünf Minuten Zielintervall. Langsame oder pausierte Quellen verlängern die Zeit bis zum nächsten erfolgreichen Abruf.

Zusätzlich läuft pro Runde eine breitere Suche, beispielsweise nach Akkuschraubern, Kopfhörern oder Toyota-Modellen. FlipRadar erkennt Modellbezeichnungen in zehn hinterlegten Produktfamilien. Taucht ein weiteres Modell in mindestens vier verschiedenen Inserat-IDs mit Erstsichtungen an mindestens zwei Tagen innerhalb von 28 Tagen auf, wird es ab der nächsten Runde mitgesucht. So können bis zu 50 zusätzliche Modelle in die Rotation kommen. Die Schwelle dient der Auswahl von Suchbegriffen. Für Geldbeträge und Telegram gelten danach die gleichen Regeln wie bei anderen Modellen. Mit **discovery: false** lässt sich die Erkennung deaktivieren. Einzelne entdeckte Namen können unter **disabled_models** in der Konfiguration ausgeschlossen werden.

## Wie du Trends und Wiederverkaufschancen liest

**TRENDS.cmd** zeigt je Modell die Zahl erstmals gesehener Inserate und die Tage mit erfolgreicher Suche für die letzten sieben Kalendertage und die Vorwoche. Die erste Woche kann durch die Ersterfassung vieler bereits bestehender Inserate besonders groß aussehen. Eine ausgefallene Quelle kann die Zahlen senken. Neu eingestellte oder verschwundene Anzeigen belegen keinen Verkauf.

Für die Nachfrage vergleicht FlipRadar deine eingetragenen Verkäufe der beiden Wochen. Eine optionale Verkaufspreis-Datei **sales_csv** wird separat ausgewiesen. Für die **30-Tage-Verkaufsquote** zählen nur Einheiten, deren Einkauf mindestens 30 Tage zurückliegt. Der Zähler enthält die davon innerhalb von 30 Tagen verkauften Einheiten, der Nenner auch die Ladenhüter. Ab zehn solchen Einheiten zeigt FlipRadar die Quote und die absoluten Zahlen an, beispielsweise **60 % (6/10)**. Bis dahin steht **offen**. Diese Quote beschreibt deinen bisherigen Absatz je Modell. Sie erfasst weder die gesamte Marktnachfrage noch die besondere Absatzchance einer einzelnen B-Ware-Einheit.

**BESTAND.cmd** verteilt beim Kauf die eingegebenen tatsächlichen Gesamtkosten centgenau auf die Stückzahl. Bei einem Verkauf wählst du die einzelne Einheit und erfasst den Erlös nach Gebühren, Versand und weiteren Verkaufskosten. Erfasse auch langsam verkäufliche Käufe. In der Trendtabelle steht der mediane realisierte Gewinn je Stück aus den letzten 90 Tagen. Wer bestehende Daten importiert, kann die semikolongetrennte Datei **Bestand.csv** im Datenordner bearbeiten. Je Einheit gibt es eine eindeutige ID, exakten Produktnamen, Einkaufsdatum und Einstand in CHF. Verkaufsdatum und Nettoerlös bleiben bis zum Verkauf leer. Beim externen Bearbeiten das Bestandsfenster schließen.

## Einzelkauf, Mengenrabatt und B-Ware

Du kannst **Maximaler Kaufpreis**, **Maximaler Gesamtpreis je Los** und **Gesamtkapital inkl. Bestand** unabhängig einstellen. Der Einstand noch offener Einheiten wird vom Gesamtkapital abgezogen. Das Los darf mehr als dein Einzelkauflimit kosten. Deine Beispielgrenze von **30 % Rabatt je Stück** ist voreingestellt. Eine Telegram-Meldung löst weder einen Kauf noch eine Kapitalreservierung aus. Mehrere gleichzeitige Angebote können zusammen das freie Budget übersteigen.

Beispiel für fünf Geräte mit vergleichbaren Einzelangeboten zu 100 CHF und einem eindeutigen Paketpreis von 350 CHF:

| Rechnung mit den Standardwerten | CHF |
|---|---:|
| Einkauf je Einheit | 70 |
| Geschätzter Gesamterlös nach Abschlag auf Angebotspreise (5 × 92) | 460 |
| Verkaufsgebühren (10 %) | −46 |
| Versand-/Verkaufspauschale (5 × 10) | −50 |
| Einkaufspreis des Loses | −350 |
| Geschätzter Nettogewinn | **14** |

Das ergibt 4 % Gewinn auf den Einsatz. Bei deiner Schwelle von 20 % bleibt der Alarm aus. Für einen Alarm müssen außerdem genügend passende Einzelangebote vorliegen, bei Standardkonfiguration mindestens acht. Ein Los zählt nie als Vergleichspreis für ein Einzelgerät. Es braucht eine klare Stückzahl im Titel und einen ausdrücklich erkennbaren Gesamtpreis. Unklare Mischpakete oder Stückpreise werden ausgefiltert. Titel und Beschreibungen sind je nach Quelle unterschiedlich ausführlich. Prüfe Menge, Lieferumfang und Preis im Originalinserat.

Gekennzeichnete **B-Ware**, Retouren und generalüberholte Ware erhalten eine eigene Vergleichsgruppe. Die zusätzliche Reserve beträgt anfangs **20 CHF je Einheit** und kann angepasst werden. Ungetestete oder als defekt erkannte Geräte werden ausgefiltert. Bei Handys berücksichtigt FlipRadar die angegebene Speicherkapazität, bei PS5 das Laufwerk, bei Autos Baujahrgruppen von drei Jahren und Kilometergruppen von 50.000 km. Fehlen diese Angaben, gibt es für das Angebot keinen Deal-Alarm. Motorisierung, Wartung, Akkuqualität und tatsächlicher Reparaturbedarf können den Wert weiter verändern.

## Quellen, Telegram und Daten

Tutti und Ricardo verwenden die öffentliche Suchergebnisseite. Bei Ricardo zählen erkannte Sofortkaufpreise. eBay.de verwendet die Browse API für Festpreisartikel mit Standort Deutschland. Dafür brauchst du freigeschaltete Produktionszugangsdaten in den Einstellungen. Beim Start prüft **D** die eingerichteten Quellen und sendet bei eingerichteter Verbindung einen Telegram-Test. Kleinanzeigen ist standardmäßig deaktiviert. Falls du eine schriftliche Freigabe hast, kannst du **kleinanzeigen_schriftliche_freigabe: true** setzen und die Quelle in **platforms** aufnehmen.

Ein Erstabruf je Produkt und Quelle sammelt den vorhandenen Bestand. Neue passende Inserate und relevante Preissenkungen können bei späteren Abrufen einen Alarm auslösen. Dazu müssen Preis, Datenlage, Budget und Mindestgewinn passen. Ein 403 pausiert die Quelle für eine Stunde. Andere Quellen laufen weiter. Bei 429 berücksichtigt die Suche die mitgeteilte Wartezeit. Ein tägliches lokales Limit begrenzt die eBay-Suchen des Radars. Es zählt keine externen Anwendungen auf demselben Schlüssel. Bei fehlgeschlagenem Telegram-Versand erfolgt ein neuer Versuch bei erneuter Sichtung und erfolgreicher Neubewertung.

Die Schweizer Preisbasis bilden gewöhnlich mindestens acht passende Einzelangebote von Ricardo und Tutti aus 30 Tagen. Der Marktwert aus Angebotspreisen erhält standardmäßig einen Faktor von 0,92. Die optionale CSV **sales_csv** aus V2 mit den Spalten **sale_id,product,sold_on,price_chf** erfasst bestätigte Bruttopreise. Passende Verkaufspreise oder manuelle Referenzen können bei einfachen Standardartikeln in die Rechnung einfließen. Bei B-Ware und unterschiedenem Variantenmerkmal verlangt das Programm passende Vergleichsinserate. Eurobeträge werden zum eingestellten Wechselkurs umgerechnet. Versand, Gebühren, Kaufnebenkosten in Deutschland und B-Ware-Reserve sind konfigurierbare Annahmen. Die angegebenen Höchstpreise beziehen sich auf diese Annahmen.

Telegram-Schlüssel und eBay-Zugangsdaten bleiben in der lokalen Konfiguration. Für eine Fehlersuche reichen die relevanten Zeilen aus **flipradar.log**. Teile keine Konfigurationsdatei mit Zugangsdaten. Bei der Übernahme werden offene Meldungen neu bewertet. V1-Ricardo-Daten mit möglichen Gebotspreisen dienen erst nach erneuter Sichtung als Vergleich. Beim ersten Profilvergleich sammelt V2.1 zusätzliche Varianten- und Zustandsmerkmale.

Die mitgelieferten Bibliotheken und Lizenzen stehen unter **vendor**. Die automatisierten Tests im Ordner **tests** laufen offline. Für Entwickler lautet der Befehl im entpackten Ordner `py -3.15 -m unittest discover -s tests`.

## Weitere Quellen (nur sammeln)

Zusätzlich zu Tutti, Ricardo und eBay gibt es **Marktplaats** (NL), **Vinted.de**, **Subito** (IT), **Wallapop** (ES) und **Leboncoin** (FR). Sie speichern Preise, senden aber nie einen Telegram-Alarm und fließen nicht in den Schweizer Marktwert ein. Zum Einschalten trägst du den Namen unter `platforms:` in der `config.yaml` im Datenordner ein, zum Beispiel `- marktplaats`.

- **Marktplaats und Vinted** lesen die öffentliche Suchseite, ohne Kosten. Bei Marktplaats zählen Festpreise und „Bieden vanaf“ (als verhandelbar). Bei Vinted gilt der Preis inklusive Käuferschutz, ohne Versand.
- **Subito, Wallapop und Leboncoin** laufen über den Dienst **Apify** (Dritter, kostenpflichtig, auf eigene Verantwortung). Den Token trägst du mit **EINSTELLUNGEN.cmd** ein. Im Block `apify:` der `config.yaml` stehen `products` (nur diese Produkte werden gesucht, Namen wie in der Watchlist), `interval_minutes` (Mindestabstand je Produkt, Standard 720) und `max_results` (Treffer pro Lauf, Standard 20). Preise laut Apify: Subito etwa 0,001 $, Wallapop etwa 0,00025 $ und Leboncoin etwa 0,0015 $ pro Treffer, dazu eine Startgebühr je Lauf. Ein Fehlschlag wird nicht vor Ablauf des Abstands wiederholt.
- Die Suchbegriffe müssen zur Sprache passen. Mit `queries:` in der Watchlist legst du für eine Plattform einen eigenen Begriff fest, zum Beispiel `ps5` statt `ps5 konsole`.
- Gesuche und Defekte filtert FlipRadar mit Begriffen der jeweiligen Sprache heraus.
- **Kleinanzeigen** bleibt wie beschrieben ausgeschaltet, solange keine schriftliche Freigabe eingetragen ist.



## Telegram und eBay testen, Quellenstatus

- In **EINSTELLUNGEN.cmd** gibt es die Knöpfe **Telegram testen** und **eBay testen**. Sie nennen die Ursache, zum Beispiel „Token ungültig“, „Chat-ID unbekannt“, „Produktionsfreigabe fehlt“ oder „Tageskontingent ausgeschöpft“.
- Im Suchfenster steht beim Start eine Zeile, von welchen Quellen Telegram-Alarme kommen können und welche nur sammeln. Quellen, die nur sammeln (Marktplaats, Vinted, Subito, Wallapop, Leboncoin), senden nie eine Nachricht.
- Nach jeder Runde zeigt jede Quelle ihren letzten Abruf, die letzten neuen Inserate und den letzten Fehler. Liefert eine Quelle seit sechs Stunden nichts Neues, erscheint eine Warnung.
- Schlägt ein Telegram-Versand fehl, steht der Grund im Fenster. Bei einem Formatfehler sendet FlipRadar die Nachricht ohne Formatierung erneut. Beim Ratenlimit wartet es die von Telegram genannte Zeit ab.

