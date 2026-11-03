"""Haelt die systemweit installierten Zwei-Pi-Skripte auf dem Stand des Git-Checkouts.

Ein Wechsel der Pi-Software (Git-Tag) aendert nur den Checkout, nicht /usr/local/bin und
/etc/systemd/system. Der Knoten-Dienst (root) gleicht das hier ab, damit neue Skripte und
Dienste (z. B. stoppuhr-alias) ohne erneutes install-zwei-pi.sh wirksam werden.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import Final

import pi_update

DEPLOY_DIR: Final[str] = os.path.join(pi_update.REPO_DIR, "deploy", "zwei-pi")
ENV_FILE: Final[str] = "/etc/stoppuhr-zwei-pi.env"
NAMES_ENV: Final[str] = "/etc/stoppuhr-namen.env"
# (Datei im Repository, Ziel, Rechte)
FILES: Final[list[tuple[str, str, int]]] = [
    ("stoppuhr-alias.sh", "/usr/local/bin/stoppuhr-alias.sh", 0o755),
    ("stoppuhr-rolle.sh", "/usr/local/bin/stoppuhr-rolle.sh", 0o755),
    ("stoppuhr-pruefen.sh", "/usr/local/bin/stoppuhr-pruefen.sh", 0o755),
    ("stoppuhr-alias.service", "/etc/systemd/system/stoppuhr-alias.service", 0o644),
]


def _read(path: str) -> bytes | None:
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except OSError:
        return None


def _run(cmd: list[str], timeout: int = 20) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)


def installed() -> bool:
    """Nur auf Pis, die mit install-zwei-pi.sh eingerichtet wurden."""
    return os.path.isfile(ENV_FILE) and os.path.isdir(DEPLOY_DIR)


def sync_files() -> bool:
    """Kopiert geaenderte Skripte und Dienstdateien; True, wenn sich etwas geaendert hat."""
    changed = False
    units_changed = False
    for name, target, mode in FILES:
        source = _read(os.path.join(DEPLOY_DIR, name))
        if source is None:
            continue
        # CRLF aus Windows-Checkouts vertragen Skripte nicht
        source = source.replace(b"\r\n", b"\n")
        if _read(target) == source:
            continue
        tmp = target + ".neu"
        with open(tmp, "wb") as fh:
            fh.write(source)
        os.chmod(tmp, mode)
        os.replace(tmp, target)
        changed = True
        units_changed = units_changed or target.endswith(".service")
    if not os.path.isfile(NAMES_ENV):
        with open(NAMES_ENV, "w", encoding="utf-8") as fh:
            fh.write("SHARED_NAME=stoppuhr\n")
        changed = True
    if units_changed:
        _run(["systemctl", "daemon-reload"])
    if shutil.which("avahi-publish-address") is None:
        # Best effort; ohne Internet bleibt es beim naechsten Durchlauf bei einem Hinweis im Log
        res = _run(["apt-get", "install", "-y", "avahi-utils"], timeout=180)
        if res.returncode != 0:
            print("avahi-utils konnte nicht installiert werden: " + (res.stderr or res.stdout)[-200:], flush=True)
        else:
            changed = True
    return changed


def _active(unit: str) -> str:
    return _run(["systemctl", "is-active", unit]).stdout.strip()


def ensure_alias(has_vip: bool) -> None:
    """Der gemeinsame Name gehoert dem Pi, der die gemeinsame Adresse hat (unabhaengig vom keepalived-Skript)."""
    state = _active("stoppuhr-alias")
    if has_vip and state in ("inactive", "failed"):
        _run(["systemctl", "start", "stoppuhr-alias"])
    elif not has_vip and state == "active":
        _run(["systemctl", "stop", "stoppuhr-alias"])
