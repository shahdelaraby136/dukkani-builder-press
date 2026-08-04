import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch


MODULE_PATH = Path(__file__).resolve().parents[1] / "api" / "shopapi.py"
SPEC = importlib.util.spec_from_file_location("shopapi_under_test", MODULE_PATH)
shopapi = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(shopapi)


class SiteContainerRoutingTests(unittest.TestCase):
    @patch.object(shopapi.subprocess, "run")
    def test_selects_container_that_contains_site(self, run):
        run.side_effect = [
            type("Result", (), {"returncode": 1})(),
            type("Result", (), {"returncode": 0})(),
        ]

        selected = shopapi._container_for_site("sense.dukani.ai")

        self.assertEqual(selected, "bench-0001-000007-dukkanip")
        self.assertEqual(run.call_count, 2)

    @patch.object(shopapi.subprocess, "run")
    def test_rejects_unknown_site(self, run):
        run.return_value = type("Result", (), {"returncode": 1})()

        with self.assertRaisesRegex(RuntimeError, "site was not found"):
            shopapi._container_for_site("missing.dukani.ai")


if __name__ == "__main__":
    unittest.main()
