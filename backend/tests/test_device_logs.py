import copy
import unittest
from unittest.mock import patch

import app as stopwatch
import device_logs


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

    def test_taster_download_is_an_attachment(self):
        device_logs.save_snapshot(
            self.redis, "taster", MAC, "v0.19.1", 42,
            [{"ms": 1200, "text": "WiFi connected"}], 1_800_000_000_000,
        )
        response = self.client.get(f"/api/device-logs/taster/{MAC}")
        self.assertEqual(response.status_code, 200)
        self.assertIn('attachment; filename="taster-AA-BB-CC-DD-EE-FF.log"',
                      response.headers["Content-Disposition"])
        self.assertIn(b"[+1200 ms] WiFi connected", response.data)

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
