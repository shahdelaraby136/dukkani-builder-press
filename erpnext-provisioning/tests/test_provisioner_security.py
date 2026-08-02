import os
import sys
import unittest
from pathlib import Path
from subprocess import CompletedProcess
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


class AppInstallationTest(unittest.TestCase):
    def test_skips_app_already_installed_by_press(self):
        apps = {"frappe", "erpnext", "builder"}

        with patch.object(provisioner, "_docker") as docker:
            output = provisioner.ensure_app_installed(
                "store.dukani.ai", "erpnext", apps
            )

        docker.assert_not_called()
        self.assertEqual(output, "already installed by Press")

    def test_installs_missing_app_for_resumable_jobs(self):
        apps = {"frappe"}
        result = CompletedProcess([], 0, stdout="installed", stderr="")

        with patch.object(provisioner, "_docker", return_value=result) as docker:
            provisioner.ensure_app_installed(
                "store.dukani.ai", "erpnext", apps
            )

        docker.assert_called_once()
        self.assertIn("erpnext", apps)


if __name__ == "__main__":
    unittest.main()
