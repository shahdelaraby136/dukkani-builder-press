import unittest
from pathlib import Path


SHOPAPI_SOURCE = (
    Path(__file__).resolve().parents[1] / "api" / "shopapi.py"
).read_text(encoding="utf-8")


class CustomerSignupContractTest(unittest.TestCase):
    def test_duplicate_mobile_number_has_a_specific_message(self):
        self.assertIn(
            'frappe.db.exists("User", {"mobile_no": phone})',
            SHOPAPI_SOURCE,
        )
        self.assertIn("رقم الهاتف مرتبط بحساب آخر.", SHOPAPI_SOURCE)


if __name__ == "__main__":
    unittest.main()
