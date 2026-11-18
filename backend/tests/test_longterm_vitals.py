import copy
import csv
import io
import json
import unittest
from unittest.mock import patch

import app as stopwatch
import longterm_vitals
import redis
import vitals_history


MAC = "AA:BB:CC:DD:EE:FF"
OTHER_MAC = "AA:BB:CC:DD:EE:01"


class FakeRedis:
    def __init__(self):
        self.hashes = {}
        self.lists = {}

    def hsetnx(self, key, field, value):
        data = self.hashes.setdefault(key, {})
        if field in data:
            return 0
        data[field] = value
        return 1

    def hscan_iter(self, key):
        return iter(self.hashes.get(key, {}).items())

    def scan_iter(self, match):
        prefix = match[:-1]
        return iter(key for key in [*self.hashes, *self.lists] if key.startswith(prefix))

    def lrange(self, key, start, end):
        points = self.lists.get(key, [])
        return points[start:] if end == -1 else points[start:end + 1]

    def pipeline(self, transaction=False):
        return self

    def execute(self):
        return []

    def info(self, section):
        return {"role": "master"}

    def add_point(self, mac, ts, *values):
        self.lists.setdefault(vitals_history.KEY_PREFIX + mac, []).append(json.dumps([ts, *values]))


class StopAfterWaits:
    def __init__(self, count):
        self.count = count
        self.delays = []

    def is_set(self):
        return len(self.delays) >= self.count

    def wait(self, delay):
        self.delays.append(delay)


class LongtermVitalsTests(unittest.TestCase):
    def setUp(self):
        self.redis = FakeRedis()
        self.state = copy.deepcopy(stopwatch._default_state())
        self.client = stopwatch.app.test_client()
        stopwatch.app.config["AUTH_DISABLED"] = True
        self.addCleanup(stopwatch.app.config.pop, "AUTH_DISABLED", None)
        old_secret = stopwatch.app.secret_key
        stopwatch.app.secret_key = "test-secret"
        self.addCleanup(setattr, stopwatch.app, "secret_key", old_secret)
        for obj, name, kwargs in (
            (stopwatch, "redis_store", {"new": self.redis}),
            (stopwatch, "load_state", {"side_effect": lambda: copy.deepcopy(self.state)}),
            (stopwatch, "save_state", {
                "side_effect": lambda state: self.state.update(copy.deepcopy(state)),
            }),
            (stopwatch, "_write_heats_xml", {}),
            (stopwatch.vitals_history, "add", {}),
            (stopwatch.vitals_history, "set_label", {}),
            (stopwatch.vitals_history, "add_clock_offset", {}),
        ):
            patcher = patch.object(obj, name, **kwargs)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_capture_averages_completed_minutes_once_across_mac_casing(self):
        self.redis.add_point(MAC.lower(), 1000, 0, None, 20, None, -60)
        self.redis.add_point(MAC, 30_000, 10, 4, None, None, -80)
        self.redis.add_point(MAC, 60_000, 80, 3.8, None, None, None)
        self.redis.add_point(MAC, 90_000, 100, None, None, None, None)
        self.redis.add_point(MAC, 120_000, 50, None, None, None, None)
        self.redis.add_point(OTHER_MAC, 30_000, None, None, None, None, None)
        self.redis.add_point(OTHER_MAC, 60_000, None, 3.8, None, None, None)
        longterm_vitals.capture(self.redis, 120_000)
        longterm_vitals.capture(self.redis, 120_000)
        self.assertEqual(longterm_vitals.known(self.redis), [OTHER_MAC, MAC])
        self.assertEqual(longterm_vitals.history(self.redis, MAC), [
            {"ts": 0, "battery": 5, "temp": 20, "vbat": 4, "rssi": -70},
            {"ts": 60_000, "battery": 90, "vbat": 3.8},
        ])
        self.assertEqual(longterm_vitals.history(self.redis, OTHER_MAC), [
            {"ts": 60_000, "vbat": 3.8},
        ])

    def test_no_longterm_writes_during_vitals(self):
        with patch.object(longterm_vitals, "capture") as capture:
            response = self.client.post("/api/vitals", json={"mac": MAC, "battery": 55})
        self.assertEqual(response.status_code, 200)
        capture.assert_not_called()
        self.assertEqual(longterm_vitals.known(self.redis), [])

    def test_daily_capture_retains_one_week_despite_48_hour_source_limit(self):
        day_ms = 24 * 60 * 60 * 1000
        interval_ms = 10 * 60 * 1000
        key = vitals_history.KEY_PREFIX + MAC
        for day in range(7):
            for ts in range(day * day_ms, (day + 1) * day_ms, interval_ms):
                self.redis.add_point(MAC, ts, 50, None, None, None, None)
            self.redis.lists[key] = [
                raw for raw in self.redis.lists[key]
                if json.loads(raw)[0] >= (day - 1) * day_ms
            ]
            longterm_vitals.capture(self.redis, (day + 1) * day_ms)
        points = longterm_vitals.history(self.redis, MAC)
        self.assertEqual(len(points), 7 * day_ms // interval_ms)
        self.assertEqual(points[0]["ts"], 0)
        self.assertEqual(points[-1]["ts"], 7 * day_ms - interval_ms)

    def test_scheduled_capture_at_start_and_every_24_hours(self):
        self.redis.add_point(MAC, 30_000, 55, None, None, None, None)
        stop = StopAfterWaits(2)
        with patch.object(stopwatch, "now_ms", return_value=180_000), \
             patch.object(longterm_vitals, "capture", wraps=longterm_vitals.capture) as capture:
            stopwatch._longterm_vitals_loop(stop)
        self.assertEqual(stop.delays, [86_400, 86_400])
        self.assertEqual(capture.call_count, 2)
        self.assertEqual(len(longterm_vitals.history(self.redis, MAC)), 1)

    def test_worker_retries_failures_and_waits_for_replica_promotion(self):
        stop = StopAfterWaits(3)
        with patch.object(self.redis, "info", side_effect=[
            redis.exceptions.ConnectionError(), {"role": "slave"}, {"role": "master"},
        ]), patch.object(longterm_vitals, "capture") as capture:
            stopwatch._longterm_vitals_loop(stop)
        self.assertEqual(stop.delays, [300, 300, 86_400])
        capture.assert_called_once()

    def test_end_captures_unregistered_macs_with_or_without_shutdown(self):
        for shutdown in (True, False):
            with self.subTest(shutdown=shutdown):
                self.redis.hashes.clear()
                self.redis.add_point(MAC, 30_000, 55, 3.7, None, None, -70)
                self.redis.add_point(MAC, 90_000, 56, 3.8, None, None, -60)
                with patch.object(stopwatch, "now_ms", return_value=60_000):
                    response = self.client.post(
                        "/api/competition/end", json={"shutdown_tasters": shutdown},
                    )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(longterm_vitals.known(self.redis), [MAC])
                self.assertEqual(len(longterm_vitals.history(self.redis, MAC)), 1)
                self.assertEqual(self.client.get("/api/vitals/longterm").json["macs"], [MAC])

    def test_partial_failure_prevents_reset_and_retry_is_safe(self):
        self.state["current_run"] = 5
        self.redis.add_point(MAC, 30_000, 55, None, None, None, None)
        self.redis.add_point(OTHER_MAC, 30_000, 60, None, None, None, None)
        original_lrange = self.redis.lrange

        def fail_second(key, start, end):
            if key.endswith(OTHER_MAC):
                raise redis.exceptions.ConnectionError()
            return original_lrange(key, start, end)

        with patch.object(self.redis, "lrange", side_effect=fail_second):
            response = self.client.post("/api/competition/end", json={"shutdown_tasters": False})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(self.state["current_run"], 5)
        self.assertEqual(len(longterm_vitals.history(self.redis, MAC)), 1)
        response = self.client.post("/api/competition/end", json={"shutdown_tasters": False})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(longterm_vitals.history(self.redis, MAC)), 1)
        self.assertEqual(len(longterm_vitals.history(self.redis, OTHER_MAC)), 1)

    def test_download_is_sorted_csv_with_empty_missing_values(self):
        self.redis.hashes[longterm_vitals.KEY_PREFIX + MAC] = {
            "2": json.dumps({"ts": 120_000, "temp": 22}),
            "1": json.dumps({"ts": 60_000, "battery": 50}),
        }
        response = self.client.get(f"/api/vitals/longterm/{MAC.lower()}")
        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment;", response.headers["Content-Disposition"])
        csv_text = response.get_data(as_text=True).lstrip("\ufeff")
        rows = list(csv.DictReader(io.StringIO(csv_text), delimiter=";"))
        self.assertEqual([row["Zeit_ms"] for row in rows], ["60000", "120000"])
        self.assertEqual(rows[0]["MAC"], MAC)
        self.assertEqual(rows[0]["temp"], "")
        self.assertEqual(rows[1]["battery"], "")

    def test_points_api_filters_range_and_keeps_csv_unfiltered(self):
        self.redis.hashes[longterm_vitals.KEY_PREFIX + MAC] = {
            "1": json.dumps({"ts": 60_000, "battery": 0}),
            "2": json.dumps({"ts": 120_000, "temp": 22}),
            "3": json.dumps({"ts": 180_000, "rssi": -70}),
        }
        response = self.client.get(
            f"/api/vitals/longterm/{MAC.lower()}/points?from=60001&to=180000"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["mac"], MAC)
        self.assertEqual(response.json["fields"], list(vitals_history.FIELDS))
        self.assertEqual(response.json["points"], [{"ts": 120_000, "temp": 22}])
        self.assertEqual(
            self.client.get(f"/api/vitals/longterm/{MAC}/points?from=180000&to=240000").json["points"],
            [{"ts": 180_000, "rssi": -70}],
        )
        self.assertEqual(
            self.client.get(f"/api/vitals/longterm/{MAC}/points?from=240000&to=300000").json["points"],
            [],
        )
        response = self.client.get(f"/api/vitals/longterm/{MAC}")
        self.assertEqual(len(list(csv.DictReader(
            io.StringIO(response.get_data(as_text=True).lstrip("\ufeff")), delimiter=";"
        ))), 3)

    def test_points_api_rejects_bad_inputs_and_reports_store_errors(self):
        for suffix in ("", "?from=0&to=0", "?from=-1&to=100", "?from=0&to=9999999999"):
            response = self.client.get(f"/api/vitals/longterm/{MAC}/points{suffix}")
            self.assertEqual(response.status_code, 400)
        response = self.client.get("/api/vitals/longterm/no/points?from=0&to=1")
        self.assertEqual(response.status_code, 400)
        with patch.object(self.redis, "hscan_iter", side_effect=redis.exceptions.ConnectionError):
            self.assertEqual(
                self.client.get(f"/api/vitals/longterm/{MAC}/points?from=0&to=60000").status_code,
                503,
            )

    def test_invalid_missing_and_storage_errors_are_explicit(self):
        self.assertEqual(self.client.get("/api/vitals/longterm/invalid").status_code, 400)
        self.assertEqual(self.client.get(f"/api/vitals/longterm/{MAC}").status_code, 404)
        with patch.object(self.redis, "scan_iter", side_effect=redis.exceptions.ConnectionError):
            self.assertEqual(self.client.get("/api/vitals/longterm").status_code, 503)
        self.redis.hashes[longterm_vitals.KEY_PREFIX + MAC] = {"1": json.dumps({"bad": 1})}
        self.assertEqual(self.client.get(f"/api/vitals/longterm/{MAC}").status_code, 503)


if __name__ == "__main__":
    unittest.main()
