"""Aus vorhandenen Vitalverläufen gesicherte Minutenmittel je MAC."""
from __future__ import annotations

import json
import math
from collections import defaultdict
from typing import Any, Final

import device_logs
import vitals_history


KEY_PREFIX: Final[str] = "LONGTERM_VITALS:"
INTERVAL_MS: Final[int] = 60_000
FIELDS: Final[tuple[str, ...]] = vitals_history.FIELDS


def capture(store: Any, until: int) -> None:
    """Speichert abgeschlossene Minuten; wiederholte Übernahmen sind idempotent."""
    keys: dict[str, list[str]] = defaultdict(list)
    for key in store.scan_iter(match=vitals_history.KEY_PREFIX + "*"):
        mac = key[len(vitals_history.KEY_PREFIX):]
        if device_logs.valid_mac(mac):
            keys[mac.upper()].append(key)
    cutoff = until // INTERVAL_MS * INTERVAL_MS
    for mac, history_keys in keys.items():
        buckets: dict[int, dict[str, list[float]]] = {}
        for key in history_keys:
            for raw in store.lrange(key, 0, -1):
                point = json.loads(raw)
                if not isinstance(point, list) or len(point) != len(FIELDS) + 1:
                    raise ValueError(f"Ungültiger Vitalverlauf für {mac}")
                ts, *readings = point
                if type(ts) is not int:
                    raise ValueError(f"Ungültiger Zeitstempel im Vitalverlauf für {mac}")
                if ts < 0 or ts >= cutoff:
                    continue
                values = {
                    field: value for field, value in zip(FIELDS, readings)
                    if isinstance(value, (int, float)) and not isinstance(value, bool)
                    and math.isfinite(value)
                }
                if not values:
                    continue
                bucket = buckets.setdefault(ts // INTERVAL_MS, defaultdict(list))
                for field, value in values.items():
                    bucket[field].append(value)
        pipeline = store.pipeline(transaction=False)
        pending = 0
        for bucket, values in sorted(buckets.items()):
            means = {field: math.fsum(items) / len(items) for field, items in values.items()}
            payload = json.dumps(
                {"ts": bucket * INTERVAL_MS, **means}, separators=(",", ":"), allow_nan=False,
            )
            pipeline.hsetnx(KEY_PREFIX + mac, str(bucket), payload)
            pending += 1
            if pending == 500:
                pipeline.execute()
                pending = 0
        if pending:
            pipeline.execute()


def known(store: Any) -> list[str]:
    macs = set()
    for key in store.scan_iter(match=KEY_PREFIX + "*"):
        mac = key[len(KEY_PREFIX):]
        if device_logs.valid_mac(mac):
            macs.add(mac.upper())
    return sorted(macs)


def history(
    store: Any, mac: str, since: int | None = None, until: int | None = None,
) -> list[dict[str, Any]]:
    if not device_logs.valid_mac(mac):
        raise ValueError("Ungültige MAC-Adresse")
    entries = []
    for field, raw in store.hscan_iter(KEY_PREFIX + mac.upper()):
        if since is not None or until is not None:
            try:
                bucket_ts = int(field) * INTERVAL_MS
            except ValueError as exc:
                raise ValueError("Ungültiges Langzeit-Zeitfenster") from exc
            if (since is not None and bucket_ts < since) or (
                until is not None and bucket_ts >= until
            ):
                continue
        point = json.loads(raw)
        if not isinstance(point, dict) or type(point.get("ts")) is not int:
            raise ValueError("Ungültiger Langzeit-Messpunkt")
        if (since is not None and point["ts"] < since) or (
            until is not None and point["ts"] >= until
        ):
            continue
        entries.append(point)
    return sorted(entries, key=lambda point: point["ts"])
