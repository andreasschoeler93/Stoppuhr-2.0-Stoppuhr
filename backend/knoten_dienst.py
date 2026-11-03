"""Kleiner Dienst (Port 2000): liefert den Zustand dieses Pi als JSON unter /info.

Laeuft auf beiden Pis dauerhaft, damit der Partner den Zustand auch im Standby sieht.
"""

import json
import os
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import redis

import node_info
import node_names
import pi_update
import wifi_config


class Handler(BaseHTTPRequestHandler):
    def _json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/info":
            self._json(200, node_info.collect())
        elif path == "/pi-tags":
            # Nur vom Partner-Pi oder von diesem Pi selbst abrufbar
            if not self._from_trusted():
                self._json(403, {"error": "Nicht erlaubt"})
                return
            try:
                tags, error = pi_update.list_tags()
                self._json(200, {"tags": tags, "error": error, "supported": pi_update.available(),
                                 "current": pi_update.current()})
            except Exception as exc:
                self._json(500, {"error": str(exc)})
        else:
            self.send_error(404)

    def _from_trusted(self) -> bool:
        allowed = {"127.0.0.1", "::1"}
        peer = os.environ.get("PEER_IP")
        if peer:
            allowed.add(peer)
        return self.client_address[0] in allowed

    def do_POST(self):
        if self.path.split("?")[0] != "/pi-update":
            self.send_error(404)
            return
        if not self._from_trusted():
            self._json(403, {"error": "Nicht erlaubt"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            tag = str(json.loads(self.rfile.read(length) or b"{}").get("tag", ""))
        except Exception:
            self._json(400, {"error": "Ungueltige Anfrage"})
            return
        if pi_update.parse_tag(tag) is None:
            self._json(400, {"error": "Ungueltige Version"})
            return
        if not pi_update.available():
            self._json(400, {"error": "Kein Git-Checkout"})
            return
        try:
            pi_update.list_tags(force=True)
            commit = pi_update.switch_to(tag)
        except Exception as exc:
            self._json(500, {"error": f"Wechsel fehlgeschlagen: {exc}"})
            return
        node_info.invalidate_git_cache()
        print(f"Pi-Software auf {tag} ({commit}) gewechselt", flush=True)
        self._json(200, {"ok": True, "tag": tag, "commit": commit})
        threading.Timer(1.0, _restart_services).start()

    def log_message(self, *args):
        pass


def _restart_services() -> None:
    """Neue Version laden: Stoppuhr (falls sie hier arbeitet) neu starten, dann diesen Dienst beenden (systemd startet ihn neu)."""
    try:
        active = subprocess.run(["systemctl", "is-active", "stoppuhr"], capture_output=True, text=True, timeout=5)
        if active.stdout.strip() == "active":
            subprocess.run(["systemctl", "restart", "stoppuhr"], timeout=30, check=False)
    except Exception as exc:
        print(f"Neustart der Stoppuhr: {exc}", flush=True)
    os._exit(0)


def wlan_loop() -> None:
    """Stellt den Zugangspunkt dieses Pi auf die neuen WLAN-Daten um, sobald die Taster sie haben."""
    r = redis.Redis(host="127.0.0.1", port=6379, socket_timeout=2, decode_responses=True)
    kind = os.environ.get("ROLLE", "")
    retry_after = 0.0
    while True:
        time.sleep(5)
        try:
            cfg = wifi_config.load(r)
            if not cfg or wifi_config.applied_version() >= cfg["version"] or time.time() < retry_after:
                continue
            raw = r.get("STATE")
            state = json.loads(raw) if raw else {}
            if not wifi_config.ready_for_pi(cfg, state, int(time.time() * 1000)):
                continue
            error = wifi_config.apply_to_pi(cfg, kind)
            if error:
                print(f"WLAN umstellen fehlgeschlagen: {error}", flush=True)
                retry_after = time.time() + 60
        except Exception as exc:  # der Dienst darf wegen eines Fehlers hier nie enden
            print(f"WLAN-Abgleich: {exc}", flush=True)


def names_loop() -> None:
    """Setzt neue Pi-Namen um, sobald sie in der Oberflaeche gespeichert wurden."""
    r = redis.Redis(host="127.0.0.1", port=6379, socket_timeout=2, decode_responses=True)
    kind = os.environ.get("ROLLE", "")
    retry_after = 0.0
    while True:
        time.sleep(5)
        try:
            cfg = node_names.load(r)
            if not cfg or node_names.applied_version() >= cfg["version"] or time.time() < retry_after:
                continue
            error = node_names.apply_to_pi(cfg, kind)
            if error:
                print(f"Namen umstellen fehlgeschlagen: {error}", flush=True)
                retry_after = time.time() + 60
        except Exception as exc:  # der Dienst darf wegen eines Fehlers hier nie enden
            print(f"Namen-Abgleich: {exc}", flush=True)


if __name__ == "__main__":
    threading.Thread(target=wlan_loop, daemon=True).start()
    threading.Thread(target=names_loop, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", node_info.NODE_PORT), Handler).serve_forever()
