import time
import unittest
from unittest.mock import patch

import app as stopwatch
import ladekoffer
import redis
import vitals_history


class FakeRedis:
    def __init__(self, fail=False):
        self.data = {}
        self.lists = {}
        self.fail = fail

    def pipeline(self):
        return self

    def rpush(self, key, value):
        self.lists.setdefault(key, []).append(value)

    def ltrim(self, key, start, end):
        if start < 0:
            self.lists[key] = self.lists.get(key, [])[start:]

    def execute(self):
        return []

    def lrange(self, key, start, end):
        return list(self.lists.get(key, []))

    def set(self, key, value):
        if self.fail:
            raise redis.RedisError("READONLY")
        self.data[key] = value

    def get(self, key):
        if self.fail:
            raise redis.RedisError("down")
        return self.data.get(key)


def slot(n, charging=False, fault=False, vbat=4.15, since_s=None):
    return {"n": n, "charging": charging, "fault": fault, "vbat": vbat, "since_s": since_s}


def payload(**over):
    p = {"mac": "AA:BB", "fw": "v0.1.0", "uptime_s": 10, "rssi": -50, "temp": 24.5, "humidity": 40,
         "aht_ok": True, "temp_alarm": False, "i2c_ok": True, "light": "green", "fault": False,
         "muted": False, "slots": [slot(n) for n in range(1, 11)]}
    p.update(over)
    return p


class SanitizeTests(unittest.TestCase):
    def test_rejects_garbage(self):
        self.assertIsNone(ladekoffer.sanitize(None))
        self.assertIsNone(ladekoffer.sanitize({"slots": "x"}))
        self.assertIsNone(ladekoffer.sanitize([]))

    def test_limits_and_types(self):
        s = ladekoffer.sanitize(payload(light="disco", temp="heiss", mac="x" * 100,
                                        slots=[slot(11), slot(0), slot(3, vbat=float("nan")), "x"]))
        self.assertEqual(s["light"], "off")
        self.assertIsNone(s["temp"])
        self.assertEqual(len(s["mac"]), 32)
        self.assertEqual([x["n"] for x in s["slots"]], [3])
        self.assertIsNone(s["slots"][0]["vbat"])


class EvaluateTests(unittest.TestCase):
    NOW = 1_000_000

    def _status(self, **over):
        s = ladekoffer.sanitize(payload(**over))
        s["ts"] = self.NOW
        return s

    def test_unknown(self):
        self.assertFalse(ladekoffer.evaluate(None, self.NOW)["known"])

    def test_idle(self):
        e = ladekoffer.evaluate(self._status(), self.NOW + 1000)
        self.assertEqual(e["state"], "ruhig")
        self.assertEqual(e["messages"], [])

    def test_charging(self):
        slots = [slot(n) for n in range(1, 11)]
        slots[1] = slot(2, charging=True, vbat=3.8)
        e = ladekoffer.evaluate(self._status(slots=slots), self.NOW)
        self.assertEqual(e["state"], "laedt")
        self.assertEqual(e["counts"], {"charging": 1})
        self.assertEqual([m["text"] for m in e["messages"]], ["Es wird geladen: Platz 2."])

    def test_charge_ended_message(self):
        slots = [slot(n) for n in range(1, 11)]
        slots[2] = slot(3, since_s=120)
        e = ladekoffer.evaluate(self._status(slots=slots), self.NOW)
        self.assertEqual([m["text"] for m in e["messages"]], ["Platz 3: Ladevorgang beendet (vor 2 Min.)."])
        slots[2] = slot(3, since_s=7200)
        self.assertEqual(ladekoffer.evaluate(self._status(slots=slots), self.NOW)["messages"], [])

    def test_temperature_alarm_is_error(self):
        e = ladekoffer.evaluate(self._status(temp_alarm=True, fault=True, temp=61.2, light="red"), self.NOW)
        self.assertEqual(e["state"], "fehler")
        self.assertEqual(e["messages"][0], {"level": "error", "text": "Übertemperatur im Ladekoffer (61,2 °C)."})

    def test_slot_fault_and_sensor(self):
        slots = [slot(n) for n in range(1, 11)]
        slots[6] = slot(7, fault=True, vbat=4.4)
        e = ladekoffer.evaluate(self._status(slots=slots, aht_ok=False, fault=True), self.NOW)
        self.assertEqual(e["state"], "fehler")
        texts = [m["text"] for m in e["messages"]]
        self.assertIn("Platz 7: Akkuspannung zu hoch (4,40 V).", texts)
        self.assertTrue(any("AHT20" in t for t in texts))

    def test_offline(self):
        e = ladekoffer.evaluate(self._status(), self.NOW + ladekoffer.OFFLINE_AFTER_MS + 120_000)
        self.assertFalse(e["online"])
        self.assertEqual(e["state"], "offline")
        self.assertEqual(e["messages"][0]["level"], "warn")


class EndpointTests(unittest.TestCase):
    def setUp(self):
        ladekoffer.reset_memory()
        self.addCleanup(ladekoffer.reset_memory)
        self.redis = FakeRedis()
        p = patch.object(stopwatch, "redis_store", self.redis)
        p.start()
        self.addCleanup(p.stop)
        stopwatch.app.config["AUTH_DISABLED"] = False
        self.client = stopwatch.app.test_client()

    def test_post_is_open_without_login_and_get_is_not(self):
        r = self.client.post("/api/charger", json=payload())
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.client.get("/api/charger").status_code, 401)
        self.assertEqual(self.client.post("/api/charger/wake", json={"slot": 1}).status_code, 401)

    def test_roundtrip(self):
        stopwatch.app.config["AUTH_DISABLED"] = True
        self.assertFalse(self.client.get("/api/charger").get_json()["known"])
        self.client.post("/api/charger", json=payload(voltage_history=[[5000, [3.8] * 10]]))
        body = self.client.get("/api/charger").get_json()
        self.assertTrue(body["known"] and body["online"])
        self.assertEqual(body["state"], "ruhig")
        self.assertLess(abs(body["status"]["ts"] - int(time.time() * 1000)), 5000)
        self.assertEqual(
            vitals_history.history_charger(self.redis),
            [[body["status"]["ts"], 24.5, 40.0]],
        )
        history = vitals_history.history_charger_slots(self.redis)
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0][1:], [3.8] * 10)
        self.assertAlmostEqual(body["status"]["ts"] - history[0][0], 5000, delta=1000)

    def test_long_press_sleeps_only_tasters_without_a_role(self):
        stopwatch.app.config["AUTH_DISABLED"] = True
        state = stopwatch._default_state()
        state["tasters"] = [
            {"mac": "A", "letter": "A"},
            {"mac": "B", "letter": "B"},
            {"mac": "C", "letter": "C"},
            {"mac": "D", "letter": "D"},
        ]
        state["assignments"]["mapping"] = {"starter": "A", "1": "B"}
        state["assignments"]["pending"] = {"2": "D"}
        state["settings"]["shutdown_grace_s"] = "10"
        with patch.object(stopwatch, "load_state", return_value=state), \
             patch.object(stopwatch, "save_state") as save_state, \
             patch.object(stopwatch, "now_ms", return_value=100_000):
            response = self.client.post("/api/charger", json=payload(sleep_unassigned=True))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["sleep_unassigned_count"], 1)
        self.assertEqual(state["sleep_until"], {"C": 110_000})
        save_state.assert_called_once_with(state)

    def test_invalid_payload(self):
        self.assertEqual(self.client.post("/api/charger", json={"x": 1}).status_code, 400)

    def test_manual_wake_uses_configured_pin_and_pulse_and_waits_for_ack(self):
        stopwatch.app.config["AUTH_DISABLED"] = True
        self.client.post("/api/charger", json=payload())
        self.client.post(
            "/api/settings",
            json={"charger_wake_pins": "1,2,3,4,5,6,7,8,9,10", "charger_wake_ms": 1800},
        )

        queued = self.client.post("/api/charger/wake", json={"slot": 4})
        self.assertEqual(queued.status_code, 202)
        request_id = queued.get_json()["id"]
        self.assertEqual(self.client.post("/api/charger/wake", json={"slot": 5}).status_code, 409)

        reply = self.client.post("/api/charger", json=payload()).get_json()
        self.assertEqual(reply["manual_wake"], {"id": request_id, "slot": 4})
        self.assertEqual(reply["wake"]["pins"][3], 4)
        self.assertEqual(reply["wake"]["ms"], 1800)

        ack = self.client.post("/api/charger", json=payload(wake_ack=request_id)).get_json()
        self.assertEqual(ack["wake_ack"], request_id)
        self.assertIsNone(ack["manual_wake"])
        result = self.client.get(f"/api/charger/wake/{request_id}")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.get_json()["status"], "completed")

    def test_manual_wake_validates_slot_and_charger_state(self):
        stopwatch.app.config["AUTH_DISABLED"] = True
        for invalid in (0, 11, True, "1"):
            self.assertEqual(
                self.client.post("/api/charger/wake", json={"slot": invalid}).status_code,
                400,
            )

        self.assertEqual(self.client.post("/api/charger/wake", json={"slot": 1}).status_code, 409)
        self.client.post("/api/charger", json=payload(wake_active=True))
        self.assertEqual(self.client.post("/api/charger/wake", json={"slot": 1}).status_code, 409)

        unknown_slots = [slot(n) for n in range(2, 11)]
        self.client.post("/api/charger", json=payload(slots=unknown_slots))
        self.assertEqual(self.client.post("/api/charger/wake", json={"slot": 1}).status_code, 409)

        faulty_slots = [slot(n, fault=n == 2) for n in range(1, 11)]
        self.client.post("/api/charger", json=payload(slots=faulty_slots))
        self.assertEqual(self.client.post("/api/charger/wake", json={"slot": 2}).status_code, 409)

    def test_redis_down_still_works(self):
        stopwatch.app.config["AUTH_DISABLED"] = True
        self.redis.fail = True
        self.assertEqual(self.client.post("/api/charger", json=payload()).status_code, 200)
        self.assertTrue(self.client.get("/api/charger").get_json()["known"])


if __name__ == "__main__":
    unittest.main()
