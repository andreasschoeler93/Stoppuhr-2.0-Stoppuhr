#!/usr/bin/env bash
# Veroeffentlicht den gemeinsamen Namen (mDNS, z. B. stoppuhr.local) mit der Router-Adresse dieses Pi.
# Laeuft nur auf dem Pi, der gerade arbeitet; stoppuhr-rolle.sh startet und stoppt den Dienst.
# Beim Beenden sendet avahi-publish ein Goodbye-Paket, der Partner kann den Namen danach uebernehmen.
source /etc/stoppuhr-zwei-pi.env
[ -f /etc/stoppuhr-namen.env ] && source /etc/stoppuhr-namen.env

NAME="${SHARED_NAME:-stoppuhr}.local"
LAN_IF="${LAN_IF:-eth0}"
IP="$(ip -4 -o addr show dev "$LAN_IF" scope global | awk '{split($4, a, "/"); print a[1]; exit}')"
if [ -z "$IP" ]; then
  echo "Keine IPv4-Adresse auf $LAN_IF gefunden." >&2
  exit 1
fi
exec avahi-publish-address -R "$NAME" "$IP"
