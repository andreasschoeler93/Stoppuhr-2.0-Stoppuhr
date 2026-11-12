import copy
import time
import unittest
from unittest.mock import patch

import app as stopwatch
import device_logs
import limits


MAC = "AA:BB:CC:DD:EE:FF"


class FakeRedis:
    def __init__(self):
        self.data = {}

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value, ex=None, nx=False):
        if nx and key in self.data:
            return False
        self.data[key] = value
        return True


class DeviceLogTests(unittest.TestCase):
    def setUp(self):
        stopwatch.app.config["AUTH_DISABLED"] = True
        self.addCleanup(stopwatch.app.config.pop, "AUTH_DISABLED", None)
        device_logs.reset_memory()
        self.addCleanup(device_logs.reset_memory)
        self.redis = FakeRedis()
        redis_patch = patch.object(stopwatch, "redis_store", self.redis)
        redis_patch.start()
        self.addCleanup(redis_patch.stop)
        self.client = stopwatch.app.test_client()

    def test_taster_logs_are_attached_to_the_registered_device(self):
        state = copy.deepcopy(stopwatch._default_state())
        state["tasters"] = [{"mac": MAC, "letter": "A"}]
        with patch.object(stopwatch, "load_state", return_value=state), \
             patch.object(stopwatch, "save_state"), \
             patch.object(stopwatch.vitals_history, "add"), \
             patch.object(stopwatch.vitals_history, "set_label"):
            response = self.client.post("/api/vitals", json={
                "mac": MAC,
                "fw": "v0.19.1",
                "uptime_s": 42,
                "logs": [{"ms": 1200, "text": "WiFi connected rssi=-50"}],
            })
        self.assertEqual(response.status_code, 200)
        snapshot = device_logs.load_snapshot(self.redis, "taster", MAC)
        self.assertEqual(snapshot["entries"], [{"ms": 1200, "text": "WiFi connected rssi=-50"}])
        self.assertEqual(device_logs.load_observations(self.redis, MAC)["role"], "keine Zuordnung")

    def test_snapshot_is_bounded_and_sanitized(self):
        entries = [{"ms": i, "text": f"entry {i}\nnext"} for i in range(30)]
        self.assertTrue(device_logs.save_snapshot(
            self.redis, "taster", MAC, "v0.19.1", 50, entries, 1000,
        ))
        snapshot = device_logs.load_snapshot(self.redis, "taster", MAC)
        self.assertEqual(len(snapshot["entries"]), device_logs.MAX_ENTRIES)
        self.assertEqual(snapshot["entries"][0]["text"], "entry 6 next")
        self.assertFalse(device_logs.save_snapshot(
            self.redis, "taster", "invalid", "v0.19.1", 50, entries, 1000,
        ))

    def test_vitals_post_records_configured_threshold_and_role_in_download(self):
        state = copy.deepcopy(stopwatch._default_state())
        state["tasters"] = [{"mac": MAC, "letter": "A"}]
        state["assignments"]["mapping"]["starter"] = MAC
        state["settings"]["limits"] = {"taster": {"battery": {"values": [60, 30]}}}
        with patch.object(stopwatch, "load_state", return_value=state), \
             patch.object(stopwatch, "save_state"), \
             patch.object(stopwatch.vitals_history, "add"), \
             patch.object(stopwatch.vitals_history, "set_label"):
            response = self.client.post("/api/vitals", json={
                "mac": MAC, "fw": "v0.19.1", "uptime_s": 42, "battery": 55,
                "logs": [{"ms": 1000, "text": "start"}],
            })
        self.assertEqual(response.status_code, 200)
        text = self.client.get(f"/api/device-logs/taster/{MAC}").get_data(as_text=True)
        self.assertIn("Letzte bekannte Rolle laut Pi: Starter", text)
        self.assertIn("Akku: warnung (55 %; Warnung 60, kritisch 30)", text)
        self.assertIn("Geräteereignisse", text)

    def test_taster_download_is_an_attachment(self):
        device_logs.save_snapshot(
            self.redis, "taster", MAC, "v0.19.1", 42,
            [{"ms": 1200, "text": "WiFi connected"}], 1_800_000_000_000,
        )
        response = self.client.get(f"/api/device-logs/taster/{MAC}")
        self.assertEqual(response.status_code, 200)
        self.assertIn('attachment; filename="taster-AA-BB-CC-DD-EE-FF.log"',
                      response.headers["Content-Disposition"])
        stamp = time.strftime("%Y-%m-%d %H:%M:%S %z", time.localtime((1_800_000_000_000 - 42_000 + 1200) / 1000))
        self.assertIn(f"[ca. {stamp}; +1200 ms] WiFi connected", response.get_data(as_text=True))

    def test_taster_timestamp_is_unknown_when_uptime_is_missing_or_inconsistent(self):
        for uptime in (None, 1):
            with self.subTest(uptime=uptime):
                device_logs.save_snapshot(
                    self.redis, "taster", MAC, "v0.19.1", uptime,
                    [{"ms": 12000, "text": "test"}], 1_800_000_000_000,
                )
                response = self.client.get(f"/api/device-logs/taster/{MAC}")
                self.assertIn("[Uhrzeit unbekannt; +12000 ms] test", response.get_data(as_text=True))

    def test_role_and_threshold_transitions_are_recorded_without_duplicates(self):
        rules = limits.defaults()["taster"]
        rules["battery"]["values"] = [50, 20]
        device_logs.record_observations(self.redis, MAC, {"battery": 60, "temp": 20}, rules, "Starter", 1000)
        device_logs.record_observations(self.redis, MAC, {"battery": 50, "temp": 20}, rules, "Starter", 2000)
        device_logs.record_observations(self.redis, MAC, {"battery": 49, "temp": 20}, rules, "Starter", 3000)
        device_logs.record_observations(self.redis, MAC, {"battery": 20, "temp": 55}, rules, "Bahn 2", 4000)
        device_logs.record_observations(self.redis, MAC, {"battery": None, "temp": float("nan")}, rules, "Bahn 2", 5000)
        device_logs.record_observations(self.redis, MAC, {"battery": 51, "temp": 40}, rules, "Bahn 2", 6000)
        device_logs.reset_memory()
        observed = device_logs.load_observations(self.redis, MAC)
        self.assertEqual(observed["role"], "Bahn 2")
        self.assertEqual(
            [e["text"] for e in observed["events"]],
            ["Rolle laut Pi: Starter", "Akku: warnung (50 %; Warnung 50, kritisch 20)",
             "Rolle laut Pi: Bahn 2", "Akku: kritisch (20 %; Warnung 50, kritisch 20)",
             "Temperatur: kritisch (55 °C; Warnung 45, kritisch 55)",
             "Akku: normal (51 %; Warnung 50, kritisch 20)",
             "Temperatur: normal (40 °C; Warnung 45, kritisch 55)"],
        )
        self.assertEqual([e["ts"] for e in observed["events"]], [1000, 2000, 4000, 4000, 4000, 6000, 6000])

    def test_role_and_threshold_events_appear_in_taster_download(self):
        device_logs.save_snapshot(self.redis, "taster", MAC, "v0.19.1", 42, [], 1_800_000_000_000)
        device_logs.record_observations(
            self.redis, MAC, {"rssi": -85}, limits.defaults()["taster"], "Bereitschaft: Starter",
            1_800_000_000_000,
        )
        response = self.client.get(f"/api/device-logs/taster/{MAC}")
        text = response.get_data(as_text=True)
        self.assertIn("Letzte bekannte Rolle laut Pi: Bereitschaft: Starter", text)
        self.assertIn("WLAN: kritisch (-85 dBm; Warnung -75, kritisch -85)", text)
        self.assertIn("Zeitpunkt der empfangenen Vitaldaten", text)

    def test_observations_are_bounded_and_invalid_measurements_do_not_change_levels(self):
        rules = limits.defaults()["taster"]
        for i in range(device_logs.MAX_THRESHOLD_EVENTS + 10):
            device_logs.record_observations(
                self.redis, MAC, {"battery": 10 if i % 2 else 50}, rules, "Starter", 1000 + i,
            )
        before = device_logs.load_observations(self.redis, MAC)
        self.assertEqual(len(before["events"]), device_logs.MAX_THRESHOLD_EVENTS)
        device_logs.record_observations(
            self.redis, MAC, {"battery": 10 ** 400}, rules, "Starter", 2000,
        )
        after = device_logs.load_observations(self.redis, MAC)
        self.assertEqual(after["levels"], before["levels"])
        self.assertEqual(after["events"], before["events"])

    def test_taster_role_describes_current_and_pending_assignment(self):
        state = copy.deepcopy(stopwatch._default_state())
        state["tasters"] = [{"mac": MAC, "letter": "A"}]
        self.assertEqual(stopwatch._taster_log_role(state, MAC), "keine Zuordnung")
        state["assignments"]["mapping"]["2"] = MAC
        self.assertEqual(stopwatch._taster_log_role(state, MAC), "Bahn 2")
        state["assignments"]["mapping"].clear()
        state["assignments"]["pending"]["ziel"] = MAC
        self.assertEqual(stopwatch._taster_log_role(state, MAC), "Bereitschaft: Zieleinlauf")

    def test_charger_logs_are_downloadable_separately(self):
        device_logs.save_snapshot(
            self.redis, "charger", MAC, "v0.7.22", 75,
            [{"ms": 2500, "text": "TRIG_ALL 15 s held"}], 1_800_000_000_000,
        )
        response = self.client.get("/api/device-logs/charger")
        self.assertEqual(response.status_code, 200)
        self.assertIn('attachment; filename="ladekoffer.log"',
                      response.headers["Content-Disposition"])
        self.assertIn(b"[+2500 ms] TRIG_ALL 15 s held", response.data)

    def test_charger_status_upload_stores_diagnostic_logs(self):
        state = copy.deepcopy(stopwatch._default_state())
        payload = {
            "mac": MAC,
            "fw": "v0.7.22",
            "uptime_s": 75,
            "slots": [{"n": 1, "charging": False, "fault": False, "vbat": 4.1}],
            "logs": [{"ms": 2500, "text": "TRIG_ALL 15 s held"}],
        }
        with patch.object(stopwatch, "load_state", return_value=state), \
             patch.object(stopwatch.ladekoffer, "save"), \
             patch.object(stopwatch.vitals_history, "add_charger"), \
             patch.object(stopwatch.vitals_history, "add_charger_slot_backfill"), \
             patch.object(stopwatch.vitals_history, "add_charger_slots"), \
             patch.object(stopwatch.charger_firmware, "offer", return_value=None):
            response = self.client.post("/api/charger", json=payload)
        self.assertEqual(response.status_code, 200)
        snapshot = device_logs.load_charger_snapshot(self.redis)
        self.assertEqual(snapshot["entries"], [{"ms": 2500, "text": "TRIG_ALL 15 s held"}])

    def test_pi_download_contains_recent_service_logs(self):
        stopwatch.logger.info("pi log download test marker")
        response = self.client.get("/api/device-logs/pi")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"pi log download test marker", response.data)
        self.assertIn('attachment; filename="pi-stoppuhr.log"',
                      response.headers["Content-Disposition"])

    def test_device_download_links_render_in_dashboard(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('href="/api/device-logs/pi"', html)
        self.assertIn('href="/api/device-logs/charger"', html)
        self.assertIn(f'/static/app.js?v={stopwatch.APP_VERSION}', html)


if __name__ == "__main__":
    unittest.main()
