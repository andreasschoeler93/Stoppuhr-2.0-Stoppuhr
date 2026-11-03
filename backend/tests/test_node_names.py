import unittest

import node_names


class NodeNamesTests(unittest.TestCase):
    def test_defaults_when_nothing_saved(self):
        self.assertEqual(node_names.effective(None), node_names.DEFAULTS)

    def test_normalize_trims_and_lowercases(self):
        names = node_names.normalize({"koffer": " Stoppuhr-Koffer ", "bad": "BAD", "shared": "Zeit"})
        self.assertEqual(names, {"koffer": "stoppuhr-koffer", "bad": "bad", "shared": "zeit"})

    def test_valid_names(self):
        self.assertIsNone(node_names.validate(node_names.DEFAULTS))

    def test_rejects_invalid_characters(self):
        for bad in ("", "-abc", "abc-", "a b", "ä", "a.b", "x" * 64):
            names = dict(node_names.DEFAULTS, shared=bad)
            self.assertIsNotNone(node_names.validate(names), bad)

    def test_rejects_duplicates(self):
        names = dict(node_names.DEFAULTS, bad=node_names.DEFAULTS["koffer"])
        self.assertIsNotNone(node_names.validate(names))


if __name__ == "__main__":
    unittest.main()
