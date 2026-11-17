import copy
import unittest
from unittest.mock import patch

import app as stopwatch
import archive


class FakeRedis:
    def __init__(self):
        self.data = {}
        self.hashes = {}
        self.commands = []

    def pipeline(self):
        self.commands = []
        return self

    def set(self, key, value):
        self.commands.append(("set", key, value))
        return self

    def hset(self, key, field, value):
        self.commands.append(("hset", key, field, value))
        return self

    def delete(self, key):
        self.commands.append(("delete", key))
        return self

    def hdel(self, key, field):
        self.commands.append(("hdel", key, field))
        return self

    def execute(self):
        result = []
        for action, *args in self.commands:
            if action == "set":
                self.data[args[0]] = args[1]
                result.append(True)
            elif action == "hset":
                self.hashes.setdefault(args[0], {})[args[1]] = args[2]
                result.append(1)
            elif action == "delete":
                result.append(int(self.data.pop(args[0], None) is not None))
            elif action == "hdel":
                result.append(int(self.hashes.get(args[0], {}).pop(args[1], None) is not None))
        return result

    def get(self, key):
        return self.data.get(key)

    def hgetall(self, key):
        return self.hashes.get(key, {})


class ArchiveDeleteTests(unittest.TestCase):
    def setUp(self):
        self.redis = FakeRedis()
        self.client = stopwatch.app.test_client()
        old_secret = stopwatch.app.secret_key
        stopwatch.app.secret_key = "archive-test-secret"
        self.addCleanup(setattr, stopwatch.app, "secret_key", old_secret)
        self.patches = [
            patch.object(stopwatch, "redis_store", self.redis),
            patch.dict(stopwatch.app.config, {"AUTH_DISABLED": True}),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    def test_only_selected_archives_are_deleted(self):
        for cid in ("1", "2", "3"):
            archive.save(self.redis, {"id": cid, "name": cid, "heats": []})
        active = {"run": 5, "times": [123]}
        self.redis.data["active-competition"] = copy.deepcopy(active)
        for cid in ("1", "3"):
            self.assertEqual(self.client.delete(f"/api/archive/{cid}").status_code, 200)
        self.assertEqual([item["id"] for item in archive.list_all(self.redis)], ["2"])
        self.assertIsNotNone(archive.load(self.redis, "2"))
        self.assertIsNone(archive.load(self.redis, "1"))
        self.assertIsNone(archive.load(self.redis, "3"))
        self.assertEqual(self.redis.data["active-competition"], active)
        self.assertEqual(self.client.delete("/api/archive/1").status_code, 404)

    def test_deletion_requires_login(self):
        archive.save(self.redis, {"id": "1", "name": "Wettkampf"})
        with patch.dict(stopwatch.app.config, {"AUTH_DISABLED": False}), patch.object(
            stopwatch.auth, "load", return_value=None
        ):
            self.assertEqual(self.client.delete("/api/archive/1").status_code, 401)
        self.assertIsNotNone(archive.load(self.redis, "1"))


if __name__ == "__main__":
    unittest.main()
