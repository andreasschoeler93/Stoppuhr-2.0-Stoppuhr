import copy
import unittest
from unittest.mock import patch

import app as stopwatch


class StartDeviationTests(unittest.TestCase):
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
        ):
            p = patch.object(stopwatch, target, **kwargs)
            p.start()
            self.addCleanup(p.stop)
        p = patch.object(stopwatch.vitals_history, "add_start")
        p.start()
        self.addCleanup(p.stop)
        self.state["current_run"] = 5
        self.state["startcards_per_run"] = {"5": [{"Bahn": "1"}, {"Bahn": "2"}]}
        self.state["assignments"]["mapping"] = {"starter": "AA", "1": "L1", "2": "L2"}

    def press(self, mac, ts):
        return self.client.post("/api/triggers", json={"mac": mac, "ts": ts})

    def deviation(self):
        return (self.state.get("start_deviation") or {}).get("5", {})

    def test_press_before_start_is_negative(self):
        self.assertEqual(self.press("L1", 9_900).status_code, 400)
        self.assertEqual(self.press("AA", 10_000).status_code, 200)
        self.assertEqual(self.deviation(), {"1": -100})

    def test_press_after_start_inside_lockout_is_positive_and_not_a_time(self):
        self.press("AA", 10_000)
        with patch.object(stopwatch, "_stop_lockout_ms", return_value=5000):
            r = self.press("L2", 10_120)
        self.assertEqual(r.json["reason"], "stop_lockout")
        self.assertEqual(self.deviation(), {"2": 120})
        self.assertIsNone(self.state["triggers_per_run"]["5"].get("2"))

    def test_old_press_outside_window_is_ignored(self):
        self.press("L1", 1_000)
        self.press("AA", 10_000)
        self.assertEqual(self.deviation(), {})

    def test_run_status_exposes_deviation(self):
        self.press("L1", 9_950)
        self.press("AA", 10_000)
        status = self.client.get("/api/run-status").json
        self.assertEqual(status["runs"]["5"]["start_deviation"], {"1": -50})


if __name__ == "__main__":
    unittest.main()
