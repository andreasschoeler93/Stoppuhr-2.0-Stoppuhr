"""Bounded diagnostic log snapshots reported by embedded devices."""
from __future__ import annotations

import json
import logging
import re
import threading
from collections import OrderedDict
from typing import Any, Final, Optional

MAX_ENTRIES: Final[int] = 24
MAX_TEXT_LENGTH: Final[int] = 180
MAX_DEVICES: Final[int] = 32
SNAPSHOT_TTL_SECONDS: Final[int] = 30 * 24 * 60 * 60
MAC_PATTERN: Final[re.Pattern[str]] = re.compile(r"(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}\Z")
_memory: OrderedDict[str, dict[str, Any]] = OrderedDict()
_lock = threading.Lock()
logger = logging.getLogger(__name__)


def _snapshot_key(kind: str, mac: str) -> str:
    return "DEVICE_LOGS:charger" if kind == "charger" else f"DEVICE_LOGS:taster:{mac.upper()}"


def _sanitize_entries(raw: Any) -> Optional[list[dict[str, Any]]]:
    if not isinstance(raw, list):
        return None
    entries: list[dict[str, Any]] = []
    for entry in raw[-MAX_ENTRIES:]:
        if not isinstance(entry, dict):
            continue
        uptime_ms = entry.get("ms")
        text = entry.get("text")
        if isinstance(uptime_ms, bool) or not isinstance(uptime_ms, int) or not 0 <= uptime_ms <= 0xFFFFFFFF:
            continue
        if not isinstance(text, str) or not text:
            continue
        clean_text = "".join(char if char.isprintable() else " " for char in text)[:MAX_TEXT_LENGTH].strip()
        if clean_text:
            entries.append({"ms": uptime_ms, "text": clean_text})
    return entries


def valid_mac(value: Any) -> bool:
    return isinstance(value, str) and MAC_PATTERN.fullmatch(value) is not None


def save_snapshot(
    store: Any,
    kind: str,
    mac: Any,
    fw: Any,
    uptime_s: Any,
    raw_entries: Any,
    received_ts: int,
) -> bool:
    """Validate and retain a bounded device-side ring-buffer snapshot."""
    if kind not in {"taster", "charger"} or not valid_mac(mac):
        return False
    entries = _sanitize_entries(raw_entries)
    if entries is None:
        return False
    uptime = uptime_s if isinstance(uptime_s, int) and not isinstance(uptime_s, bool) else None
    snapshot = {
        "kind": kind,
        "mac": mac.upper(),
        "fw": fw[:16] if isinstance(fw, str) else "",
        "uptime_s": max(0, min(uptime, 10**9)) if uptime is not None else None,
        "received_ts": received_ts,
        "entries": entries,
    }
    key = _snapshot_key(kind, mac)
    with _lock:
        _memory[key] = snapshot
        _memory.move_to_end(key)
        while len(_memory) > MAX_DEVICES:
            _memory.popitem(last=False)
    try:
        store.set(key, json.dumps(snapshot, separators=(",", ":")), ex=SNAPSHOT_TTL_SECONDS)
    except Exception:  # noqa: BLE001
        logger.warning("Diagnose-Logs für %s konnten nicht in Redis gespeichert werden", kind)
    return True


def load_snapshot(store: Any, kind: str, mac: str) -> Optional[dict[str, Any]]:
    if kind != "taster" or not valid_mac(mac):
        return None
    key = _snapshot_key(kind, mac)
    with _lock:
        snapshot = _memory.get(key)
    try:
        raw = store.get(key)
        stored = json.loads(raw) if raw else None
    except Exception:  # noqa: BLE001
        logger.warning("Diagnose-Logs für Taster konnten nicht aus Redis gelesen werden")
        stored = None
    if isinstance(stored, dict) and (snapshot is None or stored.get("received_ts", 0) > snapshot.get("received_ts", 0)):
        snapshot = stored
    return snapshot


def load_charger_snapshot(store: Any) -> Optional[dict[str, Any]]:
    with _lock:
        snapshot = _memory.get("DEVICE_LOGS:charger")
    stored = _load_key(store, "DEVICE_LOGS:charger")
    if isinstance(stored, dict) and (snapshot is None or stored.get("received_ts", 0) > snapshot.get("received_ts", 0)):
        snapshot = stored
    return snapshot


def _load_key(store: Any, key: str) -> Optional[dict[str, Any]]:
    try:
        raw = store.get(key)
        value = json.loads(raw) if raw else None
    except Exception:  # noqa: BLE001
        logger.warning("Diagnose-Logs für Ladekoffer konnten nicht aus Redis gelesen werden")
        return None
    return value if isinstance(value, dict) else None


def reset_memory() -> None:
    with _lock:
        _memory.clear()
