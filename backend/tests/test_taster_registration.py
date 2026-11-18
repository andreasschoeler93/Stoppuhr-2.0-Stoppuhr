import copy
import unittest
from unittest.mock import patch

import app as stopwatch


class TasterRegistrationTests(unittest.TestCase):
    def setUp(self):
        self.state = stopwatch._default_state()
        stopwatch.app.config["AUTH_DISABLED"] = True
        self.addCleanup(stopwatch.app.config.pop, "AUTH_DISABLED", None)
        old_secret = stopwatch.app.secret_key
        stopwatch.app.secret_key = "taster-registration-test-secret"
        self.addCleanup(setattr, stopwatch.app, "secret_key", old_secret)
        self.client = stopwatch.app.test_client()
        for name, fn in (
            ("load_state", lambda: copy.deepcopy(self.state)),
            ("save_state", lambda state: self.state.update(copy.deepcopy(state))),
        ):
            p = patch.object(stopwatch, name, side_effect=fn)
            p.start()
            self.addCleanup(p.stop)

    def test_registration_assigns_twelve_letters_through_l(self):
        letters = []
        for index in range(12):
            response = self.client.post(
                "/api/taster",
                json={"mac": f"AA:BB:CC:DD:EE:{index:02X}", "name": f"T-{index}"},
            )
            self.assertEqual(response.status_code, 200)
            letters.append(response.json["taster"]["letter"])

        self.assertEqual(letters, list("ABCDEFGHIJKL"))


if __name__ == "__main__":
    unittest.main()
