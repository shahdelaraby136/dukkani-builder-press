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


class FastTemplateTest(unittest.TestCase):
    def test_uses_existing_country_template(self):
        with patch.object(Path, "is_file", return_value=True):
            template = provisioner._fast_template("Egypt")

        self.assertEqual(template.name, "egypt.sql.gz")

    def test_falls_back_when_country_template_is_missing(self):
        with patch.object(Path, "is_file", return_value=False):
            template = provisioner._fast_template("Egypt")

        self.assertIsNone(template)

    def test_fast_restore_imports_migrates_and_resets_admin_password(self):
        ok = CompletedProcess([], 0, stdout="ok", stderr="")
        template = Path("egypt.sql.gz")

        with patch.object(provisioner, "_copy_into_container") as copy, patch.object(
            provisioner, "_docker", side_effect=[ok, ok, ok]
        ) as docker:
            provisioner._restore_fast_template(
                "store.dukani.ai", template, "generated-admin-secret"
            )

        copy.assert_called_once_with(
            template, "/tmp/dukkani-fast-template.sql.gz"
        )
        commands = [call.args[0] for call in docker.call_args_list]
        self.assertIn("mariadb", commands[0][-1])
        self.assertEqual(commands[1][-1], "migrate")
        self.assertEqual(commands[2][-2:], [
            "set-admin-password", "generated-admin-secret"
        ])


if __name__ == "__main__":
    unittest.main()
