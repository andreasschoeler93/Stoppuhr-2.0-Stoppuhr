import json
import unittest
from unittest.mock import patch

import app as stopwatch


class FakeRedis:
    def __init__(self):
        self.data = {}

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value):
        self.data[key] = value


class AlertAckTests(unittest.TestCase):
    def setUp(self):
        self.redis = FakeRedis()
        old_secret = stopwatch.app.secret_key
        stopwatch.app.secret_key = "alert-test-secret"
        self.addCleanup(setattr, stopwatch.app, "secret_key", old_secret)
        stopwatch.app.config["AUTH_DISABLED"] = True
        self.addCleanup(stopwatch.app.config.pop, "AUTH_DISABLED", None)
        patcher = patch.object(stopwatch, "redis_store", self.redis)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = stopwatch.app.test_client()

    def report(self, yellow, red):
        response = self.client.post("/api/alert-state", json={"yellow": yellow, "red": red})
        self.assertEqual(response.status_code, 200)
        return json.loads(self.redis.data[stopwatch.ALERT_STATE_KEY])

    def test_changing_values_do_not_create_new_warnings(self):
        initial = self.report(
            ["Taster H: WLAN-Signal auffällig (-76 dBm)."],
            ["Taster I: Akku kritisch (4 %)."],
        )
        updated = self.report(
            ["Taster H: WLAN-Signal auffällig (-75 dBm)."],
            ["Taster I: Akku kritisch (3 %)."],
        )
        self.assertEqual((initial["yellow_seq"], initial["red_seq"]), (1, 1))
        self.assertEqual((updated["yellow_seq"], updated["red_seq"]), (1, 1))
        with patch.object(stopwatch, "now_ms", return_value=updated["ts"]):
            config = stopwatch._beep_config(stopwatch._default_state())
        self.assertEqual((config["red_on"], config["red_seq"]), (1, 1))

    def test_new_warning_reappearance_and_severity_change_increment_sequences(self):
        self.report(
            ["Taster H: WLAN-Signal auffällig (-76 dBm)."], ["Taster I: Akku kritisch (4 %)."],
        )
        added = self.report(
            ["Taster H: WLAN-Signal auffällig (-75 dBm).", "Taster J: Akku auffällig (30 %)."],
            ["Taster I: Akku kritisch (3 %).", "Taster K: Akku kritisch (5 %)."],
        )
        self.assertEqual((added["yellow_seq"], added["red_seq"]), (2, 2))
        self.report([], ["Taster I: Akku kritisch (2 %)."])
        again = self.report(["Taster H: WLAN-Signal auffällig (-77 dBm)."], [
            "Taster I: Akku kritisch (2 %).", "Taster J: Akku kritisch (8 %).",
        ])
        self.assertEqual((again["yellow_seq"], again["red_seq"]), (3, 3))

    def test_charger_offline_duration_does_not_change_identity(self):
        self.report(["Ladekoffer meldet sich nicht (zuletzt vor 1 Min.)."], [])
        state = self.report(["Ladekoffer meldet sich nicht (zuletzt vor 2 Min.)."], [])
        self.assertEqual(state["yellow_seq"], 1)


if __name__ == "__main__":
    unittest.main()
