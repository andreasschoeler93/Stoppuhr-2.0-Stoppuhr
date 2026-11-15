import copy
import threading
import unittest
from unittest.mock import patch

import app as stopwatch


class DisplayLongPollTests(unittest.TestCase):
    def setUp(self):
        self.state = stopwatch._default_state()
        self.state["assignments"]["mapping"] = {"starter": "STARTER", "1": "LANE"}
        self.state["startcards_per_run"] = {"1": [{"Bahn": "1"}]}
        self.real_save_state = stopwatch.save_state
        stopwatch.app.config["AUTH_DISABLED"] = True
        old_secret = stopwatch.app.secret_key
        stopwatch.app.secret_key = "test-secret"
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
        no_ota = patch.object(stopwatch, "_load_ota", return_value=None)
        no_ota.start()
        self.addCleanup(no_ota.stop)
        self.addCleanup(self.load_state.stop)
        self.addCleanup(self.save_state.stop)
        self.addCleanup(setattr, stopwatch.app, "secret_key", old_secret)
        self.addCleanup(stopwatch.app.config.pop, "AUTH_DISABLED", None)
        self.addCleanup(setattr, stopwatch, "_STATE_CHANGE_ID", 0)

    def test_starter_waits_for_changes_and_returns_new_sequence(self):
        since = stopwatch._state_change_token()
        update = threading.Timer(0.01, stopwatch._notify_state_change)
        update.start()
        self.addCleanup(update.join)

        response = self.client.get(
            "/api/display",
            query_string={"mac": "STARTER", "since": since, "wait_ms": 1500},
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(response.json["state_seq"], since)
        update.join(1)
        self.assertFalse(update.is_alive())

    def test_non_starter_does_not_wait(self):
        since = stopwatch._state_change_token()

        with patch.object(stopwatch, "_wait_for_state_change") as wait:
            response = self.client.get(
                "/api/display",
                query_string={"mac": "LANE", "since": since, "wait_ms": 1500},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["role"], "lane")
        wait.assert_not_called()

    def test_stale_sequence_returns_immediately(self):
        since = "old-process-1"

        with patch.object(stopwatch, "_wait_for_state_change") as wait:
            response = self.client.get(
                "/api/display",
                query_string={"mac": "STARTER", "since": since, "wait_ms": 1500},
            )

        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(response.json["state_seq"], since)
        wait.assert_not_called()

    def test_wait_duration_is_bounded(self):
        for wait_ms in ("-1", "1501", "invalid"):
            with self.subTest(wait_ms=wait_ms):
                response = self.client.get(
                    "/api/display",
                    query_string={"mac": "STARTER", "wait_ms": wait_ms},
                )
                self.assertEqual(response.status_code, 400)

    def test_saving_state_advances_sequence(self):
        since = stopwatch._state_change_token()

        with patch.object(stopwatch.redis_store, "set") as redis_set:
            self.real_save_state(self.state)

        self.assertNotEqual(stopwatch._state_change_token(), since)
        redis_set.assert_called_once()


if __name__ == "__main__":
    unittest.main()
