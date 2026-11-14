import copy
import unittest
from unittest.mock import patch

import app as stopwatch


class ClockSyncTests(unittest.TestCase):
    def setUp(self):
        self.state = stopwatch._default_state()
        stopwatch.app.config["AUTH_DISABLED"] = True
        old_secret = stopwatch.app.secret_key
        stopwatch.app.secret_key = "test-secret"
        self.addCleanup(setattr, stopwatch.app, "secret_key", old_secret)
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
        self.add_clock_offset = patch.object(stopwatch.vitals_history, "add_clock_offset")
        self.set_label = patch.object(stopwatch.vitals_history, "set_label")
        self.record_observations = patch.object(stopwatch.device_logs, "record_observations")
        for patcher in (
            self.load_state,
            self.save_state,
            self.add_vitals,
            self.add_clock_offset,
            self.set_label,
            self.record_observations,
        ):
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

    def test_outlier_does_not_change_applied_clock_correction(self):
        mac = "AA:BB"
        start = 1_800_000_000_000
        applied = []
        for offset in (440, 441, 900, 442):
            with patch.object(stopwatch, "now_ms", return_value=start):
                response = self.client.post(
                    "/api/vitals",
                    json={"mac": mac, "clock_ms": start - offset},
                )
            self.assertEqual(response.status_code, 200)
            applied.append(self.state["clock_offsets"].get(mac, 0))
            start += 10_000

        self.assertEqual(applied[2], 440)
        self.assertEqual(applied[3], 440)

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

    def test_clock_offset_history_api_returns_chart_points(self):
        points = [[1_800_000_000_000, 440, 440]]
        with patch.object(stopwatch, "now_ms", return_value=1_800_000_000_000), patch.object(
            stopwatch.vitals_history, "clock_offset_history", return_value=points
        ) as history:
            response = self.client.get(
                "/api/clock-offset/history?mac=AA%3ABB&hours=1"
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["points"], points)
        history.assert_called_once()


if __name__ == "__main__":
    unittest.main()
