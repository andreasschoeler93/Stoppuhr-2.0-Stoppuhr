#!/usr/bin/env bash
set -euo pipefail

GROUP="cyfmac43455-sdio.bin"
LINK="/lib/firmware/brcm/brcmfmac43455-sdio.bin"
MINIMAL_FILE="/lib/firmware/cypress/cyfmac43455-sdio-minimal.bin"

if [ "$(id -u)" -ne 0 ]; then
  echo "Bitte mit sudo ausfuehren: sudo bash $0"
  exit 1
fi

MODEL="$(tr -d '\0' </proc/device-tree/model 2>/dev/null || true)"
if [[ "$MODEL" != *"Raspberry Pi 4 Model B"* ]]; then
  echo "Dieses Skript ist fuer Raspberry Pi 4 Model B vorgesehen; erkannt: ${MODEL:-unbekannt}."
  exit 1
fi

if [ ! -r "$MINIMAL_FILE" ]; then
  echo "Minimal-Firmware fehlt: $MINIMAL_FILE"
  echo "Pruefe das installierte Firmwarepaket firmware-brcm80211."
  exit 1
fi

if [ ! -e "$LINK" ]; then
  echo "WLAN-Firmware-Link fehlt: $LINK"
  exit 1
fi

ALTERNATIVES="$(update-alternatives --list "$GROUP" 2>/dev/null || true)"
MINIMAL="$(printf '%s\n' "$ALTERNATIVES" | grep -E '/cyfmac43455-sdio-minimal\.bin$' || true)"
if [ -z "$MINIMAL" ] || [ "$(printf '%s\n' "$MINIMAL" | wc -l)" -ne 1 ]; then
  echo "Die Minimal-Firmware ist nicht als update-alternative registriert."
  echo "Vorhandene Auswahl:"
  printf '%s\n' "$ALTERNATIVES"
  exit 1
fi

if [ -n "${SSH_CONNECTION:-}" ]; then
  SSH_CLIENT_IP="$(awk '{print $1}' <<<"$SSH_CONNECTION")"
  SSH_DEVICE="$(ip -o -4 route get "$SSH_CLIENT_IP" 2>/dev/null |
    sed -n 's/.* dev \([^ ]*\).*/\1/p' | head -n 1)"
  if [ "$SSH_DEVICE" = "wlan0" ]; then
    echo "SSH laeuft ueber wlan0. Bitte per Ethernet oder lokal fortfahren."
    exit 1
  fi
fi

MINIMAL_REAL="$(readlink -f "$MINIMAL")"
if [ "$(readlink -f "$LINK")" = "$MINIMAL_REAL" ]; then
  echo "Die Minimal-WLAN-Firmware ist bereits ausgewaehlt."
else
  update-alternatives --set "$GROUP" "$MINIMAL"
fi

SELECTED="$(readlink -f "$LINK")"
if [ "$SELECTED" != "$MINIMAL_REAL" ]; then
  echo "Fehler: Ausgewaehlt ist $SELECTED statt $MINIMAL_REAL."
  exit 1
fi

echo "Minimal-WLAN-Firmware ausgewaehlt: $SELECTED"
echo "Die Auswahl wird erst nach einem Neustart des Pi aktiv."
echo "Neustarte die Pis einzeln und ausserhalb eines Wettkampfs."
