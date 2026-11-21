# Erstinstallation: einzelner Raspberry Pi

Diese Anleitung installiert die Stoppuhr auf einem einzelnen Raspberry Pi. Der Pi betreibt die Weboberfläche und Redis; es gibt keinen Ersatz-Pi und keine automatische Ausfallübernahme.

> **Wichtig zum WLAN:** `deploy/install.sh` installiert die Stoppuhr-Software, richtet aber keinen WLAN-Zugangspunkt ein. Für diese Anleitung müssen Router oder Access Points die WLANs bereitstellen. Wenn du möchtest, dass der Raspberry Pi selbst das WLAN für die Taster bereitstellt, brauchst du eine dazu passende separate Access-Point-Konfiguration. Verwende dafür nicht `install-zwei-pi.sh`: Das Skript richtet Bridge, VIP und Zwei-Pi-Dienste ein.

## 1. Voraussetzungen und Zugangsdaten

- Raspberry Pi mit Raspberry Pi OS Lite (64 Bit), SD-Karte, Netzteil und Ethernet oder WLAN zum Heimnetz
- Heimnetz mit Internet für Installation und Software-/Firmware-Updates
- PC mit SSH-Client
- Zwei verschiedene, durch Router oder Access Points bereitgestellte 2,4-GHz-WLANs:
  - **Koffer-WLAN** für Taster ohne zugewiesene Rolle
  - **Bad-WLAN** für Taster mit zugewiesener Rolle
- Ein für den Pi reservierter DHCP-Lease oder eine korrekt konfigurierte feste LAN-IP. Die Taster müssen den Pi über diese Adresse erreichen können.

Die Zugangsdaten sind getrennt zu verwalten:

| Zugang | Einrichtung | Hinweis |
|---|---|---|
| Raspberry-Pi-Benutzer `stoppuhr` | Im Raspberry Pi Imager | Separates Kennwort für SSH und Betriebssystem |
| Koffer- und Bad-WLAN | Am Router/Access Point | SSID und Kennwort später exakt in der Taster-`secrets.h` eintragen |
| Zugang zur Weboberfläche | Beim ersten Öffnen der Stoppuhr | Benutzername und Kennwort; das Kennwort muss mindestens 6 Zeichen haben |
| `AUTH_SECRET` | Automatisch vom Server in Redis erzeugt | Nicht selbst setzen; wird auch für Sitzungen verwendet |

Für eine problemlose Konfiguration über die Software gelten für beide WLANs: SSID 1–32, Kennwort 8–63 druckbare ASCII-Zeichen; weder SSID noch Kennwort dürfen `"` oder `\` enthalten. Verwende für Pi, Weboberfläche und WLAN jeweils geeignete Kennwörter. `src/secrets.h` enthält WLAN-Zugangsdaten und darf nicht committet oder weitergegeben werden.

## 2. Raspberry Pi OS vorbereiten

1. Im Raspberry Pi Imager „Raspberry Pi OS Lite (64 Bit)“ auf die SD-Karte schreiben.
2. Unter den Imager-Einstellungen setzen:
   - Hostname: `stoppuhr-pi`
   - Benutzername: `stoppuhr`, eigenes sicheres Kennwort
   - SSH aktivieren
   - WLAN-Land: `DE`
3. SD-Karte einsetzen und den Pi per Ethernet mit dem Heimnetz verbinden. WLAN ist möglich, Ethernet ist für die Erstinstallation zuverlässiger.
4. Im Router die IP-Adresse des Pi reservieren. Die folgenden Beispiele nennen sie `<PI-IP>`; ersetze den Platzhalter durch die tatsächliche Adresse.
5. Per SSH verbinden: `ssh stoppuhr@<PI-IP>`.

## 3. Stoppuhr-Software installieren

Als Benutzer `stoppuhr` im SSH-Terminal ausführen:

```bash
sudo apt-get update
sudo apt-get install -y git
mkdir -p ~/apps
cd ~/apps
git clone https://github.com/andreasschoeler93/Stoppuhr-2.0-Stoppuhr.git stoppuhr
cd ~/apps/stoppuhr
bash deploy/install.sh
```

Das Skript installiert Python, Redis und chrony, erstellt `.venv` und richtet die Systemdienste `stoppuhr` und `stoppuhr-knoten` ein. Die Weboberfläche läuft auf Port `1999`.

Prüfen:

```bash
curl -s http://localhost:1999/api/version
systemctl is-active stoppuhr redis-server chrony
```

Die erste Abfrage muss die Pi-Softwareversion ausgeben; die Dienste sollten `active` melden. Im Browser auf einem Gerät im Heimnetz `http://<PI-IP>:1999` öffnen.

### Zeitdienst für die Taster freigeben

Die Taster brauchen einen erreichbaren Zeitserver. In `/etc/chrony/chrony.conf` die Netzadresse des WLANs der Taster freigeben; `<TASTER-NETZ/CIDR>` durch das tatsächliche Netz ersetzen, zum Beispiel `192.168.1.0/24`:

```conf
allow <TASTER-NETZ/CIDR>
```

Wenn der Pi keinen externen Zeitserver erreichen kann, zusätzlich `local stratum 10` eintragen. Danach:

```bash
sudo systemctl restart chrony
```

## 4. Taster-Firmware und `secrets.h` einrichten

1. Das Taster-Projekt aus [Stoppuhr-2.0-Taster](https://github.com/andreasschoeler93/Stoppuhr-2.0-Taster) auschecken.
2. Dort `src/secrets.example.h` nach `src/secrets.h` kopieren. Nur die lokale `secrets.h` bearbeiten; keine echten Kennwörter in der Beispieldatei speichern.
3. In `src/secrets.h` eintragen:
   - `SECRET_WIFI_SSID`: exakte SSID des Koffer-WLANs
   - `SECRET_WIFI_PASS`: exaktes Kennwort des Koffer-WLANs
   - `SECRET_WIFI2_SSID`: exakte SSID des Bad-WLANs
   - `SECRET_WIFI2_PASS`: exaktes Kennwort des Bad-WLANs
   - `SECRET_PI_IP`: die reservierte Pi-IP als String, zum Beispiel `"192.168.1.50"`. Stattdessen ist ein Hostname möglich, wenn er im Taster-WLAN zuverlässig auf die Pi-IP aufgelöst wird.
4. Weitere in `secrets.example.h` als erforderlich markierte Werte ebenfalls ausfüllen.
5. Den Taster per USB flashen:

```bash
pio run -e seeed_xiao_esp32s3 -t upload
```

6. Den Taster einschalten. Ohne Rolle verbindet er sich mit dem Koffer-WLAN. Nach einer Rollenzuweisung wechselt er ins Bad-WLAN. **Beide WLANs müssen daher verfügbar sein und Zugriff auf die Pi-IP haben.** Auch die Router- oder Access-Point-Konfiguration muss die Kommunikation zwischen den Taster-WLANs und dem Pi erlauben.

## 5. Erstanmeldung und Systemprüfung

1. Im Browser `http://<PI-IP>:1999` öffnen.
2. Beim ersten Aufruf einen Benutzernamen und ein Kennwort festlegen. Zugangsdaten sicher aufbewahren.
3. In der Stoppuhr-Oberfläche prüfen, dass der Taster online ist und seine Vitaldaten meldet.
4. Einen Taster testweise einer Rolle zuweisen. Er muss ins Bad-WLAN wechseln und weiter mit der Oberfläche kommunizieren können.
5. Einen vollständigen Testlauf durchführen und Zeiten sowie XML-Export mit einer unabhängigen Referenz vergleichen.

## 6. WLAN-Einstellungen und Firmware-Updates

- **Einstellungen → WLAN-Netze** verwaltet die zwei WLAN-Datensätze der Stoppuhr. Ein leeres Kennwortfeld bedeutet „bestehendes Kennwort beibehalten“. Eine WLAN-Änderung wird an Taster verteilt und kann deren Verbindung unterbrechen.
- In diesem Aufbau stellt der Router bzw. Access Point die WLANs bereit. Die WLAN-Einstellungen der Weboberfläche können den Pi-Zugangspunkt nur umstellen, wenn auf dem Pi eine passende NetworkManager-Verbindung namens `ap` vorhanden ist. Ändere die WLANs andernfalls am Router/Access Point und aktualisiere die Taster-Konfiguration entsprechend; erzwinge keine Pi-Umstellung.
- Taster-Firmware kann nach der ersten USB-Inbetriebnahme über **Einstellungen → Software und Firmware → Taster-Firmware** verteilt werden. Dazu müssen die Geräte online sein und die angezeigten Versionsvoraussetzungen erfüllen.
- Pi-Software kann in **Einstellungen → Software und Firmware** aktualisiert werden. Während des Updates ist die Oberfläche kurz nicht erreichbar. Updates nie während eines Laufs durchführen.

## 7. Betrieb, Sicherung und Fehlersuche

- Logs der Stoppuhr: `journalctl -u stoppuhr -f`
- Logs des Systemdienstes: `journalctl -u stoppuhr-knoten -f`
- Dienste prüfen: `systemctl status stoppuhr redis-server chrony`
- Oberfläche lokal prüfen: `curl -s http://localhost:1999/api/version`
- Pi-IP ermitteln: `hostname -I`
- Zugang zur Oberfläche vergessen: auf dem Pi `redis-cli del AUTH` ausführen und beim nächsten Aufruf neu einrichten. Das entfernt den Login-Eintrag, nicht die Wettkampfdaten.

Redis speichert regelmäßig Snapshots (`save 10 1`), was weder ein Backup noch eine Garantie für den Erhalt der letzten Änderungen bei Stromausfall ist. Sichere benötigte Daten regelmäßig außerhalb des Pi und teste die Wiederherstellung. Ein einzelner Pi hat keine automatische Ausfallübernahme.
