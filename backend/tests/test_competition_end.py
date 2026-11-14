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
        with patch.object(stopwatch, "_write_heats_xml"):
            response = self.client.post(
                "/api/competition/end", json={"name": "", "shutdown_tasters": False}
            )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json["shutdown_tasters"])
        self.assertEqual(response.json["shutdown_grace_s"], 0)
        self.assertEqual(self.state["shutdown_until_ms"], 0)

    def test_ending_still_shuts_down_tasters_by_default(self):
        with patch.object(stopwatch, "_write_heats_xml"), patch.object(
            stopwatch, "now_ms", return_value=100_000
        ):
            response = self.client.post("/api/competition/end", json={"name": ""})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json["shutdown_tasters"])
        self.assertEqual(response.json["shutdown_grace_s"], 10)
        self.assertEqual(self.state["shutdown_until_ms"], 110_000)


if __name__ == "__main__":
    unittest.main()
