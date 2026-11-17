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

    def test_finish_press_arriving_before_start_is_replayed(self):
        self.state["assignments"]["mapping"][stopwatch.FINISH_KEY] = "FIN"
        response = self.press("FIN", 15_000)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json["deferred"])
        self.press("AA", 10_000)
        self.assertEqual(self.state["finish_per_run"]["5"], [{"ts": 15_000, "mac": "FIN"}])

    def test_finish_press_before_actual_start_is_not_recorded(self):
        self.state["assignments"]["mapping"][stopwatch.FINISH_KEY] = "FIN"
        self.press("FIN", 9_000)
        self.press("AA", 10_000)
        self.assertFalse((self.state.get("finish_per_run") or {}).get("5"))

    def test_repeated_deferred_finish_is_recorded_once(self):
        self.state["assignments"]["mapping"][stopwatch.FINISH_KEY] = "FIN"
        self.press("FIN", 15_000)
        self.press("FIN", 15_000)
        self.press("AA", 10_000)
        self.assertEqual(self.state["finish_per_run"]["5"], [{"ts": 15_000, "mac": "FIN"}])

    def test_old_finish_retry_does_not_create_negative_time_in_next_run(self):
        self.state["assignments"]["mapping"][stopwatch.FINISH_KEY] = "FIN"
        self.press("AA", 10_000)
        self.press("FIN", 15_000)
        self.press("L1", 20_000)
        self.press("L2", 21_000)
        self.press("AA", 40_000)
        response = self.press("FIN", 15_000)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json.get("reason"), "manual_review")
        self.assertFalse((self.state.get("finish_per_run") or {}).get("6"))
        self.assertEqual(self.state["finish_per_run"]["5"], [{"ts": 15_000, "mac": "FIN"}])
        self.assertEqual(len(self.state["unresolved_finish_presses"]), 1)

    def test_late_finish_is_kept_for_explicit_manual_assignment(self):
        self.state["assignments"]["mapping"][stopwatch.FINISH_KEY] = "FIN"
        self.press("AA", 10_000)
        self.press("L1", 20_000)
        self.press("L2", 21_000)
        self.press("AA", 40_000)
        event = {"mac": "FIN", "ts": 19_000, "trigger_id": "boot:late"}
        response = self.client.post("/api/triggers", json=event)
        self.assertEqual(response.json["reason"], "manual_review")
        retry = self.client.post("/api/triggers", json=event)
        self.assertEqual(retry.json["reason"], "manual_review")
        status = self.client.get("/api/run-status").json
        pending = status["unresolved_finish_presses"]
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["candidates"][0]["run_key"], "5")
        self.assertEqual(pending[0]["candidates"][0]["time_ms"], 9_000)
        resolution = self.client.post(
            "/api/finish/resolve",
            json={
                "id": pending[0]["id"],
                "run_key": "5",
            },
        )
        self.assertEqual(resolution.status_code, 200)
        self.assertEqual(self.state["finish_per_run"]["5"][0]["ts"], 19_000)
        self.assertEqual(self.state["unresolved_finish_presses"], [])
        self.assertEqual(self.client.post("/api/triggers", json=event).json["run_key"], "5")
        self.assertEqual(len(self.state["finish_per_run"]["5"]), 1)
        self.assertEqual(
            self.client.post(
                "/api/finish/resolve",
                json={
                    "id": pending[0]["id"],
                    "run_key": "5",
                },
            ).status_code,
            200,
        )

    def test_pending_late_finish_is_archived_at_competition_end(self):
        self.state["unresolved_finish_presses"] = [{"id": "p", "mac": "FIN", "ts": 19_000}]
        saved = []
        with patch.object(stopwatch, "_archive_competition", side_effect=lambda state, name: saved.append(copy.deepcopy(state)) or "archive"):
            response = self.client.post("/api/competition/end", json={"shutdown_tasters": False})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json["automatic_archive"])
        self.assertEqual(saved[0]["unresolved_finish_presses"][0]["id"], "p")
        self.assertEqual(self.state["unresolved_finish_presses"], [])

    def test_deferred_press_is_archived_at_competition_end(self):
        self.press("L1", 15_000)
        saved = []
        with patch.object(stopwatch, "_archive_competition", side_effect=lambda state, name: saved.append(copy.deepcopy(state)) or "archive"):
            response = self.client.post("/api/competition/end", json={"shutdown_tasters": False})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json["automatic_archive"])
        self.assertEqual(saved[0]["deferred_presses"][0]["ts"], 15_000)
        self.assertEqual(self.state["deferred_presses"], [])

    def test_deferred_manual_review_preserves_event_and_retry_receipt(self):
        event = {"mac": "L1", "ts": 15_000, "trigger_id": "event-1"}
        self.assertTrue(self.client.post("/api/triggers", json=event).json["deferred"])
        status = self.client.get("/api/run-status").json
        item = status["deferred_presses"][0]["item"]
        response = self.client.post("/api/deferred/review", json={
            "index": 0, "item": item, "revision": status["deferred_revision"],
        })
        self.assertEqual(response.status_code, 200)
        review = self.state["unresolved_lane_presses"][0]
        self.assertEqual(review["recv"], item["recv"])
        self.assertEqual(review["original_lane"], "1")
        self.assertEqual(review["trigger_id"], event["trigger_id"])
        self.assertEqual(review["deferred_id"], item["deferred_id"])
        self.assertEqual(self.state["deferred_presses"], [])
        self.assertEqual(self.client.post("/api/triggers", json=event).json["id"], review["id"])
        self.assertEqual(self.client.post("/api/lane-review/resolve", json={
            "id": review["id"], "action": "park", "run_key": None, "lane": None, "note": "Geprüft",
        }).status_code, 200)
        self.assertEqual(self.state["reviewed_lane_presses"][0]["recv"], item["recv"])
        self.assertEqual(self.client.post("/api/triggers", json=event).status_code, 200)
        captured = []
        def capture_archive(state, name):
            captured.append(copy.deepcopy(state))
            return "archive-id"
        with patch.object(stopwatch, "_archive_competition", side_effect=capture_archive):
            response = self.client.post("/api/competition/end", json={
                "name": "Wettkampf", "shutdown_tasters": False,
            })
        self.assertEqual(response.status_code, 200)
        saved = captured[0]["reviewed_lane_presses"][0]
        self.assertEqual(saved["trigger_id"], event["trigger_id"])
        self.assertEqual(saved["note"], "Geprüft")

    def test_deferred_review_rejects_stale_snapshot_even_for_identical_legacy_events(self):
        legacy = {"mac": "L1", "ts": 15_000, "recv": 16_000, "lane": "1"}
        self.state["deferred_presses"] = [legacy.copy(), legacy.copy()]
        status = self.client.get("/api/run-status").json
        payload = {"index": 0, "item": legacy, "revision": status["deferred_revision"]}
        self.assertEqual(self.client.post("/api/deferred/review", json=payload).status_code, 200)
        self.assertEqual(self.client.post("/api/deferred/review", json=payload).status_code, 409)
        self.assertEqual(len(self.state["deferred_presses"]), 1)
        self.assertEqual(len(self.state["unresolved_lane_presses"]), 1)

    def test_deferred_review_rejects_pending_replay_and_full_review_buffer(self):
        self.press("L1", 15_000)
        status = self.client.get("/api/run-status").json
        payload = {"index": 0, "item": status["deferred_presses"][0]["item"],
                   "revision": status["deferred_revision"]}
        self.state["replay_pending_run"] = "5"
        self.assertEqual(self.client.post("/api/deferred/review", json=payload).status_code, 409)
        self.state["replay_pending_run"] = None
        self.state["unresolved_lane_presses"] = [{"id": str(i)} for i in range(stopwatch.DEFERRED_MAX_COUNT)]
        self.assertEqual(self.client.post("/api/deferred/review", json=payload).status_code, 503)
        self.assertEqual(len(self.state["deferred_presses"]), 1)

    def test_deferred_review_preserves_original_role_after_reassignment(self):
        self.press("L1", 15_000)
        self.state["assignments"]["mapping"]["1"] = "L3"
        status = self.client.get("/api/run-status").json
        response = self.client.post("/api/deferred/review", json={
            "index": 0, "item": status["deferred_presses"][0]["item"],
            "revision": status["deferred_revision"],
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.state["unresolved_lane_presses"][0]["original_lane"], "1")

    def test_deferred_review_failed_save_leaves_event_pending(self):
        self.press("L1", 15_000)
        status = self.client.get("/api/run-status").json
        with patch.object(stopwatch, "save_state", side_effect=RuntimeError("save failed")):
            response = self.client.post("/api/deferred/review", json={
                "index": 0, "item": status["deferred_presses"][0]["item"],
                "revision": status["deferred_revision"],
            })
        self.assertEqual(response.status_code, 500)
        self.assertEqual(len(self.state["deferred_presses"]), 1)
        self.assertFalse(self.state.get("unresolved_lane_presses"))

    def test_deferred_review_requires_login(self):
        with patch.dict(stopwatch.app.config, {"AUTH_DISABLED": False}), patch.object(
            stopwatch.auth, "load", return_value=None
        ):
            response = self.client.post("/api/deferred/review", json={})
        self.assertEqual(response.status_code, 401)

    def test_manual_finish_resolution_validates_and_preserves_existing_indices(self):
        self.state["assignments"]["mapping"][stopwatch.FINISH_KEY] = "FIN"
        self.press("AA", 10_000)
        self.press("FIN", 18_000)
        self.press("L1", 20_000)
        self.press("L2", 21_000)
        self.press("AA", 40_000)
        self.press("FIN", 15_000)
        pending_id = self.state["unresolved_finish_presses"][0]["id"]
        for run_key in ("6", "999", "invalid"):
            result = self.client.post(
                "/api/finish/resolve", json={"id": pending_id, "run_key": run_key}
            )
            self.assertEqual(result.status_code, 400)
            self.assertEqual(len(self.state["unresolved_finish_presses"]), 1)
        result = self.client.post("/api/finish/resolve", json={"id": pending_id, "run_key": "5"})
        self.assertEqual(result.status_code, 200)
        self.assertEqual([p["ts"] for p in self.state["finish_per_run"]["5"]], [18_000, 15_000])

    def test_operator_can_confirm_only_an_existing_exact_duplicate(self):
        self.state["assignments"]["mapping"][stopwatch.FINISH_KEY] = "FIN"
        self.press("AA", 10_000)
        self.press("FIN", 15_000)
        self.press("L1", 20_000)
        self.press("L2", 21_000)
        self.press("AA", 40_000)
        event = {"mac": "FIN", "ts": 15_000, "trigger_id": "boot:late"}
        self.client.post("/api/triggers", json=event)
        pending = self.client.get("/api/run-status").json["unresolved_finish_presses"][0]
        self.assertTrue(pending["candidates"][0]["duplicate"])
        body = {"id": pending["id"], "run_key": "5", "action": "duplicate"}
        self.assertEqual(self.client.post("/api/finish/resolve", json=body).status_code, 200)
        self.assertEqual(self.client.post("/api/finish/resolve", json=body).status_code, 200)
        self.assertEqual(self.client.post("/api/triggers", json=event).json["run_key"], "5")
        self.assertEqual(len(self.state["finish_per_run"]["5"]), 1)

    def test_manual_assignment_preserves_pending_on_save_error(self):
        self.state["unresolved_finish_presses"] = [{"id": "p", "mac": "FIN", "ts": 15_000}]
        self.state["triggers_per_run"] = {"5": {"starter": {"ts": 10_000, "mac": "AA"}}}
        with patch.object(stopwatch, "save_state", side_effect=RuntimeError("storage unavailable")):
            result = self.client.post("/api/finish/resolve", json={"id": "p", "run_key": "5"})
        self.assertEqual(result.status_code, 500)
        self.assertEqual(len(self.state["unresolved_finish_presses"]), 1)
        self.assertFalse(self.state.get("finish_per_run"))

    def test_manual_resolution_requires_login(self):
        self.state["unresolved_finish_presses"] = [{"id": "p", "mac": "FIN", "ts": 15_000}]
        with patch.dict(stopwatch.app.config, {"AUTH_DISABLED": False}):
            with patch.object(stopwatch.auth, "load", return_value={"user": "judge"}):
                result = self.client.post("/api/finish/resolve", json={"id": "p", "run_key": "5"})
        self.assertEqual(result.status_code, 401)
        self.assertEqual(len(self.state["unresolved_finish_presses"]), 1)

    def test_start_retry_after_receipt_save_failure_does_not_stop_run(self):
        event = {"mac": "AA", "ts": 10_000, "trigger_id": "boot:start"}
        save = stopwatch.save_state
        calls = 0

        def fail_second_save(st):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("receipt save failed")
            return save(st)

        with patch.object(stopwatch, "save_state", side_effect=fail_second_save):
            first = self.client.post("/api/triggers", json=event)
        self.assertIn(first.status_code, (200, 500))
        retry = self.client.post("/api/triggers", json=event)
        self.assertEqual(retry.status_code, 200)
        self.assertEqual(retry.json["press"]["run_key"], "5")
        self.assertNotIn("5", self.state.get("stopped_by_starter", []))

    def test_starter_stop_retry_after_save_failure_does_not_start_new_run(self):
        self.press("AA", 10_000)
        event = {"mac": "AA", "ts": 20_000, "trigger_id": "boot:stop"}
        with patch.object(stopwatch, "_write_heats_xml", side_effect=RuntimeError("xml")):
            self.assertEqual(self.client.post("/api/triggers", json=event).status_code, 500)
        retry = self.client.post("/api/triggers", json=event)
        self.assertTrue(retry.json.get("stopped"))
        self.assertEqual(self.state["current_run"], 5)

    def test_automatic_advance_checks_current_completion_after_reloading(self):
        self.state["run_finished_ts"] = 9_000
        fresh = copy.deepcopy(self.state)
        fresh["run_finished_ts"] = 19_500
        with (
            patch.object(stopwatch, "now_ms", return_value=20_000),
            patch.object(stopwatch, "_auto_next_delay_ms", return_value=1_000),
            patch.object(stopwatch, "load_state", return_value=fresh),
        ):
            stopwatch._maybe_advance_run(copy.deepcopy(self.state))
        self.assertEqual(fresh["current_run"], 5)

    def test_combo_last_finish_save_is_atomic_with_run_completion(self):
        self.state["settings"]["starter_is_finish"] = "1"
        self.state["startcards_per_run"]["5"] = [{"Bahn": "1"}]
        self.press("AA", 10_000)
        event = {"mac": "AA", "ts": 20_000, "trigger_id": "boot:finish"}
        save = stopwatch.save_state
        calls = 0

        def fail_second_save(st):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("completion save failed")
            return save(st)

        with patch.object(stopwatch, "save_state", side_effect=fail_second_save):
            self.client.post("/api/triggers", json=event)
        self.assertIsNotNone(self.state.get("run_finished_ts"))
        self.assertEqual(len(self.state["finish_per_run"]["5"]), 1)
        self.assertEqual(self.client.post("/api/triggers", json=event).status_code, 200)

    def test_run_completion_uses_latest_event_time_not_latest_arrival(self):
        self.press("AA", 10_000)
        self.press("L1", 30_000)
        self.press("L2", 20_000)
        self.assertEqual(self.state["run_done_event_ts"]["5"], 30_000)

    def test_combo_completion_uses_latest_finish_event_time(self):
        self.state["settings"]["starter_is_finish"] = "1"
        self.press("AA", 10_000)
        self.press("AA", 30_000)
        self.press("AA", 20_000)
        self.assertEqual(self.state["run_done_event_ts"]["5"], 30_000)

    def test_retry_after_xml_generation_failure_finishes_processing(self):
        self.press("AA", 10_000)
        self.press("L1", 15_000)
        event = {"mac": "L2", "ts": 16_000, "trigger_id": "boot:last"}
        with patch.object(
            stopwatch, "_write_heats_xml", side_effect=[RuntimeError("xml"), None]
        ) as write:
            self.assertEqual(self.client.post("/api/triggers", json=event).status_code, 500)
            self.assertEqual(self.client.post("/api/triggers", json=event).status_code, 200)
        self.assertEqual(write.call_count, 2)
        self.assertEqual(self.lane_time(5, "2"), 6_000)

    def test_retry_start_after_last_replayed_press_saved_but_xml_failed(self):
        self.press("L1", 15_000)
        self.press("L2", 16_000)
        with patch.object(
            stopwatch, "_write_heats_xml", side_effect=[RuntimeError("xml"), None]
        ) as write:
            self.assertEqual(self.press("AA", 10_000).status_code, 500)
            self.assertEqual(self.state["replay_pending_run"], "5")
            self.assertEqual(self.state["deferred_presses"], [])
            self.assertEqual(self.press("L1", 22_000).status_code, 503)
            self.assertEqual(self.press("AA", 10_000).status_code, 200)
        self.assertIsNone(self.state["replay_pending_run"])
        self.assertEqual(write.call_count, 2)

    def test_pending_replay_requires_original_starter_event_id(self):
        self.press("L1", 15_000)
        event = {"mac": "AA", "ts": 10_000, "trigger_id": "boot:original"}
        handler = stopwatch._handle_trigger

        def fail_replay(st, payload, replay=False):
            if replay:
                raise RuntimeError("replay failed")
            return handler(st, payload, replay=replay)

        with patch.object(stopwatch, "_handle_trigger", side_effect=fail_replay):
            self.assertEqual(self.client.post("/api/triggers", json=event).status_code, 500)
        other = {**event, "trigger_id": "boot:other"}
        self.assertEqual(self.client.post("/api/triggers", json=other).status_code, 503)
        self.assertEqual(self.client.post("/api/triggers", json=event).status_code, 200)

    def test_operator_can_resume_replay_without_starter_retry(self):
        self.press("L1", 15_000)
        handler = stopwatch._handle_trigger

        def fail_replay(st, payload, replay=False):
            if replay:
                raise RuntimeError("replay failed")
            return handler(st, payload, replay=replay)

        with patch.object(stopwatch, "_handle_trigger", side_effect=fail_replay):
            self.assertEqual(self.press("AA", 10_000).status_code, 500)
        self.assertEqual(self.client.post("/api/replay/resume", json={}).status_code, 200)
        self.assertIsNone(self.state["replay_pending_run"])
        self.assertEqual(self.lane_time(5, "1"), 5_000)

    def test_late_lane_press_requires_manual_review_instead_of_being_ignored(self):
        self.press("AA", 10_000)
        self.press("L1", 20_000)
        self.press("L2", 21_000)
        self.press("AA", 40_000)
        event = {"mac": "L2", "ts": 25_000, "trigger_id": "boot:late-lane"}
        first = self.client.post("/api/triggers", json=event)
        self.assertEqual(first.json["reason"], "manual_lane_review")
        pending = self.client.get("/api/run-status").json["unresolved_lane_presses"]
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["review_run_key"], "6")
        self.assertEqual(
            pending[0]["start_context"],
            {
                "before": [{"run_key": "5", "ts": 10_000}],
                "after": [{"run_key": "6", "ts": 40_000}],
            },
        )
        self.assertEqual(self.client.post("/api/triggers", json=event).json["id"], pending[0]["id"])

    def test_existing_reviews_get_start_context_without_guessing_original_run(self):
        self.state["triggers_per_run"] = {
            "5": {"starter": {"ts": 10_000, "mac": "AA"}},
            "5/2": {"starter": {"ts": 10_000, "mac": "AA"}},
            "6": {"starter": {"ts": 40_000, "mac": "AA"}},
        }
        self.state["unresolved_lane_presses"] = [
            {"id": "p", "mac": "L1", "ts": 10_000, "reason": "role_changed", "original_lane": "1"}
        ]
        self.state["unresolved_finish_presses"] = [{"id": "f", "mac": "FIN", "ts": 50_000}]
        status = self.client.get("/api/run-status").json
        lane = status["unresolved_lane_presses"][0]
        self.assertNotIn("review_run_key", lane)
        self.assertEqual(
            lane["start_context"],
            {
                "before": [{"run_key": "5", "ts": 10_000}, {"run_key": "5/2", "ts": 10_000}],
                "after": [{"run_key": "6", "ts": 40_000}],
            },
        )
        self.assertEqual(
            status["unresolved_finish_presses"][0]["start_context"],
            {"before": [{"run_key": "6", "ts": 40_000}], "after": []},
        )

    def test_unassigned_deferred_press_is_preserved_when_replay_cannot_find_role(self):
        self.press("L1", 15_000)
        self.state["assignments"]["mapping"].pop("1")
        response = self.press("AA", 10_000)
        self.assertEqual(response.status_code, 200)
        pending = self.state["unresolved_lane_presses"]
        self.assertEqual((pending[0]["mac"], pending[0]["ts"]), ("L1", 15_000))
        self.assertFalse(self.state["deferred_presses"])

    def test_moved_lane_press_keeps_original_lane_after_role_change(self):
        self.state["assignments"]["mapping"] = {"starter": "AA", "1": "L2", "2": "L1"}
        self.state["triggers_per_run"] = {
            "5": {"starter": {"ts": 10_000, "mac": "AA"}, "1": {"ts": 30_000, "mac": "L1"}}
        }
        self.assertEqual(self.press("AA", 20_000).status_code, 200)
        self.assertEqual(self.state["deferred_presses"][0]["lane"], "1")
        self.assertEqual(self.press("AA", 25_000).status_code, 200)
        pending = self.state["unresolved_lane_presses"]
        self.assertEqual((pending[0]["original_lane"], pending[0]["mac"]), ("1", "L1"))
        self.assertFalse((self.state["triggers_per_run"]["6"]).get("2"))

    def test_operator_resolves_lane_review_without_overwriting_existing_results(self):
        self.state["triggers_per_run"] = {
            "5": {"starter": {"ts": 10_000, "mac": "AA"}, "1": {"ts": 17_000, "mac": "L1"}}
        }
        self.state["unresolved_lane_presses"] = [
            {
                "id": "p",
                "mac": "L2",
                "ts": 18_000,
                "trigger_id": "boot:late",
                "reason": "role_changed",
            },
        ]
        base = {"id": "p", "action": "assign", "run_key": "5", "lane": "1", "note": "Protokoll"}
        self.assertEqual(self.client.post("/api/lane-review/resolve", json=base).status_code, 400)
        body = {**base, "lane": "2"}
        self.assertEqual(self.client.post("/api/lane-review/resolve", json=body).status_code, 200)
        self.assertEqual(self.client.post("/api/lane-review/resolve", json=body).status_code, 200)
        self.assertEqual(self.lane_time(5, "1"), 7_000)
        self.assertEqual(self.lane_time(5, "2"), 8_000)
        self.assertIsNotNone(self.state["run_finished_ts"])
        self.assertEqual(self.state["reviewed_lane_presses"][0]["note"], "Protokoll")
        retry = self.client.post(
            "/api/triggers", json={"mac": "L2", "ts": 18_000, "trigger_id": "boot:late"}
        )
        self.assertEqual(retry.status_code, 200)

    def test_operator_can_park_review_without_erasing_raw_event(self):
        self.state["unresolved_lane_presses"] = [
            {"id": "p", "mac": "L2", "ts": 18_000, "reason": "role_changed"}
        ]
        body = {
            "id": "p",
            "action": "park",
            "run_key": None,
            "lane": None,
            "note": "Fehlausloesung",
        }
        self.assertEqual(
            self.client.post("/api/lane-review/resolve", json={**body, "note": ""}).status_code, 400
        )
        self.assertEqual(self.client.post("/api/lane-review/resolve", json=body).status_code, 200)
        self.assertEqual(self.state["reviewed_lane_presses"][0]["ts"], 18_000)
        self.assertEqual(self.state["unresolved_lane_presses"], [])

    def test_operator_can_park_finish_with_reason_and_archive_raw_data(self):
        self.state["unresolved_finish_presses"] = [
            {"id": "p", "mac": "FIN", "ts": 15_000, "trigger_id": "boot:finish"}
        ]
        body = {"id": "p", "action": "park", "run_key": None, "note": "Fehlausloesung"}
        self.assertEqual(
            self.client.post("/api/finish/resolve", json={**body, "note": ""}).status_code, 400
        )
        self.assertEqual(self.client.post("/api/finish/resolve", json=body).status_code, 200)
        self.assertEqual(self.client.post("/api/finish/resolve", json=body).status_code, 200)
        self.assertEqual(self.state["finish_resolution_receipts"]["p"]["ts"], 15_000)
        retry = self.client.post(
            "/api/triggers", json={"mac": "FIN", "ts": 15_000, "trigger_id": "boot:finish"}
        )
        self.assertEqual(retry.status_code, 200)
        self.assertFalse(self.state.get("finish_per_run"))

    def test_operator_can_recover_finish_press_and_complete_combo_run(self):
        self.state["settings"]["starter_is_finish"] = "1"
        self.state["startcards_per_run"]["5"] = [{"Bahn": "1"}]
        self.state["triggers_per_run"] = {"5": {"starter": {"ts": 10_000, "mac": "AA"}}}
        self.state["unresolved_lane_presses"] = [
            {"id": "p", "mac": "FIN", "ts": 18_000, "reason": "role_changed"},
        ]
        body = {
            "id": "p",
            "action": "finish",
            "run_key": "5",
            "lane": None,
            "note": "Zielprotokoll",
        }
        self.assertEqual(self.client.post("/api/lane-review/resolve", json=body).status_code, 200)
        self.assertEqual(self.client.post("/api/lane-review/resolve", json=body).status_code, 200)
        self.assertEqual(self.state["finish_per_run"]["5"][0]["ts"], 18_000)
        self.assertIsNotNone(self.state["run_finished_ts"])

    def test_manual_lane_review_requires_login_and_preserves_pending_on_save_error(self):
        self.state["unresolved_lane_presses"] = [
            {"id": "p", "mac": "L2", "ts": 18_000, "reason": "role_changed"}
        ]
        body = {"id": "p", "action": "park", "run_key": None, "lane": None, "note": "Protokoll"}
        with patch.dict(stopwatch.app.config, {"AUTH_DISABLED": False}):
            with patch.object(stopwatch.auth, "load", return_value={"user": "judge"}):
                self.assertEqual(
                    self.client.post("/api/lane-review/resolve", json=body).status_code, 401
                )
        with patch.object(stopwatch, "save_state", side_effect=RuntimeError("storage unavailable")):
            self.assertEqual(
                self.client.post("/api/lane-review/resolve", json=body).status_code, 500
            )
        self.assertEqual(len(self.state["unresolved_lane_presses"]), 1)
        self.assertFalse(self.state.get("reviewed_lane_presses"))

    def test_rejected_trigger_logs_reason_and_identity(self):
        self.press("AA", 10_000)
        self.press("L1", 20_000)
        with self.assertLogs(stopwatch.logger, level="WARNING") as logs:
            response = self.client.post(
                "/api/triggers",
                json={
                    "mac": "L1",
                    "ts": 20_000,
                    "trigger_id": "boot:press",
                },
            )
        self.assertEqual(response.status_code, 400)
        self.assertTrue(
            any("Double press detected." in line and "boot:press" in line for line in logs.output)
        )

    def test_lane_retry_with_trigger_id_is_idempotent_after_run_change(self):
        self.press("AA", 10_000)
        event = {"mac": "L1", "ts": 20_000, "trigger_id": "boot:lane-1"}
        first = self.client.post("/api/triggers", json=event)
        self.press("L2", 21_000)
        self.press("AA", 40_000)
        repeated = self.client.post("/api/triggers", json=event)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(repeated.status_code, 200)
        self.assertEqual(repeated.json["press"]["run_key"], "5")
        self.assertEqual(repeated.json["press"]["lane"], "1")
        self.assertFalse((self.state["triggers_per_run"].get("6") or {}).get("1"))

    def test_lane_retry_before_run_end_is_idempotent(self):
        self.press("AA", 10_000)
        event = {"mac": "L1", "ts": 20_000, "trigger_id": "boot:lane-1"}
        first = self.client.post("/api/triggers", json=event)
        retry = self.client.post("/api/triggers", json=event)
        self.assertEqual(retry.status_code, 200)
        self.assertEqual(retry.json["press"], first.json["press"])

    def test_deferred_lane_retry_after_replay_is_idempotent(self):
        event = {"mac": "L1", "ts": 15_000, "trigger_id": "boot:lane-1"}
        self.assertTrue(self.client.post("/api/triggers", json=event).json["deferred"])
        self.press("AA", 10_000)
        retry = self.client.post("/api/triggers", json=event)
        self.assertEqual(retry.status_code, 200)
        self.assertEqual(retry.json["press"]["run_key"], "5")
        self.assertEqual(self.lane_time(5, "1"), 5_000)

    def test_same_trigger_id_with_different_timestamp_is_rejected(self):
        self.press("AA", 10_000)
        event = {"mac": "L1", "ts": 20_000, "trigger_id": "boot:lane-1"}
        self.client.post("/api/triggers", json=event)
        event["ts"] = 25_000
        retry = self.client.post("/api/triggers", json=event)
        self.assertEqual(retry.status_code, 422)
        self.assertEqual(self.lane_time(5, "1"), 10_000)

    def test_ignored_lockout_press_retry_stays_ignored_after_run_change(self):
        self.press("AA", 10_000)
        event = {"mac": "L1", "ts": 10_500, "trigger_id": "boot:lockout"}
        first = self.client.post("/api/triggers", json=event)
        self.assertEqual(first.json["reason"], "stop_lockout")
        self.press("L1", 20_000)
        self.press("L2", 21_000)
        self.press("AA", 40_000)
        retry = self.client.post("/api/triggers", json=event)
        self.assertEqual(retry.json["reason"], "stop_lockout")
        self.assertFalse(self.state.get("unresolved_lane_presses"))
        conflict = self.client.post("/api/triggers", json={**event, "ts": 10_501})
        self.assertEqual(conflict.status_code, 422)

    def test_full_deferred_buffer_rejects_new_press_without_losing_old(self):
        with patch.object(stopwatch, "DEFERRED_MAX_COUNT", 2):
            self.assertEqual(self.press("L1", 15_000).status_code, 200)
            self.assertEqual(self.press("L2", 16_000).status_code, 200)
            rejected = self.press("L1", 17_000)
        self.assertEqual(rejected.status_code, 503)
        self.assertEqual(
            {(p["mac"], p["ts"]) for p in self.state["deferred_presses"]},
            {("L1", 15_000), ("L2", 16_000)},
        )

    def test_old_deferred_press_is_not_expired_by_new_press(self):
        with patch.object(stopwatch, "now_ms", return_value=1_000):
            self.press("L1", 15_000)
        with patch.object(stopwatch, "now_ms", return_value=2_000_000):
            self.press("L2", 16_000)
        self.assertEqual(len(self.state["deferred_presses"]), 2)

    def test_replay_failure_keeps_unprocessed_presses(self):
        self.press("L1", 15_000)
        self.press("L2", 16_000)
        handler = stopwatch._handle_trigger

        def fail_replay(st, payload, replay=False):
            if replay:
                raise RuntimeError("simulated processing failure")
            return handler(st, payload, replay=replay)

        with patch.object(stopwatch, "_handle_trigger", side_effect=fail_replay):
            response = self.press("AA", 10_000)
        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            {(p["mac"], p["ts"]) for p in self.state["deferred_presses"]},
            {("L1", 15_000), ("L2", 16_000)},
        )
        retry = self.press("AA", 10_000)
        self.assertEqual(retry.status_code, 200)
        self.assertEqual(self.lane_time(5, "1"), 5_000)
        self.assertEqual(self.lane_time(5, "2"), 6_000)
        self.assertEqual(self.state.get("deferred_presses"), [])

    def test_replay_failure_keeps_remaining_presses_after_first_success(self):
        self.press("L1", 15_000)
        self.press("L2", 16_000)
        handler = stopwatch._handle_trigger

        def fail_second(st, payload, replay=False):
            if replay and payload.get("mac") == "L2":
                raise RuntimeError("simulated processing failure")
            return handler(st, payload, replay=replay)

        with patch.object(stopwatch, "_handle_trigger", side_effect=fail_second):
            response = self.press("AA", 10_000)
        self.assertEqual(response.status_code, 500)
        self.assertEqual(self.lane_time(5, "1"), 5_000)
        self.assertEqual([p["mac"] for p in self.state["deferred_presses"]], ["L2"])
        self.assertEqual(self.press("AA", 10_000).status_code, 200)
        self.assertEqual(self.lane_time(5, "2"), 6_000)
        self.assertEqual(self.state.get("deferred_presses"), [])

    def test_replay_rejection_keeps_the_unprocessed_press(self):
        self.press("L1", 15_000)
        del self.state["assignments"]["mapping"]["1"]
        response = self.press("AA", 10_000)
        self.assertEqual(response.status_code, 200)
        pending = self.state["unresolved_lane_presses"][0]
        resolution = self.client.post(
            "/api/lane-review/resolve",
            json={
                "id": pending["id"],
                "action": "assign",
                "run_key": "5",
                "lane": "1",
                "note": "Kontrolliert",
            },
        )
        self.assertEqual(resolution.status_code, 200)
        self.assertEqual(self.lane_time(5, "1"), 5_000)

    def test_combo_starter_retry_resumes_replay_not_finish(self):
        self.state["settings"]["starter_is_finish"] = "1"
        self.press("L1", 15_000)
        handler = stopwatch._handle_trigger

        def fail_replay(st, payload, replay=False):
            if replay:
                raise RuntimeError("simulated processing failure")
            return handler(st, payload, replay=replay)

        with patch.object(stopwatch, "_handle_trigger", side_effect=fail_replay):
            self.assertEqual(self.press("AA", 10_000).status_code, 500)
        retry = self.press("AA", 10_000)
        self.assertEqual(retry.status_code, 200)
        self.assertEqual(self.lane_time(5, "1"), 5_000)
        self.assertFalse((self.state.get("finish_per_run") or {}).get("5"))

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

    def test_next_run_stop_arriving_before_starter_stop_moves_to_next_run(self):
        self.press("AA", 10_000)
        self.press("L1", 20_000)
        self.press("L2", 50_000)  # eigentlich Lauf 6, kam vor dem Starter-Stopp an
        self.press("AA", 25_000)
        self.assertIsNone(self.state["triggers_per_run"]["5"].get("2"))
        self.press("AA", 40_000)
        self.assertEqual(self.lane_time(6, "2"), 10_000)

    def test_lanes_without_taster_do_not_block_next_run(self):
        # Fuenf Bahnen im Lauf, aber nur Bahn 2 hat einen Taster
        self.state["startcards_per_run"]["5"] = [{"Bahn": str(i)} for i in range(1, 6)]
        self.state["assignments"]["mapping"] = {"starter": "AA", "2": "L2"}
        self.press("AA", 10_000)
        self.press("L2", 20_000)
        self.assertIsNotNone(self.state["run_finished_ts"])
        self.press("AA", 60_000)
        self.assertEqual(self.state["current_run"], 6)

    def test_combo_starter_replay_starts_next_run_after_grace(self):
        self.state["settings"]["starter_is_finish"] = "1"
        self.state["assignments"]["mapping"] = {"starter": "AA", "2": "L2"}
        self.press("AA", 10_000)
        self.press("L2", 20_000)  # einzige Bahn mit Taster: Lauf beendet
        self.press("AA", 60_000)  # neuer Start, kein Zieleinlauf
        self.assertEqual(self.state["current_run"], 6)

    def test_combo_finish_count_ends_run(self):
        self.state["settings"]["starter_is_finish"] = "1"
        self.press("AA", 10_000)
        self.press("AA", 20_000)
        self.press("AA", 21_000)
        self.assertIsNotNone(self.state["run_finished_ts"])
        self.press("AA", 60_000)
        self.assertEqual(self.state["current_run"], 6)

    def test_unrelated_old_press_is_not_counted(self):
        self.press("L1", 1_000)
        self.press("AA", 10_000)
        self.assertIsNone(self.state["triggers_per_run"]["5"].get("1"))


if __name__ == "__main__":
    unittest.main()
