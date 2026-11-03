"""Namen der beiden Pis und der gemeinsamen Adresse (Zwei-Pi-Betrieb).

Die Oberflaeche speichert die Namen in Redis (wird auf den Partner kopiert). Jeder Pi stellt seinen
eigenen Hostnamen (mDNS `<name>.local`) um und passt den gemeinsamen Namen fuer das Taster-Netz
(dnsmasq) und fuer das Router-Netz (Dienst stoppuhr-alias) an. Umgesetzt wird das in knoten_dienst.py.
"""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import time
from typing import Any, Final, Optional

NAMES_KEY: Final[str] = "NODE_NAMES"
DEFAULTS: Final[dict[str, str]] = {"koffer": "stoppuhr-koffer", "bad": "stoppuhr-bad", "shared": "stoppuhr"}
LABELS: Final[dict[str, str]] = {"koffer": "Koffer-Pi", "bad": "Bad-Pi", "shared": "Gemeinsamer Name"}
APPLIED_FILE: Final[str] = os.environ.get("NAMES_APPLIED_FILE", "/var/lib/stoppuhr-namen-version")
ENV_FILE: Final[str] = os.environ.get("NAMES_ENV_FILE", "/etc/stoppuhr-namen.env")
DNSMASQ_DIR: Final[str] = os.environ.get("DNSMASQ_DIR", "/etc/dnsmasq.d")
HOSTS_FILE: Final[str] = os.environ.get("HOSTS_FILE", "/etc/hosts")
_LABEL = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")


def normalize(names: dict[str, Any]) -> dict[str, str]:
    return {k: str(names.get(k, DEFAULTS[k])).strip().lower() for k in DEFAULTS}


def validate(names: dict[str, str]) -> Optional[str]:
    for key, value in names.items():
        if not _LABEL.match(value):
            return (f"{LABELS[key]}: 1 bis 63 Zeichen aus a–z, 0–9 und Bindestrich, "
                    "nicht am Anfang oder Ende ein Bindestrich")
    if len(set(names.values())) != len(names):
        return "Die drei Namen müssen verschieden sein"
    return None


def load(r: Any) -> Optional[dict[str, Any]]:
    """Gespeicherte Fassung oder None, solange nie etwas gespeichert wurde."""
    raw = r.get(NAMES_KEY)
    return json.loads(raw) if raw else None


def effective(cfg: Optional[dict[str, Any]]) -> dict[str, str]:
    return normalize((cfg or {}).get("names") or {})


def save(r: Any, names: dict[str, str]) -> dict[str, Any]:
    cfg = {"version": int(time.time()), "names": names}
    r.set(NAMES_KEY, json.dumps(cfg))
    return cfg


def applied_version() -> int:
    try:
        with open(APPLIED_FILE) as fh:
            return int(fh.read().strip() or 0)
    except (OSError, ValueError):
        return 0


def _run(cmd: list[str]) -> Optional[str]:
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=False)
    if res.returncode != 0:
        return (res.stderr or res.stdout).strip() or f"{cmd[0]} fehlgeschlagen"
    return None


def _set_hosts_entry(hostname: str) -> None:
    with open(HOSTS_FILE) as fh:
        lines = [ln for ln in fh.read().splitlines() if not ln.startswith("127.0.1.1")]
    lines.append(f"127.0.1.1 {hostname}")
    with open(HOSTS_FILE, "w") as fh:
        fh.write("\n".join(lines) + "\n")


def _write_dnsmasq(shared: str, vip: str) -> bool:
    """Gemeinsamen Namen fuer das Taster-Netz setzen. True, wenn dnsmasq neu gestartet werden muss."""
    if not os.path.isdir(DNSMASQ_DIR) or not vip:
        return False
    # Aeltere Installationen tragen den Namen fest in stoppuhr.conf
    legacy = os.path.join(DNSMASQ_DIR, "stoppuhr.conf")
    if os.path.exists(legacy):
        with open(legacy) as fh:
            kept = [ln for ln in fh.read().splitlines() if not ln.startswith("address=/")]
        with open(legacy, "w") as fh:
            fh.write("\n".join(kept) + "\n")
    with open(os.path.join(DNSMASQ_DIR, "stoppuhr-name.conf"), "w") as fh:
        fh.write(f"address=/{shared}/{vip}\n")
    return True


def apply_to_pi(cfg: dict[str, Any], kind: str) -> Optional[str]:
    """Namen auf diesem Pi umsetzen. Fehlertext oder None. Muss als root laufen."""
    if kind not in ("koffer", "bad"):
        return None
    names = effective(cfg)
    own, shared = names[kind], names["shared"]
    try:
        alias_was_active = subprocess.run(
            ["systemctl", "is-active", "--quiet", "stoppuhr-alias"], check=False).returncode == 0
        renamed = socket.gethostname() != own
        if renamed:
            problem = _run(["hostnamectl", "set-hostname", own])
            if problem:
                return problem
            _set_hosts_entry(own)
        with open(ENV_FILE, "w") as fh:
            fh.write(f"SHARED_NAME={shared}\n")
        restart_dns = _write_dnsmasq(shared, os.environ.get("VIP", ""))
        if renamed:
            _run(["systemctl", "restart", "avahi-daemon"])
        if restart_dns:
            _run(["systemctl", "restart", "dnsmasq"])
        # Der Dienst wird mit Avahi beendet bzw. kennt den alten Namen noch
        if alias_was_active:
            _run(["systemctl", "restart", "stoppuhr-alias"])
        with open(APPLIED_FILE, "w") as fh:
            fh.write(str(cfg["version"]))
    except (OSError, subprocess.SubprocessError) as exc:
        return str(exc)
    return None
