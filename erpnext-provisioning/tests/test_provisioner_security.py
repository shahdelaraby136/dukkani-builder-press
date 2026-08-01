import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


API_DIR = Path(__file__).resolve().parents[1] / "api"
sys.path.insert(0, str(API_DIR))

import provisioner


class SiteAdminPasswordTest(unittest.TestCase):
    def test_generates_strong_password_without_configuration(self):
        with patch.dict(os.environ, {}, clear=True):
            password = provisioner.site_admin_password()

        self.assertGreaterEqual(len(password), 32)
        self.assertNotEqual(password, "admin")

    def test_uses_explicit_secret_when_configured(self):
        with patch.dict(
            os.environ,
            {"DUKKANI_SITE_ADMIN_PASSWORD": "configured-secret"},
            clear=True,
        ):
            password = provisioner.site_admin_password()

        self.assertEqual(password, "configured-secret")


if __name__ == "__main__":
    unittest.main()
