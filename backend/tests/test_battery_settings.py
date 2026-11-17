import copy
import unittest
from unittest.mock import patch

import app as stopwatch


class BatterySettingsTests(unittest.TestCase):
    def setUp(self):
        self.state = stopwatch._default_state()
        stopwatch.app.config["AUTH_DISABLED"] = True
        self.addCleanup(stopwatch.app.config.pop, "AUTH_DISABLED", None)
        old_secret = stopwatch.app.secret_key
        stopwatch.app.secret_key = "battery-test-secret"
        self.addCleanup(setattr, stopwatch.app, "secret_key", old_secret)
        load = patch.object(stopwatch, "load_state", side_effect=lambda: copy.deepcopy(self.state))
        save = patch.object(stopwatch, "save_state", side_effect=lambda state: self.state.update(copy.deepcopy(state)))
        load.start()
        save.start()
        no_ota = patch.object(stopwatch, "_load_ota", return_value=None)
        no_ota.start()
        self.addCleanup(load.stop)
        self.addCleanup(save.stop)
        self.addCleanup(no_ota.stop)
        self.client = stopwatch.app.test_client()

    def test_defaults_and_legacy_state_are_sent_to_tasters(self):
        del self.state["settings"]["battery_zero_mv"]
        del self.state["settings"]["battery_full_mv"]
        response = self.client.get("/api/display?mac=AA")
        self.assertEqual(response.status_code, 200)
        self.assertEqual((response.json["battery_zero_mv"], response.json["battery_full_mv"]), (3300, 4000))

    def test_save_and_deliver_limits(self):
        response = self.client.post("/api/settings", json={"battery_zero_mv": 3200, "battery_full_mv": 4100})
        self.assertEqual(response.status_code, 200)
        settings = self.client.get("/api/settings").json
        self.assertEqual((settings["battery_zero_mv"], settings["battery_full_mv"]), ("3200", "4100"))
        display = self.client.get("/api/display?mac=AA").json
        self.assertEqual((display["battery_zero_mv"], display["battery_full_mv"]), (3200, 4100))
        self.assertEqual(self.client.post("/api/settings", json={"battery_full_mv": 4200}).status_code, 200)
        self.assertEqual(self.client.get("/api/display?mac=AA").json["battery_zero_mv"], 3200)

    def test_invalid_values_do_not_save_any_settings(self):
        for zero, full in [(2490, 4000), (3300, 4510), (4000, 4000), (4010, 4000),
                           (3900, 3990), (3301, 4000), ("NaN", 4000), (True, 4000)]:
            with self.subTest(zero=zero, full=full):
                old = copy.deepcopy(self.state)
                response = self.client.post("/api/settings", json={
                    "battery_zero_mv": zero, "battery_full_mv": full, "low_battery_pct": 15,
                })
                self.assertEqual(response.status_code, 400)
                self.assertEqual(self.state, old)

    def test_valid_extreme_range(self):
        response = self.client.post("/api/settings", json={"battery_zero_mv": 2500, "battery_full_mv": 4500})
        self.assertEqual(response.status_code, 200)
