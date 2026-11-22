# Stoppuhr – Pi-Software (v0.44.14)

Webbasierte Wettkampf-Stoppuhr: ESP32-Taster messen die Zeit, der Raspberry Pi sammelt, wertet aus und
liefert die Ergebnisse an JAuswertung. Die Taster-Firmware liegt im Repository `Taster`.

> **Die Taster puffern und wiederholen nicht bestätigte Meldungen; verspätete Ereignisse werden nachverarbeitet oder zur Prüfung angezeigt. Bei Geräteausfällen oder Netztrennungen kann es trotzdem zu Datenverlust kommen.**

Versionsverlauf: [CHANGELOG.md](CHANGELOG.md). Installationsanleitungen: [Einzel-Pi](docs/INSTALLATION-EINZEL-PI.md)
oder [Zwei-Pi-Betrieb (Koffer und Bad)](docs/INSTALLATION-ZWEI-PI.md); Hintergründe zum Zwei-Pi-Betrieb stehen in
[deploy/zwei-pi/README.md](deploy/zwei-pi/README.md).

## Funktionen

- Startkarten-Import (manuell), dynamische Bahnanzahl, Drag & Drop der Taster auf Bahnen und Starter
- Start, Stopp, automatisch nächster Lauf, Abbruch und Wiederholung eines Laufs; Wettkampf beenden wahlweise mit oder ohne Taster-Abschaltung
- Der Zeitabgleich der zugeordneten Taster wird vor dem Start auf der Stoppuhr-Seite angezeigt. Grün bedeutet, dass jeder Taster seit seiner letzten WLAN-Verbindung eine SNTP-Synchronisierung gemeldet hat, die höchstens 60 Sekunden zurückliegt (Taster-Firmware ab v0.19.5). Das ist eine Bereitschaftsprüfung, keine Garantie für 5-ms-Genauigkeit; WLAN-SNTP kann diese Genauigkeit nicht pauschal garantieren.
- Tastendrücke verwenden direkt den beim Druck erfassten SNTP-Zeitstempel des Tasters. Die frühere Einweg-Diagnose „Taster-Zeitstempel minus Pi-Empfangszeit“ wird nicht mehr in den Vitaldaten angezeigt.
- Taster tauschen über „Bereitschaft“, Vitaldaten mit darunterliegendem Systemstatus, Zwei-Pi-Betrieb mit Ausfallübernahme
- Ab Pi v0.44.7 erscheinen bei Bahnen, Starter und Zieleinlauf nur Vitalwerte mit gelbem oder rotem Grenzwert; Offline bleibt sichtbar. Die Tasterzuordnung zeigt den WLAN-Namen neben der MAC-Adresse und weiterhin die übrigen Vitaldaten.
- Ab Pi v0.44.6 und Taster v0.22.2 lassen sich unter **Einstellungen → Experteneinstellungen → Lauf- und Tasterverhalten** die Spannungsgrenzen für 0 % und 100 % für alle Taster festlegen (Standard 3,30 und 4,00 V). Die vorhandene Kennlinie wird auf den Bereich angepasst. 100 % sind keine Aussage über vollständige Ladung; Akkuwarnung und Abschaltung bleiben auf der bisherigen Kennlinie und können deshalb bei anderen angezeigten Prozentwerten auslösen. Offline-Taster übernehmen Änderungen nach Verbindung; nach Neustart gelten bis zur Verbindung Standardwerte. Zuerst beide Pis und dann die Taster aktualisieren.
- Anmeldung für die Oberfläche, WLAN-Daten und Updates (Pi und Taster) aus der Oberfläche
- Einzelne Taster ausschalten (ab v0.38.0): Einstellungen → „Taster einzeln schlafen schicken“. Buchstabe wählen und im Bestätigungs-Popup erneut eingeben (`POST /api/taster/sleep`). Nur online-Taster; Taster mit Aufgabe werden während eines Laufs abgelehnt.
- Tab „Vitaldaten“ (ab v0.9.0): je ein Diagramm für Akku, Akkuspannung, Temperatur, Luftfeuchte und WLAN-Stärke mit allen Tastern in eigenen Farben (Zeitfenster bis 48 Stunden). Senkrechte gestrichelte Linien „L<Nr>“ markieren jeden Laufstart.
  Ein Klick auf einen Legendeneintrag blendet die Kurve ein oder aus (ab v0.37.0, wird im Browser gemerkt); die eingestellten Grenzwerte sind als zarter gelber (Warnung) und roter (kritisch) Hintergrund eingezeichnet.
  Die Werte kommen aus den ohnehin alle 10 s gesendeten Vitaldaten (kein Mehraufwand am Taster) und liegen in Redis (`VITALS_HIST:<MAC>`, höchstens 48 Stunden).
  Schnittstelle: `GET /api/vitals/history?mac=…&hours=…`.
- Ladekoffer (ab v0.12.0): Die Ladeplatine (Projekt `Ladekoffer`) sendet alle 5 s per `POST /api/charger` (JSON) Ladezustand („lädt“ / „lädt nicht“) und Spannung der 10 Plätze, Temperatur, Luftfeuchte und Ampel. Der Pi wertet daraus Statusmeldungen aus (Kopfzeile, Meldungen oben, Tabelle im Tab „Vitaldaten“). „Taster da“ und „voll“ lassen sich mit dem TP4056-Modul nicht erkennen und werden nicht angezeigt (ab v0.35.0). Nach 30 s ohne Meldung gilt der Ladekoffer als offline. `GET /api/charger` liefert den ausgewerteten Zustand. Unter Einstellungen lassen sich Ladeplätze einzeln wecken (Pi ab v0.24.0, Ladekoffer-Firmware ab v0.6.0).
- Unter **Einstellungen → Taster aus dem Ladekoffer wecken → Alle starten** löst Pi v0.41.9 mit Koffer-Firmware ab v0.7.24 dieselbe Sequenz wie der lange Tastendruck am Koffer aus, einschließlich der eingestellten Reihenfolge und Impulszeiten. Die Bestätigung bezieht sich auf die abgeschlossene Wecksequenz, nicht darauf, ob jeder Taster tatsächlich gestartet ist.
- Die Spannung am Ladeausgang wird ab Pi v0.41.7 und Koffer-Firmware v0.7.23 nicht mehr zur Erkennung von Überspannungsfehlern verwendet: Ein leerer Platz kann ebenfalls eine hohe Spannung anzeigen.
- Im Ladekoffer-Status im Tab „Vitaldaten“ bleiben die aktuellen Spannungen aller zehn Ladeplätze in der Tabelle sichtbar. Der Verlauf wird ab Pi v0.41.21 nicht mehr gespeichert oder als Diagramm angezeigt.
- Ab Pi v0.41.10: Gesamtstrom des INA226 im Ladekoffer-Status und als Verlauf einschließlich Wettkampfarchiv. Koffer-Firmware v0.7.26 mit R002-Shunt: Messbereich ungefähr ±40,96 A; ältere Koffer-Firmware mit R100-Shunt bleibt auf ±0,8192 A begrenzt. Messbereichsende und fehlende Messungen werden als unbekannt statt als Stromwert angezeigt. Die Messung erfolgt stichprobenartig; kurze Spitzen und eine Überlast werden nicht zuverlässig erkannt. Die 8,5-/9,5-A-Schwellen werden nicht überwacht. Keine Abschaltung und kein Überstromschutz durch die Software. Alter Kofferstatus und alte Archive bleiben lesbar.
- Bei WLAN-/Pi-Unterbrechungen puffert die Ladekoffer-Firmware ab v0.7.19 Spannungsmessungen bis zu einer Stunde im RAM und kann sie nach Wiederverbindung nachliefern. Ältere Pi-Versionen speicherten diese Messwerte mit dem ursprünglichen Zeitpunkt; ab Pi v0.41.21 werden Ladeplatz-Verläufe nicht mehr angenommen oder gespeichert. Der Firmware-Puffer übersteht keinen Neustart oder Stromausfall des Koffers.
- Ladekoffer-Firmware ab v0.7.20 kann nach langem Druck am Koffer alle Taster ohne zugeordnete oder vorgemerkte Rolle ausschalten: bis v0.7.29 nach 15 s, ab v0.7.30 nach 5 s.
- Geräte-Logs lassen sich einzeln über die Oberfläche herunterladen: Pi unter **Einstellungen → Software und Firmware**, Taster unter **Vitaldaten → Zustand der Taster und Pis** in der Zeile unter WLAN und Ladekoffer im Status. Pi-Logs enthalten bis zu 500 Anwendungsereignisse seit dem letzten Dienststart; Taster und Koffer puffern jeweils 24 Diagnoseereignisse seit dem letzten Einschalten. Die Geräte-Snapshots bleiben auf dem Pi in Redis gespeichert und laufen 30 Tage nach der letzten Meldung ab. Erfordert Pi v0.41.6, Taster v0.19.1 und Koffer v0.7.22; die neue Position der Taster-Links gilt ab Pi v0.41.8.
- Ab Pi v0.44.10: Unter **Vitaldaten → Taster-Langzeitlog nach MAC** steht ein CSV-Download je MAC bereit, auch ohne aktuelle Anmeldung, Buchstaben oder Rolle. Beim Start des Stoppuhr-Dienstes, danach alle 24 Stunden und beim Wettkampfende werden vorhandene Vitalverläufe übernommen – auch außerhalb eines Wettkampfs, etwa beim Laden. Pro abgeschlossener Minute wird je Wert der Mittelwert der verfügbaren Messungen gespeichert (Akkuanzeige, Spannung, Temperatur, Feuchte und WLAN-Stärke); die Zeitspalte bezeichnet den Beginn des Minutenfensters in UTC. Firmware und roher Akkuwert sind im bestehenden Verlauf nicht enthalten. Nicht gemeldete Werte bleiben leer; Offline-Zeiten erzeugen keine Einträge. Die aktuell laufende Minute wird erst bei einer späteren Übernahme berücksichtigt; bei automatischer Übernahme kommt eine weitere Minute Puffer hinzu. Das Langzeitlog ist daher nicht live und kann bis zur nächsten Übernahme zurückliegen.
- Der ursprüngliche Verlauf ist nach Anzahl Messpunkte begrenzt (bei Meldungen alle 10 Sekunden ungefähr 48 Stunden). Bei Redis-Fehlern wird die automatische Übernahme nach fünf Minuten wiederholt; am Wettkampfende bleibt bei Fehlern der Wettkampf bestehen. Ein längerer Ausfall oder Messungen außerhalb des vorhandenen Verlaufs können trotzdem Lücken verursachen. Das Langzeitlog wird nicht automatisch gelöscht: Speicherbedarf in Redis und auf der SD-Karte wächst. Regelmäßige externe Sicherungen sind nötig, denn Redis-Snapshots und Replikation garantieren bei Stromausfall oder Ausfall beider Pis keinen lückenlosen Erhalt.
- Ab Pi v0.44.11 lassen sich unter **Vitaldaten → Taster-Langzeitlog nach MAC** für einen ausgewählten Taster Akku, Spannung, Temperatur, Luftfeuchte und WLAN-Stärke als Diagramme anzeigen. Der frei wählbare Zeitraum umfasst bis zu 31 Kalendertage; Zeiten werden lokal angezeigt, Lücken nicht verbunden. Der CSV-Download enthält weiterhin alle gespeicherten Werte.
- Ab Pi v0.44.11 und Ladekoffer-Firmware v0.7.28 quittiert ein kurzer Druck auf den Koffertaster auch zwischen zwei Pieptönen die aktuelle rote Dashboard-Warnung. Schwankende Messwerte lösen keine neue Warnung aus; tatsächlich neue Warnungen dürfen erneut piepen. Ohne geöffnetes Dashboard werden dessen Warnungen nicht gemeldet.
- Ab Pi v0.44.13 lassen sich rote und gelbe Dashboard-Meldungen einzeln über **Stumm** quittieren; sie bleiben sichtbar, bis die Ursache behoben ist. Neue oder nach zwischenzeitlicher Behebung wieder auftretende Meldungen werden erneut gemeldet. Zur Quittierung eigener Koffer-Fehlertöne ist Koffer-Firmware v0.7.29 erforderlich; die Übermittlung erfolgt mit der nächsten Statusmeldung. Der Zustand überlebt keinen Neustart der Kofferplatine zuverlässig.
- Ab Pi v0.44.14 und Koffer-Firmware v0.7.31 blinken neue Dashboard-Meldungen am Koffer kurz in ihrer Farbe, unabhängig von der Dashboard-Toneinstellung oder Quittierung. Die Meldungen benötigen weiterhin ein geöffnetes Dashboard und die Verbindung zum Pi. Die Ampelanzeige ersetzt keine Prüfung der Meldungen.
- Ab Pi v0.41.9 enthalten Taster-Logs zusätzlich geschätzte lokale Uhrzeiten (aus Empfangszeit und gerundeter Taster-Laufzeit) sowie die letzten 100 vom Pi beobachteten Rollen- und Grenzwertwechsel. Die Uhrzeiten der Taster-Ereignisse sind Näherungen und können durch Übertragung und Uhrkorrekturen abweichen; ohne gültige Laufzeit bleiben sie unbekannt. Der Pi prüft Akku, Spannung, Temperatur, Feuchte und WLAN anhand der eingestellten Grenzwerte beim Empfang der Vitaldaten; Zwischenereignisse ohne Meldung sind nicht erkennbar. Die Beobachtungen laufen 30 Tage nach der letzten Meldung ab. Am Taster sind keine Änderungen und keine zusätzliche Übertragung nötig.
- Ab Pi v0.41.11 und Taster v0.19.2 werden Drücke sofort verarbeitet, auch am Starter. Fünf Sekunden Halten fordert den Abbruch des Versuchs an, zu dem dieser Druck gehört; der Pi bestätigt oder lehnt ihn ab. Ist inzwischen ein anderer Versuch aktiv, wird nicht dieser abgebrochen. Bei einer Unterbrechung wird der Abbruch nachgeliefert und ist bis zur Pi-Bestätigung ungewiss. Ein bereits extern abgerufenes vorläufiges Ergebnis kann nicht zurückgerufen werden. Pi zuerst aktualisieren; ältere Pi-Versionen unterstützen den neuen Abbruch nicht.
- Ab Pi v0.41.12 zählen vorzeitige Bahndrücke nicht als gestoppte Bahnen. Taster v0.19.4 zeigt online nur vom Pi bestätigte Stoppzeiten; dadurch erscheint bei einem während der Stopp-Sperre ignorierten Druck keine falsche Stoppzeit.
- Ab Pi v0.41.22 warten Redis-Verbindungen höchstens 1 s; schreibende Anfragen werden bei belegter Wettkampf-Zustandssperre nach 250 ms mit HTTP 503 abgelehnt, statt bis zu zehn Sekunden zu warten. Taster können Tastendrücke damit innerhalb ihres HTTP-Timeouts erneut zustellen; Sperr-Timeouts nennen außerdem die haltende Route im Pi-Log. Unabhängige Alarmmeldungen nutzen die Wettkampf-Sperre nicht.
- Ab Pi v0.42.0 werden Verlaufsdaten und Diagnose-Snapshots von Taster und Ladekoffer nach dem Freigeben der Wettkampf-Sperre verarbeitet. Statusmeldungen desselben Geräts bleiben geordnet; das Beenden und Archivieren eines Wettkampfs wartet auf laufende Statusverarbeitung oder meldet HTTP 503. Lange Sperrbelegungen und Statusverarbeitungen protokollieren Dauer und einzelne Verarbeitungsschritte im Pi-Log. Langsame Zustands-/Redis-Zugriffe und andere schreibende Anfragen können die Sperre weiterhin belegen; die Änderung ist keine Garantie für verlustfreie Zeitmessung und muss auf der Anlage unter Last geprüft werden.
- Ab Pi v0.42.0 werden vor dem zugehörigen Start eingetroffene Zieleinlaufdrücke vorgemerkt. Ein Druck vor dem aktuellen Start, für den ein älterer gestarteter Lauf infrage kommt, erscheint zur **manuellen Klärung** in der Oberfläche. Nach Prüfung kann er ausdrücklich einem Lauf als zusätzliche Zeit zugeordnet oder bei identischer Zeit und identischem Taster als Duplikat bestätigt werden. Neue Zeiten werden angehängt, bestehende Zuordnungsindizes bleiben unverändert. Ohne älteren möglichen Lauf wird ein Druck vor dem Start weiterhin ignoriert. HTTP 200 bedeutet nicht zwangsläufig, dass eine Zeit gewertet wurde.
- Pi v0.42.0 erkennt wiederholte gespeicherte Bahn- und Starterdrücke anhand von Taster und Ereignis-ID; eine ID mit anderer Zeit wird abgelehnt. Vorgemerkte Drücke werden einzeln verarbeitet und bleiben bei Fehlern gespeichert. Eine erneute Zustellung desselben Starts oder die Schaltfläche zur Replay-Fortsetzung kann die Nachverarbeitung fortsetzen; bis dahin sind weitere Drücke und der automatische Laufwechsel gesperrt. Mehrdeutige ältere Bahndrücke und vorgemerkte Drücke nach einem Rollenwechsel oder einer nicht verarbeitbaren Anfrage erscheinen zur manuellen Prüfung. Sie können nach ausdrücklicher Auswahl einer freien Bahn oder des Zieleinlaufs zugeordnet oder mit Begründung unbewertet dokumentiert werden. Bestehende Bahnzeiten werden dabei nicht überschrieben; geklärte Fälle werden im Archiv gespeichert.
- Ab Pi v0.44.4 werden vorgemerkte Drücke einzeln mit Taster, ursprünglicher Rolle, Druckzeit und benachbarten Starts angezeigt. Sollen sie nicht mehr auf einen Start warten, können sie einzeln ausdrücklich zur manuellen Klärung übernommen werden; dort müssen sie zugeordnet oder mit Begründung unbewertet dokumentiert werden. Die Übernahme allein wertet oder löscht keinen Druck. Bei laufender Replay-Nachverarbeitung ist sie gesperrt. Startzeiten sind nur Orientierung und kein Nachweis der Laufzugehörigkeit.
- Ab Pi v0.44.5 stehen vorgemerkte und manuell zu klärende Drücke auf der Seite **Tastendrücke**; die Anzahl steht am Reiter. Sie blockieren das Wettkampfende nicht mehr und werden ohne Wertung in den Archiv-Rohdaten gespeichert. Ohne Archivnamen wird bei offenen oder bereits geklärten Fällen automatisch ein Archiv angelegt. Eine nachträgliche Zuordnung im Archiv ist nicht möglich; sie muss bei Bedarf vor dem Beenden erfolgen. Schlägt das Archivieren fehl oder ist eine Nachverarbeitung technisch unterbrochen, bleibt der Wettkampf erhalten und das Beenden wird abgelehnt. Warnungen bei vollem Puffer, unvollständiger Nachverarbeitung und abgelehnten Tasterdrücken bleiben unmittelbar sichtbar.
- Ab Pi v0.44.2 zeigt die Oberfläche bei manuellen Klärungsfällen die Bahn bzw. Rolle, Druckzeit und die zeitlich nächsten aufgezeichneten Starts als Orientierung. Bei neu angelegten Bahnfällen wird auch der bei der Verarbeitung aktuelle Lauf gespeichert; für ältere Fälle ist dieser nicht nachträglich bekannt. Weder der aktuelle Lauf noch die nächsten Startzeiten beweisen die Zugehörigkeit eines Drucks; Zuordnung und Zeit sind anhand der Wettkampfunterlagen zu prüfen. Die Hinweise gelten auch für bereits offene Fälle, soweit Startzeiten vorhanden sind.
- Ab Pi v0.44.0 werden Bahndrücke bis einschließlich drei Sekunden vor dem zugehörigen Start als Startabweichung statt als Stopp gewertet, auch wenn ein älterer Lauf existiert. Ein verspäteter Stopp des vorherigen Laufs in diesem Fenster ist dadurch nicht automatisch erkennbar und muss anhand des Protokolls geprüft werden. Ältere Drücke bleiben bei möglicher Zuordnung zum alten Lauf zur manuellen Klärung.
- Ab Pi v0.44.1 werden Drücke von Bahnen ohne Startkarte nach dem Start ignoriert, statt einen Klärungsfall zu erzeugen. Vor dem Start und nach Laufende werden sie zunächst vorgemerkt, um den richtigen Lauf zu bestimmen. Ältere Drücke, die zu einer zuvor belegten Bahn gehören könnten, bleiben zur Klärung; bei fehlenden Startkarten des ganzen Laufs wird nicht von einer leeren Bahn ausgegangen. Bereits bestehende Klärungsfälle bleiben unverändert.
- Ab Pi v0.44.0 und Taster v0.22.0 werden seit dem Taster-Neustart erlebte HTTP-4xx-Ablehnungen im Dashboard mit dem letzten bekannten Pufferstatus angezeigt. Die Meldung kommt erst mit erfolgreicher Vitalübertragung; bei Offline-Tastern und direkt nach dem Neustart kann sie fehlen oder veraltet sein. Solange ein Druck abgelehnt bleibt, blockiert er weiterhin die Warteschlange. Im Dashboard heißt eine nicht mehr blockierte Zustellung nicht, dass der Druck als Zeit gewertet wurde. Die Anzeige ersetzt keine Prüfung und ist keine dauerhafte Ereignisaufzeichnung.
- Ab Pi v0.44.3 und Taster v0.22.1 wird der geschätzte Akku-Prozentwert für Anzeige und Verlauf über fünf Messungen geglättet. Der Pi verwendet für Prozent-Grenzwerte und Diagnose den zusätzlich übertragenen ungeglätteten Wert; die Warnung kann deshalb einen anderen Wert als die Anzeige nennen. Die Spannung bleibt ungeglättet, und der Akkuschutz des Tasters wird nicht verzögert. Ältere Taster übermitteln weiterhin nur den bisherigen Prozentwert.
- Der Pi-Vormerkpuffer und die Listen für offene Prüfungen sind jeweils auf 200 Einträge begrenzt; volle Puffer lehnen neue Vorgänge mit HTTP 503 ab, statt alte zu löschen. Dies ersetzt keine transaktionale, ausfallsichere Ende-zu-Ende-Zustellung. Insbesondere können Redis-Schreibbestätigungen bei Stromausfall oder asynchronem Pi-Wechsel verloren gehen; siehe [Zwei-Pi-Betrieb](deploy/zwei-pi/README.md).
- Ab Pi v0.43.0 zeigen die Diagramme Akkuspannung standardmäßig von 3,0–4,2 V, Temperatur von 15–40 °C, WLAN von −100 bis −30 dBm und Ladekoffer-Gesamtstrom von 0–10 A. Liegen sichtbare Messwerte außerhalb, erweitert sich die jeweilige Achse; ausgeblendete Kurven beeinflussen sie nicht. Dies gilt auch für Archive und ist keine Überwachung oder Schutzabschaltung.
- Ab Pi v0.43.0 und Taster v0.21.0 lassen sich unter **Einstellungen → Lauf- und Tasterverhalten** die Bedien- und Bestätigungstöne aller Taster auch während des Wettkampfs mit einem Schalter ausschalten. Akku-, Funk-, Abbruch- und Ereigniswarnungen bleiben hörbar. Die Taster übernehmen die Einstellung mit ihrer nächsten erfolgreichen Vitalmeldung (normalerweise innerhalb 30 s); offline oder bei Fehlern kann es länger dauern. Nach erfolgreichem Wettkampfende werden die Töne wieder eingeschaltet. Ältere Taster-Versionen bleiben unverändert.
- Ab Pi v0.41.23 unterstützt die Starteranzeige HTTP-Long-Polling: geänderte Bahnstopp-Anzeigen werden sofort ausgeliefert, statt auf den nächsten Zwei-Sekunden-Abfragezyklus zu warten. Dafür ist Taster-Firmware v0.19.8 nötig; Messzeitstempel und Wertung bleiben unverändert.
- Bei wiederholten WLAN-Ausfällen am Koffer enthalten Geräte-Logs ab Koffer v0.7.23 Verbindungsabbrüche, Wiederverbindungsversuche, Signalstärke und Funkkanal.
- Unter Einstellungen → „Ladekoffer: Taster aufwecken“ lässt sich die Slot-Aufweckreihenfolge einstellen (Pi ab v0.41.4, Koffer ab v0.7.21). Die Pinbelegung der aktuellen Koffer-Platine ist fest; das alte Pin-Einstellfeld wird von aktueller Firmware ignoriert.
- Unter Einstellungen → „Software und Firmware“ stehen im Zwei-Pi-Betrieb beide Pi-Versionen und die Ladekoffer-Firmware nebeneinander. Das Koffer-Update wird wie bei den Pis mit „Übernehmen und neu starten“ gestartet; die Oberfläche meldet, wenn die neue Version läuft oder nicht bestätigt werden kann.
- Die Oberfläche hat fünf Seiten: **Stoppuhr**, **Tastendrücke**, **Vitaldaten** (inklusive Systemstatus), **Archiv** und **Einstellungen**. JAuswertung-Startkarten werden in den Einstellungen geladen; dort kann die IP des aufrufenden Geräts übernommen werden. Koffer-Temperatur und -Luftfeuchte sind ebenfalls als Verlauf sichtbar.
- Ab Pi v0.44.5 können im **Archiv** mehrere Wettkämpfe ausgewählt und nach Bestätigung endgültig gelöscht werden; Ergebnisse, Rohdaten und Vitalverläufe dieser Archive gehen dabei verloren. Der laufende Wettkampf bleibt unverändert. Die Löschungen erfolgen einzeln; nicht bestätigte Löschungen werden angezeigt.

## Installation

### Auf dem Raspberry Pi

Für die vollständigen Schritt-für-Schritt-Anleitungen mit Betriebssystem-, Zugangsdaten-, WLAN- und Taster-`secrets.h`-Einrichtung:
[Einzel-Pi](docs/INSTALLATION-EINZEL-PI.md) oder [Zwei-Pi-Betrieb](docs/INSTALLATION-ZWEI-PI.md).
Das folgende Beispiel installiert die Software auf einem einzelnen Pi:

```bash
mkdir -p ~/apps
cd ~/apps
sudo apt-get install -y git
git clone https://github.com/andreasschoeler93/Stoppuhr-2.0-Stoppuhr.git stoppuhr
cd stoppuhr
bash deploy/install.sh
```

- Oberfläche: `http://<PI-IP>:1999`. Beim ersten Öffnen legst du Benutzername und Kennwort fest.
- Dienste: `stoppuhr` (Server) und `stoppuhr-knoten` (Systemstatus, WLAN-Umstellung). Log: `journalctl -u stoppuhr -f`.
- Die Daten liegen in Redis (`save 10 1`), nicht im Projektordner. Snapshots und Zwei-Pi-Replikation sind kein Ersatz für externe Sicherungen und garantieren keinen verlustfreien Erhalt bei Stromausfall oder Pi-Ausfall.
- Einstellungen per Umgebungsvariable in `deploy/stoppuhr.service`: `REDIS_HOST`, `REDIS_PORT`, `PORT`, `HEATS_XML_PATH`.
- Zeitserver für die Taster: in `/etc/chrony/chrony.conf` `allow <Taster-Netz>` ergänzen
  (ohne Internet zusätzlich `local stratum 10`), danach `sudo systemctl restart chrony`.

### Tests

```bash
cd backend
../.venv/bin/python -m unittest discover -s tests
```

### Prüfung vor dem Wettkampf

Die automatischen Tests und ein Firmware-Build ersetzen keine Abnahme der realen Anlage.
Vor einem Einsatz mit Testdaten und unter Aufsicht durchführen und Ergebnisse protokollieren:

1. Versionen beider Pis und aller Taster, Uhrensynchronisation, Stromversorgung, freien
   Speicherplatz sowie Redis- und Replikationszustand prüfen. Eine unabhängige Referenzzeit
   mit bekannter Messunsicherheit bereithalten.
2. Mindestens 21 Läufe mit allen eingesetzten Tastern, gleichzeitigen Bahnstopps, Zieleinlauf,
   Laufwechsel und Wiederholungsversuch durchspielen. Jeden Druck und jedes Ergebnis mit dem
   Referenzprotokoll und dem XML-Export vergleichen; keine ungeklärten Warnungen akzeptieren.
3. WLAN kurz und länger trennen, verzögerte und wiederholte Übertragung sowie Rollenwechsel
   prüfen. Die Warn- und Klärungswege einschließlich belegter Bahn und unbewerteter Ereignisse
   erproben; die Pufferstände vor einem Neustart kontrollieren.
4. Den Wechsel beider Pis und ihre Rückkehr, eine Trennung der Pi-Verbindung und Stromausfälle
   nur in einem freigegebenen Testfenster durchführen. Nach jedem Wechsel sämtliche Ergebnisse
   mit der Referenz vergleichen; asynchrone Replikation kann bestätigte Daten verlieren.
5. Zeitabweichungen gegen die unabhängige Referenz messen und dokumentieren; die Genauigkeit
   der Referenz und das geforderte Toleranzband müssen vorher feststehen. Bei ungeklärtem
   Ereignis, Datenverlust oder unzureichender Genauigkeit die Anlage nicht freigeben.

## Bedienung

### Anmeldung

Die ganze Oberfläche ist durch Benutzername und Kennwort geschützt. Beim ersten Öffnen legst du beide fest.
Ändern: **Einstellungen → Zugang zur Oberfläche** (das alte Kennwort wird abgefragt; andere Sitzungen werden abgemeldet).
Ohne Anmeldung bleiben nur erreichbar: die Schnittstellen der Taster (`/api/taster`, `/api/vitals`, `/api/charger` (nur POST), `/api/triggers`,
`/api/display`, `/api/abort-run`, Firmware-Download, `/api/ota-status`), `/api/version` und der Export `/heats.xml` für JAuswertung.
Die Sitzung bleibt 30 Tage; nach fünf Fehlversuchen pro Minute sperrt der Server die Anmeldung kurz.
Der Schlüssel der Sitzungen und der Kennwort-Hash liegen in Redis und werden im Zwei-Pi-Betrieb mitkopiert.
Kennwort vergessen: auf dem Pi `redis-cli del AUTH`, danach beim nächsten Öffnen neu festlegen.

### JAuswertung und elektronische Zeitnahme einrichten

1. In JAuswertung zuerst den HTTP-Server in den Einstellungen einschalten, dort den Port festlegen und ihn danach über die Weltkugel scharf schalten.
2. Unter **Einstellungen → JAuswertung: HTTP-Server einrichten** die IP des JAuswertung-Rechners, denselben HTTP-Port und den Startkarten-Pfad eintragen.
3. Die unter **Einstellungen → Elektronische Zeitnahme: Startkarten verbinden** angezeigte IP ohne Port im Feld **AlphaServer Server** von JAuswertung eintragen.
4. Die Startkarten-Adresse speichern und **Startkarten laden**. Die Statuszeile bestätigt den Import oder zeigt den Fehler an.

### Wettkampf beenden

**Einstellungen → Wettkampf beenden** löscht nach Bestätigung Startkarten, Zeiten, Taster und Bahnzuordnungen und leert den XML-Export.
Der Server sendet den Abschaltbefehl während der eingestellten Dauer (Standard 10 s) bei den Display-Abfragen mit.
Taster, die in dieser Zeit nicht verbunden sind, empfangen ihn nicht. Buchstaben werden danach ab A neu vergeben.

### Abbruch und Wiederholung

Ein langer Druck (5 s) am Starter fordert den Abbruch des Versuchs an; erst die Bestätigung durch
den Pi und das dreimal lange Piepen bestätigen ihn. Danach wird die nächste Version vorbereitet.
Die Stopp-Sperre beginnt mit dem Abbruch. Über **Laufvorwahl** geht das auch in der Oberfläche.
Gespeicherte Zeiten bleiben; Versionen werden getrennt nummeriert (z. B. `5/2`) und im XML-Export als eigener Heat ausgegeben.

### Taster-Anzeige

`GET /api/display` liefert Namen und Disziplinen als UTF-8 mit Umlauten; die Firmware stellt `ä ö ü Ä Ö Ü` korrekt dar.

### Zieleinlauf und Abbruch durch den Starter (ab v0.13.0)

- **Zieleinlauf-Taster** (optional): wie den Starter per Drag & Drop auf „Zieleinlauf“ ziehen. Jeder Druck nach dem Start wird gesammelt; die **Bahnzeit bleibt die Hauptzeit**.
- Die gesammelten Zeiten werden automatisch der nächstliegenden Bahnzeit zugeordnet (höchstens 3 s Abstand). In der Spalte „Zieleinlauf“ steht die Abweichung (Zieleinlauf minus Bahn, ab 0,5 s rot).
- Geparkte (nicht zugeordnete) Zeiten erscheinen unter der Tabelle und lassen sich per Drag & Drop auf die Spalte „Zieleinlauf“ einer Bahn ziehen. Auch bereits zugeordnete Zeiten (automatisch oder händisch) lassen sich auf eine andere Bahn ziehen oder zurück in den Parkbereich ziehen; „✕“ parkt ebenfalls. Eine Zeit, die auf eine belegte Bahn fällt, ersetzt die dortige, diese wandert in den Parkbereich. Die Zuordnung ändert die Bahnzeiten nicht.
- Die Abweichung zur Bahnzeit wird ab dem Grenzwert gelb bzw. rot (Standard 0,5 s / 1 s, einstellbar unter Einstellungen → Grenzwerte).
- **Starter / Zieleinlauf (ab v0.14.0):** Einstellungen → Option „Starter-Taster erfasst zusätzlich den Zieleinlauf“. Der Starter-Taster behält die Starteransicht; der erste Druck startet, jeder weitere (auch bis 5 s nach Lauf-Ende) wird im Hintergrund als Zieleinlauf-Zeit gesammelt. Der Doppeldruck-Stopp entfällt dabei.
- **Übertragen (ab v0.13.2):** Der Button unter der Tabelle legt bei jedem Klick eine **neue Laufversion** an (Lauf 5/2, dann 5/3 …) und schickt sie an JAuswertung. Bahnen mit zugeordneter Zieleinlauf-Zeit bekommen diese, alle anderen Bahnen ihre normal gestoppte Zeit (ab v0.13.4). „Letzte Version zurücknehmen“ entfernt die jeweils neueste.
- Der Zieleinlauf-Taster nimmt auch schnelle Druckfolgen an (mehrere Schwimmer kurz hintereinander).
- **Zweiter Druck des Starters** bei laufender Uhr (frühestens 1,5 s nach dem Start) beendet den Lauf. Bahnen ohne Zeit bleiben leer; oben erscheint ein Hinweis.

## Einstellungen: WLAN, Zugang und Updates

### Grenzwerte (ab v0.12.5)

**Einstellungen → Grenzwerte**: Je Messwert (Akku, Spannung, Temperatur, Luftfeuchte, WLAN-Signal von Tastern; CPU-Temperatur, CPU-Last, Speicher, SD-Karte der Pis;
Temperatur, Luftfeuchte und WLAN des Ladekoffers) ein gelber und ein roter Wert. Danach richten sich die Schriftfarben in der Übersicht,
die Hinterlegung bei Bahnen und Tastern und die Balken oben. Bei „Wert darunter ist schlecht“ (Akku, Spannung, WLAN) muss der rote Wert kleiner oder gleich dem gelben sein, sonst umgekehrt.
**Standardwerte** setzt alles zurück. Gespeichert wird in den Einstellungen des Servers (`GET/POST /api/limits`).

### WLAN-Netze (ab v0.8.0)

**Einstellungen → WLAN-Netze**: Name und Kennwort von Koffer- und Bad-WLAN. Leeres Kennwortfeld = unverändert.
Ablauf nach **Übernehmen**:

1. Die online Taster holen sich die neuen Daten, speichern sie vor und bestätigen sie (Anzeige „n von m bestätigt“).
2. Erst wenn alle online Taster bestätigt haben, stellt jeder Pi sein WLAN um (`nmcli con modify ap …`, Dienst `stoppuhr-knoten`).
   Der Koffer-Pi nimmt das Koffer-WLAN, der Bad-Pi das Bad-WLAN, ein einzelner Pi das Koffer-WLAN.
3. Die Taster verlieren kurz die Verbindung, probieren dann die neuen Daten und übernehmen sie dauerhaft.

Hinweise:

- **Jetzt auch am Pi umstellen** erzwingt Schritt 2, auch wenn nicht alle Taster bestätigt haben.
  Taster, die offline waren, finden das Netz danach nicht mehr und müssen per USB neu geflasht werden.
- Die Verbindung zur Oberfläche bricht beim Umstellen kurz ab, wenn du über das umgestellte WLAN verbunden bist.
- Während eines Laufs gesperrt; nach dem ersten gestarteten Lauf nur nach Eintippen von `UPDATE`.
- Die Daten gehen im Klartext über das interne Netz an die Taster (`GET /api/display`, nur bekannte Taster).
- Voraussetzung: Die WLAN-Verbindung des Pi heißt `ap` (so legt sie `deploy/zwei-pi/install-zwei-pi.sh` an).
  Ändere eine WLAN-Verbindung von Hand, den Namen über `AP_CONNECTION` setzen.
- Taster mit Firmware vor `v0.12.0` bestätigen nicht; sie bleiben bei den alten Daten.

### Taster-Firmware (ab v0.7.0)

**Einstellungen → Taster-Firmware** listet die Firmware-Releases aus GitHub (`andreasschoeler93/Stoppuhr-2.0-Taster`, änderbar mit `FIRMWARE_REPO`).
Für die neuen Wiederholungs- und Prüfmechanismen zuerst beide Pis auf v0.42.0 und danach die Taster auf v0.20.0 aktualisieren; offene Ereignisse vor einem Neustart kontrollieren.
Für die Tastertoneinstellung zuerst beide Pis auf v0.43.0 und danach die Taster auf v0.21.0 aktualisieren.
Für die Ablehnungswarnung im Dashboard zuerst beide Pis auf mindestens v0.44.0 und danach die Taster auf v0.22.0 aktualisieren; ältere Pi-Versionen zeigen diese Warnung nicht an.
Für die Akku-Prozentglättung zuerst beide Pis auf mindestens v0.44.3 und danach die Taster auf v0.22.1 aktualisieren, damit die Prozentwarnung am Pi den ungeglätteten Wert verwendet.
**Auf Taster laden** speichert die `firmware.bin` unter `backend/firmware_cache/` (`FIRMWARE_DIR`) und bietet sie allen online Tastern an.
Diese laden sie vom Pi, prüfen die MD5 und starten neu. Ohne Internet stehen bereits gespeicherte Versionen zur Verfügung.

- Angeboten werden nur Releases ab `v0.11.0`.
- Das Update geht nur an Taster ohne Aufgabe (keiner Bahn, dem Starter oder dem Ziel zugeordnet, auch nicht vorgemerkt); zugeordnete Taster sind in der Liste grau. Ein Taster, der nach dem Verteilen zugeordnet wird, bekommt die Datei nicht mehr (ab v0.36.0).
- Während des Updates hält der Ladekoffer alle Startkontakte eingeschaltet, damit sich die Taster nicht ausschalten (Ladekoffer-Firmware ab v0.7.17). Die Zeit stellt man unter Einstellungen → „Startkontakte bei Taster-Update einschalten (s)“ ein (Standard 300, 0 = aus); sie endet früher, sobald alle Taster fertig sind. Der Pi meldet sie dem Koffer als `ota_hold_ms` in der Antwort auf `POST /api/charger`.
- Gesperrt, sobald ein Lauf gestartet wurde (nur mit `UPDATE`); ein Taster bekommt die Datei nie während eines Laufs.
- Fehlgeschlagene Updates stehen in der Tabelle. Releases entstehen automatisch, wenn im Taster-Repo ein Tag `vX.Y.Z` hochgeladen wird.

### Pi-Software (ab v0.7.1)

**Einstellungen → Pi-Software**: Version (Git-Tag ab `v0.5.1`) wählen und **Übernehmen und neu starten**.
Der Pi holt die Tags von GitHub, wechselt darauf (`git checkout`), installiert geänderte Abhängigkeiten und startet den Dienst neu (ca. 5 s).

- Erfordert ein Git-Checkout. Bei lokalen Änderungen im Ordner bricht der Wechsel mit Fehlermeldung ab.
- Gesperrt während eines Laufs; nach dem ersten gestarteten Lauf nur mit `UPDATE`.
- Wechselt nur den Pi, dessen Oberfläche du bedienst (im Zwei-Pi-Betrieb beide einzeln).
- Danach steht der Pi „detached“ auf dem Tag. Zurück zum Branch: `cd ~/apps/stoppuhr && git switch main`.
- Bleibt die Liste leer: `curl -s localhost:1999/api/pi-update/releases` zeigt Fehler (z. B. kein Internet beim Abholen der Tags). Voraussetzung ist Version ab v0.7.1.

## Versionierung

Schema `MAJOR.MINOR.PATCH`, die Version steht in `backend/app.py` (`APP_VERSION`). Jede Änderung erhöht sie und bekommt einen Tag:
`git tag vX.Y.Z && git push origin vX.Y.Z`. Der Verlauf steht in [CHANGELOG.md](CHANGELOG.md).

- **PATCH**: Fehlerkorrekturen
- **MINOR**: neue Funktionen, abwärtskompatibel
- **MAJOR**: grundlegende Änderungen; `1.0.0` = Wettkampf-Freigabe

Update auf dem Pi ohne Oberfläche:

```bash
cd ~/apps/stoppuhr && git fetch origin --tags && git switch main && git pull --ff-only origin main && sudo systemctl restart stoppuhr
```

## Projektstatus

Die aktuelle Softwareversion ist `v0.44.14`; die API kennzeichnet den Stand weiterhin als `stable-beta`.
Eine Versionsnummer, automatisierte Tests oder der Zwei-Pi-Failover sind keine Freigabe für einen Wettkampf.
Vor einem realen Einsatz die [Prüfung vor dem Wettkampf](#prüfung-vor-dem-wettkampf) durchführen und die bekannten
[Ausfallgrenzen](deploy/zwei-pi/README.md#bekannte-grenzen) berücksichtigen.
