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
        self.write_heats = patch.object(stopwatch, "_write_heats_xml")
        for patcher in (
            self.load_state,
            self.save_state,
            self.add_vitals,
            self.add_clock_offset,
            self.set_label,
            self.record_observations,
            self.write_heats,
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(stopwatch.app.config.pop, "AUTH_DISABLED", None)

    def send_vital(self, mac, received_ts, *, clock_synced=False, sync_age_ms=None, offset_ms=440):
        with patch.object(stopwatch, "now_ms", return_value=received_ts):
            response = self.client.post(
                "/api/vitals",
                json={
                    "mac": mac,
                    "clock_ms": received_ts - offset_ms,
                    "clock_synced": clock_synced,
                    "clock_sync_age_ms": sync_age_ms,
                },
            )
        self.assertEqual(response.status_code, 200)

    def test_waits_for_recent_sntp_sync_from_every_assigned_taster(self):
        mac = "AA:BB"
        self.state["assignments"]["mapping"] = {"starter": mac}
        self.state["tasters"] = [{"mac": mac, "letter": "A", "name": "Starter"}]
        start = 1_800_000_000_000
        self.send_vital(mac, start)
        self.assertFalse(stopwatch._clock_sync_status(self.state, start)["ready"])
        self.send_vital(mac, start + 10_000, clock_synced=True, sync_age_ms=1000)

        status = stopwatch._clock_sync_status(self.state, start + 10_000)

        self.assertTrue(status["ready"])
        self.assertIn("Start möglich", status["message"])

    def test_stale_sntp_sync_keeps_readiness_waiting(self):
        mac = "AA:BB"
        self.state["assignments"]["mapping"] = {"starter": mac}
        self.state["tasters"] = [{"mac": mac, "letter": "A", "name": "Starter"}]
        start = 1_800_000_000_000
        self.send_vital(mac, start, clock_synced=True, sync_age_ms=60_001)

        status = stopwatch._clock_sync_status(self.state, start)

        self.assertFalse(status["ready"])
        self.assertIn("zu alt", status["message"])

    def test_sntp_age_includes_time_since_last_vital(self):
        mac = "AA:BB"
        self.state["assignments"]["mapping"] = {"starter": mac}
        self.state["tasters"] = [{"mac": mac, "letter": "A", "name": "Starter"}]
        start = 1_800_000_000_000
        self.send_vital(mac, start, clock_synced=True, sync_age_ms=50_000)

        status = stopwatch._clock_sync_status(self.state, start + 11_000)

        self.assertFalse(status["ready"])
        self.assertIn("zu alt", status["message"])

    def test_missing_sntp_status_keeps_readiness_waiting(self):
        mac = "AA:BB"
        self.state["assignments"]["mapping"] = {"starter": mac}
        self.state["tasters"] = [{"mac": mac, "letter": "A", "name": "Starter"}]
        start = 1_800_000_000_000
        self.send_vital(mac, start)

        status = stopwatch._clock_sync_status(self.state, start)

        self.assertFalse(status["ready"])
        self.assertIn("warte auf SNTP", status["message"])

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

    def test_one_way_vital_offset_is_not_applied_to_trigger_timestamp(self):
        mac = "AA:BB"
        self.state["current_run"] = 1
        self.state["startcards_per_run"] = {"1": [{"Bahn": "1"}]}
        self.state["assignments"]["mapping"] = {"starter": mac, "1": "LANE"}
        self.state["tasters"] = [{"mac": mac, "letter": "A", "name": "Starter"}]
        self.state["tasters"].append({"mac": "LANE", "letter": "B", "name": "Lane"})
        start = 1_800_000_000_000
        self.send_vital(mac, start, offset_ms=440)
        trigger_ts = start + 10_000

        response = self.client.post("/api/triggers", json={"mac": mac, "ts": trigger_ts})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.state["triggers_per_run"]["1"]["starter"]["ts"], trigger_ts)
        self.assertEqual(self.state.get("clock_offsets", {}), {})


if __name__ == "__main__":
    unittest.main()
