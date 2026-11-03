#!/usr/bin/env bash
# Zeigt auf einem Pi, warum die Uebernahme (nicht) klappt. Aufruf: bash deploy/zwei-pi/stoppuhr-diagnose.sh
source /etc/stoppuhr-zwei-pi.env 2>/dev/null
echo "== Rolle: ${ROLLE:-?}  Partner: ${PEER_IP:-?}  VIP: ${VIP:-?}"
echo "== Adresse $VIP auf diesem Pi?"; ip -4 addr show | grep -q " ${VIP}/" && echo ja || echo nein
echo "== Letzter Rollenwechsel"; cat /var/lib/stoppuhr-rollenwechsel 2>/dev/null; date +%s
echo "== Dienste"
for u in keepalived stoppuhr stoppuhr-knoten stoppuhr-alias avahi-daemon dnsmasq redis-server; do
  printf '%-18s %s\n' "$u" "$(systemctl is-active "$u")"
done
echo "== Installierte Skripte"; ls -l /usr/local/bin/stoppuhr-*.sh /etc/systemd/system/stoppuhr-alias.service 2>&1
echo "== Redis"; redis-cli info replication | grep -E 'role|master_link_status|master_host'
echo "== Namen"; cat /etc/stoppuhr-namen.env 2>&1; hostname
echo "== keepalived (letzte 30 Zeilen)"; journalctl -u keepalived --no-pager -n 30
echo "== Alias (letzte 15 Zeilen)"; journalctl -u stoppuhr-alias --no-pager -n 15
echo "== Knoten-Dienst (letzte 15 Zeilen)"; journalctl -u stoppuhr-knoten --no-pager -n 15
