"""Status des Ladekoffers: Die Ladeplatine meldet per POST /api/charger, die Oberflaeche liest ihn."""
from __future__ import annotations

import json
import threading
from typing import Any, Final, Optional

KEY: Final[str] = "CHARGER_STATUS"
SLOT_COUNT: Final[int] = 10
# Die Platine sendet alle 5 s; danach gilt sie als offline
OFFLINE_AFTER_MS: Final[int] = 30_000
# Die Meldung "Ladevorgang beendet" bleibt so lange stehen
ENDED_SHOWN_MS: Final[int] = 30 * 60_000
LIGHTS: Final[frozenset[str]] = frozenset({"off", "green", "yellow", "yellow_blink", "red", "red_blink"})

# Letzter Stand im Speicher, falls Redis gerade nicht schreibbar ist (z. B. Kopie im Zwei-Pi-Betrieb)
_memory: Optional[dict[str, Any]] = None
_lock = threading.Lock()


def _num(value: Any, lo: float, hi: float) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value != value or not lo <= value <= hi:  # NaN oder ausserhalb des Bereichs
        return None
    return float(value)


def _int(value: Any, lo: int, hi: int) -> Optional[int]:
    num = _num(value, lo, hi)
    return None if num is None else int(num)


def _text(value: Any, limit: int) -> str:
    return value[:limit] if isinstance(value, str) else ""


def sanitize(payload: Any) -> Optional[dict[str, Any]]:
    """Prueft die Meldung der Platine und gibt nur bekannte, begrenzte Felder zurueck."""
    if not isinstance(payload, dict) or not isinstance(payload.get("slots"), list):
        return None
    slots: dict[int, dict[str, Any]] = {}
    for raw in payload["slots"]:
        if not isinstance(raw, dict):
            continue
        n = _int(raw.get("n"), 1, SLOT_COUNT)
        if n is None:
            continue
        slots[n] = {
            "n": n,
            "charging": raw.get("charging") is True,
            # The charger cannot distinguish an empty slot from a battery by voltage alone.
            "fault": False,
            "vbat": _num(raw.get("vbat"), 0, 10),
            "since_s": _int(raw.get("since_s"), 0, 10**9),
        }
    light = payload.get("light")
    return {
        "mac": _text(payload.get("mac"), 32),
        "fw": _text(payload.get("fw"), 16),
        "uptime_s": _int(payload.get("uptime_s"), 0, 10**9),
        "rssi": _int(payload.get("rssi"), -150, 0),
        "temp": _num(payload.get("temp"), -50, 150),
        "humidity": _num(payload.get("humidity"), 0, 100),
        "current_a": _num(payload.get("current_a"), -0.8192, 0.8192)
        if payload.get("current_ok") is True and payload.get("current_saturated") is False else None,
        "current_ok": payload.get("current_ok") if isinstance(payload.get("current_ok"), bool) else None,
        "current_saturated": payload.get("current_saturated") is True,
        "aht_ok": payload.get("aht_ok") is True,
        "temp_alarm": payload.get("temp_alarm") is True,
        "i2c_ok": payload.get("i2c_ok") is True,
        "light": light if light in LIGHTS else "off",
        "fault": False,
        "muted": payload.get("muted") is True,
        "wake_active": payload.get("wake_active") is True,
        "slots": [slots[n] for n in sorted(slots)],
    }


def save(r: Any, status: dict[str, Any]) -> None:
    """Merkt den Stand im Speicher und (wenn moeglich) in Redis."""
    global _memory
    with _lock:
        _memory = status
    try:
        r.set(KEY, json.dumps(status, separators=(",", ":")))
    except Exception:  # noqa: BLE001
        pass


def load(r: Any) -> Optional[dict[str, Any]]:
    """Neuester bekannter Stand aus Speicher und Redis."""
    with _lock:
        best = _memory
    try:
        raw = r.get(KEY)
        stored = json.loads(raw) if raw else None
    except Exception:  # noqa: BLE001
        stored = None
    if isinstance(stored, dict) and (best is None or stored.get("ts", 0) > best.get("ts", 0)):
        best = stored
    return best


def reset_memory() -> None:
    global _memory
    with _lock:
        _memory = None


def _age_text(age_ms: int) -> str:
    minutes = age_ms // 60_000
    if minutes < 1:
        return "weniger als 1 Minute"
    if minutes < 60:
        return f"{minutes} Min."
    return f"{minutes // 60} Std. {minutes % 60} Min."


def _comma(value: float, dec: int = 1) -> str:
    return f"{value:.{dec}f}".replace(".", ",")


def evaluate(status: Optional[dict[str, Any]], now_ms: int) -> dict[str, Any]:
    """Leitet aus dem Stand Zustand und Statusmeldungen ab (level: error, warn, info, ok)."""
    if not status:
        return {"known": False, "online": False, "state": "unbekannt", "status": None, "messages": [],
                "counts": {"charging": 0}}
    slots = {s["n"]: s for s in status.get("slots", [])}
    charging = sorted(n for n, s in slots.items() if s["charging"])
    age = max(0, now_ms - int(status.get("ts") or 0))
    online = age <= OFFLINE_AFTER_MS
    messages: list[dict[str, str]] = []

    if not online:
        state = "offline"
        messages.append({"level": "warn", "text": f"Ladekoffer meldet sich nicht (zuletzt vor {_age_text(age)})."})
    else:
        if status.get("current_saturated"):
            messages.append({"level": "error", "text": "Stromsensor am Messbereichsende: Strom nicht messbar. 8,5/9,5 A werden nicht überwacht!"})
        elif status.get("current_ok") is False:
            messages.append({"level": "warn", "text": "Stromsensor nicht erreichbar oder keine frische Messung: Strom wird nicht überwacht."})
        elif status.get("current_ok") is True and status.get("current_a") is None:
            messages.append({"level": "warn", "text": "Stromsensor liefert keinen gültigen Messwert."})
        if status.get("temp_alarm"):
            temp = status.get("temp")
            extra = f" ({_comma(temp)} °C)" if temp is not None else ""
            messages.append({"level": "error", "text": f"Übertemperatur im Ladekoffer{extra}."})
        if not status.get("i2c_ok"):
            messages.append({"level": "error", "text": "Ladeplatine: Baustein MCP23017 antwortet nicht, Ladestatus unsicher."})
        if not status.get("aht_ok") and not status.get("temp_alarm"):
            messages.append({"level": "warn", "text": "Temperatursensor (AHT20) im Ladekoffer fehlt oder liefert nichts."})

        has_error = any(m["level"] == "error" for m in messages)
        if has_error:
            state = "fehler"
        elif charging:
            state = "laedt"
        else:
            state = "ruhig"

        # Sicher messbar ist nur "laedt" (rote LED des Lademoduls); "da" und "voll" nicht
        if charging:
            messages.append({"level": "info", "text": "Es wird geladen: Platz " + ", ".join(map(str, charging)) + "."})
        for n in sorted(slots):
            since = slots[n].get("since_s")
            if not slots[n]["charging"] and since is not None and since * 1000 + age <= ENDED_SHOWN_MS:
                messages.append({"level": "info", "text": f"Platz {n}: Ladevorgang beendet (vor {_age_text(since * 1000 + age)})."})

    return {
        "known": True,
        "online": online,
        "state": state,
        "age_ms": age,
        "status": status,
        "messages": messages,
        "counts": {"charging": len(charging)},
    }
