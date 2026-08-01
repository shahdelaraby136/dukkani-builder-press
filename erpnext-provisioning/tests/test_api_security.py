import sys
import unittest
from pathlib import Path


API_DIR = Path(__file__).resolve().parents[1] / "api"
sys.path.insert(0, str(API_DIR))

from api_security import allowed_origin, public_tenant, public_tenants


class PublicTenantTest(unittest.TestCase):
    def test_sensitive_fields_are_not_exposed(self):
        record = {
            "subdomain": "shop",
            "status": "failed",
            "email": "owner@example.com",
            "error": "db_password=secret",
            "log_tail": "private output",
            "url": "https://shop.dukani.ai",
        }

        payload = public_tenant(record)

        self.assertEqual(payload["subdomain"], "shop")
        self.assertNotIn("email", payload)
        self.assertNotIn("error", payload)
        self.assertNotIn("log_tail", payload)
        self.assertNotIn("secret", repr(payload))

    def test_list_uses_same_public_projection(self):
        payload = public_tenants([{"subdomain": "one", "password": "secret"}])

        self.assertEqual(payload, [{"subdomain": "one"}])


class AllowedOriginTest(unittest.TestCase):
    def test_allows_central_and_tenant_https_origins(self):
        self.assertEqual(
            allowed_origin("https://dukani.ai", "dukani.ai"),
            "https://dukani.ai",
        )
        self.assertEqual(
            allowed_origin("https://shop.dukani.ai", "dukani.ai"),
            "https://shop.dukani.ai",
        )

    def test_rejects_untrusted_or_insecure_origins(self):
        self.assertIsNone(allowed_origin("https://evil.example", "dukani.ai"))
        self.assertIsNone(allowed_origin("http://dukani.ai", "dukani.ai"))
        self.assertIsNone(allowed_origin("https://dukani.ai.evil.example", "dukani.ai"))


if __name__ == "__main__":
    unittest.main()
