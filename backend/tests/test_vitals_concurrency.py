import json
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import app as stopwatch


class FakeRedis:
    def __init__(self):
        self.data = {}

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value, **kwargs):
        self.data[key] = value
        return True


class VitalsConcurrencyTests(unittest.TestCase):
    def setUp(self):
        self.store = FakeRedis()
        self.state = stopwatch._default_state()
        self.macs = []
        stripes = set()
        for n in range(256):
            mac = f"AA:BB:CC:DD:EE:{n:02X}"
            stripe = hash(mac) % len(stopwatch._VITAL_LOCKS)
            if stripe not in stripes:
                stripes.add(stripe)
                self.macs.append(mac)
            if len(self.macs) == 7:
                break
        self.state["tasters"] = [
            {"mac": mac, "letter": chr(65 + n)} for n, mac in enumerate(self.macs)
        ]
        self.state["assignments"]["mapping"] = {
            "starter": self.macs[0],
            **{str(n): self.macs[n] for n in range(1, 6)},
        }
        self.state["startcards_per_run"] = {"1": [{"Bahn": str(n)} for n in range(1, 6)]}
        self.store.set(stopwatch.STATE_KEY, json.dumps(self.state))
        stopwatch.app.config["AUTH_DISABLED"] = True
        self.addCleanup(stopwatch.app.config.pop, "AUTH_DISABLED", None)
        for obj, name, kwargs in (
            (stopwatch, "redis_store", {"new": self.store}),
            (stopwatch, "_write_heats_xml", {}),
            (stopwatch, "_stop_lockout_ms", {"return_value": 1000}),
            (stopwatch.vitals_history, "add_start", {}),
            (stopwatch.vitals_history, "add_clock_offset", {}),
            (stopwatch.vitals_history, "set_label", {}),
            (stopwatch.device_logs, "record_observations", {}),
        ):
            p = patch.object(obj, name, **kwargs)
            p.start()
            self.addCleanup(p.stop)

    def post(self, path, payload):
        with stopwatch.app.test_client() as client:
            response = client.post(path, json=payload)
            return response.status_code, response.get_json()

    def test_taster_sounds_can_change_during_a_run_and_reach_vitals(self):
        start = stopwatch.now_ms()
        self.assertEqual(self.post("/api/triggers", {"mac": self.macs[0], "ts": start})[0], 200)
        with patch.object(stopwatch.vitals_history, "add"):
            status, data = self.post("/api/vitals", {"mac": self.macs[1]})
            self.assertEqual((status, data["taster_sounds"]), (200, 1))
            status, data = self.post("/api/settings", {"taster_sounds": False})
            self.assertEqual((status, data["settings"]["taster_sounds"]), (200, "0"))
            status, data = self.post("/api/vitals", {"mac": self.macs[1]})
            self.assertEqual((status, data["taster_sounds"]), (200, 0))
            self.assertEqual(self.post("/api/settings", {"taster_sounds": "invalid"})[0], 400)
            self.assertEqual(self.post("/api/settings", {"taster_sounds": True})[0], 200)
            status, data = self.post("/api/vitals", {"mac": self.macs[1]})
            self.assertEqual((status, data["taster_sounds"]), (200, 1))

    def test_existing_state_without_sound_setting_defaults_to_enabled(self):
        state = json.loads(self.store.get(stopwatch.STATE_KEY))
        del state["settings"]["taster_sounds"]
        self.store.set(stopwatch.STATE_KEY, json.dumps(state))
        with patch.object(stopwatch.vitals_history, "add"):
            status, data = self.post("/api/vitals", {"mac": self.macs[1]})
        self.assertEqual((status, data["taster_sounds"]), (200, 1))

    def test_vitals_preserves_rejection_status_for_dashboard(self):
        with patch.object(stopwatch.vitals_history, "add"):
            status, data = self.post(
                "/api/vitals",
                {
                    "mac": self.macs[1],
                    "trigger_rejected": True,
                    "trigger_rejection_seen": True,
                },
            )
        self.assertEqual(status, 200)
        self.assertTrue(data["vital"]["trigger_rejected"])
        self.assertTrue(data["vital"]["trigger_rejection_seen"])
        self.assertTrue(
            json.loads(self.store.get(stopwatch.STATE_KEY))["vitals"][self.macs[1]][
                "trigger_rejection_seen"
            ]
        )

    def test_smoothed_battery_and_raw_warning_value_are_kept_separate(self):
        with patch.object(stopwatch.vitals_history, "add") as history:
            status, data = self.post(
                "/api/vitals", {"mac": self.macs[1], "battery": 50, "battery_raw": 10, "vbat": 3.69}
            )
        self.assertEqual(status, 200)
        self.assertEqual((data["vital"]["battery"], data["vital"]["battery_raw"]), (50, 10))
        self.assertEqual(history.call_args.args[3]["battery"], 50)
        self.assertEqual(stopwatch.device_logs.record_observations.call_args.args[2]["battery"], 10)
        with stopwatch.app.test_client() as client:
            taster = next(
                t for t in client.get("/api/taster").json["tasters"] if t["mac"] == self.macs[1]
            )
        self.assertEqual((taster["battery"], taster["battery_raw"], taster["vbat"]), (50, 10, 3.69))

    def test_old_firmware_uses_unsmoothed_battery_for_diagnostics(self):
        with patch.object(stopwatch.vitals_history, "add"):
            status, data = self.post("/api/vitals", {"mac": self.macs[1], "battery": 12})
        self.assertEqual(status, 200)
        self.assertNotIn("battery_raw", data["vital"])
        self.assertEqual(stopwatch.device_logs.record_observations.call_args.args[2]["battery"], 12)

    def test_slow_vital_history_does_not_block_start_or_lane_stops(self):
        entered = threading.Event()
        release = threading.Event()
        counter_lock = threading.Lock()
        counter = 0

        def slow_history(*args):
            nonlocal counter
            with counter_lock:
                counter += 1
                if counter == 7:
                    entered.set()
            if not release.wait(5):
                raise AssertionError("Timed out waiting to release simulated history")

        start = stopwatch.now_ms()
        with patch.object(stopwatch.vitals_history, "add", side_effect=slow_history):
            with ThreadPoolExecutor(max_workers=13) as pool:
                pending = [pool.submit(self.post, "/api/vitals", {"mac": mac}) for mac in self.macs]
                try:
                    self.assertTrue(
                        entered.wait(3), "Seven vital histories did not run in parallel"
                    )
                    started = self.post(
                        "/api/triggers",
                        {
                            "mac": self.macs[0],
                            "ts": start,
                            "trigger_id": "start",
                        },
                    )
                    self.assertEqual(started[0], 200, started)
                    self.assertEqual(started[1]["press"]["run_key"], "1")
                    futures = [
                        pool.submit(
                            self.post,
                            "/api/triggers",
                            {
                                "mac": self.macs[n],
                                "ts": start + 5000 + n,
                                "trigger_id": f"stop-{n}",
                            },
                        )
                        for n in range(1, 6)
                    ]
                    results = [f.result(timeout=3) for f in futures]
                    self.assertTrue(all(status == 200 for status, _ in results), results)
                    for n, (_, body) in enumerate(results, 1):
                        self.assertEqual(body["press"]["run_key"], "1")
                        self.assertEqual(body["press"]["lane"], str(n))
                finally:
                    release.set()
                self.assertEqual([f.result(timeout=3)[0] for f in pending], [200] * 7)

        state = json.loads(self.store.get(stopwatch.STATE_KEY))
        self.assertEqual(set(state["vitals"]), set(self.macs))
        presses = state["triggers_per_run"]["1"]
        self.assertEqual(presses["starter"]["ts"], start)
        for n in range(1, 6):
            self.assertEqual(presses[str(n)]["ts"], start + 5000 + n)

    def test_same_device_diagnostics_are_kept_in_order(self):
        entered = threading.Event()
        release = threading.Event()
        values = []

        def history(_store, _mac, _ts, vital):
            values.append(vital["battery"])
            if vital["battery"] == 10:
                entered.set()
                if not release.wait(3):
                    raise AssertionError("Timed out waiting to release first vital")

        with patch.object(stopwatch.vitals_history, "add", side_effect=history):
            with ThreadPoolExecutor(max_workers=2) as pool:
                first = pool.submit(self.post, "/api/vitals", {"mac": self.macs[0], "battery": 10})
                try:
                    self.assertTrue(entered.wait(2))
                    second = pool.submit(
                        self.post,
                        "/api/vitals",
                        {
                            "mac": self.macs[0],
                            "battery": 20,
                        },
                    )
                    time.sleep(0.05)
                    self.assertFalse(second.done())
                finally:
                    release.set()
                self.assertEqual(first.result(timeout=2)[0], 200)
                self.assertEqual(second.result(timeout=2)[0], 200)
        self.assertEqual(values, [10, 20])
        state = json.loads(self.store.get(stopwatch.STATE_KEY))
        self.assertEqual(state["vitals"][self.macs[0]]["battery"], 20)

    def test_archiving_waits_for_inflight_vital_history(self):
        entered = threading.Event()
        release = threading.Event()
        history_finished = threading.Event()

        def history(*args):
            entered.set()
            if not release.wait(3):
                raise AssertionError("Timed out waiting to release vital history")
            history_finished.set()

        def archive(*args):
            self.assertTrue(history_finished.is_set())
            return "archive"

        with (
            patch.object(stopwatch.vitals_history, "add", side_effect=history),
            patch.object(stopwatch, "_archive_competition", side_effect=archive),
        ):
            with ThreadPoolExecutor(max_workers=2) as pool:
                vital = pool.submit(self.post, "/api/vitals", {"mac": self.macs[0]})
                try:
                    self.assertTrue(entered.wait(2))
                    end = pool.submit(
                        self.post,
                        "/api/competition/end",
                        {
                            "name": "Test",
                            "shutdown_tasters": False,
                        },
                    )
                    time.sleep(0.05)
                    self.assertFalse(end.done())
                finally:
                    release.set()
                self.assertEqual(vital.result(timeout=2)[0], 200)
                self.assertEqual(end.result(timeout=2)[0], 200)

    def test_slow_charger_history_does_not_block_trigger(self):
        entered = threading.Event()
        release = threading.Event()

        def history(*args):
            entered.set()
            if not release.wait(3):
                raise AssertionError("Timed out waiting to release charger history")

        with patch.object(stopwatch.vitals_history, "add_charger", side_effect=history):
            with ThreadPoolExecutor(max_workers=2) as pool:
                charger = pool.submit(
                    self.post,
                    "/api/charger",
                    {
                        "mac": "AA:BB:CC:DD:EE:FF",
                        "slots": [],
                    },
                )
                try:
                    self.assertTrue(entered.wait(2))
                    result = self.post(
                        "/api/triggers",
                        {
                            "mac": self.macs[0],
                            "ts": stopwatch.now_ms(),
                            "trigger_id": "start",
                        },
                    )
                    self.assertEqual(result[0], 200, result)
                    self.assertEqual(result[1]["press"]["run_key"], "1")
                finally:
                    release.set()
                self.assertEqual(charger.result(timeout=2)[0], 200)

    def test_telemetry_timeout_releases_partially_acquired_archive_locks(self):
        entered = threading.Event()
        release = threading.Event()

        def history(*args):
            entered.set()
            if not release.wait(3):
                raise AssertionError("Timed out waiting to release vital history")

        with (
            patch.object(stopwatch.vitals_history, "add", side_effect=history),
            patch.object(stopwatch, "_TELEMETRY_LOCK_TIMEOUT_S", 0.05),
        ):
            with ThreadPoolExecutor(max_workers=2) as pool:
                vital = pool.submit(self.post, "/api/vitals", {"mac": self.macs[0]})
                try:
                    self.assertTrue(entered.wait(2))
                    status, body = self.post("/api/competition/end", {"name": "Test"})
                    self.assertEqual(status, 503)
                    self.assertEqual(body["error"], "state_busy")
                finally:
                    release.set()
                self.assertEqual(vital.result(timeout=2)[0], 200)
        with patch.object(stopwatch.vitals_history, "add"):
            self.assertEqual(self.post("/api/vitals", {"mac": self.macs[1]})[0], 200)

    def test_slow_state_write_is_identified_in_lock_log(self):
        set_value = self.store.set

        def delayed_set(key, value, **kwargs):
            if key == stopwatch.STATE_KEY:
                time.sleep(0.26)
            return set_value(key, value, **kwargs)

        with (
            patch.object(self.store, "set", side_effect=delayed_set),
            patch.object(stopwatch.vitals_history, "add"),
            self.assertLogs(stopwatch.logger, level="WARNING") as logs,
        ):
            status, _ = self.post("/api/vitals", {"mac": self.macs[0]})
        self.assertEqual(status, 200)
        self.assertTrue(
            any(
                "Lang gehaltene Zustandssperre" in line and "zustand_speichern=" in line
                for line in logs.output
            )
        )
        self.assertTrue(
            any(
                "Langsame Statusverarbeitung /api/vitals" in line and "zustand_speichern=" in line
                for line in logs.output
            )
        )

    def test_rejected_trigger_can_be_retried_without_duplicate_start(self):
        entered = threading.Event()
        release = threading.Event()

        def hold_state_lock():
            with stopwatch._STATE_LOCK:
                entered.set()
                if not release.wait(3):
                    raise AssertionError("Timed out waiting to release state lock")

        ts = stopwatch.now_ms()
        trigger = {"mac": self.macs[0], "ts": ts, "trigger_id": "retry-start"}
        with ThreadPoolExecutor(max_workers=1) as pool:
            holder = pool.submit(hold_state_lock)
            try:
                self.assertTrue(entered.wait(2))
                status, body = self.post("/api/triggers", trigger)
                self.assertEqual(status, 503)
                self.assertEqual(body["error"], "state_busy")
            finally:
                release.set()
            holder.result(timeout=2)
        accepted = self.post("/api/triggers", trigger)
        repeated = self.post("/api/triggers", trigger)
        self.assertEqual(accepted[0], 200)
        self.assertEqual(repeated, accepted)
        state = json.loads(self.store.get(stopwatch.STATE_KEY))
        self.assertEqual(state["triggers_per_run"]["1"]["starter"]["ts"], ts)
        self.assertEqual(state["current_run"], 1)

    def test_21_runs_with_concurrent_vitals_and_lane_stops(self):
        state = json.loads(self.store.get(stopwatch.STATE_KEY))
        state["startcards_per_run"] = {
            str(run): [{"Bahn": str(n)} for n in range(1, 6)] for run in range(1, 22)
        }
        self.store.set(stopwatch.STATE_KEY, json.dumps(state))
        get = self.store.get
        set_value = self.store.set

        def delayed_get(key):
            if key == stopwatch.STATE_KEY:
                time.sleep(0.005)
            return get(key)

        def delayed_set(key, value, **kwargs):
            if key == stopwatch.STATE_KEY:
                time.sleep(0.005)
            return set_value(key, value, **kwargs)

        def delayed_history(*args):
            time.sleep(0.05)

        start = stopwatch.now_ms()
        with (
            patch.object(self.store, "get", side_effect=delayed_get),
            patch.object(self.store, "set", side_effect=delayed_set),
            patch.object(stopwatch.vitals_history, "add", side_effect=delayed_history),
            patch.object(stopwatch, "_auto_next_delay_ms", return_value=600_000),
        ):
            with ThreadPoolExecutor(max_workers=12) as pool:
                for run in range(1, 22):
                    ts = start + (run - 1) * 20_000
                    status, body = self.post(
                        "/api/triggers",
                        {
                            "mac": self.macs[0],
                            "ts": ts,
                            "trigger_id": f"start-{run}",
                        },
                    )
                    self.assertEqual(status, 200, (run, body))
                    self.assertEqual(body["press"]["run_key"], str(run))
                    barrier = threading.Barrier(12)

                    def simultaneous_post(path, payload):
                        barrier.wait(timeout=3)
                        return self.post(path, payload)

                    futures = [
                        pool.submit(simultaneous_post, "/api/vitals", {"mac": mac})
                        for mac in self.macs
                    ]
                    futures.extend(
                        pool.submit(
                            simultaneous_post,
                            "/api/triggers",
                            {
                                "mac": self.macs[n],
                                "ts": ts + 5000 + n,
                                "trigger_id": f"stop-{run}-{n}",
                            },
                        )
                        for n in range(1, 6)
                    )
                    results = [future.result(timeout=5) for future in futures]
                    self.assertEqual([status for status, _ in results], [200] * 12, (run, results))
                    for lane, (_, body) in enumerate(results[7:], 1):
                        self.assertEqual(body["press"]["run_key"], str(run))
                        self.assertEqual(body["press"]["lane"], str(lane))

        state = json.loads(self.store.get(stopwatch.STATE_KEY))
        for run in range(1, 22):
            ts = start + (run - 1) * 20_000
            presses = state["triggers_per_run"][str(run)]
            self.assertEqual(presses["starter"]["ts"], ts)
            for lane in range(1, 6):
                self.assertEqual(presses[str(lane)]["ts"], ts + 5000 + lane)


if __name__ == "__main__":
    unittest.main()
