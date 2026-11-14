import copy
import unittest
from unittest.mock import patch

import app as stopwatch


class CompetitionEndTests(unittest.TestCase):
    def setUp(self):
        self.state = stopwatch._default_state()
        self.state["shutdown_until_ms"] = 123_000
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
        self.addCleanup(stopwatch.app.config.pop, "AUTH_DISABLED", None)

    def test_ending_without_shutdown_keeps_shutdown_inactive(self):
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

    def test_ending_still_shuts_down_tasters_by_default(self):
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
        self.assertEqual(
            self.state["assignments"],
            {"mapping": {}, "pending": {}, "last_update_ts": None},
        )


if __name__ == "__main__":
    unittest.main()
