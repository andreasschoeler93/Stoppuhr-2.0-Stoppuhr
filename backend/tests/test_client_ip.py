import re
import unittest
from unittest.mock import patch

import app as stopwatch


class ClientIpTests(unittest.TestCase):
    def setUp(self):
        stopwatch.app.config["AUTH_DISABLED"] = True
        self.addCleanup(stopwatch.app.config.pop, "AUTH_DISABLED", None)
        old_secret = stopwatch.app.secret_key
        stopwatch.app.secret_key = "test-secret"
        self.addCleanup(setattr, stopwatch.app, "secret_key", old_secret)
        self.client = stopwatch.app.test_client()

    def test_returns_direct_client_address_not_forwarded_header(self):
        response = self.client.get(
            "/api/client-ip",
            environ_base={"REMOTE_ADDR": "192.168.1.23"},
            headers={"X-Forwarded-For": "203.0.113.42"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"ip": "192.168.1.23"})

    def test_requires_login(self):
        stopwatch.app.config["AUTH_DISABLED"] = False
        with patch.object(stopwatch.auth, "load", return_value=None):
            response = self.client.get("/api/client-ip")
        self.assertEqual(response.status_code, 401)

    def test_dashboard_pages_and_settings_render(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        nav = html.split('<ul class="nav nav-tabs mb-3" id="mainTabs"', 1)[1].split("</ul>", 1)[0]
        targets = re.findall(r'data-bs-target="([^"]+)"', nav)
        self.assertEqual(targets, ["#home", "#vitals", "#archive", "#settings"])
        self.assertIn('id="btnUseClientIp"', html)
        self.assertIn('id="btnReloadStartcards"', html)
        self.assertLess(html.index('id="setupHomeSlot"'), html.index('id="laufSelect"'))
        self.assertIn('id="setupSettingsSlot"', html)
        self.assertIn('<section id="status"', html)

    def _banner_tag(self, role):
        with patch.dict("os.environ", {"ROLLE": role}):
            html = self.client.get("/").get_data(as_text=True)
        return html, re.search(r'<div id="takeoverBanner"[^>]*>', html).group(0)

    def test_backup_pi_marks_dashboard(self):
        html, banner = self._banner_tag("bad")
        self.assertIn('<body data-node="bad">', html)
        self.assertNotIn("d-none", banner)
        html, banner = self._banner_tag("koffer")
        self.assertIn('<body data-node="koffer">', html)
        self.assertIn("d-none", banner)


if __name__ == "__main__":
    unittest.main()
