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
            ("_write_heats_xml", {}),
            ("_load_ota", {"return_value": None}),
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
        r = self.press("L1", 9_900)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json["deferred"])
        self.assertEqual(self.press("AA", 10_000).status_code, 200)
        self.assertEqual(self.deviation(), {"1": -100})

    def test_press_after_start_inside_lockout_is_positive_and_not_a_time(self):
        self.press("AA", 10_000)
        with patch.object(stopwatch, "_stop_lockout_ms", return_value=5000):
            r = self.press("L2", 10_120)
        self.assertEqual(r.json["reason"], "stop_lockout")
        self.assertEqual(self.deviation(), {"2": 120})
        self.assertIsNone(self.state["triggers_per_run"]["5"].get("2"))
        for mac in ("AA", "L1", "L2"):
            self.assertEqual(
                self.client.get("/api/display", query_string={"mac": mac}).json["state"], "running"
            )
        self.assertEqual(self.client.get("/api/run-status").json["runs"]["5"]["times_ms"], {})

    def test_old_press_outside_window_is_ignored(self):
        self.press("L1", 1_000)
        self.press("AA", 10_000)
        self.assertEqual(self.deviation(), {})

    def test_run_status_exposes_deviation(self):
        self.press("L1", 9_950)
        self.press("AA", 10_000)
        status = self.client.get("/api/run-status").json
        self.assertEqual(status["runs"]["5"]["start_deviation"], {"1": -50})

    def test_prestart_presses_do_not_end_run_or_stop_displays(self):
        self.press("L1", 9900)
        self.press("L2", 9950)
        self.press("AA", 10000)
        self.assertIsNone(self.state.get("run_finished_ts"))
        self.assertEqual(self.deviation(), {"1": -100, "2": -50})
        status = self.client.get("/api/run-status").json["runs"]["5"]
        self.assertTrue(status["running"])
        self.assertEqual(status["times_ms"], {})
        for mac in ("AA", "L1", "L2"):
            self.assertEqual(
                self.client.get("/api/display", query_string={"mac": mac}).json["state"], "running"
            )
        self.press("L1", 16000)
        self.assertIsNone(self.state.get("run_finished_ts"))
        self.assertEqual(
            self.client.get("/api/display", query_string={"mac": "L2"}).json["state"], "running"
        )
        self.press("L2", 17000)
        self.assertIsNotNone(self.state.get("run_finished_ts"))

    def test_existing_empty_lane_slot_does_not_finish_on_start(self):
        self.state["startcards_per_run"]["5"] = [{"Bahn": "1"}]
        self.state["triggers_per_run"] = {"5": {"1": None}}
        self.press("L1", 9900)
        self.press("AA", 10000)
        self.assertIsNone(self.state.get("run_finished_ts"))
        self.assertEqual(self.deviation(), {"1": -100})
        for mac in ("AA", "L1"):
            self.assertEqual(
                self.client.get("/api/display", query_string={"mac": mac}).json["state"], "running"
            )

    def test_prestart_replayed_with_zero_lockout_is_not_a_stop(self):
        self.state["settings"]["stop_lockout_s"] = "0"
        self.press("L1", 9900)
        self.press("AA", 10000)
        self.assertIsNone(self.state["triggers_per_run"]["5"].get("1"))
        self.assertIsNone(self.state.get("run_finished_ts"))

    def test_prestart_with_previous_run_is_deviation_not_review(self):
        self.state["settings"]["stop_lockout_s"] = "0"
        self.state["triggers_per_run"] = {"4": {"starter": {"ts": 1_000, "mac": "AA"}}}
        event = {"mac": "L1", "ts": 9_900, "trigger_id": "boot:prestart"}
        self.assertTrue(self.client.post("/api/triggers", json=event).json["deferred"])
        self.press("AA", 10_000)
        self.assertEqual(self.deviation(), {"1": -100})
        self.assertFalse(self.state.get("unresolved_lane_presses"))
        self.assertIsNone(self.state["triggers_per_run"]["5"].get("1"))
        self.assertEqual(
            self.client.post("/api/triggers", json=event).json["reason"], "start_deviation"
        )

    def test_prestart_at_window_boundary_after_start_is_deviation(self):
        self.state["settings"]["stop_lockout_s"] = "0"
        self.state["triggers_per_run"] = {"4": {"starter": {"ts": 1_000, "mac": "AA"}}}
        self.press("AA", 10_000)
        response = self.press("L1", 7_000)
        self.assertEqual(response.json["reason"], "start_deviation")
        self.assertEqual(self.deviation(), {"1": -3_000})
        self.assertFalse(self.state.get("unresolved_lane_presses"))
        self.assertIsNone(self.state["triggers_per_run"]["5"].get("1"))

    def test_late_old_event_is_not_recorded_as_start_deviation(self):
        self.state["triggers_per_run"] = {"4": {"starter": {"ts": 1_000, "mac": "AA"}}}
        self.press("L1", 5_000)
        self.press("AA", 10_000)
        self.assertEqual(self.deviation(), {})
        self.assertEqual(self.state["unresolved_lane_presses"][0]["reason"], "before_current_start")

    def test_lane_absent_from_startcards_goes_to_review(self):
        self.state["startcards_per_run"]["5"] = [{"Bahn": "2"}]
        event = {"mac": "L1", "ts": 9_900, "trigger_id": "boot:missing"}
        first = self.client.post("/api/triggers", json=event)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json["reason"], "manual_lane_review")
        self.press("AA", 10_000)
        retry = self.client.post("/api/triggers", json=event)
        self.assertEqual(retry.json["id"], first.json["id"])
        self.assertEqual(self.state["unresolved_lane_presses"][0]["original_lane"], "1")
        self.assertEqual(self.deviation(), {})

    def test_lane_of_next_run_is_deferred_if_absent_from_completed_run(self):
        self.state["startcards_per_run"] = {"5": [{"Bahn": "2"}], "6": [{"Bahn": "1"}]}
        self.state["triggers_per_run"] = {
            "5": {"starter": {"ts": 1_000, "mac": "AA"}, "2": {"ts": 6_000, "mac": "L2"}}
        }
        self.state["run_finished_ts"] = 20_000
        self.state["run_done_event_ts"] = {"5": 6_000}
        with patch.object(stopwatch, "now_ms", return_value=20_100):
            response = self.press("L1", 9_900)
        self.assertEqual(response.json["reason"], "next_run_not_started")
        self.assertEqual(self.state["deferred_presses"][0]["lane"], "1")
        self.assertFalse(self.state.get("unresolved_lane_presses"))

    def test_six_simultaneous_starts_and_an_older_deferred_event(self):
        self.state["startcards_per_run"]["5"] = [{"Bahn": str(n)} for n in range(1, 7)]
        self.state["assignments"]["mapping"] = {
            "starter": "AA",
            **{str(n): f"L{n}" for n in range(1, 7)},
        }
        self.state["triggers_per_run"] = {"4": {"starter": {"ts": 1_000, "mac": "AA"}}}
        self.press("L1", 6_000)
        for n in range(1, 7):
            self.press(f"L{n}", 10_000 - n * 10)
        self.press("AA", 10_000)
        self.assertEqual(self.deviation(), {str(n): -n * 10 for n in range(1, 7)})
        self.assertEqual(len(self.state["unresolved_lane_presses"]), 1)
        self.assertEqual(self.state["unresolved_lane_presses"][0]["ts"], 6_000)
        self.assertIsNone(self.state.get("run_finished_ts"))

    def test_run_status_reports_unresolved_and_previously_rejected_tasters(self):
        self.state["tasters"] = [{"mac": "L1", "letter": "A"}]
        self.state["vitals"]["L1"] = {
            "ts": 10_000,
            "trigger_rejected": True,
            "trigger_rejection_seen": True,
        }
        with patch.object(stopwatch, "now_ms", return_value=11_000):
            result = self.client.get("/api/run-status").json["rejected_tasters"]
        self.assertEqual(result, [{"letter": "A", "mac": "L1", "pending": True, "online": True}])
        self.state["vitals"]["L1"]["trigger_rejected"] = False
        with patch.object(stopwatch, "now_ms", return_value=100_000):
            result = self.client.get("/api/run-status").json["rejected_tasters"]
        self.assertEqual(result, [{"letter": "A", "mac": "L1", "pending": False, "online": False}])


if __name__ == "__main__":
    unittest.main()
