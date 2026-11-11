import copy
import unittest
from unittest.mock import patch

import app as stopwatch


class TasterSleepTests(unittest.TestCase):
    def setUp(self):
        self.state = stopwatch._default_state()
        self.state["tasters"] = [{"mac": "A", "letter": "A"}, {"mac": "B", "letter": "B"}]
        self.state["settings"]["shutdown_grace_s"] = "3600"
        stopwatch.app.config["AUTH_DISABLED"] = True
        self.client = stopwatch.app.test_client()
        class _NoRedis:
            def __getattr__(self, _name):
                def fail(*_a, **_k):
                    raise stopwatch.redis.RedisError("offline")

                return fail

        redis_patch = patch.object(stopwatch, "redis_store", _NoRedis())
        redis_patch.start()
        self.addCleanup(redis_patch.stop)
        for name, fn in (
            ("load_state", lambda: copy.deepcopy(self.state)),
            ("save_state", lambda s: self.state.update(copy.deepcopy(s))),
            ("_load_ota", lambda: None),
            ("_load_wifi_cfg", lambda: None),
        ):
            p = patch.object(stopwatch, name, side_effect=fn)
            p.start()
            self.addCleanup(p.stop)

    def test_wrong_confirmation_is_rejected(self):
        resp = self.client.post("/api/taster/sleep", json={"letter": "A", "confirm": "B"})
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(self.client.get("/api/display?mac=A").json["shutdown"])

    def test_only_the_chosen_taster_shuts_down(self):
        resp = self.client.post("/api/taster/sleep", json={"letter": "a", "confirm": "A"})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(self.client.get("/api/display?mac=A").json["shutdown"])
        self.assertFalse(self.client.get("/api/display?mac=B").json["shutdown"])

    def test_unknown_taster(self):
        resp = self.client.post("/api/taster/sleep", json={"letter": "Z", "confirm": "Z"})
        self.assertEqual(resp.status_code, 404)

    def test_taster_with_task_is_refused_during_run(self):
        self.state["assignments"]["mapping"] = {"1": "A"}
        with patch.object(stopwatch, "_run_in_progress", return_value=True):
            resp = self.client.post("/api/taster/sleep", json={"letter": "A", "confirm": "A"})
        self.assertEqual(resp.status_code, 409)


if __name__ == "__main__":
    unittest.main()
