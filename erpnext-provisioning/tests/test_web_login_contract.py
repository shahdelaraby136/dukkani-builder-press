import unittest
from pathlib import Path


WEB_LOGIN = (
    Path(__file__).resolve().parents[1] / "api" / "web-login.html"
).read_text(encoding="utf-8")


class WebLoginContractTest(unittest.TestCase):
    def test_system_administrator_uses_central_frappe_login(self):
        self.assertIn('usr: "Administrator"', WEB_LOGIN)
        self.assertIn('fetch("/api/method/login"', WEB_LOGIN)
        self.assertIn('location.assign("/desk")', WEB_LOGIN)

    def test_merchants_still_resolve_their_tenant(self):
        self.assertIn('fetch("/resolve?email="', WEB_LOGIN)
        self.assertIn('".dukani.ai/merchant-login"', WEB_LOGIN)


if __name__ == "__main__":
    unittest.main()
