import sys
import unittest
from pathlib import Path
from unittest.mock import patch


API_DIR = Path(__file__).resolve().parents[1] / "api"
sys.path.insert(0, str(API_DIR))

import resolver


class ResolverSourcesTest(unittest.TestCase):
    def test_indexes_legacy_and_press_benches(self):
        sources = {
            "dukkani-backend-1": [
                ("legacy.dukani.ai", {"db_name": "legacy", "db_password": "x"})
            ],
            "bench-0001-000007-dukkanip": [
                ("press.dukani.ai", {"db_name": "press", "db_password": "y"})
            ],
        }

        def site_configs(container):
            return sources[container]

        responses = [
            type("Result", (), {"stdout": "legacy@example.com\n"})(),
            type("Result", (), {"stdout": "press@example.com\n"})(),
        ]
        with patch.object(resolver, "_site_configs", side_effect=site_configs):
            with patch.object(resolver, "_docker", side_effect=responses):
                index = resolver.build_index()

        self.assertEqual(index["legacy@example.com"], "legacy.dukani.ai")
        self.assertEqual(index["press@example.com"], "press.dukani.ai")


if __name__ == "__main__":
    unittest.main()
