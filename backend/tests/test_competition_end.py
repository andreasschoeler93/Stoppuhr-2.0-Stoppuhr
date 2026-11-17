import copy
import unittest
from unittest.mock import patch

import app as stopwatch


class CompetitionEndTests(unittest.TestCase):
    def setUp(self):
        self.state = stopwatch._default_state()
        self.state["shutdown_until_ms"] = 123_000
        old_secret = stopwatch.app.secret_key
        stopwatch.app.secret_key = "competition-test-secret"
        self.addCleanup(setattr, stopwatch.app, "secret_key", old_secret)
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
        self.load_state.start()
        self.save_state.start()
        self.addCleanup(self.load_state.stop)
        self.addCleanup(self.save_state.stop)
        p = patch.object(stopwatch.vitals_history, "set_label")
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(stopwatch.app.config.pop, "AUTH_DISABLED", None)

    def test_ending_without_shutdown_keeps_shutdown_inactive(self):
        self.state["settings"]["taster_sounds"] = "0"
        tasters = [{"mac": "AA:BB", "name": "Taster", "letter": "C"}]
        vitals = {"AA:BB": {"battery_pct": 90}}
        assignments = {
            "mapping": {"starter": "AA:BB", "1": "CC:DD"},
            "pending": {"2": "EE:FF"},
            "last_update_ts": 1000,
        }
        self.state["tasters"] = copy.deepcopy(tasters)
        self.state["vitals"] = copy.deepcopy(vitals)
        self.state["assignments"] = copy.deepcopy(assignments)

        with patch.object(stopwatch, "_write_heats_xml"):
            response = self.client.post(
                "/api/competition/end", json={"name": "", "shutdown_tasters": False}
            )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json["shutdown_tasters"])
        self.assertEqual(response.json["shutdown_grace_s"], 0)
        self.assertEqual(self.state["shutdown_until_ms"], 0)
        self.assertEqual(self.state["tasters"], tasters)
        self.assertEqual(self.state["vitals"], vitals)
        self.assertEqual(self.state["assignments"], assignments)
        self.assertEqual(self.state["results"], {})
        self.assertEqual(self.state["settings"]["taster_sounds"], "1")

    def test_ending_still_shuts_down_tasters_by_default(self):
        self.state["settings"]["taster_sounds"] = "0"
        self.state["tasters"] = [{"mac": "AA:BB", "name": "Taster", "letter": "C"}]
        self.state["vitals"] = {"AA:BB": {"battery_pct": 90}}
        self.state["assignments"]["mapping"] = {"starter": "AA:BB"}

        with patch.object(stopwatch, "_write_heats_xml"), patch.object(
            stopwatch, "now_ms", return_value=100_000
        ):
            response = self.client.post("/api/competition/end", json={"name": ""})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json["shutdown_tasters"])
        self.assertEqual(response.json["shutdown_grace_s"], 10)
        self.assertEqual(self.state["shutdown_until_ms"], 110_000)
        self.assertEqual(self.state["tasters"], [])
        self.assertEqual(self.state["vitals"], {})
        self.assertEqual(self.state["settings"]["taster_sounds"], "1")
        self.assertEqual(
            self.state["assignments"],
            {"mapping": {}, "pending": {}, "last_update_ts": None},
        )

    def test_failed_end_does_not_reset_taster_sounds(self):
        self.state["settings"]["taster_sounds"] = "0"
        with patch.object(stopwatch, "_archive_competition", side_effect=RuntimeError("test")):
            response = self.client.post("/api/competition/end", json={"name": "Test"})
        self.assertEqual(response.status_code, 500)
        self.assertEqual(self.state["settings"]["taster_sounds"], "0")

    def test_open_events_are_saved_unmodified_before_reset(self):
        events = {
            "deferred_presses": [{"mac": "A", "ts": 100, "recv": 150, "lane": "1", "trigger_id": "id-a"}],
            "unresolved_lane_presses": [{"id": "l", "mac": "B", "ts": 200, "reason": "role_changed"}],
            "unresolved_finish_presses": [{"id": "f", "mac": "C", "ts": 300}],
        }
        self.state.update(copy.deepcopy(events))
        captured = []
        with patch.object(stopwatch.archive, "save", side_effect=lambda r, data: captured.append(copy.deepcopy(data))), \
             patch.object(stopwatch.vitals_history, "history_pi", return_value=[]), \
             patch.object(stopwatch.vitals_history, "history_charger", return_value=[]), \
             patch.object(stopwatch.vitals_history, "starts", return_value=[]), \
             patch.object(stopwatch, "_write_heats_xml"), \
             patch.object(stopwatch, "now_ms", return_value=100_000):
            response = self.client.post("/api/competition/end", json={"name": "", "shutdown_tasters": False})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json["automatic_archive"])
        self.assertTrue(response.json["archive_name"].startswith("Wettkampf "))
        for key, value in events.items():
            self.assertEqual(captured[0]["raw"][key], value)
            self.assertEqual(self.state[key], [])
        self.assertEqual(captured[0]["raw"]["triggers_per_run"], {})

    def test_named_archive_is_used_for_open_events(self):
        self.state["unresolved_lane_presses"] = [{"id": "l", "mac": "A", "ts": 100}]
        saved = []
        with patch.object(stopwatch, "_archive_competition", side_effect=lambda state, name: saved.append((copy.deepcopy(state), name)) or "a"), \
             patch.object(stopwatch, "_write_heats_xml"):
            response = self.client.post("/api/competition/end", json={"name": "Test", "shutdown_tasters": False})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json["automatic_archive"])
        self.assertEqual(saved[0][1], "Test")
        self.assertEqual(saved[0][0]["unresolved_lane_presses"][0]["id"], "l")

    def test_auto_archive_failure_preserves_open_events(self):
        self.state["deferred_presses"] = [{"mac": "A", "ts": 100}]
        before = copy.deepcopy(self.state)
        with patch.object(stopwatch, "_archive_competition", side_effect=RuntimeError("test")):
            response = self.client.post("/api/competition/end", json={"name": "", "shutdown_tasters": False})
        self.assertEqual(response.status_code, 500)
        self.assertEqual(self.state, before)

    def test_incomplete_replay_still_blocks_end(self):
        self.state["replay_pending_run"] = "5"
        before = copy.deepcopy(self.state)
        with patch.object(stopwatch, "_archive_competition") as archive:
            response = self.client.post("/api/competition/end", json={"name": "Test", "shutdown_tasters": False})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.state, before)
        archive.assert_not_called()

    def test_resolved_cases_auto_archive_without_name(self):
        self.state["reviewed_lane_presses"] = [{"id": "r", "note": "Geprüft"}]
        with patch.object(stopwatch, "_archive_competition", return_value="archive"), \
             patch.object(stopwatch, "_write_heats_xml"):
            response = self.client.post("/api/competition/end", json={"name": "", "shutdown_tasters": False})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json["automatic_archive"])


if __name__ == "__main__":
    unittest.main()
