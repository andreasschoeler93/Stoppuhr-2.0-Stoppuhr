# Erstinstallation: zwei Raspberry Pis (Koffer-Pi und Bad-Pi)

Diese Anleitung richtet beide Pis von Grund auf ein. Ergebnis: Der Koffer-Pi arbeitet, der Bad-Pi hält eine Kopie und übernimmt bei einem Ausfall.
Vom Heimnetz aus erreichst du die Oberfläche danach unter `http://stoppuhr.local:1999`. Ein Gerät, das mit einem der Taster-WLANs verbunden ist, erreicht sie unter `http://stoppuhr:1999` oder `http://192.168.50.10:1999`.
Für einen einzelnen Pi mit WLANs über einen vorhandenen Router oder Access Point siehe die [Einzel-Pi-Anleitung](INSTALLATION-EINZEL-PI.md).

> Der automatische Wechsel ist keine Garantie für verlustfreie Ergebnisse: Redis repliziert asynchron. Ein bestätigter Tastendruck kann bei einem Pi-Ausfall fehlen, wenn er noch nicht auf dem anderen Pi angekommen ist. Vor jedem Einsatz die Testreihenfolge am Ende durchführen und Ergebnisse nach einer Störung prüfen.

## 0. Überblick

| Was | Koffer-Pi | Bad-Pi |
|---|---|---|
| Rolle (Argument des Skripts) | `koffer` | `bad` |
| Hostname nach der Zwei-Pi-Einrichtung | `stoppuhr-koffer` | `stoppuhr-bad` |
| Feste Adresse (Taster-Netz) | 192.168.50.11 | 192.168.50.12 |
| Eigenes WLAN (versteckt, WPA2) | Koffer-WLAN | Bad-WLAN |
| WLAN-Band/Kanal | 2,4 GHz / Kanal 1 | 2,4 GHz / Kanal 11 |
| DHCP-Bereich | .100–.149 | .150–.199 |
| Normalerweise | arbeitet | Kopie, Notbetrieb |

Bei zu wenigen gleichzeitigen WLAN-Clients kann auf jedem Raspberry Pi 4B die AP-optimierte CYW43455-Minimal-Firmware ausgewählt werden. Hinweise und Rückweg stehen in [deploy/zwei-pi/README.md](../deploy/zwei-pi/README.md#mehr-wlan-clients-am-raspberry-pi-4b).

Gemeinsame Adresse (VIP): **192.168.50.10**. Sie liegt immer auf dem Pi, der gerade arbeitet.

## 1. Was du brauchst

- 2 × Raspberry Pi mit WLAN (getestet mit Raspberry Pi OS Lite, Debian 13 „trixie“), SD-Karten, Netzteile
- 1 × Netzwerkkabel zwischen den beiden Pis (direkt oder über einen Switch)
- Heimnetz mit Internet, **nur für die Installation**
- Zwei verschiedene WLAN-Namen und zwei verschiedene Kennwörter. Für eine problemlose Einrichtung und spätere Änderungen über die Oberfläche: SSID 1–32, Kennwort 8–63 druckbare ASCII-Zeichen; weder Wert darf `"` oder `\` enthalten. Dieselben Werte kommen in die Taster-`secrets.h` (Schritt 8).
- Benutzername und Kennwort für die spätere Anmeldung an der Stoppuhr-Oberfläche. Das Kennwort muss mindestens 6 Zeichen lang sein.
- PC mit SSH (PuTTY oder `ssh`)

### Zugangsdaten auseinanderhalten

Diese Kennwörter sind **nicht** austauschbar:

| Zugang | Wo wird er eingerichtet? | Zweck |
|---|---|---|
| Raspberry-Pi-Benutzer `stoppuhr` | Im Raspberry Pi Imager; auf beiden Pis separat | SSH und Anmeldung am Betriebssystem |
| Koffer-WLAN und Bad-WLAN | Beim Installieren jedes Pi als `AP_SSID` / `AP_PSK`; später auch in der Weboberfläche und der Taster-`secrets.h` | WLAN-Zugang der Taster |
| Weboberfläche | Einmalig beim ersten Öffnen der aktiven Stoppuhr | Anmeldung; der Kennwort-Hash wird in Redis gespeichert und im Zwei-Pi-Betrieb repliziert |
| Sitzungsgeheimnis `AUTH_SECRET` | Automatisch vom Pi erzeugt und in Redis gespeichert | Signieren der Web-Sitzungen; nicht selbst erzeugen oder in eine Datei kopieren |

Verwende für SSH und Weboberfläche eigene Kennwörter. WLAN-Kennwörter müssen auf Pi und Taster exakt übereinstimmen. `src/secrets.h` enthält WLAN-Zugangsdaten: nicht in Git einchecken, veröffentlichen oder in Supportmeldungen kopieren.

## 2. Betriebssystem vorbereiten (je Pi)

1. Mit dem Raspberry Pi Imager „Raspberry Pi OS Lite (64 Bit)“ auf die SD-Karte schreiben (getestet mit Debian 13 „trixie“).
2. In den Einstellungen des Imagers setzen: zunächst Hostname `koffer-pi` bzw. `bad-pi`, Benutzer `stoppuhr` mit eigenem Kennwort, SSH aktivieren und WLAN-Land `DE`.
3. Beide Pis starten und **jeweils per Ethernet mit demselben Heimnetz mit Internet verbinden**. Noch nicht das Kabel zwischen den Pis als einziges Netzwerk verwenden.
4. Per SSH verbinden, zum Beispiel `ssh stoppuhr@koffer-pi.local` bzw. `ssh stoppuhr@bad-pi.local` (oder die IP aus der Router-Liste). Während der gesamten Einrichtung die Zugangsdaten des Imager-Benutzers verwenden.

## 3. Software installieren (je Pi, einzeln)

```bash
sudo apt-get update
sudo apt-get install -y git
mkdir -p ~/apps
cd ~/apps
git clone https://github.com/andreasschoeler93/Stoppuhr-2.0-Stoppuhr.git stoppuhr
cd stoppuhr
bash deploy/install.sh
```

Das Skript installiert Python, Redis und chrony, legt die Python-Umgebung an und startet `stoppuhr` und `stoppuhr-knoten`. Es setzt Redis auf lokale Speicherung (`save 10 1`) und legt keine selbst zu erstellende `.env`- oder Secret-Datei an. Danach läuft die Oberfläche zunächst auf `http://<LAN-IP des Pi>:1999`. Prüfen: `curl -s http://localhost:1999/api/version`.

Ein Fehler „Permission denied“ bei `.venv` bedeutet meist, dass die Umgebung zuvor als `root` angelegt wurde. Besitzer korrigieren und die Umgebung neu anlegen:
`sudo chown -R stoppuhr:stoppuhr ~/apps/stoppuhr && rm -rf ~/apps/stoppuhr/.venv`, danach `bash deploy/install.sh` wiederholen.

Die beiden Pis müssen für diese Anleitung dieselbe Softwareversion haben. Für den aktuellen Branch `main` bleiben. Eine bestimmte Version stattdessen auf **beiden** Pis auschecken, zum Beispiel `git fetch --tags && git checkout v0.44.12` (oder nach der Einrichtung über Einstellungen → Software und Firmware).

## 4. Zwei-Pi-Betrieb einrichten

Führe diesen Schritt **per SSH über das Kabel (`eth0`) oder am Monitor** aus. Das Skript bricht ab, wenn deine Sitzung über das WLAN läuft.
`eth0` bleibt am Router (DHCP), die SSH-Sitzung reißt also nicht ab. Beide Pis müssen dazu im Router-Netz hängen.
Dein PC bleibt unverändert im Heimnetz; eine feste IP ist nicht nötig. Nach dem Skript erreichst du die Pis per SSH als
`ssh stoppuhr@stoppuhr-koffer.local` bzw. `ssh stoppuhr@stoppuhr-bad.local`. Die Oberfläche des gerade arbeitenden Pi erreichst du im Heimnetz über `http://stoppuhr.local:1999`. `http://192.168.50.10:1999` funktioniert nur aus dem Taster-Netz, nicht normalerweise von einem PC im Heimnetz.
Die Taster-WLANs sind davon getrennt und haben kein Internet.

### 4a. Koffer-Pi

Eine vorhandene alte Zugangspunkt-Verbindung vorher löschen (z. B. aus einem Einzelbetrieb): `nmcli con show`, dann `sudo nmcli con delete <Name>`.

```bash
cd ~/apps/stoppuhr
read -r -p "Name des Koffer-WLANs (SSID): " AP_SSID
read -r -s -p "Kennwort des Koffer-WLANs: " AP_PSK; echo
export AP_SSID AP_PSK
bash deploy/zwei-pi/install-zwei-pi.sh koffer
unset AP_SSID AP_PSK
```

Die Eingabe per `read` vermeidet, dass das Kennwort selbst im Shell-Befehl und damit in der Shell-History steht. NetworkManager speichert es anschließend im WLAN-Verbindungsprofil, damit der Zugangspunkt nach einem Neustart wieder startet.

### 4b. Bad-Pi

```bash
cd ~/apps/stoppuhr
read -r -p "Name des Bad-WLANs (SSID): " AP_SSID
read -r -s -p "Kennwort des Bad-WLANs: " AP_PSK; echo
export AP_SSID AP_PSK
bash deploy/zwei-pi/install-zwei-pi.sh bad
unset AP_SSID AP_PSK
```

Die Zugangspunkte sind auf 2,4 GHz festgelegt. Koffer verwendet Kanal 1, Bad Kanal 11. Die Kanäle 1, 6 und 11 sind die üblichen nicht überlappenden Kanäle. Einen anderen Kanal (1, 6 oder 11) nur nach einem Scan der WLAN-Umgebung vor Ort wählen; den passenden Aufruf dann mit `AP_CHANNEL=6 bash deploy/zwei-pi/install-zwei-pi.sh koffer` bzw. `... bad` ergänzen.

Das Skript erledigt:

- Bridge `br0` mit fester Adresse, versteckter WLAN-Zugangspunkt (`ap`) und VXLAN-Tunnel `vxlan0` zum anderen Pi (über `eth0`, nur Taster-Verkehr). `eth0` selbst bleibt per DHCP am Router. Kommt die Bridge nicht hoch, wird das Taster-Netz wieder entfernt.
- Hostname `stoppuhr-koffer` bzw. `stoppuhr-bad` und Avahi (`.local`-Namen im Router-Netz)
- Redis im internen Netz erreichbar; der Bad-Pi wird Kopie (`replicaof 192.168.50.11`)
- Rolle in `/etc/stoppuhr-zwei-pi.env`
- keepalived (Koffer-Pi Priorität 150, Bad-Pi 100) für die gemeinsame Adresse
- chrony (beide Pis sind Zeitserver, der Bad-Pi gleicht sich am Koffer-Pi ab)
- dnsmasq (DHCP und der Name `stoppuhr` → 192.168.50.10)
- schaltet den Dienst `stoppuhr` auf Start durch keepalived um

Andere Taster-Netz-Adressen oder ein anderer gemeinsamer Name: `VIP=`, `KOFFER_IP=`, `BAD_IP=`, `NAME=` vor den Aufruf setzen (auf beiden Pis gleich). Wenn Multicast im Heimnetz nicht funktioniert, stattdessen auf **beiden** Pis `VXLAN_REMOTE=<feste LAN-IP des anderen Pi>` setzen; für beide LAN-IPs DHCP-Reservierungen im Router einrichten.

### Bereits eingerichtete Pis auf 2,4 GHz umstellen

Nach dem Software-Update auf **jedem Pi einzeln per Ethernet-SSH oder am Monitor** ausführen, nicht während eines Wettkampfs. Das Skript setzt das WLAN-Band und startet den jeweiligen Zugangspunkt neu; die Tasterverbindung ist dabei kurz unterbrochen.

```bash
cd ~/apps/stoppuhr
sudo bash deploy/zwei-pi/wlan-kanal-setzen.sh
```

Standardmäßig erhält der Koffer-Pi Kanal 1 und der Bad-Pi Kanal 11. Optional kann als Argument 1, 6 oder 11 übergeben werden. Vor einer abweichenden Kanalwahl die Belegung vor Ort prüfen. Der Tunnel zwischen den Pis läuft über Ethernet und wird durch die Änderung nicht auf 2,4 GHz umgestellt.

## 5. Prüfen

Auf jedem Pi:

```bash
cat /etc/stoppuhr-zwei-pi.env            # ROLLE=koffer bzw. bad
ip -4 addr show br0                      # Koffer-Pi: .11 (und .10, wenn er arbeitet); Bad-Pi: .12
nmcli -f NAME,DEVICE con show --active   # br0, vxlan0, ap, dazu die LAN-Verbindung (eth0)
systemctl is-active stoppuhr-knoten keepalived dnsmasq redis-server
redis-cli info replication | head -5     # Koffer: role:master, Bad: role:slave und master_link_status:up
```

Im Heimnetz `http://stoppuhr.local:1999` öffnen. Alternativ ein Gerät mit einem der Taster-WLANs verbinden und `http://stoppuhr:1999` aufrufen:

1. Beim ersten Öffnen **Benutzername und Kennwort festlegen** (mindestens 6 Zeichen). Nur auf dem aktiven Pi ist die Ersteinrichtung möglich. Der Zugang wird in Redis angelegt und bei erfolgreicher Replikation auch auf dem Bad-Pi verfügbar.
2. Tab **Vitaldaten → Systemstatus**: Koffer-Pi „arbeitet“, Bad-Pi „Bereitschaft“, Daten „Kopie (synchron)“.

## 6. Einstellungen in der Oberfläche

- **WLAN-Netze:** Trage dieselben beiden SSIDs ein. Beim ersten Speichern kann das Kennwort eingetragen werden; ein leeres Kennwortfeld bedeutet „bestehendes Kennwort unverändert lassen“. Die Pis wechseln ihr WLAN erst, wenn alle gerade online befindlichen Taster die neuen Daten bestätigt haben. Offline-Taster können sonst den Zugang verlieren und müssen per USB neu geflasht werden. Nicht während eines Laufs ändern.
- **Namen der Pis:** Die Voreinstellungen sind `stoppuhr-koffer`, `stoppuhr-bad` und `stoppuhr`. Nur Kleinbuchstaben, Ziffern und Bindestrich verwenden.
- **Zugang zur Oberfläche:** Benutzername und Kennwort lassen sich hier ändern. Den Zugang sicher aufbewahren; bei Verlust muss der `AUTH`-Eintrag in Redis manuell gelöscht und neu eingerichtet werden.
- **Software und Firmware:** Aktuelle Pi-Versionen und Releases sind dort sichtbar. Updates nur außerhalb eines Wettkampfs ausführen. Im Zwei-Pi-Betrieb wird jeder Pi separat aktualisiert; bei Firmware-Kompatibilitätsangaben zuerst beide Pis und danach die Geräte aktualisieren.

## 7. Taster einrichten

1. Das Taster-Projekt aus [Stoppuhr-2.0-Taster](https://github.com/andreasschoeler93/Stoppuhr-2.0-Taster) auschecken und dessen `src/secrets.example.h` als `src/secrets.h` kopieren. Die Datei enthält private Gerätekonfiguration und darf nicht committet oder weitergegeben werden.
2. Werte eintragen:
   - `SECRET_WIFI_SSID` / `SECRET_WIFI_PASS`: **exakt** die SSID und das Kennwort des Koffer-WLANs.
   - `SECRET_WIFI2_SSID` / `SECRET_WIFI2_PASS`: **exakt** die SSID und das Kennwort des Bad-WLANs.
   - `SECRET_PI_IP`: `"192.168.50.10"` (empfohlen: gemeinsame VIP) oder `"stoppuhr"` (nur wenn der Taster den DNS-Namen auflösen kann).
3. Projektabhängige weitere Pflichtwerte aus `secrets.example.h` ausfüllen. Keine echten Zugangsdaten in Beispiel- oder Dokumentationsdateien eintragen.
4. Taster per USB flashen: `pio run -e seeed_xiao_esp32s3 -t upload`. Danach den Taster einschalten. Er sollte im Koffer-WLAN in der Oberfläche erscheinen und bekommt dort einen Buchstaben.
5. Nach der ersten USB-Inbetriebnahme können unterstützte Updates und WLAN-Änderungen über die Pi-Oberfläche verteilt werden. Firmware-Updates müssen mit der im Abschnitt **Software und Firmware** genannten Reihenfolge und den erforderlichen Mindestversionen erfolgen.

Die Zugangsdaten für den Ladekoffer sind getrennt von den Taster-`secrets.h`. Bei der allerersten Inbetriebnahme muss der Ladekoffer einmal per USB mit seiner eigenen Konfigurationsdatei eingerichtet werden. Welche Werte erforderlich sind, steht in der Firmware-Dokumentation des Repositories `Ladekoffer`; danach kann die Firmware über die Pi-Oberfläche aktualisiert werden.

## 8. Testreihenfolge vor dem Einsatz

1. Unter **Vitaldaten → Systemstatus** prüfen: Koffer-Pi „arbeitet“, Bad-Pi „Bereitschaft“, Daten synchron.
2. Taster ohne Rolle einschalten: Er ist im Koffer-WLAN. Rolle zuweisen: Er wechselt ins Bad-WLAN.
3. Testlauf starten, Zeiten messen.
4. Koffer-Pi vom Strom trennen: Nach wenigen Sekunden sollte der Bad-Pi übernehmen. Prüfen, ob ein Lauf gestartet werden kann und alle erwarteten Daten vorhanden sind. **Ein erfolgreicher Wechsel garantiert nicht, dass die zuletzt bestätigten Schreibvorgänge übernommen wurden.**
5. Koffer-Pi wieder einschalten: Replikation und Rollenwechsel beobachten; beide Systeme müssen wieder synchron sein. Ergebnisse mit dem Testprotokoll vergleichen.
6. Kabel zwischen den Pis und WLAN-Unterbrechungen nur in einem Testfenster prüfen. Anschließend den Wettkampf beenden und kontrollieren, dass die Taster zurück ins Koffer-WLAN wechseln.

## 9. Updates

Ohne Oberfläche, auf jedem Pi:

```bash
cd ~/apps/stoppuhr && git fetch origin --tags && git switch main && git pull --ff-only origin main
bash deploy/install.sh                 # nur nötig, wenn sich Installationsdateien geändert haben (siehe CHANGELOG)
sudo systemctl restart stoppuhr-knoten
sudo systemctl restart stoppuhr        # beim Bad-Pi startet keepalived den Dienst nur bei Bedarf; dann überspringen
```

## 10. Fehlersuche

| Problem | Ursache und Hilfe |
|---|---|
| `install.sh`: Permission denied bei `.venv` | Ordner gehört `root`: Besitzer korrigieren und `.venv` löschen, siehe Schritt 3 |
| Installer: „Du bist per WLAN verbunden“ | Per Kabel oder Monitor ausführen |
| Pi nach dem Umbau nicht erreichbar | `ping stoppuhr-koffer.local` bzw. IP in der Router-Liste suchen. Notfalls mit Monitor: `sudo nmcli con delete ap vxlan0 br0 br0-eth0` und `sudo nmcli con up "Wired connection 1"` |
| Redis startet nicht | `journalctl -xeu redis-server`; neueste Version des Skripts holen (`git pull`) |
| Bad-Pi: `master_link_status:down` | Beide Pis im selben Router-Netz? `ping 192.168.50.11` (läuft über den Tunnel). Hilft nichts: Multicast geht nicht durch den Router, dann `VXLAN_REMOTE=<LAN-IP des anderen Pi>` beim Skriptaufruf setzen (beide Pis, Router-Adresse reservieren) |
| Beide Pis „arbeiten“ | Kabel nicht verbunden. Nach dem Anstecken gewinnt der Koffer-Pi |
| Name `stoppuhr` löst nicht auf | Im Taster-WLAN `http://192.168.50.10:1999` verwenden. Im Heimnetz `http://stoppuhr-koffer.local:1999` oder `http://stoppuhr-bad.local:1999` versuchen (Port 1999 nur auf dem aktiven Pi) |
| Kennwort der Oberfläche vergessen | Auf dem Koffer-Pi `redis-cli del AUTH`, dann neu festlegen |
| WLAN-Umstellung wirkt nicht | Verbindung heißt nicht `ap`: `AP_CONNECTION=<Name>` mit `sudo systemctl edit stoppuhr-knoten` setzen (`[Service]`, `Environment=AP_CONNECTION=<Name>`) |
| Logs | `journalctl -u stoppuhr -f`, `journalctl -u stoppuhr-knoten -f`, `journalctl -u keepalived -f` |

Hintergründe, Taster-Tausch und Grenzen: [deploy/zwei-pi/README.md](../deploy/zwei-pi/README.md).
