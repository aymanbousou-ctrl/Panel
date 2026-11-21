# FlipRadar 2.0 für Windows

FlipRadar beobachtet deine Watchlist, schätzt den Wiederverkaufswert in der Schweiz und sendet passende Angebote mit Preis, Rechnung und Inserat-Link an deinen Telegram-Chat. Der PC muss eingeschaltet und das Programm geöffnet bleiben.

## In drei Schritten starten

1. Schließe das laufende V1-Fenster. Klicke im Explorer mit der rechten Maustaste auf die neue ZIP-Datei, wähle **Alle extrahieren** und öffne den entpackten Ordner **FlipRadar_2.0**.
2. Doppelklicke auf **START.cmd**. Nach fünf Sekunden beginnt die Suche automatisch. Der Starter verwendet bevorzugt dein installiertes Python 3.15. Die mitgelieferten Python-Bibliotheken funktionieren ohne Paketinstallation oder Compiler.
3. Beim ersten Start übernimmt V2 die Einstellungen, die Watchlist und eine SQLite-Kopie der vorhandenen Datenbank. Es sucht zuerst unter `Dokumente\FlipRadar_v1.2\flipradar`, dann unter `Downloads\FlipRadar_v1.2\flipradar`. Voraussetzung ist eine dort vorhandene `config.yaml`. Bei einer frischen Installation wählst du beim Start **E**, um Bot-Token und Chat-ID einzutragen.

**S** startet die Suche sofort. **E** öffnet die Einstellungen für Telegram, eBay, Kaufpreis, Gewinnschwelle, Intervall und Wechselkurs. **D** fragt je aktivierter Quelle ein Produkt ab und sendet bei konfiguriertem Telegram eine Testnachricht. Während FlipRadar läuft, beendet **Strg+C** die Suche. Vor einem Wechsel zu E oder D das laufende Fenster beenden.

## Was sendet FlipRadar?

Voreingestellt sind 33 Produkte, bis zu 2'000 CHF Kaufpreis, mindestens 20 % geschätzter Nettogewinn bezogen auf den Einsatz und ein Zielintervall von fünf Minuten. Pro Suchbegriff verarbeitet FlipRadar die von der ersten Ergebnisseite bereitgestellten Inserate, standardmäßig höchstens 40 pro Plattform. Sortierung und Umfang der öffentlich sichtbaren Ergebnisse bestimmt der Marktplatz. Ein langer Durchlauf wird abgeschlossen, bevor der nächste beginnt. Im Fenster steht die tatsächliche Wartezeit.

Ein neuer Fund oder ein Preisrückgang von mehr als 3 % gegenüber der letzten Beobachtung kann einen Alarm auslösen. Ein Angebot, dem zunächst Vergleichspreise fehlten, wird bei erneuter Sichtung wieder bewertet. Bei einer leeren Datenbank sammelt der erste erfolgreiche Durchlauf nur Vergleichspreise. Es gibt keine regelmäßige Telegram-Zusammenfassung bei null Deals.

**So liest du das Fenster.** Die Zahlen je Suche zählen gelesene Inserate vor Produkt- und Margenfilter. Ein Inserat kann in mehreren Suchen vorkommen. „Neu“ zählt erstmals gespeicherte Inserate. „Telegram gesendet“ bestätigt, dass Telegram die Nachricht angenommen hat. Scheitert ein Versand, merkt ihn die Datenbank vor. Der nächste aktive Durchlauf versucht es erneut. Falls Telegram eine Nachricht annimmt und die Antwort auf dem Rückweg verloren geht, kann eine Nachricht doppelt ankommen.

## Quellen

| Quelle | So kommen die Angebote ins Programm |
|---|---|
| Tutti.ch | V2 lädt die öffentliche deutschsprachige Suchseite und liest die darin bereits ausgelieferten Inserate. Die GraphQL-URL aus V1 wird nicht angefragt. |
| Ricardo.ch | V2 liest die öffentliche Suchergebnisseite. Nur Angebote mit erkennbarem Sofortkaufpreis werden übernommen. Bei einem Angebot mit Gebot und Sofortkauf zählt der Sofortkaufpreis. Es wird kein separater Browser installiert. |
| Kleinanzeigen.de | V2 liest Titel, Link und Angebotspreis aus den sichtbaren Trefferkarten. „VB“ ohne Betrag liefert keinen bewertbaren Kaufpreis. |
| Marktplaats.nl (NL) | V2 liest die öffentliche Suchseite (erste Ergebnisseite, nach Relevanz sortiert). Nur Festpreise zählen. „Bieden vanaf“ und reine Gebote werden übersprungen. Läuft immer im Modus „nur sammeln“: Preise werden gespeichert, aber es gibt keinen Telegram-Alarm. |
| eBay.de | V2 verwendet die offizielle Browse API für Festpreisangebote mit Artikelstandort Deutschland und Preis in EUR. Erforderlich sind eigene für die Produktion berechtigte Schlüssel. Ohne sie meldet V2 den fehlenden Zugang und durchsucht die anderen aktiven Quellen. |

**Marktplaats einschalten.** Öffne `%LOCALAPPDATA%\FlipRadarV2\config.yaml` mit dem Editor und füge unter `platforms:` die Zeile `- marktplaats` hinzu (oder schreibe `marktplaats` in die eckige Klammer). Beim nächsten Start sucht V2 dort mit. Die Quelle sammelt nur. Gesuche und Defekte filtert V2 mit niederländischen Begriffen wie „gezocht“ und „defect“ heraus.

**eBay einschalten.** Besorge im eBay Developers Program Produktionsberechtigung für die Buy APIs. Unter **Application Keys → Production** findest du App ID (Client ID) und Cert ID (Client Secret). Trage beide beim Start mit **E** ein. Ein normales Käuferkonto, Sandbox-Schlüssel oder ein eBay-Passwort genügen für diese Schnittstelle nicht. Mit **D** prüfst du danach die Verbindung. Beachte das Kontingent deines eBay-Schlüssels. Falls du keinen API-Zugang hast, bietet eBay für gespeicherte Suchen eigene E-Mail-Meldungen an. Diese laufen separat von FlipRadar und dessen Margenfilter.

**Wenn eine Quelle ausfällt.** Bei HTTP 401/403 pausiert V2 diese Quelle für eine Stunde. Bei HTTP 429 berücksichtigt es „Retry-After“. Fehlt die Wartezeit, sind 30 Minuten eingestellt. Sonstige Abruf- und Formatfehler pausieren die Quelle für fünf Minuten. Die angezeigte Uhrzeit gilt auch nach einem Neustart. Die anderen Quellen laufen weiter. Unveränderte Wiederholungen nach jeder einzelnen Produktsuche hätten die Ursache der 33 Tutti-Fehler aus V1 nicht behoben.

## Preisrechnung

Die Vorgaben aus deiner Konfiguration haben Vorrang. Die Voreinstellungen nehmen für den Schweizer Marktwert den um Ausreißer bereinigten Median aus mindestens acht Vergleichsinseraten der letzten 30 Tage auf Tutti und Ricardo. Das angebotene Objekt wird anhand seiner Plattform-ID aus seinen eigenen Vergleichsdaten ausgeschlossen. Den Median der Angebotspreise multipliziert V2 standardmäßig mit 0,92. Bei zu wenigen Daten kann ein eigener Referenzpreis aus der Watchlist einspringen. Mit genügend abgeschlossenen eigenen Verkäufen verwendet V2 deren Median vorrangig.

| Beispiel mit Standardkosten | Betrag |
|---|---:|
| Geschätzter Marktwert | 600 CHF |
| Abzüglich 10 % Verkaufsgebühr | −60 CHF |
| Abzüglich Versand-/Fahrtpauschale | −10 CHF |
| Abzüglich Kaufpreis | −400 CHF |
| Geschätzter Gewinn | **130 CHF** |
| Gewinn geteilt durch Einsatz | **32,5 %** |

Deutsche Preise werden mit `eur_to_chf` umgerechnet. Der Wechselkurs ist ein konfigurierter Wert. `germany_extra_chf` deckt zusätzliche Kosten eines deutschen Kaufs ab und geht in den Einsatz ein. Modellabhängige Mindestpreise, Budget, `min_profit_chf` und `min_margin` steuern die Auswahl. Tatsächliche Versand-, Import- oder Reparaturkosten können von deinen Pauschalen abweichen. Modellvarianten, Zustand und bei Autos Kilometerstand und Baujahr können den Schätzwert stark verändern.

Für bestätigte Neupreise kann ein Produkt eine `retail_url` von Digitec oder Galaxus haben. Ein lagernder Neupreis in CHF für die passende Artikelnummer begrenzt den geschätzten Wert. Gelingt der Abruf nicht, wird das protokolliert. Bei der mitgelieferten Watchlist ist ein Shoplink für die Nintendo Switch 2 hinterlegt.

## Deine Daten

Der im Fenster angezeigte Datenordner ist unter Windows standardmäßig **%LOCALAPPDATA%\FlipRadarV2**. Dort liegen `config.yaml`, `watchlist.yaml`, `flipradar.db` und das rotierende Protokoll `flipradar.log`. Derselbe Benutzer verwendet diesen Datenordner auch nach einem erneuten Entpacken. Die Zugangsdaten stehen lokal in der Konfiguration. Zum Teilen einer Fehlermeldung reichen die betreffenden Protokollzeilen.

Die Übernahme aus V1 ist einmalig und liest die alte Installation. Bereits verschickte Alarme bleiben bekannt. Frühere Ricardo-Preise, die auch Gebote gewesen sein könnten, zählen erst nach einer neuen Zuordnung aus einem V2-Sofortkauf wieder als Vergleich. Offene alte Ricardo-Alarme werden in der V2-Kopie verworfen. Liegt V1 woanders, kannst du die Dateien nach beendetem Programm manuell in den V2-Datenordner kopieren. Für die automatische sichere Datenbankübernahme verwende vorzugsweise einen der beiden erkannten V1-Pfade vor dem ersten Start.

Eigene Verkäufe kannst du als CSV in UTF-8 mit den Spalten `sale_id,product,sold_on,price_chf` hinterlegen und den Namen bei `sales_csv` eintragen. `product` muss dem Namen aus der Watchlist entsprechen. `sold_on` hat das Format JJJJ-MM-TT, der Betrag ist der Brutto-Verkaufspreis in CHF.

## Optionale Kommandozeile

Für die tägliche Nutzung genügt START.cmd. Im entpackten Programmordner gibt es außerdem diese Befehle.

| Befehl | Wirkung |
|---|---|
| `py -3.15 radar.py once --no-alerts` | Ein echter Suchdurchlauf, Daten sammeln, keine Telegram-Nachrichten |
| `py -3.15 radar.py stats` | Anzahl und Spanne der gespeicherten Schweizer Vergleichspreise pro Produkt |
| `py -3.15 radar.py test-telegram` | Nur die Telegram-Verbindung testen |
| `py -3.15 tests\test_v2.py` | Lokale Regressionstests ohne Zugangsdaten |

## Quellen zur Fehlersuche und Anbindung

- Öffentliche Tutti-Suchergebnisse und vom Betreiber ausgeschlossene API-Pfade. [Beispiel einer Suchseite](https://www.tutti.ch/de/q/rtx-4070-gaming/Ak6hSdHggNDA3MMCUwMDAwA) · [robots.txt](https://www.tutti.ch/robots.txt)
- Öffentliche Ricardo-Suchergebnisse mit Geboten und Sofortkauf. [PS5 auf Ricardo](https://www.ricardo.ch/de/s/ps5/)
- Bedeutung der Serverantworten. [HTTP 403](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Status/403) · [HTTP 429](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Status/429)
- Offizielle eBay-Dokumentation. [Suche](https://developer.ebay.com/develop/api/buy/browse_api/item/search) · [Produktionszugang](https://developer.ebay.com/api-docs/buy/static/buy-requirements.html) · [Application Keys](https://developer.ebay.com/my/keys) · [Gespeicherte Suchen](https://www.ebay.de/help/default/default/gespeicherte-suchen?id=4051)
- Die Bibliotheken und zugehörigen Lizenztexte liegen unter `vendor`.
