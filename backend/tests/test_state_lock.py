import unittest
from unittest.mock import patch

import app as stopwatch


class FakeRedis:
    def __init__(self):
        self.data = {}

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value, **_kwargs):
        self.data[key] = value


class BusyLock:
    def __init__(self):
        self.timeout = None

    def acquire(self, timeout):
        self.timeout = timeout
        return False

    def release(self):
        raise AssertionError("A lock that was not acquired must not be released")


class StateLockTests(unittest.TestCase):
    def setUp(self):
        stopwatch.app.config["AUTH_DISABLED"] = True
        self.addCleanup(stopwatch.app.config.pop, "AUTH_DISABLED", None)
        self.client = stopwatch.app.test_client()

    def test_write_request_is_rejected_if_state_lock_times_out(self):
        lock = BusyLock()
        with patch.object(stopwatch, "_STATE_LOCK", lock), \
             patch.object(stopwatch, "load_state") as load_state:
            response = self.client.post("/api/vitals", json={"mac": "AA:BB:CC:DD:EE:FF"})

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.headers["Retry-After"], "1")
        self.assertEqual(response.get_json(), {
            "ok": False,
            "error": "state_busy",
            "message": "Der Wettkampfzustand ist gerade belegt. Bitte erneut versuchen.",
        })
        self.assertEqual(lock.timeout, stopwatch._STATE_LOCK_TIMEOUT_S)
        self.assertEqual(lock.timeout, 0.25)
        load_state.assert_not_called()

    def test_alert_state_does_not_acquire_competition_lock(self):
        lock = BusyLock()
        with patch.object(stopwatch, "_STATE_LOCK", lock), \
             patch.object(stopwatch, "redis_store", FakeRedis()):
            response = self.client.post("/api/alert-state", json={"yellow": [], "red": []})

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(lock.timeout)

    def test_redis_connection_timeouts_are_bounded(self):
        connection_kwargs = stopwatch.redis_store.connection_pool.connection_kwargs

        self.assertEqual(connection_kwargs["socket_connect_timeout"], 1.0)
        self.assertEqual(connection_kwargs["socket_timeout"], 1.0)


if __name__ == "__main__":
    unittest.main()
