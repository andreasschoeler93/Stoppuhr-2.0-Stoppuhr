import copy
import unittest
from unittest.mock import patch

import app as stopwatch


class ClockSyncTests(unittest.TestCase):
    def setUp(self):
        self.state = stopwatch._default_state()
        stopwatch.app.config["AUTH_DISABLED"] = True
        self.client = stopwatch.app.test_client()
        self.load_state = patch.object(
            stopwatch, "load_state", side_effect=lambda: copy.deepcopy(self.state)
        )
        self.save_state = patch.object(
            stopwatch,
            "save_state",
            side_effect=lambda state: self.state.update(copy.deepcopy(state)),
        )
        self.add_vitals = patch.object(stopwatch.vitals_history, "add")
        for patcher in (self.load_state, self.save_state, self.add_vitals):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(stopwatch.app.config.pop, "AUTH_DISABLED", None)

    def send_vital(self, mac, received_ts, offset_ms):
        with patch.object(stopwatch, "now_ms", return_value=received_ts):
            response = self.client.post(
                "/api/vitals",
                json={"mac": mac, "clock_ms": received_ts - offset_ms},
            )
        self.assertEqual(response.status_code, 200)

    def test_waits_until_clock_samples_are_stable(self):
        mac = "AA:BB"
        self.state["assignments"]["mapping"] = {"starter": mac}
        self.state["tasters"] = [{"mac": mac, "letter": "A", "name": "Starter"}]
        start = 1_800_000_000_000
        self.send_vital(mac, start, 440)
        self.assertFalse(stopwatch._clock_sync_status(self.state, start)["ready"])
        self.send_vital(mac, start + 10_000, 441)
        self.assertFalse(stopwatch._clock_sync_status(self.state, start + 10_000)["ready"])
        self.send_vital(mac, start + 20_000, 439)

        status = stopwatch._clock_sync_status(self.state, start + 20_000)

        self.assertTrue(status["ready"])
        self.assertIn("Start möglich", status["message"])
        self.assertEqual(len(self.state["clock_sync_samples"][mac]), 3)

    def test_unstable_clock_samples_keep_status_waiting(self):
        mac = "AA:BB"
        self.state["assignments"]["mapping"] = {"starter": mac}
        self.state["tasters"] = [{"mac": mac, "letter": "A", "name": "Starter"}]
        start = 1_800_000_000_000
        for offset in (440, 600, 440):
            self.send_vital(mac, start, offset)
            start += 10_000

        status = stopwatch._clock_sync_status(self.state, start - 10_000)

        self.assertFalse(status["ready"])
        self.assertIn("nicht stabil", status["message"])

    def test_no_assigned_taster_is_not_reported_ready(self):
        now = 1_800_000_000_000
        status = stopwatch._clock_sync_status(self.state, now)

        self.assertFalse(status["ready"])
        self.assertIn("keine Taster zugeordnet", status["message"])
        with patch.object(stopwatch, "now_ms", return_value=now):
            response = self.client.get("/api/run-status")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json["clock_sync"]["ready"])


if __name__ == "__main__":
    unittest.main()
