import copy
import unittest
from unittest.mock import patch

import app as stopwatch


class OfflineReplayTests(unittest.TestCase):
    """Drücke, die nach einem Pi-Ausfall in beliebiger Reihenfolge nachgeliefert werden."""

    def setUp(self):
        self.state = stopwatch._default_state()
        stopwatch.app.config["AUTH_DISABLED"] = True
        old_secret = stopwatch.app.secret_key
        stopwatch.app.secret_key = "test-secret"
        self.addCleanup(setattr, stopwatch.app, "secret_key", old_secret)
        self.client = stopwatch.app.test_client()
        for target, kwargs in (
            ("load_state", {"side_effect": lambda: copy.deepcopy(self.state)}),
            ("save_state", {"side_effect": lambda s: self.state.update(copy.deepcopy(s))}),
            ("_write_heats_xml", {}),
            ("_stop_lockout_ms", {"return_value": 1000}),
        ):
            p = patch.object(stopwatch, target, **kwargs)
            p.start()
            self.addCleanup(p.stop)
        p = patch.object(stopwatch.vitals_history, "add_start")
        p.start()
        self.addCleanup(p.stop)
        self.state["current_run"] = 5
        self.state["startcards_per_run"] = {
            "5": [{"Bahn": "1"}, {"Bahn": "2"}],
            "6": [{"Bahn": "1"}, {"Bahn": "2"}],
        }
        self.state["assignments"]["mapping"] = {"starter": "AA", "1": "L1", "2": "L2"}

    def press(self, mac, ts):
        return self.client.post("/api/triggers", json={"mac": mac, "ts": ts})

    def lane_time(self, run, lane):
        presses = self.state["triggers_per_run"][f"{run}"]
        return int(presses[lane]["ts"]) - int(presses["starter"]["ts"])

    def test_stop_before_start_is_kept(self):
        self.assertTrue(self.press("L1", 15_000).json["deferred"])
        self.press("AA", 10_000)
        self.assertEqual(self.lane_time(5, "1"), 5_000)

    def test_stops_of_two_runs_arrive_before_second_start(self):
        # Reihenfolge der Ankunft: Start 1, alle Stopps beider Läufe, erst dann Start 2
        self.press("AA", 10_000)
        self.press("L1", 20_000)
        self.press("L2", 21_000)
        self.assertEqual(self.press("L1", 50_000).json["reason"], "next_run_not_started")
        self.assertEqual(self.press("L2", 53_000).json["reason"], "next_run_not_started")
        self.press("AA", 40_000)
        self.assertEqual(self.state["current_run"], 6)
        self.assertEqual(self.lane_time(5, "1"), 10_000)
        self.assertEqual(self.lane_time(5, "2"), 11_000)
        self.assertEqual(self.lane_time(6, "1"), 10_000)
        self.assertEqual(self.lane_time(6, "2"), 13_000)

    def test_stop_after_starter_stop_belongs_to_next_run(self):
        self.press("AA", 10_000)
        self.press("L1", 20_000)
        self.press("AA", 25_000)  # Starter beendet den Lauf, Bahn 2 bleibt leer
        self.assertEqual(self.press("L2", 50_000).json["reason"], "next_run_not_started")
        self.press("AA", 40_000)
        self.assertIsNone(self.state["triggers_per_run"]["5"].get("2"))
        self.assertEqual(self.lane_time(6, "2"), 10_000)

    def test_late_stop_before_starter_stop_stays_in_run(self):
        self.press("AA", 10_000)
        self.press("L1", 20_000)
        self.press("AA", 25_000)
        self.press("L2", 24_000)
        self.assertEqual(self.lane_time(5, "2"), 14_000)

    def test_unrelated_old_press_is_not_counted(self):
        self.press("L1", 1_000)
        self.press("AA", 10_000)
        self.assertIsNone(self.state["triggers_per_run"]["5"].get("1"))


if __name__ == "__main__":
    unittest.main()
